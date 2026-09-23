"use client";
import { useEffect, useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { PageHeading } from "./page-heading";
import { useToast } from "./toast-provider";
import {
  decodePreferences,
  defaultBot,
  preferencesSnapshot,
  savePreferences,
  subscribePreferences,
  type BotInput,
} from "@/lib/delivery-preferences";
import { topics, type Topic } from "@/lib/research-sources";
const server = () => "pending";
export function WorkspaceEntry() {
  const raw = useSyncExternalStore(subscribePreferences, preferencesSnapshot, server);
  const router = useRouter();
  useEffect(() => {
    if (raw === "pending") return;
    const state = decodePreferences(raw);
    router.replace(state?.bot.onboardingComplete ? "/app/insights" : "/app/setup");
  }, [raw, router]);
  return (
    <div className="page-wrap">
      <p role="status">Opening your workspace…</p>
    </div>
  );
}
export function BriefSetup() {
  const raw = useSyncExternalStore(subscribePreferences, preferencesSnapshot, server);
  const state = decodePreferences(raw === "pending" ? null : raw);
  return (
    <div className="page-wrap">
      <PageHeading
        title="Make Bursawatch yours"
        description="Set your preferences once. Then follow the research you want."
      />
      {raw === "pending" ? (
        <p role="status">Loading preferences…</p>
      ) : !state ? (
        <div className="research-notice" role="alert">
          <p>
            Your saved settings could not be read. Allow browser storage and reload. Existing data
            has been kept.
          </p>
          <button className="button secondary" onClick={() => location.reload()}>
            Reload
          </button>
        </div>
      ) : (
        <SetupSteps initial={state.bot} revision={state.revision} />
      )}
    </div>
  );
}
function SetupSteps({ initial, revision }: { initial: BotInput; revision: number }) {
  const [step, setStep] = useState(0);
  const [bot, setBot] = useState(initial ?? defaultBot);
  const [error, setError] = useState("");
  const toast = useToast();
  const router = useRouter();
  function next() {
    if (!bot.interests.length) {
      setError("Choose at least one interest.");
      return;
    }
    setError("");
    setStep(step + 1);
  }
  function finish() {
    try {
      savePreferences(revision, { type: "bot", input: { ...bot, onboardingComplete: true } });
      toast("Your brief preferences are saved. Choose who to follow.");
      router.push("/app/discover");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <section className="setup-form">
      <ol className="setup-progress" aria-label="Setup progress">
        {["Interests", "Brief style", "Follow"].map((label, i) => (
          <li key={label} aria-current={step === i ? "step" : undefined}>
            {label}
          </li>
        ))}
      </ol>
      {step === 0 ? (
        <fieldset className="preference-fieldset">
          <legend>What do you want to keep up with?</legend>
          <p className="preferences-intro">
            These defaults apply when you follow someone. You can change individual source
            preferences later.
          </p>
          {(Object.entries(topics) as [Topic, (typeof topics)[Topic]][]).map(([id, topic]) => (
            <label key={id} className="research-topic">
              <input
                type="checkbox"
                checked={bot.interests.includes(id)}
                onChange={(e) => {
                  setBot({
                    ...bot,
                    interests: e.target.checked
                      ? [...bot.interests, id]
                      : bot.interests.filter((t) => t !== id),
                  });
                  setError("");
                }}
              />
              <span>
                <strong>{topic.label}</strong>
                <small>{topic.description}</small>
              </span>
            </label>
          ))}
        </fieldset>
      ) : step === 1 ? (
        <>
          <h2>Your reading style</h2>
          <div className="preference-grid">
            <div>
              <label className="field-label" htmlFor="setup-language">
                Language
              </label>
              <select
                id="setup-language"
                className="text-input"
                value={bot.language}
                onChange={(e) =>
                  setBot({ ...bot, language: e.target.value as BotInput["language"] })
                }
              >
                <option value="id">Bahasa Indonesia</option>
                <option value="en">English</option>
              </select>
            </div>
            <div>
              <label className="field-label" htmlFor="setup-tone">
                Writing style
              </label>
              <select
                id="setup-tone"
                className="text-input"
                value={bot.tone}
                onChange={(e) => setBot({ ...bot, tone: e.target.value as BotInput["tone"] })}
              >
                <option value="concise">Direct</option>
                <option value="beginner">Explain simply</option>
                <option value="analyst">Research notes</option>
              </select>
            </div>
          </div>
          <p className="preferences-intro">
            Source links stay in every brief. More bot and delivery options are in Settings.
          </p>
        </>
      ) : (
        <>
          <h2>Now choose your sources.</h2>
          <p className="preferences-intro">
            People, publications and brokerages are together in Discover. Follow with one click.
            Everything you add appears in Following, ready to configure.
          </p>
          <div className="delivery-rule">
            <strong>Your brief</strong>
            <p>{bot.interests.map((id) => topics[id].label).join(" · ")}</p>
            <span>
              {bot.language === "id" ? "Bahasa Indonesia" : "English"} ·{" "}
              {bot.tone === "concise"
                ? "Direct"
                : bot.tone === "beginner"
                  ? "Explain simply"
                  : "Research notes"}
            </span>
          </div>
        </>
      )}
      {error ? (
        <p role="alert" className="field-error">
          {error}
        </p>
      ) : null}
      <div className="setup-actions">
        {step > 0 ? (
          <button
            type="button"
            className="button secondary"
            onClick={() => {
              setError("");
              setStep(step - 1);
            }}
          >
            <ArrowLeft size={16} aria-hidden="true" />
            Back
          </button>
        ) : (
          <Link href="/app/discover" className="text-link">
            Set up later
          </Link>
        )}
        {step < 2 ? (
          <button type="button" className="button primary" onClick={next}>
            Continue <ArrowRight size={16} aria-hidden="true" />
          </button>
        ) : (
          <button type="button" className="button primary" onClick={finish}>
            <Check size={16} aria-hidden="true" />
            Choose sources
          </button>
        )}
      </div>
    </section>
  );
}
