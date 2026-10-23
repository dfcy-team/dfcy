"""Opt-in, single-user loopback Demo supervisor. Never install on a shared server.

Keeps its update API alive while replacing its managed Django child. The browser
never receives intranet credentials. A clean, operator-provisioned template DB
preserves local login/permissions; each update creates a new disposable database.
"""
import argparse
import http.server
import json
import os
from pathlib import Path
import re
import subprocess
import socket
import shutil
import sys
import threading
import time
from urllib.parse import urlsplit
import uuid
import zipfile

import requests

BASE = Path(__file__).resolve().parents[1]
MAX_BYTES = 512 * 1024 * 1024
RESOURCES = {'platforms', 'country_sites', 'stores', 'warehouses', 'product_categories',
             'products', 'product_details', 'sales_orders', 'sales_order_items', 'inventory_snapshots'}


class UpdateError(Exception):
    pass


def database_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'saas_collab_demo_[a-z0-9_]{1,40}', value):
        raise UpdateError('LOCAL_DATABASE_REJECTED')
    return value


def extract_bundle(archive, folder):
    """Reject traversal, links, duplicates, unexpected members and ZIP bombs."""
    with zipfile.ZipFile(archive) as z:
        seen, total = set(), 0
        for member in z.infolist():
            name = member.filename
            if (name in seen or name not in {'manifest.json', *(r + '.jsonl' for r in RESOURCES)}
                    or member.is_dir() or (member.external_attr >> 16) & 0o170000 == 0o120000):
                raise UpdateError('BUNDLE_MEMBER_REJECTED')
            seen.add(name)
            total += member.file_size
            if total > MAX_BYTES or (name == 'manifest.json' and member.file_size > 1024 * 1024):
                raise UpdateError('BUNDLE_TOO_LARGE')
        if 'manifest.json' not in seen:
            raise UpdateError('MANIFEST_MISSING')
        folder.mkdir(mode=0o700)
        written = 0
        for member in z.infolist():
            with z.open(member) as src, (folder / member.filename).open('xb') as dst:
                while chunk := src.read(65536):
                    written += len(chunk)
                    if written > MAX_BYTES:
                        raise UpdateError('BUNDLE_TOO_LARGE')
                    dst.write(chunk)


