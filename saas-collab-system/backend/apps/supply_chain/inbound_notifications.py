"""Automatic, snapshot-based inbound completion messages to the tenant operations group."""
import json
from collections import defaultdict
from hashlib import sha256
from time import monotonic
import uuid
from datetime import timedelta
from django.db import transaction
from django.db.models import Q, Case, When, IntegerField, Sum, F
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from apps.permissions.models import DataScope
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.purchasing.supply_permissions import require_internal_supply_permission
from apps.masterdata.models import CountrySiteMaster
from apps.integrations.models import FeishuConnection
from apps.integrations.feishu_delivery import FeishuMessageService, system_url
from .inbound_notify_models import InboundNotificationConfig as Config, InboundNotificationOutbox as Outbox
from .permissions import VIEW, MANAGE
from .views import InternalAPI
from . import services


def can_manage(actor):
    return bool(check_user_permission(actor, MANAGE) and check_user_permission(actor,'feishu.notification.manage') and
        any(s['scope_type']==DataScope.ScopeType.ALL for s in get_permission_data_scopes(actor,MANAGE)))


def config_data(actor):
    row=Config.objects.filter(tenant_id=actor.tenant_id).first()
    return {'chat_id':row.chat_id if row else '', 'chat_name':row.chat_name if row else '',
        'country_codes':row.country_codes if row else [],'all_countries':row.all_countries if row else False,
        'enabled':row.enabled if row else False,'version':row.version if row else 0,'can_manage':can_manage(actor)}


class ConfigInput(serializers.Serializer):
    chat_id=serializers.RegexField(r'^oc_[A-Za-z0-9_-]+$',max_length=191,allow_blank=True)
    chat_name=serializers.CharField(max_length=191,allow_blank=True)
    country_codes=serializers.ListField(child=serializers.CharField(max_length=8),max_length=100)
    all_countries=serializers.BooleanField(default=False)
    enabled=serializers.BooleanField()
    expected_version=serializers.IntegerField(min_value=0)


class ConfigAPI(InternalAPI):
    def get(self,request):
        require_internal_supply_permission(request.user,VIEW)
        return Response({'data':config_data(request.user)})

    @transaction.atomic
    def put(self,request):
        actor=request.user
        require_internal_supply_permission(actor,MANAGE)
        if not can_manage(actor): raise PermissionDenied('需全部数据范围的供应链维护及飞书通知管理权限。')
        services._tenant_lock(actor)
        data=ConfigInput(data=request.data);data.is_valid(raise_exception=True);p=data.validated_data
        row=Config.objects.select_for_update().filter(tenant_id=actor.tenant_id).first()
        if p.pop('expected_version') != (row.version if row else 0): raise ValidationError('配置已变化，请刷新后重试。')
        codes=sorted(set(p['country_codes']))
        known=set(CountrySiteMaster.objects.filter(tenant_id=actor.tenant_id).values_list('country_code',flat=True))
        if set(codes)-known: raise ValidationError('通知国家必须来自当前系统国家档案。')
        if p['enabled'] and (not p['chat_id'] or not p['chat_name'] or (not p['all_countries'] and not codes)):
            raise ValidationError('启用前请填写接收群并选择通知国家。')
        if p['enabled'] and not FeishuConnection.objects.filter(tenant_id=actor.tenant_id,enabled=True).exclude(app_secret_ref='').exists():
            raise ValidationError('请先配置并启用飞书应用连接。')
        p['country_codes']=codes
        if row:
            for k,v in p.items():setattr(row,k,v)
            row.version+=1;row.updated_by=actor;row.save()
        else: Config.objects.create(tenant_id=actor.tenant_id,updated_by=actor,**p)
        return Response({'data':config_data(actor)})


def safe_text(value):
    # Feishu markdown is not needed for business-provided names.
    return str(value or '').replace('<','＜').replace('>','＞')[:MAX_CARD_TEXT_FIELD_CHARS]


