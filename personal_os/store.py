"""Atomic, revisioned text records. No network or Git writes."""

import copy
import fcntl
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class Invalid(ValueError):
    """A request cannot be applied without clarification or a fresh read."""


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise Invalid(message)


def nonempty(value, field):
    require(isinstance(value, str) and bool(value.strip()), field + " must be nonempty text")
    return value


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp = tempfile.mkstemp(prefix=".pending-", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def encode(record, markdown=False):
    value = copy.deepcopy(record)
    if markdown:
        # The current supplied words are the Markdown body, never reflowed.
        body = value["data"].pop("text")
        return "---\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n---\n" + body
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def decode(path):
    with path.open(encoding="utf-8", newline="") as input_file:
        text = input_file.read()
    if path.suffix == ".md":
        require(text.startswith("---\n"), "Invalid Markdown metadata: " + str(path))
        metadata, separator, body = text[4:].partition("\n---\n")
        require(bool(separator), "Missing Markdown metadata boundary")
        value = json.loads(metadata)
        value["data"]["text"] = body
        return value
    return json.loads(text)


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.personal = self.root / "personal"

    def safe(self, path):
        resolved = path.resolve()
        require(self.root in resolved.parents, "Storage path leaves the project")
        # Do not silently follow user-created aliases to canonical records.
        require(not any(p.is_symlink() for p in [path] + list(path.parents) if p != self.root),
                "Symlinked storage paths are not supported")
        return path

    @contextmanager
    def lock(self):
        lock = self.safe(self.root / ".local" / "write.lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def records(self):
        if getattr(self, "_read_records", None) is not None:
            return self._read_records
        result = []
        for folder in ("records", "diary", "reflections"):
            for path in sorted((self.personal / folder).rglob("*")):
                if path.suffix not in (".json", ".md") or not path.is_file():
                    continue
                value = decode(self.safe(path))
                require(value.get("schema_version") == 1, "Unsupported record schema: " + str(path))
                value["_path"] = str(path.relative_to(self.root))
                result.append(value)
        ids = [r["id"] for r in result]
        require(len(ids) == len(set(ids)), "Duplicate canonical record IDs")
        return result

    @contextmanager
    def read_snapshot(self):
        """Reuse one validated read during a read-only projection, never across calls."""
        previous = getattr(self, "_read_records", None)
        if previous is None:
            self._read_records = self.records()
        try:
            yield
        finally:
            self._read_records = previous

    def get(self, record_id):
        require(isinstance(record_id, str) and re.fullmatch(r"[a-z0-9_-]+", record_id), "Invalid record ID")
        for record in self.records():
            if record["id"] == record_id:
                return record
        raise Invalid("Record does not exist: " + record_id)

    def config(self):
        path = self.safe(self.personal / "config.json")
        require(path.exists(), "Initialize the project first")
        return json.loads(path.read_text())

    def replay(self, request_id, digest):
        nonempty(request_id, "request_id")
        for record in self.records():
            for request in record["requests"]:
                if request["id"] == request_id:
                    require(request["digest"] == digest, "request_id was already used for different input")
                    # A retry acknowledges the original write, even after later edits.
                    return {"ok": True, "id": record["id"], "revision": request["revision"],
                            "current_revision": record["revision"], "replayed": True}
        return None

    def save(self, kind, data, source, request_id, digest, existing=None, expected=None):
        nonempty(source.get("reference"), "source.reference")
        require(source.get("kind") in ("user_report", "user_instruction", "agent_generated", "calendar", "synthetic"),
                "Invalid source kind")
        stamp = now()
        if existing:
            require(type(expected) is int and expected == existing["revision"],
                    "Stale revision; reload and display the current record before accepting changes")
            record = copy.deepcopy(existing)
            path = self.safe(self.root / record.pop("_path"))
            snapshot = {k: record[k] for k in ("revision", "updated_at", "source", "data")}
            record["history"].append(snapshot)
            record["revision"] += 1
            record.update(data=data, source=source, updated_at=stamp)
        else:
            record_id = kind + "_" + fingerprint(request_id)[:20]
            record = {"schema_version": 1, "id": record_id, "kind": kind, "revision": 1,
                      "created_at": stamp, "updated_at": stamp, "source": source,
                      "data": data, "history": [], "requests": []}
            if kind in ("diary", "summary"):
                date = data["event_date"]
                path = self.personal / "diary" / date[:4] / date[5:7] / date / (record_id + ".md")
            elif kind == "reflection":
                path = self.personal / "reflections" / (data["start"] + "_" + record_id + ".md")
            else:
                path = self.personal / "records" / (record_id + ".json")
            self.safe(path)
            require(not path.exists(), "Record ID collision")
        record["requests"].append({"id": request_id, "digest": digest, "revision": record["revision"]})
        atomic_write(path, encode(record, path.suffix == ".md"))
        require(decode(path) == record, "Write verification failed; reload before retrying")
        record["_path"] = str(path.relative_to(self.root))
        return record
