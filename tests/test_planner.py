import copy
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from personal_os.engine import Engine
from personal_os.planner_server import make_server
from personal_os.store import Invalid


def fixture():
    return {"title": "Fictional week", "week_start": "2026-11-02", "timezone": "Europe/Madrid",
            "availability": {"2026-11-06": {"level": "limited", "note": "Fictional travel"}},
            "cards": [{"id": "example", "title": "Fictional draft", "project": "Other",
                       "outcome": "A draft", "first_action": "Open a blank file", "minutes": 60,
                       "estimate_basis": "Fictional estimate", "selected": False, "placement": None, "note": ""}]}


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine = Engine(self.root)
        self.engine.init({"calendar_account": "fiction@example.test", "synthetic": True})
        self.source = {"kind": "synthetic", "reference": "Isolated planner test"}
        self.created = self.engine.run("planner", {"request_id": "seed", "source": self.source, "data": fixture()})

    def payload(self):
        return {"request_id": "move", "source": self.source, "id": self.created["id"], "expected_revision": 1, "data": fixture()}

    def test_roundtrip_move_history_retry_and_conflict(self):
        p = self.payload()
        p["data"]["cards"][0].update(selected=True, placement={"date": "2026-11-03", "start_minute": 600}, note="Fictional reason")
        moved = self.engine.run("planner", p)
        fresh = Engine(self.root).store.get(moved["id"])
        self.assertEqual(fresh["data"]["cards"][0]["placement"]["start_minute"], 600)
        self.assertEqual(fresh["data"]["changes"][-1]["reason"], "Fictional reason")
        self.assertTrue(self.engine.run("planner", p)["replayed"])
        p["request_id"] = "stale"
        with self.assertRaisesRegex(Invalid, "Stale revision"):
            self.engine.run("planner", p)
        self.assertEqual([r["kind"] for r in self.engine.store.records()], ["planner"])

    def test_invalid_placement_does_not_write(self):
        for placement in ({"date": "2026-11-09", "start_minute": 600},
                          {"date": "2026-11-03", "start_minute": 1410},
                          {"date": "2026-11-03", "start_minute": 601}):
            p = self.payload()
            p["data"]["cards"][0].update(selected=True, placement=placement)
            with self.assertRaises(Invalid):
                self.engine.run("planner", p)
        self.assertEqual(self.engine.store.get(self.created["id"])["revision"], 1)

    def test_unschedule_and_unselect_preserve_task(self):
        p = self.payload()
        p["data"]["cards"][0].update(selected=True, placement={"date": "2026-11-02", "start_minute": None})
        self.engine.run("planner", p)
        p.update(request_id="return", expected_revision=2)
        p["data"]["cards"][0].update(selected=False, placement=None)
        saved = self.engine.run("planner", p)["record"]
        self.assertEqual(len(saved["data"]["cards"]), 1)
        self.assertFalse(saved["data"]["cards"][0]["selected"])
        self.assertEqual(len(saved["history"]) if "history" in saved else saved["revision"] - 1, 2)

    def test_bad_url_and_forged_history(self):
        p = self.payload()
        p["data"]["cards"][0]["chat_url"] = "javascript:alert(1)"
        with self.assertRaises(Invalid):
            self.engine.run("planner", p)
        p["data"]["cards"][0]["chat_url"] = ""
        p["data"]["changes"] = [{"title": "Forged action"}]
        self.assertEqual(self.engine.run("planner", p)["record"]["data"]["changes"], [])

    def test_http_save_requires_local_origin_token_and_revision(self):
        server = make_server(self.root, self.created["id"], 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        origin = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(origin + "/api/board") as response:
            boot = json.load(response)
        payload = self.payload()
        payload["data"]["cards"][0]["selected"] = True
        def send(headers):
            request = urllib.request.Request(origin + "/api/board", data=json.dumps(payload).encode(),
                                             headers={"Content-Type": "application/json", **headers})
            return urllib.request.urlopen(request)
        with self.assertRaises(urllib.error.HTTPError) as error:
            send({"Origin": "http://untrusted.test", "X-Planner-Token": boot["token"]})
        self.assertEqual(error.exception.code, 403)
        headers = {"Origin": origin, "X-Planner-Token": boot["token"]}
        with send(headers) as response:
            self.assertEqual(json.load(response)["record"]["revision"], 2)
        payload["request_id"] = "stale-other-tab"
        with self.assertRaises(urllib.error.HTTPError) as error:
            send(headers)
        self.assertEqual(error.exception.code, 409)
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(origin + "/personal/config.json")
        self.assertEqual(error.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
