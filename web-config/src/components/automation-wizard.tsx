"use client";

import { ArrowLeft, ArrowRight, Check, CheckCircle2, Plus, RadioTower, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { StatusBadge } from "@/components/status-badge";
import { saveBrowserWatch } from "@/lib/browser-demo";
import { WhatsAppPreview } from "@/components/whatsapp-preview";
import { maskDestination, normalizeTicker } from "@/lib/format";
import type { AutomationTriggers, Horizon, SourceRecord } from "@/lib/types";

const steps = ["Sources", "Stocks & horizon", "Triggers", "WhatsApp & review"];

type Errors = Partial<
  Record<
    "name" | "sources" | "symbols" | "triggers" | "schedule" | "destination" | "submit",
    string
  >
>;

export function AutomationWizard({ sources }: { sources: SourceRecord[] }) {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [name, setName] = useState("Banking watch");
  const [sourceIds, setSourceIds] = useState(["sectors", "bri-danareksa"]);
  const [symbols, setSymbols] = useState(["BBRI"]);
  const [symbolDraft, setSymbolDraft] = useState("");
  const [horizon, setHorizon] = useState<Horizon>("days-to-weeks");
  const [triggers, setTriggers] = useState<AutomationTriggers>({
    sourceMention: false,
    postClose: true,
    priceMove: true,
    priceMoveThreshold: 3,
    filingOrFlow: false,
  });
  const [scheduleTime, setScheduleTime] = useState("15:30");
  const [destination, setDestination] = useState("+62 812 5555 1847");
  const [language, setLanguage] = useState<"id" | "en">("id");
  const [tone, setTone] = useState<"concise" | "beginner" | "analyst">("concise");
  const [errors, setErrors] = useState<Errors>({});
  const [pending, setPending] = useState(false);
  const stepRef = useRef<HTMLDivElement>(null);
  const previousStep = useRef(step);

  useEffect(() => {
    if (previousStep.current !== step) {
      stepRef.current?.querySelector<HTMLElement>(".wizard-heading h2")?.focus();
      previousStep.current = step;
    }
  }, [step]);

  const selectedSources = useMemo(
    () => sources.filter((source) => sourceIds.includes(source.id)),
    [sourceIds, sources],
  );
  const firstSymbol = symbols[0] ?? "BBRI";

  function toggleSource(id: string) {
    if (id === "sectors") return;
    setSourceIds((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );
  }

  function addSymbol() {
    const normalized = normalizeTicker(symbolDraft);
    if (symbols.length >= 6 && !symbols.includes(normalized)) {
      setErrors((current) => ({
        ...current,
        symbols: "This watch has six stocks. Remove one before adding another.",
      }));
      return;
    }
    if (!/^[A-Z]{4}$/.test(normalized)) {
      setErrors((current) => ({
        ...current,
        symbols: "Use a four-letter IDX ticker such as BBRI.",
      }));
      return;
    }
    setSymbols((current) => Array.from(new Set([...current, normalized])).slice(0, 6));
    setSymbolDraft("");
    setErrors((current) => ({ ...current, symbols: undefined }));
  }

  function validateStep(target = step) {
    const next: Errors = {};
    if (target === 0 && (name.trim().length < 3 || name.trim().length > 48))
      next.name = "Use a name between 3 and 48 characters.";
    if (target === 0 && !sourceIds.includes("sectors"))
      next.sources = "Include Sectors to check daily prices.";
    if (target === 1 && symbols.length === 0) next.symbols = "Add at least one IDX ticker.";
    if (
      target === 2 &&
      !Object.entries(triggers).some(
        ([key, value]) => key !== "priceMoveThreshold" && value === true,
      )
    )
      next.triggers = "Enable at least one trigger.";
    if (
      target === 2 &&
      triggers.priceMove &&
      (!Number.isFinite(triggers.priceMoveThreshold) ||
        triggers.priceMoveThreshold < 1 ||
        triggers.priceMoveThreshold > 15)
    )
      next.triggers = "Set a price threshold between 1% and 15%.";
    if (target === 2 && !/^([01]\d|2[0-3]):[0-5]\d$/.test(scheduleTime))
      next.schedule = "Choose a valid daily check time.";
    if (target === 3 && !/^\+?[0-9][0-9\s-]{8,20}$/.test(destination.trim()))
      next.destination = "Enter a WhatsApp number with country code.";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  function goNext() {
    if (!validateStep()) return;
    setStep((current) => Math.min(3, current + 1));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (step < 3) {
      goNext();
      return;
    }
    if (!validateStep(3)) return;
    setPending(true);
    setErrors({});
    try {
      saveBrowserWatch({
        name,
        sourceIds,
        symbols,
        horizon,
        triggers,
        scheduleTime,
        destination,
        language,
        tone,
      });
      router.push("/app/automations?created=1");
    } catch (error) {
      setErrors({
        submit:
          error instanceof Error ? error.message : "Could not save this watch. Please try again.",
      });
      setPending(false);
    }
  }

  return (
    <form className="wizard" onSubmit={submit} noValidate>
      <div className="wizard-main" ref={stepRef}>
        <div className="stepper" aria-label="Automation setup progress">
          <p>
            Step {step + 1} of {steps.length}
          </p>
          <ol>
            {steps.map((label, index) => (
              <li
                className={index <= step ? "complete" : ""}
                aria-current={index === step ? "step" : undefined}
                aria-label={`${index + 1}. ${label}`}
                key={label}
              >
                <span>{index < step ? <Check aria-hidden="true" size={13} /> : index + 1}</span>
                <b>{label}</b>
              </li>
            ))}
          </ol>
        </div>

        {step === 0 ? (
          <section className="wizard-step" aria-labelledby="step-sources">
            <div className="wizard-heading">
              <h2 tabIndex={-1} id="step-sources">
                What should Bursawatch monitor?
              </h2>
              <p>Start with market data, then choose the research sources you follow.</p>
            </div>
            <label className="field-label" htmlFor="automation-name">
              Automation name
            </label>
            <input
              id="automation-name"
              className="text-input"
              maxLength={48}
              value={name}
              onChange={(event) => setName(event.target.value)}
              onBlur={() => validateStep(0)}
              aria-describedby={errors.name ? "name-error" : "name-help"}
              aria-invalid={Boolean(errors.name)}
            />
            <p
              className={errors.name ? "field-error" : "field-help"}
              id={errors.name ? "name-error" : "name-help"}
            >
              {errors.name ?? "A name you’ll recognize, like Banking watch or Long-term portfolio."}
            </p>
            <div className="source-choice-list">
              {sources.map((source) => {
                const selected = sourceIds.includes(source.id);
                const required = source.id === "sectors";
                return (
                  <label
                    className={selected ? "source-choice selected" : "source-choice"}
                    key={source.id}
                  >
                    <input
                      aria-label={`${selected ? "Remove" : "Add"} ${source.name}`}
                      type="checkbox"
                      checked={selected}
                      disabled={required || source.status === "disconnected"}
                      onChange={() => toggleSource(source.id)}
                    />
                    <span className="source-choice-icon">
                      <RadioTower aria-hidden="true" size={19} />
                    </span>
                    <span>
                      <strong>{source.name}</strong>
                      <small>
                        {source.kind === "sectors"
                          ? "Daily market data · Included"
                          : source.description}
                      </small>
                    </span>
                    <StatusBadge status={source.status} />
                  </label>
                );
              })}
            </div>
            {errors.sources ? <p className="field-error">{errors.sources}</p> : null}
          </section>
        ) : null}

        {step === 1 ? (
          <section className="wizard-step" aria-labelledby="step-stocks">
            <div className="wizard-heading">
              <h2 tabIndex={-1} id="step-stocks">
                What should Bursawatch track?
              </h2>
              <p>Add up to six IDX stocks to this watch.</p>
            </div>
            <label className="field-label" htmlFor="symbol">
              Add an IDX ticker
            </label>
            <div className="input-action">
              <input
                id="symbol"
                className="text-input"
                value={symbolDraft}
                onChange={(event) => setSymbolDraft(event.target.value.toUpperCase())}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    addSymbol();
                  }
                }}
                placeholder="e.g. BBRI"
                autoCapitalize="characters"
                maxLength={7}
                aria-describedby="symbol-help"
              />
              <button className="button secondary" type="button" onClick={addSymbol}>
                <Plus aria-hidden="true" size={17} /> Add
              </button>
            </div>
            <p className={errors.symbols ? "field-error" : "field-help"} id="symbol-help">
              {errors.symbols ?? "Four-letter stock codes work best: BBRI, TLKM, or BMRI."}
            </p>
            <div className="selected-symbols" aria-label="Selected stocks">
              {symbols.map((symbol) => (
                <span key={symbol}>
                  {symbol}
                  <button
                    type="button"
                    onClick={() =>
                      setSymbols((current) => current.filter((item) => item !== symbol))
                    }
                    aria-label={`Remove ${symbol}`}
                  >
                    <X aria-hidden="true" size={15} />
                  </button>
                </span>
              ))}
            </div>
            <fieldset className="choice-fieldset">
              <legend>Time horizon</legend>
              <p>Choose how far ahead you’re looking.</p>
              <div className="segmented-choices">
                <label className={horizon === "days-to-weeks" ? "selected" : ""}>
                  <input
                    type="radio"
                    name="horizon"
                    value="days-to-weeks"
                    checked={horizon === "days-to-weeks"}
                    onChange={() => setHorizon("days-to-weeks")}
                  />
                  <strong>Days to weeks</strong>
                  <span>Follow daily price changes.</span>
                </label>
                <label className={horizon === "months-to-years" ? "selected" : ""}>
                  <input
                    type="radio"
                    name="horizon"
                    value="months-to-years"
                    checked={horizon === "months-to-years"}
                    onChange={() => setHorizon("months-to-years")}
                  />
                  <strong>Months to years</strong>
                  <span>Keep a longer-term view of daily changes.</span>
                </label>
              </div>
            </fieldset>
          </section>
        ) : null}

        {step === 2 ? (
          <section className="wizard-step" aria-labelledby="step-triggers">
            <div className="wizard-heading">
              <h2 tabIndex={-1} id="step-triggers">
                When should we check?
              </h2>
              <p>Pick the changes you care about and set a daily check time.</p>
            </div>
            <div className="trigger-list">
              <label className="trigger-row">
                <input type="checkbox" checked={false} readOnly disabled />
                <span>
                  <strong>Research source mentions a watched stock</strong>
                  <small>Research alerts · Coming later</small>
                </span>
              </label>
              <label className="trigger-row">
                <input
                  type="checkbox"
                  checked={triggers.postClose}
                  onChange={(event) =>
                    setTriggers({ ...triggers, postClose: event.target.checked })
                  }
                />
                <span>
                  <strong>After market close on trading days</strong>
                  <small>Daily closing prices · Monday to Friday</small>
                </span>
              </label>
              <div className="trigger-row threshold-row">
                <label>
                  <input
                    type="checkbox"
                    checked={triggers.priceMove}
                    onChange={(event) =>
                      setTriggers({ ...triggers, priceMove: event.target.checked })
                    }
                  />
                  <span>
                    <strong>Material daily price move</strong>
                    <small>Alert when the daily price change reaches your threshold</small>
                  </span>
                </label>
                <div>
                  <input
                    aria-label="Daily price move threshold"
                    type="number"
                    min="1"
                    max="15"
                    step="0.5"
                    value={triggers.priceMoveThreshold}
                    onChange={(event) =>
                      setTriggers({ ...triggers, priceMoveThreshold: Number(event.target.value) })
                    }
                    disabled={!triggers.priceMove}
                  />
                  <span>%</span>
                </div>
              </div>
              <label className="trigger-row">
                <input type="checkbox" checked={false} readOnly disabled />
                <span>
                  <strong>New filing or material foreign-flow change</strong>
                  <small>Filing and flow alerts · Coming later</small>
                </span>
              </label>
            </div>
            {errors.triggers ? (
              <p className="field-error" role="alert">
                {errors.triggers}
              </p>
            ) : null}
            <label className="field-label" htmlFor="schedule-time">
              Daily check time
            </label>
            <div className="schedule-input">
              <input
                className="text-input"
                id="schedule-time"
                type="time"
                value={scheduleTime}
                onChange={(event) => setScheduleTime(event.target.value)}
                aria-invalid={Boolean(errors.schedule)}
                aria-describedby={errors.schedule ? "schedule-error" : undefined}
              />
              <span>WIB · Monday to Friday</span>
            </div>
            {errors.schedule ? (
              <p className="field-error" id="schedule-error" role="alert">
                {errors.schedule}
              </p>
            ) : null}
          </section>
        ) : null}

        {step === 3 ? (
          <section className="wizard-step" aria-labelledby="step-review">
            <div className="wizard-heading">
              <h2 tabIndex={-1} id="step-review">
                Make the brief yours
              </h2>
              <p>Choose a language and tone, then review your brief.</p>
            </div>
            <label className="field-label" htmlFor="destination">
              WhatsApp destination
            </label>
            <input
              id="destination"
              className="text-input"
              type="tel"
              inputMode="tel"
              autoComplete="tel"
              value={destination}
              onChange={(event) => setDestination(event.target.value)}
              onBlur={() => validateStep(3)}
              aria-invalid={Boolean(errors.destination)}
              aria-describedby={errors.destination ? "destination-error" : "destination-help"}
            />
            <p
              className={errors.destination ? "field-error" : "field-help"}
              id={errors.destination ? "destination-error" : "destination-help"}
            >
              {errors.destination ?? `Stored as ${maskDestination(destination)}`}
            </p>
            <div className="two-fields">
              <label>
                <span>Language</span>
                <select
                  value={language}
                  onChange={(event) => setLanguage(event.target.value as "id" | "en")}
                >
                  <option value="id">Bahasa Indonesia</option>
                  <option value="en">English</option>
                </select>
              </label>
              <label>
                <span>Tone</span>
                <select
                  value={tone}
                  onChange={(event) =>
                    setTone(event.target.value as "concise" | "beginner" | "analyst")
                  }
                >
                  <option value="concise">Concise</option>
                  <option value="beginner">Beginner-friendly</option>
                  <option value="analyst">Analyst-style</option>
                </select>
              </label>
            </div>
            <div className="review-summary">
              <div>
                <span>Sources</span>
                <strong>{selectedSources.map((source) => source.name).join(" + ")}</strong>
              </div>
              <div>
                <span>Watchlist</span>
                <strong>{symbols.join(", ")}</strong>
              </div>
              <div>
                <span>Horizon</span>
                <strong>{horizon === "days-to-weeks" ? "Days to weeks" : "Months to years"}</strong>
              </div>
              <div>
                <span>Schedule</span>
                <strong>Trading days · {scheduleTime} WIB</strong>
              </div>
            </div>
            <div className="honesty-note">
              <CheckCircle2 aria-hidden="true" size={20} />
              <p>Pause this watch whenever you need to.</p>
            </div>
          </section>
        ) : null}

        <footer className="wizard-actions">
          <button
            className="button ghost"
            type="button"
            onClick={() => setStep((current) => Math.max(0, current - 1))}
            disabled={step === 0 || pending}
          >
            <ArrowLeft aria-hidden="true" size={18} /> Back
          </button>
          <span>Review before saving.</span>
          {step < 3 ? (
            <button key="continue" className="button primary" type="button" onClick={goNext}>
              Continue <ArrowRight aria-hidden="true" size={18} />
            </button>
          ) : (
            <button key="save" className="button primary" type="submit" disabled={pending}>
              {pending ? "Saving…" : "Save watch"}
              <Check aria-hidden="true" size={18} />
            </button>
          )}
        </footer>
        {errors.submit ? (
          <div className="form-error-summary" role="alert">
            {errors.submit}
          </div>
        ) : null}
      </div>
      <WhatsAppPreview
        symbol={firstSymbol}
        destination={maskDestination(destination)}
        language={language}
        tone={tone}
        compact={step < 3}
      />
    </form>
  );
}
