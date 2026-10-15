"""Versioned carrier quotations, with explicit selection and frozen batch terms."""
from decimal import Decimal, ROUND_HALF_UP, localcontext
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import OuterRef, Subquery, Max, Q
from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError as APIValidationError
from rest_framework.response import Response
from apps.masterdata.models import CountrySiteMaster
from . import services
from .api import key, validated
from .archives import freight_scope
from .dates import business_date
from .models import BusinessEvent, FreightChannel, FreightQuote, domain_write
from .permissions import VIEW, MANAGE
from .views import InternalAPI


class ChannelInput(serializers.Serializer):
    company_id = serializers.IntegerField(min_value=1)
    country_id = serializers.IntegerField(min_value=1)
    code = serializers.SlugField(max_length=80)
    name = serializers.CharField(max_length=160)
    origin = serializers.CharField(max_length=160)
    cargo_type = serializers.CharField(max_length=80)
    transport_mode = serializers.ChoiceField(choices=['sea', 'air', 'road', 'rail', 'other'])
    notes = serializers.CharField(allow_blank=True, max_length=10000, default='')
    is_active = serializers.BooleanField(default=True)
    expected_version = serializers.IntegerField(min_value=1, required=False)


class QuoteInput(serializers.Serializer):
    expected_channel_version = serializers.IntegerField(min_value=1)
    effective_from = serializers.DateField()
    effective_to = serializers.DateField(allow_null=True, default=None)
    billing_basis = serializers.ChoiceField(choices=['cbm', 'container'])
    fee_per_cbm = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=0, allow_null=True, default=None)
    container_fee = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=0, allow_null=True, default=None)
    container_type = serializers.CharField(max_length=40, allow_blank=True, default='')
    tax_percent = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100, default=0)
    prices_include_tax = serializers.BooleanField(default=False)
    notes = serializers.CharField(allow_blank=True, max_length=10000, default='')
    reason = serializers.CharField(max_length=500)


def channel_scope(actor, permission=VIEW):
    return FreightChannel.objects.filter(tenant=actor.tenant, company__in=freight_scope(actor, permission)).select_related('company', 'country')


def current_quote(channel, day=None):
    # A later published applicable version replaces earlier ones. Expiration
    # never resurrects an older, open-ended price.
    quote = channel.quotes.filter(effective_from__lte=day or business_date()).order_by('-sequence').first()
    if quote and (not quote.effective_to or quote.effective_to >= (day or business_date())):
        return quote
    return None


def quote_data(quote):
    if not quote:
        return None
    return {'id': quote.pk, 'channel_id': quote.channel_id, 'sequence': quote.sequence,
            'effective_from': str(quote.effective_from), 'effective_to': str(quote.effective_to) if quote.effective_to else None,
            'billing_basis': quote.billing_basis, 'fee_per_cbm': str(quote.fee_per_cbm) if quote.fee_per_cbm is not None else None,
            'container_fee': str(quote.container_fee) if quote.container_fee is not None else None,
            'container_type': quote.container_type, 'tax_percent': str(quote.tax_percent),
            'prices_include_tax': quote.prices_include_tax, 'notes': quote.notes, 'reason': quote.reason,
            'created_at': quote.created_at}


def channel_data(channel, quote=None):
    return {'id': channel.pk, 'version': channel.version, 'company_id': channel.company_id,
            'company_name': channel.company.name, 'country_id': channel.country_id,
            'country_code': channel.country.country_code.upper(), 'country_name': channel.country.name,
            **{name: getattr(channel, name) for name in ('code', 'name', 'origin', 'cargo_type', 'transport_mode', 'notes', 'is_active')},
            'current_quote': quote_data(quote)}


def _replay(actor, model, action, request_key, payload, query):
    event = BusinessEvent.objects.filter(tenant=actor.tenant, aggregate_type=model, action=action, request_key=services._key(request_key)).first()
    if event:
        services._matching_replay(event, services.request_hash(payload))
        obj = query.filter(pk=event.aggregate_id).first()
        if obj is None:
            raise NotFound('记录不可访问。')
        return obj
    return None


