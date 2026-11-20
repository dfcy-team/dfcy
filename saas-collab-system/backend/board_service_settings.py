"""Isolated realtime board reader/refresh service settings."""
import copy
import importlib
import os
_base = importlib.import_module(os.getenv('BOARD_BASE_SETTINGS_MODULE', 'config.settings.prod'))
for _name in dir(_base):
    if _name.isupper():
        globals()[_name] = getattr(_base, _name)
DATABASES = copy.deepcopy(DATABASES)
for _database in DATABASES.values():
    _database['CONN_MAX_AGE'] = 0
CELERY_BROKER_CONNECTION_TIMEOUT = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_TRANSPORT_OPTIONS = {**globals().get('CELERY_BROKER_TRANSPORT_OPTIONS', {}),
    'socket_connect_timeout': 1, 'socket_timeout': 1, 'retry_on_timeout': False}
CELERY_TASK_PUBLISH_RETRY = False
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
