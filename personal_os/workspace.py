"""Personal workstreams and explicit focus-session reports."""

import copy
import re

from .store import nonempty, now, require
from .links import normalize_chat, projection


def workstream(engine, payload):
    existing = engine.existing(payload, "workstream") if payload.get("id") else None
    data = copy.deepcopy(payload["data"])
    for field in ("title", "summary", "outcome"):
        nonempty(data.get(field), field)
    require(data.get("color") in ("lilac", "mint", "peach", "blue", "rose", "sand", "teal", "slate"), "Choose a workstream color")
    require(data.get("status", "active") in ("active", "paused"), "Invalid workstream status")
    data.setdefault("status", "active")
    for field, kind in (("task_ids", "task"), ("source_ids", "source")):
        ids = data.get(field, [])
        require(isinstance(ids, list) and len(ids) == len(set(ids)), "References must be unique")
        require(all(engine.store.get(id)["kind"] == kind for id in ids), "Wrong linked record kind")
    for question in data.get("questions", []):
        nonempty(question.get("text"), "question")
        require(question.get("task_id") in data.get("task_ids", []), "Question must link to a workstream task")
    for chat in data.get("chats", []):
        nonempty(chat.get("title"), "chat title")
        require(re.fullmatch(r"codex://threads/[a-zA-Z0-9_-]+", chat.get("url", "")), "Invalid chat link")
        nonempty(chat.get("activity_at"), "chat activity date")
        normalized = {"chat_url": chat["url"]}
        if chat.get("chat_ref"):
            normalized["chat_ref"] = chat["chat_ref"]
        chat["chat_ref"] = normalize_chat(normalized)
    engine.source_refs(data.get("sources", []))
    return "workstream", data, existing, {}


def focus(engine, payload):
    with engine.store.read_snapshot():
        return _focus(engine, payload)


def _focus(engine, payload):
    require(payload["source"]["kind"] in ("user_instruction", "user_report", "synthetic"), "Focus needs an explicit user action")
    existing = engine.existing(payload, "focus") if payload.get("id") else None
    incoming = payload["data"]
    if existing:
        require(existing["data"]["status"] == "active", "This session is already closed")
        require(incoming.get("status") == "closed", "Finish the current session before starting another")
        require(incoming.get("outcome") in ("result", "progress", "blocked", "cancelled"), "Choose a session outcome")
        note = nonempty(incoming.get("note"), "Describe the result or reason for stopping")
        require(len(note) <= 12000 and len(incoming.get("next_action", "")) <= 4000, "Session note is too long")
        data = copy.deepcopy(existing["data"])
        data.update(status="closed", ended_at=now(), outcome=incoming["outcome"], note=note,
                    next_action=incoming.get("next_action", ""))
    else:
        require(not any(r["kind"] == "focus" and r["data"]["status"] == "active" for r in engine.store.records()), "A focus session is already active; reload")
        stream = engine.store.get(incoming["workstream_id"]) if incoming.get("workstream_id") else None
        require(not stream or stream["kind"] == "workstream", "Choose a workstream")
        task = engine.store.get(incoming["task_id"])
        require(task["kind"] == "task" and (not stream or task["id"] in stream["data"]["task_ids"]), "Choose a task from this workstream")
        require(task["data"]["status"] not in ("done", "dropped", "waiting") and not task["data"].get("deferred"), "Return the task to available work first")
        require(incoming.get("task_revision") == task["revision"], "Task revision changed; reload")
        minutes = incoming.get("minutes")
        require(type(minutes) is int and 15 <= minutes <= 180 and minutes % 15 == 0, "Choose a 15–180 minute session budget")
        planning = {}
        start_data = task["data"]
        if incoming.get("continuation_id"):
            require(not any(incoming.get(k) for k in ("day_choice_id", "planner_id", "planner_card_id")),
                    "Choose one starting context")
            previous = engine.store.get(incoming["continuation_id"])
            require(previous["kind"] == "focus" and previous["data"]["status"] == "closed"
                    and previous["data"]["task_id"] == task["id"], "Choose a closed session of this task")
            require(incoming.get("continuation_revision") == previous["revision"], "Continuation revision changed; reload")
            nonempty(previous["data"].get("next_action"), "The session has no continuation step")
            start_data = {**task["data"], "first_action": previous["data"]["next_action"]}
            planning.update(continuation_id=previous["id"], continuation_revision=previous["revision"])
        if incoming.get("day_choice_id"):
            from .today import local_date
            choice = engine.store.get(incoming["day_choice_id"])
            require(choice["kind"] == "day_choice" and incoming.get("day_choice_revision") == choice["revision"], "Day choice revision changed; reload")
            saved = choice["data"]
            require(saved["date"] == local_date(engine.config["timezone"]) and saved["status"] == "selected", "Choose a result for today first")
            require(saved["task_id"] == task["id"] and saved.get("workstream_id") == incoming.get("workstream_id"), "Day choice does not match this task")
            require(not incoming.get("planner_id") and not incoming.get("planner_card_id"), "Use the day choice's saved planner link")
            start_data = saved
            planning = {k: saved[k] for k in ("planner_id", "planner_revision", "planner_card_id") if k in saved}
            planning.update(day_choice_id=choice["id"], day_choice_revision=choice["revision"])
        elif incoming.get("planner_id") or incoming.get("planner_card_id"):
            board = engine.store.get(incoming.get("planner_id"))
            require(board["kind"] == "planner", "Choose a planner")
            require(incoming.get("planner_revision") == board["revision"], "Planner revision changed; reload")
            card = next((c for c in board["data"]["cards"] if c["id"] == incoming.get("planner_card_id")), None)
            require(card is not None and card.get("task_id") == task["id"] and card.get("workstream_id") == (stream["id"] if stream else None), "Planner card does not link this task and workstream")
            require(card["selected"], "Select the planner card before starting it")
            planning = {"planner_id": board["id"], "planner_revision": board["revision"], "planner_card_id": card["id"]}
            start_data = card
        data = {"workstream_id": stream["id"] if stream else None, "task_id": task["id"], "task_revision": task["revision"],
                "title": task["data"]["title"], "status": "active", "started_at": now(), "minutes": minutes,
                "target": nonempty(incoming.get("target"), "Choose a session result"),
                "first_action": start_data.get("first_action", start_data.get("next_action", "")),
                "chat_url": start_data.get("chat_url", ""), **planning}
        if start_data.get("chat_ref"):
            data["chat_ref"] = copy.deepcopy(start_data["chat_ref"])
        normalize_chat(data)
        require(len(data["target"]) <= 2000, "Session result is too long")
    return "focus", data, existing, {}


