"""Exercise the actual native reader against a buffered-driver test double."""
import ast
from collections import namedtuple
from datetime import date
from pathlib import Path
from types import SimpleNamespace


def test_native_finance_sql_pages_preserve_groups_and_upper_bound():
    source = Path(__file__).parents[1] / 'apps/finance/summary_database.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    reader = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == 'read_finance')
    sql_reader = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef) and node.name == 'read_sql')
    upper_reader = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef) and node.name == 'upper_value')
    rows = [(pk, 1, date(2026, 11, 1), 'same' if pk <= 601 else 'z',
             'fee', '1', '1', 'PHP', 'matched', None, 'fee')
            for pk in range(1, 1102)]
    expected = list(rows)
    pages = []

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

    def key(row):
        return row[3], row[2], row[7], row[0]

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, params):
            assert 'FORCE INDEX' in sql
            query = params[0]
            if sql.startswith('SELECT MAX('):
                assert query.limit is None and 'LIMIT' not in sql
                upper = max(row[0] for row in rows)
                self.batch = [(upper,)]
                rows.append((upper + 1, *rows[-1][1:]))
                return
            assert query.limit == 500
            self.batch = sorted((row for row in rows
                if row[0] <= query.bounds['pk__lte']
                and row[1] == query.bounds['store_id']
                and (query.after is None or key(row) > query.after)), key=key)[:query.limit]
            pages.append(len(self.batch))

        def fetchall(self):
            return self.batch

        def fetchone(self):
            return self.batch[0]

    namespace = dict(stores={1: object()}, ordered=Query(), finance_fields=(),
                     connection=SimpleNamespace(vendor='mysql', cursor=Cursor,
                         ops=SimpleNamespace(quote_name=lambda value: '`' + value + '`')),
                     FinanceRow=namedtuple('FinanceRow',
                         'pk store_id business_date external_order_id raw_fee_name raw_amount '
                         'signed_amount currency match_status raw_envelope_id fee_category'))
    exec(compile(ast.Module(body=[sql_reader, upper_reader, reader], type_ignores=[]), str(source), 'exec'), namespace)
    actual = list(namespace['read_finance']())
    assert [tuple(row) for row in actual] == expected
    assert pages == [500, 500, 101, 0]
    assert sum(row.external_order_id == 'same' for row in actual) == 601
