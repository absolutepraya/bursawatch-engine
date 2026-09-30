import { describe, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
import { handleControlRequest } from "./control-route";

const origin = "https://control.example.test";
const time = "2026-09-20T00:00:00Z";
const snapshot = {
  api_version: 1,
  watcher_id: "x-post-watch",
  revision: 2,
  config_version: 1,
  config: { profiles: [] },
  config_sha256: "a".repeat(64),
  updated_at: time,
};
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
  watcher_id: "x-post-watch",
  display_name: "X poller",
  schedule_kind: "interval",
  min_interval_seconds: 600,
  max_interval_seconds: 86400,
  schedule,
  reconciliation: { status: "applied", applied_revision: 2, effective: true },
};
function request(path: string, body?: unknown, extra: Record<string, string> = {}) {
  return new Request(`https://web.example.test/api/control/${path}`, {
    method: body === undefined ? "GET" : "PUT",
    headers: {
      authorization: "Bearer e30.e30.signature",
      origin: "https://web.example.test",
      "content-type": "application/json",
      ...extra,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}
function fake(...responses: Array<[unknown, number?]>) {
  const fetchImpl = vi.fn<typeof fetch>();
  for (const [body, status = 200] of responses)
    fetchImpl.mockResolvedValueOnce(new Response(JSON.stringify(body), { status }));
  return fetchImpl;
}
async function invoke(
  path: string,
  fetchImpl: typeof fetch,
  body?: unknown,
  headers?: Record<string, string>,
) {
  return handleControlRequest(request(path, body, headers), path.split("?")[0].split("/"), {
    origin,
    fetchImpl,
  });
}
const configWrite = { expectedRevision: 2, config_version: 1, config: { profiles: [] } };
const scheduleWrite = {
  expectedRevision: 2,
  enabled: true,
  interval_seconds: 1200,
  timezone: "Asia/Jakarta",
};

const avatarProfile = {
  watcher_id: "x-post-watch",
  profile_id: "source_one",
  handle: "sourceone",
  display_name: "Source One",
  profile_url: "https://x.com/sourceone",
  enabled: true,
  avatar: {
    mode: "auto",
    url: null,
    source: null,
    fetched_at: null,
    last_success_at: null,
    last_error: "private upstream details",
    updated_at: time,
  },
};

describe("profile metadata proxy", () => {
  const avatarPath = "watchers/x-post-watch/profiles/source_one/avatar";
  function refresh(
    path = `${avatarPath}/refresh`,
    originHeader = "https://web.example.test",
    body: unknown = {},
  ) {
    return new Request(`https://web.example.test/api/control/${path}`, {
      method: "POST",
      headers: {
        authorization: "Bearer e30.e30.signature",
        origin: originHeader,
        "content-type": "application/json",
      },
      body: JSON.stringify(body),
    });
  }
  it("allows authenticated profile reads with private, sanitized results", async () => {
    const fetchImpl = fake([[avatarProfile]]);
    const response = await invoke("watchers/x-post-watch/profiles", fetchImpl);
    expect(response.status).toBe(200);
    const result = await response.json();
    expect(result[0].avatar.has_error).toBe(true);
    expect(JSON.stringify(result)).not.toContain("private upstream");
    expect(response.headers.get("cache-control")).toContain("private, no-store");
  });
  it("forwards an avatar setting write through the user token only", async () => {
    const fetchImpl = fake([avatarProfile]);
    const response = await invoke(avatarPath, fetchImpl, { mode: "auto" });
    expect(response.status).toBe(200);
    expect(fetchImpl.mock.calls[0][1]).toMatchObject({
      method: "PUT",
      headers: { Authorization: "Bearer e30.e30.signature" },
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
  it("uses only the exact POST refresh route and an empty payload", async () => {
    const path = `${avatarPath}/refresh`;
    const fetchImpl = fake([avatarProfile]);
    const response = await handleControlRequest(refresh(), path.split("/"), { origin, fetchImpl });
    expect(response.status).toBe(200);
    expect(fetchImpl.mock.calls[0][1]?.method).toBe("POST");
    expect(fetchImpl.mock.calls[0][1]?.body).toBeUndefined();
    for (const invalidPath of [
      avatarPath,
      "watchers/x-post-watch/config",
      "runs/create",
      `${path}/extra`,
    ]) {
      expect(
        (
          await handleControlRequest(refresh(invalidPath), invalidPath.split("/"), {
            origin,
            fetchImpl,
          })
        ).status,
      ).toBe(404);
    }
    expect(
      (
        await handleControlRequest(
          refresh(path, "https://web.example.test", { url: "https://images.example.test/a.jpg" }),
          path.split("/"),
          { origin, fetchImpl },
        )
      ).status,
    ).toBe(422);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
  it("blocks cross-origin avatar saves and refreshes before fetching", async () => {
    const fetchImpl = fake();
    expect(
      (
        await invoke(
          avatarPath,
          fetchImpl,
          { mode: "auto" },
          { origin: "https://evil.example.test" },
        )
      ).status,
    ).toBe(403);
    const path = `${avatarPath}/refresh`;
    expect(
      (
        await handleControlRequest(refresh(path, "https://evil.example.test"), path.split("/"), {
          origin,
          fetchImpl,
        })
      ).status,
    ).toBe(403);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
  it("does not permit backend-denied viewer mutations or expose provider errors", async () => {
    const fetchImpl = fake([{ detail: "private auth message" }, 403]);
    const response = await invoke(avatarPath, fetchImpl, { mode: "auto" });
    expect(response.status).toBe(403);
    expect(await response.text()).not.toContain("private auth message");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
  it("rejects unsafe URLs and extra write fields without fetching", async () => {
    const fetchImpl = fake();
    for (const payload of [
      { mode: "manual", url: "https://user:secret@example.test/a.jpg" },
      { mode: "auto", token: "private" },
    ]) {
      expect((await invoke(avatarPath, fetchImpl, payload)).status).toBe(422);
    }
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe("operator inventory read proxy", () => {
  it("allowlists authenticated component, activity, job and observation GETs as no-store", async () => {
    const paths = [
      "components",
      "components/bursawatch-tg-source-ingest",
      "components/bursawatch-tg-source-ingest/activity",
      "jobs",
      "jobs?component_id=bursawatch-tg-market-news",
      "jobs/global-reader",
      "observations",
      "observations?job_id=global-reader",
    ];
    for (const path of paths) {
      const fetchImpl = fake([
        path === "components"
          ? { inventory_version: 1, components: [] }
          : ["jobs", "observations"].includes(path.split("?")[0])
            ? []
            : path === "jobs/global-reader"
              ? {
                  job_id: "global-reader",
                  can_edit: false,
                  watcher_id: null,
                  component_ids: [],
                  display_name: "Reader",
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
                }
              : path.endsWith("/activity")
                ? {
                    component_id: "bursawatch-tg-source-ingest",
                    endpoints: [],
                    pipelines: [],
                    delivery_status: "not instrumented",
                  }
                : {
                    inventory_version: 1,
                    component_id: "bursawatch-tg-source-ingest",
                    kind: "source_adapter",
                    display_name: "Telegram Source Adapter",
                    capabilities: [],
                    pipeline_ids: [],
                    config_resource_ids: [],
                    related_component_ids: [],
                    job_ids: [],
                  },
      ]);
      const response = await invoke(path, fetchImpl);
      expect(response.status).toBe(200);
      expect(response.headers.get("cache-control")).toContain("no-store");
      expect(fetchImpl.mock.calls[0][1]).toMatchObject({
        cache: "no-store",
        headers: { Authorization: "Bearer e30.e30.signature" },
      });
    }
  });

  it("rejects unrecognized inventory filters before contacting the API", async () => {
    const fetchImpl = fake();
    const response = await invoke("jobs?unbounded=true", fetchImpl);

    expect(response.status).toBe(422);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("does not expose the internal observation POST through the browser proxy", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const request = new Request("https://web.example.test/api/control/internal/observations", {
      method: "POST",
      headers: {
        authorization: "Bearer e30.e30.signature",
        origin: "https://web.example.test",
        "content-type": "application/json",
      },
      body: "{}",
    });
    const response = await handleControlRequest(request, ["internal", "observations"], {
      origin,
      fetchImpl,
    });
    expect(response.status).toBe(404);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe("authenticated control routes", () => {
  it.each(["", "Bearer machine-secret", "Bearer sb_secret_invalid"])(
    "rejects non-user-shaped credentials before fetching",
    async (authorization) => {
      const fetchImpl = fake();
      expect((await invoke("watchers", fetchImpl, undefined, { authorization })).status).toBe(401);
      expect(fetchImpl).not.toHaveBeenCalled();
    },
  );
  it("requires upstream verification even for JWT-shaped values", async () => {
    const response = await invoke("watchers", fake([{ detail: "internal-private-value" }, 401]));
    expect(response.status).toBe(401);
    expect(await response.text()).not.toContain("internal-private-value");
  });
  it.each([
    "internal/reconcile",
    "runs/create",
    "watchers/x-post-watch/execute",
    "watchers/../config",
  ])("does not expose arbitrary routes: %s", async (path) => {
    const fetchImpl = fake();
    expect((await invoke(path, fetchImpl)).status).toBe(404);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
  it("blocks cross-origin writes and machine endpoints", async () => {
    const fetchImpl = fake();
    expect(
      (
        await invoke("watchers/x-post-watch/config", fetchImpl, configWrite, {
          origin: "https://elsewhere.example.test",
        })
      ).status,
    ).toBe(403);
    expect((await invoke("internal/reconcile", fetchImpl, {})).status).toBe(404);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
  it("projects reads and marks every response private/no-store", async () => {
    const response = await invoke(
      "watchers",
      fake([
        [
          {
            watcher_id: "x-post-watch",
            display_name: "X",
            current_revision: 2,
            updated_at: time,
            token: "private-value",
          },
        ],
      ]),
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toContain("no-store");
    expect(response.headers.get("vary")).toBe("Authorization");
    expect(await response.text()).not.toContain("private-value");
  });
  it("saves a config only after checking its current revision", async () => {
    const fetchImpl = fake([snapshot], [{ ...snapshot, revision: 3 }]);
    const response = await invoke("watchers/x-post-watch/config", fetchImpl, configWrite);
    expect(response.status).toBe(200);
    expect(fetchImpl.mock.calls.map((call) => call[1]?.method)).toEqual(["GET", "PUT"]);
    expect(JSON.parse(fetchImpl.mock.calls[1][1]?.body as string)).toEqual({
      config_version: 1,
      config: { profiles: [] },
    });
    expect((await response.json()).revision).toBe(3);
  });
  it("leaves a stale draft untouched", async () => {
    const fetchImpl = fake([{ ...snapshot, revision: 3 }]);
    expect((await invoke("watchers/x-post-watch/config", fetchImpl, configWrite)).status).toBe(409);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
  it("does not issue a write for viewers", async () => {
    const fetchImpl = fake([{ detail: "admin required" }, 403]);
    expect((await invoke("watchers/x-post-watch/config", fetchImpl, configWrite)).status).toBe(403);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
  it("preserves validation field indices without exposing supplied values", async () => {
    const fetchImpl = fake(
      [snapshot],
      [
        {
          detail: [
            {
              loc: ["body", "config", "profiles", 0, "username"],
              input: "secret-input",
              msg: "private-error",
            },
          ],
        },
        422,
      ],
    );
    const response = await invoke("watchers/x-post-watch/config", fetchImpl, configWrite);
    expect(response.status).toBe(422);
    const body = await response.json();
    expect(body.fields).toEqual(["body.config.profiles.0.username"]);
    expect(JSON.stringify(body)).not.toMatch(/secret-input|private-error/);
  });
  it("extracts a plain validator path without forwarding its private prose", async () => {
    const fetchImpl = fake(
      [snapshot],
      [{ detail: "profiles[0].handle must match the configured private-source-account" }, 422],
    );
    const response = await invoke("watchers/x-post-watch/config", fetchImpl, configWrite);
    const result = await response.json();
    expect(result.fields).toEqual(["profiles[0].handle"]);
    expect(JSON.stringify(result)).not.toContain("private-source-account");
  });
  it.each([500, 502, 503])("never retries an uncertain write (%s)", async (status) => {
    const fetchImpl = fake([snapshot], [{ detail: "private-error" }, status]);
    const response = await invoke("watchers/x-post-watch/config", fetchImpl, configWrite);
    expect(response.status).toBe(502);
    expect((await response.json()).code).toBe("unknown-outcome");
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });
  it("treats dropped connections and malformed save acknowledgements as uncertain", async () => {
    for (const networkFailure of [true, false]) {
      const fetchImpl = fake([snapshot]);
      if (networkFailure) fetchImpl.mockRejectedValueOnce(new Error("private-network-data"));
      else fetchImpl.mockResolvedValueOnce(Response.json({ ...snapshot, revision: 2 }));
      const response = await invoke("watchers/x-post-watch/config", fetchImpl, configWrite);
      expect((await response.json()).code).toBe("unknown-outcome");
      expect(fetchImpl).toHaveBeenCalledTimes(2);
    }
  });
  it("validates schedule bounds and keeps fixed jobs read-only", async () => {
    for (const [current, input, status] of [
      [job, { ...scheduleWrite, interval_seconds: 60 }, 422],
      [
        {
          ...job,
          schedule_kind: "fixed",
          schedule: null,
          reconciliation: { status: "not_connected", applied_revision: null, effective: false },
        },
        scheduleWrite,
        409,
      ],
    ] as const) {
      const fetchImpl = fake([current]);
      expect((await invoke("jobs/x-poller/schedule", fetchImpl, input)).status).toBe(status);
      expect(fetchImpl).toHaveBeenCalledTimes(1);
    }
  });
  it("returns a saved schedule as pending, never inventing effective status", async () => {
    const pending = {
      ...job,
      schedule: { ...schedule, revision: 3, interval_seconds: 1200 },
      reconciliation: { status: "pending", applied_revision: 2, effective: false },
    };
    const fetchImpl = fake([job], [pending]);
    const response = await invoke("jobs/x-poller/schedule", fetchImpl, scheduleWrite);
    expect(response.status).toBe(200);
    expect((await response.json()).reconciliation.effective).toBe(false);
    expect(JSON.parse(fetchImpl.mock.calls[1][1]?.body as string)).not.toHaveProperty(
      "expectedRevision",
    );
  });
  it("rejects unknown payload fields and oversized requests before network access", async () => {
    const fetchImpl = fake();
    for (const body of [
      { ...configWrite, machineToken: "invalid" },
      { ...configWrite, config: { note: "x".repeat(262144) } },
    ]) {
      expect((await invoke("watchers/x-post-watch/config", fetchImpl, body)).status).toBe(422);
    }
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe("source catalog proxy", () => {
  const emptyConfig = {
    selected_securities: [],
    people_org: [],
    endpoints: [],
    publisher_defaults: [],
    endpoint_overrides: [],
  };
  const revision = {
    revision: 1,
    config: emptyConfig,
    sha256: "a".repeat(64),
    actor_id: "baseline",
    updated_at: time,
  };
  const catalog = {
    can_edit: true,
    securities: [],
    institutions: [],
    people_org: [],
    endpoints: [],
    capabilities: [],
    compatibility: [],
    config: revision,
  };
  it("forwards only exact authenticated catalog reads", async () => {
    const fetchImpl = fake(
      [catalog],
      [{ revision: 1, updated_at: time, selected_securities: [], subscriptions: [] }],
    );
    expect((await invoke("source-catalog", fetchImpl)).status).toBe(200);
    expect((await invoke("source-catalog/effective", fetchImpl)).status).toBe(200);
    expect((await invoke("source-catalog/private", fetchImpl)).status).toBe(404);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });
  it("checks origin and schema before a catalog write and preserves backend role denial", async () => {
    const fetchImpl = fake([{ detail: "private" }, 403]);
    const payload = { expected_revision: 1, config: emptyConfig };
    expect(
      (
        await invoke("source-catalog/config", fetchImpl, payload, {
          origin: "https://evil.example.test",
        })
      ).status,
    ).toBe(403);
    expect(
      (await invoke("source-catalog/config", fetchImpl, { ...payload, secret: "bad" })).status,
    ).toBe(422);
    const denied = await invoke("source-catalog/config", fetchImpl, payload);
    expect(denied.status).toBe(403);
    expect(await denied.text()).not.toContain("private");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});
