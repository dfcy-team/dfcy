import copy, json, tempfile, unittest, shutil, os
from pathlib import Path
from unittest.mock import patch
import verify_frozen_v227 as v

BASE = Path(os.environ.get("V227_TEST_ARTIFACT_ROOT", str(Path(__file__).resolve().parents[1] / "ci-promotion-provenance-original")))

class FrozenV227Tests(unittest.TestCase):
    def setUp(self):
        self.m = json.loads((BASE / "release-manifest.json").read_text(encoding="utf-8"))
        self.r = json.loads((BASE / "build-only-receipt.json").read_text(encoding="utf-8"))
        self.temp = tempfile.TemporaryDirectory()
        self.artifact = Path(self.temp.name)
        for name in v.FROZEN_FILES: shutil.copyfile(BASE / name, self.artifact / name)
    def tearDown(self): self.temp.cleanup()
    def test_real_artifact(self): self.assertTrue(v.check_artifact(self.artifact))
    def test_manifest_field_binding(self):
        for key in ("repository", "git_sha", "release_sha", "backend_image", "frontend_image", "redis_image", "migration_sha256", "compose_sha256"):
            m=copy.deepcopy(self.m); m[key]="tampered"
            with self.assertRaises(ValueError): v.check_artifact(self.artifact,m,self.r)
    def test_receipt_binding_and_not_deployed(self):
        for key,value in (("status","DEPLOYED"),("baseline_git_sha",v.APP),("git_sha",v.PARENT),("manifest_sha256","0"*64),("workflow_run_id","0"),("workflow_run_attempt","2"),("vm_mutated",True),("deployment_authorized_by_this_receipt",True)):
            r=copy.deepcopy(self.r); r[key]=value
            with self.assertRaises(ValueError): v.check_artifact(self.artifact,self.m,r)
    def test_gate_required(self):
        r=copy.deepcopy(self.r); r["mysql_sales_gate"]["status"]="FAIL"
        with self.assertRaises(ValueError): v.check_artifact(self.artifact,self.m,r)
    def test_api_provenance(self):
        run={"id":int(v.RUN),"run_attempt":int(v.ATTEMPT),"name":"Production Artifacts Build Only","head_sha":v.APP,"head_branch":"main","event":"workflow_dispatch","status":"completed","conclusion":"success","repository":{"full_name":v.REPO}}
        artifact={"id":int(v.ARTIFACT),"workflow_run":{"id":int(v.RUN),"head_sha":v.APP,"head_branch":"main","repository_id":v.REPOSITORY_ID},"expired":False,"name":v.ARTIFACT_NAME}
        jobs={"total_count":6,"jobs":[{"name":n,"status":"completed","conclusion":"success"} for n in sorted(v.JOBS)]}
        v.verify_api(run,artifact,jobs)
        for field in ("head_sha","name","head_branch","event","status","conclusion"):
            bad=dict(run); bad[field]="wrong"
            with self.assertRaises(ValueError): v.verify_api(bad,artifact,jobs)
        for field,value in (("head_sha","wrong"),("head_branch","wrong"),("repository_id",0)):
            ar=dict(artifact["workflow_run"]); ar[field]=value
            with self.assertRaises(ValueError): v.verify_api(run,{**artifact,"workflow_run":ar},jobs)
        with self.assertRaises(ValueError): v.verify_api(run,{**artifact,"expired":True},jobs)
        bad=dict(jobs); bad["jobs"]=jobs["jobs"][:-1]
        with self.assertRaises(ValueError): v.verify_api(run,artifact,bad)
        with self.assertRaises(ValueError): v.verify_api(run,artifact,{**jobs,"jobs":[*jobs["jobs"],jobs["jobs"][0]]})
        with self.assertRaises(ValueError): v.verify_api(run,artifact,{**jobs,"jobs":[{**jobs["jobs"][0],"status":"queued"},*jobs["jobs"][1:]]})
    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(ValueError): json.loads('{"x":1,"x":2}', object_pairs_hook=v.pairs)
        with self.assertRaises(ValueError): json.loads('{"x":NaN}', object_pairs_hook=v.pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    def test_extra_file_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); (p/"release-manifest.json").write_text("{}"); (p/"build-only-receipt.json").write_text("{}"); (p/"unexpected").write_text("x")
            with self.assertRaises(ValueError): v.check_artifact(p)
        (self.artifact/'unexpected').write_text('x')
        with self.assertRaises(ValueError): v.check_artifact(self.artifact)

    def test_all_eleven_raw_hashes_are_required(self):
        for name in v.FROZEN_FILES:
            p=self.artifact/name; raw=p.read_bytes();p.write_bytes(raw+b' ')
            with self.assertRaises(ValueError):v.check_artifact(self.artifact)
            p.write_bytes(raw)

    def test_missing_file_and_symlink_context(self):
        p=self.artifact/'index-migration.json';p.unlink()
        with self.assertRaises(ValueError):v.check_artifact(self.artifact)
        shutil.copyfile(BASE/p.name,p)
        with patch.object(Path,'is_symlink',return_value=True):
            with self.assertRaises(ValueError):v.check_artifact(self.artifact)

    def test_strict_json_reader(self):
        p=self.artifact/'bad.json'
        for raw in ('{"x":1,"x":2}','{"x":NaN}','{"x":Infinity}'):
            p.write_text(raw)
            with self.assertRaises(ValueError):v.read_json(p)

    def test_fixed_control_context_and_no_output_injection(self):
        valid={'GITHUB_REPOSITORY':v.REPO,'GITHUB_REF':'refs/heads/main','GITHUB_SHA':'a'*40,'APPROVED_CONTROL_SHA':'a'*40,'OPERATION':'dry_run','GITHUB_ACTOR':'dfcy01'}
        with patch.dict(os.environ,valid,clear=True):self.assertEqual(v.validate_context(),('a'*40,'dry_run','dfcy01'))
        for key,value in (('GITHUB_REPOSITORY','x/y'),('GITHUB_REF','refs/heads/other'),('GITHUB_SHA','b'*40),('APPROVED_CONTROL_SHA','not-a-sha'),('OPERATION','build'),('GITHUB_ACTOR','actor\nrelease_sha=x')):
            with patch.dict(os.environ,{**valid,key:value},clear=True):
                with self.assertRaises(ValueError):v.validate_context()
        with patch.dict(os.environ,{**valid,'GITHUB_SHA':v.APP,'APPROVED_CONTROL_SHA':v.APP},clear=True):
            with self.assertRaises(ValueError):v.validate_context()

if __name__ == "__main__": unittest.main()
