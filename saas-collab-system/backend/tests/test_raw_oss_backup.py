import gzip
import hashlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

from apps.integrations.raw_oss_backup import (
    RawBackupError, create_package, verify_package, restore_objects, retention_report,
)


class RawOssBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.ns = "unit-test"
        self.key1 = f"raw/{self.ns}/tenant-1/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json.gz"
        self.key2 = f"raw/{self.ns}/tenant-2/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.json.gz"
        self.payload1 = b'{"v":1}'
        self.payload2 = b'{"v":2}'
        self.blobs = {"raw_local": self.gz(self.payload1), "raw_oss": self.gz(self.payload2)}
        self.db = os.path.join(self.root, "db.dump")
        with open(self.db, "wb") as f: f.write(b"database bytes")
        self.manifest = os.path.join(self.root, "manifest.jsonl")

    def tearDown(self): self.tmp.cleanup()

    @staticmethod
    def gz(payload): return gzip.compress(payload)

    def row(self, ident, ref, tenant, alias, key, payload):
        return {"id": ident, "raw_ref": ref, "tenant_id": tenant,
                "payload_storage_alias": alias, "payload_object_key": key,
                "payload_hash": hashlib.sha256(payload).hexdigest()}

    def write_manifest(self, rows):
        with open(self.manifest, "wb") as f:
            for row in rows: f.write(json.dumps(row,separators=(",", ":")).encode()+b"\n")

    def readers(self):
        blobs = self.blobs
        return {alias: (lambda key, alias=alias: io.BytesIO(blobs[alias])) for alias in blobs}

    def build(self, rows=None, name="package"):
        if rows is None:
            rows=[self.row(1,"local-a",1,"raw_local",self.key1,self.payload1),
                  self.row(2,"oss-a",2,"raw_oss",self.key2,self.payload2),
                  self.row(3,"local-shared",1,"raw_local",self.key1,self.payload1)]
        self.write_manifest(rows)
        path=os.path.join(self.root,name)
        result=create_package(self.manifest,self.db,self.ns,path,self.readers(),min_free_bytes=0)
        return path,result

    def test_mixed_alias_shared_object_verify_restore_and_retention(self):
        package,summary=self.build()
        self.assertEqual(summary["object_count"],2)
        with open(os.path.join(package,"database.bin"),"rb") as db_copy:
            self.assertEqual(hashlib.sha256(db_copy.read()).hexdigest(),summary["database_backup_sha256"])
        verified=verify_package(package)
        self.assertEqual(verified["reference_count"],3)
        calls=[]
        def capture(alias, key, path):
            with open(path,"rb") as stream: calls.append((alias,key,stream.read()))
        count=restore_objects(package,{"raw_local":lambda k,p:capture("raw_local",k,p),
                                       "raw_oss":lambda k,p:capture("raw_oss",k,p)})
        self.assertEqual(count,2)
        self.assertEqual(len(calls),2)
        self.assertEqual(retention_report([package],now=datetime.now(timezone.utc)+timedelta(days=31))["expired_count"],1)
        self.assertEqual(retention_report([package],now=datetime.now(timezone.utc),days=30)["expired_count"],0)

    def test_missing_corrupt_and_oversized_object_fail_without_publishing(self):
        self.blobs["raw_local"] = self.gz(b'{"v":9}')
        with self.assertRaises(RawBackupError): self.build(name="bad-hash")
        self.assertFalse(os.path.exists(os.path.join(self.root,"bad-hash")))
        self.blobs["raw_local"] = b"not gzip"
        with self.assertRaises(RawBackupError): self.build(name="bad-gzip")
        self.blobs["raw_local"] = gzip.compress(b"x"*(32*1024*1024+1))
        with self.assertRaises(RawBackupError): self.build(name="too-large")

    def test_invalid_namespace_tenant_unknown_alias_and_duplicate_refs(self):
        row=self.row(1,"ref",1,"raw_local",self.key1,self.payload1)
        self.write_manifest([row])
        with self.assertRaises(RawBackupError): create_package(self.manifest,self.db,"../x",os.path.join(self.root,"badns"),self.readers(),0)
        row["payload_object_key"]=self.key2
        self.write_manifest([row])
        with self.assertRaises(RawBackupError): self.build([row],"tenant-mismatch")
        row["tenant_id"]=2; row["payload_object_key"]="raw/unit-test/tenant-2/../../outside.json.gz"
        with self.assertRaises(RawBackupError): self.build([row],"traversal")
        row["tenant_id"]=1; row["payload_object_key"]=self.key1
        row["payload_object_key"]=self.key1; row["payload_storage_alias"]="elsewhere"
        with self.assertRaises(RawBackupError): self.build([row],"unknown-alias")
        row["payload_storage_alias"]="raw_local"
        with self.assertRaises(RawBackupError): self.build([row,{**row,"id":2}],"duplicate-ref")

    def test_database_metadata_and_incomplete_tree_are_verified(self):
        package,_=self.build()
        with open(os.path.join(package,"database.bin"),"ab") as f: f.write(b"tamper")
        with self.assertRaises(RawBackupError): verify_package(package)
        package,_=self.build(name="incomplete")
        os.unlink(os.path.join(package,"objects","raw_local",*self.key1.split("/")))
        with self.assertRaises(RawBackupError): verify_package(package)
        package,_=self.build(name="extra")
        with open(os.path.join(package,"extra"),"wb") as f: f.write(b"x")
        with self.assertRaises(RawBackupError): verify_package(package)

    def test_restore_verifies_before_first_writer(self):
        package,_=self.build()
        with open(os.path.join(package,"refs.jsonl"),"ab") as f: f.write(b"bad\n")
        calls=[]
        with self.assertRaises(RawBackupError): restore_objects(package,{"raw_local":lambda *a:calls.append(a),"raw_oss":lambda *a:calls.append(a)})
        self.assertEqual(calls,[])

    def test_recompression_with_same_payload_fails_compressed_object_binding(self):
        package,_=self.build()
        object_path=os.path.join(package,"objects","raw_local",*self.key1.split("/"))
        with open(object_path,"wb") as stream: stream.write(gzip.compress(self.payload1,mtime=1))
        with self.assertRaises(RawBackupError): verify_package(package)


if __name__ == "__main__": unittest.main()
