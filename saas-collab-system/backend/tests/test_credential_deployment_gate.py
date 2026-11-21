import importlib.util
from pathlib import Path
import pytest
s=importlib.util.spec_from_file_location("runtime_deployment_gate",Path(__file__).resolve().parents[1]/"scripts/verify_runtime_consistency.py")
gate=importlib.util.module_from_spec(s);s.loader.exec_module(gate)
def test_gate_includes_independent_and_future_workers(monkeypatch):
    monkeypatch.setattr(gate.subprocess,"check_output",lambda *args,**kwargs:"production-backend-1\nproduction-celery-flash-1\nproduction-celery-video-v447-v3-1\nproduction-celery-future-1\nproduction-redis-1\n")
    assert set(gate.service_names())=={"production-backend-1","production-celery-flash-1","production-celery-video-v447-v3-1","production-celery-future-1"}
@pytest.mark.parametrize("field,value",[("helper_sha256","old-code"),("version",45),("valid",False)])
def test_gate_rejects_partial_deployment(monkeypatch,field,value):
    def check(name):
        row={"valid":True,"version":46,"helper_sha256":"same-code"}
        if name=="flash":row[field]=value
        return name,row
    monkeypatch.setattr(gate,"verify_one",check)
    assert gate.verify(["api","flash"])["status"]=="FAIL"
