"""Synthetic portfolio generator for the alternative credit scoring prototype.

Why synthetic data?
-------------------
There is no public dataset of Indian rural/MSME loan applications that carries
*asset declarations* (land, machinery, inventory) and *alternative cash-flow
proxies* (UPI ledgers, utility payment history) together with a repayment
outcome. For a prototype we therefore simulate a portfolio that behaves like a
real one.

The key design rule: **the label is not random**. We first sample borrower,
asset and cash-flow attributes from segment-specific distributions, then push
those attributes through a transparent latent creditworthiness function to get a
"true" default probability, and only then sample the observed
``repaid_on_time`` outcome. That makes the dataset (a) learnable, (b) auditable
and (c) tunable - we can dial the portfolio's base default rate with a single
parameter.

Everything is seeded, so the dataset is reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ml.config import FEATURE_COLUMNS  # noqa: F401  (documents the contract)
from ml.features import engineer_features

# ---------------------------------------------------------------------------
# Tunable portfolio parameters
# ---------------------------------------------------------------------------

DEFAULT_N_RECORDS: int = 12_000
DEFAULT_SEED: int = 42
DEFAULT_REPAYMENT_RATE: float = 0.78     # share of loans repaid on time
LABEL_NOISE_RATE: float = 0.015          # irreducible real-world label noise
FARMER_SHARE: float = 0.55

#: Agronomic and credit profile per crop. ``yield_per_acre`` is the gross market
#: value of a normal harvest in INR; ``income_volatility`` scales the harvest
#: noise (sugarcane is contracted and stable, horticulture is not).
CROP_PROFILES: dict[str, dict[str, float]] = {
    "rice": {"weight": 0.28, "yield_per_acre": 46_000, "income_volatility": 0.22},
    "wheat": {"weight": 0.22, "yield_per_acre": 41_000, "income_volatility": 0.20},
    "cotton": {"weight": 0.14, "yield_per_acre": 58_000, "income_volatility": 0.32},
    "sugarcane": {"weight": 0.09, "yield_per_acre": 92_000, "income_volatility": 0.12},
    "horticulture": {"weight": 0.12, "yield_per_acre": 128_000, "income_volatility": 0.38},
    "pulses": {"weight": 0.15, "yield_per_acre": 33_000, "income_volatility": 0.30},
}

#: Regional price/volume levels. Indices: 0 = rural, 1 = semi-urban, 2 = urban.
REGION_TIERS: tuple[str, ...] = ("rural", "semi_urban", "urban")
LAND_PRICE_PER_ACRE: tuple[float, ...] = (320_000, 640_000, 1_600_000)
HOUSE_VALUE: tuple[float, ...] = (430_000, 1_150_000, 2_700_000)
SHOP_VALUE_PER_SQFT: tuple[float, ...] = (6_000, 12_000, 25_000)
SHOP_REVENUE_PER_SQFT: tuple[float, ...] = (250, 400, 600)
INVENTORY_PER_SQFT: tuple[float, ...] = (1_200, 1_700, 2_300)

LOAN_TENURE_CHOICES: tuple[int, ...] = (12, 24, 36, 48, 60)

#: The latent "true" credit policy: ``(engineered_feature, weight)`` pairs.
#: Positive weight => the fact improves repayment odds. Every driver is
#: z-scored before weighting (see :func:`_standardised`), so the weights are
#: comparable to each other and can be read as a standardised scorecard - and
#: the resulting logit spread is wide enough to produce a realistic score
#: distribution rather than one clustered band.
LATENT_DRIVERS: tuple[tuple[str, float], ...] = (
    ("proposed_debt_service_ratio", -1.00),  # can the household afford THIS facility?
    ("debt_service_ratio", -0.70),            # existing EMI burden vs. income proxy
    ("post_facility_loan_to_value", -0.55),   # leverage after the new facility
    ("debt_to_asset_ratio", -0.70),           # leverage against tangible assets
    ("collateral_coverage_ratio", +0.55),     # pledged value vs. facility size
    ("income_to_debt_ratio", +0.45),          # ability to repay out of income
    ("liquidity_ratio", +0.35),               # cash buffer vs. monthly EMI
    ("financial_discipline_score", +0.75),    # utility/UPI payment behaviour
    ("asset_productivity", +0.40),            # earning efficiency of assets
    ("net_worth", +0.45),                     # assets net of borrowings
    ("years_in_operation", +0.30),            # track record / stability
    ("dependents", -0.25),                    # household consumption pressure
)

#: Unobserved shocks (illness, weather, fraud) plus model-irrelevant variance.
#: Deliberately large: it caps the achievable AUC and keeps the reported metrics
#: honest. The generator's own ceiling is measured and reported at training time.
LOGIT_NOISE_SD = 0.75


@dataclass
class GenerationReport:
    """Metadata about a generated portfolio (useful in the training report)."""

    n_records: int
    seed: int
    target_repayment_rate: float
    realised_repayment_rate: float
    intercept: float
    segment_counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_records": self.n_records,
            "seed": self.seed,
            "target_repayment_rate": round(self.target_repayment_rate, 4),
            "realised_repayment_rate": round(self.realised_repayment_rate, 4),
            "latent_intercept": round(self.intercept, 4),
            "label_noise_rate": LABEL_NOISE_RATE,
            "segment_counts": self.segment_counts,
        }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _clip_normal(
    rng: np.random.Generator,
    n: int,
    mean: float,
    sd: float,
    low: float,
    high: float,
) -> np.ndarray:
    return np.clip(rng.normal(mean, sd, n), low, high)


def _lognormal(rng: np.random.Generator, n: int, median: float, sigma: float) -> np.ndarray:
    return median * np.exp(rng.normal(0.0, sigma, n))


def _sigmoider(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


# ---------------------------------------------------------------------------
# segment generators
# ---------------------------------------------------------------------------


def _generate_farmers(n: int, rng: np.random.Generator) -> pd.DataFrame:
    """Sample asset-rich, cash-flow-thin farming households."""
    region_idx = rng.choice(len(REGION_TIERS), size=n, p=[0.55, 0.30, 0.15])
    crop_names = list(CROP_PROFILES)
    crop_weights = [CROP_PROFILES[c]["weight"] for c in crop_names]
    crops = rng.choice(np.array(crop_names, dtype=object), size=n, p=np.array(crop_weights))

    land_size = np.clip(_lognormal(rng, n, 3.0, 0.85), 0.2, 45.0)
    irrigation = _clip_normal(rng, n, 57, 19, 5, 100)
    soil = _clip_normal(rng, n, 59, 15, 5, 100)

    # Harvest value = acreage x crop economics x agronomic quality x weather shock
    base_yield = np.array([CROP_PROFILES[c]["yield_per_acre"] for c in crops])
    volatility = np.array([CROP_PROFILES[c]["income_volatility"] for c in crops])
    quality_multiplier = 0.55 + 0.004 * irrigation + 0.0032 * soil
    weather_shock = np.exp(rng.normal(0.0, 1.0, n) * volatility - 0.5 * volatility**2)
    crop_yield_value = land_size * base_yield * quality_multiplier * weather_shock

    land_price = np.array(LAND_PRICE_PER_ACRE)[region_idx]
    land_market_value = land_size * land_price * _lognormal(rng, n, 1.0, 0.22)

    owns_house = rng.random(n) < 0.82
    house_value = np.array(HOUSE_VALUE)[region_idx] * _lognormal(rng, n, 1.0, 0.28)
    property_value = np.where(owns_house, house_value, np.nan)

    has_tractor = rng.random(n) < 0.42
    tractor_value = np.clip(_lognormal(rng, n, 780_000, 0.30), 150_000, 2_500_000)
    implements_value = np.clip(_lognormal(rng, n, 48_000, 0.45), 5_000, 400_000)
    equipment_value = np.where(has_tractor, tractor_value + implements_value, implements_value)

    has_livestock = rng.random(n) < 0.62
    livestock_value = np.where(
        has_livestock, np.clip(_lognormal(rng, n, 185_000, 0.55), 15_000, 1_400_000), 0.0
    )

    off_farm = np.where(rng.random(n) < 0.35, _lognormal(rng, n, 120_000, 0.5), 0.0)
    annual_income = crop_yield_value + 0.15 * livestock_value + off_farm

    return pd.DataFrame(
        {
            "applicant_category": "farmer",
            "region_tier": np.array(REGION_TIERS, dtype=object)[region_idx],
            "crop_type": crops,
            "shop_space_ownership": "not_applicable",
            "age": _clip_normal(rng, n, 44, 12, 21, 74).round(0),
            "dependents": np.clip(rng.poisson(3.0, n), 0, 9),
            "years_in_operation": _clip_normal(rng, n, 11, 7, 0.5, 42),
            "land_size_acres": land_size,
            "irrigation_score": irrigation,
            "soil_quality_score": soil,
            "crop_yield_annual_value": crop_yield_value,
            "land_market_value": land_market_value,
            "property_value": property_value,
            "equipment_value": equipment_value,
            "livestock_value": livestock_value,
            "shop_area_sqft": np.nan,
            "inventory_value": np.nan,
            "monthly_upi_turnover": np.nan,
            "annual_income_proxy": annual_income,
        }
    )


def _generate_businesses(n: int, rng: np.random.Generator) -> pd.DataFrame:
    """Sample shops/workshops whose cash flow is visible in UPI ledgers."""
    region_idx = rng.choice(len(REGION_TIERS), size=n, p=[0.30, 0.40, 0.30])

    shop_area = np.clip(_lognormal(rng, n, 330, 0.60), 60, 3_000)
    owns_premises = rng.random(n) < 0.50
    # An owned shop is more likely outside the most expensive urban core.
    owns_premises = np.where((region_idx == 2) & (rng.random(n) < 0.35), False, owns_premises)

    revenue_per_sqft = np.array(SHOP_REVENUE_PER_SQFT)[region_idx]
    monthly_upi = shop_area * revenue_per_sqft * _lognormal(rng, n, 1.0, 0.45)

    inventory_density = np.array(INVENTORY_PER_SQFT)[region_idx]
    inventory_value = shop_area * inventory_density * _lognormal(rng, n, 1.0, 0.40)

    shop_value = shop_area * np.array(SHOP_VALUE_PER_SQFT)[region_idx] * _lognormal(rng, n, 1.0, 0.25)
    property_value = np.where(owns_premises, shop_value, np.nan)

    equipment_value = np.clip(_lognormal(rng, n, 125_000, 0.70), 0, 2_000_000)

    # Gross margin depends on the region's cost structure.
    gross_margin = np.array([0.19, 0.165, 0.145])[region_idx] * _lognormal(rng, n, 1.0, 0.12)
    other_income = np.where(rng.random(n) < 0.25, _lognormal(rng, n, 90_000, 0.5), 0.0)
    annual_income = monthly_upi * gross_margin * 12.0 + other_income

    return pd.DataFrame(
        {
            "applicant_category": "small_business",
            "region_tier": np.array(REGION_TIERS, dtype=object)[region_idx],
            "crop_type": "not_applicable",
            "shop_space_ownership": np.where(owns_premises, "owned", "rented"),
            "age": _clip_normal(rng, n, 38, 10, 21, 72).round(0),
            "dependents": np.clip(rng.poisson(2.6, n), 0, 9),
            "years_in_operation": _clip_normal(rng, n, 8, 6, 0.5, 36),
            "land_size_acres": np.nan,
            "irrigation_score": np.nan,
            "soil_quality_score": np.nan,
            "crop_yield_annual_value": np.nan,
            "land_market_value": np.nan,
            "property_value": property_value,
            "equipment_value": equipment_value,
            "livestock_value": np.nan,
            "shop_area_sqft": shop_area,
            "inventory_value": inventory_value,
            "monthly_upi_turnover": monthly_upi,
            "annual_income_proxy": annual_income,
        }
    )


# ---------------------------------------------------------------------------
# common fields
# ---------------------------------------------------------------------------


def _add_cashflow_and_credit(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Add the correlated cash-flow proxies and existing credit exposure."""
    out = df.copy()
    n = len(out)
    income = out["annual_income_proxy"].to_numpy(dtype=float)
    monthly_income = income / 12.0
    is_farmer = (out["applicant_category"] == "farmer").to_numpy()

    # --- utility payment discipline ------------------------------------------
    # Payment discipline tracks income strength (the central "alternative data"
    # thesis: people who pay bills on time service loans on time) but keeps a
    # lot of genuine idiosyncratic variance.
    log_income = np.log10(np.maximum(income, 1.0))
    income_z = (log_income - log_income.mean()) / max(log_income.std(), 1e-6)
    utility_score = np.clip(rng.normal(72.0 + 9.0 * income_z, 13.0), 5.0, 100.0)
    # Informal, cash-heavy households under-report and pay late more often.
    utility_score = np.clip(utility_score - np.where(is_farmer, 3.5, 0.0), 5.0, 100.0)
    delays = np.clip(np.round((100.0 - utility_score) / 9.0 + rng.normal(0, 0.8, n)), 0, 12)

    # --- liquidity ------------------------------------------------------------
    balance_share = rng.uniform(0.03, 0.55, n) * np.where(is_farmer, 0.6, 1.0)
    avg_balance = np.clip(monthly_income * balance_share, 500.0, 6_000_000.0)

    # --- existing debt --------------------------------------------------------
    leverage = rng.uniform(0.05, 0.85, n) * np.where(is_farmer, 1.15, 1.0)
    outstanding_debt = np.clip(income * leverage, 0.0, 20_000_000.0)
    emi_rate = rng.uniform(0.021, 0.033, n)
    monthly_emi = outstanding_debt * emi_rate

    # --- requested facility ---------------------------------------------------
    request_ratio = rng.uniform(0.25, 1.10, n)
    requested = np.clip(income * request_ratio, 25_000.0, 5_000_000.0)
    requested = np.round(requested / 10_000.0) * 10_000.0

    tenure_share = rng.random(n)
    tenure = np.select(
        [tenure_share < 0.15, tenure_share < 0.35, tenure_share < 0.60, tenure_share < 0.82],
        [12, 24, 36, 48],
        default=60,
    ).astype(int)

    # --- field-survey gaps (proves the pipeline handles genuine missing data) --
    irrigation = out["irrigation_score"].to_numpy(dtype=float)
    soil = out["soil_quality_score"].to_numpy(dtype=float)
    irrigation = np.where(is_farmer & (rng.random(n) < 0.07), np.nan, irrigation)
    soil = np.where(is_farmer & (rng.random(n) < 0.05), np.nan, soil)

    out["utility_payment_consistency_score"] = utility_score.round(1)
    out["utility_payment_delays_12m"] = delays
    out["avg_monthly_bank_balance"] = avg_balance.round(0)
    out["outstanding_debt"] = outstanding_debt.round(0)
    out["monthly_emi_obligation"] = monthly_emi.round(0)
    out["requested_loan_amount"] = requested
    out["loan_tenure_months"] = tenure
    out["irrigation_score"] = irrigation
    out["soil_quality_score"] = soil
    return out


