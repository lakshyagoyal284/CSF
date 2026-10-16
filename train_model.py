#!/usr/bin/env python
"""``train_model.py`` - generate data, train the credit model, save artifacts.

This is the single command a reviewer or CI job runs:

    python train_model.py                          # 1500 rows, cached CSV if present
    python train_model.py --refresh-data           # regenerate the portfolio
    python train_model.py --n-records 5000 --seed 7
    python train_model.py --repayment-rate 0.65    # simulate a stressed book

Artifacts written
-----------------
``artifacts/credit_model.pkl``          model + feature contract + metadata bundle
``artifacts/training_metrics.json``     full evaluation report (AUC, KS, deciles, ...)
``artifacts/feature_importance.csv``    XGBoost gain importance
``artifacts/shap_global_importance.csv``grouped SHAP importance in decision space
``data/synthetic_portfolio.csv``        the generated portfolio (auditable input)

Implementation lives in :mod:`ml.train`; this file is only the CLI surface.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from anywhere: ensure the project root is importable.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.config import DEFAULT_DATASET_PATH, DEFAULT_MODEL_PATH  # noqa: E402
from ml.data_generator import (  # noqa: E402
    DEFAULT_N_RECORDS,
    DEFAULT_REPAYMENT_RATE,
    DEFAULT_SEED,
)
from ml.train import run_training  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train the alternative credit scoring model (XGBoost + SHAP).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--n-records", type=int, default=DEFAULT_N_RECORDS,
                        help="Number of synthetic applications to simulate.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help="RNG seed for the dataset and the model.")
    parser.add_argument("--repayment-rate", type=float, default=DEFAULT_REPAYMENT_RATE,
                        help="Target share of on-time repayments (portfolio risk level).")
    parser.add_argument("--dataset", type=str, default=DEFAULT_DATASET_PATH,
                        help="Where the synthetic portfolio CSV lives.")
    parser.add_argument("--refresh-data", action="store_true",
                        help="Regenerate the portfolio even if the CSV already exists.")
    parser.add_argument("--model-out", type=str, default=DEFAULT_MODEL_PATH,
                        help="Destination for the pickled model bundle.")
    parser.add_argument("--skip-shap-importance", action="store_true",
                        help="Skip the grouped SHAP ranking (faster on very large data).")
    parser.add_argument("--early-stopping-patience", type=int, default=250,
                        help="Early-stopping patience passed through to XGBoost.")
    parser.add_argument("--quiet", action="store_true", help="Suppress the printed report.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    result, artifacts = run_training(
        n_records=args.n_records,
        seed=args.seed,
        repayment_rate=args.repayment_rate,
        dataset_path=args.dataset,
        refresh_data=args.refresh_data,
        model_path=args.model_out,
        compute_shap_importance=not args.skip_shap_importance,
        verbose=not args.quiet,
        early_stopping_patience=args.early_stopping_patience,
    )

    # Non-zero exit when the model is not fit for a demo: this keeps a broken
    # pipeline from silently shipping a useless scorecard.
    if result.test_auc < 0.70:
        print(f"\n[FAIL] Hold-out ROC-AUC {result.test_auc:.4f} is below the 0.70 "
              "acceptance threshold.", file=sys.stderr)
        return 1

    if args.quiet:
        print(f"Trained. ROC-AUC={result.test_auc:.4f} -> {artifacts['model_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
