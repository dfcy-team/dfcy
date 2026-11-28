"""Fail-closed, read-only exact-source and rehearsal gate for cumulative V561."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

SOURCE = "178d4ce1878c81e3e32dcd0ca84209347b0565ed"
TREE = "1662e8bf90c443c39dc732c4e782cd6cb4523a06"
PARENT = "ea40fc102015ece64157a7ff88e69fcf8be99818"
CONTROL_BASE = "8a351ec227cb252dc768b6129c041efd97fce275"
MIGRATION = "b60515d62d0de8c380f015f93fce1a61045a995017f92d1c72d4d5cc123e86df"
ARCHIVE_SHA = "8b50c31dd34a59ae2ac78eb2effc9bb5f380b220446965b7e068b2612f5bb26a"
ARCHIVE_BYTES = 27797581
BRANCH = "release/v558-v560-vm-20261128"
SOURCE_PR = 661
SOURCE_RUNS = {"phase2-ci.yml": 46106384338, "phase3-ci.yml": 46106393483}
EXPECTED_JOBS = {
    "phase2-ci.yml": {
        "Frontend build observation gate", "Docker Compose configuration",
        "Django and pytest", "Repository safety and file guard",
        "RPA samples and required documents",
    },
    "phase3-ci.yml": {
        "Repository safety and forbidden file guard",
        "Phase 3 Django, data quality, and pytest",
        "Frontend build without dependency lifecycle scripts",
        "Docker Compose placeholder configuration", "RPA samples and Phase 3 documents",
    },
}

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def git(*args):
    return subprocess.check_output(["git", *args], stderr=subprocess.PIPE).decode().strip()

_BLOB_CACHE = {}

def prefetch_blobs(refs):
    unique = list(dict.fromkeys(refs))
    payload = b"".join(ref.encode() + b"\n" for ref in unique)
    output = subprocess.check_output(["git", "cat-file", "--batch"], input=payload, stderr=subprocess.PIPE)
    cursor = 0
    for ref in unique:
        header_end = output.find(b"\n", cursor)
        require(header_end >= 0, "git cat-file batch header truncated")
        header = output[cursor:header_end].split()
        require(len(header) == 3 and header[1] == b"blob", "expected a source blob for " + ref)
        size = int(header[2])
        start, end = header_end + 1, header_end + 1 + size
        require(end < len(output) and output[end:end + 1] == b"\n", "git cat-file batch body truncated")
        _BLOB_CACHE[tuple(ref.split(":", 1))] = output[start:end]
        cursor = end + 1

def blob(rev, path):
    cached = _BLOB_CACHE.get((rev, path))
    if cached is not None:
        return cached
    return subprocess.check_output(["git", "cat-file", "blob", git("rev-parse", rev + ":" + path)], stderr=subprocess.PIPE)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

def api(path):
    token = os.environ.get("GH_API_TOKEN") or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    require(bool(token), "read-only GitHub token required")
    request = urllib.request.Request(
        "https://api.github.com/repos/dfcy-team/dfcy/" + path,
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)

def menu_at(revision):
    base = "saas-collab-system/frontend/src/"
    text = blob(revision, base + "router/menu.js").decode()
    for relative, path in [("../utils/apiAccessAdmin.js", "utils/apiAccessAdmin.js"), ("./menuRegistry.js", "router/menuRegistry.js")]:
        uri = "data:text/javascript;base64," + __import__("base64").b64encode(blob(revision, base + path)).decode()
        require(text.count("'" + relative + "'") == 1, "menu imports drifted from reviewed parser")
        text = text.replace("'" + relative + "'", json.dumps(uri))
    uri = "data:text/javascript;base64," + __import__("base64").b64encode(text.encode()).decode()
    program = "const m=await import(" + json.dumps(uri) + ");\nconst visual=(items)=>items.map(x=>({label:x.label??null,title:x.title??null,path:x.path??null,icon:x.icon??null,children:Array.isArray(x.children)?visual(x.children):[]}));\nprocess.stdout.write(JSON.stringify(visual(m.menuItems)));"
    return json.loads(subprocess.check_output(["node", "--input-type=module"], input=program.encode(), timeout=30))

def validate_pending_receipts(identity):
    b = identity["baseline"]
    require(b["status"] == "PASS" and isinstance(b["sha256"], str) and len(b["sha256"]) == 64, "fresh full read-only baseline receipt is pending")
    require(b["artifact"] == "snapshot561-before-full.json" and b["physical_table_count"] == 439 and b["migration_nodes"] == 558, "baseline schema or migration inventory mismatch")
    require(b["business_table_count"] == 436 and b["business_rows"] == 3590077 and b["read_only"] is True and b["database_writes"] == 0, "baseline row/RBAC read-only receipt mismatch")
    require(isinstance(b.get("database_schema_sha256"), str) and len(b["database_schema_sha256"]) == 64, "baseline schema digest missing")
    require(isinstance(b.get("business_hash_index_sha256"), str) and len(b["business_hash_index_sha256"]) == 64, "baseline business digest missing")
    require(b["roles"] == {"DataScope": 13, "Role": 13, "Role.permissions": 1332, "RoleResourcePolicy": 0, "UserRole": 20}, "baseline role counts mismatch")
    require(set(b.get("role_hashes", {})) == {"DataScope", "Role", "Role.permissions", "RoleResourcePolicy", "UserRole"} and all(isinstance(v, str) and len(v) == 64 for v in b["role_hashes"].values()), "baseline role digests incomplete")
    require(identity.get("baseline_sha256") == b["sha256"], "baseline identity is not bound")

    backup = identity["backup"]
    require(backup["status"] == "PASS" and isinstance(backup["sha256"], str) and len(backup["sha256"]) == 64, "fresh sealed private backup is pending")
    require(type(backup["bytes"]) is int and backup["bytes"] > 0 and backup["gzip_integrity"] == "PASS", "sealed backup integrity/size missing")
    require(backup["source_parent_sha"] == PARENT and backup["preserved_existing_backups"] is True and backup["private_destination"] is True, "backup parent, privacy, or retention proof mismatch")
    require(isinstance(backup.get("receipt_canonical_sha256"), str) and len(backup["receipt_canonical_sha256"]) == 64 and isinstance(backup.get("created_at_utc"), str), "sealed backup receipt is not bound")
    backup_receipt = dict(backup); backup_digest = backup_receipt.pop("receipt_canonical_sha256")
    require(sha(canonical(backup_receipt)) == backup_digest, "sealed backup receipt digest mismatch")

    r = identity["rehearsal"]
    require(r["status"] == "PASS" and isinstance(r["receipt_canonical_sha256"], str) and len(r["receipt_canonical_sha256"]) == 64, "actual private rehearsal receipt is pending")
    require((r["source_sha"], r["tree"], r["parent_sha"]) == (SOURCE, TREE, PARENT), "rehearsal source binding mismatch")
    require(r["baseline_sha256"] == b["sha256"] and r["backup_sha256"] == backup["sha256"], "rehearsal is not bound to the fresh baseline and backup")
    require(r["testcases_sha256"] == identity["expected_testcases_sha256"], "private MySQL test case set drift")
    tests = r["tests"]
    require((tests["count"], tests["passed"], tests["failures"], tests["errors"], tests["skipped"]) == (23, 23, 0, 0, 0), "all 23 exact private MySQL cases must pass")
    require(all(isinstance(tests.get(k), str) and len(tests[k]) == 64 for k in ("junit_sha256", "log_sha256")), "retained JUnit/log digests missing")
    m = r["migration"]
    require(m["status"] == "PASS" and m["before"] == m["after"] == {"tables": 439, "nodes": 558, "business_rows": 3590077}, "no-DDL or restore-data equivalence receipt mismatch")
    require(m["new_migration_paths"] == [] and m["ddl_count"] == 0 and m["roles_unchanged"] is True and m["restore_data_unchanged"] is True, "rehearsal changed DDL, roles, or restored data")
    require(m["schema_sha256_before"] == m["schema_sha256_after"] and m["business_hash_sha256_before"] == m["business_hash_sha256_after"], "before/after restored database hashes differ")
    require(all(isinstance(m.get(k), str) and len(m[k]) == 64 for k in ("schema_sha256_before", "business_hash_sha256_before")), "rehearsal before/after hash receipt missing")
    resources = r["resources"]
    require(resources["status"] == "PASS" and (resources["db_mib"], resources["probe_mib"], resources["max_combined_mib"], resources["host_reserve_mib"]) == (768, 512, 1280, 384), "private rehearsal resource caps drift")
    require(resources["swap_disabled"] is True and type(resources["available_mib_before"]) in (int, float) and resources["available_mib_before"] >= 1664, "private rehearsal host resource floor missing")
    removed = resources["containers_removed"]
    require(isinstance(removed, list) and len(removed) == 2 and len(removed) == len(set(removed)) and all(isinstance(x, str) and x for x in removed), "owned temporary container cleanup receipt missing")
    require(resources["all_owned_temporary_containers_removed"] is True and isinstance(resources["post_cleanup_receipt_sha256"], str) and len(resources["post_cleanup_receipt_sha256"]) == 64, "post-cleanup proof missing")
    require(r["private_artifacts_retained"] is True and r["production_database_used"] is False and r["business_writes"] == 0 and r["external_business_calls"] == 0, "rehearsal isolation or private evidence retention failure")
    receipt = dict(r); receipt_digest = receipt.pop("receipt_canonical_sha256")
    require(sha(canonical(receipt)) == receipt_digest, "actual rehearsal receipt digest mismatch")
    require(m["schema_sha256_before"] == b["database_schema_sha256"] and m["business_hash_sha256_before"] == b["business_hash_index_sha256"], "private restore hashes must match the actual full baseline")
    raw_backup = backup["raw_receipt"]
    require(sha(canonical(raw_backup)) == backup["raw_receipt_canonical_sha256"], "raw actual backup receipt digest mismatch")
    require(raw_backup["status"] == "PASS" and raw_backup["source_sha"] == SOURCE and raw_backup["parent_sha"] == PARENT and raw_backup["sha256"] == backup["sha256"] and raw_backup["bytes"] == backup["bytes"], "raw backup identity mismatch")
    require(raw_backup["candidate_identity"] == {"source_sha": SOURCE, "tree": TREE, "parent_sha": PARENT, "source_archive_sha256": ARCHIVE_SHA, "checkpoint_sha256": b["sha256"]}, "raw backup frozen input closure")
    require(raw_backup["gzip_integrity"] == "PASS" and raw_backup["tables"] == 439 and raw_backup["migration_nodes"] == 558 and raw_backup["business_writes"] == 0 and raw_backup["publication"] == "atomic_no_replace_hardlink" and raw_backup["private_stage_retained"] is True, "actual backup safety closure")
    raw = r["raw_receipt"]
    require(sha(canonical(raw)) == r["raw_receipt_canonical_sha256"] and raw["status"] == "PASS", "actual raw rehearsal receipt missing or altered")
    require((raw["source_sha"], raw["tree"], raw["parent_sha"], raw["checkpoint_sha256"], raw["backup_sha256"]) == (SOURCE, TREE, PARENT, b["sha256"], backup["sha256"]), "actual raw rehearsal frozen inputs mismatch")
    require(raw["business_writes"] == raw["external_calls"] == 0 and raw["production_runtime_unchanged"] is True and raw["private_probe_artifacts_retained"] is True, "actual raw rehearsal side effects")
    require(raw["removed_own_containers"] == removed and set(raw["terminal"]) == {raw["operation"] + "-db", raw["operation"] + "-probe"}, "both exact private containers must be cleaned")
    require({v["id"] for v in raw["terminal"].values()} == set(removed), "distinct exact terminal IDs")
    for name, terminal in raw["terminal"].items():
        require(terminal["status"] == "running" and terminal["image_id"] == (raw["mysql_image_id"] if name.endswith("-db") else raw["dependency_runtime_image_id"]), "terminal running/image identity")
        cap = (768 if name.endswith("-db") else 512) * 2**20
        require(terminal["id"] in removed and terminal["oom_killed"] is False and terminal["restart_count"] == 0 and terminal["memory"] == terminal["swap"] == cap, "actual terminal container health/caps")
    require(raw["mysql_image_id"] == "sha256:8dbcf531a03aade657e181b9cf2f1d1803ce621a1d55610cb44cb531ab7d7db6" and raw["dependency_runtime_image_id"] == "sha256:4fa5d9b1a11e5705886426323c2f2f4cf5ba284127de3acd5ad64d45df3614a8", "exact private MySQL and dependency image IDs")
    require(raw["tests"]["expected_testcases_sha256"] == "279adc5200f4950cdc4ba119b867be22a3eae7cd01cba98fb3860cc5168d451a", "actual private test manifest file seal")
    raw_limits = raw["resource_limits"]
    require(raw_limits["available_kib_before"] >= 1664 * 1024 and resources["available_mib_before"] == raw_limits["available_kib_before"] / 1024, "actual KiB/MiB resource floor binding")
    require(raw["tests"]["tests"] == {"tests": 23, "failures": 0, "errors": 0, "skipped": 0} and raw["tests"]["production_database_used"] is False and raw["tests"]["junit_sha256"] == tests["junit_sha256"] and raw["tests"]["log_sha256"] == tests["log_sha256"], "actual private JUnit bindings")
    raw_migration = raw["migration"]
    require(raw_migration["status"] == "PASS" and (raw_migration["source_sha"], raw_migration["source_tree"], raw_migration["parent_sha"], raw_migration["migration_sha256"], raw_migration["baseline_sha256"], raw_migration["backup_sha256"]) == (SOURCE, TREE, PARENT, MIGRATION, b["sha256"], backup["sha256"]), "raw actual migration proof identity/status missing")
    require(raw_migration["before"] == raw_migration["after"] == {"tables": 439, "nodes": 558, "rows": 3590077} and raw_migration["new_nodes"] == [] and raw_migration["schema_diff_count"] == raw_migration["constraint_violations"] == raw_migration["replay_changed"] == 0 and raw_migration["mismatched_chunks"] == [] and raw_migration["roles_unchanged"] is True, "actual no-DDL data and role closure")
    require(raw_migration["before_snapshot_sha256"] == raw["results_sha256"]["restored-before-snapshot.json"] and raw_migration["after_snapshot_sha256"] == raw["results_sha256"]["migrated-after-snapshot.json"] and raw["tests"]["junit_sha256"] == raw["results_sha256"]["tests.xml"] and raw["tests"]["log_sha256"] == raw["results_sha256"]["tests.log"], "actual retained artifact hashes")
    require(raw_migration["production_database_used"] is False and raw_migration["production_business_writes"] == 0 and raw_migration["raw_rows_exported"] is False, "migration isolation writes/rows")
    final = raw["verify_final"]
    require(final["status"] == "PASS" and (final["source_sha"], final["source_tree"], final["parent_sha"], final["checkpoint_sha256"], final["backup_sha256"], final["migration_sha256"]) == (SOURCE, TREE, PARENT, b["sha256"], backup["sha256"], MIGRATION), "actual final private verification missing or bound to another candidate")
    require(final["expected_testcases_sha256"] == "279adc5200f4950cdc4ba119b867be22a3eae7cd01cba98fb3860cc5168d451a" and final["migration_proof_sha256"] == raw["results_sha256"]["migration-proof.json"] and final["tests_junit_sha256"] == raw["results_sha256"]["tests.xml"] and final["tests_proof_sha256"] == raw["results_sha256"]["tests-proof.json"], "actual final test/migration proof binding mismatch")
    require(final["before_snapshot_sha256"] == raw["results_sha256"]["restored-before-snapshot.json"] and final["after_snapshot_sha256"] == raw["results_sha256"]["migrated-after-snapshot.json"] and final["proof_sha256"] == raw["results_sha256"]["verify-final-proof.json"], "actual final snapshot/proof binding mismatch")
    require(set(raw["results_sha256"]) >= {"tests.xml", "tests.log", "tests-proof.json", "migration-proof.json", "restored-before-snapshot.json", "migrated-after-snapshot.json", "verify-final-proof.json"}, "actual final required artifact hashes missing")
    require(isinstance(raw.get("cleanup_complete"), bool) and raw["cleanup_complete"] is True, "actual rehearsal cleanup completion flag missing")
    require(final["files_sha256"] == {name: raw["results_sha256"][name] for name in ("tests.xml", "tests.log", "tests-proof.json", "migration-proof.json", "restored-before-snapshot.json", "migrated-after-snapshot.json")}, "exact final six-file map")
    require(final["business_rows"] == 3590077 and final["business_writes"] == 0 and final["database_sha256"] == b["final_database_sha256"] and final["roles_sha256"] == b["final_roles_sha256"], "final full database and roles equivalence")
    cleanup_results = raw["cleanup_results"]
    require(set(cleanup_results) == {raw["operation"] + "-db", raw["operation"] + "-probe"}, "both actual temporary-container cleanup results are required")
    require(all(value == {"identity_verified": True, "health_ok": True, "remove_attempted": True, "removed": True} for value in cleanup_results.values()), "actual private-container ownership, health, or removal verification failed")
    cleanup = resources["post_cleanup_receipt"]
    require(cleanup == {"operation": raw["operation"], "terminal": raw["terminal"], "removed_own_containers": removed, "production_runtime_unchanged": True} and sha(canonical(cleanup)) == resources["post_cleanup_receipt_sha256"], "actual post-cleanup receipt binding")
    require(identity["source_ci"]["status"] == "PASS", "exact source CI runs have not passed")

def main():
    require(__debug__, "optimized Python is forbidden for production source gates")
    identity = json.loads(Path(__file__).with_name("v561-cumulative-source-identity.json").read_bytes())
    require(identity.get("schema_version") == 1, "unsupported V561 identity schema")
    require(identity.get("status") == "READY_FOR_OFFICIAL_SOURCE_GATE", "V561 source gate is intentionally fail-closed pending actual rehearsal, baseline, backup, and CI receipts")
    require(identity.get("source_archive") == {"source_sha": SOURCE, "tree": TREE, "archive": "candidate-source561-lf.tar.gz", "sha256": ARCHIVE_SHA, "bytes": ARCHIVE_BYTES, "line_endings": "git canonical LF", "scope": "repository source not production image"}, "source archive identity mismatch")
    f = identity["source"]
    require((f["version"], f["source_sha"], f["tree"], f["parent_sha"], f["commit_count"], f["changed_paths"]) == ("2.44.561", SOURCE, TREE, PARENT, 2, 30), "hard source/tree/parent/path pins mismatch")
    require(f["commits"] == ["0ba01f58e315ea2b0ea53e7e8f30cb3bb2f18e6e", SOURCE], "exact two source commits mismatch")
    require(f["migration_files"] == 569 and f["migration_sha256"] == MIGRATION and f["new_migration_paths"] == [], "exact zero-DDL migration identity mismatch")
    require(f["scope"] == {"application_versions": [558, 559, 560, 561], "supplements": ["548-R2"], "code_only": True, "business_acceptance": "deferred"}, "cumulative release scope mismatch")
    require(set(f["files"]) == set(identity["source_file_paths"]) and len(f["files"]) == 30, "source file manifest incomplete")
    require(identity["source_ci"]["branch"] == BRANCH and identity["source_ci"]["pull_request"] == SOURCE_PR, "exact source branch/PR binding mismatch")
    require(identity["source_ci_runs"] == list(SOURCE_RUNS.values()), "exact source CI run IDs mismatch")
    require(identity["expected_testcases_sha256"] == sha(canonical(identity["expected_testcases"])), "expected private MySQL test manifest digest mismatch")
    require(identity["expected_testcases"]["count"] == 23 and len(identity["expected_testcases"]["nodeids"]) == 23, "expected private MySQL case count mismatch")
    validate_pending_receipts(identity)

    source_tree_paths = git("ls-tree", "-r", "--name-only", SOURCE).splitlines()
    parent_tree_paths = git("ls-tree", "-r", "--name-only", PARENT).splitlines()
    migration_paths = sorted(p for p in source_tree_paths if "/backend/apps/" in p and "/migrations/" in p and p.endswith(".py"))
    parent_migration_paths = sorted(p for p in parent_tree_paths if "/backend/apps/" in p and "/migrations/" in p and p.endswith(".py"))
    inventory = identity["runtime_source_inventory"]
    prefetch_blobs(
        [SOURCE + ":" + path for path in f["files"]]
        + [SOURCE + ":saas-collab-system/backend/" + path for path in inventory["files"]]
        + [SOURCE + ":" + path for path in migration_paths]
        + [PARENT + ":" + path for path in parent_migration_paths]
        + [PARENT + ":saas-collab-system/frontend/src/router/menu.js", PARENT + ":saas-collab-system/frontend/src/router/index.js", PARENT + ":saas-collab-system/frontend/src/layouts/MainLayout.vue", PARENT + ":saas-collab-system/frontend/src/data/releaseNotes.json"]
    )

    require(os.environ.get("GITHUB_REF") == "refs/heads/main" and os.environ.get("GITHUB_RUN_ATTEMPT") == "1", "official main attempt1 only")
    require(os.environ.get("REQUESTED_SHA") == SOURCE, "requested release is not exact frozen V561 source")
    require(os.environ.get("EXPECTED_BASELINE_SHA") == identity["baseline"]["sha256"], "fresh full baseline SHA input mismatch")
    control = os.environ.get("EXPECTED_CONTROL_SHA")
    require(control and control == os.environ.get("GITHUB_SHA") and api("git/ref/heads/main")["object"]["sha"] == control, "exact current main control SHA required")
    require([p["sha"] for p in api("git/commits/" + control)["parents"]] == [CONTROL_BASE], "controller must be a normal single-parent merge from pinned control base")
    run_rows = api("actions/workflows/developer-a-production-release.yml/runs?event=workflow_dispatch&branch=main&head_sha=" + control + "&per_page=100")
    require(run_rows["total_count"] == len(run_rows["workflow_runs"]) == 1 and run_rows["workflow_runs"][0]["id"] == int(os.environ["GITHUB_RUN_ID"]), "exactly one official attempt1 run is allowed")
    official = run_rows["workflow_runs"][0]
    require((official["head_sha"], official["head_branch"], official["event"], official["path"], official["run_attempt"]) == (control, "main", "workflow_dispatch", ".github/workflows/developer-a-production-release.yml", 1), "official run envelope mismatch")
    pull = api("pulls/" + str(SOURCE_PR))
    require(pull["draft"] is True and pull["state"] == "open" and pull["head"]["sha"] == SOURCE and pull["head"]["ref"] == BRANCH and pull["base"]["ref"] == "main", "source PR must remain exact draft on main")

    paths = git("diff", "--name-only", PARENT, SOURCE).splitlines()
    require(len(paths) == 30 and set(paths) == set(f["files"]), "exact 30 source paths mismatch")
    require(git("rev-parse", "HEAD") == SOURCE and git("rev-parse", "HEAD^{tree}") == TREE, "requested source checkout mismatch")
    require(git("rev-list", "--reverse", PARENT + ".." + SOURCE).splitlines() == f["commits"], "source commit closure mismatch")
    require(all(sha(blob(SOURCE, path)) == digest for path, digest in f["files"].items()), "exact source file bytes mismatch")
    migration_hash = hashlib.sha256()
    for path in migration_paths:
        migration_hash.update(path.split("/backend/", 1)[1].encode())
        migration_hash.update(blob(SOURCE, path))
    require(len(migration_paths) == 569 and migration_hash.hexdigest() == MIGRATION, "historical 569 migration bytes differ")
    old_migrations = set(parent_migration_paths)
    require(set(migration_paths) == old_migrations and all(blob(PARENT, path) == blob(SOURCE, path) for path in old_migrations), "a historical migration changed or a new migration appeared")
    require(all(sha(blob(SOURCE, "saas-collab-system/backend/" + path)) == digest for path, digest in identity["runtime_source_inventory"]["files"].items()), "production backend inventory bytes mismatch")
    inventory = identity["runtime_source_inventory"]
    require(inventory["source_sha"] == SOURCE and inventory["source_tree_sha"] == TREE and inventory["production_files"] == len(inventory["files"]) == 1668, "exact runtime source inventory mismatch")

    # menu.js intentionally contains a narrow permission-identity revision; compare rendered visual hierarchy instead of raw bytes.
    visual_parent, visual_source = menu_at(PARENT), menu_at(SOURCE)
    require(visual_source == visual_parent and len(visual_source) > 0, "menu visual metadata/order/children changed")
    preserved = f["menu_layout_preserved_files"]
    require(set(preserved) == {"saas-collab-system/frontend/src/router/index.js", "saas-collab-system/frontend/src/layouts/MainLayout.vue"}, "menu layout preservation scope mismatch")
    require(all(sha(blob(PARENT, path)) == digest and blob(PARENT, path) == blob(SOURCE, path) for path, digest in preserved.items()), "router/layout identity drift")

    notes = json.loads(blob(SOURCE, "saas-collab-system/frontend/src/data/releaseNotes.json"))
    parent_notes = json.loads(blob(PARENT, "saas-collab-system/frontend/src/data/releaseNotes.json"))
    today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    require(notes[0]["version"] == "2.44.561" and notes[0]["date"] == today == identity["release_date_beijing"] == "2026-11-28", "V561 release note date is stale or drifted")
    require(parent_notes[0]["version"] == "2.44.557" and notes[1] == parent_notes[0], "actual V557 release-note entry changed")
    require(sha(canonical(notes[2:])) == identity["actual_v557_history_canonical_sha256"], "actual V557 historical release-note suffix changed")

    ci = identity["source_ci"]
    for workflow, run_id in SOURCE_RUNS.items():
        record = ci["expected_workflows"][workflow]
        require(record["run_id"] == run_id and set(record["jobs"]) == EXPECTED_JOBS[workflow], "source CI workflow identity mismatch")
        matching_runs = api("actions/workflows/" + workflow + "/runs?event=workflow_dispatch&branch=" + BRANCH + "&head_sha=" + SOURCE + "&per_page=100")
        require(matching_runs["total_count"] == len(matching_runs["workflow_runs"]) == 1 and matching_runs["workflow_runs"][0]["id"] == run_id, "source CI workflow was duplicated or run identity drifted")
        run = api("actions/runs/" + str(run_id))
        jobs = api("actions/runs/" + str(run_id) + "/attempts/1/jobs?per_page=100")
        require((run["head_sha"], run["head_branch"], run["status"], run["conclusion"], run["run_attempt"], run["event"], run["path"]) == (SOURCE, BRANCH, "completed", "success", 1, "workflow_dispatch", ".github/workflows/" + workflow), "exact source CI run is not attempt1 success")
        rows = jobs["jobs"]
        require(jobs["total_count"] == len(rows) == 5 and {job["name"] for job in rows} == EXPECTED_JOBS[workflow], "exact source CI job set mismatch")
        require(all((job["run_id"], job["head_sha"], job["run_attempt"], job["status"], job["conclusion"]) == (run_id, SOURCE, 1, "completed", "success") for job in rows), "exact source CI job did not pass")
    print(json.dumps({"status": "V561_EXACT_SOURCE_AND_ACTUAL_REHEARSAL_PASS", "source_sha": SOURCE, "tree": TREE}, separators=(",", ":")))

if __name__ == "__main__":
    main()

