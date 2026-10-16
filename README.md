# Alternative Credit Scoring Engine

An end-to-end prototype that lets a bank or MFI loan officer score a borrower who
has **no bureau history and no salary slip**, using what the borrower actually
owns (land, property, machinery, livestock, inventory) and what their digital
footprint shows (UPI turnover, utility payment discipline).

The output is a standard **300-900 credit score**, a risk tier, a recommended
credit limit, and the **top reasons behind the decision** (SHAP) - so the score
is defensible to an auditor, not just accurate.

---

## 1. What problem this solves

| | Traditional underwriting | This engine |
|---|---|---|
| Evidence | Bureau score + salary slip | Declared assets + UPI ledger + utility history |
| Who gets excluded | Farmers, shopkeepers, informal MSMEs | Included |
| Turnaround | Days to weeks (manual field verification) | Seconds (officer declares, model scores) |
| Explainability | Officer's judgement | Ranked, signed SHAP factors per file |

**Users:** loan officers processing rural and MSME applications.
**Borrowers:** unbanked / underbanked farmers and small shopkeepers who own real
assets but cannot prove income on paper.

---

## 2. Architecture

```
                 ┌─────────────────────────────────────────────────────┐
                 │  Next.js 16 + Tailwind v4 underwriting console      │
                 │  form · score dial · risk badge · SHAP breakdown    │
                 │  what-if simulator                                  │
                 └───────────────────────┬─────────────────────────────┘
                                         │ JSON over HTTP
                 ┌───────────────────────▼─────────────────────────────┐
                 │  FastAPI  (backend/)                                │
                 │  /api/score   /api/simulate   /api/model/info ...   │
                 │  schemas.py  -> validation + evidence rules         │
                 │  service.py  -> scoring orchestration               │
                 │  model_registry.py -> artifact loading + SHAP       │
                 └───────┬───────────────────────────────┬─────────────┘
                         │                               │
      ┌──────────────────▼───────────────┐   ┌───────────▼──────────────┐
      │ ml/ (offline + online shared)    │   │ PostgreSQL (db/schema.sql)│
      │  config.py    feature contract   │   │  applicants               │
      │  data_generator.py  synthetic    │   │  asset_records            │
      │  features.py  ratios + one-hot   │   │  cashflow_proxies         │
      │  scoring.py   PD -> score -> tier│   │  credit_assessment_logs   │
      │  explain.py   SHAP -> reasons    │   │  + views, indexes, audit  │
      │  train.py     XGBoost + metrics  │   └──────────────────────────┘
      └──────────────────┬───────────────┘
                         │
              artifacts/credit_model.pkl
              (model + feature contract + metadata + reference sample)
```

One design rule keeps the whole thing honest: **the feature contract lives in
`ml/config.py` and is used by both the training script and the API.** Online
scoring cannot silently drift from offline training, because both build their
matrices through `ml/features.build_feature_matrix()`.

---

## 3. Quickstart

```bash
# 1. Environment (a dedicated venv avoids a fastapi/starlette version clash)
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt      # Windows
.venv/bin/python     -m pip install -r requirements.txt      # macOS / Linux

# 2. Generate data, train, evaluate, save the model artifact
python train_model.py                 # 4,000 synthetic applications
python train_model.py --refresh-data  # regenerate the portfolio
python train_model.py --n-records 8000 --seed 7

# 3. API  (http://localhost:8000/docs for interactive Swagger)
uvicorn main:app --reload --port 8000          # root shim; backend.main:app also works

# 4. Dashboard  (http://localhost:3000)
cd frontend && npm install && npm run dev
```

The dashboard starts blank; click a **demo file** button to score a live
application, or fill the declaration form. All three demo files are real
in-distribution profiles and cover the three risk tiers on the shipped model.

---

## 4. The model

### 4.1 Features (`ml/features.py`)

**Declared raw inputs** - demographics, land and farm assets, shop and business
assets, shared collateral, alternative cash-flow proxies, and the credit ask.

**Engineered ratios** - these, not the raw values, are what a credit analyst
actually reasons with:

