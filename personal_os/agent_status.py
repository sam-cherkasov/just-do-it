"""Bounded read-only app-server capability probe, not a background agent runner."""

import copy
import json
import os
import selectors
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .store import atomic_write, now

TTL_SECONDS = 30


def normalize(status):
    """A status is neither a task outcome nor a pending request payload."""
    status = status if isinstance(status, dict) else {}
    kind = status.get("type")
    flags = status.get("activeFlags", []) if kind == "active" else []
    return {"execution": {"active": "active", "idle": "idle", "systemError": "error"}.get(kind, "unknown"),
            "attention": [flag for flag in ("waitingOnApproval", "waitingOnUserInput") if flag in flags],
            "signal": kind if kind in ("active", "idle", "notLoaded", "systemError") else "unknown"}


def project_status(receipt, at=None):
    result = copy.deepcopy(receipt)
    at = at or datetime.now(timezone.utc)
    try:
        age = (at - datetime.fromisoformat(result["observed_at"])).total_seconds()
        fresh = 0 <= age <= TTL_SECONDS
    except (KeyError, ValueError, TypeError):
        fresh = False
    if result.get("state") == "snapshot" and not fresh:
        result["state"] = "stale"
        result["message"] = "Снимок устарел. Текущее исполнение агентов неизвестно."
    if result.get("state") != "snapshot":
        for thread in result.get("threads", []):
            thread.update(execution="unknown", attention=[])
    result["live"] = False
    result["ttl_seconds"] = TTL_SECONDS
    return result


def read_status(root):
    try:
        receipt = json.loads((Path(root) / ".local/agent-status.json").read_text())
        if not isinstance(receipt, dict) or receipt.get("state") not in ("snapshot", "unavailable"):
            raise ValueError("Invalid receipt")
        return project_status(receipt)
    except (OSError, ValueError, TypeError):
        return {"state": "unavailable", "live": False, "threads": [], "observed_at": None,
                "message": "Канал статусов ещё не подтверждён. Сохранённые чаты доступны по ссылкам."}


class ReadOnlyProxy:
    """Only documented reads; never start/resume/interrupt a turn or answer requests."""

    def __init__(self, command, timeout=8):
        self.command, self.timeout = command, timeout

    def __enter__(self):
        self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.buffer, self.seq = b"", 0
        self.deadline = time.monotonic() + self.timeout
        return self

    def __exit__(self, *_):
        self.selector.close()
        self.process.stdin.close()
        if self.process.poll() is None:
            self.process.terminate()  # Only this observer's proxy process.
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=1)
        self.process.stdout.close()

    def send(self, method, params, notification=False):
        if method not in ("initialize", "initialized", "thread/loaded/list", "thread/read"):
            raise ValueError("Read-only observer")
        self.seq += 1
        request = {"method": method, "params": params}
        if not notification:
            request["id"] = self.seq
        self.process.stdin.write((json.dumps(request) + "\n").encode())
        self.process.stdin.flush()
        if notification:
            return None
        while time.monotonic() < self.deadline:
            if b"\n" not in self.buffer:
                ready = self.selector.select(max(0, self.deadline - time.monotonic()))
                if not ready:
                    break
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise ConnectionError("Proxy disconnected")
                self.buffer += chunk
                if len(self.buffer) > 2_000_000:
                    raise ValueError("Response too large")
                continue
            line, self.buffer = self.buffer.split(b"\n", 1)
            response = json.loads(line)
            if response.get("id") == self.seq:
                if "error" in response:
                    raise ConnectionError("Read rejected")
                return response["result"]
        raise TimeoutError("Probe timed out")


def probe(root, refs, socket=None):
    """Scope is this app-server only; successful connection does not prove desktop parity."""
    command = ["codex", "app-server", "proxy"]
    if socket:
        command.extend(["--sock", str(socket)])
    receipt = {"state": "unavailable", "observed_at": now(), "transport": "codex-app-server-proxy",
               "scope": "connected_app_server_only", "desktop_coverage_verified": False,
               "threads": [], "requested": len(refs), "loaded_list_truncated": None,
               "message": "Поддерживаемый канал Codex proxy не подключился. Живые статусы desktop-чатов не подтверждены."}
    try:
        with ReadOnlyProxy(command) as proxy:
            proxy.send("initialize", {"clientInfo": {"name": "personal_os_observer", "version": "0.1"}})
            proxy.send("initialized", {}, notification=True)
            loaded = proxy.send("thread/loaded/list", {"limit": 100})
            receipt["loaded_list_truncated"] = bool(loaded.get("nextCursor"))
            loaded_ids = set(loaded["data"])
            for ref in refs:
                if ref["provider"] != "codex" or ref["host_id"] != "local" or ref["thread_id"] not in loaded_ids:
                    receipt["threads"].append({**ref, **normalize(None), "coverage": "not_observed"})
                    continue
                result = proxy.send("thread/read", {"threadId": ref["thread_id"], "includeTurns": False})
                if result["thread"]["id"] != ref["thread_id"]:
                    raise ValueError("Mismatched thread")
                receipt["threads"].append({**ref, **normalize(result["thread"].get("status")), "coverage": "metadata_read"})
            receipt.update(state="snapshot", observed_at=now(),
                           message="Получен разовый снимок подключённого app-server. Полнота покрытия desktop-чатов не подтверждена; постоянный монитор ещё не подключён.")
    except (OSError, ValueError, KeyError, TypeError, TimeoutError) as error:
        receipt["failure"] = type(error).__name__  # No raw provider output or message bodies.
        receipt["observed_at"] = now()
    result = project_status(receipt)
    atomic_write(Path(root) / ".local/agent-status.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result
