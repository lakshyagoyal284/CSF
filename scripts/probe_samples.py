"""Dev helper: check how candidate demo files score against the live model.

Used while curating the ``/api/sample-applicants`` fixtures so each one lands in
the risk tier it advertises (and stays inside the training distribution).

    python scripts/probe_samples.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.model_registry import get_registry  # noqa: E402
from backend.schemas import ScoreRequest  # noqa: E402
from backend.service import _score_payload  # noqa: E402

CANDIDATES: list[tuple[str, dict]] = [
    (
        "farmer-strong",
        {
            "applicant": {
                "applicant_category": "farmer", "region_tier": "rural", "age": 46,
                "dependents": 3, "years_in_operation": 16, "crop_type": "wheat",
            },
            "assets": {
                "land_size_acres": 4.5, "irrigation_score": 78, "soil_quality_score": 70,
                "crop_yield_annual_value": 236000, "land_market_value": 1450000,
                "property_value": 520000, "equipment_value": 760000, "livestock_value": 180000,
            },
            "cashflow": {
                "monthly_upi_turnover": 62000, "utility_payment_consistency_score": 82,
                "utility_payment_delays_12m": 1, "avg_monthly_bank_balance": 68000,
                "annual_income_proxy": 300000,
            },
            "credit": {
                "requested_loan_amount": 300000, "loan_tenure_months": 36,
                "outstanding_debt": 70000, "monthly_emi_obligation": 2400,
            },
        },
    ),
    (
        "shop-borderline-A",
        {
            "applicant": {
                "applicant_category": "small_business", "region_tier": "semi_urban",
                "age": 34, "dependents": 4, "years_in_operation": 5,
            },
            "assets": {
                "shop_area_sqft": 260, "shop_space_ownership": "rented",
                "inventory_value": 410000, "property_value": 0, "equipment_value": 60000,
            },
            "cashflow": {
                "monthly_upi_turnover": 168000, "utility_payment_consistency_score": 62,
                "utility_payment_delays_12m": 3, "avg_monthly_bank_balance": 22000,
                "annual_income_proxy": 288000,
            },
            "credit": {
                "requested_loan_amount": 260000, "loan_tenure_months": 48,
                "outstanding_debt": 150000, "monthly_emi_obligation": 4400,
            },
        },
    ),
    (
        "shop-borderline-B",
        {
            "applicant": {
                "applicant_category": "small_business", "region_tier": "semi_urban",
                "age": 34, "dependents": 4, "years_in_operation": 5,
            },
            "assets": {
                "shop_area_sqft": 260, "shop_space_ownership": "rented",
                "inventory_value": 410000, "property_value": 0, "equipment_value": 60000,
            },
            "cashflow": {
                "monthly_upi_turnover": 168000, "utility_payment_consistency_score": 70,
                "utility_payment_delays_12m": 2, "avg_monthly_bank_balance": 30000,
                "annual_income_proxy": 300000,
            },
            "credit": {
                "requested_loan_amount": 300000, "loan_tenure_months": 48,
                "outstanding_debt": 120000, "monthly_emi_obligation": 3400,
            },
        },
    ),
    (
        "farmer-stressed-A",
        {
            "applicant": {
                "applicant_category": "farmer", "region_tier": "rural", "age": 52,
                "dependents": 6, "years_in_operation": 3, "crop_type": "pulses",
            },
            "assets": {
                "land_size_acres": 0.8, "irrigation_score": 20, "soil_quality_score": 35,
                "crop_yield_annual_value": 26000, "land_market_value": 210000,
                "property_value": 60000, "equipment_value": 10000, "livestock_value": 20000,
            },
            "cashflow": {
                "monthly_upi_turnover": 5000, "utility_payment_consistency_score": 34,
                "utility_payment_delays_12m": 7, "avg_monthly_bank_balance": 2000,
                "annual_income_proxy": 72000,
            },
            "credit": {
                "requested_loan_amount": 70000, "loan_tenure_months": 36,
                "outstanding_debt": 55000, "monthly_emi_obligation": 2100,
            },
        },
    ),
    (
        "farmer-stressed-B",
        {
            "applicant": {
                "applicant_category": "farmer", "region_tier": "rural", "age": 55,
                "dependents": 7, "years_in_operation": 2, "crop_type": "pulses",
            },
            "assets": {
                "land_size_acres": 0.6, "irrigation_score": 15, "soil_quality_score": 30,
                "crop_yield_annual_value": 18000, "land_market_value": 150000,
                "property_value": 40000, "equipment_value": 8000, "livestock_value": 0,
            },
            "cashflow": {
                "monthly_upi_turnover": 3000, "utility_payment_consistency_score": 28,
                "utility_payment_delays_12m": 9, "avg_monthly_bank_balance": 1200,
                "annual_income_proxy": 58000,
            },
            "credit": {
                "requested_loan_amount": 80000, "loan_tenure_months": 24,
                "outstanding_debt": 62000, "monthly_emi_obligation": 2600,
            },
        },
    ),
]


def main() -> None:
    loaded = get_registry().get()
    print(f"Model: {loaded.version}\n")
    for name, payload in CANDIDATES:
        request = ScoreRequest(**payload)
        scored = _score_payload(request.to_feature_payload(), loaded)
        top = [(f["label"], f["score_impact_points"]) for f in scored["explanation"]["top_factors"]]
        print(
            f"{name:18} score={scored['credit_score']:>3} "
            f"pd={scored['probability_of_default']:.3f} {scored['risk_tier']:6} "
            f"ratio_req/income={payload['credit']['requested_loan_amount'] / payload['cashflow']['annual_income_proxy']:.2f} "
            f"| {top}"
        )


if __name__ == "__main__":
    main()
