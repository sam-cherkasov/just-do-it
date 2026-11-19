"""Explicit personal notes, material references and task-linked decisions."""

import copy
import re
from urllib.parse import urlsplit

from .store import nonempty, now, require


def material_url(value):
    require(isinstance(value, str) and 0 < len(value) <= 4000, "Provide a material URL")
    require(not any(c.isspace() or ord(c) < 32 for c in value) and "\\" not in value, "Invalid material URL")
    if re.fullmatch(r"codex://threads/[a-zA-Z0-9_-]+", value):
        return value
    parsed = urlsplit(value)
    require(parsed.scheme in ("http", "https") and bool(parsed.hostname)
            and parsed.username is None and parsed.password is None, "Use an HTTP(S) or Codex chat link")
    parsed.port  # Reject invalid ports without opening or fetching the material.
    return value


def save(engine, payload):
    require(payload["source"]["kind"] in ("user_instruction", "user_report", "synthetic"),
            "Workspace items need an explicit user action")
    with engine.store.read_snapshot():
        existing = engine.existing(payload, "workspace_item") if payload.get("id") else None
        incoming = payload["data"]
        require(isinstance(incoming, dict), "Item data must be an object")
        action = incoming.get("action", "create")
        if existing:
            require(action in ("edit", "archive", "reopen", "resolve"), "Choose an item action")
            reason = nonempty(incoming.get("reason"), "Explain the change")
            require(len(reason) <= 4000, "Reason is too long")
            data = copy.deepcopy(existing["data"])
            data["change_reason"] = reason
            if action == "archive":
                require(data["status"] != "archived", "Item is already archived")
                data["status"] = "archived"
            elif action == "reopen":
                require(data["status"] != "open", "Item is already open")
                data["status"] = "open"
                data.pop("resolution", None)
                data.pop("resolved_at", None)
            elif action == "resolve":
                require(data["category"] == "question" and data["status"] == "open", "Resolve an open question")
                answer = nonempty(incoming.get("resolution"), "Record the decision")
                require(len(answer) <= 8000, "Decision is too long")
                data.update(status="resolved", resolution=answer, resolved_at=now())
            else:
                require(data["status"] == "open", "Reopen before editing")
        else:
            require(action == "create", "Create an item first")
            require(incoming.get("category") in ("note", "material", "question"), "Choose an item type")
            data = {"category": incoming["category"], "status": "open"}
        if action in ("create", "edit"):
            category = data["category"]
            require(incoming.get("category", category) == category, "Keep the original item type")
            title = nonempty(incoming.get("title"), "title")
            body = incoming.get("body", "")
            require(len(title) <= 300 and isinstance(body, str) and len(body) <= 8000, "Item text is too long")
            task_id = incoming.get("task_id") or None
            require(category == "note" or task_id, "Materials and questions need a task")
            if task_id:
                require(engine.store.get(task_id)["kind"] == "task", "Choose a task")
            data.update(title=title, body=body, task_id=task_id)
            if category == "material":
                data["url"] = material_url(incoming.get("url"))
            if category == "question":
                condition = nonempty(incoming.get("condition"), "Describe when the question is resolved")
                require(len(condition) <= 4000, "Condition is too long")
                dependency = incoming.get("depends_on_task_id") or None
                if dependency:
                    require(dependency != task_id and engine.store.get(dependency)["kind"] == "task", "Choose a different dependency task")
                data.update(condition=condition, depends_on_task_id=dependency)
        return "workspace_item", data, existing, {"notice": "Saved locally; no task status, focus or calendar changed."}