@transaction.atomic
def save_channel(actor, payload, request_key, pk=None):
    services._internal(actor)
    services._tenant_lock(actor)
    body = {'id': pk, 'values': payload}
    query = channel_scope(actor, MANAGE)
    prior = _replay(actor, 'freightchannel', 'channel_saved', request_key, body, query)
    if prior:
        return prior
    company = freight_scope(actor, MANAGE).filter(pk=payload['company_id']).first()
    if company is None:
        raise NotFound('货运公司不可维护。')
    if payload.get('is_active', True) and not company.is_active:
        raise ValidationError('停用的货运公司不能启用运输渠道。')
    country = services._master(CountrySiteMaster, actor, payload['country_id'])
    if payload.get('is_active', True) and country.status != 'active':
        raise ValidationError('请选择启用的目的国家。')
    obj = query.filter(pk=pk).first() if pk else FreightChannel(tenant=actor.tenant, created_by=actor)
    if obj is None:
        raise NotFound('运输渠道不可访问。')
    if pk:
        services._version(obj, payload.get('expected_version'))
        if obj.company_id != company.pk:
            raise ValidationError('渠道所属货运公司不能改换，请在另一家公司新增渠道。')
        if obj.quotes.exists() and (obj.country_id != country.pk or any(getattr(obj, field) != payload[field] for field in ('code', 'origin', 'cargo_type', 'transport_mode'))):
            raise ValidationError('已发布报价的渠道不能改换线路、货物类型或运输方式，请新增渠道并发布报价。')
    with domain_write():
        for field in ('code', 'name', 'origin', 'cargo_type', 'transport_mode', 'notes', 'is_active'):
            setattr(obj, field, payload[field])
        obj.company, obj.country = company, country
        obj.version += 1 if pk else 0
        obj.save()
        services._event(actor, obj, 'channel_saved', request_key, body)
    return obj


@transaction.atomic
def publish_quote(actor, channel_id, payload, request_key):
    services._internal(actor)
    services._tenant_lock(actor)
    channel = channel_scope(actor, MANAGE).filter(pk=channel_id).first()
    if channel is None:
        raise NotFound('运输渠道不可维护。')
    body = {'channel_id': channel_id, 'values': payload}
    prior = _replay(actor, 'freightquote', 'quote_published', request_key, body,
                    FreightQuote.objects.filter(tenant=actor.tenant, channel=channel))
    if prior:
        return prior
    services._version(channel, payload['expected_channel_version'])
    if not channel.is_active or not channel.company.is_active or channel.country.status != 'active':
        raise ValidationError('请先启用货运公司、运输渠道及目的国家。')
    values = {key: value for key, value in payload.items() if key != 'expected_channel_version'}
    seq = (channel.quotes.aggregate(value=Max('sequence'))['value'] or 0) + 1
    with domain_write():
        obj = FreightQuote.objects.create(tenant=actor.tenant, created_by=actor, channel=channel, sequence=seq, **values)
        channel.version += 1
        channel.save()
        services._event(actor, obj, 'quote_published', request_key, body, audit={'sequence': seq})
    return obj


def batch_freight_values(actor, company, country_code, channel_id=None, quote_id=None):
    base = {'freight_company': company, 'freight_channel': None, 'freight_quote': None, 'freight_quote_snapshot': {},
            'shipping_marks_snapshot': company.shipping_marks,
            'fee_per_cbm_snapshot': company.fee_per_cbm, 'tax_percent_snapshot': company.tax_percent}
    if not channel_id:
        if quote_id:
            raise ValidationError('请先选择报价所属的运输渠道。')
        return base
    channel = channel_scope(actor, VIEW).filter(pk=channel_id, company=company, is_active=True).first()
    if channel is None or channel.country.country_code.upper() != country_code or channel.country.status != 'active':
        raise ValidationError('运输渠道必须属于所选货运公司及目的国家，且处于启用状态。')
    quote = current_quote(channel)
    if not quote or quote.pk != quote_id:
        raise ValidationError('有效报价版本已变化或已过期，请刷新渠道报价后重新选择。')
    snapshot = {**channel_data(channel, quote), 'quote': quote_data(quote)}
    snapshot.pop('current_quote', None)
    # JSON snapshots contain plain dates/decimals, never model references.
    snapshot['quote'].pop('created_at', None)
    base.update(freight_channel=channel, freight_quote=quote, freight_quote_snapshot=snapshot,
                fee_per_cbm_snapshot=quote.fee_per_cbm if quote.billing_basis == 'cbm' else None,
                tax_percent_snapshot=quote.tax_percent)
    return base


