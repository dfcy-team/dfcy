"""Disposable localhost acceptance. Uses no production addresses or credentials."""
import argparse
import base64
import hashlib
import http.server
import ipaddress
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone

import requests

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
RUNTIME = ROOT.parents[2] / ".codex-tmp" / "demo-sync-local-acceptance-20261022"
EVIDENCE = ROOT / "docs" / "demo-data-sync" / "local-acceptance"
CONTAINER = "codex-demo-sync-acceptance-20261022"
DATABASES = {"source": "saas_collab_demo_source_acceptance", "control": "saas_collab_sync_acceptance", "target": "saas_collab_demo_target_acceptance"}


def emit(value):
    print(json.dumps(value, ensure_ascii=False, default=str), flush=True)


def config():
    return json.loads((RUNTIME / "private-config.json").read_text(encoding="utf-8"))


def env_for(role):
    c = config()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "DJANGO_SETTINGS_MODULE": "config.settings.demo_sync_local_acceptance",
           "DEMO_ACCEPTANCE_CONFIRM": "synthetic-local-only", "DEMO_ACCEPTANCE_ROLE": role,
           "DEMO_ACCEPTANCE_MYSQL_PASSWORD": c["mysql_password"], "DEMO_ACCEPTANCE_DJANGO_KEY": c["django_key"],
           "DEMO_SYNC_CLIENT_ID": c["client_id"], "DEMO_SYNC_CLIENT_SECRET": c["client_secret"],
           "DEMO_SYNC_MASKING_KEY": c["masking_key"], "DEMO_ACCEPTANCE_CA_BUNDLE": str(RUNTIME / "ca.pem"),
           "DEMO_ACCEPTANCE_ARTIFACT_ROOT": str(RUNTIME / "snapshots")}
    control = RUNTIME / "seed-control.json"
    if control.exists():
        env["DEMO_ACCEPTANCE_CONTROL_TENANT"] = str(json.loads(control.read_text())["tenant_id"])
    return env


