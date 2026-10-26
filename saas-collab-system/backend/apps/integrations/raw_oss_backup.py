"""Offline package core for paired local/OSS RAW references.

The manifest must be exported from an independently restored copy of the same
database backup. The command layer is responsible for proving/binding that
relationship; this module only binds the exact database bytes into the package.
No database, cloud API, or credentials are accessed here.
"""
from datetime import datetime, timezone, timedelta
import gzip
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import zlib

from . import raw_backup as _base

RawBackupError = _base.RawBackupError
MAX_PAYLOAD_BYTES = _base.MAX_PAYLOAD_BYTES
_NAMESPACE_RE = _base._NAMESPACE_RE
_HASH_RE = _base._HASH_RE
_KEY_RE = re.compile(r"^raw/(?P<namespace>[A-Za-z0-9][A-Za-z0-9._-]{0,63})/tenant-(?P<tenant>[1-9][0-9]*)/(?P<uuid>[0-9a-f]{32})\.json\.gz$")
_FIELDS = {"id", "raw_ref", "tenant_id", "payload_storage_alias", "payload_object_key", "payload_hash"}
_CHUNK = 1024 * 1024


def _parse_row(raw, namespace):
    try:
        row = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RawBackupError("Manifest contains an invalid JSONL row.") from None
    if not isinstance(row, dict) or set(row) != _FIELDS:
        raise RawBackupError("Manifest row must contain exactly the required reference fields.")
    for name in ("id", "tenant_id"):
        if type(row[name]) is not int or row[name] <= 0:
            raise RawBackupError("Manifest row has an invalid id or tenant_id.")
    if not isinstance(row["raw_ref"], str) or not row["raw_ref"] or len(row["raw_ref"]) > 80:
        raise RawBackupError("Manifest row has an invalid raw_ref.")
    alias, key, digest = row["payload_storage_alias"], row["payload_object_key"], row["payload_hash"]
    match = _KEY_RE.fullmatch(key) if isinstance(key, str) else None
    if alias not in ("raw_local", "raw_oss") or not match:
        raise RawBackupError("Manifest row has an invalid storage alias or object key.")
    if match.group("namespace") != namespace or match.group("tenant") != str(row["tenant_id"]):
        raise RawBackupError("Manifest row object key does not match namespace or tenant.")
    if not isinstance(digest, str) or not _HASH_RE.fullmatch(digest):
        raise RawBackupError("Manifest row has an invalid payload_hash.")
    return row


def _validate_object(path, expected_hash):
    info = _base._ordinary_file(path, "RAW object")
    if info.st_size > MAX_PAYLOAD_BYTES:
        raise RawBackupError("Compressed RAW object exceeds the 32 MiB limit.")
    body = bytearray()
    compressed_hash = hashlib.sha256()
    try:
        with open(path, "rb") as compressed:
            opened = os.fstat(compressed.fileno())
            if _base._path_signature(opened) != _base._path_signature(info):
                raise RawBackupError("RAW object changed while opening.")
            while True:
                block = compressed.read(_CHUNK)
                if not block: break
                compressed_hash.update(block)
            compressed.seek(0)
            payload = gzip.GzipFile(fileobj=compressed, mode="rb")
            while True:
                block = payload.read(min(_CHUNK, MAX_PAYLOAD_BYTES + 1 - len(body)))
                if not block: break
                body.extend(block)
                if len(body) > MAX_PAYLOAD_BYTES: raise RawBackupError("Decompressed RAW payload exceeds the 32 MiB limit.")
            if _base._stat_signature(opened) != _base._stat_signature(os.fstat(compressed.fileno())):
                raise RawBackupError("RAW object changed while validating.")
    except RawBackupError: raise
    except (OSError, EOFError, gzip.BadGzipFile, zlib.error):
        raise RawBackupError("RAW object is not a valid complete gzip payload.") from None
    try:
        value = json.loads(body.decode("utf-8"))
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
        raise RawBackupError("RAW object is not canonical JSON payload data.") from None
    if not isinstance(value, dict) or canonical != body or hashlib.sha256(canonical).hexdigest() != expected_hash:
        raise RawBackupError("RAW object canonical payload hash does not match payload_hash.")
    return info.st_size, compressed_hash.hexdigest()


