import io
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.finance import summary_native as native
from apps.finance.summary_memory import MemoryBudgetExceeded


@pytest.fixture
def calculator(monkeypatch, tmp_path, settings):
    native.stop()
    path = tmp_path / 'source.gz'
    path.write_bytes(b'synthetic')
    monkeypatch.setattr(native, 'document_path', lambda dataset: path)
    monkeypatch.setattr(native, 'unpack_values', lambda values: values)
    settings.FINANCE_SUMMARY_NODE = 'synthetic-node'
    dataset = SimpleNamespace(tenant_id=1, pk=1, source_hash='synthetic', metadata={},
                              accounting_state=SimpleNamespace(revision=1, values={}))
    yield dataset
    native.stop()


def test_query_uses_budget_and_returns_unchanged_result(calculator, monkeypatch):
    process = Mock()
    process.poll.return_value = None
    process.stdin = io.StringIO()
    process.stdout = io.StringIO('{"ok":true,"result":{"amount":"123.45"}}\n')
    spawn = Mock(return_value=process)
    monkeypatch.setattr(native.subprocess, 'Popen', spawn)
    monkeypatch.setattr(native, 'node_heap_mb', lambda: 700)
    result = native.query(calculator, {'action': 'table'})
    assert result == {'amount': '123.45', 'revision': 1, 'dataset': 1}
    assert '--max-old-space-size=700' in spawn.call_args.args[0]


def test_insufficient_memory_never_starts_vm(calculator, monkeypatch):
    spawn = Mock()
    monkeypatch.setattr(native.subprocess, 'Popen', spawn)
    def insufficient():
        raise MemoryBudgetExceeded()
    monkeypatch.setattr(native, 'node_heap_mb', insufficient)
    with pytest.raises(native.CalculationMemoryLimit):
        native.query(calculator, {'action': 'table'})
    spawn.assert_not_called()
    assert native._lock.acquire(blocking=False)
    native._lock.release()


def test_source_guard_waits_for_old_vm_and_releases_lock_on_failure(monkeypatch):
    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr(native, '_process', process)
    with pytest.raises(RuntimeError):
        with native.materialization_guard():
            process.kill.assert_called_once()
            process.wait.assert_called_once_with(timeout=5)
            assert native._process is None
            raise RuntimeError('source failed')
    assert native._lock.acquire(blocking=False)
    native._lock.release()


def test_rebuild_engine_reports_same_memory_budget_error(monkeypatch, settings):
    from apps.finance import summary_service as service
    from apps.finance import summary_memory
    settings.FINANCE_SUMMARY_NODE = 'synthetic-node'
    spawn = Mock()
    monkeypatch.setattr(service.subprocess, 'run', spawn)
    def insufficient():
        raise MemoryBudgetExceeded()
    monkeypatch.setattr(summary_memory, 'node_heap_mb', insufficient)
    with pytest.raises(native.CalculationMemoryLimit):
        service.engine(SimpleNamespace(source_hash='synthetic'), {'action': 'inspect'})
    spawn.assert_not_called()