def snapshot(engine):
    """One read of atomic records; send only workspace context, never diary/account data."""
    records = engine.store.records()
    index = {r["id"]: r for r in records}
    streams = [r for r in records if r["kind"] == "workstream"]
    task_ids = {r["id"] for r in records if r["kind"] == "task"}
    source_ids = {id for s in streams for id in s["data"].get("source_ids", [])}
    def clean(r):
        return {k: copy.deepcopy(v) for k, v in r.items() if k not in ("history", "requests", "_path")}
    from .connections import summary
    settings = [r for r in records if r["kind"] == "memory" and r["data"].get("scope") == "workspace-auto-refresh"
                and r["data"].get("status", "current") == "current"]
    latest_settings = max(settings, key=lambda r: r["updated_at"], default=None)
    from .today import local_date, history
    timezone = engine.store.config()["timezone"]
    day_choices = sorted([r for r in records if r["kind"] == "day_choice"], key=lambda r: r["data"]["date"], reverse=True)
    return {"generated_at": now(), "timezone": timezone, "today": local_date(timezone),
            "display_name": engine.store.config().get("display_name", ""),
            "calendar_configured": bool(engine.store.config().get("calendar_account")),
            "synthetic": engine.store.config().get("synthetic", False),
            "workstreams": [clean(r) for r in streams],
            "tasks": [clean(index[id]) for id in sorted(task_ids) if id in index],
            "sessions": [clean(r) for r in records if r["kind"] == "focus"],
            "workspace_items": [clean(r) for r in records if r["kind"] == "workspace_item"],
            "item_history": {r["id"]: [{"revision": v["revision"], "at": v["updated_at"], "data": copy.deepcopy(v["data"])}
                for v in (r.get("history", []) + [r])[-20:]] for r in records if r["kind"] == "workspace_item"},
            "planners": [clean(r) for r in records if r["kind"] == "planner"],
            "day_choices": [clean(r) for r in day_choices[:30]],
            "day_history": {r["id"]: [{"revision": v["revision"], "at": v["updated_at"],
                "target": v["data"].get("target"), "reason": v["data"].get("reason"), "status": v["data"]["status"]}
                for v in (r.get("history", []) + [r])[-20:]] for r in day_choices[:30]},
            "task_history": {id: history(index[id]) for id in sorted(task_ids)},
            "relationships": projection(records),
            "source_health": [h for h in summary(records) if h["id"] in source_ids],
            "auto_refresh": copy.deepcopy(latest_settings["data"].get("automation")) if latest_settings else None}
