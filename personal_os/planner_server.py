"""Loopback-only planner UI. Mutations go through the canonical CLI."""

import json
import secrets
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .engine import Engine
from .store import Invalid


def make_server(root, record_id, port=8769):
    root = Path(root).resolve()
    engine = Engine(root)
    if engine.store.get(record_id)["kind"] != "planner":
        raise Invalid("Choose a planner record")
    web = Path(__file__).resolve().parent.parent / "web"
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def send(self, code, body, mime="application/json"):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def local_host(self):
            port = self.server.server_port
            return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

        def do_GET(self):
            if not self.local_host():
                return self.send(403, {"error": "Open the planner on localhost."})
            if self.path == "/api/board":
                return self.send(200, {"record": engine.public(engine.store.get(record_id)), "token": token, "workspace_url": "http://127.0.0.1:8770/"})
            assets = {"/i18n.js": ("i18n.js", "text/javascript"),
                      "/i18n-catalog.js": ("i18n-catalog.js", "text/javascript"),
                      "/": ("planner.html", "text/html"), "/planner.js": ("planner.js", "text/javascript"),
                      "/planner.css": ("planner.css", "text/css"), "/planner-model.js": ("planner-model.js", "text/javascript")}
            if urlsplit(self.path).path in assets:
                name, mime = assets[urlsplit(self.path).path]
                return self.send(200, (web / name).read_bytes(), mime)
            self.send(404, {"error": "Page not found"})

        def do_POST(self):
            expected_origin = "http://" + self.headers.get("Host", "")
            if (not self.local_host() or self.headers.get("Origin") != expected_origin
                    or not secrets.compare_digest(self.headers.get("X-Planner-Token", ""), token)):
                return self.send(403, {"error": "Reload this local planner before saving."})
            if self.path != "/api/board":
                return self.send(404, {"error": "Unknown action"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 262144 or self.headers.get("Content-Type") != "application/json":
                    return self.send(400, {"error": "Invalid request size or type"})
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError("Invalid save request")
                payload = {"request_id": data["request_id"], "source": {"kind": "user_instruction", "reference": "User selected, edited or placed cards in the manual planning UI; not external-calendar authorization."},
                           "id": record_id, "expected_revision": data["expected_revision"], "data": data["data"]}
                proc = subprocess.run([sys.executable, str(Path(__file__).resolve().parent.parent / "scripts/personal_os.py"),
                                       "--root", str(root), "planner"], input=json.dumps(payload), text=True,
                                      capture_output=True, timeout=30)
                if proc.returncode:
                    detail = json.loads(proc.stderr)
                    code = 409 if "revision" in detail.get("error", "").lower() else 400
                    return self.send(code, detail)
                # Read back authoritative state even for an idempotent retry.
                self.send(200, {"record": engine.public(engine.store.get(record_id))})
            except subprocess.TimeoutExpired:
                self.send(503, {"error": "Save status is uncertain. Retry the same save before making more changes."})
            except (ValueError, KeyError, TypeError, OSError) as error:
                self.send(400, {"error": str(error)})

        def log_message(self, *_):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
