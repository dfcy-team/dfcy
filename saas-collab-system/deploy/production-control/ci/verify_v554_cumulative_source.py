"""Read-only, exact-source verifier for the cumulative V547–V554 VM release."""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

SOURCE='71faab0aee2b5e1c32204c6859a0022661ac46da'
TREE='563156c450a5943e0e2e75dc910ffa1b0d38502e'
PARENT='3d977af50a0064d455f7c5e35baacc29f7c6278c'
MIGRATION='ec5254e4007eb1997b4c053e3f795bcf714de596c986482249c4f88d676cd310'
BASELINE='7ae217794862cf81c33f9123943e5bab6055336eab167bb7cf97e4e2ab3c9c23'
# Replaced only after actual, independently reviewed MySQL execution evidence exists.
REHEARSAL_SHA='3206ca395fac203e18bb5fdb094fd4eb20b6f57432b07ffe3dc96bc7dff7cad6'
BEFORE_SCHEMA_SHA='d75a12aa77c3039084089a36c81ea4ee35fc79b9eba2b60dfc098e5e4600f0ef'


def require(condition,message):
    if not condition:raise RuntimeError(message)


def git(*args):return subprocess.check_output(['git',*args],stderr=subprocess.PIPE).decode().strip()
def blob(rev,path):return subprocess.check_output(['git','cat-file','blob',git('rev-parse',rev+':'+path)],stderr=subprocess.PIPE)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()


def menu_at(revision):
    base='saas-collab-system/frontend/src/'
    text=blob(revision,base+'router/menu.js').decode()
    for relative,path in [('../utils/apiAccessAdmin.js','utils/apiAccessAdmin.js'),('./menuRegistry.js','router/menuRegistry.js')]:
        uri='data:text/javascript;base64,'+base64.b64encode(blob(revision,base+path)).decode()
        require(text.count("'"+relative+"'")==1,'pure menu import drift')
        text=text.replace("'"+relative+"'",json.dumps(uri))
    uri='data:text/javascript;base64,'+base64.b64encode(text.encode()).decode()
    return json.loads(subprocess.check_output(['node','--input-type=module'],input=('const m=await import('+json.dumps(uri)+');process.stdout.write(JSON.stringify(m.menuItems));').encode(),timeout=30))


def api(path):
    token=os.environ.get('GH_API_TOKEN') or os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    require(bool(token),'read-only GitHub token required')
    request=urllib.request.Request('https://api.github.com/repos/dfcy-team/dfcy/'+path,
        headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
    with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)


