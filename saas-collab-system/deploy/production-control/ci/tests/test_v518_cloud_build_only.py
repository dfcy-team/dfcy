import copy
import importlib.util
import json
from pathlib import Path
import pytest
import yaml

MODULE=Path(__file__).parents[1]/'v518_cloud_build_only.py'
spec=importlib.util.spec_from_file_location('v518_gate',MODULE)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
ROOT=MODULE.parents[4]

def identity():
    return {**mod.FIXED,'strict_ci_runs':dict(mod.FIXED['strict_ci_runs'])}

def load(tmp_path,value):
    path=tmp_path/'identity.json';path.write_text(json.dumps(value),encoding='utf-8')
    return mod.load_identity(path)

def test_absent_identity_closed(tmp_path):
    with pytest.raises(ValueError,match='absent'):mod.load_identity(tmp_path/'missing.json')

def test_complete_identity(tmp_path):
    assert load(tmp_path,identity())['source_sha']==mod.SOURCE

@pytest.mark.parametrize('key,value',[
 ('source_sha','a'*40),('source_tree','b'*40),('source_parent','c'*40),
 ('notes_exception_approved',False),('bounded_minimatch_risk_accepted',False),
 ('exchange_menu_inactive',False),('source_pr_do_not_merge',False),
 ('cloud_cutover_authorized',True),('formal_registration_authorized',True),('source_chain',[]),
 ('migration_files',555),('migration_files',True),('redis_image','redis:latest'),
 ('pr_files_sha256','d'*40),('strict_ci_runs',{'phase2-ci.yml':123}),
 ('strict_ci_runs',{'phase2-ci.yml':123,'phase3-ci.yml':123}),
 ('strict_ci_runs',{'phase2-ci.yml':45090551003,'phase3-ci.yml':45090563304}),
 ('strict_ci_runs',{'phase2-ci.yml':'123','phase3-ci.yml':456}),
])
def test_bad_identity_closed(tmp_path,key,value):
    data=identity();data[key]=value
    with pytest.raises(ValueError):load(tmp_path,data)

def run_and_jobs(workflow='phase3-ci.yml'):
    run={'id':456,'head_sha':mod.SOURCE,'path':'.github/workflows/'+workflow,'event':'workflow_dispatch','run_attempt':1,'head_branch':mod.FIXED['source_ref'],'status':'completed','conclusion':'success'}
    jobs=[{'name':name,'status':'completed','conclusion':'success'} for name in mod.PHASES[workflow]]
    return run,jobs

def test_exact_manual_ci_passes():
    run,jobs=run_and_jobs();mod.verify_run(run,jobs,'phase3-ci.yml',456)

@pytest.mark.parametrize('key,value',[
 ('head_sha','a'*40),('event','pull_request'),('run_attempt',2),
 ('head_branch','main'),('path','.github/workflows/phase2-ci.yml'),
 ('status','in_progress'),('conclusion','failure'),('id',999),
])
def test_wrong_ci_closed(key,value):
    run,jobs=run_and_jobs();run[key]=value
    with pytest.raises(ValueError):mod.verify_run(run,jobs,'phase3-ci.yml',456)

@pytest.mark.parametrize('mode',['missing','duplicate','failed','renamed'])
def test_wrong_job_evidence_closed(mode):
    run,jobs=run_and_jobs()
    if mode=='missing':jobs.pop()
    elif mode=='duplicate':jobs[0]=copy.deepcopy(jobs[1])
    elif mode=='failed':jobs[0]['conclusion']='failure'
    else:jobs[0]['name']='Phase3 Django, data quality, and pytest'
    with pytest.raises(ValueError):mod.verify_run(run,jobs,'phase3-ci.yml',456)

def test_new_manifest_keeps_redis_and_not_mutable_tags():
    value=mod.make_manifest(identity(),'sha256:'+'a'*64,'sha256:'+'b'*64)
    assert value['git_sha']==mod.SOURCE and value['migration_sha256']==mod.MIGRATION_SHA
    assert value['redis_image']==mod.REDIS
    assert value['compose_sha256']=='owner-controlled-on-target'

