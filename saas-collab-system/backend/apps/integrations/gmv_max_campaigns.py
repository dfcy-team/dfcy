"""Campaign drilldown from validated daily snapshots, without provider calls."""
from decimal import Decimal


def campaign_report(days, expected_days):
    groups = {}
    coverage = {}
    for day in days:
        subject = tuple(day[k] for k in ('store_code', 'advertiser_id', 'platform_store_id', 'currency', 'timezone'))
        coverage.setdefault(subject, set()).add(day['date'])
        for entry in day['campaigns']:
            key = subject + (entry['campaign_id'],)
            if key not in groups:
                groups[key] = {k: day[k] for k in ('store_code', 'advertiser_id', 'advertiser_name', 'platform_store_id', 'currency', 'timezone')}
                groups[key].update(campaign_id=entry['campaign_id'], campaign_name=None,
                                   campaign_type='unknown', days=[])
            groups[key]['days'].append({
                'date': day['date'], 'snapshot_id': day['snapshot_id'],
                'fetched_at': day['fetched_at'],
                'cost': str(entry['cost']), 'gross_revenue': str(entry['gross_revenue']),
                'orders': int(Decimal(str(entry['orders']))),
            })
    for key, group in groups.items():
        cost = sum((Decimal(d['cost']) for d in group['days']), Decimal(0))
        revenue = sum((Decimal(d['gross_revenue']) for d in group['days']), Decimal(0))
        orders = sum(d['orders'] for d in group['days'])
        group.update(cost=str(cost), gross_revenue=str(revenue), orders=orders,
                     roi=str(revenue / cost) if cost else None,
                     cost_per_order=str(cost / orders) if orders else None,
                     covered_days=len(coverage[key[:-1]]), expected_days=expected_days)
        group['days'].sort(key=lambda d: d['date'])
    return sorted(groups.values(), key=lambda g: (g['store_code'], g['advertiser_id'], g['campaign_id'], g['platform_store_id'], g['currency'], g['timezone']))