# ---------------------------------------------------------------------------
# latent creditworthiness -> outcome
# ---------------------------------------------------------------------------


def _standardised(values: np.ndarray, clip_percentile: float = 1.0) -> np.ndarray:
    """Robust z-score: winsorise the tails, then centre and scale.

    Ratios like ``income_to_debt_ratio`` are heavily right-skewed, so a plain
    z-score would let a handful of outliers dominate the latent policy. We clip
    to the 1st/99th percentile first and bound the result to +/-3 standard
    deviations. Missing values become 0, i.e. "neutral", which is the honest
    treatment for an unobserved attribute.
    """
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return np.zeros_like(values, dtype=float)
    low, high = np.percentile(finite, [clip_percentile, 100.0 - clip_percentile])
    clipped = np.clip(values, low, high)
    mean = np.nanmean(clipped)
    sd = np.nanstd(clipped)
    if not np.isfinite(sd) or sd < 1e-9:
        return np.zeros_like(values, dtype=float)
    z = (clipped - mean) / sd
    return np.clip(np.nan_to_num(z, nan=0.0), -3.0, 3.0)


def _latent_logit(df: pd.DataFrame, intercept: float) -> np.ndarray:
    """Creditworthiness score in log-odds space (of *repayment*, not default).

    This is the ground truth the model has to rediscover: a standardised
    scorecard over collateral, indebtedness and alternative cash-flow behaviour.
    """
    ratios = engineer_features(df)
    logit = np.full(len(ratios), float(intercept), dtype=float)
    for feature, weight in LATENT_DRIVERS:
        logit = logit + weight * _standardised(ratios[feature].to_numpy(dtype=float))
    return logit


