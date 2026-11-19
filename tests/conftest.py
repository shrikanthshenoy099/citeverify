"""
conftest.py – pytest configuration for CiteVerify backend tests.

Adds the backend/ directory to sys.path so that
  ``from citeverify_core...`` and ``from app...`` both work.
"""

import sys
from pathlib import Path

# Insert backend/ at the front of sys.path
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


# ---------------------------------------------------------------------------
# Skip M2 tests when their dependencies (requests, sentence-transformers, …)
# are not installed.  M2 uses a separate venv; this prevents a collection
# error in the shared cv-m4 venv.
# ---------------------------------------------------------------------------
collect_ignore_glob = []
try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    collect_ignore_glob.append("m2/*")
