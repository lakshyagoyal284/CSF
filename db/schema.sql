-- ===========================================================================
--  Alternative Credit Scoring Engine - PostgreSQL schema
--  Target: PostgreSQL 13+ (uses IDENTITY columns, JSONB, generated columns)
--
--  Design notes
--  ------------
--  * Four core tables mirror the underwriting workflow:
--      applicants               who is asking, and for which segment
--      asset_records            what tangible collateral backs the facility
--      cashflow_proxies         alternative cash-flow evidence (UPI / utility)
--      credit_assessment_logs   the score, the reasons, and the officer's action
--  * Monetary amounts are NUMERIC(16,2) (INR). NUMERIC, never float, so rupee
--    arithmetic in reports is exact.
--  * Anything a human eye cannot interpret without the model is stored as JSONB
--    (SHAP summaries, the exact input payload) so the decision is reproducible
--    years later, when the model version is long gone.
--  * The script is idempotent: safe to re-run in a demo or a fresh environment.
--
--  Usage:
--      createdb credit_scoring
--      psql -d credit_scoring -f db/schema.sql
-- ===========================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 0. Enum types
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'applicant_category') THEN
        CREATE TYPE applicant_category AS ENUM ('farmer', 'small_business');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'region_tier') THEN
        CREATE TYPE region_tier AS ENUM ('rural', 'semi_urban', 'urban');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'shop_ownership') THEN
        CREATE TYPE shop_ownership AS ENUM ('owned', 'rented', 'not_applicable');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'crop_type') THEN
        CREATE TYPE crop_type AS ENUM (
            'rice', 'wheat', 'cotton', 'sugarcane', 'horticulture', 'pulses', 'not_applicable'
        );
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'risk_tier') THEN
        CREATE TYPE risk_tier AS ENUM ('LOW', 'MEDIUM', 'HIGH');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'underwriting_decision') THEN
        CREATE TYPE underwriting_decision AS ENUM (
            'PRE_APPROVED', 'MANUAL_REVIEW', 'DECLINE_OR_SECURED_ONLY'
        );
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 1. applicants - personal and segment information
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS applicants (
    applicant_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    external_ref        VARCHAR(64) UNIQUE,               -- core-banking / LOS id
    full_name           VARCHAR(160) NOT NULL,
    phone               VARCHAR(20),
    applicant_category  applicant_category NOT NULL,
    region_tier         region_tier NOT NULL,
    date_of_birth       DATE,
    age                 SMALLINT   CHECK (age IS NULL OR age BETWEEN 18 AND 110),
    dependents          SMALLINT   CHECK (dependents IS NULL OR dependents BETWEEN 0 AND 30),
    years_in_operation  NUMERIC(5,1) CHECK (years_in_operation IS NULL OR years_in_operation >= 0),
    primary_crop        crop_type  DEFAULT 'not_applicable',
    -- KYC / consent trail: alternative-data scoring must record consent.
    consent_reference   VARCHAR(80),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT applicants_phone_format CHECK (phone IS NULL OR phone ~ '^[0-9+\- ]{8,20}$')
);

COMMENT ON TABLE applicants IS
    'Borrower master record. `applicant_category` drives which collateral fields '
    'are applicable and which loan-to-value the credit policy applies.';

CREATE INDEX IF NOT EXISTS idx_applicants_category_region
    ON applicants (applicant_category, region_tier);
CREATE INDEX IF NOT EXISTS idx_applicants_name
    ON applicants (lower(full_name));