def _safe_pkg_object(package, alias, key):
    parts = ("objects", alias, *key.split("/"))
    path = package
    for component in parts[:-1]:
        path = os.path.join(path, component)
        _base._ordinary_dir(path, "Package directory")
    path = os.path.join(path, parts[-1])
    _base._ordinary_file(path, "Packaged RAW object")
    return path


def _copy_stream(reader, dest, min_free_bytes):
    digest, total = hashlib.sha256(), 0
    with reader as src, open(dest, "xb") as out:
        if os.name != "nt": os.chmod(dest, 0o600)
        while True:
            block = src.read(_CHUNK)
            if not block: break
            total += len(block)
            if total > MAX_PAYLOAD_BYTES: raise RawBackupError("Compressed RAW object exceeds the 32 MiB limit.")
            _base._ensure_capacity(os.path.dirname(dest), len(block), min_free_bytes)
            digest.update(block); out.write(block)
        out.flush(); os.fsync(out.fileno())
    return total


def _tree_validate(package, db, expected):
    db.execute("CREATE TABLE expected_paths(path TEXT PRIMARY KEY)")
    db.execute("CREATE TABLE seen_paths(path TEXT PRIMARY KEY)")
    db.executemany("INSERT OR IGNORE INTO expected_paths VALUES (?)", ((path,) for path in expected))
    for current, dirs, files in os.walk(package, topdown=True, followlinks=False):
        for name in dirs:
            path = os.path.join(current, name); _base._ordinary_dir(path, "Package directory")
            db.execute("INSERT OR IGNORE INTO seen_paths VALUES (?)", (os.path.relpath(path, package).replace(os.sep, "/") + "/",))
        for name in files:
            path = os.path.join(current, name); _base._ordinary_file(path, "Package file")
            db.execute("INSERT OR IGNORE INTO seen_paths VALUES (?)", (os.path.relpath(path, package).replace(os.sep, "/"),))
    if (db.execute("SELECT 1 FROM expected_paths e LEFT JOIN seen_paths s USING(path) WHERE s.path IS NULL LIMIT 1").fetchone()
            or db.execute("SELECT 1 FROM seen_paths s LEFT JOIN expected_paths e USING(path) WHERE e.path IS NULL LIMIT 1").fetchone()):
        raise RawBackupError("Package contains missing or unexpected paths.")