@pytest.mark.parametrize('bad',['latest','sha256:'+'f'*63,'SHA256:'+'f'*64])
def test_mutable_manifest_closed(bad):
    with pytest.raises(ValueError):mod.make_manifest(identity(),bad,'sha256:'+'b'*64)

def workflow(name):
    return yaml.load((ROOT/'.github/workflows'/name).read_text(encoding='utf-8'),Loader=yaml.BaseLoader)

def test_controller_tests_have_dedicated_readonly_pr_gate():
    data=workflow('v518-cloud-control-checks.yml')
    assert set(data['on'])=={'pull_request'}
    assert data['permissions']=={'contents':'read'}
    assert data['on']['pull_request']['branches']==['main']
    steps=data['jobs']['controller-offline-tests']['steps']
    checkout=steps[0]
    assert checkout['with']['ref']=='${{ github.event.pull_request.head.sha }}'
    assert checkout['with']['persist-credentials']=='false'
    runs='\n'.join(step.get('run','') for step in steps)
    assert 'ci/tests/test_v518_cloud_build_only.py' in runs
    assert '--junitxml=' in runs
    assert not any(value in runs for value in ('docker push','workflow run','ssh ','scp ','gh api','secrets.'))


def test_workflow_all_original_gates_retained():
    before=workflow('production-artifacts-build-only.yml')['jobs']
    after=workflow('v518-cloud-artifacts-build-only.yml')['jobs']
    assert set(after)=={'validate','quality','mysql-lock','mysql-sales','mysql-sync-workspace','build'}
    assert set(after['build']['needs'])==set(after)-{'build'}
    for key in ['mysql-lock','mysql-sales','mysql-sync-workspace']:
        assert after[key]['services']==before[key]['services']
        assert after[key]['env']==before[key]['env']
        scripts=lambda job:'\n'.join(step.get('run','') for step in job['steps'])
        commands=lambda script:[row for row in script.splitlines() if 'python -m pytest' in row or 'scripts.sales_mysql_index_probe' in row]
        assert commands(scripts(after[key]))==commands(scripts(before[key]))
        assert 'production_build_only.py' in scripts(after[key])
    assert after['quality']['timeout-minutes']==before['quality']['timeout-minutes']=='60'

def test_workflow_no_deployment_or_legacy_manifest():
    text=(ROOT/'.github/workflows/v518-cloud-artifacts-build-only.yml').read_text(encoding='utf-8')
    assert f"echo 'migration_sha={mod.MIGRATION_SHA}'" in text
    assert 'production_build_only.py manifest' not in text
    assert 'v518_cloud_build_only.py manifest' in text
    assert 'ssh ' not in text and 'scp ' not in text and 'sftp ' not in text
    assert 'environment: production' not in text
    assert 'release-notes.json' in text and mod.NOTES_SHA in text
    data=workflow('v518-cloud-artifacts-build-only.yml')
    assert data['permissions']['contents']=='read'
    assert data['jobs']['build']['permissions']['packages']=='write'
    for key,job in data['jobs'].items():
        if key!='build':assert job.get('permissions',{}).get('packages')!='write'
        checkouts=[step for step in job['steps'] if step.get('uses')=='actions/checkout@v4']
        assert {step['with']['path'] for step in checkouts}=={'business','control'}
        assert all(step['with']['fetch-depth']=='0' for step in checkouts)

