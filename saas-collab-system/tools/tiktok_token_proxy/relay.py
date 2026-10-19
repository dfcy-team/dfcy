"""Loopback CONNECT relay to a private SSH Unix socket; TLS remains end-to-end."""
import os
from pathlib import Path
import select
import socket
import socketserver
import stat
import threading
import time

AUTHORITY = b"auth.tiktok-shops.com:443"
MAX_HEADER = 8192
HEADER_TIMEOUT = 5


def validate_connect(header):
    if len(header) > MAX_HEADER or not header.endswith(b"\r\n\r\n"):
        return False
    lines = header[:-4].split(b"\r\n")
    if lines[0] not in {b"CONNECT " + AUTHORITY + b" HTTP/1.0", b"CONNECT " + AUTHORITY + b" HTTP/1.1"}:
        return False
    seen = set()
    if len(lines) > 20:
        return False
    for line in lines[1:]:
        name, separator, value = line.partition(b":")
        name, value = name.lower(), value.strip()
        if (not separator or name in seen or name not in {b"host", b"user-agent", b"proxy-connection", b"accept"}
                or len(value) > 1024 or any(byte < 32 or byte == 127 for byte in value)):
            return False
        if name == b"host" and value != AUTHORITY:
            return False
        seen.add(name)
    return True


def validated_socket(filename):
    path = Path(filename)
    info, parent = path.lstat(), path.parent.lstat()
    if (not stat.S_ISSOCK(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid() or not stat.S_ISDIR(parent.st_mode)
            or stat.S_IMODE(parent.st_mode) != 0o700 or parent.st_uid != os.geteuid()):
        raise OSError("Private forwarding socket unavailable")
    return str(path)


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self._connect()

    def _connect(self):
        deadline = time.monotonic() + HEADER_TIMEOUT
        header = b""
        try:
            while b"\r\n\r\n" not in header and len(header) <= MAX_HEADER:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                self.request.settimeout(remaining)
                chunk = self.request.recv(min(1024, MAX_HEADER + 1 - len(header)))
                if not chunk:
                    return
                header += chunk
            # Reject pipelined bytes; the TLS client must wait for CONNECT success.
            if not validate_connect(header):
                self.request.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                return
            filename = validated_socket(self.server.unix_socket)
            self.request.settimeout(5)
            upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            upstream.settimeout(5)
            try:
                upstream.connect(filename)
            except OSError:
                upstream.close()
                self.request.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
                return
        except OSError:
            return
        with upstream:
            try:
                upstream.sendall(b"CONNECT " + AUTHORITY + b" HTTP/1.1\r\nHost: " + AUTHORITY + b"\r\n\r\n")
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    readable, _, _ = select.select([self.request, upstream], [], [], 20)
                    if not readable:
                        return
                    for source in readable:
                        data = source.recv(16384)
                        if not data:
                            return
                        (upstream if source is self.request else self.request).sendall(data)
            except OSError:
                return


class RelayServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, address, unix_socket):
        self.unix_socket = unix_socket
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, Handler)

    def handle_error(self, *_args):
        # Never log request headers or opaque TLS data.
        pass

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


if __name__ == "__main__":
    with RelayServer(("127.0.0.1", 17898), "/proxy/forward.sock") as server:
        print("TK token proxy listening on loopback", flush=True)
        server.serve_forever()
