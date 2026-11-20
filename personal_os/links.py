"""Stable, validated links; saved planning text is never refreshed implicitly."""

import copy
import re

from .store import require


def chat_reference(data):
    """Read legacy Codex URLs without rewriting the record or guessing its topic."""
    ref = data.get("chat_ref")
    url = data.get("chat_url", "")
    if ref is None:
        if not url:
            return None
        match = re.fullmatch(r"codex://threads/([a-zA-Z0-9_-]+)", url)
        require(match is not None, "Invalid chat URL")
        return {"provider": "codex", "host_id": "local", "thread_id": match.group(1)}
    require(isinstance(ref, dict) and set(ref) == {"provider", "host_id", "thread_id"}, "Invalid chat reference")
    require(ref["provider"] == "codex", "Unsupported chat provider")
    for key in ("host_id", "thread_id"):
        require(isinstance(ref[key], str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,160}", ref[key]), "Invalid chat " + key)
    require(not url or url == "codex://threads/" + ref["thread_id"], "Chat reference and URL disagree")
    require(not url or ref["host_id"] == "local", "Remote chat needs a host-aware navigation adapter")
    return copy.deepcopy(ref)


def normalize_chat(data):
    ref = chat_reference(data)
    if ref:
        data["chat_ref"] = ref
        # Existing deep links do not encode remote host identity.
        if ref["host_id"] == "local":
            data.setdefault("chat_url", "codex://threads/" + ref["thread_id"])
    return ref


def validate_target(engine, data, previous=None):
    """Validate a link and capture task revision on creation, not on every edit."""
    task_id, stream_id = data.get("task_id"), data.get("workstream_id")
    if stream_id:
        stream = engine.store.get(stream_id)
        require(stream["kind"] == "workstream", "Choose a workstream")
    if task_id:
        require(type(data.get("task_revision")) is int and data["task_revision"] > 0, "Capture an integer task revision")
        task = engine.store.get(task_id)
        require(task["kind"] == "task", "Choose a task")
        changed = not previous or previous.get("task_id") != task_id or previous.get("workstream_id") != stream_id
        if changed:
            if stream_id:
                require(task_id in stream["data"].get("task_ids", []), "Task is outside the workstream")
            require(data.get("task_revision") == task["revision"], "Task revision changed; reload before linking")
        else:
            require(data.get("task_revision") == previous.get("task_revision"), "Relink explicitly to change the task snapshot")
    else:
        require(data.get("task_revision") is None, "Task revision needs a task")
    normalize_chat(data)


def link_cards(engine, payload):
    """Attach reviewed identities without changing any manual planning choices."""
    with engine.store.read_snapshot():
        return _link_cards(engine, payload)


def _link_cards(engine, payload):
    require(payload["source"]["kind"] in ("user_instruction", "synthetic"), "Linking needs an explicit user instruction")
    record = engine.existing(payload, "planner")
    data = copy.deepcopy(record["data"])
    cards = {c["id"]: c for c in data["cards"]}
    entries = payload["data"].get("links")
    require(isinstance(entries, list) and entries, "Provide card links")
    seen = set()
    for entry in entries:
        key = entry.get("card_id")
        require(key in cards and key not in seen, "Unknown or duplicate planner card")
        seen.add(key)
        require(isinstance(entry.get("reason"), str) and entry["reason"].strip(), "Explain the link")
        card = cards[key]
        for field in ("task_id", "workstream_id", "task_revision"):
            if entry.get(field) is None:
                card.pop(field, None)
            else:
                card[field] = entry[field]
        validate_target(engine, card)
        card["link_reason"] = entry["reason"]
    from .planner import save
    return save(engine, {**payload, "data": data}, relinking=seen)


def projection(records):
    """A minimal relationship index; no diary, source transcript, or runtime inference."""
    index = {r["id"]: r for r in records}
    result = {"cards": [], "actions": [], "sessions": [], "days": [], "items": [], "chats": []}
    chats = {}

    def attach(data, owner):
        ref = chat_reference(data)
        if ref:
            key = (ref["provider"], ref["host_id"], ref["thread_id"])
            item = chats.setdefault(key, {**ref, "owners": []})
            item["owners"].append(owner)
        return ref

    def target(data):
        task = index.get(data.get("task_id"))
        stream = index.get(data.get("workstream_id"))
        return {"task_id": data.get("task_id"), "workstream_id": data.get("workstream_id"),
                "task_revision": data.get("task_revision"),
                "membership_changed": bool(task and data.get("workstream_id") and
                    (not stream or task["id"] not in stream["data"].get("task_ids", []))),
                "task_changed": bool(task and data.get("task_revision") != task["revision"]),
                "task_missing": bool(data.get("task_id") and not task)}

    for record in records:
        kind, data, rid = record["kind"], record["data"], record["id"]
        if kind == "task":
            attach(data, {"kind": "task", "id": rid})
        elif kind == "workstream":
            for chat in data.get("chats", []):
                attach({"chat_url": chat["url"], **({"chat_ref": chat["chat_ref"]} if chat.get("chat_ref") else {})}, {"kind": kind, "id": rid})
        elif kind == "planner":
            for card in data["cards"]:
                result["cards"].append({"planner_id": rid, "planner_revision": record["revision"],
                    "card_id": card["id"], "title": card["title"], "selected": card["selected"],
                    "placement": copy.deepcopy(card.get("placement")), **target(card),
                    "chat_ref": attach(card, {"kind": kind, "id": rid, "card_id": card["id"]})})
        elif kind == "plan":
            for phase in ("agreed", "proposal"):
                for action in (data.get(phase) or {}).get("actions", []):
                    result["actions"].append({"plan_id": rid, "phase": phase, "action_id": action["id"],
                        **target(action), "chat_ref": attach(action, {"kind": kind, "id": rid, "action_id": action["id"], "phase": phase})})
        elif kind == "day_choice":
            result["days"].append({"day_choice_id": rid, "date": data["date"], "status": data["status"], **target(data),
                "planner_id": data.get("planner_id"), "planner_card_id": data.get("planner_card_id"),
                "chat_ref": attach(data, {"kind": kind, "id": rid})})
        elif kind == "workspace_item":
            result["items"].append({"item_id": rid, "task_id": data.get("task_id"),
                "category": data["category"], "status": data["status"],
                "depends_on_task_id": data.get("depends_on_task_id")})
        elif kind == "focus":
            planner = index.get(data.get("planner_id"))
            card = next((c for c in planner["data"]["cards"] if c["id"] == data.get("planner_card_id")), None) if planner else None
            result["sessions"].append({"focus_id": rid, **target(data),
                "continuation_id": data.get("continuation_id"), "continuation_revision": data.get("continuation_revision"),
                "day_choice_id": data.get("day_choice_id"), "day_choice_revision": data.get("day_choice_revision"),
                "planner_id": data.get("planner_id"), "planner_card_id": data.get("planner_card_id"),
                "planner_changed": bool(planner and planner["revision"] != data.get("planner_revision")),
                "card_missing": bool(data.get("planner_card_id") and card is None),
                "chat_ref": attach(data, {"kind": kind, "id": rid})})
    result["chats"] = [chats[k] for k in sorted(chats)]
    return result
