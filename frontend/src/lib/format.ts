/** Presentation helpers: Indian currency notation, percentages, tier styling
 *  and the declarative field catalogue the application form renders from. */

import type { RiskTier, ScoreFormState } from "./types";

/** Render INR the way an Indian credit officer reads it (lakh / crore). */
export function formatINR(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const absolute = Math.abs(value);
  if (absolute >= 1_00_00_000) return `₹${(value / 1_00_00_000).toFixed(2)} Cr`;
  if (absolute >= 1_00_000) return `₹${(value / 1_00_000).toFixed(2)} L`;
  if (absolute >= 1_000) return `₹${(value / 1_000).toFixed(1)} K`;
  return `₹${value.toFixed(0)}`;
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Colour system for the three risk tiers, shared by every component so a tier
 *  always looks the same across the dashboard. */
export const TIER_STYLES: Record<
  RiskTier,
  {
    label: string;
    text: string;
    bg: string;
    border: string;
    ring: string;
    dot: string;
    solid: string;
    headline: string;
  }
> = {
  LOW: {
    label: "Pre-Approved",
    text: "text-emerald-800",
    bg: "bg-emerald-50",
    border: "border-emerald-200",
    ring: "ring-emerald-500/30",
    dot: "bg-emerald-500",
    solid: "#059669",
    headline: "Eligible for automatic approval within the recommended limit.",
  },
  MEDIUM: {
    label: "Manual Review",
    text: "text-amber-800",
    bg: "bg-amber-50",
    border: "border-amber-200",
    ring: "ring-amber-500/30",
    dot: "bg-amber-500",
    solid: "#d97706",
    headline: "Refer to the credit officer: mitigants or a smaller facility recommended.",
  },
  HIGH: {
    label: "High Risk",
    text: "text-rose-800",
    bg: "bg-rose-50",
    border: "border-rose-200",
    ring: "ring-rose-500/30",
    dot: "bg-rose-500",
    solid: "#e11d48",
    headline: "Decline, or sanction only against full collateral cover.",
  },
};

const DECISION_LABELS: Record<string, string> = {
  PRE_APPROVED: "Pre-approved",
  MANUAL_REVIEW: "Manual review",
  DECLINE_OR_SECURED_ONLY: "Decline / secured only",
};

export function decisionLabel(decision: string): string {
  return DECISION_LABELS[decision] ?? decision;
}

export function bindingLabel(binding: string): string {
  if (binding === "collateral") return "Pledged collateral (LTV cap)";
  if (binding === "income") return "Repayment capacity (income cap)";
  return binding;
}

/** Ratio fields surfaced from the API, with display metadata. */
export const RATIO_FIELDS: Array<{ key: string; label: string; hint: string }> = [
  { key: "total_collateral_value", label: "Total collateral", hint: "Land + property + equipment + livestock + inventory" },
  { key: "collateral_coverage_ratio", label: "Collateral cover", hint: "Collateral ÷ requested facility" },
  { key: "debt_to_asset_ratio", label: "Debt-to-asset", hint: "Existing debt ÷ tangible assets" },
  { key: "debt_service_ratio", label: "Debt service ratio", hint: "Existing EMI ÷ monthly income" },
  { key: "proposed_debt_service_ratio", label: "Proposed debt service", hint: "Existing EMI + new instalment ÷ monthly income" },
  { key: "post_facility_loan_to_value", label: "Post-facility leverage", hint: "Existing debt + facility ÷ collateral" },
  { key: "liquidity_ratio", label: "Liquidity buffer", hint: "Bank balance ÷ monthly EMI" },
  { key: "income_to_debt_ratio", label: "Income-to-debt", hint: "Annual income ÷ outstanding debt" },
  { key: "net_worth", label: "Net worth", hint: "Tangible assets − borrowings" },
  { key: "asset_productivity", label: "Asset productivity", hint: "Annual income ÷ asset value" },
  { key: "financial_discipline_score", label: "Financial discipline", hint: "Utility record blend (0-100)" },
];

export function formatRatio(key: string, value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return "—";
  if (key === "total_collateral_value" || key === "net_worth") return formatINR(value);
  if (key === "financial_discipline_score") return `${value.toFixed(0)}/100`;
  if (key.endsWith("_ratio") && key.includes("debt") && !key.includes("to_debt")) {
    return formatPercent(value);
  }
  return `${value.toFixed(2)}x`;
}

/** A blank application, used for the initial form and the reset button. */
export const EMPTY_FORM: ScoreFormState = {
  applicant_category: "farmer",
  region_tier: "rural",
  crop_type: "wheat",
  shop_space_ownership: "owned",
  full_name: "",
  age: "",
  dependents: "",
  years_in_operation: "",
  land_size_acres: "",
  irrigation_score: "",
  soil_quality_score: "",
  crop_yield_annual_value: "",
  land_market_value: "",
  property_value: "",
  equipment_value: "",
  livestock_value: "",
  shop_area_sqft: "",
  inventory_value: "",
  monthly_upi_turnover: "",
  utility_payment_consistency_score: "",
  utility_payment_delays_12m: "",
  avg_monthly_bank_balance: "",
  annual_income_proxy: "",
  requested_loan_amount: "",
  loan_tenure_months: "36",
  outstanding_debt: "",
  monthly_emi_obligation: "",
};

export interface FieldSpec {
  key: keyof ScoreFormState;
  label: string;
  placeholder?: string;
  hint: string;
  segment: "all" | "farmer" | "business";
  money?: boolean;
}

/** The application form is data-driven from this catalogue, so adding a
 *  declared input is a one-line change that the API contract then validates. */
export const FIELD_GROUPS: Array<{ title: string; subtitle: string; fields: FieldSpec[] }> = [
  {
    title: "Borrower",
    subtitle: "Identity and segment - decides which collateral fields apply.",
    fields: [
      { key: "full_name", label: "Applicant name", hint: "As per KYC", segment: "all" },
      { key: "age", label: "Age", placeholder: "e.g. 46", hint: "Years", segment: "all" },
      { key: "dependents", label: "Dependents", placeholder: "e.g. 4", hint: "Consumption pressure on income", segment: "all" },
      { key: "years_in_operation", label: "Years in operation", placeholder: "e.g. 14", hint: "Track record of the enterprise", segment: "all" },
    ],
  },
  {
    title: "Land & farm assets",
    subtitle: "Declared cultivation and farming collateral.",
    fields: [
      { key: "land_size_acres", label: "Land holding", placeholder: "e.g. 4.5", hint: "Acres owned/leased", segment: "farmer" },
      { key: "irrigation_score", label: "Irrigation score", placeholder: "0 - 100", hint: "Field-survey score", segment: "farmer" },
      { key: "soil_quality_score", label: "Soil quality", placeholder: "0 - 100", hint: "Field-survey score", segment: "farmer" },
      { key: "crop_yield_annual_value", label: "Crop value (12m)", placeholder: "e.g. 236000", hint: "Last 12 months harvest value", segment: "farmer", money: true },
      { key: "land_market_value", label: "Land market value", placeholder: "e.g. 1450000", hint: "Circle-rate valuation", segment: "farmer", money: true },
      { key: "livestock_value", label: "Livestock value", placeholder: "e.g. 180000", hint: "Cattle, goats, poultry", segment: "farmer", money: true },
    ],
  },
  {
    title: "Shop & business assets",
    subtitle: "Trading premises and stock for MSME borrowers.",
    fields: [
      { key: "shop_area_sqft", label: "Shop area", placeholder: "e.g. 300", hint: "Square feet", segment: "business" },
      { key: "inventory_value", label: "Inventory value", placeholder: "e.g. 520000", hint: "Saleable stock at market value", segment: "business", money: true },
    ],
  },
  {
    title: "Shared collateral",
    subtitle: "Property and equipment pledged for either segment.",
    fields: [
      { key: "property_value", label: "Property value", placeholder: "e.g. 520000", hint: "Owned house or premises", segment: "all", money: true },
      { key: "equipment_value", label: "Equipment & machinery", placeholder: "e.g. 760000", hint: "Tractor, pumps, refrigeration", segment: "all", money: true },
    ],
  },
  {
    title: "Alternative cash flow",
    subtitle: "The evidence that replaces a salary slip or bureau score.",
    fields: [
      { key: "monthly_upi_turnover", label: "Monthly UPI turnover", placeholder: "e.g. 168000", hint: "Average digital collections", segment: "all", money: true },
      { key: "utility_payment_consistency_score", label: "Utility consistency", placeholder: "0 - 100", hint: "On-time electricity/water payments", segment: "all" },
      { key: "utility_payment_delays_12m", label: "Utility delays (12m)", placeholder: "e.g. 3", hint: "Late payments in the last year", segment: "all" },
      { key: "avg_monthly_bank_balance", label: "Avg bank balance", placeholder: "e.g. 22000", hint: "6-month average", segment: "all", money: true },
      { key: "annual_income_proxy", label: "Annual income proxy", placeholder: "e.g. 300000", hint: "Reconstructed from crop sales or UPI margin", segment: "all", money: true },
    ],
  },
  {
    title: "Credit ask",
    subtitle: "The facility requested and the existing debt burden.",
    fields: [
      { key: "requested_loan_amount", label: "Requested amount", placeholder: "e.g. 240000", hint: "Required by the model", segment: "all", money: true },
      { key: "loan_tenure_months", label: "Tenure", placeholder: "36", hint: "Months (6-360)", segment: "all" },
      { key: "outstanding_debt", label: "Outstanding debt", placeholder: "e.g. 90000", hint: "All live borrowings", segment: "all", money: true },
      { key: "monthly_emi_obligation", label: "Monthly EMI", placeholder: "e.g. 2400", hint: "Current repayment burden", segment: "all", money: true },
    ],
  },
];
