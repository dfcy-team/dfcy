"""Read-only, exact-source verifier for the cumulative V555–V557 VM release."""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

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


REHEARSAL_SHA='4ba684cb298fbcfd9728359c881af7b04294285fb38270aaff52587fc886f240'
SOURCE='ea40fc102015ece64157a7ff88e69fcf8be99818'
TREE='8fb72a3e7418ac68604b210415f52f26268b6b2b'
PARENT_SHA='71faab0aee2b5e1c32204c6859a0022661ac46da'
BASELINE='5b7e4312100f15f83c97efe2bd92258d4df0003a18de840935cd043e1cf98819'
MIGRATION='b60515d62d0de8c380f015f93fce1a61045a995017f92d1c72d4d5cc123e86df'
BACKUP='da1fb9e983a4d096d004c2e24a00441a301895fc6bf1d9fb87fa3a0ce4220d79'
def main():
    require(__debug__,'optimized gates forbidden')
    identity=json.loads(Path(__file__).with_name('v557-cumulative-source-identity.json').read_bytes())
    require(identity['status']=='READY_FOR_OFFICIAL_SOURCE_GATE','V557 pending actual MySQL and exact CI evidence')
    f=identity['source'];PARENT=f['parent_sha']
    require((PARENT,f['tree'],f['migration_sha256'],identity['baseline_sha256'])==(PARENT_SHA,TREE,MIGRATION,BASELINE),'hard source/baseline pins')
    require(identity['scope']=={'application_versions':[555,557],'operations_only_preserved':[556],'code_only':True,'business_acceptance':'deferred'},'scope mismatch')
    require(f['source_sha']==SOURCE and git('rev-parse','HEAD')==SOURCE and git('rev-parse','HEAD^{tree}')==f['tree'],'source checkout mismatch')
    require(git('rev-list','--reverse',PARENT+'..HEAD').splitlines()==f['commits'] and len(f['commits'])==3,'commit closure')
    paths=git('diff','--name-only',PARENT,'HEAD').splitlines();require(len(paths)==31 and set(paths)==set(f['files']),'exact31 paths')
    require(all(sha(blob('HEAD',p))==v for p,v in f['files'].items()),'source blob drift')
    migrations=sorted(p for p in git('ls-tree','-r','--name-only','HEAD').splitlines() if '/backend/apps/' in p and '/migrations/' in p and p.endswith('.py'))
    digest=hashlib.sha256()
    for p in migrations:digest.update(p.split('/backend/',1)[1].encode());digest.update(blob('HEAD',p))
    require(len(migrations)==569 and digest.hexdigest()==f['migration_sha256'],'migration fingerprint')
    old=set(p for p in git('ls-tree','-r','--name-only',PARENT).splitlines() if '/backend/apps/' in p and '/migrations/' in p and p.endswith('.py'))
    require(all(blob(PARENT,p)==blob('HEAD',p) for p in old) and set(migrations)-old==set(f['new_migration_paths']) and len(set(migrations)-old)==1,'historical migration drift')
    require(set(f['menu_ui_preserved_files'])=={'saas-collab-system/frontend/src/router/menu.js','saas-collab-system/frontend/src/router/index.js','saas-collab-system/frontend/src/layouts/MainLayout.vue'},'exact menu preservation scope')
    require(all(blob(PARENT,p)==blob('HEAD',p) and sha(blob('HEAD',p))==v for p,v in f['menu_ui_preserved_files'].items()),'menu/layout drift')
    inv=identity['runtime_source_inventory'];require(inv['source_sha']==SOURCE and inv['source_tree_sha']==TREE and inv['production_files']==len(inv['files'])==1666,'production inventory')
    require(all(sha(blob('HEAD','saas-collab-system/backend/'+p))==h for p,h in inv['files'].items()),'production bytes drift')
    require(os.environ.get('GITHUB_REF')=='refs/heads/main' and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','main attempt1 only')
    require(os.environ.get('EXPECTED_BASELINE_SHA')==BASELINE,'exact requested full parent baseline required')
    control=os.environ.get('EXPECTED_CONTROL_SHA');require(control and control==os.environ.get('GITHUB_SHA') and api('git/ref/heads/main')['object']['sha']==control,'exact current main control')
    require([p['sha'] for p in api('git/commits/'+control)['parents']]==[identity['control_parent_sha']],'control parent')
    runs=api('actions/workflows/developer-a-production-release.yml/runs?event=workflow_dispatch&branch=main&head_sha='+control+'&per_page=100')
    require(runs['total_count']==len(runs['workflow_runs'])==1 and runs['workflow_runs'][0]['id']==int(os.environ['GITHUB_RUN_ID']) and runs['workflow_runs'][0]['run_attempt']==1,'unique official run')
    official=runs['workflow_runs'][0];require((official['head_sha'],official['head_branch'],official['event'],official['path'])==(control,'main','workflow_dispatch','.github/workflows/developer-a-production-release.yml'),'official run envelope')
    pull=api('pulls/658');require(pull['draft'] is True and pull['state']=='open' and pull['head']['sha']==SOURCE and pull['base']['ref']=='main' and pull['head']['repo']['full_name']==pull['base']['repo']['full_name']=='dfcy-team/dfcy','source draft binding')
    notes=json.loads(blob('HEAD','saas-collab-system/frontend/src/data/releaseNotes.json'));today=datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    require(notes[0]['version']=='2.44.557' and notes[0]['date']==today==identity['release_date_beijing'],'frozen date')
    require(sha(canonical(notes[1:]))==identity['deployed_history_canonical_sha256'],'actual VM554 history')
    r=identity['rehearsal_receipt'];require(REHEARSAL_SHA!='PENDING_ACTUAL_MYSQL_RECEIPT' and sha(canonical(r))==REHEARSAL_SHA,'actual receipt seal missing')
    require(r['status']=='PASS' and r['source_sha']==SOURCE and r['tree']==f['tree'] and r['parent_sha']==PARENT and r['checkpoint_sha256']==identity['baseline_sha256'] and r['backup_sha256']==BACKUP,'rehearsal identity')
    require(r['business_writes']==r['external_calls']==0 and r['production_runtime_unchanged'] is True and r['private_probe_artifacts_retained'] is True,'side effects')
    require(len(r['removed_own_containers'])==len(set(r['removed_own_containers']))==2 and set(r['terminal'])=={r['operation']+'-db',r['operation']+'-probe'},'own cleanup')
    for n,t in r['terminal'].items():
        cap=(768 if n.endswith('-db') else 512)*2**20
        require(t['id'] in r['removed_own_containers'] and not t['oom_killed'] and t['restart_count']==0 and t['memory']==t['swap']==cap,'terminal resources')
    limits=r['resource_limits'];require(limits['db_mib']==768 and limits['probe_mib']==512 and limits['swap_disabled'] is True and limits['available_kib_before']>=1664*1024 and limits['max_combined_mib']==1280 and limits['host_reserve_mib']==384,'resource guard')
    t=r['tests'];require(t['source_sha']==SOURCE and t['source_tree']==f['tree'] and t['tests']==dict(tests=72,failures=0,errors=0,skipped=0) and t['production_database_used'] is False and t['baseline_sha256']==BASELINE and t['migration_sha256']==MIGRATION and t['expected_testcases_sha256']==identity['expected_testcases_sha256'],'72 real MySQL cases')
    hashes=r['results_sha256'];require(t['junit_sha256']==hashes['tests.xml'] and t['log_sha256']==hashes['tests.log'],'retained JUnit binding')
    m=r['migration'];require(m['source_sha']==SOURCE and m['source_tree']==f['tree'] and m['parent_sha']==PARENT and m['migration_sha256']==MIGRATION and m['baseline_sha256']==BASELINE and m['backup_sha256']==BACKUP and m['production_database_used'] is False and m['before']==dict(tables=439,nodes=557,rows=3577537) and m['after']==dict(tables=439,nodes=558),'actual migration')
    require(m['new_nodes']==[['commerce','0014_v555_sales_query_indexes_vm']] and m['approved_indexes']==3 and m['replay_changed']==m['existing_index_guard_replay_changed']==0 and m['roles_unchanged'] is True and m['private_unmasked_heartbeat_verified'] is True,'migration delta/replay')
    fk=r['fk_index_provenance'];require(fk['status']=='PASS' and fk['mysql_version']=='8.4.10' and fk['explicit_support_index_retained'] is True and fk['foreign_key_constraints_preserved'] is True and type(fk['implicit_support_index_replaced']) is bool and m['fk_index_provenance_sha256']==hashes['fk-index-provenance.json'] and sha(canonical(fk))==identity['fk_provenance_canonical_sha256'] and m['implicit_fk_support_index_replacement_observed']==fk['implicit_support_index_replaced'],'native FK proof')
    require(m['restored_before_sha256']==hashes['restored-before-snapshot.json'] and m['migrated_after_sha256']==hashes['migrated-after-snapshot.json'],'actual snapshot hashes')
    require(sha(json.dumps(t,sort_keys=True,indent=2).encode()+b'\n')==hashes['tests-proof.json'] and sha(json.dumps(m,sort_keys=True,indent=2).encode()+b'\n')==hashes['migration-proof.json'],'retained proof bytes')
    d=m['delta'];require(d['status']=='PASS' and d['source_rows']==d['target_rows']==3577537 and d['protected_tables']==436 and d['schema_diff_count']==d['constraint_violations']==0 and d['approved_added_indexes']==3 and d['mismatched_chunks']==[],'full delta validation')
    require(d['approved_removed_implicit_fk_support_indexes']==[],'restored explicit indexes must remain unchanged')
    expected={46002556145:('.github/workflows/phase2-ci.yml',{'Frontend build observation gate','Docker Compose configuration','Django and pytest','Repository safety and file guard','RPA samples and required documents'}),46002636296:('.github/workflows/phase3-ci.yml',{'Repository safety and forbidden file guard','RPA samples and Phase 3 documents','Docker Compose placeholder configuration','Phase 3 Django, data quality, and pytest','Frontend build without dependency lifecycle scripts'})}
    require(identity['source_ci_runs']==list(expected),'source CI run IDs mismatch')
    for run_id,(workflow,names) in expected.items():
        run=api('actions/runs/'+str(run_id));jobs=api('actions/runs/'+str(run_id)+'/attempts/1/jobs?per_page=100')
        require(run['head_sha']==SOURCE and run['status']=='completed' and run['conclusion']=='success' and run['run_attempt']==1 and run['event']=='workflow_dispatch' and run['path']==workflow,'exact source CI failed')
        require(jobs['total_count']==5==len(jobs['jobs']) and {job['name'] for job in jobs['jobs']}==names and all(job['conclusion']=='success' and job['status']=='completed' and job['head_sha']==SOURCE and job['run_attempt']==1 and job['run_id']==run_id for job in jobs['jobs']),'exact source ten jobs failed')
    print(json.dumps({'status':'V557_EXACT_SOURCE_PASS','source_sha':SOURCE}))

if __name__=='__main__':main()
