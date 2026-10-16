"""Scorecard and credit-policy tests.

The most important test in this file is :func:`test_score_increases_with_repayment_odds`:
an inverted score scale would silently approve the worst files while looking
perfectly healthy in any other metric, so the direction is pinned explicitly.
"""

from __future__ import annotations

import pytest

from ml.config import (
    LIMIT_CEILING,
    LIMIT_FLOOR,
    LIMIT_ROUNDING,
    MINIMUM_COMPLETENESS_FOR_PRE_APPROVAL,
    PD_LOW_RISK_MAX,
    PD_MEDIUM_RISK_MAX,
    SCORE_MAX,
    SCORE_MIN,
    SCORE_OFFSET,
)
from ml.scoring import (
    apply_data_quality_policy,
    assess_data_quality,
    probability_to_score,
    recommend_credit_limit,
    risk_tier,
    score_cutoff_for_default_rate,
    score_to_probability,
)


def test_score_increases_with_repayment_odds() -> None:
    """Better credit must always mean a higher score."""
    scores = [probability_to_score(p) for p in (0.02, 0.20, 0.50, 0.75, 0.95)]
    assert scores == sorted(scores), f"score scale is not monotone: {scores}"
    assert scores[0] < scores[-1]


def test_score_is_bounded_and_anchored() -> None:
    assert probability_to_score(1e-9) == SCORE_MIN
    assert probability_to_score(1 - 1e-9) == SCORE_MAX
    # The scorecard is anchored on the policy cuts (PD 15% -> 680, PD 35% -> 580),
    # not on PD 50%, so a coin-flip file sits at the offset, below both.
    assert probability_to_score(0.5) == round(SCORE_OFFSET)
    assert SCORE_MIN < probability_to_score(0.5) < 680


def test_score_cutoffs_are_expressed_in_default_probability() -> None:
    """Tier cuts must be stated as PD, not as repayment probability."""
    low_cut = score_cutoff_for_default_rate(PD_LOW_RISK_MAX)
    medium_cut = score_cutoff_for_default_rate(PD_MEDIUM_RISK_MAX)

    assert low_cut == probability_to_score(1.0 - PD_LOW_RISK_MAX)
    assert low_cut == 680
    assert medium_cut == 580
    # The safer tier must have the higher cut-off.
    assert low_cut > medium_cut


def test_score_and_probability_are_inverse() -> None:
    # Only probabilities whose score falls inside the 300-900 window round-trip:
    # the score is clipped at the extremes, so information is intentionally lost
    # there (a 2% default risk and a 0.2% default risk both score 900).
    for probability in (0.12, 0.3, 0.5, 0.8, 0.93):
        score = probability_to_score(probability)
        assert SCORE_MIN < score < SCORE_MAX
        assert score_to_probability(score) == pytest.approx(probability, abs=0.01)


@pytest.mark.parametrize(
    ("pd_default", "expected"),
    [
        (0.01, "LOW"),
        (PD_LOW_RISK_MAX, "LOW"),
        (PD_LOW_RISK_MAX + 0.001, "MEDIUM"),
        (PD_MEDIUM_RISK_MAX, "MEDIUM"),
        (PD_MEDIUM_RISK_MAX + 0.001, "HIGH"),
        (0.95, "HIGH"),
    ],
)
def test_risk_tier_boundaries(pd_default: float, expected: str) -> None:
    assert risk_tier(pd_default) == expected


def test_tier_is_consistent_with_score_bands() -> None:
    """The tier implied by PD must match the tier implied by the score band."""
    for pd_default in (0.02, 0.1, 0.25, 0.34, 0.5, 0.8, 0.95):
        score = probability_to_score(1 - pd_default)
        tier_from_pd = risk_tier(pd_default)
        tier_from_score = (
            "LOW"
            if score >= score_cutoff_for_default_rate(PD_LOW_RISK_MAX)
            else "MEDIUM"
            if score >= score_cutoff_for_default_rate(PD_MEDIUM_RISK_MAX)
            else "HIGH"
        )
        assert tier_from_pd == tier_from_score, f"PD {pd_default} -> score {score}"


