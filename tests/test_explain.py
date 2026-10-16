"""Explainability tests.

The additivity test is the important one: SHAP must sum to the log-odds the
model actually used, otherwise the dashboard would justify a decision with
reasons that belong to a different model.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.config import FEATURE_COLUMNS, SCORE_FACTOR
from ml.explain import CreditExplainer, format_feature_value, global_group_importance
from ml.features import build_inference_row
from tests.conftest import base_application


@pytest.fixture(scope="module")
def farmer_row(loaded):
    payload = {
        **base_application()["assets"],
        **base_application()["cashflow"],
        **base_application()["credit"],
        **base_application()["applicant"],
    }
    return build_inference_row(payload)


def test_shap_values_sum_to_the_model_margin(loaded, farmer_row) -> None:
    """Base value + SHAP contributions must equal the served decision function."""
    margin = float(loaded.model.predict(farmer_row, output_margin=True)[0])
    grouped_total = float(loaded.explainer.shap_matrix(farmer_row).sum())
    base = float(np.ravel(loaded.explainer.explainer.expected_value)[-1])

    assert base + grouped_total == pytest.approx(margin, abs=1e-4)


def test_shap_matrix_covers_every_feature_column(loaded, farmer_row) -> None:
    values = loaded.explainer.shap_matrix(farmer_row)
    assert values.shape == (1, len(FEATURE_COLUMNS))


def test_grouped_contributions_sum_to_raw_shap(loaded, farmer_row) -> None:
    grouped = loaded.explainer.grouped_contributions(farmer_row)
    raw_total = float(loaded.explainer.shap_matrix(farmer_row).sum())
    assert grouped["contribution_log_odds"].sum() == pytest.approx(raw_total, abs=1e-6)


def test_score_points_use_the_scorecard_sign(loaded, farmer_row) -> None:
    """Points must be ``+FACTOR x contribution``: a protective factor *adds*.

    Getting this sign wrong leaves scores correct but inverts every explanation,
    so the relationship is pinned exactly rather than only checked for direction.
    """
    grouped = loaded.explainer.grouped_contributions(farmer_row)
    assert len(grouped) > 10
    for _, row in grouped.iterrows():
        contribution = float(row["contribution_log_odds"])
        assert int(row["score_points"]) == round(SCORE_FACTOR * contribution)
        expected_direction = "reduces_risk" if contribution >= 0 else "increases_risk"
        assert row["direction"] == expected_direction


def test_explanation_structure_and_ranking(loaded, farmer_row) -> None:
    explanation = loaded.explainer.explain_row(farmer_row, top_n=3)

    assert len(explanation["top_factors"]) == 3
    assert explanation["decision_path"]["factors"], "waterfall factors are missing"
    for factor in explanation["top_factors"]:
        assert factor["label"] and factor["description"] is not None
        assert factor["value"]
        assert factor["direction"] in {"reduces_risk", "increases_risk"}
        assert factor["narrative"]

    magnitudes = [factor["magnitude"] for factor in explanation["decision_path"]["factors"]]
    assert magnitudes == sorted(magnitudes, reverse=True), "factors must be ranked by impact"

    positives = {factor["feature"] for factor in explanation["positive_factors"]}
    negatives = {factor["feature"] for factor in explanation["negative_factors"]}
    assert positives.isdisjoint(negatives)
    assert explanation["summary"].endswith(".")


def test_explanation_rejects_multiple_rows(loaded, farmer_row) -> None:
    """One explanation belongs to one applicant - batch calls must not slip through."""
    two_rows = pd.concat([farmer_row, farmer_row], ignore_index=True)
    with pytest.raises(ValueError):
        loaded.explainer.explain_row(two_rows)


def test_top_factors_track_the_direction_of_the_outcome(loaded) -> None:
    """The weakest file must be dominated by risk-increasing factors."""
    weak = build_inference_row(
        {
            "applicant_category": "farmer",
            "region_tier": "rural",
            "age": 52,
            "dependents": 7,
            "years_in_operation": 2,
            "land_size_acres": 0.6,
            "irrigation_score": 15,
            "land_market_value": 150000,
            "property_value": 40000,
            "equipment_value": 8000,
            "livestock_value": 0,
            "crop_yield_annual_value": 18000,
            "utility_payment_consistency_score": 28,
            "utility_payment_delays_12m": 9,
            "avg_monthly_bank_balance": 1200,
            "annual_income_proxy": 58000,
            "requested_loan_amount": 80000,
            "loan_tenure_months": 24,
            "outstanding_debt": 62000,
            "monthly_emi_obligation": 2600,
        }
    )
    explanation = loaded.explainer.explain_row(weak)
    assert explanation["negative_factors"], "a stressed file must have risk drivers"
    assert explanation["negative_factors"][0]["direction"] == "increases_risk"

    strong = build_inference_row(
        {
            **base_application()["assets"],
            **base_application()["cashflow"],
            **base_application()["credit"],
            **base_application()["applicant"],
        }
    )
    assert float(loaded.model.predict_proba(strong)[0, 1]) > float(
        loaded.model.predict_proba(weak)[0, 1]
    )
    strong_explanation = loaded.explainer.explain_row(strong)
    assert sum(f["score_impact_points"] for f in strong_explanation["positive_factors"]) > 0
    assert strong_explanation["score_impact_total_points"] > explanation["score_impact_total_points"]


def test_global_importance_is_ranked_and_labelled(loaded, portfolio) -> None:
    from ml.features import build_feature_matrix

    ranking = global_group_importance(loaded.explainer, build_feature_matrix(portfolio.head(60)))
    assert not ranking.empty
    assert ranking["mean_abs_log_odds"].is_monotonic_decreasing
    assert ranking["label"].notna().all()


def test_two_explainers_over_the_same_model_agree(loaded) -> None:
    """A second explainer over the same model must reproduce the same values."""
    other = CreditExplainer(loaded.model)
    row = build_inference_row({"requested_loan_amount": 100000, "applicant_category": "farmer"})
    first = loaded.explainer.shap_matrix(row)
    second = other.shap_matrix(row)
    assert np.allclose(first, second)


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (520000, "INR", "₹5.20 L"),
        (12500000, "INR/year", "₹1.25 Cr /year"),
        (2500, "INR/month", "₹2.5 K /month"),
        (0.45, "ratio", "45%"),
        (3.2, "x", "3.20x"),
        (72.4, "score", "72 score"),
        (4.5, "acres", "4.5 acres"),
        (None, "INR", "not on file"),
    ],
)
def test_value_formatting_is_reader_friendly(value, unit, expected) -> None:
    assert format_feature_value(value, unit) == expected


def test_categorical_factors_show_the_declared_level(loaded) -> None:
    """A declared crop/segment must be named, not reported as "not on file".

    The model row stores categoricals as one-hot columns, so the display value
    has to be resolved from the *active* level - reading the group name straight
    off the row yields NaN and silently mislabels the factor.
    """
    row = build_inference_row(
        {
            "applicant_category": "small_business",
            "region_tier": "urban",
            "crop_type": "not_applicable",
            "shop_space_ownership": "owned",
            "requested_loan_amount": 300_000,
            "annual_income_proxy": 400_000,
            "inventory_value": 500_000,
            "utility_payment_consistency_score": 70,
        }
    )
    explanation = loaded.explainer.explain_row(row)
    displayed = {factor["feature"]: factor["value"] for factor in explanation["decision_path"]["factors"]}

    assert displayed["applicant_category"] == "Small Business"
    assert displayed["region_tier"] == "Urban"
    assert displayed["shop_space_ownership"] == "Owned"
    assert displayed["crop_type"] == "Not Applicable"
    assert "not on file" not in displayed["applicant_category"]