-- ---------------------------------------------------------------------------
-- 2. asset_records - declared tangible collateral
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS asset_records (
    asset_record_id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    applicant_id            BIGINT NOT NULL REFERENCES applicants (applicant_id) ON DELETE CASCADE,

    -- farming collateral
    land_size_acres         NUMERIC(10,2) CHECK (land_size_acres IS NULL OR land_size_acres >= 0),
    irrigation_score        SMALLINT      CHECK (irrigation_score IS NULL OR irrigation_score BETWEEN 0 AND 100),
    soil_quality_score      SMALLINT      CHECK (soil_quality_score IS NULL OR soil_quality_score BETWEEN 0 AND 100),
    crop_yield_annual_value NUMERIC(16,2) CHECK (crop_yield_annual_value IS NULL OR crop_yield_annual_value >= 0),
    land_market_value       NUMERIC(16,2) CHECK (land_market_value IS NULL OR land_market_value >= 0),

    -- shared collateral
    property_value          NUMERIC(16,2) CHECK (property_value IS NULL OR property_value >= 0),
    equipment_value         NUMERIC(16,2) CHECK (equipment_value IS NULL OR equipment_value >= 0),
    livestock_value         NUMERIC(16,2) CHECK (livestock_value IS NULL OR livestock_value >= 0),

    -- small-business collateral
    shop_area_sqft          NUMERIC(10,2) CHECK (shop_area_sqft IS NULL OR shop_area_sqft >= 0),
    shop_space_ownership    shop_ownership NOT NULL DEFAULT 'not_applicable',
    inventory_value         NUMERIC(16,2) CHECK (inventory_value IS NULL OR inventory_value >= 0),

    -- Declared collateral total, kept consistent by the database rather than by
    -- application code: land + property + equipment + livestock + inventory.
    declared_total_asset_value NUMERIC(18,2) GENERATED ALWAYS AS (
        COALESCE(land_market_value, 0) + COALESCE(property_value, 0) +
        COALESCE(equipment_value, 0)   + COALESCE(livestock_value, 0) +
        COALESCE(inventory_value, 0)
    ) STORED,

    -- provenance: who vouched for these numbers, and how
    assessed_by             VARCHAR(120),
    assessment_method       VARCHAR(40) NOT NULL DEFAULT 'officer_declaration'
                            CHECK (assessment_method IN
                                   ('officer_declaration', 'field_survey', 'circle_rate', 'third_party_valuation')),
    recorded_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE asset_records IS
    'Immutable-ish snapshot of declared collateral at application time. Each '
    'reassessment inserts a new row, so collateral history is preserved.';

CREATE INDEX IF NOT EXISTS idx_asset_records_applicant
    ON asset_records (applicant_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_asset_records_recorded_at
    ON asset_records (recorded_at DESC);

-- ---------------------------------------------------------------------------
-- 3. cashflow_proxies - alternative cash-flow evidence
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS cashflow_proxies (
    cashflow_id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    applicant_id                    BIGINT NOT NULL REFERENCES applicants (applicant_id) ON DELETE CASCADE,

    -- observation window for the proxies below
    period_start                    DATE,
    period_end                      DATE,

    -- digital cash-flow evidence (UPI / account aggregator)
    monthly_upi_turnover            NUMERIC(16,2) CHECK (monthly_upi_turnover IS NULL OR monthly_upi_turnover >= 0),
    upi_txn_count_30d               INTEGER       CHECK (upi_txn_count_30d IS NULL OR upi_txn_count_30d >= 0),
    avg_monthly_bank_balance        NUMERIC(16,2) CHECK (avg_monthly_bank_balance IS NULL OR avg_monthly_bank_balance >= 0),

    -- utility payment behaviour
    utility_payment_consistency_score SMALLINT CHECK (utility_payment_consistency_score IS NULL
                                                      OR utility_payment_consistency_score BETWEEN 0 AND 100),
    utility_payment_delays_12m      SMALLINT CHECK (utility_payment_delays_12m IS NULL
                                                    OR utility_payment_delays_12m BETWEEN 0 AND 24),

    -- income and existing credit exposure
    annual_income_proxy             NUMERIC(16,2) CHECK (annual_income_proxy IS NULL OR annual_income_proxy >= 0),
    outstanding_debt                NUMERIC(16,2) CHECK (outstanding_debt IS NULL OR outstanding_debt >= 0),
    monthly_emi_obligation          NUMERIC(16,2) CHECK (monthly_emi_obligation IS NULL OR monthly_emi_obligation >= 0),
    requested_loan_amount           NUMERIC(16,2) CHECK (requested_loan_amount IS NULL OR requested_loan_amount > 0),
    loan_tenure_months              SMALLINT      CHECK (loan_tenure_months IS NULL
                                                         OR loan_tenure_months BETWEEN 6 AND 360),

    data_source                     VARCHAR(40) NOT NULL DEFAULT 'officer_declaration'
                                    CHECK (data_source IN
                                           ('upi_ledger', 'utility_board', 'account_aggregator',
                                            'field_survey', 'officer_declaration')),
    captured_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT cashflow_period_order CHECK (
        period_start IS NULL OR period_end IS NULL OR period_start <= period_end
    )
);

COMMENT ON TABLE cashflow_proxies IS
    'Alternative cash-flow evidence used in place of a bureau score: digital '
    'collection volume, utility payment discipline, reconstructed income and '
    'existing debt burden.';

CREATE INDEX IF NOT EXISTS idx_cashflow_applicant
    ON cashflow_proxies (applicant_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_cashflow_source
    ON cashflow_proxies (data_source);

-- ---------------------------------------------------------------------------
-- 4. credit_assessment_logs - score, reasons and officer action (audit trail)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS credit_assessment_logs (
    assessment_id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    applicant_id                BIGINT NOT NULL REFERENCES applicants (applicant_id) ON DELETE CASCADE,

    -- model provenance: a score is meaningless without the version that made it
    model_version               VARCHAR(64) NOT NULL,
    engine_version              VARCHAR(24),

    -- outcome
    credit_score                SMALLINT NOT NULL CHECK (credit_score BETWEEN 300 AND 900),
    probability_of_repayment    NUMERIC(7,6) CHECK (probability_of_repayment BETWEEN 0 AND 1),
    probability_of_default      NUMERIC(7,6) CHECK (probability_of_default BETWEEN 0 AND 1),
    risk_tier                   risk_tier NOT NULL,
    decision                    underwriting_decision NOT NULL,

    -- recommended facility and the constraint that produced it
    recommended_credit_limit      NUMERIC(16,2) CHECK (recommended_credit_limit >= 0),
    recommended_incremental_limit NUMERIC(16,2) CHECK (recommended_incremental_limit >= 0),
    collateral_cap                NUMERIC(16,2),
    income_cap                    NUMERIC(16,2),
    binding_constraint            VARCHAR(16) CHECK (binding_constraint IN ('collateral', 'income')),
    ltv_applied                   NUMERIC(5,3) CHECK (ltv_applied BETWEEN 0 AND 1),
    requested_amount_supported    BOOLEAN,
    indicative_rate_min           NUMERIC(5,2),
    indicative_rate_max           NUMERIC(5,2),

    -- explainability (XAI): ratios, ranked reasons, full SHAP summary
    derived_ratios              JSONB NOT NULL DEFAULT '{}'::jsonb,
    shap_summary                JSONB NOT NULL DEFAULT '{}'::jsonb,
    shap_top_factors            JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- reproducibility: the exact feature payload that produced this score
    input_payload               JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- what-if runs are logged but flagged, so they never pollute real decisions
    is_simulation               BOOLEAN NOT NULL DEFAULT FALSE,
    simulated_from_id           BIGINT REFERENCES credit_assessment_logs (assessment_id) ON DELETE SET NULL,

    -- human accountability
    scored_by                   VARCHAR(120),
    officer_remarks             TEXT,
    scored_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT assessment_rate_band CHECK (
        indicative_rate_min IS NULL OR indicative_rate_max IS NULL
        OR indicative_rate_min <= indicative_rate_max
    ),
    CONSTRAINT assessment_simulation_source CHECK (
        (is_simulation = FALSE AND simulated_from_id IS NULL)
        OR (is_simulation = TRUE)
    )
);

COMMENT ON TABLE credit_assessment_logs IS
    'One row per scoring event. Stores the score, the recommended limit, the '
    'SHAP reason codes (JSONB) and the exact input payload, so any decision can '
    'be re-derived and defended to an auditor or a regulator.';

CREATE INDEX IF NOT EXISTS idx_assessment_applicant_time
    ON credit_assessment_logs (applicant_id, scored_at DESC);
CREATE INDEX IF NOT EXISTS idx_assessment_tier_time
    ON credit_assessment_logs (risk_tier, scored_at DESC);
CREATE INDEX IF NOT EXISTS idx_assessment_score
    ON credit_assessment_logs (credit_score);
CREATE INDEX IF NOT EXISTS idx_assessment_scored_at
    ON credit_assessment_logs (scored_at DESC);
-- JSONB containment queries (e.g. "find files where Inventory Value was a top reason")
CREATE INDEX IF NOT EXISTS idx_assessment_shap_gin
    ON credit_assessment_logs USING GIN (shap_top_factors jsonb_path_ops);

-- ---------------------------------------------------------------------------
-- 5. updated_at maintenance
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_applicants_updated_at ON applicants;
CREATE TRIGGER trg_applicants_updated_at
    BEFORE UPDATE ON applicants
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 6. Reporting views
-- ---------------------------------------------------------------------------

-- Latest assessment per applicant, with the borrower attached.
CREATE OR REPLACE VIEW v_latest_credit_assessment AS
SELECT
    a.applicant_id,
    a.external_ref,
    a.full_name,
    a.applicant_category,
    a.region_tier,
    l.credit_score,
    l.probability_of_default,
    l.risk_tier,
    l.decision,
    l.recommended_credit_limit,
    l.binding_constraint,
    l.model_version,
    l.scored_at,
    l.shap_top_factors
FROM applicants a
JOIN LATERAL (
    SELECT *
    FROM credit_assessment_logs cal
    WHERE cal.applicant_id = a.applicant_id
      AND cal.is_simulation = FALSE
    ORDER BY cal.scored_at DESC
    LIMIT 1
) l ON TRUE;

COMMENT ON VIEW v_latest_credit_assessment IS
    'One row per applicant showing their most recent real (non-simulated) score.';

-- Portfolio monitoring: volume, approval mix and expected default by month/tier.
CREATE OR REPLACE VIEW v_portfolio_risk_monitor AS
SELECT
    date_trunc('month', scored_at)          AS scoring_month,
    risk_tier,
    COUNT(*)                                AS files_scored,
    ROUND(AVG(credit_score), 1)             AS avg_score,
    ROUND(AVG(probability_of_default), 4)   AS avg_pd,
    SUM(recommended_credit_limit)           AS total_limit_recommended,
    ROUND(AVG(recommended_credit_limit), 2) AS avg_limit,
    SUM(CASE WHEN decision = 'PRE_APPROVED' THEN 1 ELSE 0 END) AS pre_approved,
    SUM(CASE WHEN decision = 'MANUAL_REVIEW' THEN 1 ELSE 0 END) AS manual_review
FROM credit_assessment_logs
WHERE is_simulation = FALSE
GROUP BY 1, 2;

COMMENT ON VIEW v_portfolio_risk_monitor IS
    'Monthly underwriting funnel by risk tier - the first dashboard a credit '
    'head asks for after go-live.';

-- Reason-code frequency: which factors actually drive adverse decisions.
-- Demonstrates that the SHAP JSONB column is analytically queryable.
CREATE OR REPLACE VIEW v_reason_code_frequency AS
SELECT
    factor ->> 'label'      AS reason_code,
    factor ->> 'direction'  AS direction,
    COUNT(*)                AS appearances,
    ROUND(AVG((factor ->> 'score_impact_points')::numeric), 1) AS avg_score_points,
    MIN(scored_at)          AS first_seen,
    MAX(scored_at)          AS last_seen
FROM credit_assessment_logs,
     LATERAL jsonb_array_elements(shap_top_factors) AS factor
WHERE is_simulation = FALSE
GROUP BY 1, 2;

COMMENT ON VIEW v_reason_code_frequency IS
    'Adverse-action reason-code monitoring across the book (model governance).';

-- ---------------------------------------------------------------------------
-- 7. Convenience: one row per applicant with collateral + cash flow + score
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW v_underwriting_file AS
SELECT
    a.applicant_id,
    a.full_name,
    a.applicant_category,
    a.region_tier,
    ar.land_size_acres,
    ar.declared_total_asset_value,
    ar.shop_space_ownership,
    ar.inventory_value,
    cp.monthly_upi_turnover,
    cp.utility_payment_consistency_score,
    cp.annual_income_proxy,
    cp.outstanding_debt,
    cp.requested_loan_amount,
    l.credit_score,
    l.risk_tier,
    l.decision,
    l.recommended_credit_limit
FROM applicants a
LEFT JOIN LATERAL (
    SELECT * FROM asset_records x
    WHERE x.applicant_id = a.applicant_id
    ORDER BY x.recorded_at DESC LIMIT 1
) ar ON TRUE
LEFT JOIN LATERAL (
    SELECT * FROM cashflow_proxies y
    WHERE y.applicant_id = a.applicant_id
    ORDER BY y.captured_at DESC LIMIT 1
) cp ON TRUE
LEFT JOIN v_latest_credit_assessment l ON l.applicant_id = a.applicant_id;

COMMENT ON VIEW v_underwriting_file IS
    'Denormalised, human-readable underwriting file used by BI tools.';

COMMIT;

-- ===========================================================================
--  Optional follow-up hardening for production
-- ===========================================================================
--  * Row-level security on the four tables so each branch sees only its own book:
--      ALTER TABLE credit_assessment_logs ENABLE ROW LEVEL SECURITY;
--  * Enforce model provenance: reject scores from an unapproved model version
--    with a CHECK on an approved-versions lookup table.
--  * Retention: partition credit_assessment_logs by scored_at month once the
--    table passes ~50M rows.
--  * Make assessment logs append-only for the API role:
--      REVOKE UPDATE, DELETE ON credit_assessment_logs FROM acs_app;
-- ===========================================================================
