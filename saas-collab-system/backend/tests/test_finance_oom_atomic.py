import gzip
import hashlib
from unittest.mock import Mock
import pytest
from apps.finance import summary_rebuild as rebuild
from apps.finance import summary_native as native


def test_existing_valid_source_never_rewritten(tmp_path, monkeypatch):
    body = b'accepted source'
    target = tmp_path / 'source.gz'
    original = gzip.compress(body)
    target.write_bytes(original)
    monkeypatch.setattr(rebuild.tempfile, 'mkstemp', Mock(side_effect=AssertionError('must preserve existing')))
    rebuild.publish_source(target, body, hashlib.sha256(body).hexdigest())
    assert target.read_bytes() == original
    assert gzip.decompress(target.read_bytes()) == body


def test_half_write_preserves_existing_source(tmp_path, monkeypatch):
    old = b'previous accepted source'
    target = tmp_path / 'source.gz'
    original = gzip.compress(old)
    target.write_bytes(original)
    real = rebuild.gzip.GzipFile.write
    def fail(stream, body):
        if body:
            real(stream, body[:len(body)//2])
            raise OSError('injected halfway failure')
        return real(stream, body)
    monkeypatch.setattr(rebuild.gzip.GzipFile, 'write', fail)
    with pytest.raises(OSError):
        rebuild.publish_source(target, b'new candidate', hashlib.sha256(b'new candidate').hexdigest())
    assert target.read_bytes() == original
    assert gzip.decompress(target.read_bytes()) == old
    assert list(tmp_path.iterdir()) == [target]


def test_unreaped_child_remains_tracked(monkeypatch):
    process = Mock()
    process.poll.return_value = None
    process.wait.side_effect = native.subprocess.TimeoutExpired('node', 5)
    monkeypatch.setattr(native, '_process', process)
    with pytest.raises(native.CalculationTimeout):
        native.stop()
    assert native._process is process


def test_service_timeout_preserves_payload_and_classifies(monkeypatch):
    from apps.finance import summary_service as service
    from types import SimpleNamespace
    payload = {'action': 'inspect', 'state': {'accepted': 'unchanged'}}
    monkeypatch.setattr(service, 'document_path', lambda dataset: 'synthetic.gz')
    monkeypatch.setattr(service.subprocess, 'run', Mock(side_effect=service.subprocess.TimeoutExpired('node',120)))
    with pytest.raises(native.CalculationTimeout):
        service._run_engine(SimpleNamespace(source_hash='hash'), payload, 'node', 'worker', 700)
    assert payload == {'action': 'inspect', 'state': {'accepted': 'unchanged'}}


def test_corrupt_deflate_repaired_atomically(tmp_path):
    body=b'accepted source'
    raw=bytearray(gzip.compress(body));raw[10]=(raw[10]&248)|7
    target=tmp_path/'broken.gz';target.write_bytes(raw)
    rebuild.publish_source(target,body,hashlib.sha256(body).hexdigest())
    assert gzip.decompress(target.read_bytes())==body
    assert list(tmp_path.iterdir())==[target]


def test_unreaped_child_session_is_invalidated(monkeypatch):
    process=Mock();process.poll.return_value=None
    process.wait.side_effect=native.subprocess.TimeoutExpired('node',5)
    monkeypatch.setattr(native,'_process',process)
    monkeypatch.setattr(native,'_session_key','previous-key')
    monkeypatch.setattr(native,'_tenant_id',7)
    with pytest.raises(native.CalculationTimeout):native.stop()
    assert native._process is process and native._session_key is None and native._tenant_id is None
