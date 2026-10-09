#!/usr/bin/env python3
"""Fail-closed validator for the frozen V227 build-only artifact."""
import hashlib, json, os, re, sys, urllib.request
from pathlib import Path

REPO = "dfcy-team/dfcy"
APP = "55c54d57a28b78e3fbcc2bfb87df4b6aeb94fe1e"
PARENT = "8adf0a69a973146070c18c7450eefacc7f7f2829"
RUN, ATTEMPT, ARTIFACT = "37862759870", "1", "11586983699"
MANIFEST_SHA = "f276c03681c2dcb6ba18810a3077b44a46dc209622236449ee2cd743e61d2df1"
BACKEND = "ghcr.io/dfcy-team/dfcy/saas-collab-backend@sha256:f0119999b66cc41b8abbedfeb789ea00870e65bf5bec5e4cd899abde9915f100"
FRONTEND = "ghcr.io/dfcy-team/dfcy/saas-collab-frontend@sha256:ea407bb5199f991ef8534844b7eeea6a6fa9428382a1a11eb0ea15004c4ae469"
REDIS = "redis@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99"
MIGRATION = "b99b19daa091d2a2ba45c4bb4662808a135033ff308bd219d9a84165cc2ea47b"
JOBS = {"validate", "quality", "mysql-lock", "mysql-sales", "mysql-sync-workspace", "build"}
REPOSITORY_ID = 1290869932
ARTIFACT_NAME = "production-build-only-55c54d57a28b78e3fbcc2bfb87df4b6aeb94fe1e-37862759870-1"
FROZEN_FILES = {
    "release-manifest.json": MANIFEST_SHA,
    "build-only-receipt.json": "367204731665680047c89e091005b4b266b8954d56843a0867e04c955e54edc9",
    "index-migration.json": "27c3cb25a095946d21116e4be1e24d9a3751429e6b5a2bb337d5ecbffbc96da8",
    "mysql-gate.json": "825ddac22aba0cf42c2a565a9dd133019ba9b50be06228e0549bdfa54a110820",
    "mysql-sales-gate.json": "754102dc044f400cd83ce6f67ead8c62664bbec13accbad04ff9de270d714081",
    "mysql-sync-workspace-gate.json": "c3b39410f3540b7aa852ded9bf9c91cb2e598f216d3b70c544b65bf6c7815ab6",
    "lock-scope.xml": "48c7b2aaa26ef04c0e27b8be914f44be800ad42f84ba001182905e9db3a61355",
    "preflight-rejection.xml": "c6d302abb4f699e4b2fc5cafc738d10ea70fa3cac25cdbeb5becee82535f914f",
    "related-regression.xml": "159d266ff82b28115164a02be9a4b0d1ea4fc33d6357e26f49a118826bd6120d",
    "sales-regression.xml": "cd77c475c7e3a44b522153b71bcdef382283fc152e5f516af5e4a15f553fd052",
    "sync-workspace-regression.xml": "4982abaa479c6e0200014676c7c1c4a3d83b9ab9403d8390cf708e92b30bde2c",
}

def pairs(items):
    out = {}
    for k, v in items:
        if k in out: raise ValueError("duplicate JSON key")
        out[k] = v
    return out

