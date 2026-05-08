"""
Deployment entry point.

Adds the repo root to sys.path so that `from backend.X` imports inside
api/main.py resolve correctly, then re-exports the FastAPI app.

Procfile still runs `uvicorn main:app` — `app` is now the substantive
api.main app, with /staff, /payments, etc.
"""
import sys
from pathlib import Path

# Add the repo root (parent of backend/) to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.api.main import app  # noqa: E402

__all__ = ["app"]