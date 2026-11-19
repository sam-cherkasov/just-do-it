"""Agent-facing JSON interface; users interact in ordinary conversation."""

import argparse
import json
import sys
from pathlib import Path

from .calendar import window
from .engine import Engine
from .store import Invalid


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent), help="Project root (use a temporary directory for tests)")
    parser.add_argument("operation", choices=("init", "context", "read", "calendar-window", "calendar", "node", "remember", "propose", "commit", "reject", "close", "report", "review", "correct", "feedback", "diary", "summarize-day", "reflect", "view", "register-source", "check-source", "review-source", "refresh-sources", "task", "task-control", "choose-day", "workspace-item", "create-workstream", "create-task", "planner", "workstream", "focus", "links", "link-planner-cards"))
    parser.add_argument("--id")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--kind")
    parser.add_argument("--status")
    parser.add_argument("--period", default="today")
    parser.add_argument("--on", help="Date anchor for reproducible calendar-window tests")
    args = parser.parse_args(argv)
    engine = Engine(args.root)
    try:
        if args.operation == "context":
            result = engine.context(args.start, args.end, args.kind, args.status)
        elif args.operation == "links":
            from .links import projection
            result = projection(engine.store.records())
        elif args.operation == "read":
            result = engine.public(engine.store.get(args.id), args.history)
        elif args.operation == "calendar-window":
            result = window(args.period, engine.store.config()["timezone"], args.on)
        elif args.operation == "view":
            from .view import render
            result = {"ok": True, "path": str(render(engine))}
        elif args.operation == "refresh-sources":
            from .connections import refresh
            result = refresh(engine)
        else:
            payload = json.load(sys.stdin)
            if not isinstance(payload, dict):
                raise Invalid("Request must be a JSON object")
            result = engine.run(args.operation, payload)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if args.operation == "refresh-sources" and not result["ok"] else 0
    except (Invalid, ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error), "retryable": isinstance(error, OSError), "action": "Reload context or correct the request; do not claim it was saved."}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