def github_fixture(monkeypatch):
    data=identity();data['pr_files_sha256']=mod.digest(mod.canonical([]))
    branch={'protected':True,'commit':{'sha':'c'*40}}
    pr={'state':'open','draft':True,'merged':False,'merged_at':None,'head':{'sha':mod.SOURCE,'ref':mod.FIXED['source_ref'],'repo':{'full_name':mod.REPOSITORY}},'base':{'ref':'main'},'changed_files':0}
    dispatch={'total_count':1,'workflow_runs':[{'id':100,'event':'workflow_dispatch','head_sha':'c'*40}]}
    mapping={'branches/main':branch,'pulls/622':pr,'pulls/622/files?per_page=100&page=1':[],'actions/workflows/v518-cloud-artifacts-build-only.yml/runs?event=workflow_dispatch&head_sha='+'c'*40+'&per_page=100':dispatch}
    for workflow,run_id in data['strict_ci_runs'].items():
        run,jobs=run_and_jobs(workflow);run['id']=run_id
        mapping['actions/runs/'+str(run_id)]=run
        mapping['actions/runs/'+str(run_id)+'/attempts/1/jobs?per_page=100']={'total_count':5,'jobs':jobs}
    monkeypatch.setattr(mod,'api',lambda path:copy.deepcopy(mapping[path]))
    monkeypatch.setenv('GITHUB_RUN_ID','100')
    return data,branch,pr,dispatch

def test_live_gate_exact_one_dispatch(monkeypatch):
    data,*_=github_fixture(monkeypatch);mod.verify_github(data,'c'*40)

@pytest.mark.parametrize('change',['unprotected','main_drift','new_second_dispatch','wrong_run','source_not_draft','source_merged','pr_patch_drift'])
def test_independent_admission_failures(monkeypatch,change):
    data,branch,pr,dispatch=github_fixture(monkeypatch)
    if change=='unprotected':branch['protected']=False
    elif change=='main_drift':branch['commit']['sha']='d'*40
    elif change=='new_second_dispatch':
        dispatch['total_count']=2;dispatch['workflow_runs'].append({'id':101})
    elif change=='wrong_run':monkeypatch.setenv('GITHUB_RUN_ID','101')
    elif change=='source_not_draft':pr['draft']=False
    elif change=='source_merged':pr['merged_at']='2026-11-21T00:00:00Z'
    else:data['pr_files_sha256']='d'*64
    with pytest.raises(ValueError):mod.verify_github(data,'c'*40)

def test_caller_cannot_supply_owner_approval(monkeypatch):
    for name,value in {'GITHUB_REPOSITORY':mod.REPOSITORY,'GITHUB_REF':'refs/heads/main','GITHUB_RUN_ATTEMPT':'1','APPROVED_CONTROL_SHA':'c'*40,'OWNER_APPROVED_CONTROL_SHA':''}.items():monkeypatch.setenv(name,value)
    with pytest.raises(ValueError,match='independent repository-side'):
        mod.validate_runtime(identity(),Path('.'),Path('.'))

def test_report_review_precedes_first_publish():
    steps=workflow('v518-cloud-artifacts-build-only.yml')['jobs']['build']['steps']
    prepublish=next(i for i,row in enumerate(steps) if ' prepublish ' in row.get('run',''))
    first_publish=next(i for i,row in enumerate(steps) if row.get('uses')=='docker/build-push-action@v6')
    assert prepublish<first_publish
    assert 'cancelled()' in steps[-1]['if'] and 'always()' in steps[-1]['if']
    assert any('failure()' in row.get('if','') and 'cancelled()' in row.get('if','') and 'HOLD_NO_VERIFIED_BUILD_SUCCESS' in row.get('run','') for row in steps)
    uploads=[row for row in steps if row.get('uses')=='actions/upload-artifact@v4']
    assert uploads[0]['if']=='success()' and uploads[0]['with']['name'].startswith('production-build-only-')
    assert uploads[1]['with']['name'].startswith('v518-build-only-HOLD-')

