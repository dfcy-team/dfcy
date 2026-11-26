"""Read-only verification of the exact cumulative V542 source control."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

if not __debug__:
    raise RuntimeError("Optimized Python disables release gates")

EXPECTED_SOURCE = "2c1f39c79e08ec6a54d6dff968f4955bc8921405"
EXPECTED_TREE = "471a3ee9c7fdb32ed58b4a45fad3e6694a493bd3"
EXPECTED_PARENT = "4006bf530bfde783f54c4110773e8397aca3ec97"
EXPECTED_MIGRATIONS = "d5f68b6aa440030cd081c19e1225c5824b1b56110b56ebc40b0a5761413cfdde"
IDENTITY_NAME = "v542-cumulative-source-identity.json"


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise RuntimeError(reason)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], stderr=subprocess.PIPE).decode().strip()


def blob(revision: str, path: str) -> bytes:
    oid = git("rev-parse", f"{revision}:{path}")
    return subprocess.check_output(["git", "cat-file", "blob", oid], stderr=subprocess.PIPE)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def decode_capture(capture: dict, label: str) -> bytes:
    encoded = capture["raw_base64"]
    require(isinstance(encoded, str) and encoded, f"{label} raw capture missing")
    raw = base64.b64decode(encoded, validate=True)
    require(digest(raw) == capture["artifact_sha256"], f"{label} capture SHA mismatch")
    return raw


identity_path = Path(__file__).with_name(IDENTITY_NAME)
require(identity_path.is_file(), "V542 source identity missing")
identity = json.loads(identity_path.read_text(encoding="utf-8"))

# Exact candidate, parent, and four-commit first-parent chain.
source = identity["source"]
require(source["sha"] == EXPECTED_SOURCE, "source SHA is not current V542 candidate")
require(source["tree_sha"] == EXPECTED_TREE, "source tree SHA mismatch")
require(source["parent_sha"] == EXPECTED_PARENT, "source parent SHA mismatch")
require(source["commit_count"] == 4 and len(source["commits"]) == 4, "expected four cumulative source commits")
require(source["pull_request"] == 644, "unexpected source pull request")
require(git("rev-parse", "HEAD") == source["sha"], "Git HEAD does not match source")
require(git("rev-parse", "HEAD^{tree}") == source["tree_sha"], "Git tree does not match source tree")
require(git("rev-parse", f"HEAD~{source['commit_count']}") == source["parent_sha"], "Git parent mismatch")
require(git("rev-list", "--count", source["parent_sha"] + "..HEAD") == "4", "Git source commit count mismatch")
commits = git("rev-list", "--reverse", "--first-parent", source["parent_sha"] + "..HEAD").splitlines()
require(len(commits)==4 and commits == source["commits"], "Git source commit sequence mismatch")

# The control is bound to an explicitly selected deploy action on main.
for key in ("GITHUB_REPOSITORY", "GITHUB_REF", "GITHUB_SHA", "EXPECTED_CONTROL_SHA", "REQUESTED_ACTION", "REQUESTED_TRANSPORT"):
    require(bool(os.environ.get(key)), f"required control environment variable missing: {key}")
require(os.environ["GITHUB_REPOSITORY"] == "dfcy-team/dfcy", "unexpected control repository")
require(os.environ["GITHUB_REF"] == "refs/heads/main", "control must run on main")
require(re.fullmatch(r"[0-9a-f]{40}", os.environ["GITHUB_SHA"]) is not None, "invalid control SHA")
require(os.environ["EXPECTED_CONTROL_SHA"] == os.environ["GITHUB_SHA"], "control SHA binding mismatch")
require(os.environ["REQUESTED_ACTION"] == "deploy", "control action must be deploy")
require(os.environ["REQUESTED_TRANSPORT"] == "ssh", "control transport must be ssh")

# Exact file inventory and content hashes, including byte-identical menu files.
files = identity["files"]
require(isinstance(files, dict) and len(files)==43, "source file hash map missing")
changed = set(git("diff", "--name-only", source["parent_sha"], "HEAD").splitlines())
require(changed == set(files), "source changed-path inventory differs from identity")
for path, expected in files.items():
    require(digest(blob("HEAD", path)) == expected, f"source file SHA mismatch: {path}")

baseline = identity["baseline"]
require(baseline["sha256"] == "51450667e389d8cd30d8e93e17eec5572103ad1638e3b4024180baa31995c2f4", "independently approved V537 baseline mismatch")
require(re.fullmatch(r"[0-9a-f]{64}", baseline["sha256"]) is not None, "invalid approved baseline digest")
require(bool(os.environ.get("EXPECTED_BASELINE_SHA")) and baseline["sha256"] == os.environ["EXPECTED_BASELINE_SHA"], "baseline SHA environment binding mismatch")
require(baseline["source_sha"] == source["parent_sha"] and baseline["version"] == "2.44.537", "approved baseline source/version mismatch")
require((baseline["tables"], baseline["migration_nodes"]) == (423,542), "approved baseline counts mismatch")

protected_menu = identity["protected_menu_files"]
require(set(protected_menu)=={'saas-collab-system/frontend/src/router/index.js','saas-collab-system/frontend/src/router/integrationNavigation.js','saas-collab-system/frontend/src/router/menuRegistry.js','saas-collab-system/frontend/src/layouts/MainLayout.vue','saas-collab-system/frontend/src/router/menu.js','saas-collab-system/frontend/src/views/inventory/InventoryWorkbench.vue','saas-collab-system/frontend/src/views/inventory/CategoryInventory.vue','saas-collab-system/backend/apps/permissions/menu_registry.json'}, 'exact eight protected menu files required')
for path, expected in protected_menu.items():
    parent_bytes = blob(source["parent_sha"], path)
    head_bytes = blob("HEAD", path)
    require(parent_bytes == head_bytes, f"protected menu file changed: {path}")
    require(digest(parent_bytes) == expected, f"protected menu baseline SHA mismatch: {path}")

require(identity['title_only_files'] == [], 'no navigation/title changes authorized for V542')

# Recompute the full canonical migration fingerprint and preserve every old migration.
migration = identity["migration"]
require(migration["canonical_sha256"] == EXPECTED_MIGRATIONS, "unexpected V542 canonical migration SHA")
migration_paths = sorted(p for p in git("ls-tree", "-r", "--name-only", "HEAD").splitlines()
    if "/backend/apps/" in p and "/migrations/" in p and p.endswith(".py"))
h = hashlib.sha256()
for path in migration_paths:
    h.update(path.split("/backend/", 1)[1].encode())
    h.update(blob("HEAD", path))
require(h.hexdigest() == migration["canonical_sha256"], "full migration fingerprint mismatch")
changed_migrations = {p for p in changed if "/migrations/" in p and p.endswith(".py")}
require(changed_migrations == set(migration["new_paths"]), "unexpected migration path delta")
parent_migrations = [p for p in git("ls-tree", "-r", "--name-only", source["parent_sha"]).splitlines()
    if "/backend/apps/" in p and "/migrations/" in p and p.endswith(".py")]
for path in parent_migrations:
    require(blob(source["parent_sha"], path) == blob("HEAD", path), f"historical migration changed: {path}")

# Actual wrapper stdout receipt is embedded in identity; verify its byte hash before parsing.
rehearsal_capture = identity["rehearsal"]
receipt_raw = decode_capture(rehearsal_capture, "rehearsal receipt")
require(digest(receipt_raw) == "e846aa47c3d459d789ad31f2dd987e6e5ca0cb39e693a22d5a556fac1fd6e0c6", "independently approved actual R3 checkpoint receipt mismatch")
receipt = json.loads(receipt_raw.decode("utf-8"))
require(receipt["status"] == "PASS", "remote wrapper did not pass")
require(receipt["source_sha"] == source["sha"], "wrapper source SHA mismatch")
require(receipt["backup_sha256"] == rehearsal_capture["backup_sha256"], "wrapper backup SHA mismatch")
require(receipt["source_archive_sha256"] == rehearsal_capture["source_archive_sha256"], "wrapper archive SHA mismatch")
require(receipt["backup_sha256"] == "477238b6f5e5854c4835098fc63a5321fd88eb7e7951915c9c852b5740b51c6b", "approved rehearsal backup mismatch")
require(receipt["source_archive_sha256"] == "4340397cf70a20233e08d5875092ff2951ccdb00407bcfefd81a6af700e3d37a", "approved source archive mismatch")
require(receipt["cleanup_verified"] is True, "wrapper cleanup was not verified")
require(receipt["protected_state_unchanged"] is True, "protected release files changed")
require(receipt["production_app_unchanged"] is True, "production app container changed")
require(receipt["test_artifacts_retained"] is True, "test artifacts were not retained")
require(receipt["approved_checkpoint_sha256"] == baseline["sha256"], "wrapper checkpoint binding mismatch")
require(receipt["production_roles_unchanged"] is True and receipt["production_roles_verified"] == 14, "production role preservation mismatch")
checks = receipt["isolation_checks"]
require(checks["db_network"] == "none" and checks["probe_shares_db_network"] is True, "network isolation checks failed")

# The probe uses its real nested receipt schema; do not infer proof from wrapper status.
probe = receipt["probe_receipt"]
require(probe["checkpoint_sha256"] == baseline["sha256"] and probe["checkpoint_tables_verified"] == 420 and probe["checkpoint_rows_verified"] == 3565000 and probe["checkpoint_metadata_tables_verified"] == 3, "restored backup does not exactly match approved checkpoint")
require(baseline["protected_tables"] == 420 and baseline["protected_rows"] == 3565000, "approved checkpoint row scope mismatch")
require(probe["status"] == "PASS", "database probe failed")
require(probe["source_sha"] == source["sha"], "probe source SHA mismatch")
require(probe["source_tree"] == source["tree_sha"], "probe source tree mismatch")
require(probe["before"] == {"tables":423,"nodes":542}, "probe parent counts mismatch")
require(probe["after"] == {"tables":423,"nodes":544,"new_tables":0,"old_data_tables_hashed":420,"schema_delta":4,
    "added_nullable_columns":["influencers_tiktokvideosyncevidence.payload_object_key","influencers_tiktokvideosyncevidence.payload_storage_alias","supply_chain_paymentvoucher.content_object_key","supply_chain_paymentvoucher.content_storage_alias"],
    "old_fields_unchanged":True,"old_indexes_unchanged":True,"second_plan_empty":True}, "probe actual after-schema mismatch")
require(receipt['operation'].startswith('saas-v542-rehearsal-r3-2c1f39c7-477238b6-'), 'not approved R3 operation')
require(checks['db_labels'] is True, 'isolated ownership labels not checked')
tests=probe['tests']
require(tests['tests']>=61 and all(tests[k]==0 for k in ('failures','errors','skipped')), 'actual isolated MySQL tests not clean')
contention=probe['contention']
require(contention['status']=='PASS' and contention['connections']==2 and contention['mysql_code']==3572 and contention['conflict_status_code']==409 and contention['rollback_usable'] is True and contention['after_release_acquired'] is True and 0<=contention['elapsed_seconds']<5, 'actual MySQL NOWAIT/rollback proof missing')
require(probe['external_business_calls']==0, 'business collection forbidden')

# Actual local regression provenance and deferred acceptance limits.
local_raw=decode_capture(identity['local_validation'],'local validation')
require(digest(local_raw)=='0981a714a90803a3be14c9b3f0e3d9de5db020e56f441efb825cea959d60fd95','independently approved local validation mismatch')
local=json.loads(local_raw)
require(local['status']=='PASS' and local['source_sha']==source['sha'] and local['source_tree_sha']==source['tree_sha'] and local['migration_sha256']==EXPECTED_MIGRATIONS,'local source identity mismatch')
require(local['backend_combined']['passed']==155 and local['backend_combined']['skipped']==0 and local['backend_combined']['database']=='SQLite --nomigrations','bounded backend regression scope mismatch')
require(local['frontend_tests']['passed']==2592 and local['frontend_tests']['files']==348 and local['frontend_build']['use_mock'] is False,'frontend regression/build scope mismatch')
require(local['frontend_executed_source_sha']=='e6d0129ce6b522f93cfc8df4b296a4761754aec0' and git('rev-parse','HEAD:saas-collab-system/frontend')==git('rev-parse',local['frontend_executed_source_sha']+':saas-collab-system/frontend'),'retained frontend test execution tree mismatch')
build=local['frontend_build']
require(build['executed_source_sha']=='c33d89124af4d2bd741fadc34ad33420d226da1c' and git('rev-parse','HEAD:saas-collab-system/frontend')==git('rev-parse',build['executed_source_sha']+':saas-collab-system/frontend')==build['unchanged_frontend_tree'],'frontend build provenance mismatch')
image_raw=decode_capture(local['current_image_validation'],'local image validation');image=json.loads(image_raw)
require(image['status']=='PASS' and image['source_sha']==image['oci_revision']==source['sha'] and image['source_tree']==source['tree_sha'],'local image source mismatch')
require(image['image_id']==local['local_image']['image_id']=='sha256:04aafe6dd98763774fca5079570f07bf65ab0fa5c0e59db8002026cd0a1cec5a','local image identity mismatch')
require(image['checks']=={'model_check':'PASS','makemigrations':'No changes detected','permission_manifest':'PASS','node_tests':12,'node_failures':0,'node_skipped':0,'network':'none'},'local image checks missing')
require(local['log_sha256'][image['log']]==image['log_sha256'],'image log binding mismatch')
custody_raw=decode_capture(local['custody_synthetic_tls'],'isolated custody TLS/closed operation');custody=json.loads(custody_raw)
require(digest(custody_raw)=='f64fee92d29bdbd075b1c0ec2d405cee90b6cfdd3191ac56ee49d5e8346c3e5d' and custody['status']=='PASS' and custody['source_sha']==custody['oci_revision']==source['sha'] and custody['source_tree_sha']==source['tree_sha'] and custody['image_id']==image['image_id'],'actual isolated custody proof/source mismatch')
require(custody['network']=='none' and custody['workers']==2 and custody['synthetic_only'] is True and custody['external_business_calls']==0 and custody['health_status']==200 and custody['unauthenticated_status']==401 and custody['record_count']==1,'bounded custody TLS test scope mismatch')
require(all(custody[key] is True for key in ('tls_hostname_verified','tls_ca_verified','late_payload_same_as_accepted','closed_reference_matches','closed_marker_verified','records_after_late_request_unchanged','late_store_rejected','encrypted_payload_absent')),'closed-operation/TLS preservation proof missing')
alias=json.loads(decode_capture(local['oss_aliases_before'],'OSS aliases'))
roles={'backend','celery','celery-control','celery-credentials','celery-beat','celery-background','celery-history','celery-video','celery-realtime-board','celery-finance-summary','celery-warehouse-fees'}
require(alias['read_only'] is True and set(alias['alias_nonempty'])==roles and all(v=={'TIKTOK_VIDEO_EVIDENCE_STORAGE_ALIAS':False,'PAYMENT_VOUCHER_STORAGE_ALIAS':False} for v in alias['alias_nonempty'].values()),'OSS aliases must remain off')
inventory=json.loads(decode_capture(local['finance_dataset_inventory'],'finance dataset inventory'))
require(inventory['read_only'] is True and inventory['database_writes']==0 and inventory['datasets']==[],'actual finance dataset scope mismatch')
compat_cap=local['finance_empty_template_compatibility'];compat=json.loads(decode_capture(compat_cap,'empty-template finance compatibility'))
require(compat['template_html_bytes']==275245 and bool(compat['snapshot_arrays']) and all(n==0 for n in compat['snapshot_arrays'].values()),'empty-template workload scope mismatch')
require(set(compat['runs'])=={'baseline','current'} and all(len(v)==3 for v in compat['runs'].values()),'bounded compatibility process count mismatch')
require(all(x['exit']==0 and len(x['responses'])==2 and all(y['ok'] is True for y in x['responses']) and x['sha256']=='d3249279c1eb7937190161684d750269e51e0fa2f4e236471a35daeabfa4ef2a' for group in compat['runs'].values() for x in group),'twelve compatibility responses not equal/successful')
events=dict(line.split() for line in compat['memory_events'].splitlines());require(events['oom']==events['oom_kill']=='0' and 0<int(compat['memory_peak'])<=2684354560,'compatibility memory/OOM proof mismatch')
require(compat_cap['executed_finance_source']=='44d4c1965adb9240de538b96bf7433bbbf941245' and compat_cap['unchanged_finance_tree']==git('rev-parse','HEAD:saas-collab-system/backend/apps/finance')==git('rev-parse',compat_cap['executed_finance_source']+':saas-collab-system/backend/apps/finance'),'compatibility finance tree provenance mismatch')
require(local['actual_mysql_pending'] is False and local['actual_mysql_receipt_sha256']==digest(receipt_raw) and local['VM_deployment_complete'] is False and len(local['limits'])>=6,'MySQL binding or deferred acceptance limits missing')
require(identity['production_acceptance'] is False,'identity cannot assert production acceptance')

# GitHub reads only; credentials are never embedded or printed.
token = os.environ.get("GH_API_TOKEN")
require(bool(token), "GH_API_TOKEN is required")

def api(path: str):
    request = urllib.request.Request("https://api.github.com/repos/dfcy-team/dfcy/" + path,
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)

pr = api(f"pulls/{source['pull_request']}")
require(pr["head"]["sha"] == source["sha"], "PR head mismatch")
require(pr["base"]["ref"] == "release/v534-v537-vm" and pr["base"]["sha"] == source["parent_sha"], "PR base mismatch")
expected_jobs = {
    "phase2-ci.yml": {"Repository safety and file guard", "Django and pytest", "Frontend build observation gate", "Docker Compose configuration", "RPA samples and required documents"},
    "phase3-ci.yml": {"Repository safety and forbidden file guard", "Phase 3 Django, data quality, and pytest", "Frontend build without dependency lifecycle scripts", "Docker Compose placeholder configuration", "RPA samples and Phase 3 documents"},
}
ci_runs = identity["source_ci_runs"]
require(set(ci_runs) == set(expected_jobs), "exact Phase 2 and Phase 3 CI runs required")
verified = set()
for workflow, run_id in ci_runs.items():
    run = api(f"actions/runs/{run_id}")
    require(run_id == {"phase2-ci.yml":45731538032,"phase3-ci.yml":45731538024}[workflow] and run["id"] == run_id and run["head_sha"] == source["sha"], "CI run source mismatch")
    require(run["path"] == ".github/workflows/" + workflow and run["event"] == "pull_request", "CI workflow/event mismatch")
    require(run["run_attempt"] == 1 and run["head_branch"] == pr["head"]["ref"], "CI is not first attempt on current PR head")
    require(run["status"] == "completed" and run["conclusion"] == "success", "source CI did not pass")
    jobs = api(f"actions/runs/{run_id}/attempts/1/jobs?per_page=100")
    names = {job["name"] for job in jobs["jobs"]}
    require(jobs["total_count"] == len(jobs["jobs"]) == 5 and names == expected_jobs[workflow], "expected CI job names/count mismatch")
    require(not (names & verified), "duplicate CI job name across workflows")
    for job in jobs["jobs"]:
        require(job["run_id"] == run_id and job["run_attempt"] == 1 and job["head_sha"] == source["sha"], "CI job source/attempt mismatch")
        require(job["status"] == "completed" and job["conclusion"] == "success", "source CI job did not pass")
    verified.update(names)
require(verified == set.union(*expected_jobs.values()), "not all ten source CI jobs verified")

print("V542 exact source, MySQL receipt, protected history, and first-attempt PR CI verified")
