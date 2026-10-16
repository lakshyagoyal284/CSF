"""Synthetic portfolio tests.

The generator is the training data, so its contract (reproducibility, segment
sanity, calibrated default rate, non-degenerate labels) is worth locking down.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.config import FEATURE_COLUMNS, RAW_CATEGORICAL_FEATURES, RAW_NUMERIC_FEATURES
from ml.data_generator import FARMER_SHARE, generate_synthetic_portfolio
from ml.features import engineer_features


def test_generation_is_reproducible() -> None:
    first, first_report = generate_synthetic_portfolio(n_records=200, seed=99)
    second, second_report = generate_synthetic_portfolio(n_records=200, seed=99)
    pd.testing.assert_frame_equal(first, second)
    assert first_report.intercept == second_report.intercept


def test_different_seeds_differ() -> None:
    first, _ = generate_synthetic_portfolio(n_records=200, seed=1)
    second, _ = generate_synthetic_portfolio(n_records=200, seed=2)
    assert not np.allclose(
        first["annual_income_proxy"].to_numpy(), second["annual_income_proxy"].to_numpy()
    )


def test_portfolio_shape_and_segments() -> None:
    portfolio, report = generate_synthetic_portfolio(n_records=500, seed=3)
    assert len(portfolio) == 500
    assert portfolio["applicant_id"].is_unique
    assert set(portfolio["applicant_category"]) == {"farmer", "small_business"}

    farmers = (portfolio["applicant_category"] == "farmer").sum()
    assert abs(farmers / len(portfolio) - FARMER_SHARE) < 0.05
    assert report.segment_counts["farmer"] == farmers


def test_every_raw_input_required_by_the_model_is_present() -> None:
    portfolio, _ = generate_synthetic_portfolio(n_records=120, seed=5)
    for column in (*RAW_NUMERIC_FEATURES, *RAW_CATEGORICAL_FEATURES):
        assert column in portfolio.columns, f"generator is missing {column}"
    # The model's feature contract is built from raw inputs, so it must be
    # satisfiable from a generated row.
    assert set(FEATURE_COLUMNS).issuperset(set(RAW_NUMERIC_FEATURES))


def test_segment_specific_fields_are_missing_not_zero() -> None:
    """A farmer has no UPI ledger turnover; that is missing data, not a zero."""
    portfolio, _ = generate_synthetic_portfolio(n_records=400, seed=6)
    farmers = portfolio[portfolio["applicant_category"] == "farmer"]
    businesses = portfolio[portfolio["applicant_category"] == "small_business"]

    assert farmers["monthly_upi_turnover"].isna().all()
    assert farmers["shop_area_sqft"].isna().all()
    assert farmers["inventory_value"].isna().all()
    assert (businesses["monthly_upi_turnover"] > 0).all()
    assert (businesses["inventory_value"] > 0).all()
    assert businesses["land_size_acres"].isna().all()


def test_target_is_calibrated_and_not_degenerate() -> None:
    portfolio, report = generate_synthetic_portfolio(
        n_records=800, seed=8, target_repayment_rate=0.75
    )
    rate = portfolio["repaid_on_time"].mean()
    assert 0.68 < rate < 0.82, f"realised repayment rate {rate:.3f} is far off target"
    assert portfolio["repaid_on_time"].isin([0, 1]).all()
    assert 0.15 < rate < 0.95, "labels are degenerate"
    assert report.realised_repayment_rate == rate


def test_latent_probability_orders_the_outcome() -> None:
    """The label must be learnable: high latent probability implies more repayments."""
    portfolio, _ = generate_synthetic_portfolio(n_records=1200, seed=9)
    top = portfolio.nlargest(200, "latent_repayment_probability")
    bottom = portfolio.nsmallest(200, "latent_repayment_probability")
    assert top["repaid_on_time"].mean() > bottom["repaid_on_time"].mean() + 0.25


def test_default_rate_can_be_tuned() -> None:
    stressed, _ = generate_synthetic_portfolio(
        n_records=600, seed=10, target_repayment_rate=0.55
    )
    assert stressed["repaid_on_time"].mean() < 0.68


def test_defaulted_files_are_more_levered_on_average() -> None:
    """Sanity-check the simulated economics rather than just the code paths."""
    portfolio, _ = generate_synthetic_portfolio(n_records=1500, seed=12)
    ratios = engineer_features(portfolio)
    portfolio = portfolio.assign(
        debt_to_asset=ratios["debt_to_asset_ratio"],
        proposed_service=ratios["proposed_debt_service_ratio"],
    )
    defaulted = portfolio[portfolio["repaid_on_time"] == 0]
    repaid = portfolio[portfolio["repaid_on_time"] == 1]
    assert defaulted["debt_to_asset"].mean() > repaid["debt_to_asset"].mean()
