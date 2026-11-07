
import pytest
from django.db import connection
from apps.tenants.models import Tenant
from apps.products.models import ProductCategory
from apps.products import import_service
from tests.test_product_legacy_import_v2 import _client

@pytest.mark.django_db(transaction=True)
def test_grouped_import_category_lock_runs_inside_transaction(monkeypatch):
    tenant=Tenant.objects.create(name="Attachment",code="attachment")
    root=ProductCategory.objects.create(tenant=tenant,level=1,code="1",name="Home")
    parent=ProductCategory.objects.create(tenant=tenant,parent=root,level=2,code="04",name="Rugs")
    ProductCategory.objects.create(tenant=tenant,parent=parent,level=3,code="01",name="Rug")
    original=import_service._resolve_category
    def checked(*args,**kwargs):
        assert connection.in_atomic_block
        return original(*args,**kwargs)
    monkeypatch.setattr(import_service,"_resolve_category",checked)
    text = "旧SKU编码,SPU分组标识,*商品名称,*完整类目编码,*属性编码,*颜色英文编码,*规格\n"
    text += "".join(f",A001,Rug,10401,0,{color},{size}\n" for color in ["Blue","Green","White"] for size in ["100X150CM","120X160CM","160X230CM","200X300CM"])
    response=_client(tenant).post("/api/internal/products/legacy-items/",{"mode":"create","csv_text":text},format="json")
    assert response.status_code==201, response.data
    assert response.data["data"]["created"]==12,response.data
    assert not response.data["data"]["errors"],response.data
