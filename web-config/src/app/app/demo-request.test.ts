import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EffectiveCatalog, SourceCatalog } from "@/lib/source-catalog";
import type { ControlConfigSnapshot, ControlWatcher } from "@/server/control-plane";
import { validateWatcherConfig } from "@/lib/watcher-fields";
import { createDemoRequester } from "./demo-request";

describe("sample workspace request fixture", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("serves the eight real watcher editors with schema-valid sample configs", async () => {
    const request = createDemoRequester();
    const watchers = await request<ControlWatcher[]>("watchers");

    expect(watchers).toHaveLength(8);
    for (const watcher of watchers) {
      const snapshot = await request<ControlConfigSnapshot>(
        `watchers/${watcher.watcher_id}/config`,
      );
      expect(validateWatcherConfig(watcher.watcher_id, snapshot.config)).toEqual({});
    }
  });

  it("saves a supported watcher edit in memory and confirms it with a later read", async () => {
    const request = createDemoRequester();
    const path = "watchers/bursawatch-x-account-watch/config";
    const initial = await request<ControlConfigSnapshot>(path);
    const config = structuredClone(initial.config);
    (config.profiles as Array<Record<string, unknown>>)[0].enable_llm_summary = true;

    const saved = await request<ControlConfigSnapshot>(path, {
      expectedRevision: initial.revision,
      config_version: initial.config_version,
      config,
    });
    const confirmed = await request<ControlConfigSnapshot>(path);

    expect(saved.revision).toBe(initial.revision + 1);
    expect(confirmed).toEqual(saved);
    expect((confirmed.config.profiles as Array<Record<string, unknown>>)[0].enable_llm_summary).toBe(
      true,
    );
  });

  it("keeps fixture state isolated between sample workspaces", async () => {
    const first = createDemoRequester();
    const second = createDemoRequester();
    const path = "watchers/bursawatch-x-account-watch/config";
    const initial = await first<ControlConfigSnapshot>(path);
    const config = structuredClone(initial.config);
    (config.profiles as Array<Record<string, unknown>>)[0].enable_llm_summary = true;
    await first(path, {
      expectedRevision: initial.revision,
      config_version: initial.config_version,
      config,
    });

    const untouched = await second<ControlConfigSnapshot>(path);
    expect(untouched.revision).toBe(1);
    expect((untouched.config.profiles as Array<Record<string, unknown>>)[0].enable_llm_summary).toBe(
      false,
    );
  });

  it("saves Source Catalog settings and confirms both catalog reads", async () => {
    const request = createDemoRequester();
    const initial = await request<SourceCatalog>("source-catalog");
    const config = { ...initial.config.config, selected_securities: ["ENRG"] };
    await request("source-catalog/config", {
      expected_revision: initial.config.revision,
      config,
    });
    const catalog = await request<SourceCatalog>("source-catalog");
    const effective = await request<{ revision: number; selected_securities: string[] }>(
      "source-catalog/effective",
    );

    expect(catalog.config.revision).toBe(2);
    expect(catalog.config.config.selected_securities).toEqual(["ENRG"]);
    expect(effective).toMatchObject({ revision: 2, selected_securities: ["ENRG"] });
    expect(catalog.people_org.find((person) => person.id === "x-rickyho1989")?.name).toBe(
      "Ricky Ho",
    );
  });

  it("saves a supported public analyst capability setting and confirms its effective state", async () => {
    const request = createDemoRequester();
    const initial = await request<SourceCatalog>("source-catalog");
    const endpoint = initial.endpoints.find((item) => item.publisher_id === "x-rickyho1989");
    expect(endpoint).toMatchObject({ id: "x-rickyho1989", platform: "x", verified: true });
    expect(
      initial.compatibility.some(
        (item) => item.endpoint_id === endpoint?.id && item.capability_id === "company_news",
      ),
    ).toBe(true);

    const config = structuredClone(initial.config.config);
    config.endpoint_overrides.push({
      endpoint_id: endpoint!.id,
      capability_id: "company_news",
      enabled: true,
      settings: {},
    });
    await request("source-catalog/config", {
      expected_revision: initial.config.revision,
      config,
    });

    const confirmed = await request<EffectiveCatalog>("source-catalog/effective");
    expect(confirmed.revision).toBe(initial.config.revision + 1);
    expect(confirmed.subscriptions).toContainEqual(
      expect.objectContaining({
        endpoint_id: endpoint!.id,
        capability_id: "company_news",
        enabled: true,
        verification_status: "verified",
        source: "endpoint_override",
      }),
    );
  });

  it("keeps jobs read-only and rejects unsupported schedule writes", async () => {
    const request = createDemoRequester();
    const jobs = await request<Array<{ can_edit: boolean }>>("jobs");
    expect(jobs.length).toBeGreaterThan(0);
    expect(jobs.every((job) => job.can_edit === false)).toBe(true);
    await expect(
      request("jobs/sample-source-intake-job/schedule", {
        enabled: true,
        interval_seconds: 604800,
        timezone: "Asia/Jakarta",
      }),
    ).rejects.toMatchObject({ code: "missing" });
  });

  it("preserves WorkspaceError codes and abort behavior without making network requests", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    const request = createDemoRequester();

    await expect(request("watchers/unknown/config")).rejects.toMatchObject({ code: "missing" });
    await expect(
      request("source-catalog/config", { expected_revision: 10, config: {} }),
    ).rejects.toMatchObject({ code: "validation" });
    await expect(
      request("source-catalog/config", {
        expected_revision: 10,
        config: {
          selected_securities: [],
          people_org: [],
          endpoints: [],
          publisher_defaults: [],
          endpoint_overrides: [],
        },
      }),
    ).rejects.toMatchObject({ code: "conflict" });

    const controller = new AbortController();
    controller.abort();
    await expect(request("watchers", undefined, { signal: controller.signal })).rejects.toMatchObject({
      name: "AbortError",
    });
    expect(fetch).not.toHaveBeenCalled();
  });
});