def main():
    require(__debug__,'optimized execution disables gates')
    identity=json.loads(Path(__file__).with_name('v554-cumulative-source-identity.json').read_bytes())
    require(identity['status']=='READY_FOR_OFFICIAL_SOURCE_GATE','source evidence not ready')
    require((identity['source']['sha'],identity['source']['tree_sha'],identity['source']['parent_sha'])==(SOURCE,TREE,PARENT),'source identity mismatch')
    require(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','Only a fresh official attempt1 is permitted')
    control=os.environ.get('EXPECTED_CONTROL_SHA','')
    require(len(control)==40 and all(x in '0123456789abcdef' for x in control) and os.environ.get('GITHUB_SHA')==control,'Exact requested main control SHA required')
    runid=os.environ.get('GITHUB_RUN_ID','')
    require(runid.isdecimal(),'Actual official run ID required')
    control_commit=api('git/commits/'+control)
    require([p['sha'] for p in control_commit['parents']]==['abb6fa30cd41e3556dd9720222ca4da7d078254e'],'Exact reviewed controller main parent required')
    observed=api('actions/workflows/developer-a-production-release.yml/runs?event=workflow_dispatch&branch=main&head_sha='+control+'&per_page=100')
    require(observed['total_count']==len(observed['workflow_runs'])==1,'Only one official run for exact control is allowed')
    matches=[r for r in observed['workflow_runs'] if r['head_sha']==control]
    require(len(matches)==1 and matches[0]['id']==int(runid) and matches[0]['run_attempt']==1,'Only one official dispatch for this exact new controller is permitted')
    pull=api('pulls/656')
    require(pull['state']=='open' and pull['draft'] is True and pull['head']['sha']==SOURCE and pull['head']['repo']['full_name']=='dfcy-team/dfcy' and pull['base']['ref']=='main','Live source draft PR binding mismatch')
    require(identity['source']['pull_request']==656 and identity['source']['commit_count']==9,'source PR/commit count mismatch')
    require(git('rev-parse','HEAD')==SOURCE and git('rev-parse','HEAD^{tree}')==TREE,'checkout mismatch')
    require(git('rev-list','--reverse',PARENT+'..HEAD').splitlines()==identity['source']['commits'] and len(identity['source']['commits'])==9,'source commit closure mismatch')
    paths=git('diff','--name-only',PARENT,'HEAD').splitlines()
    require(len(paths)==143 and set(paths)==set(identity['files']),'exact143 source paths required')
    require({p for p in paths if not p.startswith('saas-collab-system/')}=={'tools/test_arrival_todo.py','tools/test_arrival_todo_query.py'},'unrelated source paths')
    require(all(sha(blob('HEAD',path))==value for path,value in identity['files'].items()),'raw source blob mismatch')
    migrations=sorted(p for p in git('ls-tree','-r','--name-only','HEAD').splitlines() if '/backend/apps/' in p and '/migrations/' in p and p.endswith('.py'))
    digest=hashlib.sha256()
    for path in migrations:digest.update(path.split('/backend/',1)[1].encode());digest.update(blob('HEAD',path))
    require(len(migrations)==568 and digest.hexdigest()==MIGRATION==identity['migration']['sha256'],'migration source mismatch')
    old={p for p in git('ls-tree','-r','--name-only',PARENT).splitlines() if '/backend/apps/' in p and '/migrations/' in p and p.endswith('.py')}
    require(all(blob(PARENT,p)==blob('HEAD',p) for p in old),'historical migration changed')
    require(set(migrations)-old==set(identity['migration']['new_paths']) and len(set(migrations)-old)==7,'exact seven forward migrations required')
    require(identity['baseline']=={'sha256':BASELINE,'source_sha':PARENT,'version':'2.44.546','tables':433,'migration_nodes':550,'protected_tables':430,'protected_rows':3577537},'parent baseline mismatch')
    require(BEFORE_SCHEMA_SHA!='PENDING_ACTUAL_PARENT_SCHEMA' and identity['baseline_schema_reference']=={'sha256':BEFORE_SCHEMA_SHA,'tables':433,'migration_nodes':550,'source_sha':PARENT,'read_only':True},'Actual supplemental parent physical schema reference not sealed')
    require(os.environ.get('EXPECTED_BASELINE_SHA')==BASELINE,'requested baseline mismatch')
    require(identity['scope']=={'included':[547,548,549,550,551,552,553,554],'code_only':True,'business_acceptance':'deferred','sales_interface_preserved':True,'live_permission_role_sync_forbidden':True},'release scope mismatch')
    parent_menu=menu_at(PARENT);current=menu_at('HEAD')
    inventory=next(item for item in current if item.get('label')=='库存管理')
    parent_inventory=next(item for item in parent_menu if item.get('label')=='库存管理')
    require(inventory['permissions']==parent_inventory['permissions']+['products.cost.view'],'inventory parent grant delta mismatch')
    ledger=[item for item in inventory['children'] if item.get('path')=='/inventory/cost-ledger']
    require(len(ledger)==1 and ledger[0].get('menuAlias')=='/products/costs' and ledger[0]['permissions']==['products.cost.view'],'cost ledger alias mismatch')
    inventory['children']=[item for item in inventory['children'] if item.get('path')!='/inventory/cost-ledger']
    inventory['permissions']=parent_inventory['permissions']
    system=next(item for item in current if item.get('label')=='系统管理')
    automation=[item for item in system['children'] if item.get('path')=='/system/automation-tasks']
    require(len(automation)==1 and automation[0].get('superuserOnly') is True,'automation must be superuser only')
    system['children']=[item for item in system['children'] if item.get('path')!='/system/automation-tasks']
    require(current==parent_menu,'unapproved menu/UI declaration change')
    require(blob('HEAD','saas-collab-system/frontend/src/views/sales-management/SalesWorkspace.vue')==blob(PARENT,'saas-collab-system/frontend/src/views/sales-management/SalesWorkspace.vue'),'VM sales interface changed')
    notes=json.loads(blob('HEAD','saas-collab-system/frontend/src/data/releaseNotes.json'))
    require(notes[0]['version']=='2.44.554' and notes[0]['date']==datetime.now(timezone(timedelta(hours=8))).date().isoformat(),'release notes version/date mismatch')
    require(sha(canonical(notes[1:]))==identity['release_notes']['deployed_history_canonical_sha256']=='4240380209bf53e25f990703ae38e6c2e9c195023bd476b1bc90882f58e4166a','deployed history changed')
    receipt=identity['rehearsal_receipt']
    require(REHEARSAL_SHA!='PENDING_ACTUAL_MYSQL_RECEIPT' and sha(canonical(receipt))==REHEARSAL_SHA,'actual rehearsal receipt not sealed')
    require(receipt['status']=='PASS' and receipt['source_sha']==SOURCE and receipt['source_tree']==TREE and receipt['parent_sha']==PARENT and receipt['checkpoint_sha256']==BASELINE,'rehearsal identity mismatch')
    require(receipt['business_writes']==0 and receipt['external_calls']==0 and receipt['production_runtime_unchanged'] is True and receipt['private_probe_artifacts_retained'] is True,'rehearsal side effect/evidence guard failed')
    require(receipt['backup_sha256']=='052d4bd292e3d94544e9a043b9ae5f8c3708127ea0c21ca91551c35c823e9dd2','Approved actual rehearsal backup mismatch')
    require(len(receipt['removed_own_containers'])==2 and len(set(receipt['removed_own_containers']))==2,'Own rehearsal container cleanup not verified')
    require(all(receipt['resource_limits'].get(k)==v for k,v in {'db_mib':512,'probe_mib':768,'swap_disabled':True,'host_reserve_mib':384}.items()),'Rehearsal resource caps mismatch')
    require(receipt.get('schema_checker_sha256')=='66134b36f610e6193676c1c38adef46552859ddc8e40a968ddab71984458b2a5','Shared physical schema checker mismatch')
    require(receipt.get('database_environment')=={'charset':'utf8mb4','collation':'utf8mb4_0900_ai_ci','version':'8.4.10','foreign_key_checks':1,'read_only':True,'source_sha':PARENT,'baseline_sha256':BASELINE,'database_writes':0,'external_calls':0},'Actual production MySQL environment mismatch')
    limits=receipt['resource_limits'];stage=limits['migration_stage']
    require(limits['available_kib_before']>=1664*1024 and limits['max_combined_mib']==1280 and all(stage.get(k)==v for k,v in {'db_mib':768,'probe_mib':512,'swap_disabled':True,'host_reserve_mib':384,'actual_caps_verified':True}.items()),'R8 staged resource envelope mismatch')
    require(stage['probe_usage_bytes_before_shrink']<=384*2**20 and stage['available_kib_before_grow']>=640*1024,'Safe stage reallocation evidence missing')
    states=receipt['private_container_terminal_state'];require(set(states)=={receipt['operation']+'-db',receipt['operation']+'-probe'},'Exact private terminal state inventory')
    for name,state in states.items():
        cap=(768 if name.endswith('-db') else 512)*2**20
        require(state['id'] in receipt['removed_own_containers'] and state['oom_killed'] is False and state['restart_count']==0 and state['exit_code']==0 and state['memory']==state['memory_swap']==cap,'Private final caps/OOM/restart guard')
    tests=receipt['tests']
    require(tests['schema_source']=='current_django_models_without_historical_migrations' and tests['historical_migration_validation']=='separate_actual_parent_backup_migration_phase','R6 synthetic schema and separate real migration proof required')
    require(tests['tests']>0 and all(tests[k]==0 for k in ('failures','errors','skipped')),'MySQL tests must actually pass without skips')
    require(tests['source_sha']==SOURCE and tests['source_tree']==TREE and tests['operation']==receipt['operation'] and tests['checkpoint_sha256']==BASELINE,'MySQL test binding mismatch')
    require(tests['execution_phase']=='before_restore_on_private_test_schema' and tests['fixture_databases_dropped'] is True and tests['clone_db_empty_before_restore'] is True,'MySQL test isolation mismatch')
    require(any(entry['module']=='/evidence/test_mysql_native554.py' and entry['tests']>0 for entry in tests['reports']),'real SSCursor regression missing')
    expected_modules=['test_finance_database_summary.py','test_finance_read_query.py','test_monthly_fee_default_gate.py','test_monthly_supply_cost_jobs.py','test_monthly_product_costs.py','test_monthly_cost_adapter.py','test_monthly_cost_reconciliation.py','test_monthly_partial_inbounds.py','test_v551_workspace_prerequisites.py','test_v554_hotfix_union.py','/evidence/test_mysql_native554.py']
    require([e['module'] for e in tests['reports']]==expected_modules,'Exact MySQL regression inventory required')
    for index,entry in enumerate(tests['reports']):
        require(entry['report']==f'tests-{index:02d}.xml' and entry['exit_code']==0 and len(entry['sha256'])==64 and all(ch in '0123456789abcdef' for ch in entry['sha256']),'Exact MySQL XML provenance required')
        require(type(entry['tests']) is int and entry['tests']>0 and all(entry[k]==0 for k in ('failures','errors','skipped')),'Every MySQL module must pass without skips')
        require(receipt['retained_probe_artifact_sha256'].get(entry['report'])==entry['sha256'],'Retained actual JUnit binding missing')
    require(all(tests[k]==sum(e[k] for e in tests['reports']) for k in ('tests','failures','errors','skipped')),'MySQL summary aggregation mismatch')
    migration=receipt['migration']
    require(migration['status']=='PASS' and migration['before']=={'tables':433,'nodes':550,'rows':3577537} and migration['after']=={'tables':439,'nodes':557} and migration['old_projection']=='verified' and len(migration['new_nodes'])==7,'actual migration/data proof mismatch')
    require(migration['tests']==tests and migration['replay_changed']==0,'Exact MySQL report/replay binding mismatch')
    require({tuple(n) for n in migration['new_nodes']}=={(path.split('/apps/',1)[1].split('/')[0],Path(path).stem) for path in identity['migration']['new_paths']},'Exact seven migration nodes required')
    require(migration['migration_proof_sha256']==receipt['retained_probe_artifact_sha256'].get('migration-proof.json'),'Actual migration audit artifact binding missing')
    expected={45939545432:('.github/workflows/phase2-ci.yml',{'Frontend build observation gate','Docker Compose configuration','Django and pytest','Repository safety and file guard','RPA samples and required documents'}),45939549008:('.github/workflows/phase3-ci.yml',{'Repository safety and forbidden file guard','RPA samples and Phase 3 documents','Docker Compose placeholder configuration','Phase 3 Django, data quality, and pytest','Frontend build without dependency lifecycle scripts'})}
    require(identity['source_ci_runs']==list(expected),'source CI run IDs mismatch')
    for run_id,(workflow,names) in expected.items():
        run=api('actions/runs/'+str(run_id));jobs=api('actions/runs/'+str(run_id)+'/attempts/1/jobs?per_page=100')
        require(run['head_sha']==SOURCE and run['status']=='completed' and run['conclusion']=='success' and run['run_attempt']==1 and run['event']=='workflow_dispatch' and run['path']==workflow,'exact source CI failed')
        require(jobs['total_count']==5==len(jobs['jobs']) and {job['name'] for job in jobs['jobs']}==names and all(job['conclusion']=='success' and job['status']=='completed' and job['head_sha']==SOURCE and job['run_attempt']==1 and job['run_id']==run_id for job in jobs['jobs']),'exact source ten jobs failed')
    print(json.dumps({'status':'V554_EXACT_SOURCE_PASS','source_sha':SOURCE,'tree':TREE,'migration_sha256':MIGRATION,'actual_mysql_operation':receipt['operation'],'source_ci_runs':list(expected)},separators=(',',':')))


if __name__=='__main__':main()
