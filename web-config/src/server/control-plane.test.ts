import { describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
import { createControlPlaneReader } from "./control-plane";

const time = "2026-09-19T10:00:00+07:00";
const schedule = {
  api_version: 1,
  job_id: "x-poller",
  revision: 2,
  enabled: true,
  interval_seconds: 600,
  timezone: "Asia/Jakarta",
  schedule_sha256: "a".repeat(64),
  updated_at: time,
};
const job = {
  job_id: "x-poller",
  can_edit: true,
  watcher_id: "x-watch",
  display_name: "X source poller",
  runtime_job_key: "private-runtime-key",
  schedule_kind: "interval",
  min_interval_seconds: 600,
  max_interval_seconds: 86400,
  schedule,
  reconciliation: {
    status: "pending",
    applied_revision: 1,
    last_error: "private-provider-error",
    effective: false,
  },
};
const run = {
  run_id: "run-1",
  watcher_id: "x-watch",
  scheduler_job_id: "x-poller",
  trigger: "scheduled",
  config_revision: 2,
  started_at: time,
  finished_at: time,
  status: "ok",
  error: "private-provider-error",
};
function setup(body: unknown, status = 200) {
  const fetchImpl = vi
    .fn<typeof fetch>()
    .mockImplementation(async () => new Response(JSON.stringify(body), { status }));
  const getAccessToken = vi.fn(async () => "user-session-token");
  return {
    fetchImpl,
    getAccessToken,
    reader: createControlPlaneReader({
      origin: "https://control.example.test",
      getAccessToken,
      fetchImpl,
    }),
  };
}

const avatarProfile = {
  watcher_id: "x-watch",
  profile_id: "source_one",
  handle: "sourceone",
  display_name: "Source One",
  profile_url: "https://x.com/sourceone",
  enabled: true,
  avatar: {
    mode: "auto",
    url: "https://pbs.twimg.com/profile_images/fixture.jpg",
    source: "rsshub_icon",
    fetched_at: time,
    last_success_at: time,
    last_error: null,
    updated_at: time,
  },
};

describe("profile avatar adapter", () => {
  it("projects metadata and safe refresh failure state without raw details", async () => {
    const { reader, fetchImpl } = setup([
      {
        ...avatarProfile,
        private_field: "hidden",
        avatar: {
          ...avatarProfile.avatar,
          last_error: "private upstream credentials",
          extra: "hidden",
        },
      },
    ]);
    const [result] = await reader.listProfiles("x-watch");
    expect(result.avatar).toMatchObject({ has_error: true, url: avatarProfile.avatar.url });
    expect(JSON.stringify(result)).not.toMatch(/hidden|private upstream|last_error/);
    expect(fetchImpl.mock.calls[0][0]).toBe(
      "https://control.example.test/v1/watchers/x-watch/profiles",
    );
  });
  it("rejects mismatched watcher identity and duplicate source IDs", async () => {
    await expect(setup([avatarProfile]).reader.listProfiles("other-watch")).rejects.toMatchObject({
      code: "invalid-response",
    });
    await expect(
      setup([avatarProfile, avatarProfile]).reader.listProfiles("x-watch"),
    ).rejects.toMatchObject({ code: "invalid-response" });
  });
  it.each([
    "http://images.example.test/p.jpg",
    "https://user:secret@images.example.test/p.jpg",
    "https://images.example.test:444/p.jpg",
    "https://images.example.test/p.jpg#fragment",
    "javascript:alert(1)",
    "https://127.0.0.1/p.jpg",
    "https://[::1]/p.jpg",
    "https://192.168.1.2/p.jpg",
    "https://localhost/p.jpg",
    "https://private.local/p.jpg",
    "https://images.example.test/p.jpg\n",
  ])("blocks unsafe URLs before write and from metadata: %s", async (url) => {
    const { reader, fetchImpl } = setup(avatarProfile);
    await expect(
      reader.saveProfileAvatar("x-watch", "source_one", { mode: "manual", url }),
    ).rejects.toMatchObject({ code: "validation" });
    expect(fetchImpl).not.toHaveBeenCalled();
    await expect(
      setup([{ ...avatarProfile, avatar: { ...avatarProfile.avatar, url } }]).reader.listProfiles(
        "x-watch",
      ),
    ).rejects.toMatchObject({ code: "invalid-response" });
  });
  it("saves manual mode once without reading or forwarding config", async () => {
    const { reader, fetchImpl } = setup({
      ...avatarProfile,
      avatar: { ...avatarProfile.avatar, mode: "manual" },
    });
    await reader.saveProfileAvatar("x-watch", "source_one", {
      mode: "manual",
      url: avatarProfile.avatar.url,
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(fetchImpl.mock.calls[0]).toEqual([
      "https://control.example.test/v1/watchers/x-watch/profiles/source_one/avatar",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ mode: "manual", url: avatarProfile.avatar.url }),
        cache: "no-store",
      }),
    ]);
  });
  it("saves automatic mode without an image URL", async () => {
    const { reader, fetchImpl } = setup(avatarProfile);
    await reader.saveProfileAvatar("x-watch", "source_one", { mode: "auto" });
    expect(fetchImpl.mock.calls[0][1]?.body).toBe('{"mode":"auto"}');
    await expect(
      reader.saveProfileAvatar("x-watch", "source_one", {
        mode: "auto",
        url: "https://images.example.test/p.jpg",
      } as never),
    ).rejects.toMatchObject({ code: "validation" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
  it("refreshes via one POST and preserves the existing result without inventing completion", async () => {
    const { reader, fetchImpl } = setup(avatarProfile);
    const result = await reader.refreshProfileAvatar("x-watch", "source_one");
    expect(fetchImpl.mock.calls[0]).toEqual([
      "https://control.example.test/v1/watchers/x-watch/profiles/source_one/avatar/refresh",
      expect.objectContaining({
        method: "POST",
        body: undefined,
        redirect: "error",
        credentials: "omit",
      }),
    ]);
    expect(result.avatar.updated_at).toBe(time);
    expect(result).not.toHaveProperty("refreshed");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
  it("rejects invalid profile identities without requests", async () => {
    const { reader, fetchImpl } = setup(avatarProfile);
    for (const invalid of ["../config", "UPPERCASE", "a".repeat(65)]) {
      await expect(reader.refreshProfileAvatar("x-watch", invalid)).rejects.toMatchObject({
        code: "validation",
      });
    }
    expect(fetchImpl).not.toHaveBeenCalled();
  });
  it("does not accept another profile's mutation acknowledgement", async () => {
    const { reader } = setup({ ...avatarProfile, profile_id: "other" });
    await expect(reader.refreshProfileAvatar("x-watch", "source_one")).rejects.toMatchObject({
      code: "unknown-outcome",
    });
    await expect(
      reader.saveProfileAvatar("x-watch", "source_one", { mode: "auto" }),
    ).rejects.toMatchObject({ code: "unknown-outcome" });
  });
  it("does not confirm a manual save when the returned URL is different", async () => {
    const { reader, fetchImpl } = setup({
      ...avatarProfile,
      avatar: { ...avatarProfile.avatar, mode: "manual" },
    });
    await expect(
      reader.saveProfileAvatar("x-watch", "source_one", {
        mode: "manual",
        url: "https://images.example.test/new.jpg",
      }),
    ).rejects.toMatchObject({ code: "unknown-outcome" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
  it("never retries uncertain refresh requests or exposes raw errors", async () => {
    for (const networkError of [true, false]) {
      const { reader, fetchImpl } = setup({ detail: "private provider details" }, 503);
      if (networkError) fetchImpl.mockRejectedValueOnce(new Error("private provider details"));
      await expect(reader.refreshProfileAvatar("x-watch", "source_one")).rejects.toMatchObject({
        code: "unknown-outcome",
      });
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    }
  });
});

describe("operator inventory reads", () => {
  const componentRow = {
    inventory_version: 1,
    component_id: "bursawatch-tg-source-ingest",
    kind: "source_adapter",
    display_name: "Telegram Source Adapter",
    capabilities: ["telegram_source_intake"],
    pipeline_ids: [],
    config_resource_ids: ["source-catalog"],
    related_component_ids: [],
    job_ids: [],
  };
  it("reads versioned components, component activity, jobs and observations with user JWT/no-store", async () => {
    const responses = [
      { inventory_version: 1, components: [componentRow] },
      componentRow,
      {
        component_id: componentRow.component_id,
        endpoints: [
          {
            endpoint_id: "endpoint-a",
            accepted_at: null,
            status: "unknown",
            meaning: "last accepted into Source Inbox",
          },
        ],
        pipelines: [],
        delivery_status: "not instrumented",
      },
      [
        {
          job_id: "global-reader",
          can_edit: false,
          watcher_id: null,
          component_ids: [],
          display_name: "Global reader",
          runtime_job_key: "reader",
          schedule_kind: "fixed",
          min_interval_seconds: null,
          max_interval_seconds: null,
          schedule: null,
          reconciliation: {
            status: "not_connected",
            applied_revision: null,
            last_error: null,
            effective: false,
          },
        },
      ],
      {
        job_id: "global-reader",
        can_edit: false,
        watcher_id: null,
        component_ids: [],
        display_name: "Global reader",
        runtime_job_key: "reader",
        schedule_kind: "fixed",
        min_interval_seconds: null,
        max_interval_seconds: null,
        schedule: null,
        reconciliation: {
          status: "not_connected",
          applied_revision: null,
          last_error: null,
          effective: false,
        },
      },
      [],
    ];
    const { reader, fetchImpl } = setup(null);
    fetchImpl.mockImplementation(
      async () => new Response(JSON.stringify(responses.shift()), { status: 200 }),
    );
    expect((await reader.listComponents()).components[0].component_id).toBe(
      componentRow.component_id,
    );
    expect((await reader.getComponent(componentRow.component_id)).component_id).toBe(
      componentRow.component_id,
    );
    expect(
      (await reader.getComponentActivity(componentRow.component_id)).endpoints[0].accepted_at,
    ).toBeNull();
    expect((await reader.listOperatorJobs())[0].watcher_id).toBeNull();
    expect((await reader.getOperatorJob("global-reader")).job_id).toBe("global-reader");
    expect(await reader.listObservations()).toEqual([]);
    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      "https://control.example.test/v1/components",
      `https://control.example.test/v1/components/${componentRow.component_id}`,
      `https://control.example.test/v1/components/${componentRow.component_id}/activity`,
      "https://control.example.test/v1/jobs",
      "https://control.example.test/v1/jobs/global-reader",
      "https://control.example.test/v1/observations",
    ]);
    expect(
      fetchImpl.mock.calls.every(
        ([, init]) =>
          init?.cache === "no-store" &&
          new Headers(init?.headers).get("Authorization") === "Bearer user-session-token",
      ),
    ).toBe(true);
  });

  it("filters shared jobs and observations to the requested workflow", async () => {
    const operatorJob = {
      job_id: "shared-reader",
      can_edit: false,
      watcher_id: null,
      component_ids: ["bursawatch-tg-market-news"],
      display_name: "Shared Telegram reader",
      runtime_job_key: "bursawatch-tg-source-ingest",
      schedule_kind: "fixed",
      min_interval_seconds: null,
      max_interval_seconds: null,
      schedule: null,
      reconciliation: {
        status: "not_connected",
        applied_revision: null,
        last_error: null,
        effective: false,
      },
    };
    const { reader, fetchImpl } = setup([operatorJob]);
    fetchImpl
      .mockImplementationOnce(async () => new Response(JSON.stringify([operatorJob])))
      .mockImplementationOnce(async () => new Response(JSON.stringify([])));

    expect((await reader.listOperatorJobs("bursawatch-tg-market-news"))[0].job_id).toBe(
      "shared-reader",
    );
    expect(await reader.listObservations(["shared-reader"])).toEqual([]);
    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      "https://control.example.test/v1/jobs?component_id=bursawatch-tg-market-news",
      "https://control.example.test/v1/observations?job_id=shared-reader",
    ]);
  });
});

describe("control-plane read adapter", () => {
  it("uses only uncached authenticated GET requests, with no redirects", async () => {
    const { reader, fetchImpl } = setup([
      { watcher_id: "x-watch", display_name: "X", current_revision: null, updated_at: time },
    ]);
    expect(await reader.listWatchers()).toHaveLength(1);
    expect(fetchImpl).toHaveBeenCalledWith(
      "https://control.example.test/v1/watchers",
      expect.objectContaining({
        method: "GET",
        cache: "no-store",
        redirect: "error",
        credentials: "omit",
        headers: { Authorization: "Bearer user-session-token", Accept: "application/json" },
      }),
    );
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it.each([
    "http://control.example.test",
    "https://user:secret@control.example.test",
    "https://control.example.test/v1",
    "https://control.example.test?key=value",
    "https://control.example.test#fragment",
    "not-a-url",
  ])("rejects unsafe or ambiguous service origins: %s", (origin) => {
    expect(() => createControlPlaneReader({ origin, getAccessToken: async () => null })).toThrow(
      /set up/,
    );
  });

  it("requires a session without issuing a network request", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const reader = createControlPlaneReader({
      origin: "https://control.example.test",
      getAccessToken: async () => null,
      fetchImpl,
    });
    await expect(reader.listWatchers()).rejects.toMatchObject({ code: "auth" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("resolves the current token for every read instead of retaining old sessions", async () => {
    const { reader, getAccessToken, fetchImpl } = setup([]);
    await reader.listWatchers();
    getAccessToken.mockResolvedValue("refreshed-user-token");
    await reader.listWatchers();
    expect(fetchImpl.mock.calls[1][1]?.headers).toMatchObject({
      Authorization: "Bearer refreshed-user-token",
    });
  });

  it.each([
    [401, "auth"],
    [403, "forbidden"],
    [404, "missing"],
    [429, "rate-limit"],
    [500, "unavailable"],
  ])("sanitizes HTTP %s without disclosing provider details", async (status, code) => {
    const { reader } = setup({ detail: "private-provider-error" }, status as number);
    await expect(reader.listWatchers()).rejects.toMatchObject({ code });
    await expect(reader.listWatchers()).rejects.not.toThrow(/private-provider-error/);
  });

  it("sanitizes network errors and does not retry or substitute sample data", async () => {
    const { reader, fetchImpl } = setup([]);
    fetchImpl.mockRejectedValue(new Error("private-provider-error"));
    await expect(reader.listWatchers()).rejects.toMatchObject({ code: "unavailable" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("rejects malformed responses", async () => {
    await expect(setup([{ watcher_id: "x-watch" }]).reader.listWatchers()).rejects.toMatchObject({
      code: "invalid-response",
    });
  });

  it("preserves pending versus applied and strips runtime/error fields", async () => {
    const [result] = await setup([job]).reader.listJobs("x-watch");
    expect(result.reconciliation).toEqual({
      status: "pending",
      applied_revision: 1,
      effective: false,
    });
    expect(result).not.toHaveProperty("runtime_job_key");
    expect(result.reconciliation).not.toHaveProperty("last_error");
    const applied = {
      ...job,
      reconciliation: { status: "applied", applied_revision: 2, effective: true },
    };
    expect((await setup([applied]).reader.listJobs("x-watch"))[0].reconciliation.effective).toBe(
      true,
    );
  });

  it("rejects false effective status and mismatched schedule identities", async () => {
    for (const invalid of [
      { ...job, reconciliation: { status: "applied", applied_revision: 1, effective: true } },
      { ...job, reconciliation: { status: "pending", applied_revision: 2, effective: true } },
      { ...job, schedule: { ...schedule, job_id: "other-job" } },
    ])
      await expect(setup([invalid]).reader.listJobs("x-watch")).rejects.toMatchObject({
        code: "invalid-response",
      });
  });

  it("retains fixed jobs without inventing a configurable schedule", async () => {
    const fixed = {
      ...job,
      schedule_kind: "fixed",
      schedule: null,
      min_interval_seconds: null,
      max_interval_seconds: null,
      reconciliation: { status: "not_connected", applied_revision: null, effective: false },
    };
    expect((await setup([fixed]).reader.listJobs("x-watch"))[0].schedule).toBeNull();
  });

  it("validates run provenance without implying successful delivery", async () => {
    const { reader, fetchImpl } = setup([run]);
    const [result] = await reader.listRuns("x-watch");
    expect(result).toMatchObject({ status: "ok", config_revision: 2, trigger: "scheduled" });
    expect(result).not.toHaveProperty("error");
    expect(result).not.toHaveProperty("delivered");
    expect(fetchImpl.mock.calls[0][0]).toBe(
      "https://control.example.test/v1/watchers/x-watch/runs?limit=50",
    );
    await expect(setup([run]).reader.listRuns("another-watch")).rejects.toMatchObject({
      code: "invalid-response",
    });
  });

  it("allowlists event metadata and rejects a different run's events", async () => {
    const event = {
      run_id: "run-1",
      event_id: "event-1",
      occurred_at: time,
      level: "info",
      phase: "scan",
      event_type: "no-change",
      message: "private-source-text",
      attributes: { token: "private-provider-secret" },
    };
    const [result] = await setup([event]).reader.listRunEvents("run-1");
    expect(result.event_type).toBe("no-change");
    expect(result).not.toHaveProperty("message");
    expect(result).not.toHaveProperty("attributes");
    await expect(setup([event]).reader.listRunEvents("run-2")).rejects.toMatchObject({
      code: "invalid-response",
    });
  });

  it("prevents identifiers from selecting arbitrary API paths", async () => {
    const { reader, fetchImpl } = setup([]);
    await expect(reader.listJobs("../internal/schedules")).rejects.toMatchObject({ code: "setup" });
    await expect(reader.listRunEvents("..")).rejects.toMatchObject({ code: "setup" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe("safe run diagnostics", () => {
  const metadata = {
    run_id: "run-1",
    event_id: "event-1",
    occurred_at: time,
    level: "info",
    phase: "source",
  };
  async function project(eventType: string, attributes?: unknown) {
    const [event] = await setup([
      { ...metadata, event_type: eventType, attributes },
    ]).reader.listRunEvents("run-1");
    return event;
  }

  it("preserves observed zero counts and false flags without synthesizing absent fields", async () => {
    expect(
      (
        await project("source.fetch.completed", {
          profile_id: "example_writer-1",
          items: 0,
          queued: 0,
        })
      ).diagnostics,
    ).toEqual({ profile_id: "example_writer-1", items: 0, queued: 0 });
    expect(
      (
        await project("delivery.drain.completed", {
          delivered: 0,
          pending: 0,
          oldest_pending_minutes: 0,
          queue_only: false,
        })
      ).diagnostics,
    ).toEqual({ delivered: 0, pending: 0, oldest_pending_minutes: 0, queue_only: false });
    expect(
      (await project("run.started", { dry_run: false, queue_only: false })).diagnostics,
    ).toEqual({ dry_run: false, queue_only: false });
    expect((await project("source.fetch.completed", { items: 2 })).diagnostics).toEqual({
      items: 2,
    });
    expect(await project("delivery.drain.completed", {})).not.toHaveProperty("diagnostics");
  });

  it.each([undefined, null, [], "private-provider-secret", 0, true])(
    "omits malformed or missing attributes: %j",
    async (attributes) => {
      const event = await project("source.fetch.completed", attributes);
      expect(event).not.toHaveProperty("diagnostics");
      expect(event).not.toHaveProperty("attributes");
    },
  );

  it.each([-1, 0.5, "1", null, true, Number.MAX_SAFE_INTEGER + 1])(
    "omits invalid counters without losing independent valid fields: %j",
    async (invalid) => {
      expect(
        (
          await project("source.fetch.completed", {
            profile_id: "example",
            items: invalid,
            queued: 3,
          })
        ).diagnostics,
      ).toEqual({ profile_id: "example", queued: 3 });
      expect(
        (
          await project("delivery.drain.completed", {
            delivered: invalid,
            pending: invalid,
            oldest_pending_minutes: invalid,
            queue_only: true,
          })
        ).diagnostics,
      ).toEqual({ queue_only: true });
    },
  );

  it.each([
    "",
    "a".repeat(65),
    "Example",
    "https://private.example.test",
    "secret_value",
    "sb_secret_example",
    "sb_publishable_example",
    "sk_example",
    "github_pat_example",
    "ghp_example",
    "bearer_example",
    "token_example",
    "password_example",
    "service_role",
    "example\n",
    "例",
    42,
  ])("omits malformed or credential-like profile identifiers: %j", async (profileId) => {
    expect(
      (await project("source.fetch.failed", { profile_id: profileId })).diagnostics,
    ).toBeUndefined();
  });

  it("limits each event type to its reviewed fields and never forwards provider prose", async () => {
    const attributes = {
      profile_id: "example",
      items: 2,
      queued: 1,
      delivered: 3,
      pending: 4,
      oldest_pending_minutes: 5,
      queue_only: true,
      dry_run: true,
      token: "private-secret",
      error: "private-error",
      reasons: ["private-reason"],
      url: "https://private.example.test",
      config: { private: true },
    };
    const expected: Record<string, unknown> = {
      "source.fetch.completed": { profile_id: "example", items: 2, queued: 1 },
      "source.fetch.failed": { profile_id: "example" },
      "delivery.drain.completed": {
        delivered: 3,
        pending: 4,
        oldest_pending_minutes: 5,
        queue_only: true,
      },
      "run.started": { queue_only: true, dry_run: true },
      "agent.submission.accepted": undefined,
      "unknown.event": undefined,
    };
    for (const [eventType, diagnostics] of Object.entries(expected)) {
      const [event] = await setup([
        {
          ...metadata,
          event_type: eventType,
          attributes,
          diagnostics: attributes,
          message: "private-message",
        },
      ]).reader.listRunEvents("run-1");
      expect(event.diagnostics).toEqual(diagnostics);
      expect(event).not.toHaveProperty("attributes");
      expect(event).not.toHaveProperty("message");
      expect(JSON.stringify(event)).not.toContain("private");
    }
  });

  it("does not coerce boolean strings or numbers", async () => {
    expect(await project("run.started", { dry_run: "false", queue_only: 1 })).not.toHaveProperty(
      "diagnostics",
    );
    expect(await project("delivery.drain.completed", { queue_only: "true" })).not.toHaveProperty(
      "diagnostics",
    );
  });

  it("retains run provenance validation for events with diagnostics", async () => {
    await expect(
      setup([
        {
          ...metadata,
          event_type: "source.fetch.completed",
          attributes: { profile_id: "example", queued: 1 },
        },
      ]).reader.listRunEvents("other-run"),
    ).rejects.toMatchObject({ code: "invalid-response" });
  });
});
