"use client";

import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type FormEvent } from "react";
import Link from "next/link";
import { ArrowDown, ArrowLeft, ArrowRight, Check, GitBranch, Plus } from "lucide-react";
import { PageHeading } from "./page-heading";
import { WorkflowNavigation } from "./workflow-navigation";
import { useToast } from "./toast-provider";
import {
  blankWorkflow,
  customWorkflowSchema,
  decodeWorkflows,
  restoreWorkflowDraft,
  saveWorkflowChange,
  subscribeWorkflows,
  workflowDraftKey,
  workflowInputs,
  workflowOutputs,
  workflowSnapshot,
  workflowTiming,
  workflowTopics,
  workflowZones,
  type CustomWorkflow,
  type WorkflowInput,
} from "@/lib/custom-workflows";

const serverSnapshot = () => "pending";
type Editor = {
  id?: string;
  draftId?: string;
  revision: number;
  input: WorkflowInput;
  initial: WorkflowInput;
};

function readEditor(saved?: CustomWorkflow, duplicate = false): Editor {
  const initial = structuredClone(saved?.input ?? blankWorkflow);
  if (duplicate) initial.name = `${initial.name.slice(0, 60)} copy`;
  const id = duplicate ? undefined : saved?.id;
  const draftId = duplicate && saved ? `copy:${saved.id}` : id;
  const revision = duplicate ? 0 : (saved?.revision ?? 0);
  let input = structuredClone(initial);
  try {
    input = restoreWorkflowDraft(
      sessionStorage.getItem(workflowDraftKey(draftId)),
      revision,
      initial,
    );
  } catch {
    /* The editor still works when session storage is unavailable. */
  }
  return { id, draftId, revision, input, initial };
}
function forgetDraft(id?: string) {
  try {
    sessionStorage.removeItem(workflowDraftKey(id));
  } catch {
    /* Saved settings stay intact. */
  }
}

