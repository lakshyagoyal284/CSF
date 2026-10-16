"use client";

/**
 * Credit score dial (300-900).
 *
 * The gauge is drawn as three coloured arcs whose boundaries come from the
 * API's own tier cut-offs, so the dial can never disagree with the score band
 * the underwriting policy actually used.
 */

import { TIER_STYLES } from "@/lib/format";
import type { ScoreBand } from "@/lib/types";

const CENTER = { x: 130, y: 132 };
const RADIUS = 102;
const STROKE = 15;

function polar(radius: number, degrees: number) {
  const radians = (degrees * Math.PI) / 180;
  return { x: CENTER.x + radius * Math.cos(radians), y: CENTER.y - radius * Math.sin(radians) };
}

/** Arc from a start angle (180 = left) to an end angle (0 = right). */
function arcPath(radius: number, startDeg: number, endDeg: number): string {
  const start = polar(radius, startDeg);
  const end = polar(radius, endDeg);
  const largeArc = Math.abs(endDeg - startDeg) > 180 ? 1 : 0;
  return `M ${start.x} ${start.y} A ${radius} ${radius} 0 ${largeArc} 1 ${end.x} ${end.y}`;
}

export function ScoreDial({
  score,
  band,
  tier,
  probabilityOfDefault,
}: {
  score: number;
  band: ScoreBand;
  tier: keyof typeof TIER_STYLES;
  probabilityOfDefault?: number;
}) {
  const span = band.score_max - band.score_min;
  const toAngle = (value: number) =>
    180 - 180 * Math.min(Math.max((value - band.score_min) / span, 0), 1);

  const angle = toAngle(score);
  const needle = polar(RADIUS - 22, angle);
  const highEnd = toAngle(Math.max(band.medium_risk_min - 1, band.score_min));
  const midEnd = toAngle(Math.max(band.low_risk_min - 1, band.score_min));

  // Small gaps between bands keep the three segments visually distinct.
  const gap = 1.2;
  const segments = [
    { from: 180, to: highEnd + gap, color: TIER_STYLES.HIGH.solid, tier: "HIGH" as const },
    { from: highEnd + gap, to: midEnd + gap, color: TIER_STYLES.MEDIUM.solid, tier: "MEDIUM" as const },
    { from: midEnd + gap, to: 0, color: TIER_STYLES.LOW.solid, tier: "LOW" as const },
  ];

  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 260 176" className="w-full max-w-[320px]" role="img"
        aria-label={`Credit score ${score} out of 900, risk tier ${tier}`}>
        {/* unfilled track */}
        <path
          d={arcPath(RADIUS, 180, 0)}
          fill="none"
          stroke="#e2e8f0"
          strokeWidth={STROKE}
          strokeLinecap="round"
        />
        {segments.map((segment) => (
          <path
            key={segment.tier}
            d={arcPath(RADIUS, segment.from, segment.to)}
            fill="none"
            stroke={segment.color}
            strokeWidth={STROKE}
            strokeLinecap="round"
            opacity={segment.tier === tier ? 1 : 0.35}
          />
        ))}

        {/* band boundary ticks + labels */}
        {[
          { value: band.score_min, deg: 180 },
          { value: band.medium_risk_min, deg: toAngle(band.medium_risk_min) },
          { value: band.low_risk_min, deg: toAngle(band.low_risk_min) },
          { value: band.score_max, deg: 0 },
        ].map((tick) => {
          const outer = polar(RADIUS + STROKE / 2 + 2, tick.deg);
          const inner = polar(RADIUS - STROKE / 2 - 2, tick.deg);
          const labelPos = polar(RADIUS + 20, tick.deg);
          return (
            <g key={tick.value}>
              <line x1={inner.x} y1={inner.y} x2={outer.x} y2={outer.y}
                stroke="#94a3b8" strokeWidth={1.5} />
              <text x={labelPos.x} y={labelPos.y} textAnchor="middle" dominantBaseline="middle"
                className="fill-slate-500 text-[9px] font-medium">
                {tick.value}
              </text>
            </g>
          );
        })}

        {/* needle */}
        <line x1={CENTER.x} y1={CENTER.y} x2={needle.x} y2={needle.y}
          stroke="#0f172a" strokeWidth={3.5} strokeLinecap="round" />
        <circle cx={CENTER.x} cy={CENTER.y} r={7} fill="#0f172a" />
        <circle cx={CENTER.x} cy={CENTER.y} r={3} fill="#f8fafc" />

        {/* score readout */}
        <text x={CENTER.x} y={CENTER.y - 34} textAnchor="middle"
          className="fill-slate-900 text-[40px] font-semibold tabular-nums">
          {score}
        </text>
        <text x={CENTER.x} y={CENTER.y - 12} textAnchor="middle"
          className="fill-slate-500 text-[9px] font-medium uppercase tracking-widest">
          Credit score
        </text>
      </svg>

      <div className="mt-1 flex items-center gap-3 text-[11px] text-slate-500">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full" style={{ background: TIER_STYLES.HIGH.solid }} />
          High &lt; {band.medium_risk_min}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full" style={{ background: TIER_STYLES.MEDIUM.solid }} />
          {band.medium_risk_min}-{band.low_risk_min - 1}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full" style={{ background: TIER_STYLES.LOW.solid }} />
          Low ≥ {band.low_risk_min}
        </span>
      </div>

      {probabilityOfDefault !== undefined && (
        <p className="mt-2 text-xs text-slate-500">
          Modelled probability of default{" "}
          <span className="font-semibold text-slate-700 tabular-nums">
            {(probabilityOfDefault * 100).toFixed(1)}%
          </span>
        </p>
      )}
    </div>
  );
}
