"""Exercise the production bounded item generator with page-time insertion."""
import ast
from pathlib import Path
from types import SimpleNamespace
from rest_framework.exceptions import ValidationError


def test_item_pages_include_201_original_rows_exclude_later_insert():
    source = Path(__file__).parents[1] / 'apps/finance/summary_database.py'
    function = next(n for n in ast.walk(ast.parse(source.read_text(encoding='utf-8'))) if isinstance(n, ast.FunctionDef) and n.name == 'read_item_pages')
    rows = [SimpleNamespace(pk=n) for n in range(1,202)]
    sizes=[]
    class Query:
        def __init__(self,bounds=None): self.bounds=bounds or {}
        def order_by(self,*fields): return self
        def values_list(self,*fields,**kw): return self
        def first(self): return max((r.pk for r in rows),default=None)
        def filter(self,**bounds): return Query(bounds)
        def __getitem__(self,sl):
            assert sl.start is None and sl.stop == 200
            batch=[r for r in rows if self.bounds['pk__gt'] < r.pk <= self.bounds['pk__lte']][:200]
            sizes.append(len(batch))
            return batch
    env={'ValidationError':ValidationError}
    exec(compile(ast.Module(body=[function],type_ignores=[]),str(source),'exec'),env)
    iterator=env['read_item_pages'](Query())
    assert [next(iterator).pk for _ in range(200)] == list(range(1,201))
    rows.append(SimpleNamespace(pk=202))
    assert [r.pk for r in iterator] == [201]
    # The frozen upper PK is reached without an extra empty query.
    assert sizes == [200,1]