| Ratio | Definition | Why it matters |
|---|---|---|
| `total_collateral_value` | land + property + equipment + livestock + inventory | the collateral base |
| `collateral_coverage_ratio` | collateral ÷ requested facility | is the ask covered? |
| `debt_to_asset_ratio` | existing debt ÷ tangible assets | leverage today |
| `debt_service_ratio` | existing EMI ÷ monthly income | existing burden |
| `proposed_debt_service_ratio` | (existing EMI + **new instalment**) ÷ monthly income | **affordability of this ask** |
| `post_facility_loan_to_value` | (debt + facility) ÷ collateral | leverage after drawdown |
| `liquidity_ratio` | avg bank balance ÷ monthly EMI | shock absorber |
| `income_to_debt_ratio` | annual income ÷ outstanding debt | repayment headroom |
| `net_worth` | assets − borrowings | balance-sheet strength |
| `asset_productivity` | annual income ÷ asset value | are the assets earning? |
| `financial_discipline_score` | 0.7·utility score + 0.3·delay penalty | the alt-data thesis |

Categoricals (segment, region, shop ownership, crop) are one-hot encoded with
**fixed levels**, so the column order is frozen. Missing values stay `NaN`:
XGBoost treats them as missing data, which is different from a declared zero
(a farmer with no shop *is not* a shopkeeper with zero inventory).

### 4.2 Scorecard scaling (`ml/scoring.py`)

A classical points-to-double-the-odds transform:

```
score = 524.5 + 89.64 · ln( p_repay / (1 − p_repay) )        clipped to [300, 900]
```

anchored on the credit policy, not on a coin flip:

| Default probability | Score | Tier |
|---|---|---|
| 5% | ~790 | Low (pre-approved) |
| 15% | **680** | Low boundary |
| 20% | ~646 | Medium (manual review) |
| 35% | **580** | Medium boundary |
| 50% | ~524 | High |
| 90% | ~340 | High |

The transform is monotone increasing in repayment odds, so a higher score always
means a safer borrower. (An inverted scale is the single most dangerous bug in a
scorecard - it approves the worst files while every other metric still looks
fine - so it is pinned by `tests/test_scoring.py::test_score_increases_with_repayment_odds`.)

### 4.3 Credit limit policy (`ml/scoring.py`)

Two independent caps are computed and the **tighter one binds**:

* **Collateral cap** = pledged value × LTV (55% farmers, 65% MSME, owner-occupied
  property counted at the same rate).
* **Income cap** = the facility whose annual debt service equals 30% of the
  income proxy, amortised at the tier's indicative rate over the requested tenure.

The lower cap is then haircut by the tier multiplier (LOW 1.00, MEDIUM 0.65,
HIGH 0.25), rounded to ₹5,000, and floored at ₹25,000 - so a high-risk file can
still be offered a small *secured* facility instead of an outright decline.
The response reports which constraint bound, and both caps.

### 4.4 Evidence policy (§ *thin files are not safe files*)

A tree model routes missing values down a learned default branch, so an
application that declares almost nothing can look perfectly healthy - measured
here: **a file declaring only a loan amount scored 607/900 (MEDIUM)**. Two rules
prevent that:

1. **Hard (HTTP 422).** At least one income/turnover/harvest proxy must be
   declared - otherwise repayment capacity is unassessable and the file is
   refused with an actionable message.
2. **Soft (tier overlay).** Files missing *any* of the three evidence groups
   (income/turnover, tangible collateral, payment behaviour) can still be
   scored, but are **capped at manual review** and never pre-approved, with the
   missing evidence listed. The score is untouched; only auto-approval is lost.

Measured effect: a file the model rates 860/LOW, with no verified payment
behaviour, is capped to **MEDIUM/manual review** and its limit drops from
₹2,30,000 to ₹1,45,000.

### 4.5 Training (`train_model.py` → `ml/train.py`)

* Synthetic portfolio (`ml/data_generator.py`): ~4,000 applications, 55% farmers,
  segment-specific distributions, a **latent creditworthiness function** so the
  label is learnable rather than noise, and a calibrated base repayment rate
  (78%). Label noise is injected so the model never looks artificially perfect.
* XGBoost, stratified 65/15/20 train/validation/test split, early stopping to
  choose the tree count, then a **refit with that exact tree count**.
* Metrics: ROC-AUC, Gini, KS, PR-AUC, Brier, decile calibration, per-segment
  breakdown, tier default rates, and the generator's own ceiling (how much of
  the recoverable signal the model captured).

**Why the refit matters:** a model left in early-stopping state scores with
`best_iteration` trees while SHAP's `TreeExplainer` walks *every* tree built, so
the explanations would describe a different (overfit) model than the one
approving loans. The refit makes prediction and explanation identical, verified
by `tests/test_explain.py::test_shap_values_sum_to_the_model_margin`.

### 4.6 Measured performance (shipped artifact, 4,000 rows)

