"""Local personal dashboard; focus writes use the revisioned CLI."""

import json
import secrets
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from .engine import Engine
from .workspace import snapshot


def make_server(root, port=8770, allow_setup=False):
    if Path(root).is_symlink():
        raise ValueError("Выбери каталог данных без символической ссылки")
    root = Path(root).resolve()
    engine = Engine(root)
    config_path = engine.store.safe(engine.store.personal / "config.json")
    if config_path.exists():
        engine.store.config()
    elif not allow_setup:
        engine.store.config()
    elif root.exists() and any(root.iterdir()):
        raise ValueError("Для первого запуска выбери новый пустой каталог данных")
    web = Path(__file__).resolve().parent.parent / "web"
    token = secrets.token_urlsafe(32)

    def state():
        if not config_path.exists():
            return {"needs_setup": True, "token": token}
        return {**snapshot(engine), "needs_setup": False, "token": token}

    class Handler(BaseHTTPRequestHandler):
        def send(self, code, body, mime="application/json"):
            body = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            for key, value in {"Content-Type": mime + "; charset=utf-8", "Content-Length": str(len(body)),
                               "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                               "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"}.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def local_host(self):
            return self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

        def do_GET(self):
            if not self.local_host():
                return self.send(403, {"error": "Открой рабочее пространство на localhost."})
            if self.path == "/api/workspace":
                return self.send(200, state())
            route = urlsplit(self.path)
            if route.path == "/api/health":
                return self.send(200, {"ok": True, "service": "personal-os-workspace"})
            if route.path == "/api/agent-status":
                from .agent_status import read_status
                return self.send(200, read_status(root))
            if route.path == "/api/board":
                try:
                    board = engine.store.get(parse_qs(route.query).get("board", [None])[0])
                    if board["kind"] != "planner":
                        raise ValueError("Choose a planner")
                    return self.send(200, {"record": engine.public(board), "token": token, "workspace_url": "/"})
                except (ValueError, KeyError, TypeError, OSError) as error:
                    return self.send(400, {"error": str(error)})
            assets = {"/i18n.js": ("i18n.js", "text/javascript"),
                      "/i18n-catalog.js": ("i18n-catalog.js", "text/javascript"),
                      "/": ("workspace.html", "text/html"), "/workspace.js": ("workspace.js", "text/javascript"),
                      "/workspace.css": ("workspace.css", "text/css"),
                      "/workspace-refresh.js": ("workspace-refresh.js", "text/javascript"),
                      "/today.js": ("today.js", "text/javascript"),
                      "/work-items.js": ("work-items.js", "text/javascript"),
                      "/onboarding.js": ("onboarding.js", "text/javascript"),
                      "/today-model.js": ("today-model.js", "text/javascript"),
                      "/planner": ("planner.html", "text/html"), "/planner.js": ("planner.js", "text/javascript"),
                      "/planner.css": ("planner.css", "text/css"), "/planner-model.js": ("planner-model.js", "text/javascript")}
            if route.path in assets:
                name, mime = assets[route.path]
                return self.send(200, (web / name).read_bytes(), mime)
            self.send(404, {"error": "Страница не найдена"})

        def do_POST(self):
            route = urlsplit(self.path)
            is_planner = route.path == "/api/board"
            operations = {"/api/focus": "focus", "/api/board": "planner", "/api/day-choice": "choose-day",
                          "/api/task-control": "task-control", "/api/link-card": "link-planner-cards",
                          "/api/workspace-item": "workspace-item", "/api/setup": "init",
                          "/api/create-workstream": "create-workstream", "/api/create-task": "create-task"}
            if (not self.local_host() or self.headers.get("Origin") != "http://" + self.headers.get("Host", "")
                    or not secrets.compare_digest(self.headers.get("X-Planner-Token" if is_planner else "X-Workspace-Token", ""), token)):
                return self.send(403, {"error": "Обнови страницу перед сохранением."})
            if route.path not in operations:
                return self.send(404, {"error": "Неизвестное действие"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= (262144 if is_planner else 32768) or self.headers.get("Content-Type") != "application/json":
                    return self.send(400, {"error": "Неверный формат записи"})
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict) or not isinstance(data.get("data"), dict):
                    raise ValueError("Неверный формат записи")
                payload = {"request_id": data["request_id"], "source": {"kind": "user_report", "reference": "Explicit choice or session outcome entered in the personal workspace UI."}, "data": data["data"]}
                if route.path == "/api/setup":
                    if not allow_setup:
                        raise ValueError("Настройка недоступна для этого сервера")
                    payload = {"display_name": data["data"].get("display_name"),
                               "timezone": data["data"].get("timezone"), "synthetic": False}
                elif is_planner:
                    board_id = parse_qs(route.query).get("board", [None])[0]
                    if engine.store.get(board_id)["kind"] != "planner":
                        raise ValueError("Choose a planner")
                    payload.update(id=board_id, expected_revision=data["expected_revision"])
                    payload["source"] = {"kind": "user_instruction", "reference": "Explicit manual planner UI edit; no calendar authorization."}
                elif data.get("id"):
                    payload.update(id=data["id"], expected_revision=data["expected_revision"])
                elif route.path == "/api/day-choice":
                    payload["expected_revision"] = data["expected_revision"]
                if route.path in ("/api/day-choice", "/api/task-control", "/api/link-card", "/api/workspace-item"):
                    payload["source"] = {"kind": "user_instruction", "reference": "Explicit choice, correction or link entered in the personal workspace UI. Local only; no calendar authorization."}
                proc = subprocess.run([sys.executable, str(web.parent / "scripts/personal_os.py"), "--root", str(root), operations[route.path]],
                                      input=json.dumps(payload), text=True, capture_output=True, timeout=45)
                if proc.returncode:
                    detail = json.loads(proc.stderr)
                    code = 409 if any(s in detail.get("error", "").lower() for s in ("revision", "already active", "already closed")) else 400
                    if detail.get("retryable"):
                        code = 503
                    return self.send(code, detail)
                result = json.loads(proc.stdout)
                self.send(200, {"record": engine.public(engine.store.get(board_id))} if is_planner else
                          {**state(), "created_id": result.get("created_task_id") or result.get("id")})
            except subprocess.TimeoutExpired:
                self.send(503, {"error": "Статус сохранения неизвестен. Повтори ту же запись."})
            except (ValueError, KeyError, TypeError, OSError) as error:
                self.send(400, {"error": str(error)})

        def log_message(self, *_):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