MAX_INBOUND_DETAIL_ROWS = 10
MAX_CARD_TEXT_FIELD_CHARS = 48


def _transit_styles(inbound, limit=None, spu_id=None):
    """Return stable SPUs in active same-country transit batches."""
    from .models import DispatchAllocation

    rows = DispatchAllocation.objects.filter(
        tenant_id=inbound.tenant_id,
        membership__tenant_id=inbound.tenant_id,
        membership__active_guard=True,
        membership__batch__tenant_id=inbound.tenant_id,
        membership__batch__country_code_snapshot=inbound.batch.country_code_snapshot,
        membership__batch__status='active',
        membership__batch__stage__in=('departed', 'arrived_port'),
        shipment_line__tenant_id=inbound.tenant_id,
        shipment_line__is_active=True,
        shipment_line__sku__tenant_id=inbound.tenant_id,
        shipment_line__sku__spu__tenant_id=inbound.tenant_id,
    ).exclude(membership__batch_id=inbound.batch_id).order_by().values(
        'shipment_line__sku__spu_id',
        'shipment_line__sku__spu__product_name',
        'shipment_line__sku__spu__spu_code',
        'shipment_line__sku__spu__legacy_spu_code',
    ).distinct()
    if spu_id is not None:
        rows = rows.filter(shipment_line__sku__spu_id=spu_id)
    total = rows.count()
    ordered_rows = rows.order_by(
        'shipment_line__sku__spu__product_name',
        'shipment_line__sku__spu__spu_code',
        'shipment_line__sku__spu_id',
    )
    if limit is not None:
        ordered_rows = ordered_rows[:limit]
    return list(ordered_rows), total


def _sku_fields(sku):
    from .supplier_products import safe_image_url
    return {
        'spu_id': sku.spu_id,
        'spu_name': sku.spu.product_name,
        'spu_code': sku.spu.spu_code,
        'legacy_spu_code': sku.spu.legacy_spu_code or '未维护',
        'image_sku_id': sku.pk if safe_image_url(sku.image_url, sku.tenant_id) else None,
    }


def _transit_images(inbound, spu_ids):
    from apps.products.models import ProductSKU
    from .supplier_products import safe_image_url
    choices = defaultdict(lambda: ([], []))
    for sku in ProductSKU.objects.filter(
        tenant_id=inbound.tenant_id, spu_id__in=spu_ids,
    ).exclude(image_url__isnull=True).exclude(image_url='').only('id', 'spu_id', 'image_url', 'is_active').order_by('pk'):
        if safe_image_url(sku.image_url, inbound.tenant_id):
            choices[sku.spu_id][0 if sku.is_active else 1].append(sku.pk)
    result = {}
    for spu_id, (active, archived) in choices.items():
        ids = active or archived
        # Stable random choice per notification, so a refresh does not reshuffle photos.
        seed = sha256(f'{inbound.tenant_id}:{inbound.pk}:{spu_id}'.encode()).digest()
        result[spu_id] = ids[int.from_bytes(seed[:8], 'big') % len(ids)]
    return result