```
Hold-out (800 accounts, 24% default rate)
  ROC-AUC  0.861      Gini 0.722      KS 0.570
  PR-AUC   0.945      Brier 0.117     train-test gap +0.077 AUC
  Signal captured: 91% of the generator's latent ceiling (0.895)

Tier separation (realised default rate)
  LOW    0.067      MEDIUM 0.219      HIGH 0.620

Top grouped SHAP drivers
  Proposed Debt Service · Debt Service Ratio · Debt-to-Asset Ratio
  · Income-to-Debt · Financial Discipline · Net Worth
```

The model rediscovered the affordability policy on its own: the **requested
facility's instalment** is the strongest driver, not the existing debt alone.

---

## 5. API reference

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | liveness + model/database status |
| `GET` | `/api/model/info` | provenance, hold-out metrics, scorecard bands |
| `GET` | `/api/feature-catalogue` | explainability vocabulary (labels, units) |
| `GET` | `/api/sample-applicants` | three demo files, one per risk tier |
| `POST` | `/api/score` | score + explain one application |
| `POST` | `/api/simulate` | what-if re-scoring with modified collateral |
| `POST` | `/api/admin/reload-model` | hot-swap a retrained artifact |
| `GET` | `/api/assessment-history` | recent assessments (PostgreSQL only) |

### `POST /api/score`

```bash
curl -s localhost:8000/api/score -H 'Content-Type: application/json' -d '{
  "applicant": {"applicant_category":"farmer","region_tier":"rural","age":46,
                "dependents":3,"years_in_operation":16,"crop_type":"wheat"},
  "assets":    {"land_size_acres":4.5,"irrigation_score":78,"soil_quality_score":70,
                "crop_yield_annual_value":236000,"land_market_value":1450000,
                "property_value":520000,"equipment_value":760000,"livestock_value":180000},
  "cashflow":  {"monthly_upi_turnover":62000,"utility_payment_consistency_score":82,
                "utility_payment_delays_12m":1,"avg_monthly_bank_balance":68000,
                "annual_income_proxy":300000},
  "credit":    {"requested_loan_amount":300000,"loan_tenure_months":36,
                "outstanding_debt":70000,"monthly_emi_obligation":2400}
}' | python -m json.tool
```

Returns the score, tier, decision, limit (with the binding constraint and both
caps), the derived ratios, the evidence assessment, and the explainability block:

```json
{
  "credit_score": 871,
  "probability_of_default": 0.02,
  "risk_tier": "LOW",
  "model_risk_tier": "LOW",
  "tier_label": "Pre-Approved",
  "decision": "PRE_APPROVED",
  "recommended_credit_limit": 230000,
  "binding_constraint": "income",
  "collateral_cap": 1600500,
  "income_cap": 233444,
  "indicative_rate_band": {"min_annual_rate": 9.5, "max_annual_rate": 11.5},
  "data_quality": {"completeness_ratio": 1.0, "allows_pre_approval": true, "warnings": []},
  "explainability": {
    "top_factors": [
      {"label": "Debt Service Ratio", "value": "8%", "score_impact_points": 52,
       "direction": "reduces_risk",
       "narrative": "Debt Service Ratio of 8% is supporting the score with about 52 extra points versus the portfolio average."}
    ],
    "summary": "Main risk drivers: Monthly UPI Turnover (₹62,000 /month). Main strengths: ..."
  }
}
```

Each factor carries the value read from the application, its contribution in
**score points** (same unit as the dial) and a plain-English narrative.

**Input conventions.** UPI turnover is consumed as one figure. Supply either
`monthly_upi_turnover` (the ledger total) or `daily_avg_upi_volume` (what bank and
PSP statements usually report) - the daily figure is annualised at 30 days, and
both score identically. A single column is used on purpose: two perfectly
collinear turnover columns would split and distort SHAP attribution.

### `POST /api/simulate`

Send the same application plus overrides. Absolute levers replace a value;
relative levers scale a class of collateral:

```bash
curl -s localhost:8000/api/simulate -H 'Content-Type: application/json' -d '{
  ... same applicant/assets/cashflow/credit ...,
  "overrides": {"inventory_value_uplift_pct": 25, "requested_loan_amount": 220000}
}'
```

Returns baseline vs. scenario (both fully scored), the deltas, the list of
changes that were actually applied, which explainability factors moved, and a
narrative:

```
"The scenario improves the credit score from 645 to 670 (+25 points).
 Changed inputs: requested_loan_amount: 240000 -> 220000.
 Largest explainability shifts: Debt-to-Asset Ratio (+13 pts), ..."
```

