"""Automatic, snapshot-based inbound completion messages to the tenant operations group."""
import json
import uuid
from datetime import timedelta
from django.db import transaction
from django.db.models import Q
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
    return str(value or '').replace('<','＜').replace('>','＞')[:200]


def snapshot(inbound,actor):
    lines=list(inbound.lines.select_related('shipment_line'))
    expected=sum(l.expected_quantity for l in lines);received=sum(l.received_quantity for l in lines)
    rows=sorted(lines,key=lambda l:l.received_quantity==l.expected_quantity)[:15]
    detail='\n'.join(f"{safe_text(l.shipment_line.product_name_snapshot)} / {safe_text(l.shipment_line.sku_code_snapshot)} · 发货 {l.expected_quantity} · 实收 {l.received_quantity} · 差异 {l.received_quantity-l.expected_quantity:+d}" for l in rows)
    elements=[{'tag':'div','text':{'tag':'plain_text','content':f'入库单：{inbound.number}\n发运批次：{inbound.batch.number}\n目的仓：{inbound.warehouse.name}\n清点人：{actor.full_name or actor.username}\n完成时间：{timezone.localtime(inbound.confirmed_at).strftime("%Y-%m-%d %H:%M")}'}},
        {'tag':'div','text':{'tag':'plain_text','content':f'发货 {expected} 件 ｜ 实收 {received} 件 ｜ 差异 {received-expected:+d} 件'}},
        {'tag':'div','text':{'tag':'plain_text','content':detail or '无商品明细'}}]
    if len(lines)>15:elements.append({'tag':'note','elements':[{'tag':'plain_text','content':f'共 {len(lines)} 行，优先展示差异商品；完整清单请查看入库单。'}]})
    try:
        url=system_url(f'/supply-chain/logistics?inbound_id={inbound.pk}')
        elements.append({'tag':'action','actions':[{'tag':'button','text':{'tag':'plain_text','content':'查看入库单'},'url':url,'type':'primary'}]})
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