def freight_reference(batch, chargeable_cbm=None):
    snapshot = batch.freight_quote_snapshot or {}
    quote = snapshot.get('quote')
    if not quote:
        return None
    basis = quote['billing_basis']
    quantity = Decimal(batch.container_count) if basis == 'container' else (Decimal(str(chargeable_cbm)) if chargeable_cbm is not None else None)
    unit = quote['container_fee'] if basis == 'container' else quote['fee_per_cbm']
    with localcontext() as ctx:
        ctx.prec = 60
        amount = Decimal(unit) * quantity if unit is not None and quantity is not None else None
        if amount is not None and not quote.get('prices_include_tax'):
            amount *= 1 + Decimal(quote['tax_percent']) / 100
        amount_text = str(amount.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)) if amount is not None else None
    return {'channel_name': snapshot['name'], 'quote_sequence': quote['sequence'], 'billing_basis': basis,
            'quantity': str(quantity) if quantity is not None else None, 'unit_price': unit,
            'container_type': quote['container_type'], 'tax_percent': quote['tax_percent'],
            'prices_include_tax': quote['prices_include_tax'],
            'reference_amount': amount_text}


class Channels(InternalAPI):
    def get(self, request):
        query = channel_scope(request.user)
        for field in ('company_id', 'country_id'):
            value = request.query_params.get(field)
            if value:
                if not str(value).isdigit():
                    raise APIValidationError('筛选条件无效。')
                query = query.filter(**{field: value})
        if request.query_params.get('country_code'):
            query = query.filter(country__country_code__iexact=request.query_params['country_code'])
        if request.query_params.get('active') == 'true':
            query = query.filter(is_active=True, company__is_active=True, country__status='active')
        term = request.query_params.get('search', '').strip()
        if term:
            query = query.filter(Q(code__icontains=term) | Q(name__icontains=term) | Q(origin__icontains=term))
        try:
            limit, offset = int(request.query_params.get('limit', 20)), int(request.query_params.get('offset', 0))
        except (ValueError, TypeError):
            raise APIValidationError('分页条件无效。')
        if not 1 <= limit <= 100 or offset < 0:
            raise APIValidationError('分页条件无效。')
        current = FreightQuote.objects.filter(channel_id=OuterRef('pk'), effective_from__lte=business_date()).order_by('-sequence')
        page = list(query.annotate(current_id=Subquery(current.values('pk')[:1])).order_by('-id')[offset:offset + limit])
        quotes = FreightQuote.objects.in_bulk([row.current_id for row in page if row.current_id])
        result = []
        for row in page:
            quote = quotes.get(row.current_id)
            if quote and quote.effective_to and quote.effective_to < business_date():
                quote = None
            result.append(channel_data(row, quote))
        return Response({'data': result, 'count': query.count(), 'limit': limit, 'offset': offset, 'business_date': business_date().isoformat()})

    def post(self, request):
        obj = save_channel(request.user, validated(ChannelInput, request), key(request))
        return Response({'data': channel_data(obj, current_quote(obj))}, status=201)


class ChannelDetail(InternalAPI):
    def patch(self, request, pk):
        obj = save_channel(request.user, validated(ChannelInput, request), key(request), pk=pk)
        return Response({'data': channel_data(obj, current_quote(obj))})


class Quotes(InternalAPI):
    def get(self, request, pk):
        channel = channel_scope(request.user).filter(pk=pk).first()
        if channel is None:
            raise NotFound('运输渠道不可访问。')
        from .views import _page
        return _page(request, channel.quotes.all(), quote_data)

    def post(self, request, pk):
        obj = publish_quote(request.user, pk, validated(QuoteInput, request), key(request))
        return Response({'data': quote_data(obj), 'channel': channel_data(obj.channel, current_quote(obj.channel))}, status=201)
