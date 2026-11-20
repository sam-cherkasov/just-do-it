"""Explicit project sources, observed checks, reconciliation, and task state."""

import copy
import hashlib
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import calendar
from .store import Invalid, nonempty, now, require


KINDS = ("source", "source_check", "source_review", "task")
TASK_STATES = ("candidate", "ready", "doing", "waiting", "done", "dropped")
MAX_SOURCE_BYTES = 512 * 1024


def stamp(value):
    nonempty(value, "checked_at")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, "Check timestamps require a timezone")
    require(parsed <= datetime.now(timezone.utc), "A source check cannot be dated in the future")
    return parsed


def latest(records, kind, source_id):
    candidates = [r for r in records if r["kind"] == kind
                  and r["data"].get("source_id") == source_id]
    return max(candidates, key=lambda r: (r["created_at"], r["id"]), default=None)


def register(engine, payload):
    require(payload["source"]["kind"] in ("user_instruction", "user_report", "synthetic"),
            "Source registration requires user authorization")
    existing = engine.existing(payload, "source") if payload.get("id") else None
    data = copy.deepcopy(payload["data"])
    nonempty(data.get("title"), "source.title")
    require(data.get("source_type") in ("file", "chat"), "Source type must be file or chat")
    nonempty(data.get("locator"), "source.locator")
    nonempty(data.get("scope"), "source.scope")
    if data["source_type"] == "file":
        require(Path(data["locator"]).is_absolute(), "File sources require an absolute path")
    else:
        require(re.fullmatch(r"[a-zA-Z0-9_-]+", data["locator"]), "Chat locator must be a thread ID")
    data.setdefault("status", "active")
    require(data["status"] in ("active", "paused"), "Invalid source status")
    data.setdefault("max_age_hours", 24)
    require(type(data["max_age_hours"]) is int and 1 <= data["max_age_hours"] <= 720,
            "Source freshness must be 1–720 hours")
    for other in engine.store.records():
        if other["kind"] == "source" and (not existing or other["id"] != existing["id"]):
            require((other["data"]["source_type"], other["data"]["locator"]) !=
                    (data["source_type"], data["locator"]), "This source is already registered")
    return "source", data, existing, {}


