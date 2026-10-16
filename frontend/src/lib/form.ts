/** Conversion between the form's string state and the API's JSON payload.
 *
 * Two rules matter here:
 *  1. An empty input becomes `null` ("not on file"), never `0` - the model
 *     treats missing data differently from a declared zero.
 *  2. Segment-specific fields are explicitly cleared for the wrong segment, so
 *     the API's consistency validator never rejects a farmer for declaring a
 *     shop area.
 */

import { EMPTY_FORM } from "./format";
import type { ScoreFormState, ScoreRequestBody } from "./types";

function numOrNull(raw: string): number | null {
  if (raw === undefined || raw === null) return null;
  const trimmed = String(raw).trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

export function formToPayload(
  form: ScoreFormState,
  options: { persist?: boolean; scoredBy?: string | null } = {},
): ScoreRequestBody {
  const isFarmer = form.applicant_category === "farmer";

  return {
    applicant: {
      applicant_category: form.applicant_category,
      region_tier: form.region_tier,
      crop_type: isFarmer ? form.crop_type : "not_applicable",
      full_name: form.full_name.trim() || null,
      age: numOrNull(form.age),
      dependents: numOrNull(form.dependents),
      years_in_operation: numOrNull(form.years_in_operation),
    },
    assets: {
      land_size_acres: isFarmer ? numOrNull(form.land_size_acres) : null,
      irrigation_score: isFarmer ? numOrNull(form.irrigation_score) : null,
      soil_quality_score: isFarmer ? numOrNull(form.soil_quality_score) : null,
      crop_yield_annual_value: isFarmer ? numOrNull(form.crop_yield_annual_value) : null,
      land_market_value: isFarmer ? numOrNull(form.land_market_value) : null,
      livestock_value: isFarmer ? numOrNull(form.livestock_value) : null,
      shop_area_sqft: isFarmer ? null : numOrNull(form.shop_area_sqft),
      inventory_value: isFarmer ? null : numOrNull(form.inventory_value),
      shop_space_ownership: isFarmer ? "not_applicable" : form.shop_space_ownership,
      property_value: numOrNull(form.property_value),
      equipment_value: numOrNull(form.equipment_value),
    },
    cashflow: {
      monthly_upi_turnover: numOrNull(form.monthly_upi_turnover),
      utility_payment_consistency_score: numOrNull(form.utility_payment_consistency_score),
      utility_payment_delays_12m: numOrNull(form.utility_payment_delays_12m),
      avg_monthly_bank_balance: numOrNull(form.avg_monthly_bank_balance),
      annual_income_proxy: numOrNull(form.annual_income_proxy),
    },
    credit: {
      requested_loan_amount: numOrNull(form.requested_loan_amount) ?? 0,
      loan_tenure_months: numOrNull(form.loan_tenure_months) ?? 36,
      outstanding_debt: numOrNull(form.outstanding_debt) ?? 0,
      monthly_emi_obligation: numOrNull(form.monthly_emi_obligation) ?? 0,
    },
    ...(options.persist !== undefined ? { persist: options.persist } : {}),
    ...(options.scoredBy ? { scored_by: options.scoredBy } : {}),
  };
}

/** Client-side guard so an obviously invalid file never leaves the browser. */
export function validateForm(form: ScoreFormState): string | null {
  const requested = numOrNull(form.requested_loan_amount);
  if (requested === null || requested <= 0) {
    return "Requested loan amount is required and must be greater than zero.";
  }
  const tenure = numOrNull(form.loan_tenure_months);
  if (tenure !== null && (tenure < 6 || tenure > 360)) {
    return "Loan tenure must be between 6 and 360 months.";
  }
  const utility = numOrNull(form.utility_payment_consistency_score);
  if (utility !== null && (utility < 0 || utility > 100)) {
    return "Utility payment consistency score must be between 0 and 100.";
  }
  return null;
}

/** Hydrate the form from a sample payload returned by the API. */
export function payloadToForm(payload: ScoreRequestBody): ScoreFormState {
  const assets = (payload.assets ?? {}) as Record<string, number | string | null>;
  const cashflow = (payload.cashflow ?? {}) as Record<string, number | null>;
  const asText = (value: unknown): string =>
    value === null || value === undefined ? "" : String(value);

  const isFarmer = payload.applicant.applicant_category === "farmer";
  return {
    ...EMPTY_FORM,
    applicant_category: payload.applicant.applicant_category,
    region_tier: payload.applicant.region_tier,
    crop_type: isFarmer ? (payload.applicant.crop_type ?? "wheat") : EMPTY_FORM.crop_type,
    shop_space_ownership: isFarmer
      ? EMPTY_FORM.shop_space_ownership
      : ((assets.shop_space_ownership as ScoreFormState["shop_space_ownership"]) ?? "rented"),
    full_name: payload.applicant.full_name ?? "",
    age: asText(payload.applicant.age),
    dependents: asText(payload.applicant.dependents),
    years_in_operation: asText(payload.applicant.years_in_operation),
    land_size_acres: asText(assets.land_size_acres),
    irrigation_score: asText(assets.irrigation_score),
    soil_quality_score: asText(assets.soil_quality_score),
    crop_yield_annual_value: asText(assets.crop_yield_annual_value),
    land_market_value: asText(assets.land_market_value),
    property_value: asText(assets.property_value),
    equipment_value: asText(assets.equipment_value),
    livestock_value: asText(assets.livestock_value),
    shop_area_sqft: asText(assets.shop_area_sqft),
    inventory_value: asText(assets.inventory_value),
    monthly_upi_turnover: asText(cashflow.monthly_upi_turnover),
    utility_payment_consistency_score: asText(cashflow.utility_payment_consistency_score),
    utility_payment_delays_12m: asText(cashflow.utility_payment_delays_12m),
    avg_monthly_bank_balance: asText(cashflow.avg_monthly_bank_balance),
    annual_income_proxy: asText(cashflow.annual_income_proxy),
    requested_loan_amount: asText(payload.credit.requested_loan_amount),
    loan_tenure_months: asText(payload.credit.loan_tenure_months),
    outstanding_debt: asText(payload.credit.outstanding_debt),
    monthly_emi_obligation: asText(payload.credit.monthly_emi_obligation),
  };
}
