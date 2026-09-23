"use client";

import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type FormEvent } from "react";
import Link from "next/link";
import {
  Check,
  ChevronRight,
  Clock3,
  Mail,
  MessageCircle,
  Send,
  Hash,
  Radio,
  ShieldCheck,
  X,
} from "lucide-react";
import { PageHeading } from "./page-heading";
import { BrandMark } from "./brand";
import { useToast } from "./toast-provider";
import { topics as researchTopics, type Topic } from "@/lib/research-sources";
import {
  botSchema,
  channels,
  defaultDelivery,
  deliverySchema,
  deliveryTopics,
  decodePreferences,
  emptyPreferences,
  exampleMessage,
  preferencesSnapshot,
  restoreBotDraft,
  restoreDeliveryDraft,
  savePreferences,
  subscribePreferences,
  type BotInput,
  type Channel,
  type DeliveryInput,
  type Preferences,
} from "@/lib/delivery-preferences";

const icons = { whatsapp: MessageCircle, telegram: Send, discord: Hash, slack: Hash, email: Mail };
const serverSnapshot = () => "pending";
export function SettingsNavigation({ active }: { active: "delivery" | "bot" | "account" }) {
  return (
    <nav className="preferences-nav" aria-label="Settings sections">
      {(
        [
          ["delivery", "Delivery"],
          ["bot", "Bot"],
          ["account", "Account"],
        ] as const
      ).map(([id, label]) => (
        <Link
          key={id}
          href={`/app/settings${id === "delivery" ? "" : `/${id}`}`}
          aria-current={active === id ? "page" : undefined}
        >
          {label}
        </Link>
      ))}
    </nav>
  );
}
function usePreferences() {
  const raw = useSyncExternalStore(subscribePreferences, preferencesSnapshot, serverSnapshot);
  return useMemo(
    () => ({
      ready: raw !== "pending",
      state: decodePreferences(raw === "pending" ? null : raw),
      error: raw !== "pending" && decodePreferences(raw) === null,
    }),
    [raw],
  );
}
function StorageProblem() {
  return (
    <div className="research-notice" role="alert">
      <p>
        Saved settings could not be read. Your existing data has been kept. Allow browser storage
        and reload to try again.
      </p>
      <button type="button" className="button secondary" onClick={() => location.reload()}>
        Reload settings
      </button>
    </div>
  );
}
function useDraftGuard(dirty: boolean) {
  useEffect(() => {
    const listener = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", listener);
    return () => window.removeEventListener("beforeunload", listener);
  }, [dirty]);
}
function readDraft<T>(
  key: string,
  revision: number,
  fallback: T,
  restore: (raw: string | null, revision: number, fallback: T) => T,
): T {
  try {
    return restore(sessionStorage.getItem(key), revision, fallback);
  } catch {
    /* An unreadable draft does not replace saved settings. */
  }
  return structuredClone(fallback);
}
function useSessionDraft(
  key: string,
  revision: number,
  input: DeliveryInput | BotInput,
  dirty: boolean,
) {
  useEffect(() => {
    try {
      if (dirty) sessionStorage.setItem(key, JSON.stringify({ revision, input }));
      else sessionStorage.removeItem(key);
    } catch {
      /* Saving reports persistent-storage problems. */
    }
  }, [key, revision, input, dirty]);
}
function discardDraft(key: string) {
  try {
    sessionStorage.removeItem(key);
  } catch {
    /* No saved settings are removed. */
  }
}
function focusFirstError(form: HTMLFormElement | null) {
  const input = form?.querySelector<HTMLElement>('[aria-invalid="true"]');
  const details = input?.closest("details");
  if (details) details.open = true;
  input?.focus();
}

