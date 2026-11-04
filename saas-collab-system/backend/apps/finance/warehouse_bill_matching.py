"""Local-only bill matching. Never call a platform or an external database."""
import re
from collections import defaultdict

from django.db.models import Q

from apps.commerce.models import SalesOrder, ShipmentRecord
from apps.integrations.models import SyncRawEnvelope
from apps.integrations.raw_services import payload_digest


MATCH_ERRORS = {
    'missing_order': '本地未找到销售订单，请补齐本地订单后重新匹配',
    'missing_tracking': '预约单缺少完整运单号，请核对原账单物流明细',
    'tracking_unmatched': '未找到本地运单与销售订单关联，请补齐本地物流数据',
    'ambiguous': '匹配到多个实际订单，请核对，未自动选择或分摊',
    'temu_unintegrated': 'Temu订单尚未关联本地销售订单，不转为国家其他处理费',
    'manual_pending': '疑似手工单，请核实手工单证据并明确确认系统店铺',
    'manual_confirmed': '手工单归属已确认，但未关联本地销售订单，保留待核对，不导入',
    'bf_candidate': '发现去除附加BF的本地订单候选，请编辑订单号并填写确认原因',
    'country_conflict': '本地订单国家与账单国家不一致，请核对',
    'store_conflict': '所选店铺与本地实际订单归属不一致',
    'booking_order_missing': '本地归档已找到预约号对应关系，但缺少对应销售订单，请补齐本地订单',
}


def reservation(value):
    return bool(re.fullmatch(r'\d{6}AAS[A-Z0-9]{10}', value, re.I))


