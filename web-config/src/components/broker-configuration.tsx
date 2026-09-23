"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowRight, Check, MessageCircle, SlidersHorizontal } from "lucide-react";
import { useBrokerWorkspace } from "@/components/use-broker-workspace";
import { PageHeading } from "@/components/page-heading";
import { useToast } from "@/components/toast-provider";
import { findBroker, type Broker, type BrokerId } from "@/lib/brokers";
import {
  clearBrokerDraft,
  readBrokerDraft,
  saveBrokerDraft,
  preferencesSchema,
  updateWorkspace,
  type BrokerPreferences,
  type BrokerWorkspace,
} from "@/lib/broker-workspace";

const goals = [
  { id: "scalp", name: "Scalp", detail: "Within the day" },
  { id: "swing", name: "Swing", detail: "Days to weeks" },
  { id: "invest", name: "Invest", detail: "Months to years" },
] as const;
const focusCopy = {
  id: {
    scalp: "Fokus: perubahan dalam satu sesi perdagangan.",
    swing: "Fokus: perkembangan harga dan katalis dalam beberapa hari hingga minggu.",
    invest: "Fokus: kinerja usaha, valuasi, dan perkembangan jangka panjang.",
  },
  en: {
    scalp: "Focus: changes within a trading session.",
    swing: "Focus: price changes and catalysts over days to weeks.",
    invest: "Focus: business performance, valuation and long-term developments.",
  },
};

function BriefPreview({ broker, preferences }: { broker: Broker; preferences: BrokerPreferences }) {
  const id = preferences.language === "id";
  const body = id
    ? preferences.tone === "plain"
      ? "BBRI naik pada contoh sesi ini. Ringkasan menampilkan perubahan harga, lalu memisahkannya dari pandangan analis. Angka harga saja tidak menjelaskan penyebabnya."
      : preferences.tone === "analytical"
        ? "Contoh observasi BBRI: perubahan harga disajikan terpisah dari ulasan sumber. Katalis, data fundamental, dan level teknikal hanya dicantumkan jika tersedia dalam sumber."
        : "Perubahan harga BBRI dirangkum terpisah dari ulasan sumber. Pandangan analis tetap diberi atribusi."
    : preferences.tone === "plain"
      ? "BBRI rose in this example session. The brief separates the price move from the analyst’s view. A price move alone does not explain its cause."
      : preferences.tone === "analytical"
        ? "Example BBRI observation: price changes are separate from source commentary. Catalysts, fundamentals and technical levels appear only when supported by the source."
        : "BBRI’s price change is separate from source commentary. The analyst’s view remains attributed.";
  return (
    <aside className="broker-preview" aria-labelledby="broker-preview-heading">
      <div className="broker-preview-title">
        <h2 id="broker-preview-heading">Message preview</h2>
        <MessageCircle size={19} aria-hidden="true" />
      </div>
      <div className="broker-preview-source">
        <div className="broker-preview-logo">
          <Image src={broker.logo} alt="" width={132} height={30} />
        </div>
        <div>
          <strong>{broker.shortName}</strong>
          <span>Research brief</span>
        </div>
      </div>
      <div className="broker-message" aria-live="polite" aria-atomic="true">
        <div className="broker-message-meta">
          <span>Bursawatch</span>
          <span>15:30 WIB</span>
        </div>
        <h3>{id ? "BBRI · Ringkasan pasar" : "BBRI · Market brief"}</h3>
        {preferences.priceSummary && (
          <div className="broker-price-block">
            <div>
              <span>{id ? "Harga penutupan" : "Closing price"}</span>
              <strong>Rp3,740</strong>
            </div>
            <span className="broker-price-change">
              +3.60% <span>1D</span>
            </span>
          </div>
        )}
        <p>{body}</p>
        <p className="broker-message-focus">{focusCopy[preferences.language][preferences.goal]}</p>
        <div className="broker-message-footer">
          <span>
            {broker.shortName} · {id ? "Sumber riset" : "Research source"}
          </span>
          <span>Illustrative content</span>
        </div>
      </div>
      <div className="broker-preview-note">
        <Check size={15} aria-hidden="true" />
        <p>
          Source facts and analyst views stay separate. Price data is never treated as a
          recommendation.
        </p>
      </div>
      {preferences.instructions.trim() && (
        <div className="broker-instruction-preview">
          <strong>Writing instructions</strong>
          <p>{preferences.instructions}</p>
          <span>Applied when a brief is generated.</span>
        </div>
      )}
      <p className="broker-preview-caption">
        Example values, not a published {broker.shortName} report.
      </p>
    </aside>
  );
}

