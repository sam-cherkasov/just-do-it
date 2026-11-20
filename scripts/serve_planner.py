#!/usr/bin/env python3
"""Open the saved manual planning experiment locally."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from personal_os.planner_server import make_server

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--id", required=True)
    parser.add_argument("--port", type=int, default=8769)
    args = parser.parse_args()
    server = make_server(args.root, args.id, args.port)
    print(f"Planner: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