def _calibrate_intercept(
    df: pd.DataFrame, target_rate: float, noise: np.ndarray
) -> float:
    """Bisect the intercept so the portfolio hits the target repayment rate."""
    low, high = -12.0, 12.0
    for _ in range(80):
        mid = (low + high) / 2.0
        prob = _sigmoider(_latent_logit(df, mid) + noise)
        if prob.mean() < target_rate:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def generate_synthetic_portfolio(
    n_records: int = DEFAULT_N_RECORDS,
    seed: int = DEFAULT_SEED,
    target_repayment_rate: float = DEFAULT_REPAYMENT_RATE,
) -> tuple[pd.DataFrame, GenerationReport]:
    """Generate a reproducible synthetic loan portfolio.

    Args:
        n_records: Number of loan applications to simulate (> 0).
        seed: RNG seed; identical seeds produce identical portfolios.
        target_repayment_rate: Share of loans that should repay on time. Used to
            calibrate the latent intercept, which is how a demo can be tuned to
            look like a low-default MFI book or a stressed one.

    Returns:
        ``(portfolio, report)`` where ``portfolio`` contains the raw declared
        features plus ``repaid_on_time`` and a diagnostic
        ``latent_repayment_probability`` column (generator ground truth, *not*
        model input).
    """
    if n_records <= 0:
        raise ValueError("n_records must be positive")
    if not 0.05 <= target_repayment_rate <= 0.98:
        raise ValueError("target_repayment_rate must be within [0.05, 0.98]")

    rng = np.random.default_rng(seed)

    n_farmers = int(round(n_records * FARMER_SHARE))
    n_businesses = n_records - n_farmers

    portfolio = pd.concat(
        [
            _generate_farmers(n_farmers, rng),
            _generate_businesses(n_businesses, rng),
        ],
        ignore_index=True,
    )
    portfolio = _add_cashflow_and_credit(portfolio, rng)

    # Latent risk: systematic noise is *calibrated away* by the intercept search,
    # so we draw it once and reuse the same vector for every candidate intercept.
    systematic_noise = rng.normal(0.0, LOGIT_NOISE_SD, len(portfolio))
    intercept = _calibrate_intercept(portfolio, target_repayment_rate, systematic_noise)

    true_prob = _sigmoider(_latent_logit(portfolio, intercept) + systematic_noise)
    observed = rng.binomial(1, true_prob).astype(int)

    # A small share of outcomes genuinely contradict the fundamentals (fraud,
    # medical shock, family event, data-entry error). Keeping this prevents the
    # model from looking artificially perfect.
    flip_mask = rng.random(len(portfolio)) < LABEL_NOISE_RATE
    observed = np.where(flip_mask, 1 - observed, observed)

    portfolio.insert(0, "applicant_id", [f"SYN{i:06d}" for i in range(1, len(portfolio) + 1)])
    portfolio["latent_repayment_probability"] = true_prob.round(6)
    portfolio["repaid_on_time"] = observed

    # Shuffle so rows are not grouped by segment.
    portfolio = portfolio.sample(frac=1.0, random_state=seed).reset_index(drop=True)

    report = GenerationReport(
        n_records=len(portfolio),
        seed=seed,
        target_repayment_rate=target_repayment_rate,
        realised_repayment_rate=float(portfolio["repaid_on_time"].mean()),
        intercept=intercept,
        segment_counts={
            str(k): int(v)
            for k, v in portfolio["applicant_category"].value_counts().items()
        },
    )
    return portfolio, report


def main() -> None:  # pragma: no cover - thin CLI wrapper
    import argparse

    from ml.config import DEFAULT_DATASET_PATH

    parser = argparse.ArgumentParser(description="Generate a synthetic loan portfolio.")
    parser.add_argument("--n-records", type=int, default=DEFAULT_N_RECORDS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--repayment-rate", type=float, default=DEFAULT_REPAYMENT_RATE)
    parser.add_argument("--out", type=str, default=DEFAULT_DATASET_PATH)
    args = parser.parse_args()

    from pathlib import Path

    portfolio, report = generate_synthetic_portfolio(
        n_records=args.n_records, seed=args.seed, target_repayment_rate=args.repayment_rate
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    portfolio.to_csv(out_path, index=False)

    print(f"Wrote {len(portfolio)} rows -> {out_path}")
    print(f"Repaid on time: {report.realised_repayment_rate:.1%}")
    print(f"Segments: {report.segment_counts}")


if __name__ == "__main__":  # pragma: no cover
    main()