def test_receipt_does_not_claim_deployment_or_real_restore(monkeypatch,tmp_path):
    monkeypatch.setattr(mod,'read_gate_reports',lambda *_:{'mysql_gate':{'status':'PASS_SYNTHETIC'},'mysql_sales_gate':{'status':'PASS_SYNTHETIC'},'mysql_sync_workspace_gate':{'status':'PASS_SYNTHETIC'}})
    for name,value in {'BACKEND_DIGEST':'sha256:'+'a'*64,'FRONTEND_DIGEST':'sha256:'+'b'*64,'GITHUB_SHA':'c'*40,'GITHUB_RUN_ID':'100'}.items():monkeypatch.setenv(name,value)
    mod.create_receipt(identity(),tmp_path,Path('.'),'d'*40)
    receipt=json.loads((tmp_path/'build-only-receipt.json').read_text(encoding='utf-8'))
    assert receipt['status']=='BUILT_NOT_DEPLOYED'
    assert receipt['cloud_mutated'] is False and receipt['deployment_authorized_by_this_receipt'] is False
    assert receipt['actual_cloud_restore_rehearsal_performed'] is False
    assert receipt['security_risk']['resolved'] is False
    assert receipt['manifest_sha256']==mod.digest((tmp_path/'release-manifest.json').read_bytes())
    assert 'release-manifest.json' in (tmp_path/'SHA256SUMS.txt').read_text(encoding='utf-8')

def approval_fixture(monkeypatch):
    control='c'*40;name='v518-cloud-build-approval/'+control
    ref={'ref':'refs/tags/'+name,'object':{'sha':'d'*40,'type':'tag'}}
    tag={'tag':name,'object':{'sha':control,'type':'commit','url':'https://api.github.com/repos/'+mod.REPOSITORY+'/git/commits/'+control},'message':json.dumps({'scope':'V518_BUILD_ARTIFACTS_ONLY','source_sha':mod.SOURCE,'control_sha':control,'run_id':100,'attempt':1,'production_cutover_authorized':False})}
    def api(path):
        return copy.deepcopy(ref if path.startswith('git/ref/') else tag)
    monkeypatch.setattr(mod,'api',api)
    return control,ref,tag

def test_repository_approval_bound_to_exact_actual_run(monkeypatch):
    control,*_=approval_fixture(monkeypatch)
    assert mod.verify_run_approval(control,'100')=='d'*40
    with pytest.raises(ValueError):mod.verify_run_approval(control,'101')

@pytest.mark.parametrize('change',['lightweight','wrong_target','wrong_source','wrong_scope','attempt2','boolean_attempt','production_allowed'])
def test_bad_run_approval_closed(monkeypatch,change):
    control,ref,tag=approval_fixture(monkeypatch)
    if change=='lightweight':ref['object']['type']='commit'
    elif change=='wrong_target':tag['object']['sha']='e'*40
    else:
        value=json.loads(tag['message'])
        if change=='wrong_source':value['source_sha']='e'*40
        elif change=='wrong_scope':value['scope']='PRODUCTION_DEPLOY'
        elif change=='attempt2':value['attempt']=2
        elif change=='boolean_attempt':value['attempt']=True
        else:value['production_cutover_authorized']=True
        tag['message']=json.dumps(value)
    with pytest.raises(ValueError):mod.verify_run_approval(control,'100')

def completed_fixture(monkeypatch,tmp_path):
    test_receipt_does_not_claim_deployment_or_real_restore(monkeypatch,tmp_path)
    run={'id':100,'status':'completed','conclusion':'success','head_sha':'c'*40,'head_branch':'main','path':'.github/workflows/v518-cloud-artifacts-build-only.yml','event':'workflow_dispatch','run_attempt':1}
    return run

def test_completed_bundle_admitted_only_after_final_success(monkeypatch,tmp_path):
    run=completed_fixture(monkeypatch,tmp_path)
    assert mod.verify_completed_bundle(tmp_path,run,'c'*40)['status']=='BUILT_NOT_DEPLOYED'

@pytest.mark.parametrize('key,value',[
 ('status','in_progress'),('conclusion','failure'),('conclusion','cancelled'),
 ('head_sha','d'*40),('head_branch','feature/other'),('event','pull_request'),('run_attempt',2),('id',101),
])
def test_success_looking_artifact_not_sufficient(monkeypatch,tmp_path,key,value):
    run=completed_fixture(monkeypatch,tmp_path);run[key]=value
    with pytest.raises(ValueError):mod.verify_completed_bundle(tmp_path,run,'c'*40)

