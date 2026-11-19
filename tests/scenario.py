"""Fictional workshop scenario. Never seed into a live personal root."""

import copy
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from personal_os.engine import Engine
from personal_os.store import now


class Scenario:
    def __init__(self, root):
        self.engine = Engine(root)
        self.serial = 0
        self.engine.init({"calendar_account": "synthetic@example.test", "synthetic": True})
        today = datetime.now(ZoneInfo("Europe/Madrid")).date()
        self.first = (today + timedelta(days=7 - today.weekday())).isoformat()
        self.second = (today + timedelta(days=8 - today.weekday())).isoformat()
        self.last = (today + timedelta(days=13 - today.weekday())).isoformat()
        self.rest = [(today + timedelta(days=12 - today.weekday())).isoformat(), self.last]
        self.calendar = self.call("calendar", data=self.calendar_data())["id"]
        area = self.call("node", data={"type": "area", "title": "Independent work", "mode": "growth", "parents": []})["id"]
        goal = self.call("node", data={"type": "goal", "title": "Find a useful offer", "parents": [area], "rationale": "Fictional goal for testing the pilot."})["id"]
        strategy = self.call("node", data={"type": "strategy", "title": "Listen before building", "parents": [goal]})["id"]
        self.outcome = self.call("node", data={"type": "outcome", "title": "Test a fictional workshop offer", "parents": [strategy]})["id"]
        self.plan = {"title": "Learn whether the workshop is useful", "start": self.first, "end": self.last,
                     "timezone": "Europe/Madrid", "calendar_id": self.calendar,
                     "capacity": {self.first: 60, self.second: 60}, "protected_days": self.rest,
                     "outcomes": [self.outcome], "exclusions": ["No full workshop build yet"],
                     "actions": [{"id": "draft", "title": "Draft the workshop question", "date": self.first,
                                  "minutes": 40, "outcome_ids": [self.outcome]},
                                 {"id": "invite", "title": "Invite someone to a conversation", "date": self.first,
                                  "minutes": 20, "outcome_ids": [self.outcome]}]}

    def calendar_data(self):
        tz = ZoneInfo("Europe/Madrid")
        start = datetime.combine(datetime.fromisoformat(self.first).date(), time(), tz)
        end = datetime.combine(datetime.fromisoformat(self.last).date() + timedelta(days=1), time(), tz)
        return {"mode": "fixture", "account": "synthetic@example.test", "timezone": "Europe/Madrid",
                "time_min": start.isoformat(), "time_max": end.isoformat(), "fetched_at": now(),
                "complete": True, "events": [{"id": "fictional-call", "summary": "Fictional fixed call",
                  "start": {"dateTime": (start + timedelta(days=1, hours=14)).isoformat()},
                  "end": {"dateTime": (start + timedelta(days=1, hours=15)).isoformat()}}]}

    def call(self, operation, **payload):
        self.serial += 1
        payload.setdefault("request_id", "scenario-" + str(self.serial))
        payload.setdefault("source", {"kind": "synthetic", "reference": "Fictional dry-run dialogue"})
        return self.engine.run(operation, payload)

    def agree(self):
        draft = self.call("propose", data=self.plan)
        return self.call("commit", id=draft["id"], expected_revision=draft["revision"], agreement="Yes, let's go with that.")

    def replan(self):
        plan = copy.deepcopy(self.plan)
        plan["capacity"][self.first] = 15
        plan["capacity_change_reason"] = "User reports only fifteen minutes left after the interruption."
        plan["actions"][0]["minutes"] = 15
        plan["actions"][1]["date"] = None
        return plan

    def populate(self):
        agreed = self.agree()
        plan_id = agreed["id"]
        report = self.call("report", data={"plan_id": plan_id, "action_id": "draft", "event_date": self.first,
                           "status": "partial", "contribution": "intermediate", "text": "I made a rough draft; a call ran over."})
        proposal = self.call("propose", id=plan_id, expected_revision=2, data=self.replan())
        self.call("commit", id=plan_id, expected_revision=proposal["revision"], agreement="Yes, lighten today and leave the invitation unallocated.")
        corrected = copy.deepcopy(report["record"]["data"])
        corrected["text"] = "I wrote an outline, not a full rough draft."
        self.call("correct", id=report["id"], expected_revision=1, reason="User clarified the amount of progress", data=corrected)
        self.call("report", data={"plan_id": plan_id, "action_id": "invite", "event_date": self.first,
                  "status": "not_done", "contribution": "none", "text": "I did not send the invitation."})
        self.call("feedback", data={"text": "Put the main priority before the calendar details.", "event_date": self.first})
        first_note = self.call("diary", data={"event_date": self.first, "text": "I felt stuck before the call.\nI want to remember the uncertainty, too.\n"})
        second_note = self.call("diary", data={"event_date": self.first, "text": "After talking, I could see one smaller next step. It didn't answer the bigger question."})
        self.call("summarize-day", date=self.first)
        self.call("review", plan_id=plan_id, start=self.first, end=self.second, learning="Test the next question before building the workshop; commercial value remains unknown.")
        candidates = self.engine.evidence(self.first, self.second)
        self.call("reflect", start=self.first, end=self.second, sources=self.engine.refs(candidates),
                  text="The notes describe uncertainty and a later smaller next step. The second day has no diary coverage. This does not establish a general pattern.",
                  interpretations=[{"text": "Talking may have helped make the next step clearer in this episode.",
                     "status": "hypothesis", "support": [second_note["id"]], "counterevidence": [],
                     "limitations": "Only one selectively reported day; no causal conclusion."}])
        self.call("remember", data={"text": "A short next step may sometimes help after an interruption.",
                  "evidence_kind": "hypothesis", "scope": "This fictional episode only", "event_date": self.first,
                  "sources": [{"id": first_note["id"], "revision": 1}]})
        return plan_id
