#!/usr/bin/env python3
"""Run from any working directory without installation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from personal_os.cli import main

if __name__ == "__main__":
    sys.exit(main())