def read_json(path):
    p = Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size > 1_000_000: raise ValueError("unsafe or oversized artifact file")
    return json.loads(p.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON number")))

def check_artifact(root, manifest=None, receipt=None):
    root = Path(root)
    if root.is_symlink() or not root.is_dir(): raise ValueError("artifact root must be a real directory")
    names = [p.name for p in root.iterdir()]
    if len(names) != len(FROZEN_FILES) or set(names) != set(FROZEN_FILES): raise ValueError("artifact contents must be exactly the eleven frozen files")
    for name, expected_sha in FROZEN_FILES.items():
        p = root / name
        if p.is_symlink() or not p.is_file() or p.stat().st_size > 1_000_000: raise ValueError("unsafe or oversized artifact file")
        if hashlib.sha256(p.read_bytes()).hexdigest() != expected_sha: raise ValueError("frozen artifact file digest mismatch")
    mp, rp = root / "release-manifest.json", root / "build-only-receipt.json"
    if mp.is_symlink() or rp.is_symlink(): raise ValueError("symlink forbidden")
    raw = mp.read_bytes()
    if len(raw) > 1_000_000 or hashlib.sha256(raw).hexdigest() != MANIFEST_SHA: raise ValueError("manifest digest mismatch")
    m = manifest if manifest is not None else read_json(mp)
    r = receipt if receipt is not None else read_json(rp)
    if not isinstance(m, dict) or not isinstance(r, dict): raise ValueError("artifact JSON roots must be objects")
    expected = {"schema_version":1,"environment":"production","repository":REPO,"git_sha":APP,"release_sha":APP,"backend_image":BACKEND,"frontend_image":FRONTEND,"redis_image":REDIS,"migration_sha256":MIGRATION,"compose_sha256":"owner-controlled-on-target"}
    if m != expected: raise ValueError("manifest fields differ from frozen release")
    if (r.get("schema_version"),r.get("status"),r.get("baseline_git_sha"),r.get("git_sha"),r.get("manifest_sha256"),r.get("workflow_run_id"),r.get("workflow_run_attempt")) != (1,"BUILT_NOT_DEPLOYED",PARENT,APP,MANIFEST_SHA,RUN,ATTEMPT): raise ValueError("receipt binding/status mismatch")
    for k in ("vm_mutated","cloud_mutated","ledger_mutated","deployment_authorized_by_this_receipt","compose_runtime_verified"):
        if r.get(k) is not False: raise ValueError("receipt safety assertion mismatch")
    g = r.get("mysql_gate", {})
    if not isinstance(g, dict) or g.get("status") != "PASS_REAL_MYSQL_CURRENT_MODEL_SCHEMA" or g.get("production_database_used") is not False or g.get("mysql") != "8.4.11" or g.get("django") != "5.2.17": raise ValueError("mysql gate metadata mismatch")
    suites = g.get("suites", {})
    for name, count in (("lock-scope",9),("related-regression",132),("preflight-rejection",6)):
        s = suites.get(name, {})
        if (s.get("passed"),s.get("failed"),s.get("skipped")) != (count,0,0): raise ValueError("mysql suite counts mismatch")
    sg = r.get("mysql_sales_gate", {})
    if (sg.get("status"),sg.get("testcases"),sg.get("failed"),sg.get("skipped"),sg.get("mysql"),sg.get("django")) != ("PASS_REAL_MYSQL_SALES_CURRENT_MODEL_SCHEMA",85,0,0,"8.4.11","5.2.17"): raise ValueError("mysql sales gate mismatch")
    mig = sg.get("index_migration", {})
    if (mig.get("status"),mig.get("migration"),mig.get("index"),mig.get("columns"),mig.get("forward_and_reverse_checked"),mig.get("rows_unchanged"),mig.get("rows_before"),mig.get("rows_after")) != ("pass","commerce.0006_salesorder_currency_catalog_idx","idx_sales_order_currency",["tenant_id","currency"],True,True,0,0): raise ValueError("migration forward/reverse evidence mismatch")
    wg = r.get("mysql_sync_workspace_gate", {})
    if (wg.get("status"),wg.get("testcases"),wg.get("failed"),wg.get("skipped"),wg.get("mysql"),wg.get("django")) != ("PASS_REAL_MYSQL_SYNC_WORKSPACE_CURRENT_MODEL_SCHEMA",128,0,0,"8.4.11","5.2.17"): raise ValueError("sync workspace gate mismatch")
    return True

def api_json(path):
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"}
    if token: headers["Authorization"] = "Bearer "+token
    req = urllib.request.Request("https://api.github.com/repos/dfcy-team/dfcy/"+path, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp: return json.load(resp)

def verify_api(run=None, artifact=None, jobs=None):
    run = run if run is not None else api_json("actions/runs/"+RUN+"/attempts/"+ATTEMPT)
    artifact = artifact if artifact is not None else api_json("actions/artifacts/"+ARTIFACT)
    jobs = jobs if jobs is not None else api_json("actions/runs/"+RUN+"/attempts/"+ATTEMPT+"/jobs?per_page=100")
    if any((str(run.get("id")) != RUN, str(run.get("run_attempt")) != ATTEMPT, run.get("name") != "Production Artifacts Build Only", run.get("head_sha") != APP, run.get("head_branch") != "main", run.get("event") != "workflow_dispatch", run.get("status") != "completed", run.get("conclusion") != "success", run.get("repository",{}).get("full_name") != REPO)): raise ValueError("build run metadata mismatch")
    ar = artifact.get("workflow_run", {})
    if any((str(artifact.get("id")) != ARTIFACT, artifact.get("expired") is not False, artifact.get("name") != ARTIFACT_NAME, str(ar.get("id")) != RUN, ar.get("head_sha") != APP, ar.get("head_branch") != "main", ar.get("repository_id") != REPOSITORY_ID)): raise ValueError("artifact metadata mismatch")
    js = jobs.get("jobs", [])
    if jobs.get("total_count") != 6 or len(js) != 6 or {j.get("name") for j in js} != JOBS or len({j.get("name") for j in js}) != 6 or any((j.get("status") != "completed" or j.get("conclusion") != "success") for j in js): raise ValueError("build job set/status mismatch")

def validate_context():
    if os.environ.get("GITHUB_REPOSITORY") != REPO or os.environ.get("GITHUB_REF") != "refs/heads/main": raise ValueError("fixed repository/main ref required")
    control = os.environ.get("APPROVED_CONTROL_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", control) or os.environ.get("GITHUB_SHA") != control or control == APP: raise ValueError("approved control SHA must equal this distinct workflow commit")
    operation = os.environ.get("OPERATION", "")
    if operation not in ("dry_run", "deploy"): raise ValueError("invalid operation")
    actor = os.environ.get("GITHUB_ACTOR", "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", actor): raise ValueError("invalid actor")
    return control, operation, actor

def main():
    control, operation, actor = validate_context()
    check_artifact(sys.argv[1])
    verify_api()
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
        for k,v in {"release_sha":APP,"backend_image":BACKEND,"frontend_image":FRONTEND,"redis_image":REDIS,"migration_sha":MIGRATION,"manifest_sha":MANIFEST_SHA,"registry_user":actor}.items(): f.write(f"{k}={v}\n")
    evidence = {"source_sha":APP,"control_sha":control,"run_id":RUN,"run_attempt":ATTEMPT,"artifact_id":ARTIFACT,"manifest_sha256":MANIFEST_SHA,"backend_image":BACKEND,"frontend_image":FRONTEND,"redis_image":REDIS,"migration_sha256":MIGRATION,"provenance":"PASS","deployed":False}
    Path(os.environ["SAFE_EVIDENCE_PATH"]).write_text(json.dumps(evidence, separators=(",",":"))+"\n", encoding="utf-8")
    print("Frozen V227 artifact and build provenance verified; this is not deployment completion.")
if __name__ == "__main__":
    try: main()
    except Exception as e: print("verification failed: "+type(e).__name__, file=sys.stderr); sys.exit(1)
