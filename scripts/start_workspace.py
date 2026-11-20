#!/usr/bin/env python3
"""Open a personal workspace with browser-based first-run setup."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from personal_os.workspace_server import make_server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.home() / "PersonalOS",
                        help="Data directory; defaults to ~/PersonalOS, outside the application")
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args()
    try:
        server = make_server(args.root, args.port, allow_setup=True)
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(f"Открой http://127.0.0.1:{server.server_port}\nДанные: {args.root.resolve()}\nДля остановки: Ctrl+C", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
