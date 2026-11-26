"""Exercise the actual native reader against a buffered-driver test double."""
import ast
from collections import namedtuple
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from rest_framework.exceptions import ValidationError

SOURCE = Path(__file__).parents[1] / 'apps/finance/summary_database.py'


def reader_for(rows, *, repeat_page=False):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    reader = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == 'read_finance')
    sql_reader = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef) and node.name == 'read_sql')
    upper_reader = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef) and node.name == 'upper_value')
    finance_fields = next(node.value for node in ast.walk(tree)
                          if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == 'finance_fields'
                                  for target in node.targets))
    fields = ast.literal_eval(finance_fields)
    row_type = namedtuple('FinanceRow', ('pk', *fields[1:]))
    pages = []
    calls = 0

    class Query:
        model = SimpleNamespace(_meta=SimpleNamespace(db_table='finance'))
        db = 'default'

        def __init__(self, bounds=None, after=None, limit=None):
            self.bounds = bounds or {}
            self.after = after
            self.limit = limit

        def filter(self, **bounds):
            return Query({**self.bounds, **bounds}, self.after, self.limit)

        def values_list(self, *args, **kwargs):
            assert args == fields or (args == ('id',) and kwargs == {'flat': True})
            return self

        def order_by(self, *args):
            return self

        def extra(self, *, where, params):
            assert 'BINARY' in where[0]
            return Query(self.bounds, params, self.limit)

        def __getitem__(self, value):
            assert value.start is None and value.stop == 500
            return Query(self.bounds, self.after, value.stop)

        @property
        def query(self):
            return SimpleNamespace(get_compiler=lambda **kwargs: SimpleNamespace(
                as_sql=lambda: ('SELECT id FROM `finance`' +
                    (' LIMIT ' + str(self.limit) if self.limit is not None else ''), [self])))

    def key(values):
        row = row_type(*values)
        return row.external_order_id, row.business_date, row.currency, row.pk

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, params):
            nonlocal calls
            calls += 1
            assert calls <= 5, 'reader exceeded bounded cursor calls'
            assert 'FORCE INDEX' in sql
            query = params[0]
            if sql.startswith('SELECT MAX('):
                assert query.limit is None and 'LIMIT' not in sql
                upper = max(row[0] for row in rows)
                self.batch = [(upper,)]
                rows.append((upper + 1, *rows[-1][1:]))  # after-snapshot row is excluded
                return
            assert query.limit == 500
            candidates = [row for row in rows
                if row[0] <= query.bounds['pk__lte']
                and row[1] == query.bounds['store_id']
                and (query.after is None or key(row) > query.after)]
            self.batch = (sorted(candidates, key=key) if not repeat_page or query.after is None
                          else sorted(rows, key=key))[:query.limit]
            pages.append(len(self.batch))

        def fetchall(self):
            return self.batch

        def fetchone(self):
            return self.batch[0]

    namespace = dict(stores={1: object()}, ordered=Query(), finance_fields=fields,
                     connection=SimpleNamespace(vendor='mysql', cursor=Cursor,
                         ops=SimpleNamespace(quote_name=lambda value: '`' + value + '`')),
                     FinanceRow=row_type, ValidationError=ValidationError)
    exec(compile(ast.Module(body=[sql_reader, upper_reader, reader], type_ignores=[]),
                 str(SOURCE), 'exec'), namespace)
    return namespace['read_finance'], pages


def test_native_finance_sql_pages_preserve_groups_and_upper_bound():
    rows = [(pk, 1, date(2026, 11, 1 + (pk % 2)), 'lazada',
             'order-a' if pk <= 601 else 'order-b', 'fee', '1', str(pk),
             'PHP' if pk % 3 else 'THB', 'matched', None, 'fee')
            for pk in range(1, 1102)]
    read_finance, pages = reader_for(rows)
    actual = list(read_finance())
    assert len(actual) == 1101
    assert {row.pk for row in actual} == set(range(1, 1102))
    assert pages == [500, 500, 101, 0]
    assert sum(row.external_order_id == 'order-a' for row in actual) == 601
    assert len({(row.external_order_id, row.business_date, row.currency) for row in actual}) > 4
    assert all(row.platform == 'lazada' for row in actual)


def test_native_finance_sql_pages_reject_nonprogress_before_yielding_duplicate_page():
    rows = [(pk, 1, date(2026, 11, 1), 'lazada', 'order-a', 'fee', '1', '1',
             'PHP', 'matched', None, 'fee') for pk in range(1, 502)]
    read_finance, pages = reader_for(rows, repeat_page=True)
    iterator = read_finance()
    assert [next(iterator).pk for _ in range(500)] == list(range(1, 501))
    with pytest.raises(ValidationError, match='分页游标未推进'):
        next(iterator)
    assert pages == [500, 500]
