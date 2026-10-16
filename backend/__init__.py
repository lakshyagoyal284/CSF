"""FastAPI service for the alternative credit scoring engine.

Modules
-------
``backend.config``          Runtime settings (model path, database URL, CORS).
``backend.schemas``         Request/response contracts (the API is the interface).
``backend.model_registry``  Loads and caches the trained model bundle.
``backend.service``         Business logic: score, explain, simulate.
``backend.db``              Optional PostgreSQL persistence of assessments.
``backend.main``            HTTP routes and app wiring.
"""

from __future__ import annotations

__all__ = ["config", "schemas", "model_registry", "service", "db", "main"]
