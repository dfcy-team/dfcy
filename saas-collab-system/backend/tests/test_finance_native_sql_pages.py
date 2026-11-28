"""Exercise the MySQL reader through a simulated unbuffered driver."""
import ast
from collections import namedtuple
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest
from rest_framework.exceptions import ValidationError


SOURCE = Path(__file__).parents[1] / 'apps/finance/summary_database.py'


def reader_for(rows, *, truncate=0):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    functions = {node.name: node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)
                 and node.name in {'read_finance', 'read_sql', 'upper_value'}}
    fields = ('id', 'store_id', 'business_date', 'platform', 'external_order_id',
              'raw_fee_name', 'raw_amount', 'signed_amount', 'currency',
              'match_status', 'raw_envelope_id', 'fee_category')
    row_type = namedtuple('FinanceRow', ('pk', *fields[1:]))
    batches, fetch_sizes, cursor_requests = [], [], []
    state = {'buffered_scalar': 0, 'streaming': 0, 'closed': 0, 'wrap_exits': 0}

    class Query:
        model = SimpleNamespace(_meta=SimpleNamespace(db_table='finance'))
        db = 'default'

        def __init__(self, bounds=None, limit=None):
            self.bounds = bounds or {}
            self.limit = limit

        def filter(self, **bounds):
            return Query({**self.bounds, **bounds}, self.limit)

        def values_list(self, *args, **kwargs):
            return self

        def order_by(self, *args):
            return self

        def extra(self, *, where, params):
            assert 'BINARY' in where[0]
            return self

        def __getitem__(self, value):
            assert value.start is None and value.stop == 500
            return Query(self.bounds, value.stop)

        @property
        def query(self):
            return SimpleNamespace(get_compiler=lambda **kwargs: SimpleNamespace(
                as_sql=lambda: ('SELECT id FROM `finance`' +
                                (' LIMIT ' + str(self.limit) if self.limit is not None else ''), [self])))

    def key(values):
        row = row_type(*values)
        return row.external_order_id, row.business_date, row.currency, row.pk

    def matching(query):
        upper = query.bounds.get('pk__lte')
        return [row for row in rows if (upper is None or row[0] <= upper)
                and row[1] == query.bounds.get('store_id', row[1])]

    class Cursor:
        def __init__(self, *, streaming):
            self.streaming = streaming
            self.batch = []
            self.offset = 0

        def __enter__(self): return self
        def __exit__(self, *args): state['closed'] += 1

        def execute(self, sql, params):
            assert 'FORCE INDEX' in sql
            query = params[0]
            if sql.startswith('SELECT MAX('):
                assert not self.streaming and query.limit is None and 'LIMIT' not in sql
                maximum = max(row[0] for row in matching(query))
                self.batch = [(maximum,)]
                rows.append((maximum + 1, *rows[-1][1:]))
            elif sql.startswith('SELECT COUNT('):
                assert not self.streaming and query.limit is None and 'LIMIT' not in sql
                self.batch = [(len(matching(query)),)]
            else:
                assert self.streaming, 'finance data query must use SSCursor'
                assert query.limit is None and 'LIMIT' not in sql
                data = sorted(matching(query), key=key)
                self.batch = data[:-truncate] if truncate else data
                self.offset = 0

        def fetchone(self):
            return self.batch[0]

        def fetchmany(self, size):
            assert self.streaming, 'fetchmany must use the unbuffered cursor'
            assert 0 < size <= 500, f'unbounded fetchmany size: {size}'
            fetch_sizes.append(size)
            result = self.batch[self.offset:self.offset + size]
            self.offset += len(result)
            batches.append(len(result))
            return result

        def fetchall(self):
            raise AssertionError('fetchall is forbidden for finance data queries')

    class SSCursor: pass

    class DriverConnection:
        def cursor(self, cursor_class=None):
            cursor_requests.append(cursor_class)
            if cursor_class is SSCursor:
                state['streaming'] += 1
                return Cursor(streaming=True)
            assert cursor_class is None, 'only scalar queries may use buffered cursors'
            state['buffered_scalar'] += 1
            return Cursor(streaming=False)

    def buffered_cursor():
        state['buffered_scalar'] += 1
        return Cursor(streaming=False)

    class CursorWrapper:
        def __init__(self, cursor): self.cursor = cursor
        def __getattr__(self, name): return getattr(self.cursor, name)

    class MakeCursor:
        def __init__(self, cursor): self.cursor = cursor
        def __enter__(self): return self.cursor.__enter__()
        def __exit__(self, *args):
            result = self.cursor.__exit__(*args)
            state['wrap_exits'] += 1
            return result

    mysql = ModuleType('MySQLdb')
    mysql_cursors = ModuleType('MySQLdb.cursors')
    mysql_cursors.SSCursor = SSCursor
    django_base = ModuleType('django.db.backends.mysql.base')
    django_base.CursorWrapper = CursorWrapper
    connection = SimpleNamespace(vendor='mysql', cursor=buffered_cursor,
        connection=DriverConnection(), make_cursor=lambda cursor: MakeCursor(cursor),
        ops=SimpleNamespace(quote_name=lambda value: '`' + value + '`'))
    namespace = dict(stores={1: object()}, ordered=Query(), finance_fields=(),
                     connection=connection, FinanceRow=row_type,
                     ValidationError=ValidationError)
    exec(compile(ast.Module(body=[functions[name] for name in
                 ('read_sql', 'upper_value', 'read_finance')], type_ignores=[]),
                 str(SOURCE), 'exec'), namespace)

    def read():
        with patch.dict('sys.modules', {
            'MySQLdb': mysql, 'MySQLdb.cursors': mysql_cursors,
            'django.db.backends.mysql.base': django_base,
        }):
            yield from namespace['read_finance']()

    read.state = state
    read.fetch_sizes = fetch_sizes
    read.cursor_requests = cursor_requests
    read.streaming_class = SSCursor
    return read, batches


def make_rows(count):
    return [(pk, 1, date(2026, 11, 1 + (pk % 2)), 'lazada',
             'order-a' if pk <= 601 else 'order-b', 'fee', '1', str(pk),
             'PHP' if pk % 3 else 'THB', 'matched', None, 'fee')
            for pk in range(1, count + 1)]


def test_native_finance_sql_pages_preserve_groups_and_upper_bound():
    rows = make_rows(1101)
    expected = sorted(rows, key=lambda row: (row[4], row[2], row[8], row[0]))
    reader, batches = reader_for(rows)
    actual = list(reader())

    assert [tuple(row) for row in actual] == expected
    assert batches == [500, 500, 101, 0]
    assert reader.fetch_sizes == [500, 500, 500, 500]
    # MAX and COUNT use ordinary cursors; the data query explicitly requests SSCursor.
    assert reader.state['buffered_scalar'] == 2
    assert reader.state['streaming'] == 1
    assert reader.cursor_requests == [reader.streaming_class]
    assert sum(row.external_order_id == 'order-a' for row in actual) == 601
    assert [(row.external_order_id, row.business_date, row.currency, row.pk)
            for row in actual] == sorted((row.external_order_id, row.business_date, row.currency, row.pk)
                                         for row in actual)
    assert max(row.pk for row in actual) == 1101
    assert len(actual) == 1101  # row inserted after MAX was captured stays outside this snapshot


def test_native_stream_rejects_early_empty_batch():
    reader, _ = reader_for(make_rows(501), truncate=1)
    with pytest.raises(ValidationError, match='读取不完整'):
        list(reader())
    assert reader.state['streaming'] == 1
