import "server-only";

import { isIP } from "node:net";
import { z } from "zod";
import {
  catalogConfig,
  catalogRevision,
  catalogWrite,
  effectiveCatalog,
  sourceCatalog,
} from "@/lib/source-catalog";
import {
  component,
  componentActivity,
  componentList,
  observation,
  operatorJob,
  operatorJobList,
} from "@/lib/operator-inventory";
import {
  publicationCoverage,
  publicationDetail,
  publicationFilters,
  publicationPage,
  type PublicationFilters,
} from "@/lib/publications";

// Reviewed against absolutepraya/bursawatch-engine at a343ec4d. The API remains the
// authority for user identity, admin permissions and watcher validation.
const id = z
  .string()
  .regex(/^[a-z0-9][a-z0-9-]*$/)
  .max(128);
const timestamp = z.iso.datetime({ offset: true });
const revision = z.number().int().positive();
const profileId = z.string().regex(/^[a-z0-9][a-z0-9_-]{0,63}$/);
const httpsUrl = z
  .string()
  .min(1)
  .max(2048)
  .refine((value) => {
    if (value !== value.trim() || /[\u0000-\u0020\u007f]/.test(value)) return false;
    try {
      const url = new URL(value);
      const host = url.hostname.toLowerCase().replace(/\.$/, "");
      // Display URLs are never fetched by this server. Still reject literal or
      // local-network destinations before handing them to the browser's image tag.
      const publicHost =
        host.includes(".") &&
        !isIP(host) &&
        !host.includes(":") &&
        !/(?:^|\.)(?:localhost|local|internal|lan|home)$/.test(host);
      return (
        url.protocol === "https:" &&
        publicHost &&
        !url.username &&
        !url.password &&
        !url.hash &&
        !url.port
      );
    } catch {
      return false;
    }
  }, "Use an HTTPS URL without credentials, fragments or custom ports.");
export const avatarInput = z.discriminatedUnion("mode", [
  z.object({ mode: z.literal("auto"), url: z.null().optional() }).strict(),
  z.object({ mode: z.literal("manual"), url: httpsUrl }).strict(),
]);
const profile = z.object({
  watcher_id: id,
  profile_id: profileId,
  handle: z.string().min(1).max(200),
  display_name: z.string().min(1).max(200),
  profile_url: httpsUrl,
  enabled: z.boolean(),
  avatar: z
    .object({
      mode: z.enum(["auto", "manual"]),
      url: httpsUrl.nullable(),
      source: z.string().min(1).max(64).nullable(),
      fetched_at: timestamp.nullable(),
      last_success_at: timestamp.nullable(),
      last_error: z.string().max(500).nullable(),
      updated_at: timestamp,
    })
    .transform(({ last_error, ...metadata }) => ({ ...metadata, has_error: Boolean(last_error) })),
});
export type AvatarInput = z.infer<typeof avatarInput>;
export type ControlProfile = z.infer<typeof profile>;
function canonicalAvatarUrl(value: string): string {
  const url = new URL(value);
  url.hostname = url.hostname.replace(/\.$/, "");
  return url.href;
}
const watcher = z.object({
  watcher_id: id,
  display_name: z.string().min(1).max(200),
  current_revision: revision.nullable(),
  updated_at: timestamp,
});
const schedule = z.object({
  api_version: z.literal(1),
  job_id: id,
  revision,
  enabled: z.boolean(),
  interval_seconds: z.number().int().min(60).max(86400).multipleOf(60),
  timezone: z.literal("Asia/Jakarta"),
  schedule_sha256: z.string().regex(/^[0-9a-f]{64}$/),
  updated_at: timestamp,
});
const job = z
  .object({
    job_id: id,
    watcher_id: id,
    display_name: z.string().min(1).max(200),
    schedule_kind: z.enum(["interval", "fixed"]),
    min_interval_seconds: z.number().int().positive().nullable(),
    max_interval_seconds: z.number().int().positive().nullable(),
    schedule: schedule.nullable(),
    reconciliation: z.object({
      status: z.enum(["not_connected", "pending", "applied", "error"]),
      applied_revision: revision.nullable(),
      effective: z.boolean(),
    }),
  })
  .superRefine((value, ctx) => {
    if (value.schedule && value.schedule.job_id !== value.job_id) {
      ctx.addIssue({ code: "custom", message: "Schedule identity mismatch" });
    }
    const verified = Boolean(
      value.schedule &&
      value.reconciliation.status === "applied" &&
      value.reconciliation.applied_revision === value.schedule.revision,
    );
    if (value.reconciliation.effective !== verified) {
      ctx.addIssue({ code: "custom", message: "Inconsistent reconciliation" });
    }
  });
