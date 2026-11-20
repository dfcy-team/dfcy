if not __debug__: raise RuntimeError('Optimized Python disables release gates')
"""Verify exact V518 cumulative source, rehearsal, baseline, and CI evidence."""
import hashlib, json, os, subprocess, urllib.request
from pathlib import Path

identity = json.loads(Path(__file__).with_name("v518-cumulative-source-identity.json").read_text(encoding="utf-8"))

def git(*args):
    return subprocess.check_output(["git", *args]).decode().strip()

def blob(path):
    oid = git("rev-parse", f"{identity['source_sha']}:{path}")
    return subprocess.check_output(["git", "cat-file", "blob", oid])

assert os.environ["GITHUB_REPOSITORY"] == "dfcy-team/dfcy"
assert os.environ["GITHUB_REF"] == "refs/heads/main"
assert os.environ["EXPECTED_CONTROL_SHA"] == os.environ["GITHUB_SHA"]
assert os.environ["REQUESTED_ACTION"] == "deploy" and os.environ["REQUESTED_TRANSPORT"] == "ssh"
assert git("rev-parse", "HEAD") == identity["source_sha"]
assert git("rev-parse", f"HEAD~{identity['source_commit_count']}") == identity["parent_sha"]
assert git("rev-list", "--count", identity["parent_sha"] + "..HEAD") == str(identity["source_commit_count"])
assert git("rev-list", "--reverse", "--first-parent", identity["parent_sha"] + "..HEAD").splitlines() == identity["source_commits"]

rehearsal = identity["migration_rehearsal"]
assert rehearsal["status"] == "PASS" and rehearsal["network"] == "none"
assert identity['version']=='2.44.518' and identity['release_generation']=='v518-cumulative-r1'
assert (rehearsal['tables_before'],rehearsal['before_nodes'],rehearsal['tables_after'],rehearsal['after_nodes'])==(411,519,415,531)
assert len(rehearsal['exact_added_nodes'])==12 and rehearsal['protected_tables']==408 and rehearsal['protected_rows']>0
assert all(rehearsal[k] is True for k in ('old_columns_unchanged','column_metadata_verified','backward_compatible_sql_defaults'))
assert (rehearsal['real_mysql_concurrency_tests'],rehearsal['real_mysql_projection_tests'],rehearsal['real_mysql_composite_orm_tests'],rehearsal['real_mysql_old_writer_default_tests'])==(4,2,10,1)
assert rehearsal['isolation_cleanup']['status']=='PASS' and rehearsal['isolation_cleanup']['containers_removed'] is True

assert rehearsal["candidate_source_sha"] == identity["source_sha"] and rehearsal["parent_sha"] == identity["parent_sha"]
generated = "saas-collab-system/backend/apps/permissions/frontend_permission_surface.json"
assert set(rehearsal["generated_only_paths"]) <= {generated}
rehearsed_tree = rehearsal["source_tree_sha"]
if rehearsal["generated_only_paths"]:
    assert git("rev-parse", "HEAD~1^{tree}") == rehearsed_tree
    assert git("diff", "--name-only", "HEAD~1", "HEAD").splitlines() == [generated]
else:
    assert git("rev-parse", "HEAD^{tree}") == rehearsed_tree
assert rehearsal["migration_sha256"] == identity["migration_sha256"]
assert len(rehearsal["receipt_sha256"]) == 64
assert identity["baseline_file_sha256"] == os.environ["EXPECTED_BASELINE_SHA"]
assert sorted(".".join(node) for node in rehearsal["exact_added_nodes"]) == sorted(identity["expected_pending_migrations"])
for key in ("backup_sha256", "receipt_sha256", "applied_nodes_sha256"):
    assert len(rehearsal[key]) == 64 and all(c in "0123456789abcdef" for c in rehearsal[key])

changed = set(git("diff", "--name-only", identity["parent_sha"], "HEAD").splitlines())
assert changed == set(identity["files"])
for path, digest in identity["files"].items():
    assert hashlib.sha256(blob(path)).hexdigest() == digest, path

migration_paths = sorted(path for path in git("ls-tree", "-r", "--name-only", "HEAD").splitlines()
    if "/backend/apps/" in path and "/migrations/" in path and path.endswith(".py"))
migrations = hashlib.sha256()
for path in migration_paths:
    migrations.update(path.split("/backend/", 1)[1].encode())
    migrations.update(blob(path))
assert migrations.hexdigest() == identity["migration_sha256"]
assert sorted(path.split("/apps/", 1)[1].replace("/migrations/", ".").removesuffix(".py")
              for path in changed if "/migrations/" in path) == sorted(identity["expected_pending_migrations"])

def api(path):
    request = urllib.request.Request("https://api.github.com/repos/dfcy-team/dfcy/" + path,
        headers={"Authorization": "Bearer " + os.environ["GH_API_TOKEN"],
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)

pr = api("pulls/" + str(identity["pull_request"]))
assert pr["head"]["sha"] == identity["source_sha"]
assert pr["base"]["ref"] == "release/v473-v490-vm" and pr["base"]["sha"] == identity["parent_sha"]
assert set(identity["source_ci_runs"]) == {"phase2-ci.yml", "phase3-ci.yml"}
required = {"Repository safety and file guard", "Django and pytest", "Frontend build observation gate",
    "Docker Compose configuration", "RPA samples and required documents",
    "Repository safety and forbidden file guard", "Phase 3 Django, data quality, and pytest",
    "Frontend build without dependency lifecycle scripts", "Docker Compose placeholder configuration",
    "RPA samples and Phase 3 documents"}
verified = set()
for workflow, run_id in identity["source_ci_runs"].items():
    run = api(f"actions/runs/{run_id}")
    assert run["id"] == run_id and run["head_sha"] == identity["source_sha"]
    assert run["path"] == ".github/workflows/" + workflow and run["event"] == "pull_request"
    assert run["run_attempt"] == 1 and run["head_branch"] == pr["head"]["ref"]
    assert run["status"] == "completed" and run["conclusion"] == "success"
    jobs = api(f"actions/runs/{run_id}/attempts/1/jobs?per_page=100")
    names = {job["name"] for job in jobs["jobs"]}
    assert jobs["total_count"] == len(jobs["jobs"]) == 5 and len(names) == 5 and names <= required
    assert not names & verified
    assert all(job["run_id"] == run_id and job["run_attempt"] == 1 and job["head_sha"] == identity["source_sha"]
        and job["status"] == "completed" and job["conclusion"] == "success" for job in jobs["jobs"])
    verified |= names
assert verified == required
print("V518 cumulative source, rehearsal, baseline, migration fingerprint, and exact ten CI jobs verified")