If a lever targets a field the applicant never declared (e.g. inventory for a
farmer), the response says so honestly instead of pretending it did something.

---

## 6. Database schema (`db/schema.sql`)

PostgreSQL 13+, idempotent, with enum types, CHECK constraints, a generated
collateral total, indexes, audit columns, an `updated_at` trigger and three
reporting views.

```bash
createdb credit_scoring
psql -d credit_scoring -f db/schema.sql
export ACS_DATABASE_URL="postgresql+psycopg://acs:acs@localhost:5432/credit_scoring"
export ACS_CREATE_TABLES_ON_STARTUP=true     # optional: demo convenience
```

| Table | Purpose |
|---|---|
| `applicants` | borrower master: segment, region, demographics, consent reference |
| `asset_records` | declared collateral per assessment (land, property, machinery, inventory) |
| `cashflow_proxies` | UPI turnover, utility discipline, income proxy, existing debt |
| `credit_assessment_logs` | score, tier, decision, limit, **SHAP JSONB**, input payload, officer |

Views: `v_latest_credit_assessment`, `v_portfolio_risk_monitor` (monthly
underwriting funnel by tier), `v_reason_code_frequency` (adverse-action
monitoring across the book), `v_underwriting_file` (BI-ready denormalised file).

The SHAP reasons are stored as JSONB *and* indexed (`GIN ... jsonb_path_ops`), so
"find every file where inventory was a top reason" is a real query. The exact
input payload is stored alongside the score so any historical decision can be
re-derived and defended.

Persistence is entirely optional: with no `ACS_DATABASE_URL` the API runs
stateless and scoring is unaffected. This is why a demo can never be broken by
an unconfigured database.

---

## 7. Frontend (`frontend/`)

Next.js 16 (App Router, Turbopack) + React 19 + Tailwind v4, TypeScript strict.

| Component | Role |
|---|---|
| `UnderwritingDashboard.tsx` | state, API orchestration, layout |
| `ApplicantForm.tsx` | segment-aware declaration form, demo file loader |
| `ScoreDial.tsx` | SVG 300-900 gauge; band arcs driven by the API's own cut-offs |
| `RiskTierBadge.tsx` / `RiskTierPanel.tsx` | green / amber / red tier indicator + decision |
| `PolicyPanel.tsx` | recommended limit, binding constraint, caps, rate band, ratios |
| `ShapBreakdown.tsx` | signed contribution bars in score points, top-3 highlighted |
| `WhatIfSimulator.tsx` | quick scenarios + levers, baseline-vs-scenario, impact chart |

Configuration: `NEXT_PUBLIC_API_BASE` (defaults to `http://localhost:8000`); see
`frontend/.env.example`. The FastAPI service ships CORS defaults for
`localhost:3000`.

---

## 8. Tests and verification

```bash
# 90 unit / integration tests (API, scorecard, features, SHAP, generator)
.venv/Scripts/python -m pytest tests -q

# DDL vs. SQLAlchemy drift check (schema is the source of truth for deployments)
.venv/Scripts/python scripts/check_schema_consistency.py

# Real-browser check of the dashboard: loads a demo file, scores it, runs a
# what-if, then asserts the dial, tier, policy and SHAP panels rendered
cd frontend && npm install --no-save puppeteer-core
node scripts/verify-dashboard.mjs          # needs API :8000 and UI :3000 running
```

The suite trains a small throwaway model into a temp directory (it never touches
`artifacts/`), and covers:

* **scorecard direction, anchoring and tier/score consistency**
* **credit limit policy** (which cap binds, haircuts, rounding, floor, ceiling)
* **feature contract** (frozen column order, exact ratio arithmetic, no infinities)
* **synthetic portfolio** (reproducibility, segment-specific missingness, calibration)
* **explainability** (SHAP additivity with the served margin, sign conventions, ranking)
* **API** (endpoints, validation, evidence refusals, simulation directions)
* **model registry** (missing/corrupt/mismatched artifacts fail with guidance)

---

## 9. Honest limitations

This is a hackathon-grade prototype, not a shippable credit model:

* **Synthetic data.** The portfolio is simulated, including the label. Real
  performance will differ; the reported AUC/KS describe the simulator, not a
  real book. Nothing here has been validated against actual repayment outcomes.
* **No probability calibration layer.** XGBoost's log-loss outputs are already
  reasonably calibrated here (Brier 0.117), but a production scorecard needs
  isotonic/Platt calibration on a holdout window before pricing depends on PD.