class TestCreditLimitPolicy:
    """The facility size must respect both collateral and repayment capacity."""

    def _limit(self, **overrides):
        defaults = dict(
            tier="LOW",
            applicant_category="farmer",
            total_collateral_value=2_000_000.0,
            annual_income_proxy=400_000.0,
            monthly_emi_obligation=2_000.0,
            outstanding_debt=50_000.0,
            requested_loan_amount=300_000.0,
            tenure_months=36,
        )
        defaults.update(overrides)
        return recommend_credit_limit(**defaults)

    def test_tier_haircut_reduces_the_limit(self) -> None:
        low = self._limit(tier="LOW").recommended_limit
        medium = self._limit(tier="MEDIUM").recommended_limit
        high = self._limit(tier="HIGH").recommended_limit
        assert low >= medium >= high

    def test_collateral_cap_binds_when_collateral_is_scarce(self) -> None:
        result = self._limit(total_collateral_value=100_000.0)
        assert result.binding_constraint == "collateral"
        # 55% LTV on 100k leaves a limit well below the income cap.
        assert result.recommended_limit <= 100_000

    def test_income_cap_binds_when_cash_flow_is_weak(self) -> None:
        result = self._limit(annual_income_proxy=50_000.0)
        assert result.binding_constraint == "income"
        assert result.income_cap < result.collateral_cap

    def test_limit_is_rounded_and_within_policy_bounds(self) -> None:
        result = self._limit(
            applicant_category="small_business",
            total_collateral_value=50_000_000.0,
            annual_income_proxy=20_000_000.0,
        )
        assert result.recommended_limit <= LIMIT_CEILING
        assert result.recommended_limit % LIMIT_ROUNDING == 0

    def test_zero_evidence_gets_no_floor_exception(self) -> None:
        """Without any collateral or income there is no case for the floor."""
        result = self._limit(total_collateral_value=0.0, annual_income_proxy=0.0)
        assert result.recommended_limit == 0

    def test_incremental_limit_excludes_existing_debt(self) -> None:
        result = self._limit(outstanding_debt=400_000.0)
        assert (
            result.recommended_incremental_limit
            == max(result.recommended_limit - 400_000, 0)
        )

    def test_requested_amount_support_flag(self) -> None:
        assert self._limit(requested_loan_amount=50_000.0).requested_amount_supported
        assert not self._limit(requested_loan_amount=4_000_000.0).requested_amount_supported

    def test_floor_applies_when_some_capacity_exists(self) -> None:
        result = self._limit(total_collateral_value=60_000.0)
        assert result.recommended_limit >= min(LIMIT_FLOOR, result.collateral_cap)


class TestEvidencePolicy:
    """A file with missing evidence must never be auto-approved.

    This is the guard against the most dangerous failure mode of a tree model on
    tabular declarations: missing values are routed down a learned default
    branch, so an almost-empty application can otherwise look perfectly healthy.
    """

    def test_completeness_counts_evidence_groups(self) -> None:
        complete = {
            "annual_income_proxy": 300_000,
            "land_market_value": 1_000_000,
            "utility_payment_consistency_score": 80,
        }
        quality = assess_data_quality(complete)
        assert quality.completeness_ratio == 1.0
        assert quality.allows_pre_approval is True
        assert quality.warnings == []

    def test_missing_income_is_flagged(self) -> None:
        quality = assess_data_quality({"land_market_value": 500_000})
        assert quality.completeness_ratio < MINIMUM_COMPLETENESS_FOR_PRE_APPROVAL
        assert any("income" in warning.lower() for warning in quality.warnings)

    def test_missing_collateral_is_flagged_as_unsecured(self) -> None:
        quality = assess_data_quality({"annual_income_proxy": 250_000})
        assert any("unsecured" in warning for warning in quality.warnings)

    def test_interchangeable_fields_satisfy_a_group(self) -> None:
        """A shopkeeper's UPI turnover counts as income just like a harvest does."""
        for field, value in (
            ("annual_income_proxy", 200_000),
            ("monthly_upi_turnover", 150_000),
            ("crop_yield_annual_value", 120_000),
        ):
            quality = assess_data_quality({field: value, "inventory_value": 300_000, "avg_monthly_bank_balance": 20_000})
            assert quality.completeness_ratio == 1.0, field

    def test_null_and_blank_values_count_as_missing(self) -> None:
        quality = assess_data_quality({"annual_income_proxy": None, "land_market_value": "", "utility_payment_consistency_score": None})
        assert quality.completeness_ratio == 0.0
        assert quality.allows_pre_approval is False

    def test_overlay_only_ever_downgrades(self) -> None:
        thin = assess_data_quality({"annual_income_proxy": 100_000})
        assert thin.allows_pre_approval is False
        assert apply_data_quality_policy("LOW", thin) == "MEDIUM"
        # Never promoted, and riskier tiers are left alone.
        assert apply_data_quality_policy("HIGH", thin) == "HIGH"

        full = assess_data_quality(
            {
                "annual_income_proxy": 300_000,
                "land_market_value": 900_000,
                "utility_payment_consistency_score": 70,
            }
        )
        assert apply_data_quality_policy("LOW", full) == "LOW"
