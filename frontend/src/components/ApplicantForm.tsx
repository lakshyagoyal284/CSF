"use client";

/** Loan officer data-capture form. Fields are rendered from the catalogue in
 *  `lib/format.ts`, filtered by borrower segment (farmer vs. small business). */

import { FIELD_GROUPS, type FieldSpec } from "@/lib/format";
import type {
  ApplicantCategory,
  CropType,
  RegionTier,
  SampleApplicant,
  ScoreFormState,
  ShopOwnership,
} from "@/lib/types";

const REGION_OPTIONS: Array<{ value: RegionTier; label: string }> = [
  { value: "rural", label: "Rural" },
  { value: "semi_urban", label: "Semi-urban" },
  { value: "urban", label: "Urban" },
];

const CROP_OPTIONS: Array<{ value: CropType; label: string }> = [
  { value: "rice", label: "Rice" },
  { value: "wheat", label: "Wheat" },
  { value: "cotton", label: "Cotton" },
  { value: "sugarcane", label: "Sugarcane" },
  { value: "horticulture", label: "Horticulture" },
  { value: "pulses", label: "Pulses" },
];

const OWNERSHIP_OPTIONS: Array<{ value: ShopOwnership; label: string }> = [
  { value: "owned", label: "Owned" },
  { value: "rented", label: "Rented" },
];

function Field({
  spec,
  value,
  onChange,
}: {
  spec: FieldSpec;
  value: string;
  onChange: (key: keyof ScoreFormState, value: string) => void;
}) {
  const isText = spec.key === "full_name";
  return (
    <label className="block">
      <span className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
          {spec.label}
        </span>
        {spec.money && <span className="text-[10px] text-slate-400">INR</span>}
      </span>
      <input
        type={isText ? "text" : "number"}
        inputMode={isText ? "text" : "decimal"}
        step="any"
        value={value}
        placeholder={spec.placeholder}
        title={spec.hint}
        onChange={(event) => onChange(spec.key, event.target.value)}
        className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-900 tabular-nums shadow-sm outline-none transition focus:border-slate-900 focus:ring-2 focus:ring-slate-900/10"
      />
      <span className="mt-0.5 block truncate text-[10px] text-slate-400" title={spec.hint}>
        {spec.hint}
      </span>
    </label>
  );
}

export function ApplicantForm({
  form,
  onChange,
  onCategoryChange,
  onSubmit,
  onReset,
  onLoadSample,
  samples,
  loading,
  error,
  persist,
  onPersistChange,
}: {
  form: ScoreFormState;
  onChange: (key: keyof ScoreFormState, value: string) => void;
  onCategoryChange: (category: ApplicantCategory) => void;
  onSubmit: () => void;
  onReset: () => void;
  onLoadSample: (sample: SampleApplicant) => void;
  samples: SampleApplicant[];
  loading: boolean;
  error: string | null;
  persist: boolean;
  onPersistChange: (value: boolean) => void;
}) {
  const isFarmer = form.applicant_category === "farmer";

  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">Loan application</h2>
            <p className="text-xs text-slate-500">
              Declared assets and alternative cash-flow evidence. Blank fields are treated as
              &ldquo;not on file&rdquo;.
            </p>
          </div>
          <div className="inline-flex rounded-lg border border-slate-300 bg-slate-50 p-0.5">
            {(
              [
                { value: "farmer" as const, label: "Farmer" },
                { value: "small_business" as const, label: "Shop / MSME" },
              ]
            ).map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => onCategoryChange(option.value)}
                className={`rounded-md px-3 py-1 text-xs font-semibold transition ${
                  form.applicant_category === option.value
                    ? "bg-slate-900 text-white shadow-sm"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        {samples.length > 0 && (
          <div className="mt-3 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-2.5">
            <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
              Load a demo file
            </p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {samples.map((sample) => (
                <button
                  key={sample.id}
                  type="button"
                  onClick={() => onLoadSample(sample)}
                  title={sample.description}
                  className="rounded-md border border-slate-300 bg-white px-2 py-1 text-[11px] font-medium text-slate-700 transition hover:border-slate-900 hover:text-slate-900"
                >
                  {sample.label.split(" - ")[0]}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {FIELD_GROUPS.map((group) => {
        const fields = group.fields.filter(
          (field) =>
            field.segment === "all" ||
            (field.segment === "farmer" && isFarmer) ||
            (field.segment === "business" && !isFarmer),
        );
        if (!fields.length) return null;

        return (
          <div key={group.title} className="rounded-xl border border-slate-200 bg-white p-4">
            <h3 className="text-sm font-semibold text-slate-900">{group.title}</h3>
            <p className="text-xs text-slate-500">{group.subtitle}</p>
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
              {fields.map((spec) => (
                <Field
                  key={spec.key}
                  spec={spec}
                  value={form[spec.key]}
                  onChange={onChange}
                />
              ))}

              {group.title === "Borrower" && (
                <>
                  <label className="block">
                    <span className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
                      Region
                    </span>
                    <select
                      value={form.region_tier}
                      onChange={(event) => onChange("region_tier", event.target.value)}
                      className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-900 shadow-sm outline-none focus:border-slate-900"
                    >
                      {REGION_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                    <span className="mt-0.5 block text-[10px] text-slate-400">
                      Drives land values and cost structure
                    </span>
                  </label>

                  {isFarmer ? (
                    <label className="block">
                      <span className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
                        Primary crop
                      </span>
                      <select
                        value={form.crop_type}
                        onChange={(event) => onChange("crop_type", event.target.value)}
                        className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-900 shadow-sm outline-none focus:border-slate-900"
                      >
                        {CROP_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <span className="mt-0.5 block text-[10px] text-slate-400">
                        Seasonality and yield profile
                      </span>
                    </label>
                  ) : (
                    <label className="block">
                      <span className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
                        Premises ownership
                      </span>
                      <select
                        value={form.shop_space_ownership}
                        onChange={(event) => onChange("shop_space_ownership", event.target.value)}
                        className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-900 shadow-sm outline-none focus:border-slate-900"
                      >
                        {OWNERSHIP_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <span className="mt-0.5 block text-[10px] text-slate-400">
                        Owned premises count as collateral
                      </span>
                    </label>
                  )}
                </>
              )}
            </div>
          </div>
        );
      })}

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800">
          {error}
        </div>
      )}

      <div className="sticky bottom-0 rounded-xl border border-slate-200 bg-white/95 p-3 backdrop-blur">
        <label className="mb-3 flex items-center gap-2 text-xs text-slate-600">
          <input
            type="checkbox"
            checked={persist}
            onChange={(event) => onPersistChange(event.target.checked)}
            className="h-3.5 w-3.5 rounded border-slate-300"
          />
          Record this assessment in the audit log (requires PostgreSQL)
        </label>
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={loading}
            className="flex-1 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? "Scoring…" : "Score application"}
          </button>
          <button
            type="button"
            onClick={onReset}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-900 hover:text-slate-900"
          >
            Reset
          </button>
        </div>
      </div>
    </form>
  );
}