def manage(role, arguments, logname):
    run = subprocess.run([sys.executable, "manage.py", *arguments], cwd=BACKEND, env=env_for(role),
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    (RUNTIME / logname).write_text(run.stdout + run.stderr, encoding="utf-8")
    if run.returncode:
        raise RuntimeError("LOCAL_MANAGEMENT_COMMAND_FAILED_" + role.upper())
    return run.stdout


def prepare():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    if (RUNTIME / "private-config.json").exists():
        raise RuntimeError("LOCAL_ACCEPTANCE_ALREADY_PREPARED")
    RUNTIME.mkdir(parents=True, mode=0o700)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    c = {name: secrets.token_urlsafe(32) for name in ("mysql_password", "django_key", "login_password", "client_secret", "masking_key")}
    c["client_id"] = "local-demo-acceptance-" + secrets.token_hex(6)
    (RUNTIME / "private-config.json").write_text(json.dumps(c), encoding="utf-8")
    (RUNTIME / "docker.env").write_text("MYSQL_ROOT_PASSWORD=" + c["mysql_password"] + "\nMYSQL_ROOT_HOST=%\n", encoding="utf-8")
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Demo Sync Local CA")])
    ca = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=2))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True).sign(ca_key, hashes.SHA256()))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
            .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True).sign(ca_key, hashes.SHA256()))
    (RUNTIME / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (RUNTIME / "server.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM) + ca.public_bytes(serialization.Encoding.PEM))
    (RUNTIME / "server-key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    for path in RUNTIME.iterdir():
        path.chmod(0o600)
    image = subprocess.check_output(["docker", "image", "inspect", "mysql:8.4.11", "--format", "{{.Id}}"], text=True).strip()
    subprocess.run(["docker", "run", "-d", "--name", CONTAINER, "--label", "purpose=synthetic-demo-sync-acceptance",
                    "--env-file", str(RUNTIME / "docker.env"), "--memory=2g", "--cpus=2",
                    "--tmpfs", "/var/lib/mysql:rw,size=768m", "-p", "127.0.0.1:13326:3306", image],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import MySQLdb
    for _ in range(60):
        try:
            connection = MySQLdb.connect(host="127.0.0.1", port=13326, user="root", passwd=c["mysql_password"], connect_timeout=2)
            break
        except MySQLdb.Error:
            time.sleep(1)
    else:
        raise RuntimeError("LOCAL_MYSQL_NOT_READY")
    with connection.cursor() as cursor:
        for name in DATABASES.values():
            cursor.execute("CREATE DATABASE `" + name + "` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
        cursor.execute("SELECT VERSION()")
        version = cursor.fetchone()[0]
    connection.close()
    result = {"status": "prepared", "mysql_version": version, "image_id": image, "container": CONTAINER,
              "bind": "127.0.0.1:13326", "databases": DATABASES, "synthetic_only": True, "production_access": False}
    (EVIDENCE / "environment.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    emit(result)


def migrate():
    for role in DATABASES:
        manage(role, ["migrate", "--noinput"], f"migrate-{role}.log")
        emit({"stage": "migrate", "role": role, "status": "passed"})


def seed():
    for role in DATABASES:
        if (RUNTIME / f"seed-{role}.json").exists():
            emit({"stage": "seed", "role": role, "status": "existing_fixture_preserved"})
            continue
        out = manage(role, ["seed_demo_sync_acceptance", "--role", role, "--config", str(RUNTIME / "private-config.json")], f"seed-{role}.log")
        row = json.loads(out.strip().splitlines()[-1])
        (RUNTIME / f"seed-{role}.json").write_text(json.dumps(row), encoding="utf-8")
        emit({"stage": "seed", "role": role, "status": "passed", "counts": row.get("resource_counts", {})})


class TLSProxy(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        # Source test server provides only the read-only API over this listener.
        if not self.path.startswith("/api/internal-readonly/v1/"):
            self.send_error(404)
            return
        session = requests.Session()
        session.trust_env = False
        headers = {"Host": "localhost", "X-Forwarded-Proto": "https"}
        if self.headers.get("Authorization"):
            headers["Authorization"] = self.headers["Authorization"]
        response = session.get("http://127.0.0.1:8021" + self.path, headers=headers, timeout=25, allow_redirects=False)
        self.send_response(response.status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response.content)))
        self.end_headers()
        self.wfile.write(response.content)
        session.close()

    def log_message(self, *args):
        pass


def serve_tls():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 8443), TLSProxy)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(RUNTIME / "server.pem", RUNTIME / "server-key.pem")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    emit({"status": "local_tls_source_listening", "bind": "127.0.0.1:8443"})
    server.serve_forever()


def serve(role):
    port = "8021" if role == "source" else "8020"
    subprocess.run([sys.executable, "manage.py", "runserver", "127.0.0.1:" + port, "--noreload"], cwd=BACKEND, env=env_for(role), check=True)


def authenticated_session():
    c = config()
    session = requests.Session()
    session.trust_env = False
    response = session.post("http://127.0.0.1:8020/api/internal/auth/login/", json={"username": "demo-sync-acceptance", "password": c["login_password"]}, timeout=20)
    response.raise_for_status()
    data = response.json().get("data", response.json())
    session.headers["Authorization"] = "Bearer " + data["access"]
    return session


def execute():
    source = json.loads((RUNTIME / "seed-source.json").read_text())
    c = config()
    direct = requests.Session()
    direct.trust_env = False
    try:
        direct.get("https://localhost:8443/api/internal-readonly/v1/capabilities/", timeout=20)
    except requests.exceptions.SSLError:
        untrusted_ca_rejected = True
    else:
        raise RuntimeError("TLS_VERIFICATION_NOT_ENFORCED")
    direct.verify = str(RUNTIME / "ca.pem")
    caps = direct.get("https://localhost:8443/api/internal-readonly/v1/capabilities/", timeout=20)
    caps.raise_for_status()
    direct.auth = (c["client_id"], "invalid-synthetic-secret")
    bad = direct.get("https://localhost:8443/api/internal-readonly/v1/products/", timeout=20)
    assert bad.status_code == 401
    direct.auth = (c["client_id"], c["client_secret"])
    forbidden = direct.get("https://localhost:8443/api/internal-readonly/v1/product_costs/", timeout=20)
    assert forbidden.status_code == 403
    session = authenticated_session()
    base = "http://127.0.0.1:8020/api/internal/demo-data-sync/"
    selected = ["platforms", "country_sites", "stores", "warehouses", "product_categories", "products", "product_details", "sales_orders", "sales_order_items", "inventory_snapshots"]
    response = session.post(base + "environments/", json={"name": "本机 MySQL 合成联调", "resources": selected,
                            "store_ids": [source["store_id"]], "warehouse_ids": [source["warehouse_id"]]}, timeout=20)
    response.raise_for_status()
    env_id = response.json()["data"]["id"]
    payload = {"environment_id": env_id, "date_from": "2026-10-20", "date_to": "2026-10-20"}
    response = session.post(base + "batches/", json=payload, timeout=20)
    assert response.status_code == 202
    batch_id = response.json()["data"]["id"]
    assert session.post(base + "batches/", json=payload, timeout=20).status_code == 400
    manage("control", ["run_demo_snapshot", "--batch-id", batch_id], "worker.log")
    batch = session.get(base + f"batches/{batch_id}/", timeout=20).json()["data"]
    assert batch["status"] == "ready", batch.get("error_code")
    response = session.get(base + f"batches/{batch_id}/download/", timeout=30)
    response.raise_for_status()
    archive = RUNTIME / "snapshot.zip"
    archive.write_bytes(response.content)
    bundle = RUNTIME / "downloaded-bundle"
    bundle.mkdir()
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            assert Path(name).name == name and (name == "manifest.json" or name.endswith(".jsonl"))
        z.extractall(bundle)
    target = json.loads((RUNTIME / "seed-target.json").read_text())
    args = ["import_demo_snapshot", str(bundle), "--tenant-id", str(target["tenant_id"]), "--actor-id", str(target["user_id"])]
    manage("target", args, "dry-run.log")
    manage("target", args + ["--commit", "--confirm-disposable-demo"], "import.log")
    manage("target", args + ["--commit", "--confirm-disposable-demo"], "replay.log")
    report = {"status": "local_http_flow_passed", "synthetic_only": True, "capabilities_http": caps.status_code,
              "ready_resources": len(caps.json()["data"]["ready_resources"]), "tls_verification": "private_CA_verified",
              "untrusted_ca_rejected": untrusted_ca_rejected, "unauthorized_resource_http": forbidden.status_code,
              "invalid_source_credential_http": bad.status_code, "batch_id": batch_id, "batch": batch,
              "zip_sha256": hashlib.sha256(response.content).hexdigest(), "zip_bytes": len(response.content)}
    (EVIDENCE / "http-flow.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    emit({"status": report["status"], "rows": batch["summary"]["rows"], "source_requests": batch["summary"]["requests"], "zip_bytes": report["zip_bytes"]})


def verify():
    import MySQLdb
    connections = {role: MySQLdb.connect(host="127.0.0.1", port=13326, user="root", passwd=config()["mysql_password"], db=name, charset="utf8mb4") for role, name in DATABASES.items()}
    def sql(role, query):
        with connections[role].cursor() as cursor:
            cursor.execute(query)
            return cursor.fetchall()
    tables = {"platforms": "master_platform", "products": "products_productspu"}
    # Business model table names are explicit in V278.
    count_tables = ["sales_order", "sales_order_item", "inventory_snapshot"]
    counts = {role: {table: sql(role, "SELECT COUNT(*) FROM `" + table + "`")[0][0] for table in count_tables} for role in ("source", "target")}
    assert counts["source"] == counts["target"]
    source_sum = sql("source", "SELECT CAST(SUM(order_total_amount) AS CHAR) FROM sales_order WHERE normalized_status <> 'cancelled'")[0][0]
    target_sum = sql("target", "SELECT CAST(SUM(order_total_amount) AS CHAR) FROM sales_order WHERE normalized_status <> 'cancelled'")[0][0]
    assert source_sum == target_sum
    line_summary = {}
    inventory_summary = {}
    for role in ("source", "target"):
        line_summary[role] = sql(role, "SELECT CAST(SUM(quantity) AS CHAR),CAST(SUM(line_total_amount) AS CHAR) FROM sales_order_item")[0]
        inventory_summary[role] = sql(role, "SELECT SUM(available_qty),SUM(reserved_qty),SUM(JSON_LENGTH(provided_quantity_fields)) FROM inventory_snapshot")[0]
    assert line_summary["source"] == line_summary["target"]
    assert inventory_summary["source"] == inventory_summary["target"]
    constraints = sql("target", "SELECT COUNT(*) FROM sales_order_item i LEFT JOIN sales_order o ON o.id=i.sales_order_id LEFT JOIN products_productsku s ON s.id=i.internal_sku_id WHERE o.id IS NULL OR (i.internal_sku_id IS NOT NULL AND s.id IS NULL)")[0][0]
    assert constraints == 0
    columns = {}
    for role in ("source", "target"):
        columns[role] = sql(role, "SELECT TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COALESCE(COLUMN_DEFAULT,'<NULL>') FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME,ORDINAL_POSITION")
    schema_diff = len(set(columns["source"]) ^ set(columns["target"]))
    assert schema_diff == 0
    credential_rows = sql("target", "SELECT COUNT(*) FROM integrations_platformintegrationconfig WHERE credential_id<>'' OR token_id<>'' OR network_enabled=1 OR sync_read_enabled=1 OR sync_write_enabled=1")[0][0]
    enabled_jobs = sql("target", "SELECT COUNT(*) FROM integrations_syncjob WHERE is_enabled=1")[0][0]
    assert credential_rows == 0 and enabled_jobs == 0
    source_rows = sum(counts["source"].values())
    target_rows = sum(counts["target"].values())
    result = {"status": "LOCAL_MYSQL_SYNTHETIC_ACCEPTANCE_PASS", "source_rows": source_rows, "target_rows": target_rows,
              "schema_diff_count": schema_diff, "constraint_violations": constraints, "mismatched_chunks": [], "sample_artifact": None,
              "recommended_action": "Review local acceptance; stage and configure the intranet service before real-data acceptance.",
              "counts": counts, "non_cancelled_order_amount": str(target_sum), "mysql_version": sql("target", "SELECT VERSION()")[0][0],
              "line_quantity": str(line_summary["target"][0]), "line_amount": str(line_summary["target"][1]),
              "available_stock": str(inventory_summary["target"][0]), "reserved_stock": str(inventory_summary["target"][1]),
              "unsafe_local_source_configs": credential_rows, "enabled_business_sync_jobs": enabled_jobs,
              "production_access": False, "checked_at_utc": datetime.now(timezone.utc).isoformat()}
    (EVIDENCE / "mysql-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for connection in connections.values():
        connection.close()
    emit(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["prepare", "migrate", "seed", "serve-source", "serve-control", "serve-tls", "execute", "verify"])
    args = parser.parse_args()
    try:
        if args.phase.startswith("serve-") and args.phase != "serve-tls":
            serve(args.phase.removeprefix("serve-"))
        else:
            {"prepare": prepare, "migrate": migrate, "seed": seed, "serve-tls": serve_tls, "execute": execute, "verify": verify}[args.phase]()
    except Exception as error:
        emit({"status": "LOCAL_ACCEPTANCE_FAILED", "stage": args.phase, "error_type": type(error).__name__, "raw_error_withheld": True})
        sys.exit(1)
