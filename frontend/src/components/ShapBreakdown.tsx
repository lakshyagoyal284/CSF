"use client";

/**
 * Feature breakdown: why the model produced this score.
 *
 * Each factor is shown as a bar measured in *score points* - the same unit as
 * the dial - so an officer can see that "Debt Service Ratio -42" is what stands
 * between this file and the next tier. Green bars push the score up, red bars
 * pull it down; the panel is fed straight from the API's SHAP output.
 */

import { useState } from "react";

import type { ShapFactor } from "@/lib/types";

function FactorBar({ factor, maxAbs, highlight }: { factor: ShapFactor; maxAbs: number; highlight: boolean }) {
  const points = factor.score_impact_points;
  const widthPercent = Math.min(Math.abs(points) / maxAbs, 1) * 50;
  const reducesRisk = factor.direction === "reduces_risk";

  return (
    <div className={`rounded-lg border p-3 ${highlight ? "border-slate-300 bg-white shadow-sm" : "border-slate-200 bg-white/60"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-slate-800" title={factor.description ?? undefined}>
            {factor.label}
          </p>
          <p className="mt-0.5 truncate text-xs text-slate-500">{factor.value ?? "—"}</p>
        </div>
        <span
          className={`shrink-0 rounded-md px-2 py-0.5 text-xs font-semibold tabular-nums ${
            reducesRisk ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"
          }`}
        >
          {points > 0 ? "+" : ""}
          {points} pts
        </span>
      </div>

      <div className="relative mt-2 h-2 rounded-full bg-slate-100">
        <div className="absolute left-1/2 top-[-4px] h-4 w-px bg-slate-300" />
        <div
          className={`absolute top-0 h-2 rounded-full ${reducesRisk ? "bg-emerald-500" : "bg-rose-500"}`}
          style={{
            width: `${widthPercent}%`,
            left: reducesRisk ? "50%" : `${50 - widthPercent}%`,
          }}
        />
      </div>
    </div>
  );
}

export function ShapBreakdown({
  factors,
  summary,
  totalPoints,
}: {
  factors: ShapFactor[];
  summary?: string;
  totalPoints?: number;
}) {
  const [expanded, setExpanded] = useState(false);

  if (!factors.length) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-500">
        No explanations available for this application.
      </div>
    );
  }

  // Only factors that actually moved the score are worth an officer's time.
  const material = factors.filter((factor) => Math.abs(factor.score_impact_points) >= 1);
  const visible = expanded ? material : material.slice(0, 6);
  const maxAbs = Math.max(...material.map((factor) => Math.abs(factor.score_impact_points)), 1);

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Feature breakdown</h3>
          <p className="text-xs text-slate-500">
            SHAP contribution of each declared factor, in credit-score points versus the
            portfolio average.
          </p>
        </div>
        {totalPoints !== undefined && (
          <span className="shrink-0 rounded-md bg-slate-900 px-2 py-1 text-[11px] font-semibold text-white tabular-nums">
            {totalPoints > 0 ? "+" : ""}
            {totalPoints} pts net
          </span>
        )}
      </div>

      {summary && (
        <p className="mt-3 rounded-lg bg-white p-3 text-xs leading-relaxed text-slate-600 ring-1 ring-slate-200">
          {summary}
        </p>
      )}

      <div className="mt-3 space-y-2">
        {visible.map((factor, index) => (
          <FactorBar key={factor.feature} factor={factor} maxAbs={maxAbs} highlight={index < 3} />
        ))}
      </div>

      {material.length > 6 && (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="mt-3 text-xs font-medium text-slate-600 underline decoration-dotted underline-offset-2 hover:text-slate-900"
        >
          {expanded ? "Show top factors only" : `Show all ${material.length} factors`}
        </button>
      )}
    </div>
  );
}
