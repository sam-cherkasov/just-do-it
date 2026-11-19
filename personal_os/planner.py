"""Manual scheduling experiments, separate from agreed/calendar-published plans."""

import copy
import re
from datetime import date, timedelta

from .store import nonempty, now, require


def validate(data, timezone):
    require(isinstance(data, dict), "Planner data must be an object")
    nonempty(data.get("title"), "title")
    start = date.fromisoformat(data["week_start"])
    require(start.weekday() == 0, "A planner week starts on Monday")
    dates = {(start + timedelta(days=i)).isoformat() for i in range(7)}
    require(data.get("timezone") == timezone, "Use the configured timezone")
    cards = data.get("cards")
    require(isinstance(cards, list) and len(cards) <= 100, "Use at most 100 cards")
    ids = set()
    for card in cards:
        require(isinstance(card, dict), "Each card must be an object")
        require(isinstance(card.get("id"), str) and re.fullmatch(r"[a-z0-9_-]{1,80}", card["id"]), "Invalid card ID")
        require(card["id"] not in ids, "Duplicate card ID")
        ids.add(card["id"])
        for key in ("title", "project", "outcome", "first_action", "estimate_basis"):
            require(len(nonempty(card.get(key), key)) <= 2000, key + " is too long")
        require(type(card.get("minutes")) is int and 15 <= card["minutes"] <= 720 and card["minutes"] % 15 == 0,
                "Duration must be 15–720 minutes in 15-minute steps")
        require(type(card.get("selected")) is bool, "Selection must be boolean")
        require(isinstance(card.get("note", ""), str) and len(card.get("note", "")) <= 2000, "Note is too long")
        url = card.get("chat_url", "")
        require(isinstance(url, str) and (not url or re.fullmatch(r"codex://threads/[a-zA-Z0-9_-]+", url)), "Invalid chat link")
        placement = card.get("placement")
        if placement is not None:
            require(isinstance(placement, dict) and card["selected"], "Placed cards must be selected")
            require(placement.get("date") in dates, "Placement is outside this week")
            minute = placement.get("start_minute")
            require(minute is None or (type(minute) is int and minute % 15 == 0 and 0 <= minute and minute + card["minutes"] <= 1440),
                    "Placement must fit within the day in 15-minute steps")
    availability = data.get("availability", {})
    require(isinstance(availability, dict), "Availability must be an object")
    for day, value in availability.items():
        require(day in dates and isinstance(value, dict), "Invalid availability date")
        require(value.get("level") in ("unknown", "limited", "off"), "Invalid availability level")
        require(isinstance(value.get("note"), str) and len(value["note"]) <= 500, "Invalid availability note")


def save(engine, payload, relinking=()):
    # Called under the Engine write lock; reuse one read for all card references.
    with engine.store.read_snapshot():
        return _save(engine, payload, relinking)


def _save(engine, payload, relinking):
    existing = engine.existing(payload, "planner") if payload.get("id") else None
    data = copy.deepcopy(payload["data"])
    validate(data, engine.config["timezone"])
    from .links import validate_target
    previous_cards = {c["id"]: c for c in existing["data"]["cards"]} if existing else {}
    for card in data["cards"]:
        validate_target(engine, card, None if card["id"] in relinking else previous_cards.get(card["id"]))
    data["status"] = "manual_experiment"
    # The server derives history; clients cannot fabricate past decisions.
    history = copy.deepcopy(existing["data"].get("changes", [])) if existing else []
    if existing:
        require(payload["source"]["kind"] in ("user_instruction", "synthetic"), "Planner changes need a user action")
        require(data["week_start"] == existing["data"]["week_start"], "Use a new board for a different week")
        old = {c["id"]: c for c in existing["data"]["cards"]}
        for card in data["cards"]:
            before = old.pop(card["id"], None)
            changed = [k for k in ("selected", "placement", "minutes", "note", "title", "outcome", "first_action", "task_id", "task_revision", "workstream_id", "chat_ref", "link_reason")
                       if before is None or before.get(k) != card.get(k)]
            if changed:
                history.append({"at": now(), "card_id": card["id"], "title": card["title"], "fields": changed,
                                "before": {k: before.get(k) for k in changed} if before else None,
                                "after": {k: card.get(k) for k in changed}, "reason": card.get("note", "")})
        for card in old.values():
            history.append({"at": now(), "card_id": card["id"], "title": card["title"], "fields": ["removed"]})
    data["changes"] = history[-300:]
    return "planner", data, existing, {"notice": "Saved manual choices; no calendar events or completion reports created."}
