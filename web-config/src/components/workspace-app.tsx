"use client";

import { createClient, type Session, type SupabaseClient } from "@supabase/supabase-js";
import { AlertTriangle, ArrowLeft, ArrowRight, Check, Copy, Eye, EyeOff, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import type { WebAuthSettings } from "@/lib/web-environment";
import { controlBrowser, WorkspaceError } from "@/lib/control-browser";
import {
  setDraftOwner,
  clearWorkspaceDrafts,
  discardWorkspaceDraft,
  hasWorkspaceDrafts,
  getDraftOwner,
} from "@/lib/workspace-drafts";
import type { ControlConfigSnapshot, ControlEvent } from "@/server/control-plane";
import type { WorkspaceRecords } from "@/lib/workspace-loader";
import { BrandMark } from "@/components/brand";
import { ToastProvider, useToast } from "@/components/toast-provider";
import { ControlDashboard } from "@/components/control-dashboard";
import { SearchableRunHistory, SearchableWorkflowList } from "@/components/workspace-list-filters";
import { WatcherConfigEditor } from "@/components/watcher-config-editor";
import { WorkspaceNavigation, type WorkspaceView } from "@/components/workspace-navigation";
import { SourceCatalogView } from "@/components/source-catalog";
import { ConnectedWorkflowSummary } from "@/components/connected-workflow-summary";
import { WorkspaceLoading } from "@/components/workspace-loading";
import { XDeliveryStatus } from "@/components/x-delivery-status";
import { SourceProfiles } from "@/components/source-profiles";
import { OperatorJobs } from "@/components/operator-jobs";
import { PublishedWorkspace } from "@/components/published-workspace";
import { xWatcherId } from "@/lib/x-delivery-status";
import { loadWorkspaceRecords, type WorkspaceProgress } from "@/lib/workspace-loader";
import "@/app/workspace.css";

type View = WorkspaceView;
const browserClients = new Map<string, SupabaseClient>();
function authClient(settings: WebAuthSettings) {
  const key = `${settings.supabaseUrl}:${settings.publishableKey}`;
  const existing = typeof window === "undefined" ? undefined : browserClients.get(key);
  if (existing) return existing;
  const client = createClient(settings.supabaseUrl, settings.publishableKey, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
  });
  // Share refresh coordination across route mounts, never across server users.
  if (typeof window !== "undefined") browserClients.set(key, client);
  return client;
}
type Records = WorkspaceRecords;

export function WorkspaceApp(props: { settings: WebAuthSettings | null; view: View }) {
  return (
    <ToastProvider>
      <WorkspaceSession {...props} />
    </ToastProvider>
  );
}

function WorkspaceSession({ settings, view }: { settings: WebAuthSettings | null; view: View }) {
  const [client] = useState(() => (settings ? authClient(settings) : null));
  const [session, setSession] = useState<Session | null | undefined>(undefined);
  const [signingOut, setSigningOut] = useState(false);
  const [sessionError, setSessionError] = useState("");
  useEffect(() => {
    if (!client) return;
    let active = true;
    let receivedAuthEvent = false;
    const restoreDeadline = window.setTimeout(() => {
      if (active && !receivedAuthEvent) {
        receivedAuthEvent = true;
        setDraftOwner(null);
        setSession(null);
        setSessionError("Restoring your session took too long. Please sign in again.");
      }
    }, 12000);
    const {
      data: { subscription },
    } = client.auth.onAuthStateChange((_event, value) => {
      receivedAuthEvent = true;
      window.clearTimeout(restoreDeadline);
      if (active) {
        setDraftOwner(value?.user.id ?? null);
        setSession(value);
        if (value) setSessionError("");
      }
    });
    void client.auth
      .getSession()
      .then(({ data, error }) => {
        window.clearTimeout(restoreDeadline);
        if (active && !receivedAuthEvent) {
          setDraftOwner(data.session?.user.id ?? null);
          setSession(data.session);
          if (error) setSessionError("Your session could not be restored. Please sign in again.");
        }
      })
      .catch(() => {
        window.clearTimeout(restoreDeadline);
        if (active && !receivedAuthEvent) {
          setDraftOwner(null);
          setSession(null);
        }
      });
    return () => {
      active = false;
      window.clearTimeout(restoreDeadline);
      subscription.unsubscribe();
    };
  }, [client]);
  const signOut = async () => {
    if (!client) return;
    setSigningOut(true);
    try {
      const { error } = await client.auth.signOut({ scope: "local" });
      if (error) setSessionError("Could not sign out. Check your connection and try again.");
      else {
        clearWorkspaceDrafts();
        setDraftOwner(null);
        setSession(null);
        setSessionError("");
      }
    } catch {
      setSessionError("Could not sign out. Check your connection and try again.");
    } finally {
      setSigningOut(false);
    }
  };
  if (!settings || !client)
    return (
      <SignInShell>
        <h1>Sign-in is being set up.</h1>
        <p>This workspace will be available when its owner finishes connecting sign-in.</p>
        <Link className="button secondary" href="/app/insights">
          Explore the sample workspace <ArrowRight size={17} />
        </Link>
      </SignInShell>
    );
  if (session === undefined)
    return (
      <SignInShell>
        <WorkspaceLoading title="Opening your workspace…" compact />
      </SignInShell>
    );
  if (!session) return <SignInForm client={client} notice={sessionError} />;
  return (
    <SignedInWorkspace
      key={session.user.id}
      client={client}
      session={session}
      view={view}
      onSignOut={signOut}
      signingOut={signingOut}
      sessionError={sessionError}
    />
  );
}