def notice_detail_data(inbound, *, line_limit=None, transit_limit=None):
    """Build read-only inbound detail data; limits are only for compact message previews."""
    lines = inbound.lines.all()
    extras = inbound.extra_lines.filter(is_active=True)
    standard_totals = lines.aggregate(expected=Sum('expected_quantity'), received=Sum('received_quantity'))
    extra_totals = extras.aggregate(received=Sum('received_quantity'))
    expected = standard_totals['expected'] or 0
    received = (standard_totals['received'] or 0) + (extra_totals['received'] or 0)
    standard_total = lines.count()
    extra_total = extras.count()
    line_total = standard_total + extra_total

    ordered_lines = lines.select_related('shipment_line__sku__spu').annotate(
        _match_order=Case(When(received_quantity=F('expected_quantity'), then=1), default=0, output_field=IntegerField())
    ).order_by('_match_order', 'pk')
    ordered_extras = extras.select_related('sku__spu').order_by('pk')
    if line_limit is not None:
        standard_limit = min(standard_total, line_limit)
        ordered_lines = ordered_lines[:standard_limit]
        ordered_extras = ordered_extras[:min(extra_total, line_limit)]
    combined_rows = []
    for line in ordered_lines:
        source = line.shipment_line
        combined_rows.append((0, line.pk, {
            'product_name': source.product_name_snapshot or '',
            **_sku_fields(source.sku),
            'sku_code': source.sku_code_snapshot,
            'legacy_sku_code': source.sku.legacy_sku_code or '未维护',
            'expected_quantity': line.expected_quantity,
            'received_quantity': line.received_quantity,
            'difference': line.received_quantity - line.expected_quantity,
            'is_extra': False,
        }))
    for line in ordered_extras:
        combined_rows.append((1, line.pk, {
            'product_name': line.product_name_snapshot or '',
            **_sku_fields(line.sku),
            'sku_code': line.sku_code_snapshot,
            'legacy_sku_code': line.legacy_sku_code_snapshot or line.sku.legacy_sku_code or '未维护',
            'expected_quantity': 0,
            'received_quantity': line.received_quantity,
            'difference': line.received_quantity,
            'is_extra': True,
        }))
    combined_rows.sort(key=lambda item: (item[2]['difference'] == 0, item[0], item[1]))
    if line_limit is not None:
        combined_rows = combined_rows[:line_limit]
    line_rows = [row for _, _, row in combined_rows]

    transit_rows, transit_total = _transit_styles(inbound, limit=transit_limit)
    transit_images = _transit_images(inbound, [row['shipment_line__sku__spu_id'] for row in transit_rows])
    country = CountrySiteMaster.objects.filter(
        tenant_id=inbound.tenant_id, country_code=inbound.batch.country_code_snapshot
    ).first()
    return {
        'inbound': {
            'id': inbound.pk,
            'number': inbound.number,
            'receipt_mode': inbound.receipt_mode,
            'batch_number': inbound.batch.number,
            'warehouse_name': inbound.warehouse.name,
            'country_code': inbound.batch.country_code_snapshot,
            'country_name': country.name if country else inbound.batch.country_code_snapshot,
            'confirmed_at': timezone.localtime(inbound.confirmed_at).isoformat(timespec='minutes'),
        },
        'summary': {
            'expected_quantity': expected,
            'received_quantity': received,
            'difference_quantity': received - expected,
        },
        'lines': line_rows,
        'line_total': line_total,
        'transit_styles': [{
            'product_name': row['shipment_line__sku__spu__product_name'] or '',
            'image_sku_id': transit_images.get(row['shipment_line__sku__spu_id']),
            'spu_code': row['shipment_line__sku__spu__spu_code'],
            'legacy_spu_code': row['shipment_line__sku__spu__legacy_spu_code'] or '未维护',
        } for row in transit_rows],
        'transit_style_total': transit_total,
        'preview_as_of': timezone.now().isoformat(),
    }


def _plain(content):
    return {'tag': 'plain_text', 'content': content}


def _style_text(name, row):
    return (f"{safe_text(name) or '未命名款式'}\n"
            f"新SPU {safe_text(row['spu_code'])} · 旧SPU {safe_text(row['legacy_spu_code'])}")


