import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from personal_os.calendar import normalize, window
from personal_os.engine import Engine
from personal_os.store import Invalid, decode, now
from personal_os.view import render
from tests.scenario import Scenario


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "personal_os.py"


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.s = Scenario(self.root)
        self.e = self.s.engine

    def test_full_loop_survives_new_process_and_ignores_absence(self):
        plan_id = self.s.populate()
        output = subprocess.check_output([sys.executable, str(CLI), "--root", str(self.root), "context"], text=True)
        context = json.loads(output)
        plan = next(r for r in context["records"] if r["id"] == plan_id)
        self.assertEqual(plan["data"]["agreed"]["capacity"][self.s.first], 15)
        self.assertEqual(plan["data"]["agreed"]["actions"][1]["date"], None)
        self.assertFalse(any(r["kind"] in ("diary", "reflection") for r in context["records"]))
        review = next(r for r in context["records"] if r["kind"] == "review")
        self.assertIn(self.s.second, review["data"]["missing_days"])
        self.assertEqual({f["status"] for f in review["data"]["findings"]}, {"partial", "not_done"})
        self.assertEqual(context["feedback_pending"], 1)

    def test_draft_rejection_and_stale_acceptance(self):
        agreed = self.s.agree()
        proposed = self.s.call("propose", id=agreed["id"], expected_revision=2, data=self.s.replan())
        self.assertEqual(proposed["record"]["data"]["agreed"], self.s.plan)
        with self.assertRaises(Invalid):
            self.s.call("commit", id=agreed["id"], expected_revision=2, agreement="Yes")
        rejected = self.s.call("reject", id=agreed["id"], expected_revision=3)
        self.assertEqual(rejected["record"]["data"]["agreed"], self.s.plan)
        self.assertIsNone(rejected["record"]["data"]["proposal"])

    def test_capacity_and_rest_cannot_be_silently_consumed(self):
        overloaded = copy.deepcopy(self.s.plan)
        overloaded["actions"][0]["minutes"] = 61
        with self.assertRaisesRegex(Invalid, "exceeds capacity"):
            self.s.call("propose", data=overloaded)
        protected = copy.deepcopy(self.s.plan)
        protected["actions"][0]["date"] = self.s.rest[0]
        with self.assertRaises(Invalid):
            self.s.call("propose", data=protected)
        agreed = self.s.agree()
        unprotect = copy.deepcopy(self.s.plan)
        unprotect["protected_days"] = []
        with self.assertRaisesRegex(Invalid, "rest_change_reason"):
            self.s.call("propose", id=agreed["id"], expected_revision=2, data=unprotect)

    def test_unreported_action_is_unknown(self):
        agreed = self.s.agree()
        review = self.s.call("review", plan_id=agreed["id"], start=self.s.first, end=self.s.last)
        self.assertEqual([f["status"] for f in review["record"]["data"]["findings"]], ["unknown", "unknown"])

    def test_verbatim_diary_corrections_late_notes_and_summary_regeneration(self):
        text = '  My exact words.\r\n\n---\n"quote" and </script> ☀️\r\n\n'
        note = self.s.call("diary", data={"event_date": self.s.first, "text": text})
        self.assertEqual(decode(self.root / note["record"]["_path"])["data"]["text"], text)
        summary = self.s.call("summarize-day", date=self.s.first)
        self.assertFalse(summary["record"]["stale"])
        self.s.call("diary", data={"event_date": self.s.first, "text": "A late addition."})
        self.assertTrue(self.e.stale(self.e.store.get(summary["id"])))
        regenerated = self.s.call("summarize-day", date=self.s.first, id=summary["id"], expected_revision=1)
        self.assertFalse(regenerated["record"]["stale"])
        changed = self.s.call("correct", id=note["id"], expected_revision=1, reason="User correction", data={"event_date": self.s.first, "text": "Corrected words."})
        self.assertEqual(self.e.store.get(note["id"])["history"][0]["data"]["text"], text)
        self.assertTrue(self.e.stale(self.e.store.get(summary["id"])))
        self.assertEqual(changed["record"]["data"]["text"], "Corrected words.")
        with self.assertRaisesRegex(Invalid, "No diary notes"):
            self.s.call("summarize-day", date=self.s.second)

    def test_correct_event_date_updates_retrieval_and_staleness(self):
        note = self.s.call("diary", data={"event_date": self.s.first, "text": "This happened yesterday."})
        summary = self.s.call("summarize-day", date=self.s.first)
        self.s.call("correct", id=note["id"], expected_revision=1, reason="Correct the reported date", data={"event_date": self.s.second, "text": "This happened yesterday."})
        self.assertTrue(self.e.stale(self.e.store.get(summary["id"])))
        self.assertEqual(len(self.e.evidence(self.s.second, self.s.second)), 1)
        self.assertEqual(self.e.store.get(note["id"])["_path"], note["record"]["_path"])

    def test_reflection_requires_original_sources_and_qualified_interpretation(self):
        note = self.s.call("diary", data={"event_date": self.s.first, "text": "I felt hopeful after a conversation."})
        sources = self.e.refs(self.e.evidence(self.s.first, self.s.second))
        result = self.s.call("reflect", start=self.s.first, end=self.s.second, sources=sources, text="One reported experience; the next day is unknown.", interpretations=[])
        self.assertIn(self.s.second, result["record"]["data"]["missing_days"])
        with self.assertRaises(Invalid):
            self.s.call("reflect", start=self.s.first, end=self.s.second, sources=[], text="Unsourced")
        with self.assertRaises(Invalid):
            self.s.call("reflect", start=self.s.first, end=self.s.second, sources=sources, text="Test", interpretations=[{"text": "Permanent trait", "status": "fact", "support": [note["id"]]}])

    def test_report_correction_invalidates_review_and_rejected_memory_is_not_startup_truth(self):
        plan = self.s.agree()
        report = self.s.call("report", data={"plan_id": plan["id"], "action_id": "draft", "event_date": self.s.first, "text": "Drafted", "status": "completed", "contribution": "output"})
        review = self.s.call("review", plan_id=plan["id"], start=self.s.first, end=self.s.last)
        memory = self.s.call("remember", data={"text": "Maybe avoidance", "evidence_kind": "hypothesis", "scope": "This report only", "event_date": self.s.first, "sources": [{"id": report["id"], "revision": 1}]})
        changed = copy.deepcopy(report["record"]["data"])
        changed.update(status="partial", contribution="intermediate", text="Only an outline")
        self.s.call("correct", id=report["id"], expected_revision=1, reason="User clarification", data=changed)
        self.assertTrue(self.e.stale(self.e.store.get(review["id"])))
        self.assertTrue(self.e.stale(self.e.store.get(memory["id"])))
        rejected = copy.deepcopy(memory["record"]["data"])
        rejected.update(status="rejected", sources=[{"id": report["id"], "revision": 2}])
        self.s.call("correct", id=memory["id"], expected_revision=1, reason="User rejects this interpretation", data=rejected)
        self.assertNotIn(memory["id"], [r["id"] for r in self.e.context()["records"]])

    def test_feedback_preserves_capture_and_triage_history(self):
        feedback = self.s.call("feedback", data={"text": "Too much detail"})
        selected = self.s.call("feedback", id=feedback["id"], expected_revision=1, status="selected")
        self.assertEqual(selected["record"]["data"]["text"], "Too much detail")
        self.assertEqual(self.e.store.get(feedback["id"])["history"][0]["data"]["status"], "new")
        self.assertEqual(len(self.e.context(kind="feedback", status="selected")["records"]), 1)

    def test_retry_idempotency_collision_and_concurrent_retry(self):
        payload = {"request_id": "retry", "source": {"kind": "synthetic", "reference": "Test"}, "data": {"event_date": self.s.first, "text": "Once only"}}
        first = self.e.run("diary", payload)
        self.assertTrue(self.e.run("diary", payload)["replayed"])
        edited = copy.deepcopy(payload)
        edited["data"]["text"] = "Different"
        with self.assertRaisesRegex(Invalid, "different input"):
            self.e.run("diary", edited)
        payload["request_id"] = "concurrent"
        processes = [subprocess.Popen([sys.executable, str(CLI), "--root", str(self.root), "diary"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        outputs = [p.communicate(json.dumps(payload)) for p in processes]
        self.assertTrue(all(p.returncode == 0 for p in processes))
        self.assertEqual(sum(json.loads(out[0])["replayed"] for out in outputs), 1)
        self.assertEqual(len(self.e.context(kind="diary")["records"]), 2)
        self.assertEqual(first["revision"], 1)

    def test_atomic_failure_does_not_claim_write_and_retry_works(self):
        count = len(self.e.store.records())
        payload = {"request_id": "failed", "source": {"kind": "synthetic", "reference": "Test"}, "data": {"text": "A note", "event_date": self.s.first}}
        with patch("personal_os.store.os.replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                self.e.run("diary", payload)
        self.assertEqual(len(self.e.store.records()), count)
        self.assertFalse(self.e.run("diary", payload)["replayed"])
        self.assertFalse(list(self.root.rglob(".pending-*")))

    def test_calendar_dst_pagination_identity_and_all_day(self):
        span = window("next week", "Europe/Madrid", "2026-10-21")
        self.assertTrue(span["time_min"].endswith("+01:00"))
        span = window("this week", "Europe/Madrid", "2026-10-21")
        self.assertTrue(span["time_min"].endswith("+02:00"))
        self.assertTrue(span["time_max"].endswith("+01:00"))
        data = self.s.calendar_data()
        data["events"] = [{"id": "rest", "summary": "Rest", "start": {"date": self.s.rest[0]}, "end": {"date": self.s.last}, "transparency": "transparent"}, {"status": "cancelled"}]
        normalized = normalize(data, self.e.store.config())
        self.assertTrue(normalized["events"][0]["all_day"])
        self.assertFalse(normalized["events"][0]["busy"])
        data["next_page_token"] = "more"
        with self.assertRaisesRegex(Invalid, "all calendar pages"):
            normalize(data, self.e.store.config())
        data.pop("next_page_token")
        data["account"] = "someone-else@example.test"
        with self.assertRaises(Invalid):
            normalize(data, self.e.store.config())

    def test_stale_failed_and_partial_calendar_does_not_claim_live_readiness(self):
        data = self.s.calendar_data()
        data["fetched_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        calendar_id = self.s.call("calendar", data=data)["id"]
        plan = copy.deepcopy(self.s.plan)
        plan["calendar_id"] = calendar_id
        with self.assertRaisesRegex(Invalid, "older than"):
            self.s.call("propose", data=plan)
        data.update(mode="unavailable", complete=False, events=[], fetched_at=now(), note="Connector denied")
        failure = self.s.call("calendar", data=data)
        plan["calendar_id"] = failure["id"]
        with self.assertRaisesRegex(Invalid, "manual_fallback_reason"):
            self.s.call("propose", data=plan)
        plan["manual_fallback_reason"] = "User explicitly chose a limited manual plan"
        saved = self.s.call("propose", data=plan)
        self.assertIn("manual_fallback_reason", saved["record"]["data"]["proposal"])

    def test_live_root_rejects_fixture_and_generated_agreement(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(directory)
            engine.init({"calendar_account": "synthetic@example.test"})
            with self.assertRaises(Invalid):
                engine.run("calendar", {"request_id": "fixture", "source": {"kind": "calendar", "reference": "Fake"}, "data": self.s.calendar_data()})
        draft = self.s.call("propose", data=self.s.plan)
        with self.assertRaisesRegex(Invalid, "user source"):
            self.e.run("commit", {"request_id": "model-assent", "id": draft["id"], "expected_revision": 1, "agreement": "Model thinks yes", "source": {"kind": "agent_generated", "reference": "Model"}})

    def test_second_active_cycle_requires_closure(self):
        first = self.s.agree()
        second = self.s.call("propose", data=self.s.plan)
        with self.assertRaisesRegex(Invalid, "Close the previous"):
            self.s.call("commit", id=second["id"], expected_revision=1, agreement="Yes")
        self.s.call("close", id=first["id"], expected_revision=2, reason="Cycle reviewed and closed")
        self.assertTrue(self.s.call("commit", id=second["id"], expected_revision=1, agreement="Yes")["ok"])

    def test_next_cycle_cites_current_review(self):
        agreed = self.s.agree()
        self.s.call("close", id=agreed["id"], expected_revision=2, reason="End of fictional cycle")
        review = self.s.call("review", plan_id=agreed["id"], start=self.s.first, end=self.s.last,
                             learning="There is no activity evidence yet; do not claim success.")
        next_plan = copy.deepcopy(self.s.plan)
        next_plan["learning_sources"] = [{"id": review["id"], "revision": 1}]
        next_plan["title"] = "Next cycle from saved review"
        proposed = self.s.call("propose", data=next_plan)
        self.assertEqual(proposed["record"]["data"]["proposal"]["learning_sources"][0]["id"], review["id"])

    def test_cli_error_receipt_and_full_calendar_span(self):
        process = subprocess.run([sys.executable, str(CLI), "--root", str(self.root), "diary"],
                                 input='{"request_id":"bad"}', capture_output=True, text=True)
        self.assertEqual(process.returncode, 2)
        self.assertFalse(json.loads(process.stderr)["ok"])
        plan = copy.deepcopy(self.s.plan)
        plan["end"] = (datetime.fromisoformat(self.s.last).date() + timedelta(days=1)).isoformat()
        with self.assertRaisesRegex(Invalid, "whole plan"):
            self.s.call("propose", data=plan)

    def test_visual_escape_links_and_no_external_resources(self):
        self.s.populate()
        attack = '</script><img src=x onerror="alert(1)">'
        self.s.call("diary", data={"event_date": self.s.first, "text": attack})
        path = render(self.e)
        html = path.read_text()
        self.assertNotIn(attack, html)
        self.assertIn("\\u003c/script>", html)
        self.assertNotIn("src=\"http", html)
        self.assertNotIn("innerHTML", html)
        self.assertIn("Synthetic demonstration", html)
        self.assertIn("source-list", html)

    def test_node_cycle_and_symlink_storage_rejected(self):
        outcome = self.e.store.get(self.s.outcome)
        changed = copy.deepcopy(outcome["data"])
        changed["parents"] = [self.s.outcome]
        with self.assertRaises(Invalid):
            self.s.call("correct", id=self.s.outcome, expected_revision=1, reason="Invalid parent", data=changed)
        with tempfile.TemporaryDirectory() as other:
            diary = self.root / "personal" / "diary"
            diary.symlink_to(other)
            with self.assertRaisesRegex(Invalid, "Storage path|Symlink"):
                self.s.call("diary", data={"text": "No escape", "event_date": self.s.first})

    def test_targeted_synthetic_git_checkpoint_and_restore(self):
        self.s.populate()
        render(self.e)
        (self.root / ".gitignore").write_text(".local/\n.env\ncredentials*.json\n")
        (self.root / ".env").write_text("TOKEN=synthetic-placeholder\n")
        def git(*args):
            return subprocess.check_output(["git", "-C", str(self.root), *args], text=True, stderr=subprocess.STDOUT)
        git("init", "-q")
        git("add", "personal", ".gitignore")
        git("-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-qm", "Checkpoint synthetic progression")
        tracked = git("ls-files")
        self.assertNotIn(".local/", tracked)
        self.assertNotIn(".env", tracked)
        note = self.e.context(kind="diary")["records"][0]
        path = self.root / note["_path"]
        before = path.read_bytes()
        changed = copy.deepcopy(note["data"])
        changed["text"] = "A corrected synthetic note"
        self.s.call("correct", id=note["id"], expected_revision=1, reason="Test correction", data=changed)
        diff = git("diff", "--", note["_path"])
        self.assertIn("A corrected synthetic note", diff)
        git("restore", "--", note["_path"])
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