const run = z.object({
  run_id: z.string().min(1).max(128),
  watcher_id: id,
  scheduler_job_id: id.nullable(),
  trigger: z.string().min(1).max(128),
  config_revision: revision,
  started_at: timestamp,
  finished_at: timestamp.nullable(),
  status: z.enum(["running", "ok", "degraded", "failed", "blocked"]),
});
export type ControlEventDiagnostics = {
  profile_id?: string;
  items?: number;
  queued?: number;
  delivered?: number;
  pending?: number;
  oldest_pending_minutes?: number;
  queue_only?: boolean;
  dry_run?: boolean;
};

// These counters describe an invocation, not proof of a particular post's
// delivery. Never forward arbitrary attributes, messages, reasons or errors.
function eventDiagnostics(
  eventType: string,
  attributes: unknown,
): ControlEventDiagnostics | undefined {
  if (!attributes || typeof attributes !== "object" || Array.isArray(attributes)) return undefined;
  const source = attributes as Record<string, unknown>;
  const result: ControlEventDiagnostics = {};
  function count(key: "items" | "queued" | "delivered" | "pending" | "oldest_pending_minutes") {
    const value = source[key];
    if (typeof value === "number" && Number.isSafeInteger(value) && value >= 0) result[key] = value;
  }
  function flag(key: "queue_only" | "dry_run") {
    if (typeof source[key] === "boolean") result[key] = source[key];
  }
  if (eventType === "source.fetch.completed" || eventType === "source.fetch.failed") {
    const profileId = source.profile_id;
    if (
      typeof profileId === "string" &&
      /^[a-z0-9][a-z0-9_-]{0,63}$/.test(profileId) &&
      !/^(?:sb_|sk[-_]|gh[pousr]_|github_pat_|bearer[-_]|token[-_]|secret[-_]|password[-_]|service_role)/i.test(
        profileId,
      )
    ) {
      result.profile_id = profileId;
    }
    if (eventType === "source.fetch.completed") {
      count("items");
      count("queued");
    }
  } else if (eventType === "delivery.drain.completed") {
    count("delivered");
    count("pending");
    count("oldest_pending_minutes");
    flag("queue_only");
  } else if (eventType === "run.started") {
    flag("dry_run");
    flag("queue_only");
  }
  return Object.keys(result).length ? result : undefined;
}

const event = z
  .object({
    run_id: z.string().min(1).max(128),
    event_id: z.string().min(1).max(128),
    occurred_at: timestamp,
    level: z.enum(["debug", "info", "warning", "error", "fatal"]),
    phase: z.string().min(1).max(64),
    event_type: z.string().min(1).max(128),
    attributes: z.unknown().optional(),
  })
  .transform(({ attributes, ...metadata }) => {
    const diagnostics = eventDiagnostics(metadata.event_type, attributes);
    return { ...metadata, ...(diagnostics ? { diagnostics } : {}) };
  });

const configSnapshot = z.object({
  api_version: z.literal(1),
  watcher_id: id,
  revision,
  config_version: revision,
  config: z.record(z.string(), z.unknown()),
  config_sha256: z.string().regex(/^[0-9a-f]{64}$/),
  updated_at: timestamp,
});
export const scheduleInput = z
  .object({
    enabled: z.boolean(),
    interval_seconds: z.number().int().min(60).max(86400).multipleOf(60),
    timezone: z.literal("Asia/Jakarta"),
  })
  .strict();
export type ScheduleInput = z.infer<typeof scheduleInput>;
export type ControlConfigSnapshot = z.infer<typeof configSnapshot>;

export type ControlWatcher = z.infer<typeof watcher>;
export type ControlJob = z.infer<typeof job>;
export type ControlRun = z.infer<typeof run>;
export type ControlEvent = z.infer<typeof event>;
export type ControlErrorCode =
  | "setup"
  | "auth"
  | "forbidden"
  | "missing"
  | "rate-limit"
  | "unavailable"
  | "invalid-response"
  | "validation"
  | "conflict"
  | "unknown-outcome";

