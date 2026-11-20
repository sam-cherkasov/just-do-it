import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from personal_os.connections import refresh
from personal_os.engine import Engine
from personal_os.store import Invalid, now
from personal_os.view import render


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.e = Engine(self.root)
        self.e.init({"calendar_account": "fiction@example.test", "synthetic": True})
        self.serial = 0
        self.area = self.call("node", data={"type": "area", "title": "Fictional income", "mode": "growth"})["id"]
        self.file = self.root / "external" / "current.md"
        self.file.parent.mkdir()
        self.file.write_text("Fictional proposal sent; acceptance unknown.\n")
        self.source = self.call("register-source", data={"title": "Fictional project", "source_type": "file",
                                "locator": str(self.file), "scope": "Current project status"})

    def call(self, operation, **payload):
        self.serial += 1
        payload.setdefault("request_id", "connection-test-" + str(self.serial))
        payload.setdefault("source", {"kind": "synthetic", "reference": "Fictional connection test"})
        return self.e.run(operation, payload)

    def check(self):
        return self.call("check-source", data={"source_id": self.source["id"], "source_revision": 1})

    def waiting_task(self, check):
        return self.call("task", data={"title": "Fictional sent offer", "parents": [self.area],
                         "intent": "reported", "status": "waiting", "priority": "primary",
                         "rationale": "Potential contribution, not accepted revenue", "waiting_on": "Client reply",
                         "sources": [{"id": check["id"], "revision": 1}]})

    def test_update_once_becomes_reviewable_without_claiming_acceptance(self):
        first = refresh(self.e)
        self.assertTrue(first["ok"])
        self.assertIn("acceptance unknown", first["checks"][0]["content"])
        check_id = first["checks"][0]["check_id"]
        self.assertEqual(self.e.context()["source_health"][0]["state"], "needs_review")
        task = self.waiting_task({"id": check_id})
        self.call("review-source", data={"check_id": check_id, "outcome": "reconciled",
                  "summary": "Offer sent; acceptance remains unknown", "records": [{"id": task["id"], "revision": 1}]})
        unchanged = refresh(self.e)
        self.assertNotIn("content", unchanged["checks"][0])
        self.assertFalse(self.e.public(self.e.store.get(task["id"]))["stale"])
        self.file.write_text("Fictional client requested a revised scope, not accepted.\n")
        changed = refresh(self.e)
        self.assertIn("revised scope", changed["checks"][0]["content"])
        self.assertEqual(self.e.context()["source_health"][0]["state"], "needs_review")
        self.assertTrue(self.e.public(self.e.store.get(task["id"]))["stale"])
        self.assertEqual(self.e.store.get(task["id"])["data"]["status"], "waiting")

    def test_failed_read_preserves_last_success_and_requires_attention(self):
        checked = self.check()
        self.file.unlink()
        result = refresh(self.e)
        self.assertFalse(result["ok"])
        health = self.e.context()["source_health"][0]
        self.assertEqual(health["state"], "unavailable")
        self.assertEqual(health["last_success_at"], checked["record"]["data"]["checked_at"])
        with self.assertRaisesRegex(Invalid, "became unavailable"):
            self.call("review-source", data={"check_id": checked["id"], "outcome": "no_relevant_change", "summary": "Wrong"})

    def test_cannot_ack_a_changed_source_or_unsaved_outputs(self):
        checked = self.check()
        with self.assertRaisesRegex(Invalid, "saved output"):
            self.call("review-source", data={"check_id": checked["id"], "outcome": "reconciled", "summary": "Unsaved"})
        self.file.write_text("Changed")
        self.check()
        with self.assertRaisesRegex(Invalid, "Source changed"):
            self.call("review-source", data={"check_id": checked["id"], "outcome": "no_relevant_change", "summary": "Stale check"})

    def test_local_status_is_observed_not_supplied_and_binary_and_symlink_fail_honestly(self):
        with self.assertRaisesRegex(Invalid, "read the file"):
            self.call("check-source", data={"source_id": self.source["id"], "source_revision": 1, "status": "ok"})
        self.file.write_bytes(b"\xff\xfe")
        self.assertEqual(self.check()["record"]["data"]["status"], "unavailable")
        self.file.unlink()
        self.file.symlink_to(self.root / "personal" / "config.json")
        self.assertEqual(self.check()["record"]["data"]["status"], "unavailable")

    def test_chat_requires_real_connector_receipt_and_is_never_marked_read_by_local_refresh(self):
        chat = self.call("register-source", data={"title": "Fictional chat", "source_type": "chat", "locator": "fictional-thread",
                        "scope": "User updates"})
        result = refresh(self.e)
        self.assertEqual(result["chat_reads_required"][0]["id"], chat["id"])
        self.assertEqual(next(h for h in self.e.context()["source_health"] if h["id"] == chat["id"])["state"], "not_checked")
        payload = {"source_id": chat["id"], "source_revision": 1, "status": "ok", "checked_at": now()}
        with self.assertRaises(Invalid):
            self.call("check-source", data=payload)
        payload.update(observed_revision="last-user-message-42", fingerprint=hashlib.sha256(b"Fictional update").hexdigest(),
                       coverage="Latest user message returned by the connector")
        check = self.call("check-source", data=payload)
        self.assertEqual(check["record"]["data"]["observed_revision"], "last-user-message-42")
        self.assertEqual(next(h for h in self.e.context()["source_health"] if h["id"] == chat["id"])["state"], "needs_review")

    def test_task_proposal_cannot_become_reported_work_without_evidence(self):
        data = {"title": "Fictional next move", "parents": [self.area], "intent": "proposed", "status": "candidate",
                "rationale": "Test an offer", "next_action": "Read the fictional source"}
        task = self.call("task", data=data)
        done = {**data, "status": "done", "completion_evidence": "Invented"}
        with self.assertRaisesRegex(Invalid, "cannot claim"):
            self.call("task", id=task["id"], expected_revision=1, reason="Wrong", data=done)
        reported = {**data, "intent": "reported", "status": "done", "completion_evidence": "Explicit fictional user report"}
        with self.assertRaisesRegex(Invalid, "user report or saved evidence"):
            self.call("task", source={"kind": "agent_generated", "reference": "Unsupported guess"}, data=reported)
        result = self.call("task", id=task["id"], expected_revision=1, reason="User reports completion", data=reported)
        self.assertEqual(result["revision"], 2)
        self.assertEqual(self.e.store.get(task["id"])["history"][0]["data"]["intent"], "proposed")
        self.assertNotIn(task["id"], [r["id"] for r in self.e.context()["records"]])

    def test_task_revision_conflict_and_retry_are_safe(self):
        checked = self.check()
        task = self.waiting_task(checked)
        payload = {"request_id": "same-task-update", "source": {"kind": "synthetic", "reference": "Fictional clarification"},
                   "id": task["id"], "expected_revision": 1, "data": copy.deepcopy(task["record"]["data"])}
        payload["data"]["waiting_on"] = "Clarified reply"
        result = self.e.run("task", payload)
        self.assertTrue(self.e.run("task", payload)["replayed"])
        self.assertEqual(result["revision"], 2)
        with self.assertRaisesRegex(Invalid, "Stale revision"):
            self.call("task", id=task["id"], expected_revision=1, data=payload["data"])

    def test_registration_changes_invalidate_old_check_and_duplicates_are_rejected(self):
        checked = self.check()
        task = self.waiting_task(checked)
        with self.assertRaisesRegex(Invalid, "already registered"):
            self.call("register-source", data=self.source["record"]["data"])
        updated = copy.deepcopy(self.source["record"]["data"])
        updated["scope"] = "Changed scope"
        self.call("register-source", id=self.source["id"], expected_revision=1, data=updated)
        self.assertEqual(self.e.context()["source_health"][0]["state"], "not_checked")
        self.assertTrue(self.e.public(self.e.store.get(task["id"]))["stale"])
        with self.assertRaisesRegex(Invalid, "Source registration changed"):
            self.check()
        with self.assertRaisesRegex(Invalid, "Source changed"):
            self.call("review-source", data={"check_id": checked["id"], "outcome": "no_relevant_change", "summary": "Wrong"})

    def test_overview_contains_live_board_and_source_freshness(self):
        checked = self.check()
        task = self.waiting_task(checked)
        html = render(self.e).read_text()
        self.assertIn('href="#tasks"', html)
        self.assertIn('href="#sources"', html)
        self.assertIn('"source_health"', html)
        self.assertIn(task["id"], html)
        self.assertIn("needs_review", html)
        self.assertIn("acceptance unknown", self.file.read_text())

    def test_cli_refresh_is_available_in_fresh_process(self):
        cli = Path(__file__).resolve().parents[1] / "scripts" / "personal_os.py"
        run = subprocess.run([sys.executable, str(cli), "--root", str(self.root), "refresh-sources"], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(json.loads(run.stdout)["ok"])
        self.file.unlink()
        failed = subprocess.run([sys.executable, str(cli), "--root", str(self.root), "refresh-sources"], capture_output=True, text=True)
        self.assertEqual(failed.returncode, 2)
        self.assertFalse(json.loads(failed.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
