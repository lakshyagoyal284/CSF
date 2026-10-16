"use client";

/**
 * What-if simulator.
 *
 * Lets an officer answer "what changes the decision?" before negotiating with
 * the borrower. Levers are prefilled from the application, and only fields that
 * actually differ are sent as overrides - so the audit trail shows the real
 * change, not a re-declaration of the whole file.
 */

import { useMemo, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { TIER_STYLES, formatINR, formatPercent } from "@/lib/format";
import type {
  ScoreRequestBody,
  SimulateRequestBody,
  SimulateResponse,
} from "@/lib/types";

interface LeverSpec {
  key: string;
  label: string;
  hint: string;
  money?: boolean;
}

const LEVERS: LeverSpec[] = [
  { key: "inventory_value", label: "Inventory value", hint: "Re-valued stock", money: true },
  { key: "land_market_value", label: "Land value", hint: "Fresh circle-rate valuation", money: true },
  { key: "equipment_value", label: "Equipment value", hint: "Additional machinery pledged", money: true },
  { key: "annual_income_proxy", label: "Annual income proxy", hint: "Reconstructed income", money: true },
  { key: "monthly_upi_turnover", label: "Monthly UPI turnover", hint: "Digital collection volume", money: true },
  { key: "utility_payment_consistency_score", label: "Utility consistency", hint: "0-100 payment score" },
  { key: "outstanding_debt", label: "Outstanding debt", hint: "Repaid or newly discovered debt", money: true },
  { key: "requested_loan_amount", label: "Requested amount", hint: "Facility size", money: true },
  { key: "loan_tenure_months", label: "Tenure (months)", hint: "Repayment period" },
];

const PRESETS: Array<{ label: string; description: string; overrides: Record<string, number> }> = [
  { label: "Inventory +25%", description: "Stock revaluation goes in the borrower's favour", overrides: { inventory_value_uplift_pct: 25 } },
  { label: "Pledge more collateral +20%", description: "Property, land, equipment and livestock", overrides: { collateral_value_uplift_pct: 20 } },
  { label: "Income +15%", description: "Verified income higher than declared", overrides: { income_uplift_pct: 15 } },
  { label: "Clear utility delays", description: "Perfect payment record for 12 months", overrides: { utility_payment_delays_12m: 0, utility_payment_consistency_score: 95 } },
];

function baseValueOf(payload: ScoreRequestBody, key: string): number | null {
  const assets = payload.assets as Record<string, unknown>;
  const cashflow = payload.cashflow as Record<string, unknown>;
  // `credit` is a fixed, typed shape; read it explicitly for type safety.
  if (key === "requested_loan_amount") return payload.credit.requested_loan_amount;
  if (key === "loan_tenure_months") return payload.credit.loan_tenure_months;
  if (key === "outstanding_debt") return payload.credit.outstanding_debt ?? null;
  if (key in cashflow) return (cashflow[key] as number | null) ?? null;
  if (key in assets) return (assets[key] as number | null) ?? null;
  return null;
}

function formatOverrideValue(key: string, value: unknown): string {
  if (value === null || value === undefined) return "not on file";
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return String(value);
  const moneyLike = /amount|value|debt|emi|balance|turnover|income|proxy/.test(key);
  return moneyLike ? formatINR(numeric) : numeric.toLocaleString("en-IN");
}

export function WhatIfSimulator({ basePayload }: { basePayload: ScoreRequestBody }) {
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [presetOverrides, setPresetOverrides] = useState<Record<string, number>>({});
  const [result, setResult] = useState<SimulateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Stale what-ifs mislead, so the dashboard remounts this panel (via `key`)
  // whenever a new application is scored. Resetting through a key keeps the
  // component free of the "set state in an effect" anti-pattern.

  const overrides = useMemo(() => {
    const computed: Record<string, number> = { ...presetOverrides };
    for (const lever of LEVERS) {
      const raw = edits[lever.key];
      if (raw === undefined || raw.trim() === "") continue;
      const numeric = Number(raw);
      if (!Number.isFinite(numeric)) continue;
      const base = baseValueOf(basePayload, lever.key);
      if (base !== null && Math.abs(base - numeric) < 1e-9) continue; // unchanged
      computed[lever.key] = numeric;
    }
    return computed;
  }, [edits, presetOverrides, basePayload]);

  const changedCount = Object.keys(overrides).length;

  async function run() {
    if (changedCount === 0) {
      setError("Change a value or apply a preset to simulate a scenario.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const body: SimulateRequestBody = {
        applicant: basePayload.applicant,
        assets: basePayload.assets,
        cashflow: basePayload.cashflow,
        credit: basePayload.credit,
        overrides,
      };
      setResult(await api.simulate(body));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Simulation failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">What-if simulator</h3>
          <p className="text-xs text-slate-500">
            Re-score this file with modified collateral or cash-flow assumptions.
          </p>
        </div>
        {changedCount > 0 && (
          <span className="rounded-md bg-slate-900 px-2 py-0.5 text-[11px] font-semibold text-white">
            {changedCount} change{changedCount === 1 ? "" : "s"} pending
          </span>
        )}
      </div>

      <div className="mt-3">
        <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
          Quick scenarios
        </p>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {PRESETS.map((preset) => {
            const active = JSON.stringify(presetOverrides) === JSON.stringify(preset.overrides);
            return (
              <button
                key={preset.label}
                type="button"
                title={preset.description}
                onClick={() => setPresetOverrides(active ? {} : preset.overrides)}
                className={`rounded-md border px-2 py-1 text-[11px] font-medium transition ${
                  active
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-300 bg-white text-slate-700 hover:border-slate-900"
                }`}
              >
                {preset.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
        {LEVERS.map((lever) => {
          const base = baseValueOf(basePayload, lever.key);
          return (
            <label key={lever.key} className="block">
              <span className="block truncate text-[10px] font-medium uppercase tracking-wide text-slate-500">
                {lever.label}
              </span>
              <input
                type="number"
                step="any"
                title={`${lever.hint}. Current: ${formatOverrideValue(lever.key, base)}`}
                placeholder={base === null ? "not on file" : String(base)}
                value={edits[lever.key] ?? ""}
                onChange={(event) =>
                  setEdits((current) => ({ ...current, [lever.key]: event.target.value }))
                }
                className="mt-0.5 w-full rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs text-slate-900 tabular-nums outline-none focus:border-slate-900"
              />
            </label>
          );
        })}
      </div>

      {error && <p className="mt-2 text-xs text-rose-700">{error}</p>}

      <button
        type="button"
        onClick={run}
        disabled={loading}
        className="mt-3 w-full rounded-lg border border-slate-900 bg-white px-4 py-2 text-sm font-semibold text-slate-900 transition hover:bg-slate-900 hover:text-white disabled:opacity-60"
      >
        {loading ? "Simulating…" : "Run simulation"}
      </button>

      {result && (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-2 gap-2">
            {[
              { title: "Baseline", data: result.baseline, muted: true },
              { title: "Scenario", data: result.simulated, muted: false },
            ].map(({ title, data, muted }) => (
              <div
                key={title}
                className={`rounded-lg border p-3 ${
                  muted ? "border-slate-200 bg-slate-50" : "border-slate-900/15 bg-slate-900/[0.03]"
                }`}
              >
                <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
                  {title}
                </p>
                <p className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">
                  {data.credit_score}
                </p>
                <span
                  className={`mt-1 inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                    TIER_STYLES[data.risk_tier].bg
                  } ${TIER_STYLES[data.risk_tier].text}`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full ${TIER_STYLES[data.risk_tier].dot}`} />
                  {TIER_STYLES[data.risk_tier].label}
                </span>
                <p className="mt-1.5 text-[11px] text-slate-500">
                  Limit {formatINR(data.recommended_credit_limit)} · PD{" "}
                  {formatPercent(data.probability_of_default)}
                </p>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap gap-1.5 text-[11px]">
            <span
              className={`rounded-md px-2 py-1 font-semibold ${
                result.delta.score_change > 0
                  ? "bg-emerald-50 text-emerald-700"
                  : result.delta.score_change < 0
                    ? "bg-rose-50 text-rose-700"
                    : "bg-slate-100 text-slate-600"
              }`}
            >
              Score {result.delta.score_change > 0 ? "+" : ""}
              {result.delta.score_change} pts
            </span>
            <span className="rounded-md bg-slate-100 px-2 py-1 font-medium text-slate-700">
              Limit {result.delta.recommended_limit_change > 0 ? "+" : ""}
              {formatINR(result.delta.recommended_limit_change)}
            </span>
            <span className="rounded-md bg-slate-100 px-2 py-1 font-medium text-slate-700">
              PD {(result.delta.probability_of_default_change * 100).toFixed(1)} pp
            </span>
            {result.delta.tier_changed && (
              <span className="rounded-md bg-slate-900 px-2 py-1 font-semibold text-white">
                Tier {result.delta.previous_tier} → {result.delta.new_tier}
              </span>
            )}
          </div>

          <p className="rounded-lg bg-slate-50 p-3 text-xs leading-relaxed text-slate-600 ring-1 ring-slate-200">
            {result.narrative}
          </p>

          {Object.keys(result.applied_overrides).length > 0 && (
            <div>
              <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
                Applied changes
              </p>
              <ul className="mt-1 space-y-0.5">
                {Object.entries(result.applied_overrides).map(([key, change]) => (
                  <li key={key} className="flex justify-between gap-3 text-xs text-slate-600">
                    <span className="truncate">{key.replace(/_/g, " ")}</span>
                    <span className="shrink-0 font-medium tabular-nums text-slate-800">
                      {formatOverrideValue(key, change.from)} → {formatOverrideValue(key, change.to)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {result.impact_breakdown.length > 0 && (
            <div>
              <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
                What moved
              </p>
              <ul className="mt-1 space-y-1">
                {result.impact_breakdown.slice(0, 5).map((item) => (
                  <li key={item.feature} className="flex items-center justify-between gap-3 text-xs">
                    <span className="truncate text-slate-600">{item.label}</span>
                    <span
                      className={`shrink-0 rounded px-1.5 py-0.5 font-semibold tabular-nums ${
                        item.delta_points > 0
                          ? "bg-emerald-50 text-emerald-700"
                          : "bg-rose-50 text-rose-700"
                      }`}
                    >
                      {item.delta_points > 0 ? "+" : ""}
                      {item.delta_points} pts
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
