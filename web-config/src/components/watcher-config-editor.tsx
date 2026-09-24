"use client";

import {
  createContext,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { ChevronDown, Plus, Save, Trash2 } from "lucide-react";
import Image from "next/image";
import { matchSourceIdentity } from "@/lib/connected-sources";
import { useToast } from "@/components/toast-provider";
import {
  discardWorkspaceDraft,
  getDraftOwner,
  readWorkspaceDraft,
  retainWorkspaceDraft,
  type WorkspaceDraftKey,
} from "@/lib/workspace-drafts";
import {
  configValue,
  configFieldErrors,
  nextDestination,
  newProfile,
  profileKind,
  setConfigValue,
  supportsWatcherConfig,
  validateWatcherConfig,
  watcherNames,
  type ConfigPath,
  type ConfigSnapshot,
  type FieldErrors,
  type ProfileKind,
} from "@/lib/watcher-fields";
import "@/app/watcher-editor.css";

type EditorContext = {
  draft: Record<string, unknown>;
  errors: FieldErrors;
  update: (path: ConfigPath, value: unknown) => void;
  touch: (path: ConfigPath) => void;
  prefix: string;
};
const Context = createContext<EditorContext | null>(null);
function useEditor() {
  const value = useContext(Context);
  if (!value) throw new Error("Editor context missing");
  return value;
}

function Field({
  path,
  label,
  hint,
  type = "text",
  min,
  max,
  step,
  options,
  multiline = false,
  nullable = false,
  fallback,
}: {
  path: ConfigPath;
  label: string;
  hint?: string;
  type?: "text" | "number" | "url";
  min?: number;
  max?: number;
  step?: number;
  options?: [string, string][];
  multiline?: boolean;
  nullable?: boolean;
  fallback?: string;
}) {
  const { draft, errors, update, touch, prefix } = useEditor();
  const key = path.join(".");
  const id = `${prefix}-${key}`;
  const value = configValue(draft, path);
  const common = {
    id,
    name: key,
    "aria-invalid": Boolean(errors[key]),
    "aria-describedby": errors[key] ? `${id}-error` : hint ? `${id}-hint` : undefined,
    onBlur: () => touch(path),
  };
  const stringValue =
    typeof value === "string" || typeof value === "number" ? String(value) : (fallback ?? "");
  return (
    <div className={`watcher-field${multiline ? " watcher-field-wide" : ""}`}>
      <label htmlFor={id}>{label}</label>
      {multiline ? (
        <textarea
          {...common}
          rows={3}
          value={stringValue}
          onChange={(event) => update(path, event.target.value)}
        />
      ) : options ? (
        <select
          {...common}
          value={stringValue}
          onChange={(event) => update(path, event.target.value)}
        >
          {!options.some(([value]) => value === stringValue) ? (
            <option value={stringValue}>{stringValue || "Choose an option"}</option>
          ) : null}
          {options.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      ) : (
        <input
          {...common}
          type={type}
          value={stringValue}
          min={min}
          max={max}
          step={step}
          autoComplete="off"
          spellCheck={false}
          inputMode={
            type === "number" ? "decimal" : key.endsWith("channel_id") ? "numeric" : undefined
          }
          onChange={(event) =>
            update(
              path,
              type === "number"
                ? event.target.value === ""
                  ? ""
                  : Number(event.target.value)
                : nullable && !event.target.value
                  ? null
                  : event.target.value,
            )
          }
        />
      )}
      {hint ? <small id={`${id}-hint`}>{hint}</small> : null}
      {errors[key] ? (
        <small className="watcher-field-error" id={`${id}-error`}>
          {errors[key]}
        </small>
      ) : null}
    </div>
  );
}

function Toggle({ path, label, hint }: { path: ConfigPath; label: string; hint?: string }) {
  const { draft, update, errors, prefix } = useEditor();
  const key = path.join(".");
  const id = `${prefix}-${key}`;
  return (
    <label className="watcher-toggle" htmlFor={id}>
      <input
        id={id}
        type="checkbox"
        checked={configValue(draft, path) === true}
        aria-invalid={Boolean(errors[key])}
        aria-describedby={errors[key] ? `${id}-error` : undefined}
        onChange={(event) => update(path, event.target.checked)}
      />
      <span>
        {label}
        {hint ? <small>{hint}</small> : null}
        {errors[key] ? (
          <small id={`${id}-error`} className="watcher-field-error">
            {errors[key]}
          </small>
        ) : null}
      </span>
    </label>
  );
}

function Group({ title, children, hint }: { title: string; children: ReactNode; hint?: string }) {
  return (
    <fieldset className="watcher-group">
      <legend>{title}</legend>
      {hint ? <p className="watcher-help">{hint}</p> : null}
      <div className="watcher-fields">{children}</div>
    </fieldset>
  );
}

function Channels({ path, kind }: { path: ConfigPath; kind: ProfileKind }) {
  const { draft, errors, update } = useEditor();
  const raw = configValue(draft, path);
  const rows = Array.isArray(raw) ? raw : [];
  const next =
    nextDestination(kind, rows) ??
    (kind === "whatsapp" && !rows.some((row) => configValue(row, ["key"]) === "id_industry_news")
      ? { key: "id_industry_news", channel_id: "", description: "" }
      : null);
  return (
    <section className="watcher-routes" aria-label="Discord destinations">
      <h4>Discord destinations</h4>
      <p className="watcher-help">
        Give each route a distinct key and a description of the content it should receive.
      </p>
      {rows.map((_, index) => (
        <div className="watcher-route" key={index}>
          <div className="watcher-fields">
            <Field
              path={[...path, index, "key"]}
              label="Route key"
              options={
                kind === "whatsapp"
                  ? [
                      ["id_stocks_news", "Stock news"],
                      ["macro_news", "Macro news"],
                      ["id_industry_news", "Industry news"],
                      ["id_stocks_swing", "Swing calls"],
                    ]
                  : undefined
              }
            />
            <Field path={[...path, index, "channel_id"]} label="Discord channel ID" />
            <Field path={[...path, index, "description"]} label="Content description" />
            <button
              type="button"
              className="button ghost watcher-remove"
              onClick={() => {
                if (window.confirm("Remove this destination from the draft?"))
                  update(
                    path,
                    rows.filter((_, row) => row !== index),
                  );
              }}
            >
              <Trash2 size={16} aria-hidden="true" />
              Remove destination {index + 1}
            </button>
          </div>
        </div>
      ))}
      {errors[path.join(".")] ? (
        <p className="watcher-field-error" role="alert" tabIndex={-1}>
          {errors[path.join(".")]}
        </p>
      ) : null}
      <button
        type="button"
        className="button secondary"
        disabled={!next}
        onClick={() => {
          if (next) update(path, [...rows, next]);
        }}
      >
        <Plus size={16} aria-hidden="true" />
        Add destination
      </button>
    </section>
  );
}

const relevanceOptions: [string, string][] = [
  ["stock_market", "Stock market"],
  ["financial_market", "Financial markets"],
  ["indonesia_economy", "Indonesian economy"],
];

function ProfileIdentity({
  profile: rawProfile,
  kind,
  index,
}: {
  profile: unknown;
  kind: ProfileKind;
  index: number;
}) {
  const profile =
    rawProfile && typeof rawProfile === "object" && !Array.isArray(rawProfile)
      ? (rawProfile as Record<string, unknown>)
      : {};
  const identity = matchSourceIdentity(kind, profile);
  const name =
    typeof profile.display_name === "string" && profile.display_name.trim()
      ? profile.display_name
      : `Source ${index + 1}`;
  const destinations = Array.isArray(profile.discord_channels)
    ? profile.discord_channels.length
    : 0;
  return (
    <span className="watcher-profile-identity">
      <span
        className={`watcher-source-avatar${identity?.portrait ? " is-portrait" : ""}`}
        aria-hidden="true"
      >
        {identity?.image ? (
          <Image src={identity.image} alt="" width={44} height={44} />
        ) : (
          name.slice(0, 2).toUpperCase()
        )}
      </span>
      <span className="watcher-profile-name">
        <strong>{name}</strong>
        <small>
          {kind === "whatsapp"
            ? "WhatsApp Channel"
            : typeof profile.handle === "string"
              ? `@${profile.handle.replace(/^@/, "")}`
              : kind === "x"
                ? "X account"
                : "Instagram account"}{" "}
          · {destinations} {destinations === 1 ? "destination" : "destinations"}
        </small>
      </span>
    </span>
  );
}

function ProfileFields({ index, kind }: { index: number; kind: ProfileKind }) {
  const { draft, update, errors, prefix } = useEditor();
  const path = ["profiles", index];
  const at = (key: string) => [...path, key];
  const rawLanguages = configValue(draft, at("ocr_languages"));
  const languages = Array.isArray(rawLanguages) ? rawLanguages : [];
  return (
    <>
      <Group title="Input source">
        <Field path={at("id")} label="Profile ID" hint="A stable, unique name for this source." />
        <Field path={at("display_name")} label="Display name" />
        {kind === "whatsapp" ? (
          <>
            <Field
              path={at("channel_jid")}
              label="WhatsApp channel identifier"
              hint="Ends in @newsletter."
            />
            <Field path={at("channel_url")} label="Channel URL" type="url" />
            <Field
              path={at("mode")}
              label="Channel mode"
              options={[
                ["observe", "Observe only"],
                ["forward", "Forward to Discord"],
              ]}
              hint="Observe collects channel posts without forwarding or AI analysis. Changing mode keeps your other settings intact."
            />
          </>
        ) : (
          <>
            <Field path={at("handle")} label="Account handle" hint="Without the @ symbol." />
            <Field path={at("profile_url")} label="Profile URL" type="url" />
            {kind === "x" ? (
              <Field
                path={at("source")}
                label="Source connection"
                fallback="rsshub"
                options={[
                  ["rsshub", "RSS feed"],
                  ["direct_x", "Direct X"],
                ]}
              />
            ) : null}
          </>
        )}
        <Toggle path={at("enabled")} label="Watch this source" />
      </Group>
      <p className="watcher-source-note">
        {configValue(draft, at("enabled")) === true
          ? "Source enabled in this draft. Save to update the watcher’s configuration."
          : "This source is paused. It will not collect posts until you enable it and save."}
      </p>
      {kind === "whatsapp" && configValue(draft, at("mode")) === "observe" ? (
        <p className="watcher-source-note">
          Observe only: keep media forwarding and all AI options off, remove Discord destinations
          and leave the source emoji empty. These settings must be reviewed before saving a mode
          change.
        </p>
      ) : null}
      <Group title="Posts and summaries">
        {kind === "x" ? (
          <>
            <Toggle path={at("forward_normal_post")} label="Original posts" />
            <Toggle path={at("forward_quote_post")} label="Quote posts" />
            <Toggle
              path={at("show_quoted_post")}
              label="Show quoted content"
              hint="Include the original quoted content inside forwarded posts. Quote posts above controls which authored posts are eligible."
            />
            <Toggle path={at("forward_reply")} label="Replies" />
            <Toggle path={at("forward_repost")} label="Reposts" />
          </>
        ) : null}
        {kind === "instagram" ? (
          <>
            <Toggle path={at("forward_post")} label="Posts" />
            <Toggle path={at("forward_reel")} label="Reels" />
          </>
        ) : null}
        <Toggle path={at("forward_media")} label="Include media" />
        <Toggle path={at("enable_llm_title")} label="Generate titles" />
        <Toggle path={at("enable_llm_summary")} label="Summarize posts" />
        <Toggle path={at("enable_llm_relevance_filter")} label="Filter for relevance" />
        <Toggle
          path={at("enable_llm_routing")}
          label="Choose a destination by content"
          hint="Uses the destination descriptions below."
        />
        {kind !== "instagram" ? (
          <Field
            path={at("relevance_scope")}
            label="Relevant topics"
            options={relevanceOptions}
            fallback="stock_market"
          />
        ) : null}
        <Field
          path={at("additional_prompt_instruction")}
          label="Additional instructions"
          multiline
          hint={
            kind === "x"
              ? "Optional. Up to 800 characters."
              : "Optional guidance for titles, summaries and relevance."
          }
        />
      </Group>
      {kind === "x" && configValue(draft, at("enable_llm_relevance_filter")) !== false ? (
        <p className="watcher-source-note">
          Relevance filtering is on. Personal updates and unrelated test posts may be skipped rather
          than sent to Discord.
        </p>
      ) : null}
      <Channels path={at("discord_channels")} kind={kind} />
      <details className="watcher-advanced">
        <summary>Processing and appearance</summary>
        <Group title="Processing limits">
          <Field
            path={at("max_items_per_poll")}
            label="Maximum items per check"
            type="number"
            min={1}
            max={kind === "whatsapp" ? 50 : 100}
            step={1}
          />
          {kind === "x" ? (
            <>
              <Field
                path={at("media_policy")}
                label="Media selection"
                fallback="all"
                options={[
                  ["all", "All media"],
                  ["omit_last", "Skip the last media item"],
                ]}
              />
              <Field
                path={[...at("thread_handling"), "mode"]}
                label="Thread handling"
                options={[
                  ["self_chain", "Collect connected posts"],
                  ["disabled", "Individual posts"],
                ]}
              />
              <Field
                path={[...at("thread_handling"), "max_posts"]}
                label="Maximum posts per thread"
                type="number"
                min={1}
                max={20}
              />
              <Field
                path={[...at("thread_handling"), "max_age_minutes"]}
                label="Thread age limit (minutes)"
                type="number"
                min={1}
                max={1440}
              />
              <Field
                path={[...at("thread_handling"), "settle_minutes"]}
                label="Wait for thread updates (minutes)"
                type="number"
                min={1}
                max={240}
              />
            </>
          ) : null}
          {kind === "instagram" ? (
            <>
              <Field
                path={at("ocr_min_confidence")}
                label="Image text confidence"
                type="number"
                min={0}
                max={1}
                step={0.01}
                hint="Minimum confidence from 0 to 1."
              />
              <Field
                path={at("max_reel_frames")}
                label="Maximum frames per reel"
                type="number"
                min={1}
                max={8}
              />
              <fieldset
                className="watcher-languages"
                aria-describedby={
                  errors[at("ocr_languages").join(".")]
                    ? `${prefix}-${index}-languages-error`
                    : undefined
                }
              >
                <legend>Image text languages</legend>
                {[
                  ["eng", "English"],
                  ["ind", "Indonesian"],
                ].map(([value, label]) => (
                  <label
                    className="watcher-toggle"
                    key={value}
                    htmlFor={`${prefix}-${index}-language-${value}`}
                  >
                    <input
                      id={`${prefix}-${index}-language-${value}`}
                      type="checkbox"
                      checked={languages.includes(value)}
                      aria-invalid={Boolean(errors[at("ocr_languages").join(".")])}
                      onChange={(event) =>
                        update(
                          at("ocr_languages"),
                          event.target.checked
                            ? [...languages, value]
                            : languages.filter((language) => language !== value),
                        )
                      }
                    />
                    {label}
                  </label>
                ))}
                {errors[at("ocr_languages").join(".")] ? (
                  <small className="watcher-field-error" id={`${prefix}-${index}-languages-error`}>
                    {errors[at("ocr_languages").join(".")]}
                  </small>
                ) : null}
              </fieldset>
            </>
          ) : null}
        </Group>
        <Group title="Message appearance">
          <Field
            path={at("emoji")}
            label="Source emoji"
            nullable={kind === "whatsapp"}
            hint={
              kind === "instagram"
                ? "Optional text or custom emoji."
                : kind === "whatsapp"
                  ? "Required for forwarding in <:name:ID> format. Leave empty for observe-only mode."
                  : "Discord custom emoji in <:name:ID> format."
            }
          />
          {kind === "x" ? (
            <Field
              path={at("twitter_emoji")}
              label="X platform emoji"
              hint="Discord custom emoji in <:name:ID> format."
            />
          ) : null}
          {kind === "instagram" ? (
            <Field path={at("platform_emoji")} label="Instagram platform emoji" />
          ) : null}
          {kind === "whatsapp" ? (
            <>
              <Field
                path={[...at("status_emojis"), "up"]}
                label="Up status emoji"
                nullable
                hint="Optional custom emoji. Leave empty to omit."
              />
              <Field path={[...at("status_emojis"), "down"]} label="Down status emoji" nullable />
              <Field path={[...at("status_emojis"), "hold"]} label="Hold status emoji" nullable />
            </>
          ) : null}
        </Group>
      </details>
    </>
  );
}

function TelegramFields({ watcherId }: { watcherId: string }) {
  const news = watcherId === "bursawatch-tg-market-news";
  const board = watcherId === "bursawatch-dc-swing-board";
  return (
    <>
      {!board ? (
        <Group title="Telegram sources">
          {news ? (
            <>
              <Field
                path={["providers", "phintraco", "telegram_username"]}
                label="Phintraco username"
                hint="Without the @ symbol."
              />
              <Field
                path={["providers", "tuntun", "telegram_username"]}
                label="Tuntun username"
                hint="Without the @ symbol."
              />
            </>
          ) : (
            <>
              <Field
                path={["source", "telegram_username"]}
                label="Channel username"
                hint="Without the @ symbol."
              />
              <Field
                path={["source", "telegram_channel_id"]}
                label="Telegram channel ID"
                type="number"
                min={1}
                max={9_999_999_999}
                step={1}
              />
            </>
          )}
        </Group>
      ) : null}
      <Group
        title="Discord destinations"
        hint="Use channel IDs from the Discord server you manage."
      >
        {news ? (
          <>
            <Field
              path={["destinations", "id_stocks_news_discord_channel_id"]}
              label="Stock news channel ID"
            />
            <Field
              path={["destinations", "macro_news_discord_channel_id"]}
              label="Macro news channel ID"
            />
            <Field
              path={["destinations", "industry_news_discord_channel_id"]}
              label="Industry news channel ID"
            />
          </>
        ) : !board ? (
          <Field path={["destinations", "alert_discord_channel_id"]} label="Alert channel ID" />
        ) : null}
        <Field
          path={["destinations", "heartbeat_discord_channel_id"]}
          label="Heartbeat channel ID"
          hint="Operational updates for each run."
        />
      </Group>
      {news || watcherId === "bursawatch-tg-kelas-investasi-gtw" ? (
        <Group title="Summary guidance">
          <Field
            path={["additional_prompt_instruction"]}
            label="Additional instructions"
            multiline
            hint="Optional. Up to 800 characters."
          />
        </Group>
      ) : null}
    </>
  );
}

function StockbitFields() {
  const { draft, errors } = useEditor();
  const feeds = Array.isArray(draft.feeds) ? draft.feeds : [];
  const lanes = [
    ["stockbit_commentary", "Stockbit Commentary"],
    ["unboxing", "Unboxing"],
    ["unboxing_ipo", "Unboxing IPO"],
    ["ai_reports_stockbit", "AI Reports Stockbit"],
  ] as const;
  return (
    <>
      <Group
        title="Stockbit feeds"
        hint="Pause or resume intake for each fixed feed. Resuming starts with new items after the next successful check; work already queued continues."
      >
        {lanes.map(([id, label]) => {
          const index = feeds.findIndex((feed) => configValue(feed, ["id"]) === id);
          return index < 0 ? null : (
            <Toggle key={id} path={["feeds", index, "enabled"]} label={label} />
          );
        })}
        {errors.feeds ? (
          <p className="watcher-field-error" role="alert">
            {errors.feeds}
          </p>
        ) : null}
      </Group>
      <Group
        title="Discord destinations"
        hint="These two route names are fixed. Use distinct channel IDs from the Discord server you manage."
      >
        <Field path={["destinations", "id_stocks_news_channel_id"]} label="Stock news channel ID" />
        <Field path={["destinations", "macro_news_channel_id"]} label="Macro news channel ID" />
      </Group>
      <Group title="Analysis guidance">
        <Field
          path={["additional_prompt_instruction"]}
          label="Additional instructions"
          multiline
          hint="Optional. Up to 800 characters after whitespace normalization. Added to the fixed analysis rules for future article work."
        />
      </Group>
    </>
  );
}

export function useUnsavedWarning(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    const onNavigate = (event: MouseEvent) => {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      const anchor = (event.target as Element)?.closest?.("a[href]");
      if (
        !(anchor instanceof HTMLAnchorElement) ||
        anchor.target === "_blank" ||
        anchor.hasAttribute("download")
      )
        return;
      const url = new URL(anchor.href);
      if (url.pathname === window.location.pathname && url.search === window.location.search)
        return;
      if (!window.confirm("You have unsaved changes. Leave without saving?")) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", onNavigate, true);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", onNavigate, true);
    };
  }, [dirty]);
}

