"""Desktop GUI frontend for :mod:`ssscreen`.

The GUI is intentionally a thin control layer over the existing Click CLI.  It
never re-implements the scientific algorithms; every run is executed through
``python -m ssscreen.cli.app`` so CLI and GUI share the same validated code
path and file contracts.
"""

from __future__ import annotations


def run_gui(project_dir: str | None = None) -> int:
    """Launch the optional PySide6 desktop application lazily."""
    from .app import run_gui as _run_gui

    return _run_gui(project_dir=project_dir)


__all__ = ["run_gui"]