def full_tracking(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[A-Za-z0-9_-]{6,191}', value.strip()))


def manual_source(source):
    names = source.get('raw_stores') or [source.get('raw_store', '')]
    return any(str(name).strip().lower() in {'manual orders', '手工订单店铺', '手工单', '手工订单'} for name in names)


def tracking_pairs(node, order='', depth=0):
    """Carry an order only down its own object, never across sibling orders."""
    if depth > 20:
        return
    if isinstance(node, list):
        for child in node:
            yield from tracking_pairs(child, order, depth + 1)
    elif isinstance(node, dict):
        own = node.get('order_sn') or node.get('external_order_id') or node.get('order_id')
        if isinstance(own, (str, int)) and not isinstance(own, bool):
            order = str(own).strip()
        for key in ['tracking_number', 'tracking_no', 'tracking_code']:
            value = node.get(key)
            if order and full_tracking(value):
                yield order, value.strip()
        for child in node.values():
            if isinstance(child, (dict, list)):
                yield from tracking_pairs(child, order, depth + 1)


def booking_pairs(node, depth=0):
    """Only accept booking_sn and formal order_sn from the same local record."""
    if depth > 20:
        return
    if isinstance(node, list):
        for child in node:
            yield from booking_pairs(child, depth + 1)
    elif isinstance(node, dict):
        booking, order = node.get('booking_sn'), node.get('order_sn')
        if isinstance(booking, str) and reservation(booking) and isinstance(order, str) and order.strip():
            yield booking, order.strip()
        for child in node.values():
            if isinstance(child, (dict, list)):
                yield from booking_pairs(child, depth + 1)


class LocalOrderLookup:
    def __init__(self, user, rows):
        self.user = user
        self.orders = defaultdict(dict)
        self.tracking = defaultdict(dict)
        self.bookings = defaultdict(dict)
        self.booking_refs = defaultdict(set)
        self.booking_missing = set()
        ids, tracking, bookings = set(), set(), set()
        for data, source in rows:
            if data['kind'] != 'order':
                continue
            for value in [data.get('external_order_id'), source.get('original_order_id')]:
                if value:
                    ids.add(value)
                    if value.endswith('BF') and re.fullmatch(r'(?:\d{6}[A-Z0-9]{8}|\d{18})BF', value):
                        ids.add(value[:-2])
            if reservation(source.get('original_order_id') or data.get('external_order_id', '')):
                bookings.add(source.get('original_order_id') or data['external_order_id'])
                tracking.update(t.strip() for t in source.get('tracking_numbers', []) if full_tracking(t))
        self.load_orders(ids)
        if tracking or bookings:
            self.load_references(tracking, bookings)

    def load_orders(self, ids):
        ids = sorted(ids)
        for offset in range(0, len(ids), 500):
            orders = SalesOrder.objects.filter(tenant=self.user.tenant,
                external_order_id__in=ids[offset:offset + 500]).select_related('store', 'platform')
            for order in orders:
                self.orders[order.external_order_id][order.pk] = order

    def load_references(self, wanted, bookings):
        numbers = sorted(wanted)
        for offset in range(0, len(numbers), 500):
            shipments = ShipmentRecord.objects.filter(tenant=self.user.tenant, sales_order__isnull=False,
                tracking_reference_masked__in=numbers[offset:offset + 500]).select_related('sales_order__store', 'sales_order__platform')
            for shipment in shipments:
                order = shipment.sales_order
                if (order.tenant_id == self.user.tenant_id and order.store_id == shipment.store_id
                        and full_tracking(shipment.tracking_reference_masked)):
                    self.tracking[shipment.tracking_reference_masked][order.pk] = order
        # Full tracking may exist only in retained, immutable local API envelopes.
        # Masked references are never fuzzy-matched; no network operation occurs.
        pairs = defaultdict(set)
        envelopes = SyncRawEnvelope.objects.filter(tenant=self.user.tenant, platform='shopee').filter(
            Q(sync_run__sync_job__resource_type__in=['sales_order', 'shipment'])
            | Q(endpoint__icontains='get_tracking_number')).order_by()
        for store, payload, digest in envelopes.values_list('store_id', 'payload', 'payload_hash').iterator(chunk_size=100):
            if not isinstance(payload, dict) or payload_digest(payload) != digest:
                continue
            for external, number in tracking_pairs(payload):
                if number in wanted:
                    pairs[number].add((external, store))
            for booking, external in booking_pairs(payload):
                if booking in bookings:
                    self.booking_refs[booking].add((external, store))
        external_ids = {external for values in pairs.values() for external, _ in values}
        external_ids.update(external for values in self.booking_refs.values() for external, _ in values)
        self.load_orders(external_ids)
        for booking, values in self.booking_refs.items():
            for external, store in values:
                linked = [o for o in self.orders[external].values()
                          if o.platform.platform_type == 'shopee' and (store is None or o.store_id == store)]
                if not linked:
                    self.booking_missing.add(booking)
                for order in linked:
                    self.bookings[booking][order.pk] = order
        for number, values in pairs.items():
            for external, store in values:
                for order in self.orders[external].values():
                    if order.platform.platform_type == 'shopee' and (store is None or order.store_id == store):
                        self.tracking[number][order.pk] = order

    def resolve(self, data, source):
        if data['kind'] == 'other':
            return {'status': 'not_applicable', 'candidates': []}
        original = source.get('original_order_id') or data.get('external_order_id', '')
        changed = 'external_order_id' in source.get('correction', {}).get('changes', {})
        external = data.get('external_order_id', '') if changed else original
        is_reservation = reservation(external)
        base = {'original_order_id': original, 'tracking_numbers': source.get('tracking_numbers', []), 'candidates': []}
        has_booking = is_reservation and bool(self.booking_refs[external])
        if has_booking:
            candidates = self.bookings[external]
            if external in self.booking_missing:
                return {**base, 'status': 'ambiguous' if candidates else 'booking_order_missing'}
        elif is_reservation:
            numbers = {t.strip() for t in source.get('tracking_numbers', []) if full_tracking(t)}
            if not numbers:
                return {**base, 'status': 'missing_tracking'}
            candidates = {pk: order for number in numbers for pk, order in self.tracking[number].items()}
        else:
            candidates = self.orders[external]
        platform = next((p for p in ['shopee', 'tiktok', 'lazada'] if p in source.get('raw_platform', '').lower()), '')
        eligible = {pk: order for pk, order in candidates.items()
                    if order.store.country_code == data['country'] and (not platform or order.platform.platform_type == platform)}
        base['candidates'] = [{'order_id': o.pk, 'external_order_id': o.external_order_id, 'store_id': o.store_id}
                              for o in eligible.values()]
        if len(eligible) == 1:
            order = next(iter(eligible.values()))
            if 'store_id' in source.get('correction', {}).get('changes', {}) and data.get('store_id') != order.store_id:
                return {**base, 'status': 'store_conflict'}
            status = 'booking_matched' if has_booking else 'reservation_matched' if is_reservation else 'matched'
            return {**base, 'status': status,
                    'order_id': order.pk, 'external_order_id': order.external_order_id, 'store_id': order.store_id}
        if eligible:
            return {**base, 'status': 'ambiguous'}
        if candidates:
            return {**base, 'status': 'country_conflict'}
        if is_reservation:
            return {**base, 'status': 'tracking_unmatched'}
        if (manual_source(source) and data.get('store_id')
                and 'store_id' in source.get('correction', {}).get('changes', {})
                and source.get('correction', {}).get('reason', '').strip()):
            return {**base, 'status': 'manual_confirmed'}
        if external.upper().startswith('PO-'):
            return {**base, 'status': 'temu_unintegrated'}
        if external.upper().startswith('OD') or manual_source(source):
            return {**base, 'status': 'manual_pending'}
        if external.endswith('BF') and re.fullmatch(r'(?:\d{6}[A-Z0-9]{8}|\d{18})BF', external):
            options = [o for o in self.orders[external[:-2]].values() if o.store.country_code == data['country']]
            if options:
                return {**base, 'status': 'bf_candidate', 'candidates': [
                    {'order_id': o.pk, 'external_order_id': o.external_order_id, 'store_id': o.store_id} for o in options]}
        return {**base, 'status': 'missing_order'}


def apply_match(lookup, data, source):
    result = lookup.resolve(data, source)
    source['matching'] = result
    if result['status'] in {'matched', 'booking_matched', 'reservation_matched'}:
        data.update(store_id=result['store_id'], external_order_id=result['external_order_id'])
    if data['kind'] == 'order' and result['status'] not in {'matched', 'booking_matched', 'reservation_matched'}:
        source['order_unlinked'] = True
    else:
        source.pop('order_unlinked', None)
    return MATCH_ERRORS.get(result['status'], '')
