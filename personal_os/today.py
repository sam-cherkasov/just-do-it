"""Explicit local day choices and task corrections. No calendar or runtime writes."""

import copy
from datetime import datetime
from zoneinfo import ZoneInfo

from . import calendar
from .links import normalize_chat, validate_target
from .store import nonempty, now, require

USER_SOURCES = ("user_report", "user_instruction", "synthetic")
CONTROL_FIELDS = ("title", "next_action", "chat_url", "chat_ref", "status", "intent",
                  "waiting_on", "completion_evidence", "deferred", "deferred_until")


def local_date(timezone):
    return datetime.now(ZoneInfo(timezone)).date().isoformat()


def preserve_control(existing, data, allow_control=False):
    """Only the explicit task-control operation replaces protected values."""
    before = existing["data"] if existing else {}
    control = before.get("user_control", {})
    retained = []
    if not allow_control:
        for field in control.get("fields", []):
            if data.get(field) != before.get(field):
                retained.append(field)
            if field in before:
                data[field] = copy.deepcopy(before[field])
            else:
                data.pop(field, None)
        if control:
            data["user_control"] = copy.deepcopy(control)
        else:
            data.pop("user_control", None)
    elif control and "user_control" not in data:
        data["user_control"] = copy.deepcopy(control)
    return retained


def update_task(engine, payload):
    require(payload["source"]["kind"] in USER_SOURCES, "Task controls need an explicit user action")
    with engine.store.read_snapshot():
        existing = engine.existing(payload, "task")
        incoming, data = payload["data"], copy.deepcopy(existing["data"])
        action = incoming.get("action")
        reason = nonempty(incoming.get("reason"), "Describe the task change")
        require(len(reason) <= 4000, "Reason is too long")
        fields = set(data.get("user_control", {}).get("fields", []))
        if action == "edit":
            values = incoming.get("values")
            require(isinstance(values, dict) and values and set(values) <= {"title", "next_action", "chat_url"}, "Choose editable task fields")
            for key, value in values.items():
                require(isinstance(value, str) and len(value) <= (2000 if key == "title" else 4000), "Task text is too long")
                if key != "chat_url":
                    nonempty(value, key)
                data[key] = value
                fields.add(key)
            if "chat_url" in values:
                data.pop("chat_ref", None)
                normalize_chat(data)
                fields.add("chat_ref")
        else:
            require(action in ("later", "wait", "done", "drop", "restore"), "Unknown task action")
            require(not any(r["kind"] == "focus" and r["data"].get("task_id") == existing["id"] and r["data"]["status"] == "active"
                            for r in engine.store.records()), "A focus session is already active for this task; finish it first")
            if action == "later":
                require(data["status"] not in ("done", "dropped"), "Reopen this task first")
                until = incoming.get("until") or None
                if until:
                    calendar.day(until)
                    require(until >= local_date(engine.config["timezone"]), "Choose today or a future review date")
                data.update(deferred=True, deferred_until=until)
                fields.update(("deferred", "deferred_until"))
            else:
                data.update(status={"wait": "waiting", "done": "done", "drop": "dropped", "restore": "ready"}[action],
                            intent="reported", deferred=False, deferred_until=None)
                data.pop("waiting_on", None)
                data.pop("completion_evidence", None)
                if action == "wait":
                    data["waiting_on"] = reason
                if action == "done":
                    data["completion_evidence"] = reason
                fields.update(("status", "intent", "waiting_on", "completion_evidence", "deferred", "deferred_until"))
        data["user_control"] = {"fields": sorted(fields), "at": now(), "action": action, "reason": reason}
        from .connections import task
        return task(engine, {**payload, "data": data, "reason": reason}, preserve_sources=True, allow_control=True)


