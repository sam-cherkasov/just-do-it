#!/usr/bin/env python3
"""Start a disposable fictional workspace without reading personal data."""
import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from personal_os.engine import Engine
from personal_os.workspace_server import make_server


def prepare(root, timezone="UTC"):
    root = Path(root)
    if root.is_symlink() or (root.exists() and any(root.iterdir())):
        raise ValueError("Demo needs a new empty directory; existing data is never overwritten")
    engine = Engine(root)
    engine.init({"calendar_account": "demo@example.test", "timezone": timezone, "synthetic": True})
    source = {"kind": "synthetic", "reference": "Fictional public demo; no connected accounts or real chats"}
    def run(op, key, data, **extra):
        return engine.run(op, {"request_id": key, "source": source, "data": data, **extra})
    area = run("node", "demo-area", {"type": "area", "title": "Creative work", "mode": "growth", "parents": []})
    task = run("task", "demo-task", {"title": "Prepare one useful tutorial", "parents": [area["id"]],
        "intent": "proposed", "status": "ready", "priority": "unranked", "sources": [],
        "rationale": "Fictional example for exploring the workspace", "next_action": "Choose one question to explain"})
    stream = run("workstream", "demo-stream", {"title": "Learning project", "summary": "A fictional project for the demo",
        "outcome": "A useful tutorial draft", "context": "All records in this workspace are fictional.", "color": "lilac",
        "task_ids": [task["id"]], "source_ids": [], "sources": [], "chats": [], "questions": []})
    session = run("focus", "demo-session", {"task_id": task["id"], "task_revision": 1,
        "workstream_id": stream["id"], "target": "Draft one clear example", "minutes": 45})
    run("focus", "demo-outcome", {"status": "closed", "outcome": "progress", "note": "Outlined the example; the ending needs another pass.",
        "next_action": "Write the final paragraph and check the example"}, id=session["id"], expected_revision=1)
    run("workspace-item", "demo-thought", {"category": "note", "title": "Try a shorter example later", "body": "An idea can wait without changing the current focus."})
    run("workspace-item", "demo-question", {"category": "question", "title": "Which example explains the idea best?",
        "task_id": task["id"], "condition": "Choose one example and explain why", "body": "This is a saved question, not an agent approval request."})
    day = datetime.now(ZoneInfo(timezone)).date()
    monday = day - timedelta(days=day.weekday())
    board = run("planner", "demo-board", {"title": "Example week", "week_start": monday.isoformat(), "timezone": timezone,
        "availability": {}, "cards": [{"id": "tutorial", "project": "Learning project", "title": "Tutorial draft",
            "outcome": "One clear example", "first_action": "Write the final paragraph", "minutes": 45,
            "estimate_basis": "Fictional estimate", "selected": False, "placement": None, "note": "",
            "task_id": task["id"], "task_revision": 1, "workstream_id": stream["id"]}]})
    return {"synthetic": True, "root": str(root.resolve()), "task_id": task["id"], "planner_id": board["id"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="New empty demo directory; default is a temporary directory")
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument("--port", type=int, default=8771)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    try:
        result = prepare(args.root or tempfile.mkdtemp(prefix="personal-os-workspace-demo-"), args.timezone)
        print(json.dumps(result), flush=True)
        if args.prepare_only:
            return 0
        server = make_server(result["root"], args.port)
        print("Fictional demo: http://127.0.0.1:" + str(server.server_port), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
