"use client";

/**
 * Bank officer underwriting dashboard.
 *
 * Owns all application state, calls the scoring API and composes the panels:
 *   application form -> score dial + tier -> credit policy -> SHAP reasons -> what-if.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { ApplicantForm } from "@/components/ApplicantForm";
import { PolicyPanel } from "@/components/PolicyPanel";
import { RiskTierBadge, RiskTierPanel } from "@/components/RiskTierBadge";
import { ScoreDial } from "@/components/ScoreDial";
import { ShapBreakdown } from "@/components/ShapBreakdown";
import { WhatIfSimulator } from "@/components/WhatIfSimulator";
import { API_BASE, ApiError, api } from "@/lib/api";
import { EMPTY_FORM, formatDateTime } from "@/lib/format";
import { formToPayload, payloadToForm, validateForm } from "@/lib/form";
import type {
  ApplicantCategory,
  HealthResponse,
  ModelInfoResponse,
  SampleApplicant,
  ScoreFormState,
  ScoreRequestBody,
  ScoreResponse,
} from "@/lib/types";

export function UnderwritingDashboard() {
  const [form, setForm] = useState<ScoreFormState>(EMPTY_FORM);
  const [result, setResult] = useState<ScoreResponse | null>(null);
  const [scoredPayload, setScoredPayload] = useState<ScoreRequestBody | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [persist, setPersist] = useState(false);
  const [samples, setSamples] = useState<SampleApplicant[]>([]);
  const [modelInfo, setModelInfo] = useState<ModelInfoResponse | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);

  // Load demo files plus model provenance once, when the dashboard mounts.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [sampleList, info, healthResponse] = await Promise.all([
          api.samples(),
          api.modelInfo(),
          api.health(),
        ]);
        if (cancelled) return;
        setSamples(sampleList);
        setModelInfo(info);
        setHealth(healthResponse);
      } catch (caught) {
        if (cancelled) return;
        setError(caught instanceof ApiError ? caught.message : "Could not reach the scoring API.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleFieldChange = useCallback((key: keyof ScoreFormState, value: string) => {
    setForm((current) => ({ ...current, [key]: value }));
  }, []);

  const handleCategoryChange = useCallback((category: ApplicantCategory) => {
    setForm((current) => ({ ...current, applicant_category: category }));
    setResult(null);
    setScoredPayload(null);
  }, []);

  const handleSubmit = useCallback(async () => {
    const validationError = validateForm(form);
    if (validationError) {
      setError(validationError);
      return;
    }
    setLoading(true);
    setError(null);
    const payload = formToPayload(form, { persist });
    try {
      const scored = await api.score(payload);
      setResult(scored);
      setScoredPayload(payload);
    } catch (caught) {
      setResult(null);
      setScoredPayload(null);
      setError(
        caught instanceof ApiError
          ? [caught.message, ...(caught.fields ?? [])].join(" ")
          : "Scoring failed unexpectedly.",
      );
    } finally {
      setLoading(false);
    }
  }, [form, persist]);

  const handleLoadSample = useCallback((sample: SampleApplicant) => {
    setForm(payloadToForm(sample.payload));
    setResult(null);
    setScoredPayload(null);
    setError(null);
  }, []);

  const handleReset = useCallback(() => {
    setForm(EMPTY_FORM);
    setResult(null);
    setScoredPayload(null);
    setError(null);
  }, []);

  const healthPill = useMemo(() => {
    if (!health) return { text: "API unknown", className: "bg-slate-700 text-slate-200" };
    if (health.model_loaded) return { text: `Model ready · ${API_BASE}`, className: "bg-emerald-500/15 text-emerald-300" };
    return { text: "Model not loaded", className: "bg-rose-500/15 text-rose-300" };
  }, [health]);

  return (
    <div className="min-h-screen bg-slate-100">
      <header className="border-b border-slate-800 bg-slate-900">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div>
            <h1 className="text-base font-semibold text-white">
              Alternative Credit Scoring · Underwriting Console
            </h1>
            <p className="text-xs text-slate-400">
              Score farmers and MSME borrowers on declared assets and alternative cash flow, with
              SHAP-backed reasons.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[11px]">
            <span className={`rounded-full px-2.5 py-1 font-medium ${healthPill.className}`}>
              {healthPill.text}
            </span>
            {modelInfo && (
              <>
                <span className="rounded-full bg-slate-800 px-2.5 py-1 font-medium text-slate-300">
                  AUC {modelInfo.test_metrics.roc_auc?.toFixed(3) ?? "—"} · KS{" "}
                  {modelInfo.test_metrics.ks?.toFixed(3) ?? "—"}
                </span>
                <span className="rounded-full bg-slate-800 px-2.5 py-1 font-medium text-slate-300">
                  {modelInfo.feature_count} features · trained{" "}
                  {formatDateTime(modelInfo.trained_at).split(",")[0]}
                </span>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-[1400px] grid-cols-1 gap-4 px-4 py-5 lg:grid-cols-12">
        <section className="lg:col-span-5">
          <ApplicantForm
            form={form}
            onChange={handleFieldChange}
            onCategoryChange={handleCategoryChange}
            onSubmit={handleSubmit}
            onReset={handleReset}
            onLoadSample={handleLoadSample}
            samples={samples}
            loading={loading}
            error={error}
            persist={persist}
            onPersistChange={setPersist}
          />
        </section>

        <section className="space-y-4 lg:col-span-7">
          {!result && (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white p-10 text-center">
              <p className="text-sm font-semibold text-slate-800">
                Capture a declaration or load a demo file to score an application
              </p>
              <p className="mx-auto mt-1 max-w-lg text-xs leading-relaxed text-slate-500">
                The model reads land, property, machinery, livestock and inventory together with
                alternative cash-flow proxies (UPI turnover, utility payment discipline) and returns
                a 300-900 score, a risk tier, a recommended limit and the top reasons behind the
                decision.
              </p>
              <div className="mx-auto mt-4 grid max-w-xl grid-cols-1 gap-2 text-left sm:grid-cols-3">
                {[
                  { step: "1", text: "Declare assets and cash-flow proxies" },
                  { step: "2", text: "Score, then read the SHAP reasons" },
                  { step: "3", text: "Simulate collateral changes before deciding" },
                ].map((item) => (
                  <div key={item.step} className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200">
                    <span className="text-[10px] font-semibold text-slate-400">STEP {item.step}</span>
                    <p className="mt-0.5 text-xs text-slate-600">{item.text}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {result && (
            <>
              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <h2 className="text-sm font-semibold text-slate-900">
                      {form.full_name || "Applicant"} ·{" "}
                      {result.risk_tier === "LOW"
                        ? "Strong file"
                        : result.risk_tier === "MEDIUM"
                          ? "Review required"
                          : "Weak file"}
                    </h2>
                    <p className="text-xs text-slate-500">
                      Assessment {result.assessment_id.slice(0, 8)} · {formatDateTime(result.scored_at)}{" "}
                      · model {result.model_version} · evidence{" "}
                      {result.data_quality.satisfied_groups}/{result.data_quality.total_groups}
                      {result.persisted && " · saved to audit log"}
                    </p>
                  </div>
                  <RiskTierBadge tier={result.risk_tier} />
                </div>

                <div className="mt-2 grid grid-cols-1 gap-4 lg:grid-cols-2">
                  <ScoreDial
                    score={result.credit_score}
                    band={result.score_band}
                    tier={result.risk_tier}
                    probabilityOfDefault={result.probability_of_default}
                  />
                  <div className="space-y-3">
                    <RiskTierPanel
                      tier={result.risk_tier}
                      decision={result.decision}
                      score={result.credit_score}
                      band={result.score_band}
                    />

                    {result.risk_tier !== result.model_risk_tier && (
                      <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
                        <p className="text-xs font-semibold text-amber-900">
                          Evidence overlay: capped at {result.tier_label}
                        </p>
                        <p className="mt-1 text-[11px] leading-relaxed text-amber-800">
                          The model alone rates this file {result.model_risk_tier}, but the declared
                          evidence base is incomplete, so automated pre-approval is withheld.
                        </p>
                        <ul className="mt-1.5 list-inside list-disc space-y-0.5 text-[11px] text-amber-800">
                          {result.data_quality.warnings.map((warning) => (
                            <li key={warning}>{warning}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    <dl className="grid grid-cols-2 gap-2 text-xs">
                      <div className="rounded-lg bg-slate-50 p-2.5">
                        <dt className="text-[10px] uppercase tracking-wide text-slate-500">
                          Repayment probability
                        </dt>
                        <dd className="mt-0.5 text-lg font-semibold tabular-nums text-slate-900">
                          {(result.probability_of_repayment * 100).toFixed(1)}%
                        </dd>
                      </div>
                      <div className="rounded-lg bg-slate-50 p-2.5">
                        <dt className="text-[10px] uppercase tracking-wide text-slate-500">
                          Score band
                        </dt>
                        <dd className="mt-0.5 text-lg font-semibold tabular-nums text-slate-900">
                          {result.credit_score}
                          <span className="text-xs font-normal text-slate-500"> / 900</span>
                        </dd>
                      </div>
                    </dl>
                  </div>
                </div>
              </div>

              <PolicyPanel result={result} />

              <ShapBreakdown
                factors={result.explainability.all_factors}
                summary={result.explainability.summary}
                totalPoints={result.explainability.score_impact_total_points}
              />

              {/* Keyed on the assessment so a new score starts from a clean
                  simulator rather than showing the previous file's scenario. */}
              {scoredPayload && (
                <WhatIfSimulator key={result.assessment_id} basePayload={scoredPayload} />
              )}
            </>
          )}
        </section>
      </main>

      <footer className="mx-auto max-w-[1400px] px-4 pb-8 pt-2 text-[11px] text-slate-500">
        Prototype for demonstration. Scores are produced by a synthetic-data model
        ({modelInfo?.model_library ?? "XGBoost"}) and must not be used for live credit decisions
        without validation on the institution&apos;s own portfolio.
      </footer>
    </div>
  );
}
