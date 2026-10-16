#!/usr/bin/env python
"""``main.py`` - root ASGI entry point.

The application is implemented in :mod:`backend.main` (routes, lifespan, CORS)
with the scoring logic in :mod:`backend.service` and the model in :mod:`ml`.
This module re-exports it so the conventional invocation works:

    uvicorn main:app --reload --port 8000

Equivalent to ``uvicorn backend.main:app``. Interactive docs: /docs
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `uvicorn main:app` from any working directory.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.main import app  # noqa: E402  (import must follow the sys.path fix)

__all__ = ["app"]

if __name__ == "__main__":  # pragma: no cover - convenience runner
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
