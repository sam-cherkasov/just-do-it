"""Explicit creation commands; resumable child writes under the engine lock."""
import copy

from . import connections, workspace
from .store import fingerprint, nonempty, require


def text(data, key, limit):
    value = nonempty(data.get(key), key).strip()
    require(len(value) <= limit, key + ": текст слишком длинный")
    return value


def explicit(payload):
    require(payload["source"].get("kind") in ("user_instruction", "user_report", "synthetic"),
            "Creation requires an explicit user action")
    require(not payload.get("id"), "Creation cannot replace an existing record")
    require(isinstance(payload.get("data"), dict), "Expected creation fields")


def child(engine, kind, data, payload, suffix):
    request = payload["request_id"] + ":" + suffix
    digest = fingerprint({"parent": payload, "child": suffix})
    replay = engine.store.replay(request, digest)
    if replay:
        return engine.store.get(replay["id"])
    return engine.store.save(kind, data, payload["source"], request, digest)


def create_workstream(engine, payload):
    explicit(payload)
    incoming = payload["data"]
    title, outcome = text(incoming, "title", 160), text(incoming, "outcome", 2000)
    data = {"title": title, "summary": outcome, "outcome": outcome,
            "color": incoming.get("color", "lilac"), "status": "active", "task_ids": [],
            "source_ids": [], "sources": [], "chats": [], "questions": []}
    workspace.workstream(engine, {**payload, "data": data})  # Validate before any write.
    area = child(engine, "node", {"title": title, "type": "area", "mode": "growth",
                                  "status": "active", "parents": []}, payload, "area")
    data["area_id"] = area["id"]
    return "workstream", data, None, {}


def create_task(engine, payload):
    explicit(payload)
    incoming = payload["data"]
    title, step = text(incoming, "title", 2000), text(incoming, "next_action", 4000)
    stream = engine.store.get(incoming.get("workstream_id"))
    require(stream["kind"] == "workstream" and stream["data"].get("status") == "active",
            "Выбери активное направление")
    stream_data = copy.deepcopy(stream["data"])
    # Older directions have no area_id. Link their existing task's area where possible.
    area_id = stream_data.get("area_id")
    if not area_id:
        for task_id in stream_data.get("task_ids", []):
            parents = engine.store.get(task_id)["data"].get("parents", [])
            if parents:
                area_id = parents[0]
                break
    if area_id:
        require(engine.store.get(area_id)["kind"] == "node", "Invalid direction area")
    else:
        area_id = child(engine, "node", {"title": stream_data["title"], "type": "area", "mode": "growth",
                                        "status": "active", "parents": []}, payload, "area")["id"]
    data = {"title": title, "next_action": step, "parents": [area_id], "status": "ready",
            "intent": "proposed", "priority": "unranked", "sources": [],
            "rationale": "Задача добавлена пользователем в рабочем пространстве."}
    connections.task(engine, {**payload, "data": data})
    task = child(engine, "task", data, payload, "task")
    # Append to the latest direction under the shared lock, preserving all other fields.
    stream_data["area_id"] = area_id
    stream_data.setdefault("task_ids", [])
    if task["id"] not in stream_data["task_ids"]:
        stream_data["task_ids"].append(task["id"])
    return "workstream", stream_data, stream, {"created_task_id": task["id"]}
