"""Private shard integrity and bounded generation, synthetic files only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from collections import OrderedDict
import hashlib
import multiprocessing
from pathlib import Path
from threading import Event
from unittest.mock import Mock
import pytest
from apps.finance import summary_documents as docs


@pytest.fixture
def context(db,settings,tmp_path,monkeypatch):
    # Keep spawned lock-test children independent of Django model setup.
    from tests.test_finance_summary import context as summary_context
    return summary_context.__wrapped__(db,settings,tmp_path,monkeypatch)


def child_lock(source, attempted, entered):
    attempted.set()
    with docs.document_generation_lock(source):
        entered.set()


def test_private_fragment_integrity_and_version_keys(tmp_path):
    source=tmp_path/'accepted.gz';source.write_bytes(b'synthetic')
    key=(str(source),'a'*64,(1,2),((1,2),),True,1)
    body=b'compressed-immutable-template'
    docs.save_fragment(key,body)
    assert docs.load_fragment(key)==body
    other=(*key[:-1],2)
    assert docs.load_fragment(other) is None
    docs.fragment_path(other).write_bytes(docs.fragment_path(key).read_bytes())
    assert docs.load_fragment(other) is None
    docs.fragment_path(other).unlink()
    changed=(key[0],key[1],key[2],((2,2),),key[4],key[5])
    assert docs.load_fragment(changed) is None
    docs.fragment_path(key).write_bytes(b'corrupt')
    assert docs.load_fragment(key) is None
    docs.save_fragment(key,body)
    assert docs.load_fragment(key)==body
    original=source.read_bytes()
    assert docs.prune_settings_fragments(docs.fragment_path(key).parent,float('inf'))==1
    assert source.read_bytes()==original


def test_fragment_reused_after_memory_cache_is_cleared(tmp_path,monkeypatch):
    from apps.finance import summary_views as views
    source=tmp_path/'accepted.gz';source.write_bytes(b'synthetic')
    monkeypatch.setattr(views,'_document_cache',OrderedDict())
    monkeypatch.setattr(views,'_document_cache_bytes',0)
    build=Mock(return_value=b'valid-gzip-body')
    monkeypatch.setattr(views,'build_prepared_document',build)
    args=(str(source),'a'*64,(1,2),((1,2),),True,1)
    assert views.prepared_document(*args)==b'valid-gzip-body'
    views._document_cache.clear();views._document_cache_bytes=0
    assert views.prepared_document(*args)==b'valid-gzip-body'
    assert build.call_count==1


def test_distinct_documents_do_not_generate_simultaneously(monkeypatch):
    from apps.finance import summary_views as views
    entered,second_attempt,release=Event(),Event(),Event()
    original=docs.document_generation_lock;attempts=[]
    @contextmanager
    def lock(source):
        attempts.append(source)
        if len(attempts)==2:second_attempt.set()
        with original(source):yield
    calls=[]
    def build(*args):
        calls.append(args)
        if len(calls)==1:
            entered.set();assert release.wait(10)
        return b'body'
    monkeypatch.setattr(views,'_document_cache',OrderedDict());monkeypatch.setattr(views,'_document_cache_bytes',0)
    monkeypatch.setattr(views,'build_prepared_document',build);monkeypatch.setattr(docs,'document_generation_lock',lock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(views.prepared_document,'synthetic-missing-one','hash',(1,),(),True,1)
        try:
            assert entered.wait(10)
            second=pool.submit(views.prepared_document,'synthetic-missing-two','hash',(1,),(),True,2)
            assert second_attempt.wait(10)
            assert len(calls)==1
        finally:release.set()
        assert first.result(timeout=10)==second.result(timeout=10)==b'body'


def test_generation_lock_is_shared_across_processes(tmp_path):
    source=tmp_path/'source.gz';source.write_bytes(b'synthetic')
    ctx=multiprocessing.get_context('spawn');attempted=ctx.Event();entered=ctx.Event()
    process=ctx.Process(target=child_lock,args=(str(source),attempted,entered))
    try:
        with docs.document_generation_lock(str(source)):
            process.start();assert attempted.wait(15)
            assert not entered.wait(0.3)
        assert entered.wait(15)
        process.join(15);assert process.exitcode==0
    finally:
        if process.is_alive():process.terminate();process.join()


def test_warmup_yields_after_one_store_and_stops_obsolete_batch(context,monkeypatch):
    _,_,dataset,_=context
    dataset.metadata.update(database_scope={'stores':[1,2]},store_ids=[1,2])
    dataset.save()
    build=Mock(return_value=b'prepared');publish=Mock()
    monkeypatch.setattr('apps.finance.summary_views.prepared_document',build)
    monkeypatch.setattr(docs.warm_settings_documents,'apply_async',publish)
    assert docs.warm_settings_documents(dataset.pk)['prepared']==1
    assert build.call_count==1 and build.call_args.args[-1]==1
    assert publish.call_args.kwargs['args']==[dataset.pk,1]
    publish.reset_mock()
    assert docs.warm_settings_documents(dataset.pk,1)['prepared']==1
    assert build.call_args.args[-1]==2 and not publish.called
    def obsolete(*args):
        type(dataset).objects.filter(pk=dataset.pk).update(active=False)
        return b'prepared'
    build.side_effect=obsolete
    assert docs.warm_settings_documents(dataset.pk)['prepared']==1
    assert not publish.called
    build.reset_mock()
    assert docs.warm_settings_documents(dataset.pk,1)['prepared']==0
    assert not build.called