def check(engine, payload):
    source_id = payload["data"]["source_id"]
    source = engine.store.get(source_id)
    require(source["kind"] == "source", "Check requires a registered source")
    require(source["data"]["status"] == "active", "Source is paused")
    require(payload["data"].get("source_revision") == source["revision"], "Source registration changed; reload")
    data = {"source_id": source_id, "source_revision": source["revision"], "checked_at": now()}
    extra = {}
    if source["data"]["source_type"] == "file":
        require(not any(k in payload["data"] for k in ("fingerprint", "status", "checked_at")),
                "Local checks must read the file, not accept a supplied result")
        path = Path(source["data"]["locator"])
        try:
            require(not any(p.is_symlink() for p in (path, *path.parents)), "Source symlinks are not followed")
            require(path.is_file(), "Registered source is not a readable regular file")
            with path.open("rb") as handle:
                raw = handle.read(MAX_SOURCE_BYTES + 1)
            require(len(raw) <= MAX_SOURCE_BYTES, "Source exceeds 512 KiB; register a smaller current-state file")
            content = raw.decode("utf-8")
            data.update(status="ok", fingerprint=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
            extra["content"] = content
        except (OSError, UnicodeError, Invalid) as error:
            data.update(status="unavailable", error=str(error))
    else:
        observed = payload["data"]
        require(observed.get("status") in ("ok", "unavailable"), "Chat checks require a connector result")
        stamp(observed.get("checked_at"))
        data.update(status=observed["status"], checked_at=observed["checked_at"])
        if data["status"] == "ok":
            nonempty(observed.get("observed_revision"), "observed_revision")
            require(isinstance(observed.get("fingerprint"), str)
                    and re.fullmatch(r"[0-9a-f]{64}", observed["fingerprint"]), "Chat check requires a SHA-256 digest")
            nonempty(observed.get("coverage"), "Chat check coverage")
            data.update(fingerprint=observed["fingerprint"], observed_revision=observed["observed_revision"],
                        coverage=observed["coverage"])
        else:
            data["error"] = nonempty(observed.get("error"), "error")
    return "source_check", data, None, extra


def review(engine, payload):
    data = copy.deepcopy(payload["data"])
    check_record = engine.store.get(data["check_id"])
    require(check_record["kind"] == "source_check" and check_record["data"]["status"] == "ok",
            "Reconciliation requires a successful source check")
    source_id = check_record["data"]["source_id"]
    source = engine.store.get(source_id)
    current = latest(engine.store.records(), "source_check", source_id)
    require(current["data"]["status"] == "ok" and
            current["data"].get("fingerprint") == check_record["data"]["fingerprint"] and
            source["revision"] == check_record["data"]["source_revision"],
            "Source changed or became unavailable after the reviewed check")
    nonempty(data.get("summary"), "review.summary")
    require(data.get("outcome") in ("reconciled", "no_relevant_change"), "Invalid reconciliation outcome")
    refs = engine.source_refs(data.get("records", []))
    require(data["outcome"] != "reconciled" or refs, "Reconciliation must reference saved output records")
    require(all(engine.store.get(ref["id"])["kind"] in ("memory", "node", "task", "workstream") for ref in refs),
            "Reconciliation outputs must be saved memory, map nodes, tasks, or workstreams")
    data.update(source_id=source_id, source_revision=source["revision"],
                fingerprint=check_record["data"]["fingerprint"], records=refs)
    return "source_review", data, None, {}


def task(engine, payload, preserve_sources=False, allow_control=False):
    existing = engine.existing(payload, "task") if payload.get("id") else None
    data = copy.deepcopy(payload["data"])
    from .links import normalize_chat
    from .today import preserve_control, CONTROL_FIELDS
    retained = preserve_control(existing, data, allow_control)
    controlled = data.get("user_control", {}).get("fields", [])
    require(isinstance(controlled, list) and set(controlled) <= set(CONTROL_FIELDS), "Invalid controlled task fields")
    normalize_chat(data)
    nonempty(data.get("title"), "task.title")
    require(data.get("status") in TASK_STATES, "Invalid task state")
    require(data.get("intent") in ("proposed", "reported"), "Task intent must be proposed or reported")
    require(data.get("priority", "unranked") in ("primary", "supporting", "unranked"), "Invalid priority")
    data.setdefault("priority", "unranked")
    parents = data.get("parents", [])
    require(isinstance(parents, list) and len(parents) == len(set(parents)), "Task parents must be unique")
    require(parents and all(engine.store.get(p)["kind"] == "node" for p in parents),
            "Link every task to at least one area, goal, or strategy")
    nonempty(data.get("rationale"), "task.rationale")
    if preserve_sources:
        # A direct correction is new user evidence; it does not reinterpret old sources.
        refs = data.get("sources", [])
        require(existing and refs == existing["data"].get("sources", []), "Keep historical source references unchanged")
        for ref in refs:
            require(0 < ref["revision"] <= engine.store.get(ref["id"])["revision"], "Invalid historical source revision")
    else:
        refs = engine.source_refs(data.get("sources", []))
    if data["intent"] == "reported":
        require(payload["source"]["kind"] in ("user_report", "user_instruction", "synthetic") or refs or
                (existing and {"status", "intent"} <= set(controlled) and
                 (data["status"], data["intent"]) == (existing["data"]["status"], existing["data"]["intent"])),
                "Reported task state requires a user report or saved evidence")
    else:
        require(data["status"] in ("candidate", "ready"), "A proposed task cannot claim execution or completion")
    if data["status"] == "waiting":
        nonempty(data.get("waiting_on"), "task.waiting_on")
    elif data["status"] in ("candidate", "ready", "doing"):
        nonempty(data.get("next_action"), "task.next_action")
    elif data["status"] == "done":
        nonempty(data.get("completion_evidence"), "task.completion_evidence")
    if data.get("attention_date"):
        calendar.day(data["attention_date"])
        nonempty(data.get("date_basis"), "task.date_basis")
    if existing and (data["status"], data["intent"]) != (existing["data"]["status"], existing["data"]["intent"]):
        nonempty(payload.get("reason"), "State changes require a reason")
    return "task", data, existing, {"protected_fields_retained": retained}


def stale_reference(engine, record):
    for ref in record["data"].get("sources", []):
        source = engine.store.get(ref["id"])
        if source["kind"] == "source_check":
            registry = engine.store.get(source["data"]["source_id"])
            if registry["revision"] != source["data"]["source_revision"]:
                return True
            current = latest(engine.store.records(), "source_check", source["data"]["source_id"])
            if current and current["data"]["status"] == "ok" and current["data"].get("fingerprint") != source["data"].get("fingerprint"):
                return True
    return False


def summary(records):
    result = []
    for source in [r for r in records if r["kind"] == "source"]:
        check_record = latest(records, "source_check", source["id"])
        reviewed = latest(records, "source_review", source["id"])
        successful = [r for r in records if r["kind"] == "source_check"
                      and r["data"]["source_id"] == source["id"] and r["data"]["status"] == "ok"]
        success = max(successful, key=lambda r: r["created_at"], default=None)
        state = "not_checked"
        if check_record:
            state = "unavailable" if check_record["data"]["status"] != "ok" else "needs_review"
            if state != "unavailable" and reviewed and reviewed["data"]["fingerprint"] == check_record["data"]["fingerprint"] and reviewed["data"]["source_revision"] == source["revision"]:
                state = "reviewed"
            if check_record["data"]["source_revision"] != source["revision"]:
                state = "not_checked"
        if source["data"]["status"] == "paused":
            state = "paused"
        expired = bool(check_record and (datetime.now(timezone.utc) - stamp(check_record["data"]["checked_at"])).total_seconds()
                       > source["data"]["max_age_hours"] * 3600)
        result.append({"id": source["id"], "title": source["data"]["title"], "state": state,
                       "expired": expired, "checked_at": check_record["data"]["checked_at"] if check_record else None,
                       "last_success_at": success["data"]["checked_at"] if success else None,
                       "check_id": check_record["id"] if check_record else None,
                       "review_id": reviewed["id"] if reviewed else None,
                       "error": check_record["data"].get("error") if check_record else None})
    return result


def context_records(records):
    selected = [r for r in records if r["kind"] == "source" or
                (r["kind"] == "task" and r["data"]["status"] not in ("done", "dropped"))]
    for source in [r for r in records if r["kind"] == "source"]:
        for kind in ("source_check", "source_review"):
            item = latest(records, kind, source["id"])
            if item:
                selected.append(item)
    return selected


def refresh(engine):
    """Read only registered local files; chat retrieval stays with connected tools."""
    results, pending = [], []
    batch = uuid.uuid4().hex
    for source in engine.store.records():
        if source["kind"] != "source" or source["data"]["status"] != "active":
            continue
        if source["data"]["source_type"] == "chat":
            pending.append({"id": source["id"], "revision": source["revision"], **source["data"]})
            continue
        receipt = engine.run("check-source", {"request_id": batch + "-" + source["id"],
                             "source": {"kind": "agent_generated", "reference": "Read registered local source"},
                             "data": {"source_id": source["id"], "source_revision": source["revision"]}})
        item = {"id": source["id"], "check_id": receipt["id"], "title": source["data"]["title"],
                "status": receipt["record"]["data"]["status"]}
        health = next(x for x in summary(engine.store.records()) if x["id"] == source["id"])
        item["state"] = health["state"]
        if health["state"] == "needs_review":
            item["content"] = receipt.get("content", "")
        if health["error"]:
            item["error"] = health["error"]
        results.append(item)
    return {"ok": all(x["status"] == "ok" for x in results), "checks": results,
            "chat_reads_required": pending,
            "notice": "A successful read is not reconciliation. Read pending chats with connected tools; save supported facts/tasks, then review-source. No calendar changes."}
