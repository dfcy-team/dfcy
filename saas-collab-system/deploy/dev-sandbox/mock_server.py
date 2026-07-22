import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent


def load_routes():
    routes = {}
    for path in sorted((ROOT / "fixtures").glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        routes.update(document["routes"])
    return routes


ROUTES = load_routes()


class Handler(BaseHTTPRequestHandler):
    server_version = "LocalSandboxMock/1"

    def _write_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = urlsplit(self.path).path
        if route == "/health/":
            self._write_json(200, {"success": True, "code": "OK", "message": "success", "data": {"status": "mock"}})
            return
        response = ROUTES.get(route)
        if response is None:
            self._write_json(404, {"success": False, "code": "NOT_FOUND", "message": "mock route not found", "data": None})
            return
        self._write_json(200, response)

    def do_POST(self):
        self._write_json(405, {"success": False, "code": "MOCK_READ_ONLY", "message": "mock service is read-only", "data": None})

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST

    def log_message(self, format_string, *args):
        print(f"mock_request method={self.command} path={urlsplit(self.path).path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8091)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"LOCAL_SANDBOX_CREATOR_MOCK=READY port={args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