def snapshot(inbound, actor):
    data = notice_detail_data(inbound, transit_limit=0)
    received = {}
    for row in data['lines']:
        quantity = row['received_quantity'] or 0
        if quantity <= 0:
            continue
        style = received.setdefault(row['spu_id'], {**row, 'received_total': 0})
        style['received_total'] += quantity
        if not style['image_sku_id']:
            style['image_sku_id'] = row['image_sku_id']
    styles = sorted(received.values(), key=lambda row: (-row['received_total'], row['spu_code'], row['spu_id']))
    header = data['inbound']
    elements = []
    image_rows = {}

    def add(text, sku_id=None):
        if sku_id:
            image_rows[str(len(elements))] = sku_id
        elements.append({'tag': 'div', 'text': _plain(text)})

    add(f"入库单：{header['number']}\n发运批次：{header['batch_number']}\n"
        f"目的仓：{header['warehouse_name']}\n完成时间：{timezone.localtime(inbound.confirmed_at):%Y-%m-%d %H:%M}")
    add(f"到货款式 · 实收合计 {data['summary']['received_quantity']} 件")
    for row in styles[:MAX_INBOUND_DETAIL_ROWS]:
        add(f"{_style_text(row['spu_name'], row)} · 实收 {row['received_total']} 件", row['image_sku_id'])
    if not styles:
        add('暂无实收到货款式。')
    if len(styles) > MAX_INBOUND_DETAIL_ROWS:
        add(f'另有 {len(styles) - MAX_INBOUND_DETAIL_ROWS} 款到货，详见明细。')
    try:
        url = system_url(f'/inbound-notices/{inbound.pk}')
        elements.append({'tag': 'action', 'actions': [
            {'tag': 'button', 'text': _plain('查看到货明细与预告'), 'url': url, 'type': 'primary'},
        ]})
    except ValidationError:
        pass
    payload = {'header': {'title': _plain(f"{header['country_name']} · 入库清点完成"),
                         'template': 'purple'}, 'elements': elements}
    if image_rows:
        payload['_image_rows'] = image_rows
    return payload


def _resolve_card_images(payload, tenant_id, service, connection):
    """Upload thumbnails outside the receipt transaction and freeze the resulting card."""
    from io import BytesIO
    from PIL import Image
    from billiard.exceptions import SoftTimeLimitExceeded
    from apps.products.models import ProductSKU
    from .supplier_product_images import load_product_images
    from .supplier_products import safe_image_url

    card = dict(payload)
    rows = card.pop('_image_rows', {})
    if not rows:
        return card
    deadline = monotonic() + 45
    try:
        skus = ProductSKU.objects.filter(tenant_id=tenant_id, pk__in=set(rows.values()))
        images = load_product_images({'lines': [
            {'sku_id': sku.pk, 'product_details': {'image_url': safe_image_url(sku.image_url, tenant_id)}}
            for sku in skus
        ]}, tenant_id)
    except SoftTimeLimitExceeded:
        raise
    except Exception:
        return card
    keys = {}
    for sku_id in dict.fromkeys(rows.values()):
        body = images.get(sku_id, {}).get('body')
        if not body or monotonic() >= deadline:
            continue
        try:
            with Image.open(BytesIO(body)) as image:
                buffer = BytesIO()
                image.save(buffer, format='PNG')
            keys[sku_id] = service.upload_image(connection, buffer.getvalue())
        except SoftTimeLimitExceeded:
            raise
        except Exception:
            continue
    elements = []
    for index, element in enumerate(card['elements']):
        key = keys.get(rows.get(str(index)))
        if key:
            element = {**element, 'extra': {'tag': 'img', 'img_key': key,
                                           'alt': _plain('商品图片')}}
        elements.append(element)
    card['elements'] = elements
    return card


def prepare(inbound,actor):
    cfg=Config.objects.filter(tenant_id=inbound.tenant_id).first()
    connection=FeishuConnection.objects.filter(tenant_id=inbound.tenant_id,enabled=True).first()
    code=inbound.batch.country_code_snapshot
    matched=bool(cfg and cfg.enabled and (cfg.all_countries or code in cfg.country_codes))
    return Outbox.objects.get_or_create(tenant_id=inbound.tenant_id,inbound=inbound,defaults={
        'event_key':str(uuid.uuid4()),'chat_id':cfg.chat_id if matched else '',
        'chat_name':cfg.chat_name if matched else '', 'country_code':code,
        'app_id':connection.app_id if connection else '', 'app_domain':connection.domain if connection else '',
        'payload':snapshot(inbound,actor),'status':'pending' if matched else 'skipped',
        'error_code':'' if matched else 'notification_not_enabled_or_country_unmatched'})[0]


