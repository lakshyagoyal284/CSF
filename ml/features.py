"""Feature engineering for the alternative credit scoring engine.

Two responsibilities:

* :func:`engineer_features` - turn *declared* facts (land, inventory, UPI
  turnover, debt) into the financial **ratios** a credit model actually needs.
* :func:`build_feature_matrix` / :func:`build_inference_row` - place every
  feature in the exact column order defined by :data:`ml.config.FEATURE_COLUMNS`
  so that offline training and online inference can never drift apart.

The module is deliberately pure pandas/numpy: it is imported by the training
script, the FastAPI service and the tests.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from ml.config import (
    CATEGORY_LEVELS,
    COLUMN_TO_GROUP,
    ENGINEERED_FEATURES,
    FEATURE_COLUMNS,
    PROPOSED_FACILITY_ANNUAL_RATE,
    RAW_CATEGORICAL_FEATURES,
    RAW_NUMERIC_FEATURES,
)
from ml.scoring import monthly_annuity_factor

#: Guards against divide-by-zero and against a single outlier (a 40x coverage
#: ratio, say) dominating a tree split. Ratios are statistically derived, so
#: clipping them preserves rank order while keeping the model well conditioned.
_RATIO_CAPS: dict[str, float] = {
    "collateral_coverage_ratio": 20.0,
    "debt_to_asset_ratio": 10.0,
    "debt_service_ratio": 10.0,
    "proposed_debt_service_ratio": 10.0,
    "post_facility_loan_to_value": 10.0,
    "liquidity_ratio": 50.0,
    "income_to_debt_ratio": 20.0,
    "asset_productivity": 10.0,
}

#: Fields that default to 0 when absent (a shopkeeper simply owns no tractor).
_ZERO_DEFAULT_ASSETS: tuple[str, ...] = (
    "land_market_value",
    "property_value",
    "equipment_value",
    "livestock_value",
    "inventory_value",
)


def _safe_divide(numerator: pd.Series, denominator: pd.Series, cap: float) -> pd.Series:
    """Divide two series, treating a non-positive denominator as missing."""
    denom = denominator.where(denominator > 0, np.nan)
    ratio = numerator / denom
    # ``np.inf`` can still appear if the numerator is NaN-free and denom is tiny.
    return ratio.replace([np.inf, -np.inf], np.nan).clip(lower=0.0, upper=cap)


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Derive the ratio features consumed by the model.

    Args:
        df: Frame containing (at least) the raw numeric feature columns.
            Missing columns are treated as ``NaN``.

    Returns:
        A new frame with the raw columns plus :data:`ENGINEERED_FEATURES`.
        The input frame is never mutated.
    """
    out = df.copy()

    for column in RAW_NUMERIC_FEATURES:
        if column not in out.columns:
            out[column] = np.nan
        out[column] = pd.to_numeric(out[column], errors="coerce")

    # --- tangible collateral --------------------------------------------------
    asset_parts: list[pd.Series] = []
    for column in _ZERO_DEFAULT_ASSETS:
        asset_parts.append(out[column].fillna(0.0))
    total_collateral = pd.concat(asset_parts, axis=1).sum(axis=1)

    requested = out["requested_loan_amount"]
    outstanding = out["outstanding_debt"].fillna(0.0)
    annual_income = out["annual_income_proxy"].fillna(0.0)
    monthly_income = annual_income / 12.0
    monthly_emi = out["monthly_emi_obligation"].fillna(0.0)

    out["total_collateral_value"] = total_collateral
    out["collateral_coverage_ratio"] = _safe_divide(
        total_collateral, requested, _RATIO_CAPS["collateral_coverage_ratio"]
    )
    out["debt_to_asset_ratio"] = _safe_divide(
        outstanding, total_collateral, _RATIO_CAPS["debt_to_asset_ratio"]
    )
    out["debt_service_ratio"] = _safe_divide(
        monthly_emi, monthly_income, _RATIO_CAPS["debt_service_ratio"]
    )

    # --- affordability of the *requested* facility ---------------------------
    # A credit decision is about the new facility, not just the existing book:
    # scoring only the current EMI would let an unaffordable ask look safe. The
    # instalment is priced at the fixed policy rate so training and serving
    # compute it identically.
    tenure = out["loan_tenure_months"].fillna(36.0).clip(lower=1.0, upper=360.0)
    annual_rate = pd.Series(PROPOSED_FACILITY_ANNUAL_RATE, index=out.index)
    annuity = np.vectorize(monthly_annuity_factor)(annual_rate.to_numpy(), tenure.to_numpy(dtype=int))
    proposed_instalment = requested.fillna(0.0) * annuity
    out["proposed_instalment"] = proposed_instalment
    out["proposed_debt_service_ratio"] = _safe_divide(
        monthly_emi + proposed_instalment,
        monthly_income,
        _RATIO_CAPS["proposed_debt_service_ratio"],
    )
    out["post_facility_loan_to_value"] = _safe_divide(
        outstanding + requested.fillna(0.0),
        total_collateral,
        _RATIO_CAPS["post_facility_loan_to_value"],
    )
    out["liquidity_ratio"] = _safe_divide(
        out["avg_monthly_bank_balance"].fillna(0.0),
        monthly_emi,
        _RATIO_CAPS["liquidity_ratio"],
    )
    out["income_to_debt_ratio"] = _safe_divide(
        annual_income, outstanding, _RATIO_CAPS["income_to_debt_ratio"]
    )
    out["net_worth"] = total_collateral - outstanding
    out["asset_productivity"] = _safe_divide(
        annual_income, total_collateral, _RATIO_CAPS["asset_productivity"]
    )

    # --- payment discipline blend (utility score + delay count) --------------
    utility_score = out["utility_payment_consistency_score"].fillna(
        out["utility_payment_consistency_score"].median()
    )
    delays = out["utility_payment_delays_12m"].fillna(0.0)
    delay_penalty_component = (100.0 - 9.0 * delays).clip(lower=0.0, upper=100.0)
    out["financial_discipline_score"] = (
        0.7 * utility_score + 0.3 * delay_penalty_component
    ).clip(lower=0.0, upper=100.0)

    return out


