/**
 * Types mirroring the FastAPI contracts in `backend/schemas.py`.
 *
 * Keep these in sync with the API: they are the only place the dashboard
 * learns the shape of a score response.
 */

export type ApplicantCategory = "farmer" | "small_business";
export type RegionTier = "rural" | "semi_urban" | "urban";
export type ShopOwnership = "owned" | "rented" | "not_applicable";
export type CropType =
  | "rice"
  | "wheat"
  | "cotton"
  | "sugarcane"
  | "horticulture"
  | "pulses"
  | "not_applicable";
export type RiskTier = "LOW" | "MEDIUM" | "HIGH";
export type Direction = "reduces_risk" | "increases_risk";

/** Flat form state. Numeric fields are held as strings so an empty input can
 *  mean "not on file", which the model treats as missing rather than zero. */
export interface ScoreFormState {
  applicant_category: ApplicantCategory;
  region_tier: RegionTier;
  crop_type: CropType;
  shop_space_ownership: ShopOwnership;
  full_name: string;
  age: string;
  dependents: string;
  years_in_operation: string;

  land_size_acres: string;
  irrigation_score: string;
  soil_quality_score: string;
  crop_yield_annual_value: string;
  land_market_value: string;
  property_value: string;
  equipment_value: string;
  livestock_value: string;
  shop_area_sqft: string;
  inventory_value: string;

  monthly_upi_turnover: string;
  utility_payment_consistency_score: string;
  utility_payment_delays_12m: string;
  avg_monthly_bank_balance: string;
  annual_income_proxy: string;

  requested_loan_amount: string;
  loan_tenure_months: string;
  outstanding_debt: string;
  monthly_emi_obligation: string;
}

/** Request body for `POST /api/score`. */
export interface ScoreRequestBody {
  applicant: {
    applicant_category: ApplicantCategory;
    region_tier: RegionTier;
    crop_type?: CropType;
    full_name?: string | null;
    age?: number | null;
    dependents?: number | null;
    years_in_operation?: number | null;
  };
  assets: Record<string, number | ShopOwnership | null>;
  cashflow: Record<string, number | null>;
  credit: {
    requested_loan_amount: number;
    loan_tenure_months: number;
    outstanding_debt: number | null;
    monthly_emi_obligation: number | null;
  };
  persist?: boolean;
  scored_by?: string | null;
}

/** What-if overrides for `POST /api/simulate`. */
export interface SimulationOverrides {
  [key: string]: number | undefined;
}

export interface SimulateRequestBody extends ScoreRequestBody {
  overrides: SimulationOverrides;
}

export interface ShapFactor {
  feature: string;
  label: string;
  description?: string | null;
  value?: string | null;
  score_impact_points: number;
  contribution_log_odds: number;
  direction: Direction;
  magnitude: number;
  narrative?: string | null;
}

export interface Explainability {
  base_value_log_odds: number;
  score_impact_total_points: number;
  top_factors: ShapFactor[];
  positive_factors: ShapFactor[];
  negative_factors: ShapFactor[];
  all_factors: ShapFactor[];
  summary: string;
}

export interface DataQuality {
  completeness_ratio: number;
  satisfied_groups: number;
  total_groups: number;
  missing_evidence: string[];
  warnings: string[];
  allows_pre_approval: boolean;
}

export interface ScoreBand {
  low_risk_min: number;
  medium_risk_min: number;
  score_min: number;
  score_max: number;
}

export interface ScoreResponse {
  assessment_id: string;
  scored_at: string;
  model_version: string;
  credit_score: number;
  score_band: ScoreBand;
  probability_of_repayment: number;
  probability_of_default: number;  risk_tier: RiskTier;
  /** Tier from the model alone, before the evidence-quality overlay. */
  model_risk_tier: RiskTier;
  tier_label: string;
  decision: string;
  data_quality: DataQuality;

  recommended_credit_limit: number;
  recommended_incremental_limit: number;
  collateral_cap: number;
  income_cap: number;
  binding_constraint: string;
  ltv_applied: number;
  requested_amount_supported: boolean;
  indicative_rate_band: { min_annual_rate: number; max_annual_rate: number };
  derived_ratios: Record<string, number>;
  explainability: Explainability;
  persisted: boolean;
}

export interface FactorDelta {
  feature: string;
  label: string;
  baseline_points: number;
  simulated_points: number;
  delta_points: number;
}

export interface SimulateResponse {
  baseline: ScoreResponse;
  simulated: ScoreResponse;
  delta: {
    score_change: number;
    probability_of_default_change: number;
    recommended_limit_change: number;
    tier_changed: boolean;
    decision_changed: boolean;
    previous_tier: RiskTier;
    new_tier: RiskTier;
  };
  applied_overrides: Record<string, { from: unknown; to: unknown }>;
  impact_breakdown: FactorDelta[];
  narrative: string;
}

export interface SampleApplicant {
  id: string;
  label: string;
  description: string;
  payload: ScoreRequestBody;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  model_loaded: boolean;
  model_path: string;
  persistence_enabled: boolean;
  database_connected: boolean;
  detail: string | null;
}

export interface ModelInfoResponse {
  engine_version: string;
  trained_at: string;
  feature_count: number;
  model_library: string;
  test_metrics: {
    roc_auc?: number;
    ks?: number;
    gini?: number;
    brier_score?: number;
    accounts?: number;
    default_rate?: number;
  };
  scorecard: {
    tier_thresholds?: { score_low_min: number; score_medium_min: number };
    tier_counts?: Record<string, number>;
  };
  top_drivers: Array<{ feature: string; label: string; mean_abs_log_odds: number; direction: string }>;
  data_report: Record<string, unknown>;
}
