"""Synthetic localhost preparation/launch/verification. No production connectivity."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import http.server
import ssl

import requests
import MySQLdb

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('acceptance', ROOT / 'tools/demo_sync_local_acceptance.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
PRIVATE = a.RUNTIME / 'one-click'
TEMPLATE = 'saas_collab_demo_update_template'
INITIAL = 'saas_collab_demo_update_initial'


def env():
    c = a.config()
    return {**os.environ, 'DB_ENGINE': 'django.db.backends.mysql', 'DB_HOST': '127.0.0.1', 'DB_PORT': '13326',
            'DB_USER': 'root', 'DB_PASSWORD': c['mysql_password'], 'DJANGO_SECRET_KEY': c['django_key'],
            'DJANGO_ALLOWED_HOSTS': 'localhost,127.0.0.1', 'MYSQL_PWD': c['mysql_password'],
            'DJANGO_SETTINGS_MODULE': 'config.settings.demo_snapshot', 'PYTHONIOENCODING': 'utf-8'}


def session():
    s = requests.Session()
    s.trust_env = False
    return s


def login(s, port):
    r = s.post(f'http://127.0.0.1:{port}/api/internal/auth/login/',
               json={'username': 'demo-sync-acceptance', 'password': a.config()['login_password']}, timeout=20)
    r.raise_for_status()
    payload = r.json()
    return payload.get('data', payload)


def prepare():
    PRIVATE.mkdir(mode=0o700, exist_ok=False)
    c = a.config()
    conn = MySQLdb.connect(host='127.0.0.1', port=13326, user='root', passwd=c['mysql_password'])
    with conn.cursor() as cursor:
        for name in (TEMPLATE, INITIAL):
            cursor.execute(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4')
    conn.close()
    dump = PRIVATE / 'bootstrap.sql'
    cli = ['docker', 'exec', '-i', '--env', 'MYSQL_PWD', a.CONTAINER]
    with dump.open('wb') as f:
        subprocess.run([*cli, 'mysqldump', '--user=root', '--single-transaction', '--no-tablespaces',
                        '--set-gtid-purged=OFF', '--skip-triggers', a.DATABASES['control']],
                       env=env(), stdout=f, check=True)
    for name in (TEMPLATE, INITIAL):
        with dump.open('rb') as f:
            subprocess.run([*cli, 'mysql', '--user=root', name], env=env(), stdin=f, check=True)
        code = ('from apps.demo_sync.models import SyncAudit,SnapshotBatch,SyncEnvironment\n'
                'SyncAudit.objects.all().delete();SnapshotBatch.objects.all().delete();SyncEnvironment.objects.all().delete()')
        subprocess.run([sys.executable, 'manage.py', 'shell', '-c', code], cwd=ROOT / 'backend',
                       env={**env(), 'DB_NAME': name}, check=True, stdout=subprocess.DEVNULL)
    ids = json.loads((a.RUNTIME / 'seed-control.json').read_text())
    data = {'confirm_disposable_local_demo': True, 'initial_database': INITIAL, 'template_database': TEMPLATE,
            'tenant_id': ids['tenant_id'], 'actor_id': ids['user_id'], 'environment_id': 1,
            'intranet_url': 'https://localhost:8544', 'ca_bundle': str(a.RUNTIME / 'ca.pem'),
            'window_days': 3, 'port': 5182, 'backend_port': 8032,
            'state_directory': str(PRIVATE / 'state'), 'frontend_directory': str(ROOT / 'frontend/dist'),
            'mysql_tools_container': a.CONTAINER}
    (PRIVATE / 'runtime.json').write_text(json.dumps(data), encoding='utf-8')
    print('Synthetic one-click runtime prepared; no credentials printed.')


def launch():
    s = session()
    token = login(s, 8020)['refresh']
    subprocess.run([sys.executable, 'tools/demo_local_runtime.py', '--config', str(PRIVATE / 'runtime.json')],
                   cwd=ROOT, env={**env(), 'DEMO_INTRANET_REFRESH_TOKEN': token}, check=True)


def serve_tls():
    class Proxy(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_request(self):
            if not self.path.startswith('/api/internal/'):
                self.send_error(404)
                return
            size = int(self.headers.get('Content-Length', '0'))
            r = session().request(self.command, 'http://127.0.0.1:8020' + self.path,
                                  headers={k: v for k, v in self.headers.items() if k.lower() in ('authorization', 'content-type')},
                                  data=self.rfile.read(size) if size else None, timeout=60, allow_redirects=False)
            self.send_response(r.status_code)
            self.send_header('Content-Type', r.headers.get('Content-Type', 'application/json'))
            self.send_header('Content-Length', str(len(r.content)))
            self.end_headers()
            self.wfile.write(r.content)
        do_GET = do_POST = handle_request
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 8544), Proxy)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(a.RUNTIME / 'server.pem'), str(a.RUNTIME / 'server-key.pem'))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


def verify():
    s = session()
    tokens = login(s, 5182)
    token = tokens['access']
    headers = {'Authorization': 'Bearer ' + token}
    pointer = PRIVATE / 'state/active.json'
    before = json.loads(pointer.read_text())['active'] if pointer.exists() else INITIAL
    r = s.post('http://127.0.0.1:5182/__demo_update/start', headers=headers, timeout=20)
    r.raise_for_status()
    for _ in range(240):
        time.sleep(2)
        r = s.get('http://127.0.0.1:5182/__demo_update/status', headers=headers, timeout=20)
        if r.status_code == 503:
            continue
        if r.status_code == 401:
            renewed = s.post('http://127.0.0.1:5182/api/internal/auth/refresh/', json={'refresh': tokens['refresh']}, timeout=20)
            renewed.raise_for_status()
            payload = renewed.json()
            headers['Authorization'] = 'Bearer ' + payload.get('data', payload)['access']
            continue
        r.raise_for_status()
        status = r.json()['data']
        if status['status'] == 'failed':
            raise RuntimeError(status['error_code'])
        if status['status'] == 'ready':
            break
    else:
        raise RuntimeError('Acceptance wait timed out')
    active = json.loads((PRIVATE / 'state/active.json').read_text())
    conn = MySQLdb.connect(host='127.0.0.1', port=13326, user='root', passwd=a.config()['mysql_password'], db=active['active'])
    with conn.cursor() as c:
        c.execute('SELECT COUNT(*) FROM sales_order')
        orders = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM demo_sync_importedsnapshotreceipt')
        receipts = c.fetchone()[0]
    conn.close()
    assert active['active'] != before and active['previous'] == before and orders == 2 and receipts == 1
    rollback = s.post('http://127.0.0.1:5182/__demo_update/rollback', headers=headers, timeout=20)
    rollback.raise_for_status()
    for _ in range(90):
        time.sleep(1)
        r = s.get('http://127.0.0.1:5182/__demo_update/status', headers=headers, timeout=10)
        if r.status_code == 200 and r.json()['data']['status'] == 'ready':
            break
    restored = json.loads((PRIVATE / 'state/active.json').read_text())
    assert restored['active'] == before and restored['previous'] == active['active']
    result = {'status': 'LOCAL_ONE_CLICK_SYNTHETIC_PASS', 'orders': orders, 'import_receipts': receipts,
              'automatic_worker': True, 'new_database_activated': True, 'rollback_verified': True,
              'production_operations': 0}
    (ROOT / 'docs/demo-data-sync/one-click/local-runtime-validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


def audit():
    """Deterministic aggregate checks on the currently active synthetic target."""
    pointer = json.loads((PRIVATE / 'state/active.json').read_text())
    target = pointer['active']
    if not target.startswith('saas_collab_demo_u'):
        raise RuntimeError('An imported synthetic target must be active')
    conn = MySQLdb.connect(host='127.0.0.1', port=13326, user='root', passwd=a.config()['mysql_password'])
    tables = ['sales_order', 'sales_order_item', 'inventory_snapshot', 'products_productspu',
              'products_productsku', 'products_productcategory', 'masterdata_platformmaster',
              'masterdata_countrysitemaster', 'masterdata_storemaster', 'masterdata_warehousemaster']
    schema, counts = {}, {}
    with conn.cursor() as c:
        for name in (a.DATABASES['source'], target):
            counts[name] = {}
            for table in tables:
                c.execute(f'SELECT COUNT(*) FROM `{name}`.`{table}`')
                counts[name][table] = c.fetchone()[0]
            c.execute('SELECT TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,CHARACTER_SET_NAME,COLLATION_NAME,EXTRA '
                      'FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN (' + ','.join(['%s'] * len(tables)) + ') '
                      'ORDER BY TABLE_NAME,ORDINAL_POSITION', [name, *tables])
            schema[name] = c.fetchall()
        c.execute(f'SELECT COUNT(*) FROM `{target}`.sales_order_item i LEFT JOIN `{target}`.sales_order o ON o.id=i.sales_order_id '
                  f'LEFT JOIN `{target}`.products_productsku s ON s.id=i.internal_sku_id '
                  'WHERE o.id IS NULL OR (i.internal_sku_id IS NOT NULL AND s.id IS NULL)')
        violations = c.fetchone()[0]
        c.execute(f'SELECT CAST(SUM(order_total_amount) AS CHAR) FROM `{target}`.sales_order WHERE normalized_status <> %s', ['cancelled'])
        amount = c.fetchone()[0]
    conn.close()
    diff = sum(x != y for x, y in zip(schema[a.DATABASES['source']], schema[target])) + abs(len(schema[a.DATABASES['source']]) - len(schema[target]))
    assert counts[a.DATABASES['source']] == counts[target] and diff == violations == 0 and amount == '20.1234'
    fact = sum(counts[target][t] for t in tables[:3])
    result = {'status': 'LOCAL_ONE_CLICK_MYSQL_AUDIT_PASS', 'source_rows': fact, 'target_rows': fact,
              'schema_diff_count': diff, 'constraint_violations': violations, 'mismatched_chunks': [],
              'sample_artifact': None, 'recommended_action': 'Review candidate; configure intranet before real-data acceptance.',
              'snapshot_rows': sum(counts[target].values()), 'non_cancelled_order_amount': amount,
              'production_access': False}
    (ROOT / 'docs/demo-data-sync/one-click/mysql-audit.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['prepare', 'launch', 'verify', 'serve_tls', 'audit'])
    globals()[parser.parse_args().phase]()
