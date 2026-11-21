"""Preserve the hash-pinned cloud board module without importing real settings."""
import hashlib
from pathlib import Path
import runpy
import sys
from types import ModuleType

MODULE=Path(__file__).resolve().parents[1]/'board_service_settings.py'
# Raw cloud B80EE4... has a single CRLF at EOF; the reviewed LF-only source is
# byte-identical after that line-ending normalization, with no logic changes.
NORMALIZED_CLOUD_SHA='a5a145a2ea3c37c37507edd7946d4f17376d7063736e85938a09a66ebe24090b'


def test_board_settings_match_preserved_cloud_source():
    assert hashlib.sha256(MODULE.read_bytes().replace(b'\r\n',b'\n')).hexdigest()==NORMALIZED_CLOUD_SHA


def test_board_isolates_connection_lifetime_and_preserves_base_policy(monkeypatch):
    base=ModuleType('v518_board_synthetic_base')
    base.DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':':memory:','CONN_MAX_AGE':120}}
    base.CELERY_BROKER_TRANSPORT_OPTIONS={'visibility_timeout':600}
    base.CELERY_BEAT_SCHEDULE={'existing-job':{'task':'synthetic.existing','schedule':60}}
    monkeypatch.setitem(sys.modules,base.__name__,base)
    monkeypatch.setenv('BOARD_BASE_SETTINGS_MODULE',base.__name__)
    selected=runpy.run_path(str(MODULE))
    assert selected['DATABASES']['default']['CONN_MAX_AGE']==0
    assert base.DATABASES['default']['CONN_MAX_AGE']==120
    assert selected['CELERY_BROKER_TRANSPORT_OPTIONS']=={
        'visibility_timeout':600,'socket_connect_timeout':1,'socket_timeout':1,'retry_on_timeout':False}
    assert base.CELERY_BROKER_TRANSPORT_OPTIONS=={'visibility_timeout':600}
    assert selected['CELERY_BROKER_CONNECTION_TIMEOUT']==1
    assert selected['CELERY_TASK_PUBLISH_RETRY'] is False
    assert selected['CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP'] is True
    assert selected['CELERY_WORKER_PREFETCH_MULTIPLIER']==1
    assert selected['CELERY_BEAT_SCHEDULE']==base.CELERY_BEAT_SCHEDULE
