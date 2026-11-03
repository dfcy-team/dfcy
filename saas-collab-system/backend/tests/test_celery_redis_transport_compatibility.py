"""Catch runtime transport incompatibilities that pip check alone can miss."""

from types import SimpleNamespace

from kombu.transport.redis import Channel
from redis import Redis


def test_redis_transport_accepts_installed_client():
    # Resolve the real Kombu client factory without connecting to a broker.
    # Kombu 5.7 / redis-py 5.3 raises VersionMismatch here during worker startup.
    client_class = Channel._get_client(SimpleNamespace(global_keyprefix=""))
    assert issubclass(client_class, Redis)
