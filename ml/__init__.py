"""Package marker for the alternative credit scoring engine.

Sub-modules
-----------
``ml.config``          Feature contract, scorecard scaling, credit policy constants.
``ml.data_generator``  Synthetic loan-portfolio simulator with a latent risk process.
``ml.features``        Feature engineering + the frozen model input matrix.
``ml.scoring``         PD -> 300-900 score, risk tier and credit-limit policy.
``ml.explain``         SHAP explainability (grouped, signed, in score points).
``ml.train``           Training, evaluation and artifact persistence.
"""

from __future__ import annotations

__all__ = ["config", "data_generator", "features", "scoring", "explain", "train"]
__version__ = "1.0.0"