@pytest.mark.parametrize('change',['tamper','extra','hold','unsafe_checksum','duplicate_checksum'])
def test_artifact_integrity_and_hold_gate(monkeypatch,tmp_path,change):
    run=completed_fixture(monkeypatch,tmp_path)
    if change=='tamper':(tmp_path/'release-manifest.json').write_text('{}',encoding='utf-8')
    elif change=='extra':(tmp_path/'unexpected.json').write_text('{}',encoding='utf-8')
    elif change=='hold':(tmp_path/'unverified-build-disposition.json').write_text('{}',encoding='utf-8')
    elif change=='unsafe_checksum':(tmp_path/'SHA256SUMS.txt').write_text('a'*64+'  ../outside\n',encoding='utf-8')
    else:
        path=tmp_path/'SHA256SUMS.txt';body=path.read_text(encoding='utf-8');path.write_text(body+body.splitlines()[0]+'\n',encoding='utf-8')
    with pytest.raises(ValueError):mod.verify_completed_bundle(tmp_path,run,'c'*40)


def source_git_replies():
    replies={('rev-parse','HEAD'):mod.SOURCE,('rev-parse','HEAD^{tree}'):mod.TREE}
    replies.update({('rev-list','--parents','-n','1',child):child+' '+parent for child,parent in mod.SOURCE_CHAIN})
    return replies


@pytest.mark.parametrize('child',[child for child,_parent in mod.SOURCE_CHAIN])
def test_every_reviewed_source_ancestry_link_is_required(monkeypatch,tmp_path,child):
    replies=source_git_replies()
    replies[('rev-list','--parents','-n','1',child)]=child+' '+'0'*40
    monkeypatch.setattr(mod,'git',lambda _root,*args:replies[args])
    with pytest.raises(ValueError,match='source chain parent drift'):
        mod.verify_source(tmp_path,identity())


def test_reviewed_delta_cannot_drop_a_source_file(monkeypatch,tmp_path):
    replies=source_git_replies()
    replies[('diff','--name-only',mod.BASE,mod.SOURCE)]='\n'.join(mod.SAFETY_FILES[:-1])
    monkeypatch.setattr(mod,'git',lambda _root,*args:replies[args])
    with pytest.raises(ValueError,match='reviewed source delta drift'):
        mod.verify_source(tmp_path,identity())


def exchange_fixture(tmp_path):
    code='menu.sales_management.sales_pre_shipment_adjustments.view'
    directory=tmp_path/'apps/permissions';directory.mkdir(parents=True)
    registry={'menus':[{'code':code,'metadata':{'status':'inactive','registry_status':'inactive'}}]}
    manifest={'permissions':[{'code':code,'lifecycle':'inactive'}]}
    return directory,registry,manifest


def write_exchange_fixture(directory,registry,manifest):
    (directory/'menu_registry.json').write_text(json.dumps(registry),encoding='utf-8')
    (directory/'permission_manifest.json').write_text(json.dumps(manifest),encoding='utf-8')


def test_physical_exchange_policy_remains_inactive(tmp_path):
    directory,registry,manifest=exchange_fixture(tmp_path)
    write_exchange_fixture(directory,registry,manifest)
    mod.verify_exchange_policy(tmp_path)


@pytest.mark.parametrize('field',['status','registry_status','lifecycle'])
def test_physical_exchange_reactivation_is_refused(tmp_path,field):
    directory,registry,manifest=exchange_fixture(tmp_path)
    if field=='lifecycle':manifest['permissions'][0][field]='active'
    else:registry['menus'][0]['metadata'][field]='active'
    write_exchange_fixture(directory,registry,manifest)
    with pytest.raises(ValueError,match='exchange menu must remain inactive'):
        mod.verify_exchange_policy(tmp_path)


@pytest.mark.parametrize('mode',['missing','duplicate'])
def test_exchange_menu_identity_must_be_unique(tmp_path,mode):
    directory,registry,manifest=exchange_fixture(tmp_path)
    if mode=='missing':registry['menus']=[]
    else:manifest['permissions']*=2
    write_exchange_fixture(directory,registry,manifest)
    with pytest.raises(ValueError,match='exchange menu identity drift'):
        mod.verify_exchange_policy(tmp_path)