* **Score clipping.** Scores saturate at 300/900 for PD below ~1.3% and above
  ~93%; ranking inside those extremes is not preserved.
* **Collateral revaluation is near-neutral.** Measured: +25% collateral moves the
  score by ≈ -1 point, because it improves collateral cover and leverage but
  lowers asset productivity. Levers that reliably move the decision are the
  requested amount, existing EMI/debt, income and payment discipline.
* **No authentication, rate limiting, PII masking or field encryption.** None of
  the API is safe to expose as-is.
* **Account Aggregator / UPI ingestion is stubbed.** The proxies are declared by
  the officer; wiring real AA/UPI feeds (and their consent artefact) is the next
  integration step.
* **Single model, no fairness testing.** Segment-level bias testing (region,
  gender, caste proxies), drift monitoring, and a challenger model are required
  before this touches a real decision; `v_reason_code_frequency` and the
  assessment log are the foundations for that governance work.
* **Hyper-parameters** were chosen by a small measured sweep on synthetic data;
  they are not the result of a proper search.

### What was verified, and how

Everything claimed above was measured on this checkout, not assumed:

| Claim | How it was checked |
|---|---|
| Model trains and separates risk | `python train_model.py` report: AUC 0.861, KS 0.570, tier default rates 6.7% / 21.9% / 62.0% |
| SHAP explains the *serving* model | `test_shap_values_sum_to_the_model_margin`: base + ΣSHAP == `predict(output_margin=True)` to 1e-4 |
| API scoring and simulation | live `uvicorn` on :8000, exercised with real HTTP POSTs (all three demo files, four simulator scenarios, evidence refusals) |
| Dashboard renders and works | headless Chrome through `verify-dashboard.mjs`: 16/16 checks, dial score 645 matching the readout, simulator +96 pts |
| Scorecard direction | unit tests pin monotonicity and the 680/580 cut-offs |
| Schema matches the ORM | `check_schema_consistency.py`: 4 tables, 4 views, 6 enums |

The DDL in `db/schema.sql` has **not** been executed against a live PostgreSQL
server (none was available in the build environment); it is parsed and
cross-checked against the ORM models, not run. Apply it on a real instance
before relying on it.

### Production hardening roadmap

1. Score real historical files; recalibrate PD and re-anchor the score bands.
2. Add probability calibration + a holdout monitoring window per cohort.
3. Bias/fairness testing per segment and region; document adverse-action codes.
4. AuthN/AuthZ (officer roles), PII encryption, request audit logging.
5. Move the artifact to a registry with signed versions and staged rollout.
6. Feed live AA/UPI/utility data instead of officer declarations, and reconcile.

---

## 10. Repository layout

```
main.py                           root ASGI entry point (`uvicorn main:app`)
train_model.py                    CLI: generate data -> train -> evaluate -> save artifacts
ml/                               offline + shared scoring library
  config.py                       feature contract, scorecard constants, credit policy
  data_generator.py               synthetic portfolio with a latent risk process
  features.py                     ratios + one-hot, frozen column order
  scoring.py                      PD -> score, tiers, limits, evidence policy
  explain.py                      SHAP -> grouped, signed, human-readable reasons
  train.py                        XGBoost training, metrics, artifact persistence
backend/                          FastAPI service
  main.py                         routes, lifespan, CORS
  schemas.py                      request/response contracts + validation rules
  service.py                      scoring + simulation orchestration
  model_registry.py               artifact loading, version checks, hot reload
  db.py                           SQLAlchemy persistence (optional)
  config.py                       env-driven settings (ACS_*)
db/schema.sql                     PostgreSQL DDL, indexes, triggers, views
frontend/                         Next.js 16 + Tailwind v4 underwriting console
  src/lib/                        API client, types, formatting, form mapping
  src/components/                 dashboard, form, dial, tier badge, SHAP, simulator
  scripts/verify-dashboard.mjs    headless-browser end-to-end UI check
tests/                            pytest suite (90 tests)
scripts/check_schema_consistency.py  DDL vs. ORM drift check
scripts/probe_samples.py          dev helper: score candidate demo profiles
artifacts/                        credit_model.pkl, metrics, importance (generated)
data/                             synthetic_portfolio.csv (generated, auditable input)
```

> **Reminder:** the disclaimer in the dashboard footer is deliberate. This
> prototype must not be used for live credit decisions without validation on the
> institution's own portfolio.
