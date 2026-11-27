"""Exercise the actual native reader against a buffered-driver test double."""
import ast
from collections import namedtuple
from contextlib import nullcontext
import sys
from unittest.mock import patch
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from rest_framework.exceptions import ValidationError

SOURCE = Path(__file__).parents[1] / 'apps/finance/summary_database.py'


def reader_for(rows, *, repeat_page=False, count_delta=0, truncate=0):
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
            assert args == fields or (args == ('id',) and kwargs == {'flat': True}) or (args == ('pk',) and not kwargs)
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

    state = {'closed': 0, 'wrap_exits': 0}
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): state['closed'] += 1
        def execute(self, sql, params):
            nonlocal calls
            calls += 1
            assert calls <= 3, 'reader exceeded bounded cursor calls'
            assert 'FORCE INDEX' in sql
            query = params[0]
            if sql.startswith('SELECT MAX('):
                upper = max(row[0] for row in rows)
                self.batch = [(upper,)]
                rows.append((upper + 1, *rows[-1][1:]))
            elif sql.startswith('SELECT COUNT('):
                self.batch = [(sum(row[0] <= query.bounds['pk__lte'] for row in rows) + count_delta,)]
            else:
                self.batch = sorted([row for row in rows if row[0] <= query.bounds['pk__lte']
                                     and row[1] == query.bounds['store_id']], key=key)
                if truncate: self.batch = self.batch[:-truncate]
                if repeat_page: self.batch[500:] = self.batch[:len(self.batch)-500]
                self.offset = 0
        def fetchmany(self, size):
            assert size == 500
            result = self.batch[self.offset:self.offset+size]
            self.offset += len(result)
            pages.append(len(result))
            return result
        def fetchone(self): return self.batch[0]
    class Wrap:
        def __enter__(self): return self
        def __exit__(self, *args): state['wrap_exits'] += 1
    # Test the real generator body, with only driver/query I/O replaced.
    fake_mysql = SimpleNamespace(cursors=SimpleNamespace(SSCursor=object))
    namespace = dict(stores={1: object()}, ordered=Query(), finance_fields=fields,
                     connection=SimpleNamespace(vendor='mysql', cursor=Cursor,
                         connection=SimpleNamespace(cursor=lambda cls: Cursor()), wrap_database_errors=Wrap(),
                         ops=SimpleNamespace(quote_name=lambda value: '`' + value + '`')),
                     FinanceRow=row_type, ValidationError=ValidationError)
    exec(compile(ast.Module(body=[sql_reader, upper_reader, reader], type_ignores=[]),
                 str(SOURCE), 'exec'), namespace)
    def read():
        with patch.dict(sys.modules, {'MySQLdb': fake_mysql, 'MySQLdb.cursors': fake_mysql.cursors}):
            yield from namespace['read_finance']()
    read.state = state
    return read, pages


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
    with pytest.raises(ValidationError, match='财务流水排序异常'):
        next(iterator)
    assert pages == [500, 1]


@pytest.mark.parametrize('count_delta,truncate,message', [(1,0,'读取不完整'),(-1,0,'读取异常'),(0,1,'读取不完整')])
def test_native_stream_rejects_short_or_excess_snapshot(count_delta, truncate, message):
    rows = [(pk,1,date(2026,11,1),'lazada','order-a','fee','1','1','PHP','matched',None,'fee') for pk in range(1,502)]
    reader, _ = reader_for(rows,count_delta=count_delta,truncate=truncate)
    with pytest.raises(ValidationError,match=message): list(reader())
    assert reader.state == {'closed':3,'wrap_exits':1}


def test_native_stream_early_close_closes_driver_before_outer_cleanup():
    rows = [(pk,1,date(2026,11,1),'lazada','order-a','fee','1','1','PHP','matched',None,'fee') for pk in range(1,502)]
    reader, _ = reader_for(rows)
    iterator = reader()
    assert next(iterator).pk == 1
    assert reader.state == {'closed':2,'wrap_exits':0}
    iterator.close()
    assert reader.state == {'closed':3,'wrap_exits':1}