export function CustomWorkflows() {
  const raw = useSyncExternalStore(subscribeWorkflows, workflowSnapshot, serverSnapshot);
  const state = useMemo(() => (raw === "pending" ? null : decodeWorkflows(raw)), [raw]);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [removing, setRemoving] = useState<CustomWorkflow | null>(null);
  const [error, setError] = useState("");
  const notify = useToast();
  const heading = useRef<HTMLHeadingElement>(null);
  const keepWorkflow = useRef<HTMLButtonElement>(null);
  const removalTrigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (removing) keepWorkflow.current?.focus();
  }, [removing]);
  function open(saved?: CustomWorkflow, duplicate = false) {
    setEditor(readEditor(saved, duplicate));
    setRemoving(null);
    setError("");
  }
  function close(message?: string) {
    setEditor(null);
    if (message) notify(message);
    requestAnimationFrame(() => heading.current?.focus());
  }
  function remove() {
    if (!removing) return;
    try {
      saveWorkflowChange({ type: "remove", id: removing.id, revision: removing.revision });
      forgetDraft(removing.id);
      setRemoving(null);
      setError("");
      notify("Workflow removed from this browser.");
      requestAnimationFrame(() => heading.current?.focus());
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <div className="page-wrap custom-workflows">
      <PageHeading
        title="Your workflows"
        description="Choose what to follow, when to check and where the brief should go."
      />
      <WorkflowNavigation />
      {raw === "pending" ? (
        <p role="status">Loading your workflows…</p>
      ) : !state ? (
        <div className="research-notice" role="alert">
          <p>
            Saved workflows could not be read. Your existing data has been kept. Allow browser
            storage and reload to try again.
          </p>
          <button className="button secondary" onClick={() => location.reload()}>
            Reload workflows
          </button>
        </div>
      ) : editor ? (
        <WorkflowEditor
          key={`${editor.id ?? "new"}-${editor.revision}`}
          editor={editor}
          onClose={close}
        />
      ) : (
        <>
          <div className="custom-library-heading">
            <div>
              <h2 ref={heading} tabIndex={-1}>
                Saved configurations
              </h2>
              <p>
                {state.workflows.length
                  ? `${state.workflows.length} saved in this browser. No workflows are running.`
                  : "Plan a workflow and save it in this browser. Nothing runs or sends messages yet."}
              </p>
            </div>
            <button className="button primary" onClick={() => open()}>
              <Plus size={18} aria-hidden="true" /> Create your own
            </button>
          </div>
          {error ? (
            <p className="custom-error" role="alert">
              {error}
            </p>
          ) : null}
          {state.workflows.length ? (
            <div className="custom-saved-list">
              {state.workflows.map((item) => (
                <article className="custom-saved-row" key={item.id}>
                  <div className="custom-saved-identity">
                    <GitBranch size={22} aria-hidden="true" />
                    <div>
                      <h3>{item.input.name}</h3>
                      <p>{workflowTiming(item.input)}</p>
                      <p>
                        {item.input.inputs.map((v) => workflowInputs[v]).join(", ")}{" "}
                        <ArrowRight size={14} aria-hidden="true" />{" "}
                        {item.input.outputs.map((v) => workflowOutputs[v]).join(", ")}
                      </p>
                    </div>
                  </div>
                  <div className="custom-row-actions">
                    <button
                      className="button secondary small"
                      onClick={() => open(item)}
                      aria-label={`Edit ${item.input.name}`}
                    >
                      Edit
                    </button>
                    <button
                      className="button secondary small"
                      onClick={() => open(item, true)}
                      aria-label={`Duplicate ${item.input.name}`}
                    >
                      Duplicate
                    </button>
                    <button
                      className="button ghost small"
                      onClick={(event) => {
                        removalTrigger.current = event.currentTarget;
                        setRemoving(item);
                        setError("");
                      }}
                      aria-label={`Remove ${item.input.name}`}
                    >
                      Remove
                    </button>
                  </div>
                  {removing?.id === item.id ? (
                    <div
                      className="custom-removal"
                      role="group"
                      aria-label={`Confirm removal of ${item.input.name}`}
                    >
                      <p>Remove “{item.input.name}” from this browser? This cannot be undone.</p>
                      <div className="custom-row-actions">
                        <button
                          ref={keepWorkflow}
                          className="button secondary"
                          onClick={() => {
                            setRemoving(null);
                            setError("");
                            requestAnimationFrame(() => removalTrigger.current?.focus());
                          }}
                        >
                          Keep workflow
                        </button>
                        <button className="button secondary custom-danger" onClick={remove}>
                          Remove workflow
                        </button>
                      </div>
                    </div>
                  ) : null}
                </article>
              ))}
            </div>
          ) : (
            <div className="custom-empty">
              <GitBranch size={32} aria-hidden="true" />
              <h3>Your research, on your terms.</h3>
              <p>
                Combine the sources you follow with a schedule and an output channel. Start with one
                workflow and refine it as you go.
              </p>
              <Link href="/app/automations/library" className="text-link">
                Explore the workflow library <ArrowRight size={16} aria-hidden="true" />
              </Link>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function WorkflowEditor({
  editor,
  onClose,
}: {
  editor: Editor;
  onClose: (message?: string) => void;
}) {
  const [input, setInput] = useState(editor.input);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saveError, setSaveError] = useState("");
  const [draftError, setDraftError] = useState(false);
  const [discard, setDiscard] = useState(false);
  const form = useRef<HTMLFormElement>(null);
  const keepEditing = useRef<HTMLButtonElement>(null);
  const discardTrigger = useRef<HTMLButtonElement>(null);
  const dirty = JSON.stringify(input) !== JSON.stringify(editor.initial);
  const recovered = JSON.stringify(editor.input) !== JSON.stringify(editor.initial);
  const draftKey = workflowDraftKey(editor.draftId);

  useEffect(() => {
    if (discard) keepEditing.current?.focus();
  }, [discard]);

  function requestClose(trigger: HTMLButtonElement) {
    if (dirty) {
      discardTrigger.current = trigger;
      setDiscard(true);
    } else onClose();
  }

  useEffect(() => {
    form.current?.querySelector<HTMLInputElement>("#workflow-name")?.focus();
  }, []);
  useEffect(() => {
    try {
      if (dirty)
        sessionStorage.setItem(draftKey, JSON.stringify({ revision: editor.revision, input }));
      else sessionStorage.removeItem(draftKey);
    } catch {
      /* Persistent save is explicit; show session-draft recovery warning below. */
    }
    const leave = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", leave);
    return () => window.removeEventListener("beforeunload", leave);
  }, [draftKey, dirty, editor.revision, input]);

  function update<K extends keyof WorkflowInput>(key: K, value: WorkflowInput[K]) {
    const next = { ...input, [key]: value };
    setInput(next);
    setErrors((existing) => {
      const values = { ...existing };
      delete values[key];
      return values;
    });
    setSaveError("");
    setDiscard(false);
    try {
      sessionStorage.setItem(draftKey, JSON.stringify({ revision: editor.revision, input: next }));
      setDraftError(false);
    } catch {
      setDraftError(true);
    }
  }
  function toggle<K extends "inputs" | "topics" | "outputs">(
    key: K,
    value: WorkflowInput[K][number],
  ) {
    const selected: string[] = input[key];
    update(
      key,
      (selected.includes(value)
        ? selected.filter((item) => item !== value)
        : [...selected, value]) as WorkflowInput[K],
    );
  }
  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaveError("");
    const parsed = customWorkflowSchema.safeParse(input);
    if (!parsed.success) {
      const nextErrors: Record<string, string> = {};
      for (const issue of parsed.error.issues) nextErrors[String(issue.path[0])] ??= issue.message;
      setErrors(nextErrors);
      requestAnimationFrame(() => {
        const target = form.current?.querySelector<HTMLElement>(
          `[data-field="${Object.keys(nextErrors)[0]}"]`,
        );
        (target?.matches("input, select")
          ? target
          : target?.querySelector<HTMLElement>("input, select")
        )?.focus();
      });
      return;
    }
    try {
      saveWorkflowChange({
        type: "save",
        id: editor.id,
        revision: editor.revision,
        input: parsed.data,
      });
      forgetDraft(editor.draftId);
      onClose("Workflow saved in this browser. It is not running.");
    } catch (e) {
      setSaveError((e as Error).message);
    }
  }
  const fieldError = (key: string) =>
    errors[key] ? (
      <p className="custom-error" id={`workflow-${key}-error`} role="alert">
        {errors[key]}
      </p>
    ) : null;
  return (
    <>
      <button
        className="text-link custom-editor-back"
        type="button"
        onClick={(event) => requestClose(event.currentTarget)}
      >
        <ArrowLeft size={17} aria-hidden="true" /> Your saved workflows
      </button>
      <div className="custom-editor-heading">
        <h2>{editor.id ? "Edit workflow" : "Create a workflow"}</h2>
        <p>Save your plan in this browser. Nothing runs or sends messages yet.</p>
      </div>
      {recovered ? (
        <p className="field-help" role="status">
          Your unsaved draft was restored.
        </p>
      ) : null}
      {draftError ? (
        <p className="custom-error" role="status">
          Draft recovery is unavailable in this browser. Keep this page open until you save.
        </p>
      ) : null}
      <div className="custom-editor-layout">
        <form ref={form} className="custom-workflow-form" onSubmit={save} noValidate>
          <section className="custom-form-section" aria-labelledby="workflow-name-heading">
            <h3 id="workflow-name-heading">Give it a name</h3>
            <label htmlFor="workflow-name">Workflow name</label>
            <input
              id="workflow-name"
              data-field="name"
              autoComplete="off"
              maxLength={70}
              value={input.name}
              onChange={(e) => update("name", e.target.value)}
              placeholder="Morning market brief"
              aria-invalid={Boolean(errors.name)}
              aria-describedby={errors.name ? "workflow-name-error" : undefined}
            />
            {fieldError("name")}
          </section>
          <section className="custom-form-section" aria-labelledby="workflow-input-heading">
            <h3 id="workflow-input-heading">Inputs</h3>
            <p>
              Choose platforms for accounts you follow in{" "}
              <Link className="text-link" href="/app/following">
                Following
              </Link>
              .
            </p>
            <fieldset
              data-field="inputs"
              aria-invalid={Boolean(errors.inputs)}
              aria-describedby={errors.inputs ? "workflow-inputs-error" : undefined}
            >
              <legend>Source platforms</legend>
              <div className="custom-choices">
                {Object.entries(workflowInputs).map(([key, label]) => (
                  <label key={key}>
                    <input
                      type="checkbox"
                      checked={input.inputs.includes(key as WorkflowInput["inputs"][number])}
                      onChange={() => toggle("inputs", key as WorkflowInput["inputs"][number])}
                    />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
              {fieldError("inputs")}
            </fieldset>
            <fieldset
              data-field="topics"
              aria-invalid={Boolean(errors.topics)}
              aria-describedby={errors.topics ? "workflow-topics-error" : undefined}
            >
              <legend>Keep updates about</legend>
              <div className="custom-choices">
                {Object.entries(workflowTopics).map(([key, label]) => (
                  <label key={key}>
                    <input
                      type="checkbox"
                      checked={input.topics.includes(key as WorkflowInput["topics"][number])}
                      onChange={() => toggle("topics", key as WorkflowInput["topics"][number])}
                    />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
              {fieldError("topics")}
            </fieldset>
          </section>
          <section className="custom-form-section" aria-labelledby="workflow-rule-heading">
            <h3 id="workflow-rule-heading">When to check</h3>
            <label htmlFor="workflow-trigger">Trigger</label>
            <select
              id="workflow-trigger"
              value={input.trigger}
              onChange={(e) => update("trigger", e.target.value as WorkflowInput["trigger"])}
            >
              <option value="event">A matching source update</option>
              <option value="daily">At a daily time</option>
              <option value="interval">At a regular interval</option>
            </select>
            <p className="field-help">
              {input.trigger === "event"
                ? "Check when a new source update matches one of your selected topics."
                : input.trigger === "daily"
                  ? "Choose a time for your daily brief."
                  : "Check for matching updates throughout the day."}
            </p>
            {input.trigger === "daily" ? (
              <>
                <div className="custom-field-pair">
                  <div>
                    <label htmlFor="workflow-time">Daily time</label>
                    <input
                      id="workflow-time"
                      data-field="time"
                      type="time"
                      value={input.time}
                      onChange={(e) => update("time", e.target.value)}
                      aria-invalid={Boolean(errors.time)}
                      aria-describedby={errors.time ? "workflow-time-error" : undefined}
                    />
                    {fieldError("time")}
                  </div>
                  <ZoneSelect input={input} onChange={(zone) => update("timezone", zone)} />
                </div>
                <label className="custom-check-row">
                  <input
                    type="checkbox"
                    checked={input.weekdaysOnly}
                    onChange={(e) => update("weekdaysOnly", e.target.checked)}
                  />
                  <span>
                    Monday to Friday only <small>Public holidays are not filtered here.</small>
                  </span>
                </label>
              </>
            ) : input.trigger === "interval" ? (
              <div className="custom-field-pair">
                <div>
                  <label htmlFor="workflow-interval">Interval in minutes</label>
                  <input
                    id="workflow-interval"
                    data-field="intervalMinutes"
                    type="number"
                    min={30}
                    max={1440}
                    step={1}
                    value={input.intervalMinutes || ""}
                    onChange={(e) =>
                      update("intervalMinutes", e.target.value === "" ? 0 : Number(e.target.value))
                    }
                    aria-invalid={Boolean(errors.intervalMinutes)}
                    aria-describedby={
                      errors.intervalMinutes
                        ? "workflow-intervalMinutes-error"
                        : "workflow-interval-help"
                    }
                  />
                  <small id="workflow-interval-help">30–1,440 minutes</small>
                  {fieldError("intervalMinutes")}
                </div>
                <ZoneSelect input={input} onChange={(zone) => update("timezone", zone)} />
              </div>
            ) : null}
          </section>
          <section className="custom-form-section" aria-labelledby="workflow-output-heading">
            <h3 id="workflow-output-heading">Outputs</h3>
            <p>Choose where you would like your brief delivered.</p>
            <fieldset
              data-field="outputs"
              aria-invalid={Boolean(errors.outputs)}
              aria-describedby={
                errors.outputs ? "workflow-outputs-error" : "workflow-output-support"
              }
            >
              <legend>Delivery channels</legend>
              <div className="custom-choices">
                {Object.entries(workflowOutputs).map(([key, label]) => (
                  <label key={key}>
                    <input
                      type="checkbox"
                      checked={input.outputs.includes(key as WorkflowInput["outputs"][number])}
                      onChange={() => toggle("outputs", key as WorkflowInput["outputs"][number])}
                    />
                    <span>
                      {label}
                      <small>{key === "discord" ? "Not connected" : "Planned output"}</small>
                    </span>
                  </label>
                ))}
              </div>
              {fieldError("outputs")}
            </fieldset>
            <p id="workflow-output-support" className="field-help">
              Delivery is not connected. Additional channels are planned.
            </p>
            <details className="custom-brief-options">
              <summary>Brief format & language</summary>
              <div className="custom-field-pair">
                <div>
                  <label htmlFor="workflow-summary">Brief format</label>
                  <select
                    id="workflow-summary"
                    value={input.summary}
                    onChange={(e) => update("summary", e.target.value as WorkflowInput["summary"])}
                  >
                    <option value="concise">Concise summary</option>
                    <option value="detailed">Detailed summary</option>
                    <option value="original">Original source update</option>
                  </select>
                </div>
                <div>
                  <label htmlFor="workflow-language">Summary language</label>
                  <select
                    id="workflow-language"
                    value={input.language}
                    disabled={input.summary === "original"}
                    onChange={(e) =>
                      update("language", e.target.value as WorkflowInput["language"])
                    }
                  >
                    <option value="id">Bahasa Indonesia</option>
                    <option value="en">English</option>
                  </select>
                </div>
              </div>
            </details>
            <p className="custom-attribution">
              <Check size={16} aria-hidden="true" /> Source links always included.{" "}
              {input.summary === "original"
                ? "Original updates keep their source language."
                : "Summaries stay grounded in the source."}
            </p>
          </section>
          {saveError ? (
            <p className="custom-error" role="alert">
              {saveError}
            </p>
          ) : null}
          {discard ? (
            <div className="custom-removal" role="group" aria-label="Unsaved workflow changes">
              <p>Discard your unsaved changes? Your saved workflow will stay unchanged.</p>
              <div className="custom-row-actions">
                <button
                  ref={keepEditing}
                  type="button"
                  className="button secondary"
                  onClick={() => {
                    setDiscard(false);
                    requestAnimationFrame(() => discardTrigger.current?.focus());
                  }}
                >
                  Keep editing
                </button>
                <button
                  type="button"
                  className="button secondary custom-danger"
                  onClick={() => {
                    forgetDraft(editor.draftId);
                    onClose();
                  }}
                >
                  Discard changes
                </button>
              </div>
            </div>
          ) : null}
          <div className="custom-save-bar">
            <button type="submit" className="button primary">
              Save workflow
            </button>
            <button
              type="button"
              className="button secondary"
              onClick={(event) => requestClose(event.currentTarget)}
            >
              Cancel
            </button>
          </div>
        </form>
        <aside className="custom-workflow-preview" aria-labelledby="workflow-preview-title">
          <h3 id="workflow-preview-title">Your workflow</h3>
          <ol>
            <li>
              <small>Read from</small>
              <strong>
                {input.inputs.length
                  ? input.inputs.map((v) => workflowInputs[v]).join(" · ")
                  : "Choose an input"}
              </strong>
              <p>
                {input.topics.length
                  ? input.topics.map((v) => workflowTopics[v]).join(", ")
                  : "Choose a topic"}
              </p>
            </li>
            <li>
              <ArrowDown size={18} aria-hidden="true" />
              <small>Check</small>
              <strong>{workflowTiming(input)}</strong>
              <p>
                {input.summary === "original"
                  ? "Keep the original source update"
                  : `${input.summary === "concise" ? "Concise" : "Detailed"} summary in ${input.language === "id" ? "Bahasa Indonesia" : "English"}`}
              </p>
            </li>
            <li>
              <ArrowDown size={18} aria-hidden="true" />
              <small>Send to</small>
              <strong>
                {input.outputs.length
                  ? input.outputs.map((v) => workflowOutputs[v]).join(" · ")
                  : "Choose an output"}
              </strong>
              <p>Source links included</p>
            </li>
          </ol>
          <p className="custom-preview-boundary">
            Configuration preview. Not scheduled or connected.
          </p>
          <Link className="text-link" href="/app/settings">
            Review channel preferences <ArrowRight size={15} aria-hidden="true" />
          </Link>
        </aside>
      </div>
    </>
  );
}

function ZoneSelect({
  input,
  onChange,
}: {
  input: WorkflowInput;
  onChange: (zone: WorkflowInput["timezone"]) => void;
}) {
  return (
    <div>
      <label htmlFor="workflow-timezone">Time zone</label>
      <select
        id="workflow-timezone"
        value={input.timezone}
        onChange={(e) => onChange(e.target.value as WorkflowInput["timezone"])}
      >
        {Object.entries(workflowZones).map(([key, label]) => (
          <option key={key} value={key}>
            {label}
          </option>
        ))}
      </select>
    </div>
  );
}