function ConfigurationForm({
  broker,
  watch,
  watchedIds,
}: {
  broker: Broker;
  watch: BrokerWorkspace["watches"][number];
  watchedIds: BrokerId[];
}) {
  const toast = useToast();
  const [draft, setDraft] = useState<BrokerPreferences>(
    () => readBrokerDraft(broker.id, watch.preferences) ?? watch.preferences,
  );
  const [baseline, setBaseline] = useState(watch.preferences);
  const [message, setMessage] = useState(() =>
    JSON.stringify(draft) !== JSON.stringify(watch.preferences)
      ? "Recovered your unsaved draft."
      : "",
  );
  const [error, setError] = useState("");
  const [pendingFirm, setPendingFirm] = useState<BrokerId | null>(null);
  const router = useRouter();
  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline);
  const externallyChanged = JSON.stringify(watch.preferences) !== JSON.stringify(baseline);
  useEffect(() => {
    if (!dirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    const protectNavigation = (event: MouseEvent) => {
      const anchor = (event.target as Element)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (
        !anchor ||
        anchor.target === "_blank" ||
        event.ctrlKey ||
        event.metaKey ||
        anchor.origin !== location.origin
      )
        return;
      if (!window.confirm("Leave without saving your configuration?")) {
        event.preventDefault();
        event.stopPropagation();
      } else {
        clearBrokerDraft(broker.id);
      }
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", protectNavigation, true);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", protectNavigation, true);
    };
  }, [dirty, broker.id]);
  function update<Key extends keyof BrokerPreferences>(key: Key, value: BrokerPreferences[Key]) {
    const next = { ...draft, [key]: value };
    const recoverable = saveBrokerDraft(broker.id, baseline, next);
    setDraft(next);
    setMessage("");
    setError(
      recoverable
        ? ""
        : "Draft recovery is unavailable. Save your configuration before leaving this page.",
    );
  }
  function save(event: React.FormEvent) {
    event.preventDefault();
    const validated = preferencesSchema.safeParse(draft);
    if (!validated.success) {
      setError(validated.error.issues[0]?.message ?? "Check your preferences.");
      return;
    }
    if (externallyChanged) {
      setError("Settings changed in another tab. Load the saved version before editing again.");
      return;
    }
    try {
      updateWorkspace({ type: "configure", id: broker.id, preferences: validated.data });
      setDraft(validated.data);
      setBaseline(validated.data);
      clearBrokerDraft(broker.id);
      setError("");
      setMessage("Configuration saved in this browser.");
      toast(`${broker.shortName} preferences saved.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save your configuration.");
    }
  }
  const switchFirm = (id: BrokerId) => {
    if (dirty) setPendingFirm(id);
    else router.push(`/app/configuration?firm=${id}`);
  };
  return (
    <>
      <div className="broker-config-selector">
        <label htmlFor="configured-firm">Securities firm</label>
        <select
          id="configured-firm"
          value={broker.id}
          onChange={(event) => switchFirm(event.target.value as BrokerId)}
        >
          {watchedIds.map((id) => (
            <option value={id} key={id}>
              {findBroker(id)!.name}
            </option>
          ))}
        </select>
        <span>{watch.paused ? "Watch paused" : "In your watched securities"}</span>
      </div>
      {pendingFirm && (
        <div className="broker-switch-confirm" role="alert">
          <p>You have unsaved changes for {broker.shortName}.</p>
          <button className="button secondary small" onClick={() => setPendingFirm(null)}>
            Keep editing
          </button>
          <button
            className="button secondary small"
            onClick={() => {
              clearBrokerDraft(broker.id);
              setPendingFirm(null);
              router.push(`/app/configuration?firm=${pendingFirm}`);
            }}
          >
            Discard and switch
          </button>
        </div>
      )}
      <div className="broker-config-layout">
        <form className="broker-config-form" onSubmit={save}>
          <fieldset className="broker-config-section">
            <legend>Investment approach</legend>
            <p>Choose the horizon your brief should focus on.</p>
            <div className="broker-goals">
              {goals.map((goal) => (
                <label key={goal.id} className={draft.goal === goal.id ? "selected" : ""}>
                  <input
                    type="radio"
                    name="goal"
                    value={goal.id}
                    checked={draft.goal === goal.id}
                    onChange={() => update("goal", goal.id)}
                  />
                  <strong>{goal.name}</strong>
                  <span>{goal.detail}</span>
                </label>
              ))}
            </div>
            {draft.goal === "scalp" && (
              <p className="broker-config-hint">
                A focus preference, not a real-time feed. Data frequency depends on your connected
                source.
              </p>
            )}
          </fieldset>
          <div className="broker-config-section broker-toggle-row">
            <div>
              <label htmlFor="price-summary">Price-change summary</label>
              <p>Include the price move alongside the research.</p>
            </div>
            <label className="broker-toggle">
              <input
                id="price-summary"
                type="checkbox"
                role="switch"
                checked={draft.priceSummary}
                onChange={(event) => update("priceSummary", event.target.checked)}
              />
              <span aria-hidden="true" />
              <strong aria-hidden="true">{draft.priceSummary ? "On" : "Off"}</strong>
            </label>
          </div>
          <div className="broker-config-section">
            <h2>Writing style</h2>
            <div className="broker-writing-fields">
              <div>
                <label htmlFor="brief-language">Language</label>
                <select
                  id="brief-language"
                  value={draft.language}
                  onChange={(event) =>
                    update("language", event.target.value as BrokerPreferences["language"])
                  }
                >
                  <option value="id">Bahasa Indonesia</option>
                  <option value="en">English</option>
                </select>
              </div>
              <div>
                <label htmlFor="brief-tone">Tone</label>
                <select
                  id="brief-tone"
                  value={draft.tone}
                  onChange={(event) =>
                    update("tone", event.target.value as BrokerPreferences["tone"])
                  }
                >
                  <option value="concise">Concise</option>
                  <option value="plain">Plain language</option>
                  <option value="analytical">Analytical</option>
                </select>
              </div>
            </div>
            <label className="broker-instructions-label" htmlFor="custom-instructions">
              Custom instructions
            </label>
            <textarea
              id="custom-instructions"
              className="text-input"
              rows={4}
              maxLength={600}
              aria-describedby="instructions-help instructions-count"
              value={draft.instructions}
              onChange={(event) => update("instructions", event.target.value)}
              placeholder="Contoh: pakai bahasa santai, jelaskan istilah teknis, dan utamakan saham perbankan."
            />
            <div className="broker-textarea-meta">
              <p id="instructions-help">Adjust the explanation, not the source facts.</p>
              <span id="instructions-count">{draft.instructions.length}/600</span>
            </div>
          </div>
          <details className="broker-source-contract">
            <summary>How this source is handled</summary>
            <p>
              {broker.id === "phintraco"
                ? "Phintraco’s daily swing calls and weekly SSF reports retain their original numbers, rationale and source charts. Writing preferences apply to an accompanying brief, never to the original analyst call."
                : "BRI Danareksa posts are filtered for substantive market content. Issuer news, macro commentary and source-tagged technical reviews stay distinct. Source ratings are preserved, never inferred."}
            </p>
            <p>
              Custom instructions cannot override source attribution, relevance safeguards, or
              missing-data handling.
            </p>
          </details>
          {externallyChanged && (
            <div className="broker-error" role="alert">
              This configuration changed in another tab.{" "}
              <button
                type="button"
                className="button secondary small"
                onClick={() => {
                  setDraft(watch.preferences);
                  setBaseline(watch.preferences);
                  clearBrokerDraft(broker.id);
                  setError("");
                }}
              >
                Load saved version
              </button>
            </div>
          )}
          {error && (
            <p className="broker-error" role="alert">
              {error}
            </p>
          )}
          <footer className="broker-config-actions">
            <button className="button primary" type="submit" disabled={!dirty || externallyChanged}>
              Save configuration
            </button>
            <button
              className="button ghost"
              type="button"
              disabled={!dirty}
              onClick={() => {
                setDraft(baseline);
                clearBrokerDraft(broker.id);
                setError("");
                setMessage("");
              }}
            >
              Discard changes
            </button>
            <span role="status">
              {message || (dirty ? "Unsaved changes" : "All changes saved")}
            </span>
          </footer>
        </form>
        <BriefPreview broker={broker} preferences={draft} />
      </div>
    </>
  );
}

export function BrokerConfiguration() {
  const { state, ready, error } = useBrokerWorkspace();
  const params = useSearchParams();
  const requested = params.get("firm");
  const watch = requested
    ? state.watches.find((watch) => watch.brokerId === requested)
    : state.watches[0];
  const broker = watch ? findBroker(watch.brokerId) : undefined;
  return (
    <div className="page-wrap broker-config-page">
      <Link className="text-link hub-back" href="/app/following">
        Back to Following
      </Link>
      <PageHeading
        title={broker?.shortName ?? "Following"}
        description={
          broker
            ? `Set up your ${broker.shortName} brief.`
            : "Choose a securities firm to configure its brief."
        }
      />
      {error && (
        <p className="broker-error" role="alert">
          {error}
        </p>
      )}
      {!ready ? (
        <p role="status">Loading configuration…</p>
      ) : watch && broker ? (
        <ConfigurationForm
          key={broker.id}
          broker={broker}
          watch={watch}
          watchedIds={state.watches.map((watch) => watch.brokerId)}
        />
      ) : (
        <div className="broker-empty">
          <SlidersHorizontal size={28} aria-hidden="true" />
          <h2>
            {requested ? "This security isn’t in your list." : "First, choose your securities."}
          </h2>
          <p>Add a firm to set your goals, writing style and price summary.</p>
          <Link href="/app/securities/add" className="button primary">
            Browse securities <ArrowRight size={17} aria-hidden="true" />
          </Link>
          {state.watches.length > 0 && (
            <Link href="/app/configuration" className="text-link">
              Configure a watched firm
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
