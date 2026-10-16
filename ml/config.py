"""Central configuration for the Alternative Credit Scoring Engine.

This module is the single source of truth for:

1. The **feature contract** - the exact ordered list of model input columns.
   Training and online inference both build their matrices through
   :mod:`ml.features`, so a mismatch here is a hard failure rather than a
   silent prediction drift.
2. The **scorecard scaling** that maps a default probability to a 300-900 score.
3. The **credit policy** thresholds used to derive risk tiers and loan limits.

Nothing in this file imports heavy libraries, so it is safe to import from
scripts, the API, unit tests and notebooks alike.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# 1. FEATURE CONTRACT
# ---------------------------------------------------------------------------

#: Raw numeric inputs supplied by the loan officer (or the bank core system).
#: ``NaN`` is meaningful: it means "not applicable for this applicant type"
#: (e.g. ``land_size_acres`` is NaN for a shopkeeper). XGBoost handles missing
#: values natively by learning a default split direction.
RAW_NUMERIC_FEATURES: tuple[str, ...] = (
    # --- borrower demographics -------------------------------------------------
    "age",
    "dependents",
    "years_in_operation",
    # --- farming collateral ----------------------------------------------------
    "land_size_acres",
    "irrigation_score",
    "soil_quality_score",
    "crop_yield_annual_value",
    "land_market_value",
    "property_value",
    "equipment_value",
    "livestock_value",
    # --- small-business collateral --------------------------------------------
    "shop_area_sqft",
    "inventory_value",
    # --- alternative cash-flow proxies ----------------------------------------
    "monthly_upi_turnover",
    "utility_payment_consistency_score",
    "utility_payment_delays_12m",
    "avg_monthly_bank_balance",
    "annual_income_proxy",
    # --- requested / existing credit ------------------------------------------
    "outstanding_debt",
    "monthly_emi_obligation",
    "requested_loan_amount",
    "loan_tenure_months",
)

#: Raw categorical inputs. Unknown / not-applicable values are mapped to the
#: ``not_applicable`` level, which is itself an explicit one-hot column.
RAW_CATEGORICAL_FEATURES: tuple[str, ...] = (
    "applicant_category",      # farmer | small_business
    "region_tier",             # rural | semi_urban | urban
    "shop_space_ownership",    # owned | rented | not_applicable
    "crop_type",               # rice | wheat | cotton | sugarcane | horticulture | pulses | not_applicable
)

#: Explicit category levels. Order defines the one-hot column order, so never
#: reorder without retraining.
CATEGORY_LEVELS: dict[str, tuple[str, ...]] = {
    "applicant_category": ("farmer", "small_business"),
    "region_tier": ("rural", "semi_urban", "urban"),
    "shop_space_ownership": ("owned", "rented", "not_applicable"),
    "crop_type": (
        "rice",
        "wheat",
        "cotton",
        "sugarcane",
        "horticulture",
        "pulses",
        "not_applicable",
    ),
}

#: Features derived by :func:`ml.features.engineer_features`. These are what
#: turn raw declarations into financial ratios the model can reason about.
#: Pricing rate used to compute the instalment of the *requested* facility when
#: deriving affordability ratios. Fixed (rather than per-tier) so that training
#: and online scoring compute an identical feature, and so the affordability
#: ratio cannot leak the policy's own tier-dependent pricing back into the model.
PROPOSED_FACILITY_ANNUAL_RATE: float = 0.14

ENGINEERED_FEATURES: tuple[str, ...] = (
    "total_collateral_value",
    "collateral_coverage_ratio",
    "debt_to_asset_ratio",
    "debt_service_ratio",
    "proposed_instalment",
    "proposed_debt_service_ratio",
    "post_facility_loan_to_value",
    "liquidity_ratio",
    "income_to_debt_ratio",
    "net_worth",
    "asset_productivity",
    "financial_discipline_score",
)


def _one_hot_columns() -> tuple[str, ...]:
    """Deterministic one-hot column names (``<feature>__<level>``)."""
    return tuple(
        f"{feature}__{level}"
        for feature, levels in CATEGORY_LEVELS.items()
        for level in levels
    )


#: The final, ordered model input contract. Anything the model consumes must
#: appear here, in this order.
FEATURE_COLUMNS: tuple[str, ...] = (
    RAW_NUMERIC_FEATURES + ENGINEERED_FEATURES + _one_hot_columns()
)

# ---------------------------------------------------------------------------
# 2. SCORECARD SCALING (PD -> 300-900)
# ---------------------------------------------------------------------------
# We use the classical "points to double the odds" scorecard transform:
#
#     score = OFFSET - FACTOR * ln(odds)      where odds = PD / (1 - PD)
#
# The two anchors were chosen so the score bands line up with the credit policy
# cut-offs below:
#
#     PD = 0.15  ->  score 680   (below this PD the file is auto-pre-approved)
#     PD = 0.35  ->  score 580   (above this PD the file is high risk)
#
# Solving both anchors simultaneously gives FACTOR = 89.64 (a "points to double
# the odds" of ~62, in the same ballpark as bureau scorecards) and
# OFFSET = 524.5. Scores are clipped to the 300-900 window.

SCORE_MIN: int = 300
SCORE_MAX: int = 900
SCORE_OFFSET: float = 524.5
SCORE_FACTOR: float = 89.64

#: Policy cut-offs used to derive the risk tier from PD. Because the PD ->
#: score transform is monotone, these are equivalent to the score bands
#: ``>= 680`` (low), ``580-679`` (medium) and ``< 580`` (high).
PD_LOW_RISK_MAX: float = 0.15
PD_MEDIUM_RISK_MAX: float = 0.35

# ---------------------------------------------------------------------------
# 3. CREDIT POLICY
# ---------------------------------------------------------------------------

#: Loan-to-value applied to pledged tangible collateral, per borrower segment.
LTV_BY_CATEGORY: dict[str, float] = {
    "farmer": 0.55,
    "small_business": 0.65,
}
LTV_DEFAULT: float = 0.55

#: Share of the annual income proxy that may be committed to debt service.
MAX_DEBT_SERVICE_RATIO: float = 0.30

#: Haircut applied to the income/collateral caps per risk tier.
LIMIT_MULTIPLIER_BY_TIER: dict[str, float] = {
    "LOW": 1.00,
    "MEDIUM": 0.65,
    "HIGH": 0.25,
}

#: Evidence an application must contain before it can be *pre-approved*.
#: Alternative-data scoring is only as good as the declarations behind it: a
#: file with no verifiable income and no collateral is not "low risk", it is
#: *unknown*. The model's missing-value handling cannot express that (XGBoost
#: routes missing values down a learned default branch, which for a farmer looks
#: like a typical, decent file), so the policy layer enforces it instead.
CRITICAL_EVIDENCE_FIELDS: tuple[str, ...] = (
    "annual_income_proxy",
    "monthly_upi_turnover",
    "crop_yield_annual_value",
    "avg_monthly_bank_balance",
    "utility_payment_consistency_score",
    "land_market_value",
    "property_value",
    "equipment_value",
    "livestock_value",
    "inventory_value",
)

#: Each entry is a group of interchangeable fields; a group counts as satisfied
#: when at least one member is declared. This stops a farmer from being failed
#: for lacking a shop inventory and vice versa.
EVIDENCE_GROUPS: tuple[tuple[str, ...], ...] = (
    ("annual_income_proxy", "monthly_upi_turnover", "crop_yield_annual_value"),
    ("land_market_value", "property_value", "equipment_value", "livestock_value", "inventory_value"),
    ("utility_payment_consistency_score", "avg_monthly_bank_balance"),
)

#: Share of the evidence groups that must be declared before automated approval
#: is allowed. Set to 1.0 deliberately: a file missing *any* of income,
#: collateral or payment-behaviour evidence is referred to a human instead of
#: being auto-approved, which is the industry norm for straight-through rural
#: lending. The score is untouched - only the ability to auto-approve is lost.
MINIMUM_COMPLETENESS_FOR_PRE_APPROVAL: float = 1.0

#: Indicative pricing bands (annualised %) surfaced to the loan officer.
INTEREST_BY_TIER: dict[str, tuple[float, float]] = {
    "LOW": (9.5, 11.5),
    "MEDIUM": (12.5, 15.5),
    "HIGH": (16.0, 21.0),
}

LIMIT_FLOOR: int = 25_000          # INR
LIMIT_CEILING: int = 5_000_000     # INR
LIMIT_ROUNDING: int = 5_000        # round sanctioned limits to the nearest 5k

#: Human-readable underwriting decisions attached to each tier.
DECISION_BY_TIER: dict[str, str] = {
    "LOW": "PRE_APPROVED",
    "MEDIUM": "MANUAL_REVIEW",
    "HIGH": "DECLINE_OR_SECURED_ONLY",
}

TIER_LABELS: dict[str, str] = {
    "LOW": "Pre-Approved",
    "MEDIUM": "Manual Review",
    "HIGH": "High Risk",
}

# ---------------------------------------------------------------------------
# 4. HUMAN-READABLE FEATURE METADATA (drives SHAP explanations + the UI)
# ---------------------------------------------------------------------------
# SHAP values are computed per one-hot column, but a loan officer thinks in
# terms of concepts ("Debt-to-Asset Ratio"), so every column is mapped to a
# *group*. Contributions of the columns inside a group are summed.

FEATURE_GROUPS: dict[str, dict[str, Any]] = {
    # --- demographics ---------------------------------------------------------
    "age": {
        "label": "Applicant Age",
        "description": "Borrower age in years at application.",
        "unit": "years",
    },
    "dependents": {
        "label": "Household Dependents",
        "description": "Number of financially dependent family members.",
        "unit": "people",
    },
    "years_in_operation": {
        "label": "Years in Operation",
        "description": "Track record of the farm or shop; a proxy for stability.",
        "unit": "years",
    },
    # --- farming collateral ---------------------------------------------------
    "land_size_acres": {
        "label": "Land Holding",
        "description": "Cultivable land owned or leased.",
        "unit": "acres",
    },
    "irrigation_score": {
        "label": "Irrigation Quality",
        "description": "Irrigation dependability score (0-100) from the field survey.",
        "unit": "score",
    },
    "soil_quality_score": {
        "label": "Soil Quality",
        "description": "Soil fertility/quality score (0-100) from the field survey.",
        "unit": "score",
    },
    "crop_yield_annual_value": {
        "label": "Annual Crop Yield Value",
        "description": "Market value of the last 12 months of harvest.",
        "unit": "INR/year",
    },
    "land_market_value": {
        "label": "Land Market Value",
        "description": "Circle-rate based market value of the land parcel.",
        "unit": "INR",
    },
    "property_value": {
        "label": "Property Value",
        "description": "Market value of owned buildings (house or shop premises).",
        "unit": "INR",
    },
    "equipment_value": {
        "label": "Equipment & Machinery",
        "description": "Present value of tractors, pumps, harvesters and tools.",
        "unit": "INR",
    },
    "livestock_value": {
        "label": "Livestock Value",
        "description": "Present value of cattle, goats and poultry.",
        "unit": "INR",
    },
    # --- small-business collateral -------------------------------------------
    "shop_area_sqft": {
        "label": "Shop Premises Area",
        "description": "Trading area of the shop or workshop.",
        "unit": "sq ft",
    },
    "inventory_value": {
        "label": "Inventory Value",
        "description": "Market value of saleable stock on hand.",
        "unit": "INR",
    },
    # --- alternative cash-flow proxies ---------------------------------------
    "monthly_upi_turnover": {
        "label": "Monthly UPI Turnover",
        "description": "Average monthly digital collection volume from the UPI ledger.",
        "unit": "INR/month",
    },
    "utility_payment_consistency_score": {
        "label": "Utility Payment Consistency",
        "description": "On-time payment score (0-100) across electricity/water bills.",
        "unit": "score",
    },
    "utility_payment_delays_12m": {
        "label": "Utility Payment Delays",
        "description": "Number of late utility payments in the trailing 12 months.",
        "unit": "delays",
    },
    "avg_monthly_bank_balance": {
        "label": "Average Bank Balance",
        "description": "Trailing 6-month average balance across bank/UPI accounts.",
        "unit": "INR",
    },
    "annual_income_proxy": {
        "label": "Annual Income Proxy",
        "description": "Verifiable annual income reconstructed from crop sales or UPI margin.",
        "unit": "INR/year",
    },
    # --- credit ---------------------------------------------------------------
    "outstanding_debt": {
        "label": "Outstanding Debt",
        "description": "Total live borrowings across formal and informal lenders.",
        "unit": "INR",
    },
    "monthly_emi_obligation": {
        "label": "Monthly EMI Obligation",
        "description": "Current monthly repayment burden.",
        "unit": "INR/month",
    },
    "requested_loan_amount": {
        "label": "Requested Loan Amount",
        "description": "Facility size requested by the applicant.",
        "unit": "INR",
    },
    "loan_tenure_months": {
        "label": "Requested Tenure",
        "description": "Requested repayment period.",
        "unit": "months",
    },
    # --- engineered -----------------------------------------------------------
    "total_collateral_value": {
        "label": "Total Pledged Collateral",
        "description": "Land + property + equipment + livestock + inventory at market value.",
        "unit": "INR",
    },
    "collateral_coverage_ratio": {
        "label": "Collateral Coverage",
        "description": "Pledged collateral value divided by the requested facility.",
        "unit": "x",
    },
    "debt_to_asset_ratio": {
        "label": "Debt-to-Asset Ratio",
        "description": "Existing borrowings as a share of tangible asset value.",
        "unit": "ratio",
    },
    "debt_service_ratio": {
        "label": "Debt Service Ratio",
        "description": "Existing monthly EMI obligation as a share of monthly income proxy.",
        "unit": "ratio",
    },
    "proposed_instalment": {
        "label": "Proposed Instalment",
        "description": "Indicative monthly instalment for the requested facility at the policy rate.",
        "unit": "INR/month",
    },
    "proposed_debt_service_ratio": {
        "label": "Proposed Debt Service",
        "description": "Existing EMIs plus the new instalment, as a share of monthly income proxy (affordability).",
        "unit": "ratio",
    },
    "post_facility_loan_to_value": {
        "label": "Post-Facility Leverage",
        "description": "Existing debt plus the requested facility, divided by pledged collateral value.",
        "unit": "ratio",
    },
    "liquidity_ratio": {
        "label": "Liquidity Buffer",
        "description": "Average bank balance divided by the monthly EMI obligation.",
        "unit": "x",
    },
    "income_to_debt_ratio": {
        "label": "Income-to-Debt Ratio",
        "description": "Annual income proxy divided by outstanding debt.",
        "unit": "x",
    },
    "net_worth": {
        "label": "Net Worth",
        "description": "Tangible assets minus outstanding borrowings.",
        "unit": "INR",
    },
    "asset_productivity": {
        "label": "Asset Productivity",
        "description": "Annual income generated per rupee of assets (earning efficiency).",
        "unit": "x",
    },
    "financial_discipline_score": {
        "label": "Financial Discipline",
        "description": "Blend of utility payment consistency and delay history (0-100).",
        "unit": "score",
    },
    # --- categorical (one-hot) ------------------------------------------------
    "applicant_category": {
        "label": "Borrower Segment",
        "description": "Whether the applicant is a farmer or a small-business owner.",
        "unit": None,
    },
    "region_tier": {
        "label": "Region Tier",
        "description": "Rural / semi-urban / urban location of the enterprise.",
        "unit": None,
    },
    "shop_space_ownership": {
        "label": "Shop Ownership",
        "description": "Whether the trading premises are owned or rented.",
        "unit": None,
    },
    "crop_type": {
        "label": "Primary Crop",
        "description": "Dominant crop cultivated (farmers only).",
        "unit": None,
    },
}

#: Maps every model column to a display group in :data:`FEATURE_GROUPS`.
COLUMN_TO_GROUP: dict[str, str] = {col: col for col in RAW_NUMERIC_FEATURES}
COLUMN_TO_GROUP.update({col: col for col in ENGINEERED_FEATURES})
for _feature, _levels in CATEGORY_LEVELS.items():
    for _level in _levels:
        COLUMN_TO_GROUP[f"{_feature}__{_level}"] = _feature

#: Columns rendered on the "waterfall" chart, ordered by explainability value.
GROUP_ORDER: tuple[str, ...] = tuple(FEATURE_GROUPS.keys())

CATEGORY_DISPLAY_NAMES: dict[str, str] = {
    "farmer": "Farmer",
    "small_business": "Small Business",
    "rural": "Rural",
    "semi_urban": "Semi-Urban",
    "urban": "Urban",
    "owned": "Owned",
    "rented": "Rented",
    "not_applicable": "Not Applicable",
    "rice": "Rice",
    "wheat": "Wheat",
    "cotton": "Cotton",
    "sugarcane": "Sugarcane",
    "horticulture": "Horticulture",
    "pulses": "Pulses",
}

#: Lightweight regex-free guard used by the API layer for category validation.
VALID_CATEGORY_VALUES: dict[str, set[str]] = {
    feature: set(levels) for feature, levels in CATEGORY_LEVELS.items()
}

# ---------------------------------------------------------------------------
# 5. FILE LOCATIONS
# ---------------------------------------------------------------------------

DEFAULT_MODEL_PATH = "artifacts/credit_model.pkl"
DEFAULT_DATASET_PATH = "data/synthetic_portfolio.csv"
DEFAULT_METRICS_PATH = "artifacts/training_metrics.json"
DEFAULT_IMPORTANCE_PATH = "artifacts/feature_importance.csv"
