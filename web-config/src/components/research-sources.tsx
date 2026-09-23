"use client";

import {
  ArrowRight,
  Check,
  ChevronRight,
  Database,
  Globe2,
  Camera,
  MessageCircle,
  Pause,
  Plus,
  RadioTower,
  Search,
  Send,
  Settings2,
  X,
} from "lucide-react";
import Link from "next/link";
import Image from "next/image";
import { recommendedSources } from "@/lib/recommended-sources";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { PageHeading } from "@/components/page-heading";
import { useResearchSources } from "@/components/use-research-sources";
import {
  blankSource,
  platforms,
  sourceDraftSchema,
  sourceInputSchema,
  topics,
  updateResearch,
  type Platform,
  type ResearchSource,
  type SourceInput,
  type Topic,
} from "@/lib/research-sources";

const platformIcons = { x: Globe2, instagram: Camera, whatsapp: MessageCircle, telegram: Send };
const placeholders = {
  x: "https://x.com/username",
  instagram: "https://www.instagram.com/username",
  whatsapp: "https://www.whatsapp.com/channel/…",
  telegram: "https://t.me/channelname",
};

export function SourceEditor({
  source,
  initial,
  onClose,
  onSaved,
}: {
  source?: ResearchSource;
  initial?: SourceInput;
  onClose: () => void;
  onSaved: () => void;
}) {
  const baseline = source?.input ?? initial ?? blankSource;
  const draftKey = `bursawatch-source-draft:${source?.id ?? `new:${initial?.platform ?? "x"}:${initial?.url || "blank"}`}`;
  const [input, setInput] = useState<SourceInput>(() => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(draftKey) ?? "null");
      if (saved?.revision === (source?.revision ?? 0)) return sourceDraftSchema.parse(saved.input);
    } catch {
      /* Start with the persisted settings if a draft is unreadable. */
    }
    return structuredClone(baseline);
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [discard, setDiscard] = useState(false);
  const dirty = JSON.stringify(input) !== JSON.stringify(baseline);
  const formRef = useRef<HTMLFormElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const profile = recommendedSources.find((item) => item.url === baseline.url);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);
  useEffect(() => {
    try {
      if (dirty)
        sessionStorage.setItem(
          draftKey,
          JSON.stringify({ revision: source?.revision ?? 0, input }),
        );
      else sessionStorage.removeItem(draftKey);
    } catch {
      /* The save action reports persistent-storage failures separately. */
    }
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [input, dirty, draftKey, source?.revision]);

  function change<K extends keyof SourceInput>(key: K, value: SourceInput[K]) {
    setInput((current) => ({ ...current, [key]: value }));
    setErrors((current) => ({ ...current, [key]: "", submit: "" }));
  }
  function close() {
    try {
      sessionStorage.removeItem(draftKey);
    } catch {
      /* No persisted profile is removed. */
    }
    onClose();
  }
  function save(event: FormEvent) {
    event.preventDefault();
    const result = sourceInputSchema.safeParse(input);
    if (!result.success) {
      const next: Record<string, string> = {};
      result.error.issues.forEach((issue) => {
        next[String(issue.path[0])] ??= issue.message;
      });
      setErrors(next);
      requestAnimationFrame(() => {
        const field = formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]');
        const disclosure = field?.closest("details");
        if (disclosure) disclosure.open = true;
        field?.focus();
      });
      return;
    }
    try {
      updateResearch({
        type: "save",
        id: source?.id,
        revision: source?.revision,
        input: result.data,
      });
      try {
        sessionStorage.removeItem(draftKey);
      } catch {
        /* Saving the profile succeeded. */
      }
      onSaved();
    } catch (error) {
      setErrors({ submit: (error as Error).message });
    }
  }
  const selectedTopics = input.topics.map((topic) => topics[topic].label.toLowerCase());
  return (
    <section className="research-editor" aria-labelledby="source-editor-title">
      <div className="section-heading">
        <h2 id="source-editor-title" ref={headingRef} tabIndex={-1}>
          {source ? "Edit source" : "Add a source"}
        </h2>
        <button
          className="icon-button"
          aria-label="Close source editor"
          type="button"
          onClick={() => (dirty ? setDiscard(true) : close())}
        >
          <X size={20} aria-hidden="true" />
        </button>
      </div>
      {profile ? (
        <div className="source-profile-context">
          {profile.image ? (
            <Image src={profile.image} width={48} height={48} alt="" />
          ) : (
            <span className="hub-avatar" aria-hidden="true">
              {profile.name
                .split(/\s+/)
                .slice(0, 2)
                .map((word) => word[0])
                .join("")}
            </span>
          )}
          <div>
            <strong>{profile.name}</strong>
            <span>{profile.coverage}</span>
          </div>
        </div>
      ) : null}
      {discard ? (
        <div className="research-notice" role="alert">
          <p>Discard your unsaved changes?</p>
          <div className="research-actions">
            <button className="button secondary" type="button" onClick={() => setDiscard(false)}>
              Keep editing
            </button>
            <button className="button secondary" type="button" onClick={close}>
              Discard changes
            </button>
          </div>
        </div>
      ) : null}
      <form ref={formRef} onSubmit={save} noValidate>
        <div className="research-fields">
          <label className="field-label" htmlFor="source-platform">
            Where is it published?
          </label>
          <select
            id="source-platform"
            className="text-input"
            value={input.platform}
            onChange={(e) => change("platform", e.target.value as Platform)}
          >
            {Object.entries(platforms).map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
          <label className="field-label" htmlFor="research-name">
            Source name
          </label>
          <input
            id="research-name"
            className="text-input"
            value={input.name}
            maxLength={60}
            placeholder="A name you’ll recognize"
            onChange={(e) => change("name", e.target.value)}
            aria-invalid={!!errors.name}
            aria-describedby={errors.name ? "source-name-error" : undefined}
          />
          {errors.name ? (
            <p className="field-error" id="source-name-error">
              {errors.name}
            </p>
          ) : null}
          <label className="field-label" htmlFor="research-url">
            {input.platform === "x" || input.platform === "instagram"
              ? "Profile link or handle"
              : "Public channel link"}
          </label>
          <input
            id="research-url"
            className="text-input"
            value={input.url}
            maxLength={300}
            autoCapitalize="none"
            spellCheck={false}
            placeholder={placeholders[input.platform]}
            onChange={(e) => change("url", e.target.value)}
            aria-invalid={!!errors.url}
            aria-describedby="source-url-help"
          />
          <p id="source-url-help" className={errors.url ? "field-error" : "field-help"}>
            {errors.url ?? "Use the channel or profile itself, rather than a single post."}
          </p>
        </div>
        <fieldset className="research-topic-field">
          <legend>Topics for this source</legend>
          <div className="research-topics">
            {(Object.entries(topics) as [Topic, (typeof topics)[Topic]][]).map(([id, topic]) => (
              <label className="research-topic" key={id}>
                <input
                  type="checkbox"
                  checked={input.topics.includes(id)}
                  onChange={(e) =>
                    change(
                      "topics",
                      e.target.checked
                        ? [...input.topics, id]
                        : input.topics.filter((t) => t !== id),
                    )
                  }
                  aria-invalid={!!errors.topics}
                  aria-describedby={errors.topics ? "source-topics-error" : undefined}
                />
                <span>
                  <strong>{topic.label}</strong>
                  <small>{topic.description}</small>
                </span>
              </label>
            ))}
          </div>
          {errors.topics ? (
            <p className="field-error" id="source-topics-error">
              {errors.topics}
            </p>
          ) : null}
        </fieldset>
        <fieldset className="research-format">
          <legend>How should it read?</legend>
          <label>
            <input
              type="radio"
              name="source-format"
              value="summary"
              checked={input.format === "summary"}
              onChange={() => change("format", "summary")}
            />{" "}
            Concise summary
          </label>
          <label>
            <input
              type="radio"
              name="source-format"
              value="original"
              checked={input.format === "original"}
              onChange={() => change("format", "original")}
            />{" "}
            Original source text
          </label>
        </fieldset>
        <details className="research-options">
          <summary>Media & extra preferences</summary>
          {input.platform === "instagram" ? (
            <fieldset className="research-format">
              <legend>Publications to include</legend>
              <label>
                <input
                  type="checkbox"
                  checked={input.includePosts ?? true}
                  onChange={(e) => change("includePosts", e.target.checked)}
                  aria-invalid={!!errors.includePosts}
                  aria-describedby={
                    errors.includePosts ? "instagram-publications-error" : undefined
                  }
                />{" "}
                Posts and carousels
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={input.includeReels ?? true}
                  onChange={(e) => change("includeReels", e.target.checked)}
                />{" "}
                Reels
              </label>
              {errors.includePosts ? (
                <p id="instagram-publications-error" className="field-error" role="alert">
                  {errors.includePosts}
                </p>
              ) : null}
              <p className="field-help">
                Public posts and reels only. Stories and private accounts are not supported.
              </p>
            </fieldset>
          ) : null}
          <label>
            <input
              type="checkbox"
              checked={input.includeMedia}
              onChange={(e) => change("includeMedia", e.target.checked)}
            />{" "}
            Include source charts and images
          </label>
          {input.platform === "x" ? (
            <>
              <label>
                <input
                  type="checkbox"
                  checked={input.includeOriginals ?? true}
                  onChange={(e) => change("includeOriginals", e.target.checked)}
                  aria-invalid={!!errors.includeOriginals}
                  aria-describedby={errors.includeOriginals ? "x-publications-error" : undefined}
                />{" "}
                Include original posts
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={input.includeReplies ?? false}
                  onChange={(e) => change("includeReplies", e.target.checked)}
                />{" "}
                Include replies
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={input.includeQuotes}
                  onChange={(e) => change("includeQuotes", e.target.checked)}
                />{" "}
                Include quote posts
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={input.includeReposts}
                  onChange={(e) => change("includeReposts", e.target.checked)}
                />{" "}
                Include reposts
              </label>
              {errors.includeOriginals ? (
                <p id="x-publications-error" className="field-error" role="alert">
                  {errors.includeOriginals}
                </p>
              ) : null}
              <label>
                <input
                  type="checkbox"
                  checked={input.groupThreads ?? true}
                  onChange={(e) => change("groupThreads", e.target.checked)}
                />{" "}
                Group posts from the same thread
              </label>
              <p className="field-help">
                Keep a thread together rather than treating each post as separate research. Queue
                timing stays with the backend.
              </p>
            </>
          ) : null}
          <label className="field-label" htmlFor="source-instructions">
            Additional instructions <span>(optional)</span>
          </label>
          <textarea
            id="source-instructions"
            className="text-input"
            rows={3}
            maxLength={600}
            value={input.instructions}
            onChange={(e) => change("instructions", e.target.value)}
            placeholder="For example: focus on Indonesian banks and interest rates."
            aria-describedby="source-instructions-help"
          />
          <p className="field-help" id="source-instructions-help">
            Preferences guide the brief; source facts stay intact. {input.instructions.length}/600
          </p>
        </details>
        <div className="research-receipt" aria-live="polite">
          <h3>Your source rule</h3>
          <p>
            Follow {input.name.trim() || "this source"} on {platforms[input.platform]} for{" "}
            {selectedTopics.length ? selectedTopics.join(", ") : "the topics you choose"}. Keep{" "}
            {input.format === "summary"
              ? "a concise summary with the source link"
              : "the original wording and source link"}
            {input.includeMedia ? ", including available charts and images" : ""}.
          </p>
          <p className="field-help">
            Saved in this browser. Applying preferences to a running watcher requires the backend
            connection.
          </p>
        </div>
        {errors.submit ? (
          <p className="field-error" role="alert">
            {errors.submit}
          </p>
        ) : null}
        <div className="research-save">
          <span>{dirty ? "Unsaved changes" : "Choose your preferences"}</span>
          <button className="button primary" type="submit" disabled={!!source && !dirty}>
            <Check size={17} aria-hidden="true" />
            {source ? "Save changes" : "Save source"}
          </button>
        </div>
      </form>
    </section>
  );
}