def create_package(manifest_path, database_backup, namespace, output, readers, min_free_bytes=10737418240):
    """Create atomically. readers[alias](key) returns a context-manager binary stream."""
    if not isinstance(namespace, str) or not _NAMESPACE_RE.fullmatch(namespace): raise RawBackupError("Invalid namespace.")
    if isinstance(min_free_bytes, bool) or not isinstance(min_free_bytes, int) or min_free_bytes < 0: raise RawBackupError("min_free_bytes must be non-negative.")
    if not isinstance(readers, dict): raise RawBackupError("readers must map storage aliases to callables.")
    source_db_info = _base._ordinary_file(database_backup, "Database backup")
    output = os.path.abspath(output); parent = os.path.dirname(output)
    _base._ordinary_dir(parent, "Output parent")
    if os.path.lexists(output): raise RawBackupError("Output already exists; refusing to overwrite it.")
    _base._ensure_capacity(parent, source_db_info.st_size, min_free_bytes)
    temp = os.path.join(parent, ".raw-oss-package-" + secrets.token_hex(12))
    os.mkdir(temp, 0o700)
    # Empty filename asks SQLite for a temporary on-disk database, avoiding a
    # process-memory index when manifests contain many millions of references.
    db = sqlite3.connect("")
    db.executescript("CREATE TABLE refs(id INTEGER PRIMARY KEY, raw_ref TEXT UNIQUE, tenant INTEGER, alias TEXT, object_key TEXT, payload_hash TEXT); CREATE TABLE objects(alias TEXT, object_key TEXT, payload_hash TEXT, byte_count INTEGER, compressed_hash TEXT, PRIMARY KEY(alias,object_key)); CREATE INDEX objects_key_hash_idx ON objects(object_key,payload_hash);")
    try:
        os.mkdir(os.path.join(temp, "objects"), 0o700)
        db_dest = os.path.join(temp, "database.bin")
        source_sig = _base._path_signature(source_db_info)
        source_digest = hashlib.sha256(); copied = 0
        with open(database_backup, "rb") as src, open(db_dest, "xb") as dst:
            opened = os.fstat(src.fileno())
            if _base._path_signature(opened) != source_sig: raise RawBackupError("Database backup changed before copy.")
            while True:
                block = src.read(_CHUNK)
                if not block: break
                copied += len(block); source_digest.update(block); dst.write(block)
            if copied != opened.st_size or _base._stat_signature(opened) != _base._stat_signature(os.fstat(src.fileno())):
                raise RawBackupError("Database backup changed while being copied.")
            dst.flush(); os.fsync(dst.fileno())
        if _base._path_signature(_base._ordinary_file(database_backup, "Database backup")) != source_sig:
            raise RawBackupError("Database backup changed while being copied.")
        db_hash = _base._sha256_file(db_dest, "Database backup")
        if db_hash != source_digest.hexdigest(): raise RawBackupError("Copied database backup hash does not match source.")
        refs_path = os.path.join(temp, "refs.jsonl")
        # Canonicalize line endings and JSON representation while retaining exact six-field rows.
        with open(refs_path, "xb") as refs:
            if os.name != "nt": os.chmod(refs_path, 0o600)
            _base._ordinary_file(manifest_path, "Manifest")
            with open(manifest_path, "rb") as src:
                count = 0
                while line := src.readline(_base.MAX_MANIFEST_LINE_BYTES + 1):
                    if len(line) > _base.MAX_MANIFEST_LINE_BYTES or not line.strip(): raise RawBackupError("Manifest has a blank row or row over 1 MiB.")
                    row = _parse_row(line, namespace)
                    try:
                        db.execute("INSERT INTO refs VALUES (?,?,?,?,?,?)", (row["id"],row["raw_ref"],row["tenant_id"],row["payload_storage_alias"],row["payload_object_key"],row["payload_hash"]))
                    except sqlite3.IntegrityError: raise RawBackupError("Manifest contains duplicate id or raw_ref.") from None
                    db.execute("INSERT OR IGNORE INTO objects VALUES (?,?,?,0,NULL)",(row["payload_storage_alias"],row["payload_object_key"],row["payload_hash"]))
                    existing = db.execute("SELECT payload_hash FROM objects WHERE alias=? AND object_key=?",(row["payload_storage_alias"],row["payload_object_key"])).fetchone()
                    if existing[0] != row["payload_hash"]: raise RawBackupError("Shared object key has inconsistent payload hash.")
                    conflict = db.execute("SELECT 1 FROM objects WHERE object_key=? AND payload_hash<>? LIMIT 1",(row["payload_object_key"],row["payload_hash"])).fetchone()
                    if conflict: raise RawBackupError("Shared object key has inconsistent payload hash.")
                    refs.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()+b"\n"); count += 1
            refs.flush(); os.fsync(refs.fileno())
        total = 0
        object_index_path=os.path.join(temp,"object_index.jsonl")
        with open(object_index_path,"xb") as object_index:
          if os.name != "nt": os.chmod(object_index_path,0o600)
          index_digest=hashlib.sha256()
          for alias,key,payload_hash in db.execute("SELECT alias,object_key,payload_hash FROM objects ORDER BY alias,object_key"):
            if alias not in readers or not callable(readers[alias]): raise RawBackupError("Manifest references an unavailable storage alias.")
            target = os.path.join(temp,"objects",alias,*key.split("/")); os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
            _base._ensure_capacity(os.path.dirname(target),0,min_free_bytes)
            try: stream = readers[alias](key)
            except Exception: raise RawBackupError("RAW object could not be read.") from None
            size = _copy_stream(stream,target,min_free_bytes); _payload_size, compressed_hash = _validate_object(target,payload_hash); total += size
            db.execute("UPDATE objects SET byte_count=?,compressed_hash=? WHERE alias=? AND object_key=?",(size,compressed_hash,alias,key))
            index_line=json.dumps({"alias":alias,"object_key":key,"compressed_sha256":compressed_hash,"compressed_bytes":size},sort_keys=True,separators=(",",":" )).encode()+b"\n"
            object_index.write(index_line); index_digest.update(index_line)
          object_index.flush(); os.fsync(object_index.fileno())
        ref_hash = _base._sha256_file(refs_path,"Reference manifest")
        meta={"format_version":1,"namespace":namespace,"created_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"database_backup_sha256":db_hash,"refs_sha256":ref_hash,"object_index_sha256":index_digest.hexdigest(),"reference_count":count,"object_count":db.execute("SELECT count(*) FROM objects").fetchone()[0],"total_bytes":total}
        with open(os.path.join(temp,"metadata.json"),"x",encoding="utf-8",newline="\n") as f:
            if os.name != "nt": os.chmod(f.name,0o600)
            json.dump(meta,f,sort_keys=True,separators=(",",":")); f.write("\n"); f.flush(); os.fsync(f.fileno())
        _base._fsync_dir(temp)
        verify_package(temp)
        if os.path.lexists(output): raise RawBackupError("Output already exists; refusing to overwrite it.")
        os.rename(temp,output); _base._fsync_dir(parent)
        return {"status":"complete","path":output,"reference_count":count,"object_count":meta["object_count"],"total_bytes":total,"database_backup_sha256":db_hash,"refs_sha256":ref_hash}
    except RawBackupError: raise
    except Exception as exc: raise RawBackupError(f"Package creation failed ({type(exc).__name__}).") from None
    finally:
        db.close()
        if os.path.lexists(temp): shutil.rmtree(temp,ignore_errors=True)


def verify_package(package):
    _base._ordinary_dir(package,"Package")
    meta_path=os.path.join(package,"metadata.json"); refs=os.path.join(package,"refs.jsonl"); dbpath=os.path.join(package,"database.bin"); object_index=os.path.join(package,"object_index.jsonl")
    for p,n in ((meta_path,"Metadata"),(refs,"Reference manifest"),(dbpath,"Database backup"),(object_index,"Object index")): _base._ordinary_file(p,n)
    try:
        if os.path.getsize(meta_path)>65536: raise ValueError
        with open(meta_path,"rb") as f: meta=json.loads(f.read(65537).decode("utf-8"))
    except Exception: raise RawBackupError("Package metadata is invalid.") from None
    fields={"format_version","namespace","created_at","database_backup_sha256","refs_sha256","object_index_sha256","reference_count","object_count","total_bytes"}
    if not isinstance(meta,dict) or set(meta)!=fields or type(meta["format_version"]) is not int or meta["format_version"]!=1 or not isinstance(meta["namespace"],str) or not _NAMESPACE_RE.fullmatch(meta["namespace"]): raise RawBackupError("Package metadata fields are invalid.")
    for name in ("reference_count", "object_count", "total_bytes"):
        if type(meta[name]) is not int or meta[name] < 0: raise RawBackupError("Package metadata counts are invalid.")
    for name in ("database_backup_sha256", "refs_sha256", "object_index_sha256"):
        if not isinstance(meta[name],str) or not _HASH_RE.fullmatch(meta[name]): raise RawBackupError("Package metadata hash is invalid.")
    try:
        created=datetime.fromisoformat(meta["created_at"].replace("Z","+00:00"))
        if created.tzinfo is None: raise ValueError
    except Exception: raise RawBackupError("Package creation time is invalid.") from None
    if (_base._sha256_file(dbpath,"Database backup") != meta["database_backup_sha256"]
            or _base._sha256_file(refs,"Reference manifest") != meta["refs_sha256"]
            or _base._sha256_file(object_index,"Object index") != meta["object_index_sha256"]):
        raise RawBackupError("Package database or index hash mismatch.")
    db=sqlite3.connect(""); db.executescript("CREATE TABLE refs(id INTEGER PRIMARY KEY,raw_ref TEXT UNIQUE,tenant INTEGER,alias TEXT,object_key TEXT,payload_hash TEXT); CREATE TABLE objects(alias TEXT,object_key TEXT,payload_hash TEXT,compressed_hash TEXT,compressed_bytes INTEGER,PRIMARY KEY(alias,object_key)); CREATE INDEX objects_key_hash_idx ON objects(object_key,payload_hash);")
    count=0
    try:
        with open(refs,"rb") as f:
            while line:=f.readline(_base.MAX_MANIFEST_LINE_BYTES+1):
                if len(line)>_base.MAX_MANIFEST_LINE_BYTES or not line.strip(): raise RawBackupError("Reference manifest row is invalid.")
                row=_parse_row(line,meta["namespace"])
                try:
                    db.execute("INSERT INTO refs VALUES (?,?,?,?,?,?)",(row["id"],row["raw_ref"],row["tenant_id"],row["payload_storage_alias"],row["payload_object_key"],row["payload_hash"]))
                except sqlite3.IntegrityError: raise RawBackupError("Package has duplicate references.") from None
                db.execute("INSERT OR IGNORE INTO objects VALUES (?,?,?,NULL,NULL)",(row["payload_storage_alias"],row["payload_object_key"],row["payload_hash"]))
                if db.execute("SELECT payload_hash FROM objects WHERE alias=? AND object_key=?",(row["payload_storage_alias"],row["payload_object_key"])).fetchone()[0]!=row["payload_hash"]: raise RawBackupError("Package shared object key conflict.")
                if db.execute("SELECT 1 FROM objects WHERE object_key=? AND payload_hash<>? LIMIT 1",(row["payload_object_key"],row["payload_hash"])).fetchone(): raise RawBackupError("Package shared object key conflict.")
                count+=1
        index_count=0
        with open(object_index,"rb") as f:
            while line:=f.readline(_base.MAX_MANIFEST_LINE_BYTES+1):
                if len(line)>_base.MAX_MANIFEST_LINE_BYTES: raise RawBackupError("Object index row exceeds the 1 MiB limit.")
                try: row=json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError,json.JSONDecodeError): raise RawBackupError("Object index row is invalid.") from None
                if not isinstance(row,dict) or set(row)!={"alias","object_key","compressed_sha256","compressed_bytes"} or row["alias"] not in ("raw_local","raw_oss") or not isinstance(row["object_key"],str) or not isinstance(row.get("compressed_sha256"),str) or not _HASH_RE.fullmatch(row["compressed_sha256"]) or type(row["compressed_bytes"]) is not int or row["compressed_bytes"]<0: raise RawBackupError("Object index fields are invalid.")
                key_match=_KEY_RE.fullmatch(row["object_key"])
                if not key_match or key_match.group("namespace")!=meta["namespace"]: raise RawBackupError("Object index key is invalid.")
                try: db.execute("UPDATE objects SET compressed_hash=?,compressed_bytes=? WHERE alias=? AND object_key=? AND compressed_hash IS NULL",(row["compressed_sha256"],row["compressed_bytes"],row["alias"],row["object_key"]))
                except sqlite3.Error: raise RawBackupError("Object index is invalid.") from None
                if db.execute("SELECT changes()").fetchone()[0]!=1: raise RawBackupError("Object index does not match references.")
                index_count+=1
        if index_count!=db.execute("SELECT count(*) FROM objects").fetchone()[0]: raise RawBackupError("Object index is incomplete.")
        total=0
        for alias,key,digest,compressed_hash,compressed_bytes in db.execute("SELECT alias,object_key,payload_hash,compressed_hash,compressed_bytes FROM objects"):
            if compressed_hash is None or compressed_bytes is None: raise RawBackupError("Object index is incomplete.")
            rel="objects/"+alias+"/"+key
            parts=rel.split("/")
            size,actual_compressed_hash=_validate_object(_safe_pkg_object(package,alias,key),digest)
            if size!=compressed_bytes or actual_compressed_hash!=compressed_hash: raise RawBackupError("Compressed RAW object hash or size mismatch.")
            total+=size
        def expected_paths():
            yield from ("metadata.json","refs.jsonl","database.bin","object_index.jsonl","objects/")
            for alias,key in db.execute("SELECT alias,object_key FROM objects"):
                parts=("objects",alias,*key.split("/"))
                for i in range(1,len(parts)): yield "/".join(parts[:i]) + "/"
                yield "/".join(parts)
        _tree_validate(package,db,expected_paths())
        if count!=meta["reference_count"] or db.execute("SELECT count(*) FROM objects").fetchone()[0]!=meta["object_count"] or total!=sum(r[0] for r in db.execute("SELECT compressed_bytes FROM objects")): raise RawBackupError("Package indexes or counts do not match metadata.")
        if total!=meta["total_bytes"]: raise RawBackupError("Package byte count does not match metadata.")
        return {"status":"verified","reference_count":count,"object_count":meta["object_count"],"total_bytes":total,"database_backup_sha256":meta["database_backup_sha256"],"refs_sha256":meta["refs_sha256"],"object_index_sha256":meta["object_index_sha256"]}
    finally: db.close()