def choose_day(engine, payload):
    require(payload["source"]["kind"] in USER_SOURCES, "Day choice needs an explicit user action")
    with engine.store.read_snapshot():
        incoming = payload["data"]
        date = incoming.get("date")
        calendar.day(date)
        require(date == local_date(engine.config["timezone"]), "The local day changed; reload Today before choosing")
        choices = [r for r in engine.store.records() if r["kind"] == "day_choice" and r["data"]["date"] == date]
        require(len(choices) <= 1, "Duplicate day choices; reconcile before saving")
        existing = choices[0] if choices else None
        require(payload.get("expected_revision") == (existing["revision"] if existing else 0), "Day choice revision changed; reload")
        require(payload.get("id") == (existing["id"] if existing else None), "Day choice identity changed; reload")
        if incoming.get("action") == "clear":
            require(existing is not None, "No result has been chosen")
            data = copy.deepcopy(existing["data"])
            data.update(status="cleared", reason=nonempty(incoming.get("reason"), "Why clear the day choice?"))
        else:
            require(incoming.get("action") == "choose", "Choose or clear a day result")
            task = engine.store.get(incoming.get("task_id"))
            require(task["kind"] == "task", "Choose a task")
            require(task["data"]["status"] not in ("done", "dropped", "waiting") and not task["data"].get("deferred"), "Return the task to available work first")
            data = {"date": date, "timezone": engine.config["timezone"], "status": "selected",
                    "task_id": task["id"], "task_revision": incoming.get("task_revision"),
                    "workstream_id": incoming.get("workstream_id"),
                    "target": nonempty(incoming.get("target"), "Choose the result for today"),
                    "first_action": nonempty(incoming.get("first_action"), "Choose the first action"),
                    "reason": nonempty(incoming.get("reason"), "Why choose this result?"),
                    "title": task["data"]["title"], "chat_url": task["data"].get("chat_url", "")}
            if task["data"].get("chat_ref"):
                data["chat_ref"] = copy.deepcopy(task["data"]["chat_ref"])
            validate_target(engine, data)
            if incoming.get("planner_id") or incoming.get("planner_card_id"):
                board = engine.store.get(incoming.get("planner_id"))
                require(board["kind"] == "planner" and incoming.get("planner_revision") == board["revision"], "Planner revision changed; reload")
                card = next((c for c in board["data"]["cards"] if c["id"] == incoming.get("planner_card_id")), None)
                require(card and card.get("task_id") == task["id"] and card.get("workstream_id") == data["workstream_id"] and card["selected"], "Choose a selected card linked to this task")
                data.update(planner_id=board["id"], planner_revision=board["revision"], planner_card_id=card["id"])
                # Keep the reviewed card's chat; frozen first action/result are the form's explicit choice.
                data.pop("chat_ref", None)
                data["chat_url"] = card.get("chat_url", "")
                if card.get("chat_ref"):
                    data["chat_ref"] = copy.deepcopy(card["chat_ref"])
                normalize_chat(data)
            require(len(data["target"]) <= 2000 and len(data["first_action"]) <= 4000 and len(data["reason"]) <= 4000, "Day choice text is too long")
        return "day_choice", data, existing, {}


def history(record):
    """Small UI history, excluding original source bodies and private record metadata."""
    versions = list(record.get("history", [])) + [record]
    keys = ("title", "next_action", "status", "intent", "waiting_on", "completion_evidence", "deferred", "deferred_until", "chat_url", "rationale", "attention_date", "date_basis", "priority")
    result, previous, previous_control = [], {}, None
    for version in versions:
        current = {k: version["data"].get(k) for k in keys}
        changed = {k: {"before": previous.get(k), "after": current[k]} for k in keys if previous.get(k) != current[k]}
        control = version["data"].get("user_control")
        if changed or control != previous_control:
            result.append({"revision": version["revision"], "at": version["updated_at"],
                           "source_kind": version["source"]["kind"], "changes": changed,
                           "reason": version["data"].get("user_control", {}).get("reason", "") if version["source"]["kind"] in USER_SOURCES else ""})
        previous = current
        previous_control = control
    return result[-20:]