def _normalise_categories(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce categorical columns to lowercase levels, mapping junk to NA."""
    out = pd.DataFrame(index=df.index)
    for feature in RAW_CATEGORICAL_FEATURES:
        levels = set(CATEGORY_LEVELS[feature])
        if feature in df.columns:
            series = df[feature].astype("string").str.strip().str.lower()
        else:
            series = pd.Series(pd.NA, index=df.index, dtype="string")
        out[feature] = series.where(series.isin(levels), "not_applicable").astype(object)
    return out


def build_feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Return a model-ready matrix with the frozen :data:`FEATURE_COLUMNS` order.

    Args:
        df: Raw applicant records (one row per applicant).

    Returns:
        A float frame containing raw numerics, engineered ratios and one-hot
        encoded categoricals. Column order is guaranteed by the feature
        contract, which is what makes the pickled model safely reusable.
    """
    engineered = engineer_features(df)

    numeric = engineered.loc[:, list(RAW_NUMERIC_FEATURES)].astype("float64")
    for column in ENGINEERED_FEATURES:
        numeric[column] = engineered[column].astype("float64")

    categories = _normalise_categories(df)
    one_hot = pd.DataFrame(
        {
            f"{feature}__{level}": (categories[feature] == level).astype("float64")
            for feature, levels in CATEGORY_LEVELS.items()
            for level in levels
        },
        index=df.index,
    )

    matrix = pd.concat([numeric, one_hot], axis=1)
    return matrix.loc[:, list(FEATURE_COLUMNS)]


def build_inference_row(payload: Mapping[str, Any]) -> pd.DataFrame:
    """Build a one-row feature matrix from an API JSON payload.

    Unknown keys are ignored; missing numeric keys become ``NaN``. This mirrors
    :func:`build_feature_matrix` exactly because it delegates to it.
    """
    row: dict[str, Any] = {}
    for column in RAW_NUMERIC_FEATURES:
        value = payload.get(column)
        row[column] = np.nan if value is None or value == "" else value
    for feature in RAW_CATEGORICAL_FEATURES:
        row[feature] = payload.get(feature)
    return build_feature_matrix(pd.DataFrame([row]))


def feature_groups_for(column: str) -> str:
    """Return the human-facing group a raw model column belongs to."""
    return COLUMN_TO_GROUP.get(column, column)


def summarise_inputs(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the headline financial ratios for display / audit purposes.

    Used by the API to return the computed ratios alongside the score so a loan
    officer can sanity-check the model without opening the model itself.
    """
    row = build_inference_row(payload)
    keys: Sequence[str] = ENGINEERED_FEATURES
    return {key: float(row.iloc[0][key]) for key in keys}
