"""Incremental daily refresh of received supply-chain batch costs."""
import hashlib
import json

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef

from . import costs
from .cost_models import CostEntry, CostVersion
from .models import DispatchBatch, InboundOrder
from .monthly_payment_gate import payment_state
from .models import domain_write
from .services import _internal

COST_RULE_VERSION = "monthly-v4-fees-recorded-1"
PAYMENT_AUDIT_RULE_VERSION = "monthly-v4-payment-audit-1"
DEFAULT_BATCH_LIMIT = 100
MAX_BATCH_LIMIT = 500


def _persist_payment_snapshot(actor, batch, payment, previous):
    """Append a trace-only version when observed payment state changes."""
    if previous is None:
        return False
    snapshot = json.dumps(payment, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)
    fingerprint = hashlib.sha256(snapshot.encode('utf-8')).hexdigest()
    summary = dict(previous.summary or {})
    old = summary.get('payment_audit') or {}
    if old.get('fingerprint') == fingerprint and old.get('rule_version') == PAYMENT_AUDIT_RULE_VERSION:
        return False
    issues = [value for value in previous.issues if not str(value).startswith('每日批次增量计算暂估')]
    confirmation = bool(payment.get('ready') and not issues)
    summary['payment_audit'] = {'fingerprint': fingerprint, 'rule_version': PAYMENT_AUDIT_RULE_VERSION,
                                'snapshot': payment, 'confirmation_state': 'confirmed' if confirmation else 'estimated'}
    key = f'{COST_RULE_VERSION}-{PAYMENT_AUDIT_RULE_VERSION}-{batch.pk}-{fingerprint[:24]}-{previous.sequence + 1}'
    digest = hashlib.sha256(key.encode('utf-8')).hexdigest()
    with transaction.atomic(), domain_write():
        DispatchBatch.objects.select_for_update().get(pk=batch.pk)
        latest = CostVersion.objects.filter(batch=batch, tenant=actor.tenant).order_by("-sequence").first()
        if latest.pk != previous.pk:
            return _persist_payment_snapshot(actor, batch, payment, latest)
        version = CostVersion.objects.create(tenant=actor.tenant, created_by=previous.created_by, batch=batch,
            sequence=previous.sequence + 1, state="confirmed" if confirmation else "estimated", stage=previous.stage,
            input_fingerprint=previous.input_fingerprint, source_snapshot=previous.source_snapshot,
            summary=summary, issues=issues, creation_key=key, request_hash=digest)
        for row in previous.entries.all():
            CostEntry.objects.create(tenant=actor.tenant, created_by=previous.created_by,
                cost_version=version, shipment_line=row.shipment_line,
                receipt_line=row.receipt_line, quantity=row.quantity,
                received_quantity=row.received_quantity, goods_tax_amount=row.goods_tax_amount,
                goods_amount=row.goods_amount, collection_fee=row.collection_fee,
                freight_fee=row.freight_fee, clearance_fee=row.clearance_fee,
                received_goods_amount=row.received_goods_amount,
                received_collection_fee=row.received_collection_fee,
                received_freight_fee=row.received_freight_fee, shipped_total=row.shipped_total,
                received_total=row.received_total, pending_total=row.pending_total,
                shipped_unit_cost=row.shipped_unit_cost, received_unit_cost=row.received_unit_cost)
    return True


def run_daily_batch_costs(actor, *, limit=DEFAULT_BATCH_LIMIT, after_id=0):
    """Refresh changed batches with confirmed receipts, isolating row errors.

    The actor must be a valid internal tenant actor accepted by costs.calculate.
    This job only creates estimates. Payment balances gate unknown goods and
    are returned for consumers; this job never posts payments or publishes
    confirmed product costs.
    """
    if getattr(settings, 'SUPPLY_MONTHLY_COST_JOBS_ENABLED', False) is not True:
        return {'status': 'disabled', 'processed': 0, 'skipped': 0, 'errors': [],
                'payment_reconciliation': 'enabled'}
    _internal(actor)
    limit = max(1, min(int(limit), MAX_BATCH_LIMIT))
    after_id = max(0, int(after_id))
    confirmed = InboundOrder.objects.filter(batch_id=OuterRef('pk'), status='confirmed')
    base = DispatchBatch.objects.filter(tenant_id=actor.tenant_id, status='active', pk__gt=after_id).annotate(
        has_confirmed_inbound=Exists(confirmed)).filter(has_confirmed_inbound=True).order_by('pk')
    batches = list(base[:limit + 1])
    has_more = len(batches) > limit
    batches = batches[:limit]
    processed = skipped = 0
    errors = []
    payment_results = []
    for batch in batches:
        try:
            payment = payment_state(actor, batch)
            payment_results.append({'batch_id': batch.pk, **payment})
            previous = CostVersion.objects.filter(tenant_id=actor.tenant_id, batch_id=batch.pk).order_by('-sequence').first()
            _persist_payment_snapshot(actor, batch, payment, previous)
            if previous:
                previous = CostVersion.objects.filter(tenant_id=actor.tenant_id, batch_id=batch.pk).order_by('-sequence').first()
            if payment['goods']['state'] == 'unknown':
                skipped += 1
                continue
            source, fingerprint, _, _, _, _ = costs.inputs('batch', batch)
            if previous and previous.input_fingerprint == fingerprint and COST_RULE_VERSION in (previous.creation_key or ""):
                skipped += 1
                continue
            payload = {'expected_source_version': batch.version,
                       'expected_input_fingerprint': fingerprint}
            calculated = costs.calculate(actor, 'batch', batch.pk, payload,
                            f'{COST_RULE_VERSION}-{batch.pk}-{fingerprint[:32]}',
                            automatic_reason='每日批次增量计算暂估；付款状态仅作门禁信息，不发布正式产品成本。')
            _persist_payment_snapshot(actor, batch, payment, calculated)
            processed += 1
        except Exception as exc:  # one invalid batch must not stop the daily run
            errors.append({'batch_id': batch.pk, 'error': f'{type(exc).__name__}: {exc}'[:500]})
    return {'status': 'completed', 'processed': processed, 'skipped': skipped,
            'errors': errors, 'limit': limit,
            'next_cursor': batches[-1].pk if batches else after_id,
            'has_more': has_more,
            'payment_reconciliation': 'checked', 'payment_results': payment_results}
