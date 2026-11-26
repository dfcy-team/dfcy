"""Incremental daily refresh of received supply-chain batch costs."""
from django.conf import settings
from django.db.models import Exists, OuterRef

from . import costs
from .cost_models import CostVersion
from .models import DispatchBatch, InboundOrder
from .monthly_payment_gate import payment_state
from .services import _internal

COST_RULE_VERSION = "monthly-v4-fees-recorded-1"
DEFAULT_BATCH_LIMIT = 100
MAX_BATCH_LIMIT = 500


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
            if payment['goods']['state'] == 'unknown':
                skipped += 1
                continue
            source, fingerprint, _, _, _, _ = costs.inputs('batch', batch)
            previous = CostVersion.objects.filter(tenant_id=actor.tenant_id, batch_id=batch.pk).order_by('-sequence').first()
            if previous and previous.input_fingerprint == fingerprint and COST_RULE_VERSION in (previous.creation_key or ""):
                skipped += 1
                continue
            payload = {'expected_source_version': batch.version,
                       'expected_input_fingerprint': fingerprint}
            costs.calculate(actor, 'batch', batch.pk, payload,
                            f'{COST_RULE_VERSION}-{batch.pk}-{fingerprint[:32]}',
                            automatic_reason='每日批次增量计算暂估；付款状态仅作门禁信息，不发布正式产品成本。')
            processed += 1
        except Exception as exc:  # one invalid batch must not stop the daily run
            errors.append({'batch_id': batch.pk, 'error': f'{type(exc).__name__}: {exc}'[:500]})
    return {'status': 'completed', 'processed': processed, 'skipped': skipped,
            'errors': errors, 'limit': limit,
            'next_cursor': batches[-1].pk if batches else after_id,
            'has_more': has_more,
            'payment_reconciliation': 'checked', 'payment_results': payment_results}
