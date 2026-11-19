"""Read-only boundary: an agent supplies a complete connector result, not credentials."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .store import nonempty, require


def day(value):
    require(isinstance(value, str), "Date must use YYYY-MM-DD")
    parsed = date.fromisoformat(value)
    require(parsed.isoformat() == value, "Date must use YYYY-MM-DD")
    return parsed


def instant(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, "Calendar timestamps require UTC offsets")
    return parsed


def days(start, end):
    first, last = day(start), day(end)
    require(first <= last and (last - first).days <= 366, "Use an ordered period of at most 367 days")
    return [(first + timedelta(days=n)).isoformat() for n in range((last - first).days + 1)]


def window(period, zone, on=None):
    tz = ZoneInfo(zone)
    today = day(on) if on else datetime.now(tz).date()
    monday = today - timedelta(days=today.weekday())
    spans = {"today": (today, 1), "tomorrow": (today + timedelta(days=1), 1),
             "this week": (monday, 7), "next week": (monday + timedelta(days=7), 7),
             "next two weeks": (monday + timedelta(days=7), 14)}
    require(period in spans, "Use today, tomorrow, this week, next week, or next two weeks; resolve other spans explicitly")
    start, length = spans[period]
    end = start + timedelta(days=length)
    return {"start": start.isoformat(), "end": (end - timedelta(days=1)).isoformat(),
            "time_min": datetime.combine(start, time(), tz).isoformat(),
            "time_max": datetime.combine(end, time(), tz).isoformat(), "timezone": zone}


def normalize(payload, config):
    require(bool(config.get("calendar_account")), "Calendar is not configured; local workspace use does not require it")
    zone = payload.get("timezone", config["timezone"])
    ZoneInfo(zone)
    start, end = instant(payload["time_min"]), instant(payload["time_max"])
    require(start < end, "Calendar window must have a positive duration")
    require(end - start <= timedelta(days=368), "Calendar window is too large")
    require(payload.get("account") == config["calendar_account"], "Calendar account does not match configured account")
    mode = payload.get("mode")
    require(mode in ("live", "fixture", "unavailable", "manual"), "Invalid calendar mode")
    fetched = instant(payload["fetched_at"])
    require(fetched <= datetime.now(timezone.utc) + timedelta(minutes=5), "Calendar fetched_at is in the future")
    require(payload.get("next_page_token") in (None, ""), "Finish all calendar pages before saving the snapshot")
    complete = payload.get("complete") is True
    require(mode not in ("live", "fixture") or complete, "Calendar read is incomplete")
    require(mode != "unavailable" or not payload.get("events"), "Unavailable reads must not include invented or cached events")
    events = []
    for event in payload.get("events", []):
        if event.get("status") == "cancelled":
            continue
        a, b = event["start"], event["end"]
        all_day = isinstance(a, dict) and "date" in a
        if all_day:
            a = datetime.combine(day(a["date"]), time(), ZoneInfo(zone))
            b = datetime.combine(day(b["date"]), time(), ZoneInfo(zone))
        else:
            a = instant(a["dateTime"] if isinstance(a, dict) else a)
            b = instant(b["dateTime"] if isinstance(b, dict) else b)
        require(a < b, "Calendar event has an invalid interval")
        if a < end and b > start:
            events.append({"id": nonempty(event.get("id"), "event.id"),
                           "title": event.get("summary", event.get("title", "Busy")),
                           "start": a.isoformat(), "end": b.isoformat(), "all_day": all_day,
                           "busy": event.get("transparency") != "transparent"})
    ids = [event["id"] for event in events]
    require(len(ids) == len(set(ids)), "Duplicate calendar events; merge pagination results by event ID")
    return {"provider": "google", "account": config["calendar_account"], "timezone": zone,
            "time_min": start.isoformat(), "time_max": end.isoformat(),
            "fetched_at": fetched.isoformat(), "mode": mode, "complete": complete,
            "events": sorted(events, key=lambda e: instant(e["start"])), "note": payload.get("note", ""),
            "meaning": "Scheduled events, not proof of activity. Empty time is not work capacity."}


def check_for_plan(snapshot, plan, allow_fixture, fallback_reason=None):
    tz = ZoneInfo(plan["timezone"])
    start = datetime.combine(day(plan["start"]), time(), tz)
    end = datetime.combine(day(plan["end"]) + timedelta(days=1), time(), tz)
    require(instant(snapshot["time_min"]) <= start and instant(snapshot["time_max"]) >= end,
            "Calendar snapshot does not cover the whole plan")
    if snapshot["mode"] in ("manual", "unavailable"):
        nonempty(fallback_reason, "explicit manual_fallback_reason")
        return
    require(snapshot["mode"] != "fixture" or allow_fixture, "Fixture calendar cannot be used for live personal plans")
    require(snapshot["complete"], "Calendar result is incomplete")
    age = datetime.now(timezone.utc) - instant(snapshot["fetched_at"])
    require(age <= timedelta(hours=1), "Calendar snapshot is older than one hour; read the period again")