export function ResearchSources() {
  const { state, ready, error } = useResearchSources();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Platform | "all">("all");
  const [editor, setEditor] = useState<ResearchSource | "new" | null>(null);
  const [initial, setInitial] = useState<SourceInput | undefined>();
  const [view, setView] = useState<"recommended" | "following">("recommended");
  const [topicFilter, setTopicFilter] = useState<Topic | "all">("all");
  const [showAll, setShowAll] = useState(false);
  const [removeId, setRemoveId] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [failure, setFailure] = useState("");
  const addRef = useRef<HTMLButtonElement>(null);
  const filtered = state.sources.filter(
    (s) =>
      (filter === "all" || filter === s.input.platform) &&
      `${s.input.name} ${s.input.url}`.toLowerCase().includes(query.toLowerCase()),
  );
  const recommendations = recommendedSources.filter(
    (item) =>
      (topicFilter === "all" || (item.topics as Topic[]).includes(topicFilter)) &&
      `${item.name} ${item.handle} ${item.coverage}`.toLowerCase().includes(query.toLowerCase()),
  );
  const visibleRecommendations =
    showAll || query || topicFilter !== "all" ? recommendations : recommendations.slice(0, 6);
  function closeEditor() {
    setEditor(null);
    requestAnimationFrame(() => addRef.current?.focus());
  }
  function act(source: ResearchSource, type: "toggle" | "remove") {
    try {
      updateResearch({ type, id: source.id, revision: source.revision });
      setFailure("");
      setRemoveId(null);
      setNotice(
        type === "remove"
          ? `${source.input.name} removed.`
          : source.enabled
            ? `${source.input.name} paused.`
            : `${source.input.name} included again. Connection verification is still required.`,
      );
    } catch (e) {
      setFailure((e as Error).message);
    }
  }
  return (
    <div className="page-wrap">
      <PageHeading
        title="Sources"
        description="Choose who you follow and which updates reach your brief."
        action={
          <button
            ref={addRef}
            className="button primary"
            type="button"
            disabled={!ready || error || !!editor}
            onClick={() => {
              setNotice("");
              setInitial(undefined);
              setEditor("new");
            }}
          >
            <Plus size={18} aria-hidden="true" /> Add your own
          </button>
        }
      />
      <section className="sectors-foundation" aria-labelledby="sectors-data-title">
        <Database size={23} aria-hidden="true" />
        <div>
          <h2 id="sectors-data-title">Sectors market data</h2>
          <p>Daily prices, trading volume and company context for your IDX watches.</p>
        </div>
        <Link href="/app/watchlist" className="text-link">
          Choose stocks <ArrowRight size={16} aria-hidden="true" />
        </Link>
      </section>
      {error ? (
        <div className="research-notice" role="alert">
          <p>
            Saved sources could not be read. Your existing data has been kept. Allow browser storage
            and reload to try again.
          </p>
          <button
            className="button secondary"
            type="button"
            onClick={() => window.location.reload()}
          >
            Reload sources
          </button>
        </div>
      ) : null}
      {!editor ? (
        <div className="research-view-switch" aria-label="Source directory view">
          <button
            type="button"
            aria-pressed={view === "recommended"}
            onClick={() => setView("recommended")}
          >
            Recommended
          </button>
          <button
            type="button"
            aria-pressed={view === "following"}
            onClick={() => setView("following")}
          >
            Following {!error ? <span>{state.sources.length}</span> : null}
          </button>
        </div>
      ) : null}
      {view === "recommended" && !editor ? (
        <section className="recommended-directory" aria-labelledby="recommended-title">
          <div className="section-heading">
            <h2 id="recommended-title">From our watchlist to yours</h2>
          </div>
          <p className="recommended-intro">
            People and publications selected by the Bursawatch team, alongside official
            institutions. Choose whose work belongs in your brief.
          </p>
          <div className="research-toolbar">
            <div className="research-search">
              <Search size={17} aria-hidden="true" />
              <input
                aria-label="Search recommended accounts"
                placeholder="Find a name or research focus"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <select
              className="text-input"
              aria-label="Filter recommended topics"
              value={topicFilter}
              onChange={(e) => setTopicFilter(e.target.value as Topic | "all")}
            >
              <option value="all">All topics</option>
              {Object.entries(topics).map(([key, value]) => (
                <option key={key} value={key}>
                  {value.label}
                </option>
              ))}
            </select>
          </div>
          {visibleRecommendations.map((item) => {
            const existing = state.sources.find((s) => s.input.url === item.url);
            return (
              <article className="recommended-profile" key={item.id}>
                <div className={item.portrait ? "recommended-image portrait" : "recommended-image"}>
                  {item.image ? (
                    <Image
                      src={item.image}
                      alt={`${item.name} ${item.portrait ? "profile image" : "logo"}`}
                      width={item.portrait ? 96 : 180}
                      height={item.portrait ? 96 : 70}
                    />
                  ) : (
                    <span className="hub-avatar" aria-hidden="true">
                      {item.name
                        .split(/\s+/)
                        .slice(0, 2)
                        .map((word) => word[0])
                        .join("")}
                    </span>
                  )}
                </div>
                <div className="recommended-body">
                  <div className="recommended-heading">
                    <h3>{item.name}</h3>
                    <span
                      className={
                        item.label === "Official institution" ? "institution-label" : "team-label"
                      }
                    >
                      {item.label}
                    </span>
                  </div>
                  <p className="recommended-handle">
                    {item.handle} · {platforms[item.platform]}
                  </p>
                  <p>
                    {item.background} {item.coverage}
                  </p>
                  <p className="recommended-reason">{item.reason}</p>
                  <a className="text-link" href={item.evidence} target="_blank" rel="noreferrer">
                    {item.label === "Official institution"
                      ? "Account listed on its website"
                      : "View public profile"}{" "}
                    <ChevronRight size={15} aria-hidden="true" />
                  </a>
                </div>
                <button
                  className="button secondary"
                  disabled={!ready || error}
                  onClick={() => {
                    setInitial(
                      existing
                        ? undefined
                        : {
                            ...blankSource,
                            name: item.name,
                            platform: item.platform,
                            url: item.url,
                            topics: [...item.topics],
                          },
                    );
                    setEditor(existing ?? "new");
                  }}
                >
                  {existing ? "Edit preferences" : "Choose source"}
                  <ArrowRight size={16} aria-hidden="true" />
                </button>
              </article>
            );
          })}
          {!visibleRecommendations.length ? (
            <div className="research-empty">
              <h3>No matching recommendations</h3>
              <p>Try another name or topic. You can also add your own public source.</p>
              <button
                className="button secondary"
                onClick={() => {
                  setQuery("");
                  setTopicFilter("all");
                }}
              >
                Clear filters
              </button>
            </div>
          ) : null}
          {!showAll && !query && topicFilter === "all" ? (
            <button className="button secondary recommended-more" onClick={() => setShowAll(true)}>
              Show all {recommendedSources.length} sources
            </button>
          ) : null}
          <div className="research-link-row">
            <div>
              <h3>Brokerage research</h3>
              <p>Explore the people and firms behind the research, then choose your preferences.</p>
            </div>
            <Link className="button secondary" href="/app/securities/add">
              Explore securities <ArrowRight size={16} aria-hidden="true" />
            </Link>
          </div>
        </section>
      ) : null}
      {view === "following" || editor ? (
        <>
          <div className={editor ? "research-workspace editing" : "research-workspace"}>
            <section className="research-library" aria-labelledby="research-library-title">
              <div className="section-heading">
                <h2 id="research-library-title">Research sources</h2>
                <span>{state.sources.length} saved</span>
              </div>
              <div className="research-toolbar">
                <div className="research-search">
                  <Search size={17} aria-hidden="true" />
                  <input
                    aria-label="Search research sources"
                    placeholder="Search sources"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </div>
                <select
                  className="text-input"
                  aria-label="Filter by platform"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value as Platform | "all")}
                >
                  <option value="all">All platforms</option>
                  {Object.entries(platforms).map(([id, name]) => (
                    <option key={id} value={id}>
                      {name}
                    </option>
                  ))}
                </select>
              </div>
              {error ? null : !ready ? (
                <p className="empty-copy" role="status">
                  Loading your sources…
                </p>
              ) : !state.sources.length ? (
                <div className="research-empty">
                  <RadioTower size={30} aria-hidden="true" />
                  <h3>Bring your research together</h3>
                  <p>
                    Add a public X or Instagram profile, WhatsApp Channel or Telegram channel.
                    Choose the topics you want to follow.
                  </p>
                  <button
                    className="button secondary"
                    disabled={!!editor}
                    onClick={() => {
                      setInitial(undefined);
                      setEditor("new");
                    }}
                  >
                    Add your first source <ArrowRight size={16} aria-hidden="true" />
                  </button>
                </div>
              ) : !filtered.length ? (
                <div className="research-empty">
                  <h3>No matching sources</h3>
                  <p>Try a different name or show every platform.</p>
                  <button
                    className="button secondary"
                    onClick={() => {
                      setQuery("");
                      setFilter("all");
                    }}
                  >
                    Clear filters
                  </button>
                </div>
              ) : (
                <div className="research-list">
                  {filtered.map((source) => {
                    const Icon = platformIcons[source.input.platform];
                    const identity = recommendedSources.find(
                      (item) => item.url === source.input.url,
                    );
                    return (
                      <article className="research-row" key={source.id}>
                        <div className="research-row-heading">
                          {identity?.image ? (
                            <Image
                              className="following-avatar"
                              src={identity.image}
                              alt=""
                              width={40}
                              height={40}
                            />
                          ) : (
                            <Icon size={21} aria-hidden="true" />
                          )}
                          <div>
                            <h3>{source.input.name}</h3>
                            <p>
                              {platforms[source.input.platform]} ·{" "}
                              {source.enabled ? "Connection needed" : "Paused"}
                            </p>
                          </div>
                          <button
                            className="icon-button"
                            aria-label={`Edit ${source.input.name}`}
                            disabled={!!editor}
                            onClick={() => setEditor(source)}
                          >
                            <Settings2 size={19} aria-hidden="true" />
                          </button>
                        </div>
                        <p className="research-row-topics">
                          {source.input.topics.map((t) => topics[t].label).join(" · ")}
                        </p>
                        <div className="research-row-footer">
                          <a
                            className="text-link"
                            href={source.input.url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            View source <ChevronRight size={15} aria-hidden="true" />
                          </a>
                          <button
                            className="text-link"
                            disabled={!!editor}
                            onClick={() => act(source, "toggle")}
                          >
                            {source.enabled ? <Pause size={14} aria-hidden="true" /> : null}
                            {source.enabled ? "Pause" : "Resume"}
                          </button>
                          <button
                            className="text-link"
                            disabled={!!editor}
                            onClick={() => setRemoveId(source.id)}
                          >
                            Remove
                          </button>
                        </div>
                        {removeId === source.id ? (
                          <div className="research-notice" role="alert">
                            <p>Remove {source.input.name} and its preferences?</p>
                            <div className="research-actions">
                              <button
                                className="button secondary"
                                onClick={() => setRemoveId(null)}
                              >
                                Keep source
                              </button>
                              <button
                                className="button secondary"
                                onClick={() => act(source, "remove")}
                              >
                                Remove source
                              </button>
                            </div>
                          </div>
                        ) : null}
                      </article>
                    );
                  })}
                </div>
              )}
              <p className="saved-confirmation" role="status">
                {notice}
              </p>
              {failure ? (
                <p className="field-error" role="alert">
                  {failure}
                </p>
              ) : null}
              <div className="research-link-row">
                <div>
                  <h3>Following a securities firm?</h3>
                  <p>Choose a brokerage and set its research preferences.</p>
                </div>
                <Link className="text-link" href="/app/securities">
                  Your securities <ArrowRight size={17} aria-hidden="true" />
                </Link>
              </div>
              {!editor ? (
                <div className="research-next">
                  <div>
                    <h3>Put your market watch on a schedule</h3>
                    <p>Choose a daily check and a price condition using Sectors data.</p>
                  </div>
                  <Link className="button secondary" href="/app/automations/new">
                    Create a workflow <ArrowRight size={17} aria-hidden="true" />
                  </Link>
                </div>
              ) : null}
            </section>
            {editor ? (
              <SourceEditor
                key={editor === "new" ? (initial?.url ?? "new") : `${editor.id}:${editor.revision}`}
                source={editor === "new" ? undefined : editor}
                initial={initial}
                onClose={closeEditor}
                onSaved={() => {
                  setView("following");
                  setNotice(
                    "Source preferences saved on this device. Connect the source before collecting updates.",
                  );
                  closeEditor();
                }}
              />
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}
