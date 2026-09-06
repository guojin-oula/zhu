# -*- coding: utf-8 -*-
"""Start the standalone SS-Screen GUI review build."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

# `src` is the import root, so the package name is `ssscreen`, not
# `src.ssscreen`.
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ssscreen.gui.app import run_gui  # noqa: E402

project_dir = sys.argv[1] if len(sys.argv) > 1 else None
raise SystemExit(run_gui(project_dir=project_dir))
