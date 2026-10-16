"""Feature engineering tests: the frozen contract and the derived ratios."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.config import ENGINEERED_FEATURES, FEATURE_COLUMNS, RAW_NUMERIC_FEATURES
from ml.features import (
    build_feature_matrix,
    build_inference_row,
    engineer_features,
    summarise_inputs,
)
from tests.conftest import base_application


def test_feature_columns_are_unique_and_complete() -> None:
    assert len(FEATURE_COLUMNS) == len(set(FEATURE_COLUMNS)), "duplicate feature column"
    for column in (*RAW_NUMERIC_FEATURES, *ENGINEERED_FEATURES):
        assert column in FEATURE_COLUMNS
    assert not any(column == "repaid_on_time" for column in FEATURE_COLUMNS)


def test_matrix_has_frozen_column_order(portfolio: pd.DataFrame) -> None:
    matrix = build_feature_matrix(portfolio.head(25))
    assert list(matrix.columns) == list(FEATURE_COLUMNS)
    assert matrix.shape[0] == 25
    assert matrix.select_dtypes(include=[np.number]).shape[1] == len(FEATURE_COLUMNS)


def test_engineered_ratios_are_mathematically_correct() -> None:
    frame = pd.DataFrame(
        [
            {
                "requested_loan_amount": 100_000,
                "outstanding_debt": 50_000,
                "monthly_emi_obligation": 2_000,
                "annual_income_proxy": 240_000,
                "avg_monthly_bank_balance": 20_000,
                "land_market_value": 300_000,
                "property_value": 100_000,
                "equipment_value": 0,
                "livestock_value": 0,
                "inventory_value": 0,
                "loan_tenure_months": 36,
                "utility_payment_consistency_score": 80,
                "utility_payment_delays_12m": 0,
            }
        ]
    )
    ratios = engineer_features(frame).iloc[0]

    assert ratios["total_collateral_value"] == 400_000
    assert ratios["collateral_coverage_ratio"] == pytest.approx(4.0)
    assert ratios["debt_to_asset_ratio"] == pytest.approx(0.125)
    assert ratios["debt_service_ratio"] == pytest.approx(2_000 / 20_000)
    assert ratios["liquidity_ratio"] == pytest.approx(10.0)
    assert ratios["income_to_debt_ratio"] == pytest.approx(4.8)
    assert ratios["net_worth"] == 350_000
    assert ratios["asset_productivity"] == pytest.approx(0.6)
    # 0.7 * 80 + 0.3 * (100 - 0) = 86
    assert ratios["financial_discipline_score"] == pytest.approx(86.0)


def test_affordability_ratios_track_the_requested_facility() -> None:
    """Doubling the ask must worsen affordability - the model's top driver."""
    base = base_application()
    smaller = build_inference_row({**base["assets"], **base["cashflow"], **base["credit"]})
    bigger = build_inference_row(
        {
            **base["assets"],
            **base["cashflow"],
            **{**base["credit"], "requested_loan_amount": base["credit"]["requested_loan_amount"] * 2},
        }
    )
    assert (
        bigger.iloc[0]["proposed_debt_service_ratio"]
        > smaller.iloc[0]["proposed_debt_service_ratio"]
    )
    assert (
        bigger.iloc[0]["post_facility_loan_to_value"]
        > smaller.iloc[0]["post_facility_loan_to_value"]
    )
    assert bigger.iloc[0]["collateral_coverage_ratio"] < smaller.iloc[0]["collateral_coverage_ratio"]


def test_zero_and_missing_denominators_never_produce_infinities() -> None:
    frame = pd.DataFrame(
        [
            {
                "requested_loan_amount": 0,
                "outstanding_debt": 0,
                "monthly_emi_obligation": 0,
                "annual_income_proxy": 0,
                "avg_monthly_bank_balance": 0,
            }
        ]
    )
    ratios = engineer_features(frame).iloc[0]
    for column in ENGINEERED_FEATURES:
        value = ratios[column]
        assert not np.isinf(value), f"{column} produced an infinity"
    # A zero denominator means "unknown", which the model reads as missing.
    assert np.isnan(ratios["liquidity_ratio"])


def test_inference_row_ignores_unknown_keys_and_maps_blanks_to_nan() -> None:
    row = build_inference_row(
        {
            "applicant_category": "farmer",
            "region_tier": "rural",
            "land_size_acres": None,
            "property_value": "",
            "irrigation_score": 55,
            "requested_loan_amount": 100_000,
            "something_unknown": "ignored",
        }
    )
    assert list(row.columns) == list(FEATURE_COLUMNS)
    assert np.isnan(row.iloc[0]["land_size_acres"])
    assert np.isnan(row.iloc[0]["property_value"])
    assert row.iloc[0]["irrigation_score"] == 55


def test_unknown_category_values_fall_back_to_not_applicable() -> None:
    row = build_inference_row(
        {"applicant_category": "farmer", "shop_space_ownership": "squatted", "loan_tenure_months": 24}
    )
    assert row.iloc[0]["shop_space_ownership__not_applicable"] == 1.0
    assert row.iloc[0]["shop_space_ownership__owned"] == 0.0


def test_missing_categorical_columns_still_one_hot_encode() -> None:
    """A partial payload must still produce the full, correctly ordered matrix."""
    row = build_inference_row({"requested_loan_amount": 50_000})
    assert list(row.columns) == list(FEATURE_COLUMNS)
    assert row.shape == (1, len(FEATURE_COLUMNS))
    # No category supplied means "not applicable" is the active level.
    assert row.iloc[0]["shop_space_ownership__not_applicable"] == 1.0
    assert row.iloc[0]["crop_type__not_applicable"] == 1.0
    assert row.iloc[0]["applicant_category__farmer"] == 0.0


def test_summarise_inputs_returns_all_engineered_ratios() -> None:
    payload = {
        **base_application()["assets"],
        **base_application()["cashflow"],
        **base_application()["credit"],
        "applicant_category": "farmer",
    }
    summary = summarise_inputs(payload)
    assert set(summary) == set(ENGINEERED_FEATURES)
    assert all(isinstance(value, float) for value in summary.values())
