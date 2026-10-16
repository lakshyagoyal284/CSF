"use client";

/** Credit policy panel: the recommended facility, why it is that size, and the
 *  derived ratios the decision rests on. */

import { RATIO_FIELDS, bindingLabel, formatINR, formatPercent, formatRatio } from "@/lib/format";
import type { ScoreResponse } from "@/lib/types";

function Metric({
  label,
  value,
  hint,
  emphasis,
}: {
  label: string;
  value: string;
  hint?: string;
  emphasis?: boolean;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3" title={hint}>
      <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p
        className={`mt-1 tabular-nums ${emphasis ? "text-lg font-semibold text-slate-900" : "text-sm font-medium text-slate-800"}`}
      >
        {value}
      </p>
    </div>
  );
}

export function PolicyPanel({ result }: { result: ScoreResponse }) {
  const bindingIsIncome = result.binding_constraint === "income";

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Recommended facility</h3>
            <p className="text-xs text-slate-500">
              Lower of the collateral cap and the repayment-capacity cap, haircut by risk tier.
            </p>
          </div>
          <div className="text-right">
            <p className="text-2xl font-semibold tabular-nums text-slate-900">
              {formatINR(result.recommended_credit_limit)}
            </p>
            <p className="text-[11px] text-slate-500">
              incremental {formatINR(result.recommended_incremental_limit)} after existing debt
            </p>
          </div>
        </div>

        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Metric label="Collateral cap" value={formatINR(result.collateral_cap)} hint="Pledged value × loan-to-value" />
          <Metric
            label="Income cap"
            value={formatINR(result.income_cap)}
            hint="Facility whose debt service fits the share of income the policy allows"
          />
          <Metric label="LTV applied" value={formatPercent(result.ltv_applied, 0)} hint="Segment loan-to-value" />
          <Metric
            label="Rate band p.a."
            value={`${result.indicative_rate_band.min_annual_rate.toFixed(1)}-${result.indicative_rate_band.max_annual_rate.toFixed(1)}%`}
            hint="Indicative pricing for this tier"
          />
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-md bg-slate-100 px-2 py-1 font-medium text-slate-700">
            Binding constraint: {bindingLabel(result.binding_constraint)}
          </span>
          <span
            className={`rounded-md px-2 py-1 font-medium ${
              result.requested_amount_supported
                ? "bg-emerald-50 text-emerald-700"
                : "bg-amber-50 text-amber-700"
            }`}
          >
            {result.requested_amount_supported
              ? "Requested amount fully supported"
              : "Requested amount exceeds the policy limit"}
          </span>
          <span className="rounded-md bg-slate-100 px-2 py-1 font-medium text-slate-600" title={`Constraint driver: ${result.binding_constraint}`}>
            {bindingIsIncome
              ? "Cash flow is the bottleneck, not collateral"
              : "Collateral is the bottleneck, not cash flow"}
          </span>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-slate-900">Derived financial ratios</h3>
        <p className="text-xs text-slate-500">
          The ratios the model scored, computed from the declared inputs.
        </p>
        <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
          {RATIO_FIELDS.map((field) => (
            <div key={field.key} className="flex items-baseline justify-between gap-3 border-b border-dashed border-slate-200 py-1 last:border-0">
              <dt className="text-xs text-slate-600" title={field.hint}>
                {field.label}
              </dt>
              <dd className="text-xs font-semibold tabular-nums text-slate-800">
                {formatRatio(field.key, result.derived_ratios[field.key])}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
