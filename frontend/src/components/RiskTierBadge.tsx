"use client";

/** Risk tier indicator: green (pre-approved), amber (manual review), red (high risk). */

import { TIER_STYLES, decisionLabel } from "@/lib/format";
import type { RiskTier } from "@/lib/types";

export function RiskTierBadge({
  tier,
  label,
  size = "md",
}: {
  tier: RiskTier;
  label?: string;
  size?: "sm" | "md";
}) {
  const style = TIER_STYLES[tier];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-semibold ${style.bg} ${style.border} ${style.text} ${
        size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-3 py-1 text-sm"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
      {label ?? style.label}
    </span>
  );
}

export function RiskTierPanel({
  tier,
  decision,
  score,
  band,
}: {
  tier: RiskTier;
  decision: string;
  score: number;
  band: { low_risk_min: number; medium_risk_min: number };
}) {
  const style = TIER_STYLES[tier];
  const pointsToNext =
    tier === "HIGH"
      ? band.medium_risk_min - score
      : tier === "MEDIUM"
        ? band.low_risk_min - score
        : null;

  return (
    <div className={`rounded-xl border p-4 ${style.bg} ${style.border}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className={`h-2.5 w-2.5 rounded-full ${style.dot}`} />
          <span className={`text-base font-semibold ${style.text}`}>{style.label}</span>
        </div>
        <span className={`rounded-md bg-white/70 px-2 py-0.5 text-xs font-semibold ${style.text}`}>
          {decisionLabel(decision)}
        </span>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-slate-600">{style.headline}</p>
      {pointsToNext !== null && pointsToNext > 0 && (
        <p className="mt-2 text-xs font-medium text-slate-700">
          {pointsToNext} more point{pointsToNext === 1 ? "" : "s"} would move this file to the
          next tier.
        </p>
      )}
    </div>
  );
}