export class ControlPlaneError extends Error {
  constructor(
    public readonly code: ControlErrorCode,
    public readonly fields: string[] = [],
  ) {
    const messages: Record<ControlErrorCode, string> = {
      setup: "The configuration service needs to be set up.",
      auth: "Sign in again to view the workspace.",
      forbidden: "Your account does not have access to this workspace.",
      missing: "This record is no longer available.",
      "rate-limit": "The service is busy. Try again shortly.",
      unavailable: "The configuration service could not be reached.",
      "invalid-response": "The service returned data the workspace could not verify.",
      validation: "Some settings could not be saved. Check the highlighted fields and try again.",
      conflict:
        "These settings changed since you opened them. Reload the latest version before saving.",
      "unknown-outcome":
        "The save could not be confirmed. Reload the current settings before trying again.",
    };
    super(messages[code]);
    this.name = "ControlPlaneError";
  }
}

function serviceOrigin(value: string): string {
  try {
    const url = new URL(value);
    if (
      url.protocol !== "https:" ||
      url.username ||
      url.password ||
      url.pathname !== "/" ||
      url.search ||
      url.hash
    )
      throw new Error();
    return url.origin;
  } catch {
    throw new ControlPlaneError("setup");
  }
}

function watcherPath(value: string): string {
  if (!id.safeParse(value).success) throw new ControlPlaneError("setup");
  return `/v1/watchers/${value}`;
}

/** Construct per request, never as a global singleton. origin must come from
 * server configuration, never a request query. getAccessToken must use the
 * authenticated user's Supabase session, never a machine or admin secret.
 * The API verifies the token; this transport does not grant roles or tenancy.
 */
