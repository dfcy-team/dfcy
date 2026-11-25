"""Private, validated settings shards; no user bootstrap or credentials are stored."""
from contextlib import contextmanager
import errno
import hashlib
import json
import logging
import os
from pathlib import Path
import re
from threading import BoundedSemaphore
import time
import uuid

from celery import shared_task
from django.conf import settings
from rest_framework.exceptions import ValidationError

_BUILD_SLOT = BoundedSemaphore(1)
_MAGIC = b'SAAS-FINANCE-SETTINGS-2\n'
logger = logging.getLogger(__name__)


def fragment_root(source_path):
    source = Path(source_path).resolve()
    if not source.is_file():
        return None
    root = source.parent / 'settings-documents-v1'
    try:
        root.mkdir(exist_ok=True)
        return root.resolve() if root.resolve().parent==source.parent and root.resolve().name==root.name else None
    except OSError:
        return None


def fragment_path(key):
    if not key[4] or not re.fullmatch(r'[0-9a-f]{64}', key[1]):
        return None
    root = fragment_root(key[0])
    if root is None:
        return None
    name = hashlib.sha256(json.dumps(key,sort_keys=True).encode()).hexdigest()+'.fdoc'
    return root / name


def load_fragment(key):
    path = fragment_path(key)
    if path is None:
        return None
    try:
        if path.stat().st_size>32*1024*1024:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if not data.startswith(_MAGIC):
        return None
    identity, separator, remaining = data[len(_MAGIC):].partition(b'\n')
    digest, checksum_separator, body = remaining.partition(b'\n')
    if not separator or not checksum_separator or identity!=path.stem.encode() or hashlib.sha256(body).hexdigest().encode()!=digest:
        return None
    return body


def save_fragment(key, body):
    path = fragment_path(key)
    if path is None or len(body)>32*1024*1024:
        return
    temporary = path.parent / ('.build-'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_bytes(_MAGIC+path.stem.encode()+b'\n'+hashlib.sha256(body).hexdigest().encode()+b'\n'+body)
        os.replace(temporary,path)
    except OSError:
        # An optional cache must not make accepted accounting data unavailable.
        pass
    finally:
        if temporary.resolve().parent==path.parent.resolve():
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


@contextmanager
def document_generation_lock(source_path):
    # One large generator per process and per shared private source directory.
    with _BUILD_SLOT:
        root = fragment_root(source_path)
        if root is None:
            yield
            return
        try:
            handle = (root / '.generation.lock').open('a+b')
        except OSError:
            yield
            return
        locked = False
        try:
            if handle.seek(0,2)==0:
                handle.write(b'0');handle.flush()
            started = time.monotonic()
            while not locked:
                try:
                    handle.seek(0)
                    if os.name=='nt':
                        import msvcrt
                        msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                    locked=True
                except OSError as error:
                    if error.errno not in {errno.EACCES,errno.EAGAIN,errno.EDEADLK}:
                        raise
                    if time.monotonic()-started>120:
                        raise ValidationError('设置文档正在准备，请稍后重新打开。') from None
                    time.sleep(0.05)
            yield
        finally:
            if locked:
                handle.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
            handle.close()


def queue_settings_warmup(pk, offset=0):
    try:
        warm_settings_documents.apply_async(args=[pk,offset],queue=getattr(settings,'FINANCE_SUMMARY_REBUILD_QUEUE',getattr(settings,'FINANCE_SUMMARY_QUEUE','finance-summary')),retry=False)
    except Exception:
        # First access still builds and validates the shard synchronously.
        pass


@shared_task(soft_time_limit=840,time_limit=900)
def warm_settings_documents(pk, offset=0):
    from .summary_models import FinanceSummaryDataset
    from .summary_service import document_path
    from .summary_views import prepared_document,presentation_stamp
    dataset=FinanceSummaryDataset.objects.filter(pk=pk,active=True).first()
    if not dataset or not dataset.metadata.get('database_scope'):
        return {'prepared':0}
    stores=dataset.metadata.get('store_ids',[])
    if offset<0 or offset>=len(stores):
        return {'prepared':0}
    path=document_path(dataset);stamp=path.stat()
    prepared_document(str(path),dataset.source_hash,(stamp.st_mtime_ns,stamp.st_size),presentation_stamp(),True,stores[offset])
    # Rejoin the tail so a batch rebuild can run between two store shards.
    if offset+1<len(stores) and FinanceSummaryDataset.objects.filter(pk=pk,active=True).exists():
        queue_settings_warmup(pk,offset+1)
    return {'prepared':1}


def prune_settings_fragments(root, cutoff):
    original=Path(root).absolute()
    try:
        root=original.resolve()
        if original.is_symlink() or root.parent!=original.parent.resolve() or root.name!=original.name:
            return 0
    except (OSError,RuntimeError):
        return 0
    deleted=0;deleted_bytes=0
    if not root.is_dir():
        return 0
    for path in root.glob('*.fdoc'):
        if deleted>=500:
            break
        if not re.fullmatch(r'[0-9a-f]{64}\.fdoc',path.name) or path.resolve().parent!=root:
            continue
        try:
            stamp=path.stat()
            if stamp.st_mtime<cutoff:
                path.unlink();deleted+=1;deleted_bytes+=stamp.st_size
        except OSError:
            continue
    if deleted:
        logger.info('Finance settings cache cleanup: deleted_fragments=%s deleted_bytes=%s',deleted,deleted_bytes)
    return deleted