def restore_objects(package, writers):
    verify_package(package)
    db=sqlite3.connect("")
    try:
        refs=os.path.join(package,"refs.jsonl")
        with open(os.path.join(package,"metadata.json"),encoding="utf-8") as metadata: meta=json.load(metadata)
        db.execute("CREATE TABLE objects(alias TEXT,key TEXT,PRIMARY KEY(alias,key))")
        with open(refs,"rb") as f:
            for line in f:
                row=_parse_row(line,meta["namespace"]); db.execute("INSERT OR IGNORE INTO objects VALUES (?,?)",(row["payload_storage_alias"],row["payload_object_key"]))
        for (alias,) in db.execute("SELECT DISTINCT alias FROM objects"):
            if alias not in writers or not callable(writers[alias]): raise RawBackupError("No writer is configured for a referenced storage alias.")
        for alias,key in db.execute("SELECT alias,key FROM objects ORDER BY alias,key"):
            writers[alias](key,_safe_pkg_object(package,alias,key))
        return db.execute("SELECT count(*) FROM objects").fetchone()[0]
    finally: db.close()


def retention_report(packages, now=None, days=30):
    if isinstance(days,bool) or not isinstance(days,int) or days<0: raise RawBackupError("days must be a non-negative integer.")
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise RawBackupError("now must be timezone-aware.")
    cutoff=now.astimezone(timezone.utc)-timedelta(days=days); expired=[]; invalid=[]
    for package in packages:
        try:
            verify_package(package)
            with open(os.path.join(package,"metadata.json"),encoding="utf-8") as f: meta=json.load(f)
            created=datetime.fromisoformat(meta["created_at"].replace("Z","+00:00")).astimezone(timezone.utc)
            if created < cutoff: expired.append({"path":os.path.abspath(package),"reference_count":meta["reference_count"],"object_count":meta["object_count"],"created_at":meta["created_at"]})
        except RawBackupError: invalid.append(os.path.abspath(package))
    return {"status":"reported","days":days,"expired_count":len(expired),"expired":expired,
            "invalid_count":len(invalid),"invalid_packages":invalid,"deleted_objects":0}
