#!/usr/bin/env python3
"""Launch the saved personal workstream dashboard."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from personal_os.workspace_server import make_server

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
parser.add_argument("--port", type=int, default=8770)
args = parser.parse_args()
server = make_server(args.root, args.port)
print(f"Personal workspace: http://127.0.0.1:{server.server_port}", flush=True)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