export function WatcherConfigEditor({
  snapshot,
  onSave,
  onDirtyChange,
}: {
  snapshot: ConfigSnapshot;
  onSave: (config: Record<string, unknown>) => Promise<ConfigSnapshot>;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const draftKey: WorkspaceDraftKey = `config:${snapshot.watcher_id}`;
  const [draftOwner] = useState(getDraftOwner);
  const [restored] = useState(() =>
    readWorkspaceDraft<ConfigSnapshot, Record<string, unknown>>(draftKey),
  );
  const restoredConflict = Boolean(restored && restored.base.revision !== snapshot.revision);
  const [saved, setSaved] = useState(restored?.base ?? snapshot);
  const [receivedSnapshot, setReceivedSnapshot] = useState(snapshot);
  const [draft, setDraft] = useState(() => structuredClone(restored?.draft ?? snapshot.config));
  const [errors, setErrors] = useState<FieldErrors>({});
  const [failure, setFailure] = useState(
    restoredConflict
      ? "The configuration changed while you were away. Your draft is preserved; reload to review the latest saved configuration."
      : restored?.failure ||
          (restored?.blocked ? "Reload the saved configuration before trying to save again." : ""),
  );
  const [blocked, setBlocked] = useState(restoredConflict || (restored?.blocked ?? false));
  const [saving, setSaving] = useState(false);
  const [restoredNotice, setRestoredNotice] = useState(Boolean(restored));
  const [savedNotice, setSavedNotice] = useState("");
  const prefix = useId();
  const form = useRef<HTMLFormElement>(null);
  const toast = useToast();
  const dirty = JSON.stringify(saved.config) !== JSON.stringify(draft);
  if (snapshot !== receivedSnapshot) {
    setReceivedSnapshot(snapshot);
    if (!saving && !blocked) {
      if (dirty && snapshot.revision !== saved.revision) {
        setBlocked(true);
        setFailure(
          "The configuration changed elsewhere. Your draft is preserved; reload to review the latest saved configuration.",
        );
      } else if (!dirty) {
        setSaved(snapshot);
        setDraft(structuredClone(snapshot.config));
      }
    }
  }
  useUnsavedWarning(dirty || saving);
  useEffect(() => {
    retainWorkspaceDraft(
      draftKey,
      {
        base: saved,
        draft,
        blocked: blocked || saving,
        failure: saving
          ? "A previous save has not been confirmed here. Reload the saved configuration before trying again."
          : failure,
      },
      dirty,
      draftOwner,
    );
  }, [draftKey, draftOwner, saved, draft, blocked, saving, failure, dirty]);
  useEffect(() => {
    onDirtyChange?.(dirty || saving);
    return () => onDirtyChange?.(false);
  }, [dirty, saving, onDirtyChange]);
  const kind = profileKind(saved.watcher_id);
  const profiles = Array.isArray(draft.profiles) ? draft.profiles : [];
  const known =
    supportsWatcherConfig(saved.watcher_id, saved.config_version) &&
    saved.config.version === saved.config_version;
  function focusErrors() {
    requestAnimationFrame(() => {
      form.current?.querySelectorAll("details").forEach((detail) => {
        detail.open = true;
      });
      const first = form.current?.querySelector<HTMLElement>("[aria-invalid=true]:not(:disabled)");
      (first ?? form.current?.querySelector<HTMLElement>("[role=alert]"))?.focus();
    });
  }
  function update(path: ConfigPath, value: unknown) {
    setDraft((current) => setConfigValue(current, path, value));
    setSavedNotice("");
    setErrors((current) => {
      const next = { ...current };
      delete next[path.join(".")];
      return next;
    });
  }
  function touch(path: ConfigPath) {
    const key = path.join(".");
    const next = validateWatcherConfig(saved.watcher_id, draft);
    setErrors((current) => {
      const errors = { ...current };
      if (next[key]) errors[key] = next[key];
      else delete errors[key];
      return errors;
    });
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (saving || blocked || !dirty) return;
    const nextErrors = validateWatcherConfig(saved.watcher_id, draft);
    setErrors(nextErrors);
    setFailure("");
    setSavedNotice("");
    if (Object.keys(nextErrors).length) {
      focusErrors();
      return;
    }
    setSaving(true);
    try {
      const result = await onSave(structuredClone(draft));
      discardWorkspaceDraft(draftKey, draftOwner);
      setSaved(result);
      setDraft(structuredClone(result.config));
      setRestoredNotice(false);
      setSavedNotice(`Configuration saved as revision ${result.revision}.`);
      toast("Watcher configuration saved.");
    } catch (error) {
      const code = error && typeof error === "object" && "code" in error ? error.code : undefined;
      const fields = error && typeof error === "object" && "fields" in error ? error.fields : [];
      setErrors(configFieldErrors(fields));
      setBlocked(code === "unknown-outcome" || code === "conflict");
      setFailure(
        error instanceof Error
          ? error.message
          : "Could not save. Your draft is still here; try again shortly.",
      );
      focusErrors();
    } finally {
      setSaving(false);
    }
  }
  return (
    <Context.Provider value={{ draft, errors, update, touch, prefix }}>
      <form className="watcher-editor" ref={form} onSubmit={submit} noValidate aria-busy={saving}>
        <header className="watcher-editor-header">
          <div>
            <h2>Watcher configuration</h2>
            <p>
              Revision {saved.revision} · {watcherNames[saved.watcher_id] ?? "Watcher"}
            </p>
          </div>
          <span className={`watcher-draft-status${dirty ? " is-dirty" : ""}`}>
            {dirty ? "Unsaved changes" : "Saved configuration"}
          </span>
        </header>
        {!known ? (
          <p role="alert">
            This configuration version is not supported by this editor. Ask your administrator to
            review it.
          </p>
        ) : (
          <>
            {restoredNotice ? (
              <p className="watcher-feedback" role="status">
                Your unsaved draft was restored for this tab. It will be cleared when you reload the
                page or sign out.
              </p>
            ) : null}
            {Object.keys(errors).length ? (
              <div className="watcher-feedback is-error" role="alert" tabIndex={-1}>
                Review the marked fields before saving.{" "}
                {errors.version || errors[""] || errors.profiles || ""}
              </div>
            ) : null}
            <fieldset className="watcher-form-body" disabled={saving || blocked}>
              {kind ? (
                <>
                  <div className="watcher-source-intro">
                    <h3>
                      {profiles.length} {profiles.length === 1 ? "source" : "sources"}
                    </h3>
                    <p className="watcher-help">
                      Open a source to edit its input, summary rules and Discord destinations.
                      Changes are shared across this workspace after saving.
                    </p>
                  </div>
                  <div className="watcher-profile-list">
                    {profiles.map((profile, index) => (
                      <details
                        className="watcher-profile"
                        key={index}
                        open={profiles.length === 1 || undefined}
                      >
                        <summary>
                          <ProfileIdentity
                            profile={profile as Record<string, unknown>}
                            kind={kind}
                            index={index}
                          />
                          <small className="watcher-profile-state">
                            {(profile as Record<string, unknown>)?.enabled === true
                              ? "Enabled"
                              : "Paused"}
                          </small>
                          <ChevronDown
                            className="watcher-profile-chevron"
                            size={18}
                            aria-hidden="true"
                          />
                        </summary>
                        <div className="watcher-profile-content">
                          <ProfileFields index={index} kind={kind} />
                          <button
                            className="button ghost watcher-remove"
                            type="button"
                            disabled={kind !== "whatsapp" && profiles.length === 1}
                            aria-describedby={
                              kind !== "whatsapp" && profiles.length === 1
                                ? `${prefix}-last-source`
                                : undefined
                            }
                            onClick={() => {
                              if (
                                window.confirm(
                                  "Remove this source from the draft? This takes effect after you save.",
                                )
                              )
                                update(
                                  ["profiles"],
                                  profiles.filter((_, row) => row !== index),
                                );
                            }}
                          >
                            <Trash2 size={16} aria-hidden="true" />
                            Remove source
                          </button>
                          {kind !== "whatsapp" && profiles.length === 1 ? (
                            <p id={`${prefix}-last-source`} className="watcher-help">
                              This workflow requires at least one source. Turn off “Watch this
                              source” to pause it instead.
                            </p>
                          ) : null}
                        </div>
                      </details>
                    ))}
                  </div>
                  <button
                    className="button secondary"
                    type="button"
                    onClick={() => update(["profiles"], [...profiles, newProfile(kind)])}
                  >
                    <Plus size={16} aria-hidden="true" />
                    Add {kind === "whatsapp" ? "channel" : "account"}
                  </button>
                </>
              ) : saved.watcher_id === "bursawatch-stockbit-snips" ? (
                <StockbitFields />
              ) : (
                <TelegramFields watcherId={saved.watcher_id} />
              )}
            </fieldset>
            {failure ? (
              <div className="watcher-feedback is-error" role="alert" tabIndex={-1}>
                <p>{failure}</p>
                {blocked ? (
                  <p>
                    Your draft is preserved. Open this watcher in another tab to compare its saved
                    configuration before reloading this editor.
                  </p>
                ) : null}
              </div>
            ) : null}
            {savedNotice ? (
              <p className="watcher-feedback" role="status">
                {savedNotice}
              </p>
            ) : null}
            <footer className="watcher-editor-actions">
              <p>
                {saving
                  ? "Saving configuration…"
                  : dirty
                    ? "Save settings for the watcher’s next check."
                    : "Saved settings do not confirm a source check or message delivery."}
              </p>
              <div>
                <button
                  type="button"
                  className="button secondary"
                  disabled={!dirty || saving || blocked}
                  onClick={() => {
                    if (window.confirm("Discard your unsaved changes?")) {
                      discardWorkspaceDraft(draftKey, draftOwner);
                      setDraft(structuredClone(saved.config));
                      setRestoredNotice(false);
                      setErrors({});
                      setFailure("");
                    }
                  }}
                >
                  Discard changes
                </button>
                <button className="button primary" disabled={!dirty || saving || blocked}>
                  <Save size={16} aria-hidden="true" />
                  {saving ? "Saving…" : "Save configuration"}
                </button>
              </div>
            </footer>
          </>
        )}
      </form>
    </Context.Provider>
  );
}
