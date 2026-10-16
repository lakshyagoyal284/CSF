"""Shared test fixtures.

The suite trains a small model once per session into a temporary directory and
points the API at it, so tests never touch (or depend on) the repository's
``artifacts/`` folder and can run before ``train_model.py`` has ever been
executed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.data_generator import generate_synthetic_portfolio  # noqa: E402
from ml.train import save_artifacts, train_model  # noqa: E402

#: Small but still learnable portfolio - keeps the whole suite to a few seconds.
TEST_ROWS = 900
TEST_SEED = 11


@pytest.fixture(scope="session")
def portfolio():
    """A reproducible synthetic portfolio shared by the whole session."""
    data, _report = generate_synthetic_portfolio(n_records=TEST_ROWS, seed=TEST_SEED)
    return data


@pytest.fixture(scope="session")
def model_path(tmp_path_factory) -> Path:
    """Train a throwaway model artifact and return its path."""
    directory = tmp_path_factory.mktemp("artifacts")
    data, report = generate_synthetic_portfolio(n_records=TEST_ROWS, seed=TEST_SEED)
    # Train exactly like production (including the grouped SHAP ranking) so the
    # fixture artifact has the same shape as the one the API serves.
    result = train_model(data, seed=TEST_SEED, compute_shap_importance=True)
    path = directory / "credit_model.pkl"
    save_artifacts(
        result,
        portfolio=data,
        data_report=report.as_dict(),
        model_path=path,
        metrics_path=directory / "training_metrics.json",
        importance_path=directory / "feature_importance.csv",
    )
    return path


@pytest.fixture(scope="session")
def loaded(model_path):
    """A loaded model bundle bound to the throwaway artifact."""
    from backend.model_registry import ModelRegistry

    return ModelRegistry(model_path).get()


@pytest.fixture(scope="session")
def client(model_path):
    """FastAPI test client wired to the throwaway model."""
    os.environ["ACS_MODEL_PATH"] = str(model_path)
    os.environ.pop("ACS_DATABASE_URL", None)

    from backend.config import get_settings
    from backend.model_registry import reset_registry

    get_settings.cache_clear()
    reset_registry()

    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as test_client:
        yield test_client


def base_application() -> dict:
    """A valid farmer application used as the starting point for API tests."""
    return {
        "applicant": {
            "full_name": "Test Farmer",
            "applicant_category": "farmer",
            "region_tier": "rural",
            "age": 46,
            "dependents": 3,
            "years_in_operation": 16,
            "crop_type": "wheat",
        },
        "assets": {
            "land_size_acres": 4.5,
            "irrigation_score": 78,
            "soil_quality_score": 70,
            "crop_yield_annual_value": 236000,
            "land_market_value": 1450000,
            "property_value": 520000,
            "equipment_value": 760000,
            "livestock_value": 180000,
        },
        "cashflow": {
            "monthly_upi_turnover": 62000,
            "utility_payment_consistency_score": 82,
            "utility_payment_delays_12m": 1,
            "avg_monthly_bank_balance": 68000,
            "annual_income_proxy": 300000,
        },
        "credit": {
            "requested_loan_amount": 300000,
            "loan_tenure_months": 36,
            "outstanding_debt": 70000,
            "monthly_emi_obligation": 2400,
        },
    }


@pytest.fixture
def application() -> dict:
    return base_application()