export function createControlPlaneReader(options: {
  origin: string;
  getAccessToken: () => Promise<string | null>;
  fetchImpl?: typeof fetch;
}) {
  const origin = serviceOrigin(options.origin);
  const fetchImpl = options.fetchImpl ?? fetch;

  async function request<T>(
    path: string,
    schema: z.ZodType<T>,
    body?: unknown,
    method: "GET" | "PUT" | "POST" = body === undefined ? "GET" : "PUT",
  ): Promise<T> {
    const writing = method !== "GET";
    let token: string | null;
    try {
      token = await options.getAccessToken();
    } catch {
      throw new ControlPlaneError("auth");
    }
    if (!token || token.length > 16384 || /\s/.test(token)) throw new ControlPlaneError("auth");
    let response: Response;
    try {
      response = await fetchImpl(`${origin}${path}`, {
        method,
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/json",
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: "no-store",
        redirect: "error",
        credentials: "omit",
        signal: AbortSignal.timeout(10000),
      });
    } catch {
      throw new ControlPlaneError(writing ? "unknown-outcome" : "unavailable");
    }
    if (!response.ok) {
      const codes: Record<number, ControlErrorCode> = {
        400: "validation",
        401: "auth",
        403: "forbidden",
        404: "missing",
        409: "conflict",
        422: "validation",
        429: "rate-limit",
      };
      // Never include raw response bodies or URLs in errors/analytics.
      let fields: string[] = [];
      if (response.status === 422) {
        const detail: unknown = await response.json().catch(() => null);
        if (detail && typeof detail === "object" && "detail" in detail) {
          const errors = detail.detail;
          if (Array.isArray(errors))
            fields = errors.slice(0, 20).flatMap((item) => {
              if (!item || typeof item !== "object" || !Array.isArray(item.loc)) return [];
              const path = item.loc
                .filter(
                  (value: unknown) =>
                    (typeof value === "string" && /^[a-z_][a-z0-9_]*$/i.test(value)) ||
                    (typeof value === "number" && Number.isSafeInteger(value) && value >= 0),
                )
                .join(".");
              return path ? [path.slice(0, 160)] : [];
            });
          // Watcher validators return strings, unlike Pydantic envelopes.
          // Project only a leading schema path, never the submitted value or
          // error prose (which may contain private source details).
          if (
            typeof errors === "string" &&
            !/token|password|secret|bearer|credential/i.test(errors)
          ) {
            const field =
              /^([a-z_][a-z0-9_]*(?:(?:\[\d+\])|(?:\.[a-z_][a-z0-9_]*))*)(?=\s|:|$)/i.exec(
                errors,
              )?.[1];
            if (field) fields = [field.slice(0, 160)];
          }
        }
      }
      throw new ControlPlaneError(
        codes[response.status] ?? (writing ? "unknown-outcome" : "unavailable"),
        fields,
      );
    }
    try {
      return schema.parse(await response.json());
    } catch {
      throw new ControlPlaneError(writing ? "unknown-outcome" : "invalid-response");
    }
  }

  const read = request;
  async function getConfig(watcherId: string) {
    const result = await read(`${watcherPath(watcherId)}/config`, configSnapshot);
    if (result.watcher_id !== watcherId) throw new ControlPlaneError("invalid-response");
    return result;
  }
  async function getSchedule(jobId: string) {
    if (!id.safeParse(jobId).success) throw new ControlPlaneError("setup");
    const result = await read(`/v1/jobs/${jobId}/schedule`, job);
    if (result.job_id !== jobId) throw new ControlPlaneError("invalid-response");
    return result;
  }
  return {
    listWatchers: () => read("/v1/watchers", z.array(watcher).max(200)),
    getSourceCatalog: () => read("/v1/source-catalog", sourceCatalog),
    getEffectiveCatalog: () => read("/v1/source-catalog/effective", effectiveCatalog),
    async saveSourceCatalog(expectedRevision: number, config: z.infer<typeof catalogConfig>) {
      const payload = catalogWrite.safeParse({ expected_revision: expectedRevision, config });
      if (!payload.success) throw new ControlPlaneError("validation");
      const result = await request("/v1/source-catalog/config", catalogRevision, payload.data);
      if (result.revision <= expectedRevision) throw new ControlPlaneError("unknown-outcome");
      return result;
    },
    async listProfiles(watcherId: string) {
      const rows = await read(`${watcherPath(watcherId)}/profiles`, z.array(profile).max(500));
      if (
        rows.some((row) => row.watcher_id !== watcherId) ||
        new Set(rows.map((row) => row.profile_id)).size !== rows.length
      )
        throw new ControlPlaneError("invalid-response");
      return rows;
    },
    async saveProfileAvatar(watcherId: string, targetProfileId: string, input: AvatarInput) {
      const path = watcherPath(watcherId);
      const parsed = avatarInput.safeParse(input);
      if (!profileId.safeParse(targetProfileId).success || !parsed.success)
        throw new ControlPlaneError("validation");
      const result = await request(
        `${path}/profiles/${targetProfileId}/avatar`,
        profile,
        parsed.data,
      );
      if (
        result.watcher_id !== watcherId ||
        result.profile_id !== targetProfileId ||
        result.avatar.mode !== parsed.data.mode ||
        (parsed.data.mode === "manual" &&
          (!result.avatar.url ||
            canonicalAvatarUrl(result.avatar.url) !== canonicalAvatarUrl(parsed.data.url)))
      )
        throw new ControlPlaneError("unknown-outcome");
      return result;
    },
    async refreshProfileAvatar(watcherId: string, targetProfileId: string) {
      const path = watcherPath(watcherId);
      if (!profileId.safeParse(targetProfileId).success) throw new ControlPlaneError("validation");
      // This only acknowledges the request. A subsequent explicit read may
      // observe the asynchronous result; never retry or claim refresh success.
      const result = await request(
        `${path}/profiles/${targetProfileId}/avatar/refresh`,
        profile,
        undefined,
        "POST",
      );
      if (result.watcher_id !== watcherId || result.profile_id !== targetProfileId)
        throw new ControlPlaneError("unknown-outcome");
      return result;
    },
    async listJobs(watcherId: string) {
      const rows = await read(`${watcherPath(watcherId)}/jobs`, z.array(job).max(200));
      if (rows.some((row) => row.watcher_id !== watcherId))
        throw new ControlPlaneError("invalid-response");
      return rows;
    },
    async listComponents() {
      return read("/v1/components", componentList);
    },
    async getComponent(componentId: string) {
      if (!id.safeParse(componentId).success) throw new ControlPlaneError("setup");
      const result = await read(`/v1/components/${encodeURIComponent(componentId)}`, component);
      if (result.component_id !== componentId) throw new ControlPlaneError("invalid-response");
      return result;
    },
    async getComponentActivity(componentId: string) {
      if (!id.safeParse(componentId).success) throw new ControlPlaneError("setup");
      const result = await read(
        `/v1/components/${encodeURIComponent(componentId)}/activity`,
        componentActivity,
      );
      if (result.component_id !== componentId) throw new ControlPlaneError("invalid-response");
      return result;
    },
    async listOperatorJobs(componentId?: string) {
      const query = new URLSearchParams();
      if (componentId !== undefined) {
        if (!id.safeParse(componentId).success) throw new ControlPlaneError("validation");
        query.set("component_id", componentId);
      }
      return read(`/v1/jobs${query.size ? `?${query.toString()}` : ""}`, operatorJobList);
    },
    async getOperatorJob(jobId: string) {
      if (!id.safeParse(jobId).success) throw new ControlPlaneError("setup");
      const result = await read(`/v1/jobs/${encodeURIComponent(jobId)}`, operatorJob);
      if (result.job_id !== jobId) throw new ControlPlaneError("invalid-response");
      return result;
    },
    async listObservations(jobIds?: string[]) {
      const query = new URLSearchParams();
      if (jobIds !== undefined) {
        if (
          jobIds.length > 100 ||
          new Set(jobIds).size !== jobIds.length ||
          jobIds.some((jobId) => !id.safeParse(jobId).success)
        )
          throw new ControlPlaneError("validation");
        for (const jobId of jobIds) query.append("job_id", jobId);
      }
      const rows = await read(
        `/v1/observations${query.size ? `?${query.toString()}` : ""}`,
        z.array(observation).max(500),
      );
      if (
        new Set(rows.map((row) => `${row.identity_kind}:${row.identity_id}`)).size !== rows.length
      )
        throw new ControlPlaneError("invalid-response");
      return rows;
    },
    async listPublications(filters: PublicationFilters = {}) {
      const parsed = publicationFilters.safeParse(filters);
      if (!parsed.success) throw new ControlPlaneError("validation");
      const query = new URLSearchParams();
      for (const [key, value] of Object.entries(parsed.data)) {
        if (value !== undefined) query.set(key, String(value));
      }
      return read(`/v1/publications${query.size ? `?${query.toString()}` : ""}`, publicationPage);
    },
    async getPublication(publicationId: string) {
      if (!/^[0-9a-f]{64}$/.test(publicationId)) throw new ControlPlaneError("validation");
      const result = await read(`/v1/publications/${publicationId}`, publicationDetail);
      if (result.publication_id !== publicationId) throw new ControlPlaneError("invalid-response");
      return result;
    },
    async getPublicationCoverage() {
      return read("/v1/publications/coverage", publicationCoverage);
    },
    async listRuns(watcherId: string) {
      const rows = await read(`${watcherPath(watcherId)}/runs?limit=50`, z.array(run).max(50));
      if (rows.some((row) => row.watcher_id !== watcherId))
        throw new ControlPlaneError("invalid-response");
      return rows;
    },
    async listRunEvents(runId: string) {
      if (
        !runId ||
        runId.length > 128 ||
        [...runId].some((char) => char.charCodeAt(0) <= 32 || char.charCodeAt(0) === 127) ||
        runId === "." ||
        runId === ".."
      )
        throw new ControlPlaneError("setup");
      const rows = await read(
        `/v1/runs/${encodeURIComponent(runId)}/events?limit=500`,
        z.array(event).max(500),
      );
      if (rows.some((row) => row.run_id !== runId)) throw new ControlPlaneError("invalid-response");
      return rows;
    },
    getConfig,
    getSchedule,
    async saveConfig(
      watcherId: string,
      expectedRevision: number,
      input: { config_version: number; config: Record<string, unknown> },
    ) {
      if (
        !revision.safeParse(expectedRevision).success ||
        !revision.safeParse(input.config_version).success
      )
        throw new ControlPlaneError("validation");
      const current = await getConfig(watcherId);
      if (current.revision !== expectedRevision) throw new ControlPlaneError("conflict");
      // Best-effort stale-draft check, not an atomic compare-and-swap. The
      // upstream API currently has no If-Match or idempotency support.
      const result = await request(`${watcherPath(watcherId)}/config`, configSnapshot, input);
      if (result.watcher_id !== watcherId || result.revision <= expectedRevision)
        throw new ControlPlaneError("unknown-outcome");
      return result;
    },
    async saveSchedule(jobId: string, expectedRevision: number, input: ScheduleInput) {
      const parsed = scheduleInput.safeParse(input);
      if (!parsed.success || !revision.safeParse(expectedRevision).success)
        throw new ControlPlaneError("validation");
      const current = await getSchedule(jobId);
      if (
        current.schedule_kind === "fixed" ||
        !current.schedule ||
        current.schedule.revision !== expectedRevision
      )
        throw new ControlPlaneError("conflict");
      if (
        current.min_interval_seconds === null ||
        current.max_interval_seconds === null ||
        input.interval_seconds < current.min_interval_seconds ||
        input.interval_seconds > current.max_interval_seconds
      )
        throw new ControlPlaneError("validation");
      const result = await request(`/v1/jobs/${jobId}/schedule`, job, parsed.data);
      if (
        result.job_id !== jobId ||
        !result.schedule ||
        result.schedule.revision <= expectedRevision
      )
        throw new ControlPlaneError("unknown-outcome");
      return result;
    },
  };
}
