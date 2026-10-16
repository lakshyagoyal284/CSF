"""Scorecard scaling and credit policy.

Pure functions, no model and no I/O, which makes the credit policy unit-testable
and easy for a risk team to review.

Pipeline:
    model probability (PD)  ->  score 300-900  ->  risk tier  ->  credit limit
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from ml.config import (
    DECISION_BY_TIER,
    EVIDENCE_GROUPS,
    INTEREST_BY_TIER,
    LIMIT_CEILING,
    LIMIT_FLOOR,
    LIMIT_MULTIPLIER_BY_TIER,
    LIMIT_ROUNDING,
    LTV_BY_CATEGORY,
    LTV_DEFAULT,
    MAX_DEBT_SERVICE_RATIO,
    MINIMUM_COMPLETENESS_FOR_PRE_APPROVAL,
    PD_LOW_RISK_MAX,
    PD_MEDIUM_RISK_MAX,
    SCORE_FACTOR,
    SCORE_MAX,
    SCORE_MIN,
    SCORE_OFFSET,
    TIER_LABELS,
)


# ---------------------------------------------------------------------------
# PD -> score (points-to-double-the-odds scorecard)
# ---------------------------------------------------------------------------


def probability_to_score(probability_of_repayment: float) -> int:
    """Map a repayment probability to the 300-900 credit score band.

    ``score = OFFSET + FACTOR * ln(odds of repayment)``. More repayment odds
    means more score, so the transform is monotone increasing - a higher score
    always means a *safer* borrower. The sign matters: an inverted scale would
    silently approve the worst files, so it is covered by a unit test.
    """
    p = min(max(float(probability_of_repayment), 1e-6), 1 - 1e-6)
    log_odds = math.log(p / (1.0 - p))
    score = SCORE_OFFSET + SCORE_FACTOR * log_odds
    return int(round(min(max(score, SCORE_MIN), SCORE_MAX)))


def score_to_probability(score: float) -> float:
    """Inverse of :func:`probability_to_score` (used by the what-if simulator)."""
    clamped = min(max(float(score), SCORE_MIN), SCORE_MAX)
    log_odds = (clamped - SCORE_OFFSET) / SCORE_FACTOR
    return 1.0 / (1.0 + math.exp(-log_odds))


def score_cutoff_for_default_rate(pd_max_default: float) -> int:
    """Score at or above which a file belongs to the *better* tier.

    Convenience inverse of :func:`probability_to_score` that speaks in PD, the
    language of the credit policy. Passing a PD straight into
    ``probability_to_score`` would silently produce the score of a borrower with
    that *repayment* probability - the floors below would read 369/469 instead
    of 680/580 - so this helper exists to make that mistake impossible.
    """
    return probability_to_score(1.0 - float(pd_max_default))


def risk_tier(pd_default: float) -> str:
    """Bucket a default probability into the underwriting policy tiers."""
    if pd_default <= PD_LOW_RISK_MAX:
        return "LOW"
    if pd_default <= PD_MEDIUM_RISK_MAX:
        return "MEDIUM"
    return "HIGH"


def tier_description(tier: str) -> str:
    return TIER_LABELS.get(tier, "Unknown")


# ---------------------------------------------------------------------------
# Credit limit policy
# ---------------------------------------------------------------------------


def monthly_annuity_factor(annual_rate: float, tenure_months: int) -> float:
    """Monthly instalment per rupee of principal (standard annuity formula)."""
    months = max(int(tenure_months), 1)
    monthly_rate = annual_rate / 12.0
    if monthly_rate <= 0:
        return 1.0 / months
    return monthly_rate / (1.0 - (1.0 + monthly_rate) ** (-months))


def _cap_to_policy(value: float) -> int:
    rounded = int(round(value / LIMIT_ROUNDING) * LIMIT_ROUNDING)
    return max(min(rounded, LIMIT_CEILING), 0)


@dataclass
class CreditPolicyResult:
    """Output of the credit policy engine for a single applicant."""

    recommended_limit: int
    recommended_incremental_limit: int
    collateral_cap: int
    income_cap: int
    binding_constraint: str
    ltv_applied: float
    requested_amount_supported: bool
    indicative_rate_band: dict[str, float]
    debt_coverage_ratio: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "recommended_limit": self.recommended_limit,
            "recommended_incremental_limit": self.recommended_incremental_limit,
            "collateral_cap": self.collateral_cap,
            "income_cap": self.income_cap,
            "binding_constraint": self.binding_constraint,
            "ltv_applied": self.ltv_applied,
            "requested_amount_supported": self.requested_amount_supported,
            "indicative_rate_band": self.indicative_rate_band,
            "debt_coverage_ratio": round(self.debt_coverage_ratio, 3),
        }


def recommend_credit_limit(
    *,
    tier: str,
    applicant_category: str,
    total_collateral_value: float,
    annual_income_proxy: float,
    monthly_emi_obligation: float,
    outstanding_debt: float,
    requested_loan_amount: float,
    tenure_months: int,
) -> CreditPolicyResult:
    """Size a facility from *both* collateral and cash flow, take the tighter.

    Two independent caps are computed and the lower one binds:

    * **Collateral cap** - pledged value x LTV for the segment.
    * **Income cap** - the facility whose annual debt service equals
      ``MAX_DEBT_SERVICE_RATIO`` of the income proxy, priced at the tier's
      indicative rate and amortised over the requested tenure.

    The result is then haircut by the tier multiplier, so a high-risk file can
    still be granted a small *secured* facility instead of an outright decline.
    """
    tier_key = tier if tier in LIMIT_MULTIPLIER_BY_TIER else "HIGH"
    ltv = LTV_BY_CATEGORY.get(applicant_category, LTV_DEFAULT)

    rate_low, rate_high = INTEREST_BY_TIER[tier_key]
    pricing_rate = (rate_low + rate_high) / 2.0 / 100.0

    collateral_cap = max(total_collateral_value, 0.0) * ltv
    annuity = monthly_annuity_factor(pricing_rate, tenure_months)
    annual_income = max(annual_income_proxy, 0.0)
    income_cap = (annual_income * MAX_DEBT_SERVICE_RATIO) / (12.0 * annuity)

    binding = "collateral" if collateral_cap <= income_cap else "income"
    base_cap = min(collateral_cap, income_cap)
    limit = _cap_to_policy(base_cap * LIMIT_MULTIPLIER_BY_TIER[tier_key])

    # A file with a real facility but no collateral/income evidence gets the
    # policy floor rather than zero, so the officer can still see a proposal.
    if limit < LIMIT_FLOOR and base_cap > 0:
        limit = LIMIT_FLOOR

    existing = max(outstanding_debt, 0.0)
    incremental = max(limit - existing, 0)

    annual_debt_service = max(monthly_emi_obligation, 0.0) * 12.0
    debt_coverage = annual_income / annual_debt_service if annual_debt_service > 0 else float("inf")

    return CreditPolicyResult(
        recommended_limit=limit,
        recommended_incremental_limit=int(round(incremental)),
        collateral_cap=_cap_to_policy(collateral_cap),
        income_cap=_cap_to_policy(income_cap),
        binding_constraint=binding,
        ltv_applied=ltv,
        requested_amount_supported=float(requested_loan_amount) <= limit,
        indicative_rate_band={"min_annual_rate": rate_low, "max_annual_rate": rate_high},
        debt_coverage_ratio=debt_coverage,
    )


@dataclass
class DataQualityAssessment:
    """How much of the required evidence an application actually declares."""

    completeness_ratio: float
    satisfied_groups: int
    total_groups: int
    missing_groups: list[list[str]]
    warnings: list[str]
    allows_pre_approval: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "completeness_ratio": round(self.completeness_ratio, 3),
            "satisfied_groups": self.satisfied_groups,
            "total_groups": self.total_groups,
            "missing_evidence": [group[0] for group in self.missing_groups],
            "warnings": self.warnings,
            "allows_pre_approval": self.allows_pre_approval,
        }


def _declared(value: Any) -> bool:
    """A field counts as declared when it is present and not a null-ish value."""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    try:
        import math

        return not math.isnan(float(value))
    except (TypeError, ValueError):
        return True


def assess_data_quality(payload: Mapping[str, Any]) -> DataQualityAssessment:
    """Measure the evidence base behind an application.

    An incomplete file is *not* a safe file. This assessment drives a policy
    overlay: files below the completeness threshold can still be scored, but they
    cannot be pre-approved automatically.
    """
    missing_groups: list[list[str]] = []
    for group in EVIDENCE_GROUPS:
        if not any(_declared(payload.get(field)) for field in group):
            missing_groups.append(list(group))

    total_groups = max(len(EVIDENCE_GROUPS), 1)
    satisfied = total_groups - len(missing_groups)
    completeness = satisfied / total_groups

    warnings: list[str] = []
    if missing_groups:
        warnings.append(
            "Missing evidence: "
            + "; ".join(group[0].replace("_", " ") for group in missing_groups)
            + "."
        )
    if not any(
        _declared(payload.get(field))
        for field in ("annual_income_proxy", "monthly_upi_turnover", "crop_yield_annual_value")
    ):
        warnings.append(
            "No verifiable income or turnover proxy was declared, so repayment capacity "
            "could not be assessed."
        )
    if not any(
        _declared(payload.get(field))
        for field in ("land_market_value", "property_value", "equipment_value", "livestock_value", "inventory_value")
    ):
        warnings.append("No tangible collateral was declared; the facility would be unsecured.")

    return DataQualityAssessment(
        completeness_ratio=completeness,
        satisfied_groups=satisfied,
        total_groups=total_groups,
        missing_groups=missing_groups,
        warnings=warnings,
        allows_pre_approval=completeness >= MINIMUM_COMPLETENESS_FOR_PRE_APPROVAL,
    )


def apply_data_quality_policy(tier: str, quality: DataQualityAssessment) -> str:
    """Cap the tier when the evidence base is too thin to pre-approve.

    Only ever moves a file to a *more* cautious tier - a thin file can never be
    promoted, and a file that is already MEDIUM/HIGH is left alone.
    """
    if not quality.allows_pre_approval and tier == "LOW":
        return "MEDIUM"
    return tier


def policy_summary(
    *,
    pd_default: float,
    ratios: Mapping[str, float],
    applicant_category: str,
    payload: Mapping[str, Any],
    tier: str | None = None,
) -> dict[str, Any]:
    """Convenience wrapper that turns a PD + ratios into the full policy block.

    ``tier`` may be supplied to override the tier implied by the PD (used by the
    data-quality overlay), in which case the limit is sized on the *effective*
    tier so the facility and the decision stay consistent.
    """
    model_tier = risk_tier(pd_default)
    tier = tier or model_tier
    limits = recommend_credit_limit(
        tier=tier,
        applicant_category=applicant_category,
        total_collateral_value=ratios.get("total_collateral_value", 0.0),
        annual_income_proxy=float(payload.get("annual_income_proxy") or 0.0),
        monthly_emi_obligation=float(payload.get("monthly_emi_obligation") or 0.0),
        outstanding_debt=float(payload.get("outstanding_debt") or 0.0),
        requested_loan_amount=float(payload.get("requested_loan_amount") or 0.0),
        tenure_months=int(payload.get("loan_tenure_months") or 36),
    )
    return {
        "risk_tier": tier,
        "tier_label": tier_description(tier),
        "decision": DECISION_BY_TIER[tier],
        "model_risk_tier": model_tier,
        "tier_capped_by_data_quality": tier != model_tier,
        **limits.as_dict(),
    }
