"""Read-only verifier for the cumulative V543-V546 VM source control."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

SOURCE = "3d977af50a0064d455f7c5e35baacc29f7c6278c"
TREE = "44a2eb5a94c9549da6e330ec57fb132ed5d4d5f1"
PARENT = "2c1f39c79e08ec6a54d6dff968f4955bc8921405"
MIGRATION = "c74f93cc49ee050b36d00ab7ec9aca305b6e17bff6d069cc46faea2464b9f0ff"
IDENTITY = "v546-cumulative-r2-source-identity.json"
REHEARSAL_SHA = "a89f288fc1aa8cc6cfb3a384c90d7f3afc3fa031d9ad72377b44df736f3f0cef"
if not __debug__: raise RuntimeError("Optimized Python disables release gates")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


EXPECTED_TEST_MODULES=['test_finance_read_query.py', 'test_finance_mysql_concurrency.py', 'test_finance_read_history.py', 'test_finance_native_sample_history.py', 'test_issue_tracking_api.py', 'test_issue_tracking_context.py', 'test_issue_tracking_links.py', 'test_replenishment_strategy_math.py', 'test_replenishment_jobs_acceptance.py', 'test546_sync_terminal.py', 'test546_affiliate_quarantine_retry.py', 'test_affiliate_daily_ingestion.py', 'test_finance_native_sql_pages.py', 'test_finance_oom_atomic.py', 'test_tk_oss_current.py', 'test_tk_oss_checkpoint.py', 'test_tk_oss_checkpoint_regression.py', 'test_payment_voucher_storage.py', 'test_payment_voucher_oss_api.py', 'test_payment_voucher_oss_roundtrip.py', 'test_creator_rate_resume541.py', 'test_withdraw_lock539.py', 'test_finance_memory_budget.py', 'test_finance_oom_runtime.py', 'test_video_receipt_retry.py', 'test_supply_payment_classification.py']
EXPECTED_MYSQL_CASES=['test_mysql_different_statements_cannot_share_one_receipt', 'test_mysql_finance_index_migration_forward_and_reverse', 'test_mysql_simultaneous_confirm_and_reject_has_one_final_state', 'test_mysql_simultaneous_same_source_creation_has_one_winner']

def validate_phase_summary(summary, source, tree, operation):
    def check(condition, message):
        if not condition:raise RuntimeError('actual MySQL test phase: '+message)
    check(isinstance(summary,dict),'missing summary')
    check(re.fullmatch(r'saas-v546-rehearsal-r13-'+source[:8]+r'-d9a85c4c-[0-9a-f]{10}',operation) is not None,'operation format')
    check(summary.get('status')=='PASS' and summary.get('source_sha')==source and summary.get('source_tree')==tree and summary.get('operation')==operation,'source/tree/operation binding')
    check(summary.get('database')=='test_vm546_acceptance' and summary.get('required_modules')==EXPECTED_TEST_MODULES and summary.get('required_mysql_cases')==EXPECTED_MYSQL_CASES,'exact database/test inventory')
    check(summary.get('execution_phase')=='before_restore_on_private_test_schema' and all(summary.get(k) is True for k in ('modules_run_separately','fixture_databases_dropped','clone_db_empty_before_restore')),'phase scope')
    entries=summary.get('module_reports');check(isinstance(entries,list) and len(entries)==26,'26 reports')
    totals=dict.fromkeys(('tests','failures','errors','skipped'),0)
    for index,(entry,module) in enumerate(zip(entries,EXPECTED_TEST_MODULES)):
        check(isinstance(entry,dict) and entry.get('module')==Path(module).stem and entry.get('report')==f'synthetic-module-{index:02d}.xml' and re.fullmatch(r'[0-9a-f]{64}',entry.get('sha256','')) is not None,'unique module report identity')
        check(type(entry.get('exit_code')) is int and entry['exit_code']==0,'module exit code')
        for key in totals:
            value=entry.get(key);check(type(value) is int and (value>0 if key=='tests' else value==0),'module counts')
            totals[key]+=value
        cases=entry.get('mysql_cases');expected=EXPECTED_MYSQL_CASES if module=='test_finance_mysql_concurrency.py' else []
        check(isinstance(cases,list) and sorted(cases)==expected,'four exact unique MySQL cases')
    check(totals['tests']==256 and all(type(summary.get(k)) is int and summary[k]==v for k,v in totals.items()),'aggregate counts')
    return True

def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], stderr=subprocess.PIPE).decode().strip()


def blob(revision: str, path: str) -> bytes:
    oid = git("rev-parse", f"{revision}:{path}")
    return subprocess.check_output(["git", "cat-file", "blob", oid], stderr=subprocess.PIPE)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


identity_path = Path(__file__).with_name(IDENTITY)
require(identity_path.is_file(), "V546 identity missing; run build-control-identity546.py only after actual rehearsal")
identity = json.loads(identity_path.read_text(encoding="utf-8"))
source = identity["source"]
require(source == {"sha": SOURCE, "tree_sha": TREE, "parent_sha": PARENT, "commit_count": 9,
                  "commits": source.get("commits"), "pull_request": 649}, "frozen source identity mismatch")
require(len(source["commits"]) == 9, "expected nine cumulative commits")
require(git("rev-parse", "HEAD") == SOURCE and git("rev-parse", "HEAD^{tree}") == TREE,
        "checkout does not match frozen source")
require(git("rev-parse", "HEAD~9") == PARENT and git("rev-list", "--count", f"{PARENT}..HEAD") == "9",
        "source parent or commit count mismatch")
require(git("rev-list", "--reverse", "--first-parent", f"{PARENT}..HEAD").splitlines() == source["commits"],
        "first-parent commit sequence mismatch")

require(git("rev-parse", "HEAD^") == "69d2196e331f11a7001f515e1770c79cf2e1a8bb", "R2 must directly extend reviewed R1 source")
require(git("diff", "--name-only", "HEAD^", "HEAD").splitlines() == ["saas-collab-system/deploy/pilot/application/Dockerfile.frontend"], "R2 delta must be Dockerfile only")
require(sha(blob("HEAD", "saas-collab-system/deploy/pilot/application/Dockerfile.frontend")) == "a2b9a1c5d9339d72dcd0381a9be67b812b078d4aada452d83eb2c508ae6dc649", "reviewed five-COPY Dockerfile required")

for key, expected in (("GITHUB_REPOSITORY", "dfcy-team/dfcy"), ("GITHUB_REF", "refs/heads/main"),
                      ("REQUESTED_ACTION", "deploy"), ("REQUESTED_TRANSPORT", "ssh")):
    require(os.environ.get(key) == expected, f"control binding mismatch: {key}")
require(re.fullmatch(r"[0-9a-f]{40}", os.environ.get("GITHUB_SHA", "")) is not None
        and os.environ.get("EXPECTED_CONTROL_SHA") == os.environ.get("GITHUB_SHA"), "exact control SHA binding mismatch")

files = identity["files"]
require(len(files) == 169, "frozen 169-path inventory missing")
changed = set(git("diff", "--name-only", PARENT, "HEAD").splitlines())
require(changed == set(files), "source changed-path inventory mismatch")
for path, expected in files.items():
    require(sha(blob("HEAD", path)) == expected, f"source file SHA mismatch: {path}")
# Recompute migration hash from raw Git blobs, preserving every historical migration.
paths=sorted(p for p in git('ls-tree','-r','--name-only','HEAD').splitlines() if '/backend/apps/' in p and '/migrations/' in p and p.endswith('.py'))
h=hashlib.sha256()
for path in paths:
    h.update(path.split('/backend/',1)[1].encode());h.update(blob('HEAD',path))
require(len(paths)==561 and h.hexdigest()==MIGRATION,'actual migration bytes mismatch')
old_paths={p for p in git('ls-tree','-r','--name-only',PARENT).splitlines() if '/backend/apps/' in p and '/migrations/' in p and p.endswith('.py')}
require(all(blob(PARENT,p)==blob('HEAD',p) for p in old_paths),'historical migration changed')
added_paths=set(paths)-old_paths
require(added_paths==set(identity['migration']['new_paths']) and len(added_paths)==7,'exact seven migration Python files required')
require({p for p in added_paths if p.endswith('/__init__.py')}=={'saas-collab-system/backend/apps/issue_tracking/migrations/__init__.py'} and len([p for p in added_paths if not p.endswith('/__init__.py')])==6,'six migration nodes plus one package initializer required')
require(identity['migration']['sha256']==MIGRATION,'migration identity mismatch')

baseline=identity['baseline']
require(baseline=={'sha256':'1ade0d3f496f895e13aaad3fc8f6982635712aea35cc831f02a53fd45b9d419d','source_sha':PARENT,'version':'2.44.542','tables':423,'migration_nodes':544,'protected_tables':420,'protected_rows':3577537,'custom_permission_rows':473},'actual V542 baseline mismatch')
require(os.environ.get('EXPECTED_BASELINE_SHA')==baseline['sha256'],'requested baseline mismatch')
require(identity['metadata']=={'django_migrations':6,'django_content_type':8,'auth_permission':32},'metadata increment mismatch')
require(identity['scope']=={'included':[543,544,545,546],'cloud_only_543_sales_included':False,'code_only':True,'business_acceptance':'deferred'},'scope mismatch')

# Execute only the pure menu declaration modules from exact Git bytes, with no app/API calls.
def menu_at(revision):
    base='saas-collab-system/frontend/src/'
    text=blob(revision,base+'router/menu.js').decode()
    for relative,path in [('../utils/apiAccessAdmin.js','utils/apiAccessAdmin.js'),('./menuRegistry.js','router/menuRegistry.js')]:
        uri='data:text/javascript;base64,'+base64.b64encode(blob(revision,base+path)).decode()
        require(text.count("'"+relative+"'")==1,'menu import drift')
        text=text.replace("'"+relative+"'",json.dumps(uri))
    uri='data:text/javascript;base64,'+base64.b64encode(text.encode()).decode()
    js='const m=await import('+json.dumps(uri)+');process.stdout.write(JSON.stringify(m.menuItems));'
    return json.loads(subprocess.check_output(['node','--input-type=module'],input=js.encode(),timeout=30))
parent_menu=menu_at(PARENT); current_menu=menu_at('HEAD')
fixture=blob('HEAD','saas-collab-system/frontend/tests/fixtures/menu-v542-baseline.json')
require(sha(fixture)=='5f048a28b6076a8d7cf099bb4c9518dd3cf388a3a64b2d38c47e5b1c532f5126' and json.loads(fixture)==parent_menu,'parent menu fixture mismatch')
system=[x for x in current_menu if x.get('label')=='系统管理'];require(len(system)==1,'system menu missing')
added=[x for x in system[0]['children'] if x.get('path')=='/system/issue-tracking']
require(added==[{'path':'/system/issue-tracking','label':'事件跟踪配置','permissions':['issue_tracking.configure'],'menuPermissions':['menu.system.issue_tracking.view']}],'unexpected new menu entry')
system[0]['children']=[x for x in system[0]['children'] if x.get('path')!='/system/issue-tracking']
require(current_menu==parent_menu,'preexisting menu object/order changed')
manifest=json.loads(blob('HEAD','saas-collab-system/backend/apps/permissions/permission_manifest.json'))
surface=json.loads(blob('HEAD','saas-collab-system/backend/apps/permissions/frontend_permission_surface.json'))
require(len(manifest['permissions'])==478 and len(surface['references'])==473,'source permission catalog/surface counts mismatch')

local_cap = identity["local_validation"]
local_raw = base64.b64decode(local_cap["raw_base64"], validate=True)
require(sha(local_raw) == local_cap["artifact_sha256"], "local validation record SHA mismatch")
local = json.loads(local_raw.decode("utf-8"))
require(local.get("status") == "PASS_LOCAL_VALIDATION_ONLY" and local.get("source_sha") == SOURCE
        and local.get("source_tree_sha") == TREE, "local validation source mismatch")
require(local['evidence']['ci546-nine-failures-fixed-combined.log']['terminal_marker']=='215 passed','combined regression missing')
require(local['evidence']['ci546-v545-replenishment-targeted.log']['terminal_marker']=='6 passed','V545 regression missing')
for path,tree in local['unchanged_source_trees'].items():
 require(git('rev-parse','HEAD:'+path)==tree==git('rev-parse',local['prior_source_sha']+':'+path),'reused component tree changed')
require(bool(local['limitations']) and identity.get('production_acceptance') is False,'acceptance limits missing')

# Receipt must be a real captured artifact. A derived backup manifest is not a rehearsal receipt.
capture = identity["rehearsal"]
raw = base64.b64decode(capture["raw_base64"], validate=True)
require(sha(raw) == capture["artifact_sha256"], "rehearsal receipt SHA mismatch")
receipt = json.loads(raw.decode("utf-8"))
require(sha(raw)==REHEARSAL_SHA,'independently pinned actual rehearsal receipt mismatch')
require(receipt.get('status')=='PASS' and receipt.get('source_sha')==SOURCE,'actual rehearsal source mismatch')
require(receipt['source_archive_sha256']=='f3d44e8d5bb83fb91efeb61ebb4ea79d6bffebc00919ae411ec71bd0a0059821' and receipt['backup_sha256']=='d9a85c4c2936039d4eadf6e0409f1c3cca5f013e69785e21b9662ad9229135b6','archive/backup binding mismatch')
require(receipt['approved_checkpoint_sha256']==baseline['sha256'],'checkpoint mismatch')
require(all(receipt.get(k) is True for k in ['cleanup_verified','production_app_unchanged','production_roles_unchanged','protected_state_unchanged','test_artifacts_retained']) and receipt['production_roles_verified']==14,'isolation/production preservation failed')
require(receipt['isolation_checks']['db_network']=='none' and receipt['isolation_checks']['probe_shares_db_network'] is True,'network isolation failed')
probe=receipt['probe_receipt']
require(probe['status']=='PASS' and probe['source_sha']==SOURCE and probe['source_tree']==TREE and probe['migration_digest']==MIGRATION,'probe source/tree/migration mismatch')
require(probe['checkpoint_sha256']==baseline['sha256'] and probe['checkpoint_tables_verified']==420 and probe['checkpoint_rows_verified']==3577537 and probe['checkpoint_metadata_tables_verified']==3,'checkpoint proof mismatch')
require(probe['before']=={'tables':423,'nodes':544},'before schema mismatch')
after=probe['after'];require((after['tables'],after['nodes'],after['new_tables'],after['old_data_tables_hashed'],after['old_data_rows_verified'],after['schema_delta'])==(433,550,10,420,3577537,1),'after schema mismatch')
require(all(after.get(k) is True for k in ['new_tables_empty','finance_is_active_default_preserved','old_fields_unchanged','old_indexes_unchanged_except_allowlisted_covering_index','role_permission_hash_unchanged','second_plan_empty']),'migration preservation proof missing')
require(probe['metadata_increments']==identity['metadata'] and probe['external_business_calls']==0,'metadata/external-call mismatch')
ct=probe['contention'];require(ct['status']=='PASS' and ct['connections']==2 and ct['mysql_code']==3572 and ct['conflict_status_code']==409 and ct['rollback_usable'] is True and ct['after_release_acquired'] is True and ct['elapsed_seconds']<5,'actual NOWAIT proof mismatch')
tests=probe['tests'];require(tests['tests']>0 and all(tests[k]==0 for k in ['failures','errors','skipped']) and 'test_finance_mysql_concurrency.py' in tests['required_modules'],'actual MySQL tests missing')
require(receipt.get('restore_started') is True and receipt.get('restore_completed') is True and receipt['isolation_checks'].get('tests_completed_before_restore') is True,'actual tests-before-restore stages missing')
require(tests==receipt.get('test_phase_receipt') and tests.get('execution_phase')=='before_restore_on_private_test_schema' and all(tests.get(k) is True for k in ['modules_run_separately','fixture_databases_dropped','clone_db_empty_before_restore']),'phase-isolated MySQL proof missing')
require(len(tests.get('module_reports',[]))==len(tests.get('required_modules',[]))==26 and len(tests.get('required_mysql_cases',[]))==4 and tests['tests']==256,'all26 modules/four MySQL cases missing')
validate_phase_summary(tests,SOURCE,TREE,receipt['operation'])


# Live read-only GitHub verification; never infer source checks from local status strings.
token=os.environ.get('GH_API_TOKEN');require(bool(token),'GH_API_TOKEN required')
def api(path):
    request=urllib.request.Request('https://api.github.com/repos/dfcy-team/dfcy/'+path,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(request,timeout=40) as response:return json.load(response)
pr=api('pulls/649');require(pr['head']['sha']==SOURCE and pr['head']['repo']['full_name']=='dfcy-team/dfcy','source PR head mismatch')
expected_jobs={
 'phase2-ci.yml':{'Repository safety and file guard','Django and pytest','Frontend build observation gate','Docker Compose configuration','RPA samples and required documents'},
 'phase3-ci.yml':{'Repository safety and forbidden file guard','Phase 3 Django, data quality, and pytest','Frontend build without dependency lifecycle scripts','Docker Compose placeholder configuration','RPA samples and Phase 3 documents'}}
require(identity['source_ci_runs']=={'phase2-ci.yml':45864267538,'phase3-ci.yml':45864275893},'exact source CI runs mismatch')
for workflow,run_id in identity['source_ci_runs'].items():
    run=api(f'actions/runs/{run_id}')
    require((run['head_sha'],run['run_attempt'],run['path'],run['event'],run['status'],run['conclusion'])==(SOURCE,1,'.github/workflows/'+workflow,'workflow_dispatch','completed','success'),'source CI identity/status mismatch')
    jobs=api(f'actions/runs/{run_id}/attempts/1/jobs?per_page=100')
    require(jobs['total_count']==len(jobs['jobs'])==5 and {j['name'] for j in jobs['jobs']}==expected_jobs[workflow],'exact CI jobs mismatch')
    require(all((j['head_sha'],j['run_id'],j['run_attempt'],j['status'],j['conclusion'])==(SOURCE,run_id,1,'completed','success') for j in jobs['jobs']),'CI job failed/stale')
print('V546 source, actual MySQL proof, parent menu and ten exact source CI checks verified')
