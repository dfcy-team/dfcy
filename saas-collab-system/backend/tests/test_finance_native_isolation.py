"""Calculation process recycling without running financial or provider writes."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from tests.test_finance_summary import context


@pytest.mark.parametrize('change',['tenant','revision'])
@pytest.mark.parametrize('direct',[False,True])
def test_tenant_switch_recycles_before_loading_next_vm(context,monkeypatch,change,caplog,direct):
    from apps.finance import summary_native as native
    _,_,dataset,_=context
    dataset.metadata = {**dataset.metadata, 'direct_query': direct}
    one,two=Mock(),Mock()
    for process in [one,two]:process.poll.return_value=None
    spawn=Mock(side_effect=[one,two])
    monkeypatch.setattr(native.shutil,'which',lambda name:'synthetic-node')
    monkeypatch.setattr(native,'_process',None);monkeypatch.setattr(native,'_tenant_id',None);monkeypatch.setattr(native,'_code_stamp',None)
    monkeypatch.setattr(native,'_session_key',None)
    monkeypatch.setattr(native.subprocess,'Popen',spawn)
    monkeypatch.setattr(native.threading,'Thread',Mock())
    monkeypatch.setattr(native.threading,'Timer',Mock())
    replies=Mock();replies.get.return_value={'ok':True,'result':{'rows':[]},'timings':{'vm_ms':1.25,'unsafe':'SENSITIVE'}}
    monkeypatch.setattr(native.queue,'Queue',lambda:replies)
    with caplog.at_level('INFO',logger='apps.finance.summary_native'):
        native.query(dataset,{'action':'table'});native.query(dataset,{'action':'table'})
    assert 'vm_ms' in caplog.text and 'SENSITIVE' not in caplog.text
    assert spawn.call_count==1 and not one.kill.called
    assert f'--max-old-space-size={1024 if direct else 2048}' in spawn.call_args[0][0]
    second=SimpleNamespace(tenant_id=999999,pk=999999,source_hash=dataset.source_hash,document_file=dataset.document_file,metadata=dataset.metadata,accounting_state=dataset.accounting_state)
    if change=='revision':
        second=dataset
        dataset.accounting_state.revision+=1
    native.query(second,{'action':'table'})
    assert spawn.call_count==2 and one.kill.call_count==1
    native.stop();assert native._tenant_id is None


def test_busy_calculator_does_not_kill_another_request(context,monkeypatch):
    from apps.finance import summary_native as native
    _,_,dataset,_=context
    lock=Mock();lock.acquire.return_value=False
    process=Mock()
    monkeypatch.setattr(native,'_lock',lock);monkeypatch.setattr(native,'_process',process)
    with pytest.raises(native.CalculationBusy):native.query(dataset,{'action':'table'})
    lock.acquire.assert_called_once_with(timeout=30)
    assert not process.kill.called and not lock.release.called


def test_calculation_timeout_releases_lock_and_recycles_process(context,monkeypatch):
    from apps.finance import summary_native as native
    _,_,dataset,_=context
    process=Mock();process.poll.return_value=None
    lock=Mock();lock.acquire.return_value=True
    replies=Mock();replies.get.side_effect=native.queue.Empty
    monkeypatch.setattr(native,'_lock',lock);monkeypatch.setattr(native,'_process',None)
    monkeypatch.setattr(native,'_session_key',None);monkeypatch.setattr(native,'_code_stamp',None)
    monkeypatch.setattr(native.subprocess,'Popen',lambda *a,**k:process)
    monkeypatch.setattr(native.shutil,'which',lambda name:'synthetic-node')
    monkeypatch.setattr(native.threading,'Thread',Mock());monkeypatch.setattr(native.queue,'Queue',lambda:replies)
    with pytest.raises(native.CalculationTimeout):native.query(dataset,{'action':'table'})
    assert process.kill.call_count==1 and lock.release.call_count==1


def test_source_read_does_not_kill_busy_calculation(monkeypatch):
    from apps.finance import summary_native as native
    lock=Mock();lock.acquire.return_value=False;process=Mock()
    monkeypatch.setattr(native,'_lock',lock);monkeypatch.setattr(native,'_process',process)
    with pytest.raises(native.CalculationBusy):
        with native.materialization_guard():pytest.fail('Busy VM must be left alone')
    assert not process.kill.called and not lock.release.called


@pytest.mark.parametrize('failed',[False,True])
def test_source_read_releases_old_vm_before_reading_and_always_unlocks(monkeypatch,failed):
    from apps.finance import summary_native as native
    lock=Mock();lock.acquire.return_value=True;process=Mock();process.poll.return_value=None
    monkeypatch.setattr(native,'_lock',lock);monkeypatch.setattr(native,'_process',process)
    def read():
        with native.materialization_guard():
            assert native._process is None and process.kill.call_count==1
            if failed:raise RuntimeError('synthetic failure')
    if failed:
        with pytest.raises(RuntimeError):read()
    else:read()
    assert lock.release.call_count==1
