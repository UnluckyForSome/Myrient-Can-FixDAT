#!/usr/bin/env python3
"""
Minerva Can FixDAT — launcher.

Forwards to ``minerva.app.bootstrap.main()``.
"""

from __future__ import annotations

import sys as _sys

# ── Quick venv check ──────────────────────────────────────────────
try:
    import superqt  # noqa: F401
except ImportError:
    print(
        "Minerva requires the project virtual environment.\n"
        "Run:  ./minerva.sh\n"
        "Or:   source .venv/bin/activate && python minerva_gui.py",
        file=_sys.stderr,
    )
    _sys.exit(1)


def main() -> int:
    """Forward to the production entry point."""
    from minerva.app.bootstrap import main as _bootstrap_main

    return _bootstrap_main()


if __name__ == "__main__":
    _sys.exit(main())
