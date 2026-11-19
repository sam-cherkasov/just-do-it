#!/usr/bin/env python3
"""Build a clearly synthetic visual walkthrough in a new temporary directory."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from personal_os.view import render
from personal_os.connections import refresh
from tests.scenario import Scenario


def main():
    root = Path(tempfile.mkdtemp(prefix="personal-os-demo-")).resolve()
    scenario = Scenario(root)
    scenario.populate()
    project = root / "fictional-project.md"
    project.write_text("Fictional client: proposal sent; waiting for a reply. Acceptance and payment unknown.\n")
    source = scenario.call("register-source", data={"title": "Fictional client project", "source_type": "file",
                           "locator": str(project), "scope": "Synthetic current status"})
    check = refresh(scenario.engine)["checks"][0]
    task = scenario.call("task", data={"title": "Fictional proposal — awaiting reply", "parents": [scenario.outcome],
                         "intent": "reported", "status": "waiting", "priority": "primary",
                         "rationale": "A potential opportunity, not confirmed income", "waiting_on": "Fictional client reply",
                         "sources": [{"id": check["check_id"], "revision": 1}]})
    scenario.call("review-source", data={"check_id": check["check_id"], "outcome": "reconciled",
                  "summary": "Saved the fictional waiting status without assuming acceptance.",
                  "records": [{"id": task["id"], "revision": 1}]})
    scenario.call("task", data={"title": "Test the next useful offer", "parents": [scenario.outcome],
                  "intent": "proposed", "status": "candidate", "priority": "primary",
                  "rationale": "Reduce uncertainty while another opportunity waits",
                  "next_action": "Read the fictional project and choose one question to test."})
    scenario.call("register-source", data={"title": "Fictional consultation chat", "source_type": "chat",
                  "locator": "fictional-consultation-thread", "scope": "Connector retrieval has not been performed"})
    path = render(scenario.engine)
    print(json.dumps({"synthetic": True, "root": str(root), "view": str(path)}, indent=2))


if __name__ == "__main__":
    main()
