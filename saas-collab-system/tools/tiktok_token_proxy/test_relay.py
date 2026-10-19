"""Local fake CONNECT tests, no platform or live proxy traffic."""
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch
import time

from relay import RelayServer, validate_connect, validated_socket

VALID = b"CONNECT auth.tiktok-shops.com:443 HTTP/1.1\r\nHost: auth.tiktok-shops.com:443\r\n\r\n"


class HeaderTests(unittest.TestCase):
    def test_expected_target(self):
        self.assertTrue(validate_connect(VALID))
        self.assertTrue(validate_connect(VALID.replace(b"HTTP/1.1", b"HTTP/1.0")))

    def test_other_targets_and_extra_bytes_are_rejected(self):
        for data in (VALID.replace(b"auth.tiktok-shops.com", b"business-api.tiktok.com"),
                     VALID.replace(b":443", b":80"), VALID.replace(b"CONNECT ", b"GET "),
                     VALID.replace(b"CONNECT auth", b"CONNECT https://auth"), VALID + b"GET / HTTP/1.1\r\n\r\n",
                     VALID.replace(b"\r\n\r\n", b"\r\nHost: other.example.test\r\n\r\n"),
                     VALID.replace(b"\r\n\r\n", b"\r\nProxy-Authorization: FAKE\r\n\r\n"), b"x" * 8193):
            with self.subTest(size=len(data)):
                self.assertFalse(validate_connect(data))


@unittest.skipUnless(os.name == 'posix', 'Unix socket permissions require Linux')
class RelayTests(unittest.TestCase):
    def test_header_deadline_closes_slow_clients_and_releases_slots(self):
        with patch('relay.HEADER_TIMEOUT', 0.1), RelayServer(('127.0.0.1',0), '/NONEXISTENT_FAKE_SOCKET') as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            with socket.create_connection(server.server_address, timeout=2) as client:
                client.sendall(b'C')
                time.sleep(0.2)
                self.assertEqual(client.recv(100), b'')
            self.assertEqual(server.slots._value,8)
            server.shutdown()
            thread.join(3)

    def test_unsafe_socket_or_parent_permissions_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory,0o700)
            path=Path(directory)/'forward.sock'
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(str(path))
                os.chmod(path,0o600)
                self.assertEqual(validated_socket(path),str(path))
                os.chmod(path,0o666)
                with self.assertRaises(OSError): validated_socket(path)
                os.chmod(path,0o600)
                os.chmod(directory,0o755)
                with self.assertRaises(OSError): validated_socket(path)
                os.chmod(directory,0o700)

    def test_canonical_connect_and_opaque_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o700)
            filename = Path(directory) / 'forward.sock'
            upstream = socket.socket(socket.AF_UNIX)
            upstream.bind(str(filename))
            os.chmod(filename, 0o600)
            upstream.listen(1)
            received = []
            def fake_proxy():
                with upstream.accept()[0] as connection:
                    received.append(connection.recv(8192))
                    connection.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                    received.append(connection.recv(100))
                    connection.sendall(b'FAKE_OPAQUE_RESPONSE')
            fake = threading.Thread(target=fake_proxy, daemon=True)
            fake.start()
            with RelayServer(('127.0.0.1', 0), str(filename)) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                with socket.create_connection(server.server_address, timeout=3) as client:
                    client.sendall(VALID)
                    self.assertIn(b'200 Connection Established', client.recv(8192))
                    client.sendall(b'FAKE_OPAQUE_TLS')
                    self.assertEqual(client.recv(100), b'FAKE_OPAQUE_RESPONSE')
                server.shutdown()
                thread.join(3)
            fake.join(3)
            upstream.close()
            self.assertEqual(received, [VALID, b'FAKE_OPAQUE_TLS'])


if __name__ == '__main__':
    unittest.main()
