"""Exact V518 artifact admission and receipts. No production transport."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request

IDENTITY=Path(__file__).with_name('v518-cloud-build-only-identity.json')
REPOSITORY='dfcy-team/dfcy'
BASE='cd7c991d222703cec4f7d7eb6cc1237664217908'
VM_BASE='9728c548cce4c21d9cbc99aea7407298b4056fc7'
SECURITY='08569188173edbe93524d6fe33a8c6ca39dfb13c'
SURFACE='e4b32bf9e0c1168c6396e5f0399d8c0e41abccc0'
PARENT='2151b639a307c5d476e7aeb4758217aed11ca8ac'
SOURCE='89a5457035c43f8fc6d032d32275721b49f9c54a'
TREE='3bd698034bd3fc64ed7acb82a4febebf40bd237f'
SOURCE_CHAIN=[(SOURCE,PARENT),(PARENT,'13233654721edf6a8f405099266d3001c99ec1e8'),('13233654721edf6a8f405099266d3001c99ec1e8','e81811e855db166c53137aaf5ec3d1b68b9743c9'),('e81811e855db166c53137aaf5ec3d1b68b9743c9','fb9ba5fa9f060265a6300cbd11628269747ee9a6'),('fb9ba5fa9f060265a6300cbd11628269747ee9a6',SURFACE),(SURFACE,SECURITY),(SECURITY,BASE),(BASE,VM_BASE)]
MIGRATION_SHA='d51ba76b2d4cfe08c31d2e93c7b927e6a506e538ec7087206185efbd66a5a27e'
NOTES_SHA='77791a9fd987409866afa3798b476c32d8e128c75e0dcba3e26f54741ab20c4d'
MATERIAL_SHA='f8e79fa7810d85c6304aa644f273e356d94e8a9fba03f79b37d434d738f36b4d'
REDIS='redis@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99'
PHASES={
 'phase2-ci.yml':['Repository safety and file guard','Django and pytest','Frontend build observation gate','Docker Compose configuration','RPA samples and required documents'],
 'phase3-ci.yml':['Repository safety and forbidden file guard','Phase 3 Django, data quality, and pytest','Frontend build without dependency lifecycle scripts','Docker Compose placeholder configuration','RPA samples and Phase 3 documents'],
}
SAFETY_FILES=sorted('''
saas-collab-system/backend/apps/flash_sales/engine.py
saas-collab-system/backend/apps/flash_sales/provider.py
saas-collab-system/backend/apps/integrations/apps.py
saas-collab-system/backend/apps/integrations/automatic_refresh.py
saas-collab-system/backend/apps/integrations/custody.py
saas-collab-system/backend/apps/integrations/credential_access.py
saas-collab-system/backend/apps/integrations/live_providers.py
saas-collab-system/backend/apps/integrations/marketplace_oauth_service.py
saas-collab-system/backend/apps/integrations/migrations/0068_automatic_refresh_commit_recovery.py
saas-collab-system/backend/apps/integrations/migrations/0070_merge_refresh_commit_recovery.py
saas-collab-system/backend/apps/integrations/models.py
saas-collab-system/backend/apps/integrations/readonly_clients.py
saas-collab-system/backend/apps/integrations/refresh_commit_recovery.py
saas-collab-system/backend/apps/integrations/store_authorization_service.py
saas-collab-system/backend/apps/integrations/tests/test_internal_api_clients.py
saas-collab-system/backend/apps/integrations/tests/test_tiktok_migration_compatibility.py
saas-collab-system/backend/apps/permissions/frontend_permission_surface.json
saas-collab-system/backend/apps/permissions/menu_registry.json
saas-collab-system/backend/apps/permissions/permission_manifest.json
saas-collab-system/backend/tests/test_cloud_credential_preservation.py
saas-collab-system/backend/tests/test_credential_wait_state_contract.py
saas-collab-system/backend/tests/test_flash_pacing_lease.py
saas-collab-system/backend/tests/test_flash_rate_scope.py
saas-collab-system/backend/tests/test_menu_permission_registry.py
saas-collab-system/backend/tests/test_permission_lifecycle.py
saas-collab-system/backend/tests/test_v518_refresh_recovery_compat.py
saas-collab-system/backend/tests/test_warehouse_migration_alignment.py
saas-collab-system/deploy/pilot/application/Dockerfile.frontend
saas-collab-system/deploy/sandbox/application/Dockerfile.frontend
saas-collab-system/frontend/package-lock.json
saas-collab-system/frontend/package.json
saas-collab-system/frontend/src/data/releaseNotes.json
saas-collab-system/frontend/src/router/menu.js
saas-collab-system/frontend/src/router/menuRegistry.js
saas-collab-system/frontend/tests/cloud-exchange-menu-retirement.spec.js
saas-collab-system/frontend/tests/order-registrations.spec.js
saas-collab-system/frontend/tests/permission-tree-structure.spec.js
saas-collab-system/frontend/tests/ui-p11-sales-management-routing.spec.js
'''.split())
FIXED={'schema_version':1,'repository':REPOSITORY,'controller_base':'287847be708b3a296c7949ef8def5be6f5f07954','source_sha':SOURCE,'source_tree':TREE,'source_parent':PARENT,'reconciled_base':BASE,'vm_base':VM_BASE,'source_material_sha256':MATERIAL_SHA,'migration_sha256':MIGRATION_SHA,'migration_files':558,'release_notes_sha256':NOTES_SHA,'release_version':'2.44.518','release_date':'2026-11-22','redis_image':REDIS,'source_pr':622,'source_ref':'release/v518-cloud-reconciled-20261121','notes_exception_approved':True,'bounded_minimatch_risk_accepted':True,'pr_file_count':1045,'pr_files_sha256':'2b1ebc383df3be0a8c764502d2db38b563e375afbaf7716e2973c13870a58695'}
FIXED.update(source_chain=[list(pair) for pair in SOURCE_CHAIN],reviewed_source_files=SAFETY_FILES,exchange_menu_inactive=True,source_pr_do_not_merge=True,cloud_cutover_authorized=False,formal_registration_authorized=False)

def require(condition,message):
    if not condition:
        raise ValueError(message)

def digest(body):
    return hashlib.sha256(body).hexdigest()

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')

FIXED['strict_ci_runs']={'phase2-ci.yml':44997459463,'phase3-ci.yml':44997470665}

def load_identity(path=IDENTITY):
    require(Path(path).is_file(),'final reviewed identity absent; build disabled')
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    for key,expected in FIXED.items():
        require(type(data.get(key)) is type(expected) and data[key]==expected,'identity mismatch: '+key)
    require(re.fullmatch('[0-9a-f]{64}',data.get('pr_files_sha256','')) is not None,'invalid PR files fingerprint')
    require(set(data.get('strict_ci_runs',{}))==set(PHASES),'exact two strict workflows required')
    ids=list(data['strict_ci_runs'].values())
    require(all(type(value) is int and value>0 for value in ids) and len(set(ids))==2,'two distinct real run IDs required')
    return data

def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args],encoding='utf-8').strip()

def fingerprint_source(root):
    paths=subprocess.check_output(['git','-C',str(root),'ls-files','--cached','--others','--exclude-standard','-z']).split(b'\0')
    records=[]
    for raw in sorted(x for x in paths if x):
        rel=raw.decode('utf-8');path=root/rel
        require(not path.is_symlink() and path.is_file(),'source path missing or symbolic link')
        if rel=='saas-collab-system/frontend/src/data/releaseNotes.json':
            continue
        body=path.read_bytes()
        try:
            body.decode('utf-8')
            if b'\0' not in body:
                body=body.replace(b'\r\n',b'\n')
        except UnicodeDecodeError:
            pass
        records.append(raw+b'\0'+digest(body).encode()+b'\n')
    return digest(b''.join(records))

def verify_exchange_policy(backend):
    code='menu.sales_management.sales_pre_shipment_adjustments.view'
    registry=json.loads((backend/'apps/permissions/menu_registry.json').read_text(encoding='utf-8'))
    manifest=json.loads((backend/'apps/permissions/permission_manifest.json').read_text(encoding='utf-8'))
    rows=[row for row in registry['menus'] if row['code']==code]
    definitions=[row for row in manifest['permissions'] if row['code']==code]
    require(len(rows)==len(definitions)==1,'exchange menu identity drift')
    require(rows[0]['metadata'].get('status')=='inactive' and rows[0]['metadata'].get('registry_status')=='inactive' and definitions[0].get('lifecycle')=='inactive','exchange menu must remain inactive')


def verify_source(root,identity):
    root=Path(root).resolve()
    require(git(root,'rev-parse','HEAD')==SOURCE,'source HEAD drift')
    require(git(root,'rev-parse','HEAD^{tree}')==TREE,'source tree drift')
    for child,parent in SOURCE_CHAIN:
        require(git(root,'rev-list','--parents','-n','1',child).split()==[child,parent],'source chain parent drift')
    require(sorted(git(root,'diff','--name-only',BASE,SOURCE).splitlines())==SAFETY_FILES,'reviewed source delta drift')
    require(not git(root,'status','--porcelain','--untracked-files=normal'),'source checkout dirty')
    require(fingerprint_source(root)==MATERIAL_SHA,'source material drift')
    require(digest((root/'saas-collab-system/frontend/src/data/releaseNotes.json').read_bytes())==NOTES_SHA,'notes byte drift')
    backend=root/'saas-collab-system/backend';paths=sorted(backend.glob('apps/*/migrations/*.py'));h=hashlib.sha256()
    verify_exchange_policy(backend)
    for path in paths:
        h.update(path.relative_to(backend).as_posix().encode());h.update(path.read_bytes().replace(b'\r\n',b'\n'))
    require(len(paths)==558 and h.hexdigest()==MIGRATION_SHA,'migration tree drift')
    require(identity['source_sha']==SOURCE,'source identity mismatch')

def verify_run(run,jobs,workflow,run_id):
    require(run.get('id')==run_id and run.get('head_sha')==SOURCE,'strict run identity drift')
    require(run.get('path')=='.github/workflows/'+workflow,'strict workflow mismatch')
    require(run.get('event')=='workflow_dispatch' and run.get('run_attempt')==1,'manual attempt1 required')
    require(run.get('head_branch')==FIXED['source_ref'],'strict branch drift')
    require(run.get('status')=='completed' and run.get('conclusion')=='success','strict CI not successful')
    require(len(jobs)==5 and sorted(job.get('name','') for job in jobs)==sorted(PHASES[workflow]),'exact named jobs required')
    require(all(job.get('status')=='completed' and job.get('conclusion')=='success' for job in jobs),'strict job failure')

def api(path):
    if not os.environ.get('GH_TOKEN'):
        return json.loads(subprocess.check_output(['gh','api','--hostname','github.com','repos/'+REPOSITORY+'/'+path],encoding='utf-8'))
    req=urllib.request.Request('https://api.github.com/repos/'+REPOSITORY+'/'+path,headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
    with urllib.request.urlopen(req,timeout=30) as response:
        return json.load(response)

def verify_github(identity,control_sha,current_run_id=None):
    require(re.fullmatch('[0-9a-f]{40}',control_sha or '') is not None,'exact approved controller SHA required')
    branch=api('branches/main')
    require(branch.get('protected') is True and branch['commit']['sha']==control_sha,'protected main drift or protection absent')
    dispatches=api('actions/workflows/v518-cloud-artifacts-build-only.yml/runs?event=workflow_dispatch&head_sha='+control_sha+'&per_page=100')
    runs=dispatches.get('workflow_runs',[])
    require(dispatches.get('total_count')==len(runs)==1,'one single build dispatch required; do not retry')
    require(str(runs[0].get('id'))==(current_run_id or os.environ.get('GITHUB_RUN_ID')) and runs[0].get('head_sha')==control_sha and runs[0].get('event')=='workflow_dispatch','build dispatch identity mismatch')
    pr=api('pulls/622')
    require(pr['state']=='open' and pr.get('draft') is True and not pr.get('merged') and pr.get('merged_at') is None,'source PR must remain draft and unmerged')
    require(pr['head']['sha']==SOURCE and pr['head']['ref']==identity['source_ref'],'PR head drift')
    require(pr['head']['repo']['full_name']==REPOSITORY and pr['base']['ref']=='main','PR repository/base drift')
    rows=[]
    for page in range(1,32):
        chunk=api('pulls/622/files?per_page=100&page='+str(page));rows.extend(chunk)
        if len(chunk)<100:
            break
    else:
        raise ValueError('PR file pagination overflow')
    require(len(rows)==pr['changed_files'],'incomplete PR files evidence')
    records=sorted([{'filename':r['filename'],'status':r['status'],'sha':r['sha'],'previous_filename':r.get('previous_filename')} for r in rows],key=lambda r:r['filename'])
    require(digest(canonical(records))==identity['pr_files_sha256'],'PR patch identity drift')
    for workflow,run_id in identity['strict_ci_runs'].items():
        run=api('actions/runs/'+str(run_id));job_data=api('actions/runs/'+str(run_id)+'/attempts/1/jobs?per_page=100')
        require(job_data.get('total_count')==len(job_data.get('jobs',[])),'incomplete job evidence')
        verify_run(run,job_data['jobs'],workflow,run_id)

def verify_run_approval(control_sha,run_id):
    """Repository-side annotated approval survives workflow-run history removal.

    Created by the authorized operator after dispatch, never by this read-only
    workflow token. The fixed ref must not be force-updated or reused.
    """
    require(re.fullmatch('[1-9][0-9]*',run_id or '') is not None,'actual run ID required')
    ref_name='v518-cloud-build-approval/'+control_sha
    ref=api('git/ref/tags/'+ref_name)
    require(ref.get('ref')=='refs/tags/'+ref_name and ref.get('object',{}).get('type')=='tag','annotated run approval required')
    tag_sha=ref['object']['sha']
    require(re.fullmatch('[0-9a-f]{40}',tag_sha or '') is not None,'approval object SHA invalid')
    tag=api('git/tags/'+tag_sha)
    require(tag.get('tag')==ref_name and tag.get('object')=={'type':'commit','sha':control_sha,'url':'https://api.github.com/repos/'+REPOSITORY+'/git/commits/'+control_sha},'approval must target exact controller commit')
    approval=json.loads(tag.get('message',''))
    expected={'scope':'V518_BUILD_ARTIFACTS_ONLY','source_sha':SOURCE,'control_sha':control_sha,'run_id':int(run_id),'attempt':1,'production_cutover_authorized':False}
    require(canonical(approval)==canonical(expected),'approval is not for this exact single run')
    return tag_sha

def validate_runtime(identity,source_root,control_root,require_publish_approval=False):
    require(os.environ.get('GITHUB_REPOSITORY')==REPOSITORY,'repository mismatch')
    require(os.environ.get('GITHUB_REF')=='refs/heads/main','main-only controller')
    require(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','build reruns forbidden')
    control_sha=os.environ.get('APPROVED_CONTROL_SHA','')
    require(control_sha and control_sha==os.environ.get('OWNER_APPROVED_CONTROL_SHA'),'independent repository-side owner approval absent or mismatched')
    require(control_sha==os.environ.get('GITHUB_SHA')==git(control_root,'rev-parse','HEAD'),'controller mismatch')
    require(os.environ.get('REQUESTED_SHA')==SOURCE and os.environ.get('REQUESTED_REDIS')==REDIS,'requested inputs mismatch')
    require(datetime.now(timezone(timedelta(hours=8))).date().isoformat()==identity['release_date'],'notes date expired; refreeze required')
    subprocess.run(['git','-C',str(control_root),'merge-base','--is-ancestor',identity['controller_base'],control_sha],check=True)
    verify_source(source_root,identity);verify_github(identity,control_sha)
    if require_publish_approval:
        return verify_run_approval(control_sha,os.environ.get('GITHUB_RUN_ID',''))

def make_manifest(identity,backend_digest,frontend_digest):
    require(identity['source_sha']==SOURCE and identity['migration_sha256']==MIGRATION_SHA,'manifest identity drift')
    for value in (backend_digest,frontend_digest):
        require(re.fullmatch('sha256:[0-9a-f]{64}',value or '') is not None,'immutable digest required')
    return {'schema_version':1,'environment':'production','repository':REPOSITORY,'git_sha':SOURCE,'release_sha':SOURCE,'backend_image':f'ghcr.io/{REPOSITORY}/saas-collab-backend@{backend_digest}','frontend_image':f'ghcr.io/{REPOSITORY}/saas-collab-frontend@{frontend_digest}','redis_image':REDIS,'migration_sha256':MIGRATION_SHA,'compose_sha256':'owner-controlled-on-target'}

def write_json(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

def read_gate_reports(directory,control_root):
    helper=Path(control_root)/'saas-collab-system/backend/scripts/production_build_only.py'
    spec=importlib.util.spec_from_file_location('sealed_evidence_readers',helper);old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    return {'mysql_gate':old.verify_reports(directory,directory),'mysql_sales_gate':old.verify_sales_reports(directory,directory),'mysql_sync_workspace_gate':old.verify_sync_workspace_report(directory,directory)}

def create_receipt(identity,directory,control_root,approval_tag_sha):
    require(re.fullmatch('[0-9a-f]{40}',approval_tag_sha or '') is not None,'verified run approval evidence required')
    gates=read_gate_reports(directory,control_root)
    manifest=make_manifest(identity,os.environ['BACKEND_DIGEST'],os.environ['FRONTEND_DIGEST'])
    write_json(directory/'release-manifest.json',manifest)
    write_json(directory/'build-only-receipt.json',{'schema_version':1,'status':'BUILT_NOT_DEPLOYED','git_sha':SOURCE,'source_tree':TREE,'control_sha':os.environ['GITHUB_SHA'],'workflow_run_id':os.environ['GITHUB_RUN_ID'],'workflow_run_attempt':1,'run_approval_tag_sha':approval_tag_sha,'manifest_sha256':digest((directory/'release-manifest.json').read_bytes()),'release_notes_sha256':NOTES_SHA,'security_risk':{'advisory':'GHSA-g3hv-75wg-m249','package':'minimatch9.0.9','accepted_for_this_batch':True,'resolved':False},'notes_exception':{'original_date_preserved':'2026-11-20','append_date':identity['release_date'],'original_entries_preserved':58,'appended_lines':32},**gates,'vm_mutated':False,'cloud_mutated':False,'ledger_mutated':False,'deployment_authorized_by_this_receipt':False,'compose_runtime_verified':False,'actual_cloud_restore_rehearsal_performed':False})
    with (directory/'SHA256SUMS.txt').open('x',encoding='utf-8',newline='\n') as stream:
        for path in sorted(directory.rglob('*')):
            if path.is_file() and path.name!='SHA256SUMS.txt':
                stream.write(digest(path.read_bytes())+'  '+path.relative_to(directory).as_posix()+'\n')

def verify_completed_bundle(directory,run,control_sha):
    """A normal artifact name or success-looking receipt alone never admits it."""
    require(run.get('status')=='completed' and run.get('conclusion')=='success','build run not terminal success')
    require(run.get('head_sha')==control_sha and run.get('head_branch')=='main','completed control identity drift')
    require(run.get('path')=='.github/workflows/v518-cloud-artifacts-build-only.yml' and run.get('event')=='workflow_dispatch' and run.get('run_attempt')==1,'completed workflow identity drift')
    root=Path(directory).resolve();entries={}
    require(not any('HOLD' in path.name.upper() or path.name=='unverified-build-disposition.json' for path in root.rglob('*')),'HOLD evidence present')
    for line in (root/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
        match=re.fullmatch('([0-9a-f]{64})  (.+)',line)
        require(match is not None,'malformed checksum line')
        expected,rel=match.groups();path=root/rel
        require('\\' not in rel and not Path(rel).is_absolute() and '..' not in Path(rel).parts and rel!='SHA256SUMS.txt' and rel not in entries,'unsafe or duplicate checksum path')
        require(path.resolve().is_relative_to(root) and path.is_file() and not path.is_symlink(),'checksum path escapes bundle')
        cursor=path.parent
        while cursor!=root:
            require(not cursor.is_symlink(),'symbolic bundle parent');cursor=cursor.parent
        require(digest(path.read_bytes())==expected,'artifact checksum mismatch')
        entries[rel]=expected
    actual={path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file() and path.name!='SHA256SUMS.txt'}
    require(set(entries)==actual and {'release-manifest.json','build-only-receipt.json'}<=actual,'incomplete artifact checksums')
    receipt=json.loads((root/'build-only-receipt.json').read_text(encoding='utf-8'))
    manifest=json.loads((root/'release-manifest.json').read_text(encoding='utf-8'))
    require(receipt.get('status')=='BUILT_NOT_DEPLOYED' and receipt.get('git_sha')==SOURCE and receipt.get('source_tree')==TREE,'receipt source mismatch')
    require(receipt.get('control_sha')==control_sha and str(receipt.get('workflow_run_id'))==str(run.get('id')) and receipt.get('workflow_run_attempt')==1,'receipt run mismatch')
    require(receipt.get('release_notes_sha256')==NOTES_SHA and receipt.get('manifest_sha256')==entries['release-manifest.json'],'receipt digest mismatch')
    require(receipt.get('deployment_authorized_by_this_receipt') is False and receipt.get('cloud_mutated') is False,'build receipt cannot authorize production')
    for key,expected in {'git_sha':SOURCE,'release_sha':SOURCE,'repository':REPOSITORY,'environment':'production','redis_image':REDIS,'migration_sha256':MIGRATION_SHA}.items():
        require(manifest.get(key)==expected,'manifest identity mismatch: '+key)
    for key,component in [('backend_image','backend'),('frontend_image','frontend')]:
        require(re.fullmatch(re.escape('ghcr.io/'+REPOSITORY+'/saas-collab-'+component+'@sha256:')+'[0-9a-f]{64}',manifest.get(key,'')) is not None,'manifest mutable image')
    return receipt

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['validate','prepublish','manifest','admit'])
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--control-root',type=Path,required=True)
    parser.add_argument('--directory',type=Path)
    parser.add_argument('--build-run-id',type=int)
    parser.add_argument('--approved-control-sha')
    args=parser.parse_args();identity=load_identity()
    if args.operation=='admit':
        require(args.build_run_id is not None and args.build_run_id>0 and args.directory is not None,'actual completed run and bundle required')
        verify_source(args.source_root,identity)
        verify_github(identity,args.approved_control_sha,str(args.build_run_id))
        run=api('actions/runs/'+str(args.build_run_id))
        receipt=verify_completed_bundle(args.directory,run,args.approved_control_sha)
        require(verify_run_approval(args.approved_control_sha,str(args.build_run_id))==receipt.get('run_approval_tag_sha'),'approved run tag changed')
        print('PASS_COMPLETED_BUILD_ADMISSION; deployment remains unauthorized')
        return
    approval_tag_sha=validate_runtime(identity,args.source_root,args.control_root,require_publish_approval=args.operation!='validate')
    if args.operation in ('prepublish','manifest'):
        require(args.directory is not None and args.directory.is_dir(),'gate evidence directory required')
        if args.operation=='prepublish':
            write_json(args.directory/'prepublish-gates.json',{'status':'PASS_SYNTHETIC_GATE_REPORTS_BEFORE_PUBLISH','source_sha':SOURCE,**read_gate_reports(args.directory,args.control_root),'production_database_used':False,'actual_cloud_restore_rehearsal_performed':False})
        else:
            create_receipt(identity,args.directory,args.control_root,approval_tag_sha)
    print('PASS exact V518 artifact identity; production not deployed')

if __name__=='__main__':
    main()
