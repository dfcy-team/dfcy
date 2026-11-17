"""Automatic, snapshot-based inbound completion messages to the tenant operations group."""
import json
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


MAX_INBOUND_DETAIL_ROWS = 15
MAX_TRANSIT_STYLE_ROWS = 20
MAX_CARD_TEXT_FIELD_CHARS = 48


def _transit_styles(inbound, limit=None):
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
    total = rows.count()
    ordered_rows = rows.order_by(
        'shipment_line__sku__spu__product_name',
        'shipment_line__sku__spu__spu_code',
        'shipment_line__sku__spu_id',
    )
    if limit is not None:
        ordered_rows = ordered_rows[:limit]
    return list(ordered_rows), total


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
    country = CountrySiteMaster.objects.filter(
        tenant_id=inbound.tenant_id, country_code=inbound.batch.country_code_snapshot
    ).first()
    return {
        'inbound': {
            'id': inbound.pk,
            'number': inbound.number,
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
            'spu_code': row['shipment_line__sku__spu__spu_code'],
            'legacy_spu_code': row['shipment_line__sku__spu__legacy_spu_code'] or '未维护',
        } for row in transit_rows],
        'transit_style_total': transit_total,
        'preview_as_of': timezone.now().isoformat(),
    }


def snapshot(inbound, actor):
    data = notice_detail_data(
        inbound, line_limit=MAX_INBOUND_DETAIL_ROWS, transit_limit=MAX_TRANSIT_STYLE_ROWS
    )
    inbound_data = data['inbound']
    summary = data['summary']
    rows = [
        f"{safe_text(line['product_name'])} / {safe_text(line['sku_code'])}（旧SKU：{safe_text(line['legacy_sku_code'])}） · "
        + (f"额外实收 {line['received_quantity']}" if line['is_extra'] else
           f"发货 {line['expected_quantity']} · 实收 {line['received_quantity']} · 差异 {line['difference']:+d}")
        for line in data['lines']
    ]
    detail='\n'.join(rows)
    elements=[{'tag':'div','text':{'tag':'plain_text','content':f'入库单：{inbound.number}\n发运批次：{inbound.batch.number}\n目的仓：{inbound.warehouse.name}\n完成时间：{timezone.localtime(inbound.confirmed_at).strftime("%Y-%m-%d %H:%M")}'}},
        {'tag':'div','text':{'tag':'plain_text','content':f'发货 {summary["expected_quantity"]} 件 ｜ 实收 {summary["received_quantity"]} 件 ｜ 差异 {summary["difference_quantity"]:+d} 件'}},
        {'tag':'div','text':{'tag':'plain_text','content':detail or '无商品明细'}}]
    if data['line_total']>MAX_INBOUND_DETAIL_ROWS:elements.append({'tag':'note','elements':[{'tag':'plain_text','content':f'共 {data["line_total"]} 行，优先展示差异商品；完整清单请查看到货明细。'}]})
    transit_lines=[f"{safe_text(row['product_name']) or '未命名款式'} / 新SPU：{safe_text(row['spu_code'])} / 旧SPU：{safe_text(row['legacy_spu_code'])}" for row in data['transit_styles']]
    transit_count=data['transit_style_total']
    if transit_count>MAX_TRANSIT_STYLE_ROWS:
        transit_lines.append(f'另有 {transit_count-MAX_TRANSIT_STYLE_ROWS} 个款式未展示。')
    elements.append({'tag':'div','text':{'tag':'plain_text','content':'同目的国家在途款式预告：\n'+('\n'.join(transit_lines) if transit_lines else '暂无在途款式。')}})
    try:
        url=system_url(f'/inbound-notices/{inbound.pk}')
        elements.append({'tag':'action','actions':[{'tag':'button','text':{'tag':'plain_text','content':'查看到货明细与预告'},'url':url,'type':'primary'}]})
    except ValidationError:pass
    country=CountrySiteMaster.objects.filter(tenant_id=inbound.tenant_id,country_code=inbound.batch.country_code_snapshot).first()
    country_label=country.name if country else inbound.batch.country_code_snapshot
    return {'header':{'title':{'tag':'plain_text','content':f'{country_label} · 入库清点完成'},'template':'purple'},'elements':elements}


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
            receipt=GroupMessageService().send_group(connection,row.chat_id,row.payload,row.event_key)
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
