import importlib
import pytest
from django.apps import apps
from django.db import connection
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_payments import itemized_batch,save_itemized_fee
from apps.supply_chain.cost_models import FeeRevisionItem,FeeRevision
@pytest.mark.django_db
def test_backfill_preserves_source(world):
    _,api,batch,_,profiles=itemized_batch(world)
    save_itemized_fee(api,batch,profiles)
    before=list(FeeRevision.objects.values('id','amount','item_breakdown'))
    FeeRevisionItem.objects.all().delete()
    migration=importlib.import_module('apps.supply_chain.migrations.0053_fee_item_query_projection')
    class Editor: pass
    editor=Editor();editor.connection=connection
    migration.backfill(apps,editor)
    assert FeeRevisionItem.objects.count()==2
    assert list(FeeRevision.objects.values('id','amount','item_breakdown'))==before
