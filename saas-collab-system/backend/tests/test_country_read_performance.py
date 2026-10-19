from django.db import connection
from django.test.utils import CaptureQueriesContext
from tests.test_country_inventory_decisions import facts, clock
from apps.commerce.country_decisions import decision_rows

def test_country_read_query_profile(facts):
    with CaptureQueriesContext(connection) as queries:
        rows = decision_rows(facts['actor'], facts['country'], [facts['sku']])
    assert len(rows) == 1
    assert sum('integrations_historysyncsegment' in q['sql'] for q in queries) == 1
    assert sum('ROW_NUMBER' in q['sql'] for q in queries) == 2


def test_full_page_reuses_authorization_branches(facts):
    from apps.products.models import ProductSKU
    skus = [facts['sku']] + [ProductSKU.objects.create(
        tenant=facts['tenant'], spu=facts['spu'], sku_code=f'PAGE-{i}') for i in range(19)]
    with CaptureQueriesContext(connection) as queries:
        rows = decision_rows(facts['actor'], facts['country'], skus)
    assert len(rows) == 20
    # Includes the per-SKU product detail contract; catches per-SKU scope lookups.
    assert len(queries) <= 160