function SignInShell({ children }: { children: React.ReactNode }) {
  return (
    <main className="workspace-auth">
      <Link href="/" className="workspace-brand">
        <BrandMark />
        <span>Bursawatch</span>
      </Link>
      <div className="workspace-auth-content">{children}</div>
      <p className="workspace-auth-footer">Watch the sources. Keep the judgment.</p>
    </main>
  );
}

function SignInForm({ client, notice }: { client: SupabaseClient; notice: string }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(notice);
  return (
    <SignInShell>
      <h1>
        Your research,
        <br />
        in one place.
      </h1>
      <p>Sign in to follow your workflows, review what changed and keep your brief on schedule.</p>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          setError("");
          try {
            const { error: signInError } = await client.auth.signInWithPassword({
              email: email.trim(),
              password,
            });
            if (signInError)
              setError(
                signInError.status === 429
                  ? "Too many attempts. Wait a moment, then try again."
                  : "We couldn’t sign you in. Check your email and password, or ask the workspace owner for access.",
              );
            else setPassword("");
          } catch {
            setError("Could not reach sign-in. Check your connection and try again.");
          } finally {
            setBusy(false);
          }
        }}
      >
        <label htmlFor="workspace-email">Email</label>
        <input
          id="workspace-email"
          type="email"
          autoComplete="username"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
          disabled={busy}
        />
        <label htmlFor="workspace-password">Password</label>
        <div className="workspace-password">
          <input
            id="workspace-password"
            type={visible ? "text" : "password"}
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            disabled={busy}
          />
          <button
            type="button"
            aria-label={visible ? "Hide password" : "Show password"}
            onClick={() => setVisible(!visible)}
          >
            {visible ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        </div>
        {error ? (
          <p className="workspace-error" role="alert">
            {error}
          </p>
        ) : null}
        <button className="button primary" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
          <ArrowRight size={17} />
        </button>
      </form>
      <p className="workspace-access-note">Access is provided by your workspace owner.</p>
      <Link className="workspace-sample-link" href="/app/insights">
        Explore the sample workspace <ArrowRight size={15} />
      </Link>
    </SignInShell>
  );
}

