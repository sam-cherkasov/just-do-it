"""Validated operations used by the conversational agent and the command line."""

import copy
from datetime import datetime
from zoneinfo import ZoneInfo

from . import calendar, connections, planner, workspace, links, today, work_items, onboarding
from .store import Invalid, Store, atomic_write, fingerprint, nonempty, now, require


GENERATED = ("summary", "reflection", "review")


class Engine:
    def __init__(self, root):
        self.store = Store(root)

    def init(self, payload):
        import json
        account = payload.get("calendar_account") or None
        if account is not None:
            nonempty(account, "calendar_account")
        config = {"schema_version": 1, "timezone": payload.get("timezone", "Europe/Madrid"),
                  "calendar_provider": "google" if account else None, "calendar_account": account,
                  "synthetic": payload.get("synthetic", False)}
        if "display_name" in payload:
            config["display_name"] = nonempty(payload["display_name"], "Имя").strip()
            require(len(config["display_name"]) <= 100, "Имя слишком длинное")
        require(type(config["synthetic"]) is bool, "synthetic must be boolean")
        try:
            ZoneInfo(config["timezone"])
        except (KeyError, ValueError, TypeError):
            require(False, "Неизвестный часовой пояс. Укажи, например, Europe/Paris или UTC.")
        with self.store.lock():
            path = self.store.safe(self.store.personal / "config.json")
            if path.exists():
                require(self.store.config() == config, "Configuration already exists; do not silently reinitialize it")
            else:
                atomic_write(path, json.dumps(config, indent=2) + "\n")
        return {"ok": True, "config": self.store.config()}

    def refs(self, records):
        return [{"id": r["id"], "revision": r["revision"]} for r in sorted(records, key=lambda r: r["id"])]

    def evidence(self, start, end, kinds=("diary", "report")):
        calendar.days(start, end)
        return [r for r in self.store.records() if r["kind"] in kinds
                and start <= r["data"].get("event_date", "") <= end]

    def stale(self, record):
        if record["kind"] in ("memory", "task"):
            for ref in record["data"].get("sources", []):
                try:
                    if self.store.get(ref["id"])["revision"] != ref["revision"]:
                        return True
                except Invalid:
                    return True
            return connections.stale_reference(self, record)
        if record["kind"] not in GENERATED:
            return False
        data = record["data"]
        candidates = self.evidence(data["start"], data["end"], tuple(data["coverage_kinds"]))
        if data.get("plan_id"):
            try:
                candidates.append(self.store.get(data["plan_id"]))
            except Invalid:
                return True
        return data["sources"] != self.refs(candidates)

    def public(self, record, history=False):
        result = copy.deepcopy(record)
        result.pop("requests", None)
        if not history:
            result.pop("history", None)
        if result["kind"] in GENERATED + ("memory", "task"):
            result["stale"] = self.stale(record)
        return result

    def context(self, start=None, end=None, kind=None, status=None):
        with self.store.read_snapshot():
            return self._context(start, end, kind, status)

    def _context(self, start=None, end=None, kind=None, status=None):
        config = self.store.config()
        records = self.store.records()
        if start or end:
            require(bool(start and end), "Specify both start and end")
            calendar.days(start, end)
            selected = [r for r in records if start <= r["data"].get("event_date", r["data"].get("start", "")) <= end]
        elif kind:
            selected = records
        else:
            # Diary bodies and long-running history are deliberately absent from startup.
            selected = [r for r in records if r["kind"] in ("node", "memory", "plan", "planner", "workstream", "focus")
                        and r["data"].get("status") not in ("closed", "rejected", "superseded")]
            selected += sorted([r for r in records if r["kind"] == "day_choice"],
                               key=lambda r: r["data"]["date"], reverse=True)[:5]
            selected += [r for r in records if r["kind"] == "workspace_item" and r["data"]["status"] == "open"]
            for recent_kind in ("report", "review"):
                selected += sorted([r for r in records if r["kind"] == recent_kind],
                                   key=lambda r: r["updated_at"], reverse=True)[:5]
            selected += connections.context_records(records)
        if kind:
            selected = [r for r in selected if r["kind"] == kind]
        if status:
            selected = [r for r in selected if r["data"].get("status") == status]
        return {"config": config, "records": [self.public(r) for r in selected],
                "source_health": connections.summary(records),
                "feedback_pending": sum(r["kind"] == "feedback" and r["data"]["status"] in ("new", "selected") for r in records),
                "notice": "Missing reports are unknown. Load diary dates explicitly. Calendar requires a fresh read when planning."}

    def run(self, operation, payload):
        if operation == "init":
            return self.init(payload)
        with self.store.lock():
            self.config = self.store.config()
            request_id = nonempty(payload.get("request_id"), "request_id")
            digest = fingerprint({"operation": operation, "payload": payload})
            replay = self.store.replay(request_id, digest)
            if replay:
                if operation == "create-task":
                    replay["created_task_id"] = "task_" + fingerprint(request_id + ":task")[:20]
                return replay
            source = payload.get("source", {})
            require(isinstance(source, dict), "source must be an object")
            if operation in ("commit", "reject", "close", "correct"):
                require(source.get("kind") in ("user_instruction", "user_report", "synthetic"),
                        "Agreement and corrections require an explicit user source")
            if operation in ("diary", "report"):
                require(source.get("kind") in ("user_report", "synthetic"), "Original notes/reports require a user_report source")
            if source.get("kind") == "synthetic":
                require(self.config["synthetic"], "Synthetic records require a separate synthetic project")
            handlers = {"create-workstream": lambda p: onboarding.create_workstream(self, p),
                        "create-task": lambda p: onboarding.create_task(self, p),
                        "calendar": self.calendar, "node": self.node, "remember": self.memory,
                        "propose": self.propose, "commit": self.commit, "reject": self.reject,
                        "close": self.close, "report": self.report, "diary": self.diary,
                        "feedback": self.feedback, "correct": self.correct,
                        "summarize-day": self.summary, "reflect": self.reflection, "review": self.review,
                        "register-source": lambda p: connections.register(self, p),
                        "check-source": lambda p: connections.check(self, p),
                        "review-source": lambda p: connections.review(self, p),
                        "task": lambda p: connections.task(self, p),
                        "task-control": lambda p: today.update_task(self, p),
                        "choose-day": lambda p: today.choose_day(self, p),
                        "workspace-item": lambda p: work_items.save(self, p),
                        "planner": lambda p: planner.save(self, p),
                        "link-planner-cards": lambda p: links.link_cards(self, p),
                        "workstream": lambda p: workspace.workstream(self, p),
                        "focus": lambda p: workspace.focus(self, p)}
            require(operation in handlers, "Unknown operation")
            kind, data, existing, extra = handlers[operation](payload)
            if kind in GENERATED:
                require(source.get("kind") in ("agent_generated", "synthetic"), "Generated records must be labeled agent_generated")
            saved = self.store.save(kind, data, source, request_id, digest,
                                    existing, existing["revision"] if operation == "create-task" else payload.get("expected_revision"))
            return {"ok": True, "id": saved["id"], "revision": saved["revision"], "replayed": False,
                    "record": self.public(saved), **extra}

    def existing(self, payload, kind=None):
        record = self.store.get(payload["id"])
        if kind:
            require(record["kind"] == kind, "Wrong record type")
        require(payload.get("expected_revision") == record["revision"], "Stale revision; reload before making changes")
        return record

    def source_refs(self, refs):
        require(isinstance(refs, list), "sources must be a list")
        for ref in refs:
            record = self.store.get(ref["id"])
            require(record["revision"] == ref["revision"], "Source changed; reread it before interpreting")
        return refs

    def calendar(self, payload):
        require(payload["source"]["kind"] in ("calendar", "synthetic"), "Calendar results require a calendar source")
        data = calendar.normalize(payload["data"], self.config)
        require(data["mode"] != "fixture" or self.config["synthetic"], "Fixtures belong in a synthetic project")
        return "calendar", data, None, {}

    def validate_node(self, data, node_id=None):
        nonempty(data.get("title"), "title")
        require(data.get("type") in ("area", "goal", "strategy", "experiment", "outcome"), "Invalid node type")
        require(data.get("status", "active") in ("active", "paused", "superseded"), "Invalid node status")
        parents = data.get("parents", [])
        require(isinstance(parents, list) and len(parents) == len(set(parents)), "parents must be unique IDs")
        def visit(parent_id, seen):
            require(parent_id != node_id and parent_id not in seen, "Life map cannot contain a parent cycle")
            record = self.store.get(parent_id)
            require(record["kind"] == "node", "Parents must be life-map nodes")
            for ancestor in record["data"].get("parents", []):
                visit(ancestor, seen | {parent_id})
        for parent in parents:
            visit(parent, set())
        if data["type"] == "area":
            require(data.get("mode") in ("growth", "maintenance", "essentials", "paused"), "Area requires a focus mode")

    def node(self, payload):
        data = copy.deepcopy(payload["data"])
        self.validate_node(data)
        data.setdefault("status", "active")
        return "node", data, None, {}

    def memory(self, payload):
        data = copy.deepcopy(payload["data"])
        self.validate_memory(data)
        data.setdefault("status", "current")
        return "memory", data, None, {}

    def validate_memory(self, data):
        nonempty(data.get("text"), "text")
        require(data.get("evidence_kind") in ("user_statement", "observation", "hypothesis"), "Memory requires an evidence kind")
        require(data.get("status", "current") in ("current", "rejected", "superseded"), "Invalid memory status")
        nonempty(data.get("scope"), "scope")
        calendar.day(data["event_date"])
        self.source_refs(data.get("sources", []))
        if data["evidence_kind"] != "user_statement":
            require(bool(data.get("sources")), "Observations and hypotheses require sources")

    def validate_plan(self, plan, previous=None):
        nonempty(plan.get("title"), "plan.title")
        dates = calendar.days(plan["start"], plan["end"])
        ZoneInfo(plan["timezone"])
        self.source_refs(plan.get("learning_sources", []))
        for ref in plan.get("learning_sources", []):
            require(not self.stale(self.store.get(ref["id"])), "Regenerate stale learning before using it in a plan")
        require(plan["timezone"] == self.config["timezone"], "Use the configured planning timezone")
        snapshot = self.store.get(plan["calendar_id"])
        require(snapshot["kind"] == "calendar", "Plan requires a calendar snapshot")
        calendar.check_for_plan(snapshot["data"], plan, self.config["synthetic"], plan.get("manual_fallback_reason"))
        # A later failure/read supersedes an older successful read for this exact span.
        newer = [r for r in self.store.records() if r["kind"] == "calendar"
                 and r["created_at"] > snapshot["created_at"]
                 and r["data"]["time_min"] == snapshot["data"]["time_min"]
                 and r["data"]["time_max"] == snapshot["data"]["time_max"]]
        require(not newer, "A newer calendar read exists; use that result")
        capacity = plan.get("capacity", {})
        require(isinstance(capacity, dict), "capacity must map dates to user-provided minutes")
        for date, minutes in capacity.items():
            require(date in dates and type(minutes) is int and 0 <= minutes <= 1440, "Invalid capacity date/minutes")
        protected = plan.get("protected_days", [])
        require(isinstance(protected, list) and all(d in dates for d in protected), "Invalid protected dates")
        require(all(capacity.get(d, 0) == 0 for d in protected), "Protected rest cannot carry work capacity")
        totals, action_ids = {}, set()
        for outcome_id in plan.get("outcomes", []):
            node = self.store.get(outcome_id)
            require(node["kind"] == "node" and node["data"]["type"] in ("outcome", "experiment"), "Plan outcomes must reference outcomes or experiments")
        require(isinstance(plan.get("actions"), list), "actions must be a list")
        for action in plan["actions"]:
            old_action = next((a for a in (previous or {}).get("actions", []) if a.get("id") == action.get("id")), None)
            links.validate_target(self, action, old_action)
            nonempty(action.get("id"), "action.id")
            nonempty(action.get("title"), "action.title")
            require(action["id"] not in action_ids, "Duplicate action ID")
            action_ids.add(action["id"])
            minutes = action.get("minutes")
            require(type(minutes) is int and minutes > 0, "Action minutes must be a positive integer")
            outcome_links = action.get("outcome_ids", [])
            require(bool(outcome_links) or action.get("maintenance") is True, "Link actions to an outcome or label maintenance")
            require(all(o in plan.get("outcomes", []) for o in outcome_links), "Action outcome is outside the plan")
            date = action.get("date")
            if date is not None:
                require(date in capacity and date not in protected, "Scheduled work needs stated capacity and cannot consume protected rest")
                totals[date] = totals.get(date, 0) + minutes
                require(totals[date] <= capacity[date], "Proposed work exceeds capacity on " + date)
        require(isinstance(plan.get("exclusions", []), list), "exclusions must be a list")
        if previous:
            removed_rest = set(previous.get("protected_days", [])) - set(protected)
            if removed_rest:
                nonempty(plan.get("rest_change_reason"), "explicit user rest_change_reason")
            if previous.get("capacity") != capacity:
                nonempty(plan.get("capacity_change_reason"), "capacity_change_reason")
            removed_actions = {a["id"] for a in previous["actions"]} - action_ids
            if removed_actions:
                nonempty(plan.get("displaced_work_reason"), "displaced_work_reason")

    def propose(self, payload):
        existing = self.existing(payload, "plan") if payload.get("id") else None
        previous = existing["data"].get("agreed") if existing else None
        require(not existing or existing["data"]["status"] != "closed", "Closed plans cannot be changed")
        plan = copy.deepcopy(payload["data"])
        self.validate_plan(plan, previous)
        data = copy.deepcopy(existing["data"]) if existing else {"status": "draft", "agreed": None}
        data["proposal"] = plan
        changes = {key: {"before": previous.get(key) if previous else None, "after": value}
                   for key, value in plan.items() if not previous or previous.get(key) != value}
        data["proposal_changes"] = changes
        return "plan", data, existing, {"changes": changes, "notice": "Proposal only; the agreed plan has not changed"}

    def commit(self, payload):
        existing = self.existing(payload, "plan")
        data = copy.deepcopy(existing["data"])
        require(data.get("proposal") is not None and data["status"] != "closed", "No proposal to accept")
        nonempty(payload.get("agreement"), "user agreement")
        self.validate_plan(data["proposal"], data.get("agreed"))
        other = [r for r in self.store.records() if r["kind"] == "plan" and r["id"] != existing["id"] and r["data"]["status"] == "agreed"]
        require(not other, "Close the previous active plan before agreeing a new cycle")
        data.update(agreed=data["proposal"], proposal=None, proposal_changes={}, status="agreed",
                    agreement=payload["agreement"], agreed_at=now())
        return "plan", data, existing, {}

    def reject(self, payload):
        existing = self.existing(payload, "plan")
        data = copy.deepcopy(existing["data"])
        require(data.get("proposal") is not None, "No pending proposal")
        data.update(proposal=None, proposal_changes={}, status="agreed" if data.get("agreed") else "rejected")
        return "plan", data, existing, {}

    def close(self, payload):
        existing = self.existing(payload, "plan")
        data = copy.deepcopy(existing["data"])
        require(data["status"] == "agreed", "Only an agreed cycle can be closed")
        nonempty(payload.get("reason"), "reason")
        data.update(status="closed", proposal=None, proposal_changes={}, closure_reason=payload["reason"])
        return "plan", data, existing, {}

    def actions(self, plan):
        actions = {}
        for snapshot in plan["history"] + [plan]:
            agreed = snapshot["data"].get("agreed")
            if agreed:
                actions.update({a["id"]: a for a in agreed["actions"]})
        return actions

    def validate_report(self, data):
        calendar.day(data["event_date"])
        nonempty(data.get("text"), "report.text")
        require(data.get("status") in ("completed", "partial", "not_done", "unknown"), "Invalid reported status")
        require(data.get("contribution") in ("output", "intermediate", "learning", "preparation", "none"), "Label the kind of reported contribution")
        plan = self.store.get(data["plan_id"])
        require(plan["kind"] == "plan" and data["action_id"] in self.actions(plan), "Report must reference a previously agreed action")

    def report(self, payload):
        data = copy.deepcopy(payload["data"])
        self.validate_report(data)
        return "report", data, None, {}

    def diary(self, payload):
        data = copy.deepcopy(payload["data"])
        nonempty(data.get("text"), "diary.text")
        calendar.day(data["event_date"])
        data["timezone"] = self.config["timezone"]
        data["received_as"] = "text"
        return "diary", data, None, {}

    def feedback(self, payload):
        existing = self.existing(payload, "feedback") if payload.get("id") else None
        data = copy.deepcopy(existing["data"]) if existing else copy.deepcopy(payload["data"])
        if existing:
            data["status"] = payload["status"]
            data["triage_note"] = payload.get("triage_note", "")
        else:
            data["status"] = "new"
            data["event_date"] = data.get("event_date", datetime.now(ZoneInfo(self.config["timezone"])).date().isoformat())
        calendar.day(data["event_date"])
        nonempty(data.get("text"), "feedback.text")
        require(data["status"] in ("new", "selected", "resolved", "deferred"), "Invalid feedback status")
        return "feedback", data, existing, {}

    def correct(self, payload):
        existing = self.existing(payload)
        kind = existing["kind"]
        require(kind in ("diary", "report", "memory", "node"), "Use the dedicated operation for this record type")
        nonempty(payload.get("reason"), "correction reason")
        data = copy.deepcopy(payload["data"])
        # The original path is a stable locator; corrected event dates drive retrieval.
        if "event_date" in existing["data"]:
            calendar.day(data["event_date"])
        if kind == "diary":
            nonempty(data.get("text"), "text")
            data["timezone"] = existing["data"]["timezone"]
            data["received_as"] = "text"
        elif kind == "report":
            self.validate_report(data)
            require(data["plan_id"] == existing["data"]["plan_id"] and data["action_id"] == existing["data"]["action_id"], "Correct a report without moving its action reference")
        elif kind == "memory":
            self.validate_memory(data)
        else:
            self.validate_node(data, existing["id"])
        data["correction_reason"] = payload["reason"]
        return kind, data, existing, {}

    def generated(self, kind, payload, start, end, candidates, text, extra=None):
        existing = self.existing(payload, kind) if payload.get("id") else None
        if not existing and kind in ("summary", "review"):
            duplicates = [r for r in self.store.records() if r["kind"] == kind
                          and r["data"]["start"] == start and r["data"]["end"] == end
                          and r["data"].get("plan_id") == (extra or {}).get("plan_id")]
            require(not duplicates, "Summary/review already exists; regenerate using its ID and expected_revision")
        if existing:
            require(existing["data"]["start"] == start and existing["data"]["end"] == end, "Regenerate the same period")
        nonempty(text, "generated text")
        dates = calendar.days(start, end)
        covered = sorted({r["data"]["event_date"] for r in candidates if r["kind"] in ("diary", "report")})
        data = {"text": text, "start": start, "end": end, "event_date": start,
                "timezone": self.config["timezone"], "sources": self.refs(candidates),
                "coverage_kinds": ["diary", "report"] if kind != "review" else ["report"],
                "covered_days": covered, "missing_days": [d for d in dates if d not in covered],
                "interpretation_status": "agent_generated; selective self-report, not objective measurement",
                **(extra or {})}
        return kind, data, existing, {}

    def summary(self, payload):
        date = payload["date"]
        candidates = self.evidence(date, date)
        require(bool(candidates), "No diary notes or reports for that day; do not invent a summary")
        refs = self.refs(candidates)
        text = payload.get("text")
        if text is not None:
            require(payload.get("sources") == refs, "Summary sources must match all current notes/reports for the day")
        else:
            text = "# Daily record: " + date + "\n\nAgent-generated source digest. No interpretation added.\n\n"
            for r in candidates:
                text += "## " + ("Diary note" if r["kind"] == "diary" else "Reported activity") + "\n\n" + r["data"]["text"] + "\n\nSource: " + r["id"] + " (revision " + str(r["revision"]) + ").\n\n"
        return self.generated("summary", payload, date, date, candidates, text)

    def reflection(self, payload):
        start, end = payload["start"], payload["end"]
        candidates = self.evidence(start, end)
        require(bool(candidates), "No source notes/reports in this period")
        require(payload.get("sources") == self.refs(candidates), "Reflection must cite current original records, not summaries as independent evidence")
        observations = payload.get("interpretations", [])
        allowed = {r["id"] for r in candidates}
        for item in observations:
            nonempty(item.get("text"), "interpretation.text")
            require(item.get("status") == "hypothesis", "Interpretations remain hypotheses")
            require(bool(item.get("support")) and set(item["support"]) <= allowed, "Interpretation needs supporting source IDs")
            require(set(item.get("counterevidence", [])) <= allowed, "Counterevidence must reference source IDs")
            nonempty(item.get("limitations"), "interpretation limitations")
        return self.generated("reflection", payload, start, end, candidates, payload["text"],
                              {"interpretations": observations})

    def review(self, payload):
        plan = self.store.get(payload["plan_id"])
        require(plan["kind"] == "plan" and plan["data"].get("agreed"), "Review needs an agreed plan")
        start, end = payload["start"], payload["end"]
        reports = [r for r in self.evidence(start, end, ("report",)) if r["data"]["plan_id"] == plan["id"]]
        # Include all reports in the span in coverage so new reports invalidate prior reviews.
        candidates = self.evidence(start, end, ("report",)) + [plan]
        latest = {}
        for report in sorted(reports, key=lambda r: (r["data"]["event_date"], r["updated_at"])):
            latest[report["data"]["action_id"]] = report
        findings = []
        current_ids = {a["id"] for a in plan["data"]["agreed"]["actions"]}
        for action_id, action in self.actions(plan).items():
            if action_id not in latest and (not action.get("date") or not start <= action["date"] <= end):
                continue
            report = latest.get(action_id)
            findings.append({"action_id": action_id, "title": action["title"],
                             "status": report["data"]["status"] if report else "unknown",
                             "contribution": report["data"]["contribution"] if report else "none",
                             "source": report["id"] if report else None, "in_current_plan": action_id in current_ids})
        text = "# Review: " + start + " to " + end + "\n\nBased on explicit reports. Missing activity remains unknown.\n\n"
        text += "\n".join("- " + f["title"] + ": " + f["status"] + " (" + f["contribution"] + ")." for f in findings)
        if payload.get("learning"):
            text += "\n\n## Proposed learning\n\n" + payload["learning"]
        return self.generated("review", payload, start, end, candidates, text,
                              {"plan_id": plan["id"], "findings": findings, "learning": payload.get("learning", "")})
