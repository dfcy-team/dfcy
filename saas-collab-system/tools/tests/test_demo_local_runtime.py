import importlib.util
from pathlib import Path
import threading
from unittest.mock import Mock
import zipfile

import pytest

spec = importlib.util.spec_from_file_location('demo_local_runtime', Path(__file__).parents[1] / 'demo_local_runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


@pytest.mark.parametrize('name', ['production', 'saas_collab_sync_control', 'saas_collab_demo_x`;DROP', '../demo'])
def test_reject_non_demo_database(name):
    with pytest.raises(runtime.UpdateError):
        runtime.database_name(name)


@pytest.mark.parametrize('member', ['../escape', '/absolute', 'other.json', 'products/../products.jsonl'])
def test_reject_zip_member(tmp_path, member):
    archive = tmp_path / 'x.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('manifest.json', '{}')
        z.writestr(member, '{}')
    with pytest.raises(runtime.UpdateError, match='BUNDLE_MEMBER_REJECTED'):
        runtime.extract_bundle(archive, tmp_path / 'bundle')


def bare(tmp_path):
    rt = object.__new__(runtime.Runtime)
    rt.root = tmp_path
    rt.state_file = tmp_path / 'active.json'
    rt.state = {'active': 'saas_collab_demo_old', 'previous': None}
    rt.traffic = threading.Condition()
    rt.inflight, rt.switching = 0, False
    rt.start_backend, rt.stop_backend = Mock(), Mock()
    rt.child = Mock()
    rt.child.poll.return_value = None
    return rt


def test_activation_persists_only_after_healthy_start(tmp_path):
    rt = bare(tmp_path)
    rt.activate('saas_collab_demo_new')
    assert rt.state == {'active': 'saas_collab_demo_new', 'previous': 'saas_collab_demo_old'}
    assert rt.state_file.exists()
    assert rt.switching is False


def test_activation_failure_restores_old_without_pointer_change(tmp_path):
    rt = bare(tmp_path)
    rt.start_backend.side_effect = [runtime.UpdateError('FAILED'), None]
    with pytest.raises(runtime.UpdateError, match='ACTIVATION_FAILED_OLD_RESTORED'):
        rt.activate('saas_collab_demo_new')
    assert rt.state['active'] == 'saas_collab_demo_old'
    assert not rt.state_file.exists()
    assert rt.start_backend.call_args.args == ('saas_collab_demo_old',)
    assert rt.switching is False


def test_failed_preparation_does_not_activate(tmp_path):
    rt = bare(tmp_path)
    rt.status, rt.lock, rt.busy = {}, threading.Lock(), True
    rt.config = {'environment_id': 1}
    rt.remote = Mock(side_effect=runtime.UpdateError('INTRANET_LOGIN_REQUIRED'))
    rt.update()
    assert rt.status == {'status': 'failed', 'error_code': 'INTRANET_LOGIN_REQUIRED'}
    rt.start_backend.assert_not_called()
    assert not rt.busy


def test_local_sessions_ignore_proxy_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_HOST', '127.0.0.1')
    monkeypatch.setenv('DB_PASSWORD', 'synthetic-only-password')
    monkeypatch.setenv('DJANGO_SECRET_KEY', 'synthetic-only-key')
    monkeypatch.setenv('HTTP_PROXY', 'http://proxy.invalid:3128')
    config = {'confirm_disposable_local_demo': True, 'initial_database': 'saas_collab_demo_initial',
              'template_database': 'saas_collab_demo_template', 'intranet_url': 'https://intranet.example',
              'port': 5182, 'backend_port': 8032, 'state_directory': str(tmp_path)}
    rt = runtime.Runtime(config)
    try:
        assert rt.session.trust_env is False and rt.local_session.trust_env is False
    finally:
        rt.log.close()
        rt.instance_lock.close()


def test_occupied_backend_port_never_starts_child(tmp_path):
    import socket
    rt = bare(tmp_path)
    with socket.socket() as server:
        server.bind(('127.0.0.1', 0))
        server.listen()
        rt.config = {'backend_port': server.getsockname()[1]}
        # Exercise real implementation, not the fake start callback in bare().
        with pytest.raises(runtime.UpdateError, match='BACKEND_PORT_OCCUPIED'):
            runtime.Runtime.start_backend(rt, 'saas_collab_demo_next')


def test_remote_access_is_cached_and_refreshes_on_unauthorized(monkeypatch):
    rt = object.__new__(runtime.Runtime)
    rt.config = {'intranet_url': 'https://intranet.example'}
    rt.remote_access = ''
    rt.session = Mock()
    rt.session.post.return_value.status_code = 200
    rt.session.post.return_value.json.return_value = {'access': 'synthetic-access-only'}
    ok, unauthorized = Mock(status_code=200), Mock(status_code=401)
    rt.session.request.side_effect = [ok, ok, unauthorized, ok]
    monkeypatch.setenv('DEMO_INTRANET_REFRESH_TOKEN', 'synthetic-refresh-only')
    rt.remote('GET', '/first')
    rt.remote('GET', '/second')
    assert rt.session.post.call_count == 1
    rt.remote('GET', '/third')
    assert rt.session.post.call_count == 2
    unauthorized.close.assert_called_once()


def test_mysql_container_space_guard_runs_before_create(tmp_path, monkeypatch):
    rt = bare(tmp_path)
    rt.config = {'mysql_tools_container': 'synthetic-mysql'}
    rt.manage = Mock()
    monkeypatch.setattr(runtime.shutil, 'disk_usage', lambda _: Mock(free=10 * runtime.MAX_BYTES))
    monkeypatch.setattr(runtime.subprocess, 'run', lambda *a, **k: Mock(returncode=0, stdout='Filesystem 1024-blocks Used Available Capacity Mounted\n tmpfs 786432 786432 0 100% /var/lib/mysql\n'))
    with pytest.raises(runtime.UpdateError, match='MYSQL_DISK_SPACE_LOW'):
        rt.prepare(tmp_path / 'bundle')
    rt.manage.assert_not_called()


def test_refresh_remains_available_while_business_writes_pause(tmp_path):
    import http.server
    import requests
    rt = bare(tmp_path)
    rt.busy = True
    rt.config = {'port': 0, 'backend_port': 8032}
    rt.local_session = Mock()
    rt.local_session.request.return_value = Mock(status_code=200, headers={'Content-Type': 'application/json'}, content=b'{}')
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), runtime.Handler)
    server.runtime = rt
    rt.config['port'] = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    session = requests.Session()
    session.trust_env = False
    url = f'http://127.0.0.1:{server.server_port}'
    try:
        assert session.post(url + '/api/internal/commerce/orders/', json={}, timeout=2).status_code == 503
        assert session.post(url + '/api/internal/auth/refresh/', json={'refresh': 'synthetic'}, timeout=2).status_code == 200
        assert rt.local_session.request.call_count == 1
    finally:
        session.close()
        server.shutdown()
        server.server_close()