function SignedInWorkspace({
  client,
  session,
  view,
  onSignOut,
  signingOut,
  sessionError,
}: {
  client: SupabaseClient;
  session: Session;
  view: View;
  onSignOut: () => Promise<void>;
  signingOut: boolean;
  sessionError: string;
}) {
  const [request] = useState(() => controlBrowser(client));
  const [loadedRecords, setRecords] = useState<Records | null>(null);
  const [recordScope, setRecordScope] = useState("");
  const [progress, setProgress] = useState<WorkspaceProgress | null>(null);
  const readController = useRef<AbortController | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [authRequired, setAuthRequired] = useState(false);
  const generation = useRef(0);
  const dirty = useRef(false);
  const onDirtyChange = useCallback((value: boolean) => {
    dirty.current = value;
  }, []);
  const guardedSignOut = () => {
    if (
      (!dirty.current && !hasWorkspaceDrafts()) ||
      window.confirm("Discard unsaved changes and sign out?")
    )
      void onSignOut();
  };
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const watcherId = params.get("watcher");
  const runId = params.get("run");
  const legacySourceLibrary = view === "workflows" && params.get("tab") === "sources" && !watcherId;
  const scope = `${view}:${view === "workflows" ? (watcherId ?? "") : ""}`;
  const records = recordScope === scope ? loadedRecords : null;
  const heading = useRef<HTMLElement>(null);
  const refresh = useCallback(async () => {
    const current = ++generation.current;
    readController.current?.abort();
    const controller = new AbortController();
    readController.current = controller;
    if (view === "settings" || view === "published") {
      setRefreshing(false);
      setError("");
      return;
    }
    setRefreshing(true);
    setProgress(null);
    setError("");
    setAuthRequired(false);
    try {
      const result = await loadWorkspaceRecords(request, {
        view,
        watcherId,
        runId,
        signal: controller.signal,
        onProgress: (value) => {
          if (current === generation.current) setProgress(value);
        },
        onCatalog: (watchers) => {
          if (current !== generation.current || view !== "workflows") return;
          setRecords({
            watchers,
            jobs: [],
            runs: [],
            components: [],
            componentActivity: [],
            operatorJobs: [],
            observations: [],
            operatorIssues: [],
            issues: [],
            updatedAt: new Date().toISOString(),
          });
          setRecordScope(scope);
        },
      });
      // Keep only this mounted session's existing metadata for a selected run.
      // Direct links do not fetch every watcher history to reconstruct it.
      if (current === generation.current && !(view === "history" && runId)) {
        setRecords(result);
        setRecordScope(scope);
      }
    } catch (failure) {
      if (controller.signal.aborted) return;
      if (current === generation.current) {
        setAuthRequired(failure instanceof WorkspaceError && failure.code === "auth");
        if (failure instanceof WorkspaceError && ["auth", "forbidden"].includes(failure.code)) {
          setRecords(null);
          setRecordScope("");
        }
      }
      if (current === generation.current)
        setError(
          failure instanceof Error ? failure.message : "Could not load the workspace. Try again.",
        );
    } finally {
      if (current === generation.current) setRefreshing(false);
    }
  }, [request, view, watcherId, runId, scope]);
  const onTimelineAccessFailure = useCallback((failure: WorkspaceError) => {
    readController.current?.abort();
    generation.current++;
    setRecords(null);
    setRecordScope("");
    setRefreshing(false);
    setAuthRequired(failure.code === "auth");
    setError(
      failure.code === "auth"
        ? "Your session has expired. Sign in again."
        : "Your account does not have access to this timeline.",
    );
  }, []);
  useEffect(() => {
    const lifecycle = generation;
    // This effect starts an external API read; subsequent renders use its result.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
    return () => {
      lifecycle.current++;
      readController.current?.abort();
    };
  }, [refresh]);
  useEffect(() => {
    heading.current?.focus();
  }, [pathname, watcherId, runId]);
  useEffect(() => {
    if (legacySourceLibrary) router.replace("/workspace/sources");
  }, [legacySourceLibrary, router]);
  const selectWatcher = (id: string) =>
    router.push(`/workspace/workflows?watcher=${encodeURIComponent(id)}`);
  const selectRun = (id: string) => router.push(`/workspace/history?run=${encodeURIComponent(id)}`);
  return (
    <div className="control-workspace has-connected-navigation">
      <a className="skip-link" href="#workspace-main">
        Skip to main content
      </a>
      <WorkspaceNavigation view={view} onSignOut={guardedSignOut} signingOut={signingOut} />
      <main id="workspace-main" ref={heading} tabIndex={-1} className="control-main">
        {sessionError ? (
          <p role="alert" className="workspace-error">
            {sessionError}
          </p>
        ) : null}
        {error ? (
          <div className="control-alert" role="alert">
            <p>
              {error} {records ? "The information below is from your last successful refresh." : ""}
            </p>
            <button
              className="button secondary small"
              onClick={authRequired ? guardedSignOut : () => void refresh()}
              disabled={refreshing}
            >
              {authRequired ? "Sign in again" : "Try again"}
            </button>
          </div>
        ) : null}
        {view !== "settings" &&
        view !== "sources" &&
        view !== "published" &&
        !(view === "history" && runId) &&
        !error &&
        (!records || refreshing) ? (
          <WorkspaceLoading key={scope} progress={progress} compact={Boolean(records)} />
        ) : null}
        {records &&
        records.issues.length > 0 &&
        view !== "overview" &&
        !(view === "history" && runId) ? (
          <div className="control-alert" role="status">
            <p>Some schedules or run records could not be loaded. This view may be incomplete.</p>
            <details>
              <summary>What could not be loaded?</summary>
              <ul>
                {records.issues.map((issue) => (
                  <li key={`${issue.watcherId}:${issue.resource}`}>
                    {records.watchers.find((item) => item.watcher_id === issue.watcherId)
                      ?.display_name ?? "Workflow"}
                    : {issue.message}
                  </li>
                ))}
              </ul>
            </details>
            <button
              className="button secondary small"
              disabled={refreshing}
              onClick={() => {
                if (
                  !dirty.current ||
                  window.confirm("Discard unsaved changes and refresh the workspace?")
                ) {
                  dirty.current = false;
                  window.location.reload();
                }
              }}
            >
              Reload workspace
            </button>
          </div>
        ) : null}
        {records && records.operatorIssues.length > 0 && view !== "overview" ? (
          <div className="control-alert" role="status">
            <p>
              Operator evidence is incomplete. A missing row means unavailable data, not an empty
              result.
            </p>
            <ul>
              {records.operatorIssues.map((issue, index) => (
                <li key={`${issue.resource}:${issue.componentId ?? "inventory"}:${index}`}>
                  {issue.message}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {records && view === "overview" ? (
          <ControlDashboard
            {...records}
            refreshing={refreshing}
            onRefresh={() => void refresh()}
            onSelectWatcher={selectWatcher}
            onSelectRun={selectRun}
          />
        ) : null}
        {view === "sources" ? (
          <>
            <WorkspaceHeading
              title="Sources"
              description="Review supported sources and their saved catalog settings."
            />
            <SourceCatalogView
              request={request}
              onDirtyChange={onDirtyChange}
              components={records?.components ?? []}
              activity={records?.componentActivity ?? []}
              activityUnavailable={
                records?.operatorIssues.some(
                  (issue) =>
                    issue.resource === "components" || issue.resource === "component-activity",
                ) ?? false
              }
            />
          </>
        ) : null}
        {records && view === "workflows" ? (
          watcherId ? (
            <WatcherDetail
              key={watcherId}
              watcherId={watcherId}
              records={records}
              request={request}
              onDirtyChange={onDirtyChange}
              loadingStatus={refreshing}
            />
          ) : legacySourceLibrary ? null : (
            <>
              <WorkspaceHeading
                title="Workflows"
                description="Choose your inputs, shape the brief and set where it goes."
              />
              <SearchableWorkflowList
                {...records}
                components={records.components}
                operatorJobs={records.operatorJobs}
                observations={records.observations}
                onSelectWatcher={selectWatcher}
                statusLoaded={false}
              />
            </>
          )
        ) : null}
        {view === "history" && runId && !error ? (
          <RunDetail
            key={runId}
            runId={runId}
            records={loadedRecords}
            request={request}
            onAccessFailure={onTimelineAccessFailure}
          />
        ) : records && view === "history" && !runId ? (
          <>
            <WorkspaceHeading
              title="Run history"
              description="Up to 50 recent checks per workflow. A completed check may have nothing new to deliver."
            />
            <p className="control-data-note">
              Source-adapter run telemetry is unavailable here. This page shows bounded workflow run
              records, not a count of source polls or deliveries.
            </p>
            <SearchableRunHistory
              runs={records.runs}
              watchers={records.watchers}
              onSelectRun={selectRun}
            />
          </>
        ) : null}
        {records && view === "jobs" ? (
          <OperatorJobs
            jobs={records.operatorJobs}
            components={records.components}
            observations={records.observations}
            request={request}
            onDirtyChange={onDirtyChange}
            unavailable={records.operatorIssues.some((issue) => issue.resource === "operator-jobs")}
          />
        ) : null}
        {view === "published" ? (
          <PublishedWorkspace request={request} onSignIn={guardedSignOut} />
        ) : null}
        {view === "settings" ? (
          <>
            <WorkspaceHeading
              title="Account"
              description="Your access to this shared research workspace."
            />
            <section className="control-account">
              <h2>Signed in</h2>
              <p>{session.user.email ?? "Workspace member"}</p>
              <p className="control-muted">
                Your workspace owner manages configuration permissions.
              </p>
              <div className="control-account-id">
                <span>Account ID</span>
                <code>{session.user.id}</code>
                <button
                  className="button secondary small"
                  onClick={() =>
                    void navigator.clipboard
                      .writeText(session.user.id)
                      .then(() => toast("Account ID copied."))
                      .catch(() => toast("Copy unavailable. Select your account ID to copy it."))
                  }
                >
                  <Copy size={16} />
                  Copy
                </button>
              </div>
              <details>
                <summary>About workspace access</summary>
                <p>
                  Members can view shared workflows and run history. Administrators can also change
                  source configuration and supported schedules. Share your account ID with the owner
                  if you need editing access.
                </p>
              </details>
              <button className="button secondary" onClick={guardedSignOut} disabled={signingOut}>
                Sign out
              </button>
            </section>
          </>
        ) : null}
      </main>
      <footer className="control-footer">
        <span>Asia/Jakarta · Shared workspace</span>
        <span>Information and analysis. No automated trading.</span>
      </footer>
    </div>
  );
}

function WorkspaceHeading({ title, description }: { title: string; description: string }) {
  return (
    <div className="control-page-heading">
      <h1>{title}</h1>
      <p>{description}</p>
    </div>
  );
}
type Requester = ReturnType<typeof controlBrowser>;

function WatcherDetail({
  watcherId,
  records,
  request,
  onDirtyChange,
  loadingStatus,
}: {
  watcherId: string;
  records: Records;
  request: Requester;
  onDirtyChange: (dirty: boolean) => void;
  loadingStatus: boolean;
}) {
  const watcher = records.watchers.find((item) => item.watcher_id === watcherId);
  const hasWatcher = Boolean(watcher);
  const configReadController = useRef<AbortController | null>(null);
  const [snapshot, setSnapshot] = useState<ControlConfigSnapshot | null>(null);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const dirty = useRef(false);
  const configDirty = useRef(false);
  const photoDirty = useRef(false);
  const updateDirty = useCallback(
    (value: boolean) => {
      configDirty.current = value;
      dirty.current = value || photoDirty.current;
      onDirtyChange(dirty.current);
    },
    [onDirtyChange],
  );
  const updatePhotoDirty = useCallback(
    (value: boolean) => {
      photoDirty.current = value;
      dirty.current = value || configDirty.current;
      onDirtyChange(dirty.current);
    },
    [onDirtyChange],
  );
  const load = useCallback(
    async (discard = false) => {
      configReadController.current?.abort();
      const controller = new AbortController();
      configReadController.current = controller;
      const owner = getDraftOwner();
      setStatus("loading");
      setError("");
      try {
        const result = await request<ControlConfigSnapshot>(
          `watchers/${encodeURIComponent(watcherId)}/config`,
          undefined,
          { signal: controller.signal },
        );
        if (discard) discardWorkspaceDraft(`config:${watcherId}`, owner);
        setSnapshot(result);
        setStatus("ready");
      } catch (failure) {
        if (controller.signal.aborted) return;
        setStatus(
          failure instanceof WorkspaceError && failure.code === "forbidden" ? "viewer" : "error",
        );
        setError(failure instanceof Error ? failure.message : "Could not load configuration.");
      }
    },
    [request, watcherId],
  );
  useEffect(() => {
    // Load the selected remote resource, independently of the editor's draft.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (hasWatcher) void load();
    return () => configReadController.current?.abort();
  }, [load, hasWatcher]);
  if (!watcher)
    return (
      <div className="control-empty">
        <h1>Workflow not found</h1>
        <Link href="/workspace/workflows">Back to workflows</Link>
      </div>
    );
  return (
    <>
      <Link className="control-back" href="/workspace/workflows">
        <ArrowLeft size={17} />
        Workflows
      </Link>
      <WorkspaceHeading
        title={watcher.display_name}
        description={`Configuration revision ${snapshot?.revision ?? watcher.current_revision ?? "not available"}`}
      />
      <ConnectedWorkflowSummary
        watcherId={watcherId}
        jobs={records.operatorJobs}
        observations={records.observations}
        jobsUnavailable={records.operatorIssues.some(
          (issue) => issue.componentId === watcherId && issue.resource === "operator-jobs",
        )}
        observationsUnavailable={records.operatorIssues.some(
          (issue) => issue.componentId === watcherId && issue.resource === "observations",
        )}
      />
      {status === "loading" ? <WorkspaceLoading title="Loading configuration…" compact /> : null}
      {status === "viewer" ? (
        <div className="control-access">
          <Eye size={20} />
          <div>
            <h2>View access</h2>
            <p>
              You can review this workflow’s runs and related jobs. Configuration editing is
              available to workspace administrators.
            </p>
            <Link className="button secondary small" href="/workspace/settings">
              View your account
            </Link>
          </div>
        </div>
      ) : null}
      {status === "error" ? (
        <div className="control-alert" role="alert">
          <p>{error}</p>
          <button className="button secondary" onClick={() => void load()}>
            Try again
          </button>
        </div>
      ) : null}
      {status === "ready" && snapshot ? (
        <>
          {watcherId === "bursawatch-x-account-watch" ? (
            <XDeliveryStatus
              snapshot={snapshot}
              jobs={records.jobs}
              runs={records.runs}
              loading={loadingStatus}
              unavailable={records.issues.some((issue) => issue.watcherId === watcherId)}
            />
          ) : null}
          <WatcherConfigEditor
            key={snapshot.watcher_id}
            snapshot={snapshot}
            onDirtyChange={updateDirty}
            onSave={async (config) => {
              const result = await request<ControlConfigSnapshot>(
                `watchers/${encodeURIComponent(watcherId)}/config`,
                {
                  expectedRevision: snapshot.revision,
                  config_version: snapshot.config_version,
                  config,
                },
              );
              setSnapshot(result);
              return result;
            }}
          />
        </>
      ) : null}
      <SourceProfiles
        key={watcherId}
        watcherId={watcherId}
        request={request}
        canEdit={status === "ready"}
        onDirtyChange={updatePhotoDirty}
      />
      <div className="control-detail-actions">
        <button
          className="button ghost"
          onClick={() => {
            if (
              !configDirty.current ||
              window.confirm("Discard unsaved changes and reload the latest configuration?")
            )
              void load(true);
          }}
        >
          Reload configuration
        </button>
      </div>
    </>
  );
}

function EventDiagnostics({ event }: { event: ControlEvent }) {
  const data = event.diagnostics;
  if (!data) return null;
  const rows = [
    ["Source ID", data.profile_id],
    ["Items fetched", data.items],
    ["Items queued", data.queued],
    ["Delivery count (run total)", data.delivered],
    ["Analysis queue (run total)", data.pending],
    ["Oldest eligible queue item (minutes)", data.oldest_pending_minutes],
    [
      "Queue-only execution",
      typeof data.queue_only === "boolean" ? (data.queue_only ? "Yes" : "No") : undefined,
    ],
    [
      "Dry run",
      typeof data.dry_run === "boolean"
        ? data.dry_run
          ? "Yes — no live delivery"
          : "No"
        : undefined,
    ],
  ] as const;
  return (
    <dl className="control-event-details" aria-label="Recorded diagnostics">
      {rows
        .filter(([, value]) => value !== undefined)
        .map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
    </dl>
  );
}

function RunDetail({
  runId,
  records,
  request,
  onAccessFailure,
}: {
  runId: string;
  records: Records | null;
  request: Requester;
  onAccessFailure: (failure: WorkspaceError) => void;
}) {
  const [events, setEvents] = useState<ControlEvent[] | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const run = records?.runs.find((item) => item.run_id === runId);
  useEffect(() => {
    const controller = new AbortController();
    void request<ControlEvent[]>(`runs/${encodeURIComponent(runId)}/events`, undefined, {
      signal: controller.signal,
    })
      .then((result) => {
        if (!controller.signal.aborted) setEvents(result);
      })
      .catch((failure) => {
        if (controller.signal.aborted) return;
        if (failure instanceof WorkspaceError && ["auth", "forbidden"].includes(failure.code)) {
          onAccessFailure(failure);
          return;
        }
        setError(failure instanceof Error ? failure.message : "Could not load this timeline.");
      });
    return () => controller.abort();
  }, [request, runId, attempt, onAccessFailure]);
  return (
    <>
      <Link className="control-back" href="/workspace/history">
        <ArrowLeft size={17} />
        Run history
      </Link>
      <WorkspaceHeading
        title="Run timeline"
        description={
          run
            ? `${records?.watchers.find((watcher) => watcher.watcher_id === run.watcher_id)?.display_name ?? run.watcher_id} · Configuration revision ${run.config_revision}`
            : "Recorded events for this run."
        }
      />
      {run ? (
        <div className="control-run-meta">
          <span>{run.status === "ok" ? "Completed" : run.status}</span>
          <span>{run.trigger}</span>
          <time dateTime={run.started_at}>
            {new Date(run.started_at).toLocaleString("en-GB", { timeZone: "Asia/Jakarta" })} WIB
          </time>
        </div>
      ) : null}
      {run?.watcher_id === xWatcherId && run.trigger === "queue" ? (
        <div className="control-alert" role="note" aria-label="Queue check, not a source poll">
          <p>
            This run checked queued posts. It did not fetch X. A completed queue check does not
            confirm that your account was fetched or that Discord received a message.
          </p>
          <Link className="button secondary" href={`/workspace/workflows?watcher=${xWatcherId}`}>
            Check X source polling
          </Link>
        </div>
      ) : null}
      {error ? (
        <div role="alert" className="control-alert">
          <p>{error}</p>
          <button
            className="button secondary"
            onClick={() => {
              setError("");
              setAttempt((value) => value + 1);
            }}
          >
            Try again
          </button>
        </div>
      ) : !events ? (
        <WorkspaceLoading title="Loading timeline…" compact />
      ) : events.length ? (
        <ol className="control-timeline">
          {events.map((event) => (
            <li key={event.event_id}>
              <span className="control-timeline-dot" aria-hidden="true">
                {event.level === "error" || event.level === "fatal" ? (
                  <X size={14} />
                ) : event.level === "warning" ? (
                  <AlertTriangle size={14} />
                ) : (
                  <Check size={14} />
                )}
              </span>
              <div>
                <h2>{event.event_type.replaceAll(/[._-]/g, " ")}</h2>
                <p>
                  {event.phase.replaceAll(/[_-]/g, " ")} · {event.level}
                </p>
                <EventDiagnostics event={event} />
                {event.event_type === "source.fetch.failed" ? (
                  <p>
                    The source request failed. Ask the workspace owner to check the source
                    connection and rate-limit status. This timeline does not expose provider
                    credentials or raw error text.
                  </p>
                ) : null}
                {event.event_type === "source.fetch.completed" ? (
                  <p>
                    {event.diagnostics?.items === 0
                      ? "This fetch returned no items. There was nothing from this fetch to queue. Ask the workspace owner to check this source connection; this event does not explain why it was empty."
                      : event.diagnostics?.items !== undefined &&
                          event.diagnostics.items > 0 &&
                          event.diagnostics.queued === 0
                        ? "Items were fetched, but none were queued. This can happen during first-poll initialization or when no new eligible posts are found. This event does not establish which reason applies."
                        : event.diagnostics?.queued !== undefined && event.diagnostics.queued > 0
                          ? "New items were queued for processing. This event does not confirm delivery to Discord."
                          : "Source fetch recorded. This event does not confirm delivery. Any fetched or queued counts not shown are unavailable, not zero."}
                  </p>
                ) : null}
                {event.event_type === "delivery.drain.completed" ? (
                  <p>
                    Queue processing finished; there may have been nothing to send. This event is
                    not a delivery receipt for an individual post or Discord channel. Counts cover
                    the whole run and may include simulated delivery in a dry run.
                  </p>
                ) : null}
              </div>
              <time dateTime={event.occurred_at}>
                {new Date(event.occurred_at).toLocaleTimeString("en-GB", {
                  timeZone: "Asia/Jakarta",
                })}{" "}
                WIB
              </time>
            </li>
          ))}
        </ol>
      ) : (
        <div className="control-empty">No events have been recorded for this run yet.</div>
      )}
    </>
  );
}
