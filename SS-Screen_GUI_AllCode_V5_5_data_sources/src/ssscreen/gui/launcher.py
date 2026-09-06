"""Friendly console launcher for the optional desktop GUI."""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="ss-screen-gui", description="Launch SS-Screen GUI")
    parser.add_argument("project_dir", nargs="?", help="Initial SS-Screen project directory")
    args = parser.parse_args()
    try:
        from .app import run_gui

        return run_gui(project_dir=args.project_dir)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
