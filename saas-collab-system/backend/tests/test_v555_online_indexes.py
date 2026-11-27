"""Fail-closed online index guard tests; synthetic cursor, never a live database."""
import importlib
from types import SimpleNamespace
import pytest

migration=importlib.import_module('apps.commerce.migrations.0014_v555_sales_query_indexes_vm')
TABLES={'SalesOrder':'sales_order','SalesOrderItem':'sales_order_item'}
COLUMNS={'store':'store_id','sales_order':'sales_order_id','tenant':'tenant_id'}

class FakeCursor:
    def __init__(self, owner): self.owner=owner
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute(self, sql, params=None):
        self.owner.queries.append((sql,params));self.sql=sql
    def fetchall(self):
        table=self.sql.split('`')[1]
        return self.owner.rows.get(table,[])
    def fetchone(self): return (99,)

class FakeEditor:
    def __init__(self, rows, fail=False):
        self.rows=rows;self.fail=fail;self.queries=[];self.ddl=[]
        self.connection=SimpleNamespace(vendor='mysql',cursor=lambda:FakeCursor(self))
    def quote_name(self,name):return '`'+name+'`'
    def execute(self,sql):
        self.ddl.append(sql)
        if self.fail:raise RuntimeError('synthetic online DDL failure')

class FakeApps:
    def get_model(self,app,name):
        return SimpleNamespace(_meta=SimpleNamespace(db_table=TABLES[name],get_field=lambda f:SimpleNamespace(column=COLUMNS.get(f,f))))

def exact_rows():
    rows={t:[] for t in TABLES.values()}
    for model,name,fields in migration.INDEXES:
        for i,field in enumerate(fields,1):
            rows[TABLES[model]].append([TABLES[model],1,name,i,COLUMNS.get(field,field),'A',0,None,None,'','BTREE','','','YES',None])
    return rows

def test_exact_existing_indexes_are_idempotent_without_ddl_or_session_changes():
    editor=FakeEditor(exact_rows());migration.add_online_indexes(FakeApps(),editor)
    assert editor.ddl==[]
    assert all(sql.startswith('SHOW INDEX') for sql,_ in editor.queries)

@pytest.mark.parametrize('column,value',[(1,0),(4,'wrong_column'),(5,'D'),(7,4),(10,'HASH'),(13,'NO'),(14,'lower(id)')])
def test_any_existing_index_drift_fails_before_first_ddl(column,value):
    rows=exact_rows();rows['sales_order'][0][column]=value
    # Missing another index must not cause an earlier write before all checks pass.
    rows['sales_order_item']=[]
    editor=FakeEditor(rows)
    with pytest.raises(RuntimeError,match='definition differs'):migration.add_online_indexes(FakeApps(),editor)
    assert editor.ddl==[]

def test_new_indexes_require_online_no_lock_and_restore_metadata_lock_timeout():
    editor=FakeEditor({});migration.add_online_indexes(FakeApps(),editor)
    assert len(editor.ddl)==3
    assert all(sql.endswith('ALGORITHM=INPLACE, LOCK=NONE') for sql in editor.ddl)
    assert ('SET SESSION lock_wait_timeout = 15',None) in editor.queries
    assert editor.queries[-1]==('SET SESSION lock_wait_timeout = %s',[99])

def test_failed_online_ddl_still_restores_original_session_lock_timeout():
    editor=FakeEditor({},fail=True)
    with pytest.raises(RuntimeError,match='synthetic online DDL failure'):migration.add_online_indexes(FakeApps(),editor)
    assert len(editor.ddl)==1
    assert editor.queries[-1]==('SET SESSION lock_wait_timeout = %s',[99])
