#!/usr/bin/env python3
"""Check an existing Codex proxy without launching or resuming chats."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from personal_os.agent_status import probe
from personal_os.engine import Engine
from personal_os.links import projection

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
parser.add_argument("--socket", help="Explicit documented app-server control socket, if configured")
args = parser.parse_args()
chats = projection(Engine(args.root).store.records())["chats"]
refs = [{k: chat[k] for k in ("provider", "host_id", "thread_id")} for chat in chats]
result = probe(args.root, refs, args.socket)
print(json.dumps(result, ensure_ascii=False, indent=2))
sys.exit(0 if result["state"] == "snapshot" else 2)