class GroupMessageService(FeishuMessageService):
    def send_group(self,connection,chat_id,payload,key):
        token=self._tenant_token(connection)
        response=self.http.request('POST',self.base(connection)+'/open-apis/im/v1/messages?receive_id_type=chat_id',
            headers={'Authorization':f'Bearer {token}'},json_body={'receive_id':chat_id,'msg_type':'interactive',
            'content':json.dumps(payload,ensure_ascii=False),'uuid':key},retry=False,diagnostic_platform='feishu')
        result=self._payload(response,'飞书群消息发送失败。')
        message_id=(result.get('data') or {}).get('message_id')
        if not message_id:raise ValidationError('飞书未返回消息编号。')
        return message_id


def dispatch_due(limit=20):
    now=timezone.now()
    ids=list(Outbox.objects.filter(status='pending',next_attempt_at__lte=now).filter(Q(lease_until__isnull=True)|Q(lease_until__lte=now)).values_list('pk',flat=True)[:limit])
    sent=0
    for pk in ids:
        with transaction.atomic():
            row=Outbox.objects.select_for_update().get(pk=pk)
            now=timezone.now()
            if row.status!='pending' or row.next_attempt_at>now or (row.lease_until and row.lease_until>now):continue
            # Uncertain deliveries are retried within Feishu's UUID deduplication window only.
            if row.attempts and now-row.created_at>timedelta(minutes=30):
                row.status='needs_review';row.error_code='delivery_result_requires_review';row.save();continue
            cfg=Config.objects.filter(tenant_id=row.tenant_id).first()
            if not cfg or not cfg.enabled or cfg.chat_id!=row.chat_id or not (cfg.all_countries or row.country_code in cfg.country_codes):
                row.status='skipped';row.error_code='configuration_changed';row.save();continue
            row.attempts+=1;row.lease_until=now+timedelta(minutes=2);row.save()
        try:
            connection=FeishuConnection.objects.filter(tenant_id=row.tenant_id,enabled=True).first()
            if not connection or connection.app_id!=row.app_id or connection.domain!=row.app_domain:
                Outbox.objects.filter(pk=pk,status='pending').update(status='needs_review',lease_until=None,error_code='application_changed')
                continue
            service = GroupMessageService()
            payload = row.payload
            if '_image_rows' in payload:
                payload = _resolve_card_images(payload, row.tenant_id, service, connection)
                updated = Outbox.objects.filter(pk=pk, status='pending', attempts=row.attempts).update(payload=payload)
                if not updated:
                    continue
            receipt = service.send_group(connection, row.chat_id, payload, row.event_key)
        except Exception:
            # Never persist secrets or raw provider responses in UI errors.
            Outbox.objects.filter(pk=pk,status='pending').update(lease_until=None,next_attempt_at=timezone.now()+timedelta(seconds=60),error_code='delivery_failed_retrying')
        else:
            Outbox.objects.filter(pk=pk,status='pending').update(status='sent',receipt_id=receipt,sent_at=timezone.now(),lease_until=None,error_code='')
            sent+=1
    return sent


class StatusAPI(InternalAPI):
    def get(self,request,pk):
        from .logistics import inbound_for
        inbound=inbound_for(request.user,pk,VIEW)
        rows=Outbox.objects.filter(tenant_id=request.user.tenant_id,inbound=inbound)
        return Response({'data':list(rows.values('id','status','chat_name','country_code','created_at','sent_at','receipt_id','error_code','attempts'))})