export function DeliverySettings() {
  const { state, ready, error } = usePreferences();
  const [selected, setSelected] = useState<Channel | null>(null);
  const notify = useToast();
  const addRef = useRef<HTMLButtonElement>(null);
  function finish(message: string) {
    if (message) notify(message);
    setSelected(null);
    requestAnimationFrame(() => addRef.current?.focus());
  }
  return (
    <div className="page-wrap preferences-page">
      <PageHeading title="Settings" description="Choose where your brief goes and how it reads." />
      <SettingsNavigation active="delivery" />
      {error ? <StorageProblem /> : null}
      <div className={`delivery-layout${selected ? " is-editing" : ""}`}>
        <section aria-labelledby="delivery-title" className="channel-directory">
          <div className="section-heading">
            <h2 id="delivery-title">Delivery channels</h2>
          </div>
          <p className="preferences-intro">
            Discord delivery exists in the backend. Other channels are planned. Prepare your
            preferences here; no channel is connected to this workspace yet.
          </p>
          <div className="channel-list">
            {(Object.entries(channels) as [Channel, (typeof channels)[Channel]][]).map(
              ([id, item], i) => {
                const Icon = icons[id];
                const config = state?.delivery[id];
                return (
                  <button
                    ref={i === 0 ? addRef : undefined}
                    key={id}
                    className="channel-choice"
                    disabled={!ready || error || !!selected}
                    type="button"
                    onClick={() => {
                      setSelected(id);
                    }}
                    aria-label={`Configure ${item.name}`}
                  >
                    <span className="channel-symbol">
                      <Icon size={22} aria-hidden="true" />
                    </span>
                    <span className="channel-choice-copy">
                      <strong>{item.name}</strong>
                      <small className="channel-support">
                        {id === "discord"
                          ? "Backend supported · not connected"
                          : "Planned delivery"}
                      </small>
                      <span>
                        {config
                          ? config.destination
                          : id === "email"
                            ? "A daily read in your inbox"
                            : id === "slack"
                              ? "Keep your team in the loop"
                              : id === "discord"
                                ? "Briefs for your community"
                                : "Your brief, alongside your conversations"}
                      </span>
                    </span>
                    <span className="channel-state">
                      {config
                        ? config.enabled
                          ? "Preferences saved"
                          : "Preference off"
                        : "Preferences"}
                    </span>
                    <ChevronRight size={17} aria-hidden="true" />
                  </button>
                );
              },
            )}
          </div>
          <div className="preferences-footnote">
            <ShieldCheck size={18} aria-hidden="true" />
            <p>
              Preferences stay on this device. Delivery starts only after the channel is connected
              and verified.
            </p>
          </div>
        </section>
        {selected && state ? (
          <ChannelEditor
            key={selected}
            channel={selected}
            state={state}
            onClose={() => finish("")}
            onSaved={() =>
              finish(`${channels[selected].name} preferences saved. Connection is still required.`)
            }
          />
        ) : (
          <aside className="delivery-guide">
            <Radio size={24} aria-hidden="true" />
            <h2>Your brief has a home.</h2>
            <p>
              Choose a channel, decide which updates belong there, and set a rhythm that fits your
              day.
            </p>
            <dl>
              <div>
                <dt>Delivery</dt>
                <dd>Where and when updates arrive</dd>
              </div>
              <div>
                <dt>Bot</dt>
                <dd>Name, language and brief style</dd>
              </div>
              <div>
                <dt>Sources</dt>
                <dd>Whose research goes into your brief</dd>
              </div>
            </dl>
            <Link href="/app/settings/bot" className="text-link">
              Customize your bot <ChevronRight size={16} aria-hidden="true" />
            </Link>
            <Link href="/app/settings/account" className="text-link">
              Prepare account connections <ChevronRight size={16} aria-hidden="true" />
            </Link>
          </aside>
        )}
      </div>
    </div>
  );
}
function ChannelEditor({
  channel,
  state,
  onClose,
  onSaved,
}: {
  channel: Channel;
  state: Preferences;
  onClose: () => void;
  onSaved: () => void;
}) {
  const baseline = state.delivery[channel] ?? defaultDelivery;
  const notify = useToast();
  const [revision] = useState(state.revision);
  const key = `bursawatch-delivery-draft:${channel}`;
  const [input, setInput] = useState<DeliveryInput>(() =>
    readDraft(key, revision, baseline, restoreDeliveryDraft),
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [closing, setClosing] = useState(false);
  const [removing, setRemoving] = useState(false);
  const form = useRef<HTMLFormElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const dirty = JSON.stringify(input) !== JSON.stringify(baseline);
  useDraftGuard(dirty);
  useSessionDraft(key, revision, input, dirty);
  useEffect(() => heading.current?.focus(), []);
  function update<K extends keyof DeliveryInput>(k: K, value: DeliveryInput[K]) {
    setInput((p) => ({ ...p, [k]: value }));
    setErrors((p) => ({ ...p, [k]: "", submit: "" }));
  }
  function close() {
    discardDraft(key);
    onClose();
  }
  function submit(e: FormEvent) {
    e.preventDefault();
    const result = deliverySchema.safeParse(input);
    if (!result.success) {
      const next: Record<string, string> = {};
      result.error.issues.forEach((issue) => (next[String(issue.path[0])] ??= issue.message));
      setErrors(next);
      requestAnimationFrame(() => focusFirstError(form.current));
      return;
    }
    try {
      savePreferences(revision, { type: "delivery", channel, input: result.data });
      discardDraft(key);
      onSaved();
    } catch (e) {
      setErrors({ submit: (e as Error).message });
    }
  }
  const item = channels[channel];
  return (
    <section className="channel-editor" aria-labelledby="channel-title">
      <div className="section-heading">
        <h2 id="channel-title" tabIndex={-1} ref={heading}>
          {item.name}
        </h2>
        <button
          type="button"
          className="icon-button"
          aria-label="Close channel settings"
          onClick={() => (dirty ? setClosing(true) : close())}
        >
          <X size={20} aria-hidden="true" />
        </button>
      </div>
      {closing ? (
        <div className="research-notice" role="alert">
          <p>Discard unsaved changes?</p>
          <div className="research-actions">
            <button type="button" className="button secondary" onClick={() => setClosing(false)}>
              Keep editing
            </button>
            <button type="button" className="button secondary" onClick={close}>
              Discard changes
            </button>
          </div>
        </div>
      ) : null}
      <p className="preferences-intro">
        {channel === "discord"
          ? "Discord delivery exists in the reviewed Hermes setup. This destination still needs verification."
          : "Save the setup you want. This delivery adapter needs backend integration."}
      </p>
      <form ref={form} onSubmit={submit} noValidate>
        <label className="field-label" htmlFor="channel-destination">
          {item.destination}
        </label>
        <input
          id="channel-destination"
          className="text-input"
          value={input.destination}
          placeholder={item.placeholder}
          maxLength={80}
          autoComplete="off"
          onChange={(e) => update("destination", e.target.value)}
          aria-invalid={!!errors.destination}
          aria-describedby="destination-help"
        />
        <p id="destination-help" className={errors.destination ? "field-error" : "field-help"}>
          {errors.destination || item.hint}
        </p>
        <fieldset className="preference-fieldset">
          <legend>Include these updates</legend>
          {Object.entries(deliveryTopics).map(([id, label]) => (
            <label className="preference-check" key={id}>
              <input
                type="checkbox"
                checked={input.topics.includes(id as keyof typeof deliveryTopics)}
                onChange={(e) =>
                  update(
                    "topics",
                    e.target.checked
                      ? [...input.topics, id as keyof typeof deliveryTopics]
                      : input.topics.filter((t) => t !== id),
                  )
                }
                aria-invalid={!!errors.topics}
                aria-describedby={errors.topics ? "delivery-topics-error" : undefined}
              />
              {label}
            </label>
          ))}
          {errors.topics ? (
            <p id="delivery-topics-error" className="field-error">
              {errors.topics}
            </p>
          ) : null}
        </fieldset>
        <fieldset className="preference-fieldset">
          <legend>Delivery rhythm</legend>
          <label className="preference-check">
            <input
              type="radio"
              name="cadence"
              checked={input.cadence === "as-ready"}
              onChange={() => update("cadence", "as-ready")}
            />
            As updates are ready
          </label>
          <label className="preference-check">
            <input
              type="radio"
              name="cadence"
              checked={input.cadence === "digest"}
              onChange={() => update("cadence", "digest")}
            />
            One daily digest
          </label>
        </fieldset>
        {input.cadence === "digest" || errors.digestTime ? (
          <div className="preference-grid">
            <div>
              <label className="field-label" htmlFor="digest-time">
                Digest time
              </label>
              <input
                type="time"
                id="digest-time"
                className="text-input"
                value={input.digestTime}
                onChange={(e) => update("digestTime", e.target.value)}
                aria-invalid={!!errors.digestTime}
                aria-describedby={errors.digestTime ? "digest-error" : undefined}
              />
              {errors.digestTime ? (
                <p id="digest-error" className="field-error">
                  {errors.digestTime}
                </p>
              ) : null}
            </div>
            <div>
              <label className="field-label" htmlFor="delivery-timezone">
                Time zone
              </label>
              <select
                id="delivery-timezone"
                className="text-input"
                value={input.timezone}
                onChange={(e) => update("timezone", e.target.value as DeliveryInput["timezone"])}
              >
                <option value="Asia/Jakarta">WIB · Jakarta</option>
                <option value="Asia/Makassar">WITA · Makassar</option>
                <option value="Asia/Jayapura">WIT · Jayapura</option>
              </select>
            </div>
          </div>
        ) : null}
        <label className="preference-check">
          <input
            type="checkbox"
            checked={input.weekdaysOnly}
            onChange={(e) => update("weekdaysOnly", e.target.checked)}
          />
          Weekdays only
        </label>
        <details className="preference-details">
          <summary>
            <Clock3 size={16} aria-hidden="true" /> Quiet hours & status
          </summary>
          <label className="preference-check">
            <input
              type="checkbox"
              checked={input.quietEnabled}
              onChange={(e) => update("quietEnabled", e.target.checked)}
            />
            Hold updates during quiet hours
          </label>
          {input.quietEnabled || errors.quietStart || errors.quietEnd ? (
            <>
              <div className="preference-grid">
                <div>
                  <label className="field-label" htmlFor="quiet-start">
                    From
                  </label>
                  <input
                    id="quiet-start"
                    type="time"
                    className="text-input"
                    value={input.quietStart}
                    onChange={(e) => update("quietStart", e.target.value)}
                    aria-invalid={!!errors.quietStart}
                    aria-describedby={errors.quietStart ? "quiet-start-error" : undefined}
                  />
                  {errors.quietStart ? (
                    <p id="quiet-start-error" className="field-error">
                      {errors.quietStart}
                    </p>
                  ) : null}
                </div>
                <div>
                  <label className="field-label" htmlFor="quiet-end">
                    Until
                  </label>
                  <input
                    id="quiet-end"
                    type="time"
                    className="text-input"
                    value={input.quietEnd}
                    onChange={(e) => update("quietEnd", e.target.value)}
                    aria-invalid={!!errors.quietEnd}
                    aria-describedby={errors.quietEnd ? "quiet-error" : undefined}
                  />
                </div>
              </div>
              {errors.quietEnd ? (
                <p id="quiet-error" className="field-error">
                  {errors.quietEnd}
                </p>
              ) : null}
              <p className="field-help">
                Uses {input.timezone}. Held updates resume after quiet hours; nothing is sent by
                this frontend.
              </p>
              {input.cadence === "as-ready" ? (
                <>
                  <label className="field-label" htmlFor="quiet-zone">
                    Time zone
                  </label>
                  <select
                    id="quiet-zone"
                    className="text-input"
                    value={input.timezone}
                    onChange={(e) =>
                      update("timezone", e.target.value as DeliveryInput["timezone"])
                    }
                  >
                    <option value="Asia/Jakarta">WIB · Jakarta</option>
                    <option value="Asia/Makassar">WITA · Makassar</option>
                    <option value="Asia/Jayapura">WIT · Jayapura</option>
                  </select>
                </>
              ) : null}
            </>
          ) : null}
          <label className="preference-check">
            <input
              type="checkbox"
              checked={input.enabled}
              onChange={(e) => update("enabled", e.target.checked)}
            />
            Include this channel in my delivery plan
          </label>
          <p className="field-help">
            Changing this plan does not cancel queued messages in Hermes.
          </p>
        </details>
        <div className="delivery-rule">
          <strong>Your delivery plan</strong>
          <p>
            {input.enabled
              ? `${input.topics.length} update types to ${input.destination || item.name}, ${input.cadence === "digest" ? `in a daily digest at ${input.digestTime}` : "as they are ready"}${input.weekdaysOnly ? ", weekdays only" : ""}.`
              : "This channel is paused in your delivery plan."}
          </p>
          <span>Not connected · preferences only</span>
        </div>
        {errors.submit ? (
          <p className="field-error" role="alert">
            {errors.submit}
          </p>
        ) : null}
        <div className="preferences-save">
          <span>{dirty ? "Unsaved changes" : "Preferences"}</span>
          <button
            className="button primary"
            type="submit"
            disabled={!!state.delivery[channel] && !dirty}
          >
            <Check size={17} aria-hidden="true" />
            Save channel
          </button>
        </div>
      </form>
      {state.delivery[channel] ? (
        <div className="remove-preference">
          {removing ? (
            <>
              <p>Remove this channel’s saved preferences?</p>
              <div className="research-actions">
                <button
                  type="button"
                  className="button secondary"
                  onClick={() => setRemoving(false)}
                >
                  Keep channel
                </button>
                <button
                  type="button"
                  className="button secondary"
                  onClick={() => {
                    try {
                      savePreferences(revision, { type: "remove", channel });
                      notify(`${channels[channel].name} preferences removed.`);
                      close();
                    } catch (e) {
                      setErrors({ submit: (e as Error).message });
                    }
                  }}
                >
                  Remove preferences
                </button>
              </div>
            </>
          ) : (
            <button type="button" className="text-link" onClick={() => setRemoving(true)}>
              Remove channel preferences
            </button>
          )}
        </div>
      ) : null}
    </section>
  );
}

export function BotSettings() {
  const { state, ready, error } = usePreferences();
  return (
    <div className="page-wrap preferences-page">
      <PageHeading title="Settings" description="Choose where your brief goes and how it reads." />
      <SettingsNavigation active="bot" />
      {error ? (
        <StorageProblem />
      ) : !ready ? (
        <p role="status">Loading bot preferences…</p>
      ) : (
        <BotEditor initial={state ?? emptyPreferences} />
      )}
    </div>
  );
}
function BotEditor({ initial }: { initial: Preferences }) {
  const [baseline, setBaseline] = useState(initial.bot);
  const [revision, setRevision] = useState(initial.revision);
  const key = "bursawatch-bot-draft";
  const [input, setInput] = useState<BotInput>(() =>
    readDraft(key, initial.revision, initial.bot, restoreBotDraft),
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const notify = useToast();
  const [previewChannel, setPreviewChannel] = useState<Channel>("whatsapp");
  const dirty = JSON.stringify(input) !== JSON.stringify(baseline);
  const form = useRef<HTMLFormElement>(null);
  useDraftGuard(dirty);
  useSessionDraft(key, revision, input, dirty);
  function update<K extends keyof BotInput>(k: K, value: BotInput[K]) {
    setInput((p) => ({ ...p, [k]: value }));
    setErrors((p) => ({ ...p, [k]: "", submit: "" }));
  }
  function submit(e: FormEvent) {
    e.preventDefault();
    const result = botSchema.safeParse(input);
    if (!result.success) {
      const next: Record<string, string> = {};
      result.error.issues.forEach((i) => (next[String(i.path[0])] ??= i.message));
      setErrors(next);
      requestAnimationFrame(() => focusFirstError(form.current));
      return;
    }
    try {
      const next = savePreferences(revision, { type: "bot", input: result.data });
      setBaseline(next.bot);
      setRevision(next.revision);
      setInput(next.bot);
      discardDraft(key);
      notify("Bot preferences saved on this device.");
    } catch (e) {
      setErrors({ submit: (e as Error).message });
    }
  }
  return (
    <div className="bot-layout">
      <form onSubmit={submit} ref={form} noValidate>
        <div className="section-heading">
          <h2>Your bot</h2>
        </div>
        <p className="preferences-intro">
          Give your brief a familiar voice. Keep the facts intact.
        </p>
        <label className="field-label" htmlFor="bot-name">
          Display name
        </label>
        <input
          id="bot-name"
          className="text-input"
          value={input.name}
          maxLength={32}
          onChange={(e) => update("name", e.target.value)}
          aria-invalid={!!errors.name}
          aria-describedby={errors.name ? "bot-name-error" : undefined}
        />
        {errors.name ? (
          <p id="bot-name-error" className="field-error">
            {errors.name}
          </p>
        ) : null}
        <div className="preference-grid">
          <div>
            <label className="field-label" htmlFor="bot-language">
              Language
            </label>
            <select
              id="bot-language"
              className="text-input"
              value={input.language}
              onChange={(e) => update("language", e.target.value as BotInput["language"])}
            >
              <option value="id">Bahasa Indonesia</option>
              <option value="en">English</option>
            </select>
          </div>
          <div>
            <label className="field-label" htmlFor="bot-tone">
              Writing style
            </label>
            <select
              id="bot-tone"
              className="text-input"
              value={input.tone}
              onChange={(e) => update("tone", e.target.value as BotInput["tone"])}
            >
              <option value="concise">Direct</option>
              <option value="beginner">Explain simply</option>
              <option value="analyst">Research notes</option>
            </select>
          </div>
        </div>
        <fieldset className="preference-fieldset">
          <legend>Research interests</legend>
          <p className="field-help" id="bot-interests-help">
            New follows use these topics. You can adjust each source in Following.
          </p>
          {(Object.entries(researchTopics) as [Topic, (typeof researchTopics)[Topic]][]).map(
            ([topic, details]) => (
              <label className="preference-check" key={topic}>
                <input
                  type="checkbox"
                  checked={input.interests.includes(topic)}
                  onChange={(event) =>
                    update(
                      "interests",
                      event.target.checked
                        ? [...input.interests, topic]
                        : input.interests.filter((item) => item !== topic),
                    )
                  }
                  aria-invalid={!!errors.interests}
                  aria-describedby={errors.interests ? "bot-interests-error" : "bot-interests-help"}
                />
                {details.label}
              </label>
            ),
          )}
          {errors.interests ? (
            <p id="bot-interests-error" className="field-error">
              {errors.interests}
            </p>
          ) : null}
        </fieldset>
        <fieldset className="preference-fieldset">
          <legend>Brief length</legend>
          <div className="preference-inline">
            {(
              [
                ["short", "Quick read"],
                ["standard", "Standard"],
                ["detailed", "Detailed"],
              ] as const
            ).map(([value, label]) => (
              <label className="preference-check" key={value}>
                <input
                  type="radio"
                  name="bot-length"
                  checked={input.length === value}
                  onChange={() => update("length", value)}
                />
                {label}
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset className="preference-fieldset">
          <legend>Message details</legend>
          <label className="preference-check">
            <input
              type="checkbox"
              checked={input.includeTime}
              onChange={(e) => update("includeTime", e.target.checked)}
            />
            Include the publication time
          </label>
          <label className="preference-check">
            <input
              type="checkbox"
              checked={input.includeCharts}
              onChange={(e) => update("includeCharts", e.target.checked)}
            />
            Include available source charts
          </label>
          <label className="preference-check">
            <input
              type="checkbox"
              checked={input.useEmoji}
              onChange={(e) => update("useEmoji", e.target.checked)}
            />
            Use a small amount of emoji
          </label>
          <p className="field-help">Source links are always included.</p>
        </fieldset>
        <details className="preference-details">
          <summary>Additional instructions</summary>
          <label className="field-label" htmlFor="bot-instructions">
            What should the bot keep in mind?
          </label>
          <textarea
            id="bot-instructions"
            rows={4}
            maxLength={600}
            className="text-input"
            value={input.instructions}
            onChange={(e) => update("instructions", e.target.value)}
            placeholder="For example: explain unfamiliar terms and focus on Indonesian banking."
            aria-invalid={!!errors.instructions}
            aria-describedby="bot-instructions-help"
          />
          <p
            id="bot-instructions-help"
            className={errors.instructions ? "field-error" : "field-help"}
          >
            {errors.instructions ||
              `${input.instructions.length}/600 · Instructions guide generated briefs after integration; this example does not run an AI model.`}
          </p>
        </details>
        <p className="preferences-boundary">
          These are shared defaults. A securities firm’s own configuration stays separate. Platform
          avatars and live bot identity are managed during connection setup.
        </p>
        {errors.submit ? (
          <p className="field-error" role="alert">
            {errors.submit}
          </p>
        ) : null}
        <div className="preferences-save">
          <span>{dirty ? "Unsaved changes" : "All changes saved"}</span>
          <button className="button primary" disabled={!dirty} type="submit">
            <Check size={17} aria-hidden="true" />
            Save bot
          </button>
        </div>
      </form>
      <aside className="bot-preview">
        <div className="section-heading">
          <h2>Message preview</h2>
        </div>
        <label className="field-label" htmlFor="preview-channel">
          Preview in
        </label>
        <select
          className="text-input"
          id="preview-channel"
          value={previewChannel}
          onChange={(e) => setPreviewChannel(e.target.value as Channel)}
        >
          {Object.entries(channels).map(([id, v]) => (
            <option key={id} value={id}>
              {v.name}
            </option>
          ))}
        </select>
        <div className={`bot-message ${previewChannel === "email" ? "is-email" : ""}`}>
          <div className="bot-message-sender">
            <BrandMark />
            <div>
              <strong>{input.name || "Your bot"}</strong>
              <span>{channels[previewChannel].name} · example message</span>
            </div>
          </div>
          {previewChannel === "email" ? (
            <p className="bot-email-subject">
              Subject: {input.language === "id" ? "Ringkasan pasar" : "Market brief"}
            </p>
          ) : null}
          <p className="bot-message-body">{exampleMessage(input)}</p>
          {input.includeCharts ? (
            <div className="source-attachment">
              <Radio size={17} aria-hidden="true" />
              <span>Source chart · included when available</span>
            </div>
          ) : null}
        </div>
        <p className="field-help">
          Wording preview, not a sent message. Each platform adapts formatting and media to its
          capabilities.
        </p>
        <Link className="text-link" href="/app/settings">
          Choose delivery channels <ChevronRight size={16} aria-hidden="true" />
        </Link>
      </aside>
    </div>
  );
}