class Runtime:
    def __init__(self, config):
        self.config = config
        if config.get('confirm_disposable_local_demo') is not True:
            raise UpdateError('LOCAL_OPT_IN_REQUIRED')
        if os.environ.get('DB_HOST') not in ('localhost', '127.0.0.1'):
            raise UpdateError('LOCAL_MYSQL_REQUIRED')
        if not os.environ.get('DJANGO_SECRET_KEY') or not os.environ.get('DB_PASSWORD'):
            raise UpdateError('LOCAL_SECRETS_REQUIRED')
        database_name(config['initial_database'])
        database_name(config['template_database'])
        if config['initial_database'] == config['template_database']:
            raise UpdateError('TEMPLATE_MUST_BE_SEPARATE')
        if not 1 <= int(config.get('window_days', 7)) <= 31:
            raise UpdateError('WINDOW_INVALID')
        source = urlsplit(config['intranet_url'])
        if (source.scheme != 'https' or not source.hostname or source.username or source.password
                or source.path not in ('', '/') or source.query or source.fragment):
            raise UpdateError('INTRANET_HTTPS_REQUIRED')
        for key in ('port', 'backend_port'):
            if not 1024 <= int(config[key]) <= 65535:
                raise UpdateError('PORT_INVALID')
        if config['port'] == config['backend_port']:
            raise UpdateError('PORT_CONFLICT')
        self.root = Path(config['state_directory']).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.instance_lock = (self.root / 'runtime.lock').open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self.instance_lock.seek(0)
                self.instance_lock.write(b'0')
                self.instance_lock.flush()
                self.instance_lock.seek(0)
                msvcrt.locking(self.instance_lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.instance_lock.close()
            raise UpdateError('LOCAL_RUNTIME_ALREADY_RUNNING') from None
        self.state_file = self.root / 'active.json'
        self.state = json.loads(self.state_file.read_text()) if self.state_file.exists() else {
            'active': config['initial_database'], 'previous': None}
        database_name(self.state['active'])
        if self.state.get('previous'):
            database_name(self.state['previous'])
        if config['template_database'] in (self.state['active'], self.state.get('previous')):
            raise UpdateError('TEMPLATE_CANNOT_BE_ACTIVE')
        self.status = {'enabled': True, 'status': 'idle', 'error_code': ''}
        self.lock = threading.Lock()
        self.traffic = threading.Condition()
        self.inflight = 0
        self.switching = False
        self.busy = False
        self.child = None
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.verify = config.get('ca_bundle') or True
        self.local_session = requests.Session()
        self.local_session.trust_env = False
        self.remote_access = os.environ.get('DEMO_INTRANET_ACCESS_TOKEN', '')
        self.log = (self.root / 'runtime.log').open('ab')

    def env(self, database):
        return {**os.environ, 'DB_NAME': database_name(database),
                'DJANGO_SETTINGS_MODULE': 'config.settings.demo_snapshot',
                'DEMO_DATA_SYNC_ENABLED': 'false', 'DEMO_DATA_SYNC_WORKER_ENABLED': 'false',
                'DEMO_DATA_SYNC_IMPORT_ENABLED': 'true', 'DEMO_LOCAL_UPDATE_ENABLED': 'true',
                'DEMO_LOCAL_ACTOR_ID': str(self.config['actor_id']),
                'DEMO_LOCAL_TENANT_ID': str(self.config['tenant_id'])}

    def manage(self, database, *args):
        result = subprocess.run([sys.executable, 'manage.py', *args], cwd=BASE / 'backend',
                                env=self.env(database), stdout=self.log, stderr=self.log, timeout=600)
        if result.returncode:
            raise UpdateError('LOCAL_PREPARATION_FAILED')

    def start_backend(self, database):
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', self.config['backend_port'])) == 0:
                raise UpdateError('BACKEND_PORT_OCCUPIED')
        generation = uuid.uuid4().hex
        env = {**self.env(database), 'DEMO_LOCAL_GENERATION': generation}
        self.child = subprocess.Popen([sys.executable, 'manage.py', 'runserver', '--noreload',
                                       f'127.0.0.1:{self.config["backend_port"]}'],
                                      cwd=BASE / 'backend', env=env, stdout=self.log, stderr=self.log)
        for _ in range(120):
            if self.child.poll() is not None:
                raise UpdateError('BACKEND_START_FAILED')
            try:
                r = self.local_session.get(f'http://127.0.0.1:{self.config["backend_port"]}/api/internal/demo-data-sync/local-health/', timeout=1)
                if r.status_code == 200 and r.json().get('data', {}).get('generation') == generation:
                    return
            except requests.RequestException:
                pass
            time.sleep(0.5)
        raise UpdateError('BACKEND_HEALTH_TIMEOUT')

    def stop_backend(self):
        if self.child and self.child.poll() is None:
            self.child.terminate()
            try:
                self.child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait(timeout=5)

    def prepare(self, bundle):
        if shutil.disk_usage(self.root).free < 3 * MAX_BYTES:
            raise UpdateError('LOCAL_DISK_SPACE_LOW')
        container = self.config.get('mysql_tools_container')
        if container:
            if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,100}', container):
                raise UpdateError('MYSQL_CONTAINER_INVALID')
            result = subprocess.run(['docker', 'exec', container, 'df', '-Pk', '/var/lib/mysql'],
                                    capture_output=True, text=True, timeout=10)
            try:
                free = int(result.stdout.strip().splitlines()[-1].split()[3]) * 1024
            except (IndexError, ValueError):
                raise UpdateError('MYSQL_STORAGE_CHECK_FAILED') from None
            if result.returncode or free < 256 * 1024 * 1024:
                raise UpdateError('MYSQL_DISK_SPACE_LOW')
        elif self.config.get('mysql_data_directory'):
            if shutil.disk_usage(self.config['mysql_data_directory']).free < 256 * 1024 * 1024:
                raise UpdateError('MYSQL_DISK_SPACE_LOW')
        template = self.config['template_database']
        # Template must have no business snapshot rows and a valid preconfigured local actor.
        code = """from django.apps import apps
from apps.demo_sync.importer import MODEL_MAP
from apps.demo_sync.models import ImportedSnapshotReceipt, SnapshotIdentity, SnapshotBatch, SyncEnvironment
from apps.integrations.models import PlatformIntegrationConfig, SyncJob
from apps.accounts.models import CustomUser
import os
if ImportedSnapshotReceipt.objects.exists() or SnapshotIdentity.objects.exists():
 raise RuntimeError('TEMPLATE_HAS_IMPORTED_DATA')
if SnapshotBatch.objects.exists() or SyncEnvironment.objects.exists():
 raise RuntimeError('TEMPLATE_HAS_SYNC_TASKS')
if PlatformIntegrationConfig.objects.exists() or SyncJob.objects.exists():
 raise RuntimeError('TEMPLATE_HAS_INTEGRATIONS')
for module, name in MODEL_MAP.values():
 import importlib
 if getattr(importlib.import_module(module),name).objects.exists():
  raise RuntimeError('TEMPLATE_HAS_BUSINESS_ROWS')
if not CustomUser.objects.filter(pk=int(os.environ['DEMO_LOCAL_ACTOR_ID']),tenant_id=int(os.environ['DEMO_LOCAL_TENANT_ID']),is_active=True,user_type='internal').exists():
 raise RuntimeError('TEMPLATE_ACTOR_INVALID')
"""
        self.manage(template, 'shell', '-c', code)
        target = database_name('saas_collab_demo_u' + uuid.uuid4().hex[:20])
        self.manage(template, 'shell', '-c',
                    "from django.db import connection\nwith connection.cursor() as c: c.execute('CREATE DATABASE `" + target + "` CHARACTER SET utf8mb4')")
        dump = bundle.parent / 'template.sql'
        mysql_env = {**os.environ, 'MYSQL_PWD': os.environ['DB_PASSWORD']}
        common = ['--host=' + os.environ['DB_HOST'], '--port=' + os.environ.get('DB_PORT', '3306'),
                  '--user=' + os.environ['DB_USER'], '--protocol=TCP']
        prefix = []
        container = self.config.get('mysql_tools_container')
        if container:
            if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,100}', container):
                raise UpdateError('MYSQL_CONTAINER_INVALID')
            prefix = ['docker', 'exec', '-i', '--env', 'MYSQL_PWD', container]
            common = ['--host=127.0.0.1', '--port=3306', '--user=' + os.environ['DB_USER'], '--protocol=TCP']
        with dump.open('xb') as out:
            p = subprocess.run([*prefix, 'mysqldump', *common, '--single-transaction', '--no-tablespaces',
                                '--set-gtid-purged=OFF', '--skip-triggers', template],
                               env=mysql_env, stdout=out, stderr=self.log, timeout=600)
        if p.returncode:
            raise UpdateError('TEMPLATE_COPY_FAILED')
        with dump.open('rb') as src:
            p = subprocess.run([*prefix, 'mysql', *common, target], env=mysql_env, stdin=src,
                               stdout=self.log, stderr=self.log, timeout=600)
        if p.returncode:
            raise UpdateError('TEMPLATE_COPY_FAILED')
        self.manage(target, 'migrate', '--noinput')
        args = ('import_demo_snapshot', str(bundle), '--tenant-id', str(self.config['tenant_id']),
                '--actor-id', str(self.config['actor_id']))
        self.manage(target, *args)  # dry-run before commit
        self.manage(target, *args, '--commit', '--confirm-disposable-demo')
        return target

    def activate(self, target):
        database_name(target)
        old = dict(self.state)
        with self.traffic:
            self.switching = True
            if not self.traffic.wait_for(lambda: self.inflight == 0, timeout=30):
                self.switching = False
                raise UpdateError('REQUEST_DRAIN_TIMEOUT')
        try:
            self.stop_backend()
            self.start_backend(target)
            if self.child.poll() is not None:
                raise UpdateError('BACKEND_EXITED_BEFORE_ACTIVATION')
            new = {'active': target, 'previous': old['active']}
            temp = self.root / 'active.tmp'
            with temp.open('w', encoding='utf-8') as f:
                json.dump(new, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.state_file)
            self.state = new
        except Exception:
            self.stop_backend()
            try:
                self.start_backend(old['active'])
            except Exception:
                raise UpdateError('ROLLBACK_START_FAILED') from None
            raise UpdateError('ACTIVATION_FAILED_OLD_RESTORED') from None
        finally:
            with self.traffic:
                self.switching = False
                self.traffic.notify_all()

    def remote(self, method, path, **kwargs):
        refresh = os.environ.get('DEMO_INTRANET_REFRESH_TOKEN', '')
        def refresh_access():
            if not refresh:
                raise UpdateError('INTRANET_LOGIN_REQUIRED')
            r = self.session.post(self.config['intranet_url'].rstrip('/') + '/api/internal/auth/refresh/',
                                  json={'refresh': refresh}, timeout=(5, 20), allow_redirects=False)
            if r.status_code != 200:
                raise UpdateError('INTRANET_LOGIN_REQUIRED')
            payload = r.json()
            self.remote_access = payload.get('access') or payload.get('data', {}).get('access')
        if not self.remote_access:
            refresh_access()
        if not self.remote_access:
            raise UpdateError('INTRANET_LOGIN_REQUIRED')
        r = self.session.request(method, self.config['intranet_url'].rstrip('/') + path,
                                 headers={'Authorization': 'Bearer ' + self.remote_access},
                                 timeout=(5, 60), allow_redirects=False, **kwargs)
        if r.status_code == 401 and refresh:
            r.close()
            refresh_access()
            r = self.session.request(method, self.config['intranet_url'].rstrip('/') + path,
                                     headers={'Authorization': 'Bearer ' + self.remote_access},
                                     timeout=(5, 60), allow_redirects=False, **kwargs)
        if r.status_code not in (200, 202):
            r.close()
            raise UpdateError('INTRANET_REQUEST_REJECTED')
        return r

    def update(self, rollback=False):
        try:
            if rollback:
                if not self.state.get('previous'):
                    raise UpdateError('NO_PREVIOUS_DATABASE')
                target = self.state['previous']
            else:
                self.status.update(status='fetching', error_code='')
                base = '/api/internal/demo-data-sync/batches/'
                from datetime import date, timedelta
                end = date.today() - timedelta(days=1)
                start = end - timedelta(days=int(self.config.get('window_days', 7)) - 1)
                response = self.remote('POST', base, json={'environment_id': self.config['environment_id'],
                                                         'date_from': start.isoformat(), 'date_to': end.isoformat()})
                batch = str(uuid.UUID(response.json()['data']['id']))
                deadline = time.monotonic() + 1800
                for _ in range(600):
                    if time.monotonic() >= deadline:
                        raise UpdateError('SNAPSHOT_TIMEOUT')
                    item = self.remote('GET', base + batch + '/').json()['data']
                    if item['status'] == 'ready':
                        break
                    if item['status'] == 'failed':
                        raise UpdateError('SNAPSHOT_FAILED')
                    time.sleep(3)
                else:
                    raise UpdateError('SNAPSHOT_TIMEOUT')
                work = self.root / uuid.uuid4().hex
                work.mkdir(mode=0o700)
                archive = work / 'snapshot.zip'
                with self.remote('GET', base + batch + '/download/', stream=True) as r, archive.open('xb') as f:
                    count = 0
                    for chunk in r.iter_content(65536):
                        count += len(chunk)
                        if count > MAX_BYTES:
                            raise UpdateError('BUNDLE_TOO_LARGE')
                        f.write(chunk)
                bundle = work / 'bundle'
                extract_bundle(archive, bundle)
                self.status.update(status='preparing')
                target = self.prepare(bundle)
            self.status.update(status='activating')
            self.activate(target)
            self.status.update(status='ready', error_code='')
        except Exception as exc:
            self.status.update(status='failed', error_code=str(exc) if isinstance(exc, UpdateError) else 'UPDATE_FAILED')
        finally:
            with self.lock:
                self.busy = False

    def submit(self, rollback=False):
        with self.lock:
            if self.busy:
                return False
            self.busy = True
            self.status.update(status='queued', error_code='')
            threading.Thread(target=self.update, args=(rollback,), daemon=True).start()
            return True


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # URLs and headers can contain credentials; no HTTP access logging.

    def reply(self, code, value):
        raw = json.dumps(value).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def handle_request(self):
        rt = self.server.runtime
        host = self.headers.get('Host', '')
        allowed = {f'127.0.0.1:{rt.config["port"]}', f'localhost:{rt.config["port"]}'}
        if host not in allowed or self.headers.get('Origin', 'http://' + host) != 'http://' + host:
            return self.reply(403, {'success': False, 'code': 'LOCAL_ORIGIN_REQUIRED', 'message': '只允许本机同源访问。', 'data': None})
        if self.headers.get('Transfer-Encoding') or not self.headers.get('Content-Length', '0').isdigit():
            return self.reply(400, {'success': False, 'code': 'BODY_INVALID', 'message': '请求格式无效。', 'data': None})
        length = int(self.headers.get('Content-Length', '0'))
        if length > 10 * 1024 * 1024:
            return self.reply(413, {})
        body = self.rfile.read(length) if length else None
        local = f'http://127.0.0.1:{rt.config["backend_port"]}'
        if self.path.startswith('/__demo_update/'):
            if (self.path, self.command) not in {('/__demo_update/status', 'GET'), ('/__demo_update/start', 'POST'), ('/__demo_update/rollback', 'POST')}:
                return self.reply(404, {})
            if not self.headers.get('Authorization', '').startswith('Bearer '):
                return self.reply(401, {'success': False, 'code': 'LOCAL_LOGIN_REQUIRED', 'message': '请先登录本地 Demo。', 'data': None})
            if rt.switching:
                return self.reply(503, {'success': False, 'code': 'DEMO_SWITCHING', 'message': '本地 Demo 切换中，请稍后重试。', 'data': None})
            try:
                auth = rt.local_session.get(local + '/api/internal/demo-data-sync/local-authorize/',
                                    headers={'Authorization': self.headers.get('Authorization', '')}, timeout=5)
                if auth.status_code != 200:
                    return self.reply(auth.status_code, {'success': False, 'code': 'LOCAL_ACCESS_DENIED', 'message': '没有本地更新权限。', 'data': None})
                if self.command == 'POST' and not rt.submit(self.path.endswith('rollback')):
                    return self.reply(409, {'success': False, 'code': 'UPDATE_BUSY', 'message': '更新正在进行。', 'data': None})
                return self.reply(200, {'success': True, 'code': 'OK', 'message': 'success',
                                       'data': {**rt.status, 'previous_available': bool(rt.state.get('previous'))}})
            except requests.RequestException:
                return self.reply(503, {'success': False, 'code': 'DEMO_SWITCHING', 'message': '本地服务恢复中。', 'data': None})
        with rt.traffic:
            auth_request = self.path in ('/api/internal/auth/login/', '/api/internal/auth/refresh/')
            if rt.switching or (rt.busy and self.command not in ('GET', 'HEAD', 'OPTIONS') and not auth_request):
                return self.reply(503, {'success': False, 'code': 'DEMO_UPDATE_READ_ONLY', 'message': '更新期间暂停写入，请稍后重试。', 'data': None})
            rt.inflight += 1
        try:
            if not self.path.startswith('/api/'):
                target = (Path(rt.config['frontend_directory']) / self.path.split('?', 1)[0].lstrip('/')).resolve()
                root = Path(rt.config['frontend_directory']).resolve()
                if not target.is_relative_to(root) or not target.is_file():
                    target = root / 'index.html'
                import mimetypes
                raw = target.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            else:
                headers = {k: v for k, v in self.headers.items() if k.lower() in {'authorization', 'content-type', 'cookie', 'x-csrftoken'}}
                r = rt.local_session.request(self.command, local + self.path, data=body, headers=headers,
                                     allow_redirects=False, timeout=60)
                self.send_response(r.status_code)
                for k, v in r.headers.items():
                    if k.lower() in ('content-type', 'content-disposition', 'set-cookie'):
                        self.send_header(k, v)
                self.send_header('Content-Length', str(len(r.content)))
                self.end_headers()
                self.wfile.write(r.content)
        except (OSError, requests.RequestException):
            self.reply(503, {'success': False, 'code': 'LOCAL_BACKEND_UNAVAILABLE', 'message': '本地服务不可用。', 'data': None})
        finally:
            with rt.traffic:
                rt.inflight -= 1
                rt.traffic.notify_all()

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = do_OPTIONS = do_HEAD = handle_request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args()
    runtime = Runtime(json.loads(args.config.read_text(encoding='utf-8')))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', runtime.config['port']), Handler)
    server.runtime = runtime
    try:
        runtime.start_backend(runtime.state['active'])
        server.serve_forever()
    finally:
        runtime.stop_backend()
        server.server_close()


if __name__ == '__main__':
    main()
