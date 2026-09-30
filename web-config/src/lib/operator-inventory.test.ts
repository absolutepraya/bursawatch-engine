import { describe, expect, it } from "vitest";
import {
  component,
  componentActivity,
  componentList,
  observation,
  operatorJob,
} from "./operator-inventory";

const time = "2026-09-29T00:00:00Z";
const componentRow = {
  inventory_version: 1,
  component_id: "bursawatch-tg-source-ingest",
  kind: "source_adapter",
  display_name: "Telegram Source Adapter",
  capabilities: ["telegram_source_intake"],
  pipeline_ids: [],
  config_resource_ids: ["source-catalog"],
  related_component_ids: ["bursawatch-tg-market-news"],
  job_ids: ["bursawatch-tg-source-ingest"],
};

describe("operator inventory response contracts", () => {
  it("requires the known inventory version and rejects unknown fields", () => {
    expect(component.safeParse({ ...componentRow, inventory_version: 2 }).success).toBe(false);
    expect(component.safeParse({ ...componentRow, internal_token: "secret" }).success).toBe(false);
    expect(componentList.safeParse({ inventory_version: 2, components: [] }).success).toBe(false);
  });

  it("accepts nullable activity timestamps while preserving unknown states", () => {
    const parsed = componentActivity.parse({
      component_id: componentRow.component_id,
      endpoints: [
        {
          endpoint_id: "endpoint-a",
          accepted_at: null,
          status: "unknown",
          meaning: "last accepted into Source Inbox",
        },
      ],
      pipelines: [
        {
          pipeline_id: "stockbit_snips",
          work_created_at: null,
          work_status: null,
          status: "unknown",
          meaning: "last pipeline work",
        },
      ],
      delivery_status: "not instrumented",
    });
    expect(parsed.endpoints[0].accepted_at).toBeNull();
    expect(parsed.delivery_status).toBe("not instrumented");
  });

  it("accepts a global job without watcher ownership and projects raw error text", () => {
    const parsed = operatorJob.parse({
      job_id: "global-reader",
      watcher_id: null,
      component_ids: [componentRow.component_id],
      display_name: "Shared reader",
      runtime_job_key: "runtime-reader",
      schedule_kind: "fixed",
      min_interval_seconds: null,
      max_interval_seconds: null,
      schedule: null,
      reconciliation: {
        status: "error",
        applied_revision: null,
        last_error: "private detail",
        effective: false,
      },
    });
    expect(parsed.watcher_id).toBeNull();
    expect(parsed.reconciliation).toEqual({
      status: "error",
      applied_revision: null,
      effective: false,
      has_error: true,
    });
  });

  it("rejects stale or malformed observations and unknown observation fields", () => {
    const row = {
      api_version: 1,
      identity_kind: "job",
      identity_id: "global-reader",
      observer_id: "observer",
      observed_at: time,
      received_at: time,
      status: "stale",
      freshness: "stale",
      evidence: {
        runtime_job_key: "runtime-reader",
        enabled: true,
        schedule: { kind: "cron", expr: "0 * * * *" },
        last_execution: { at: null, status: null },
      },
      comparison: "not_comparable",
      desired: null,
      reconciliation: { status: "not_connected", applied_revision: null },
    };
    expect(observation.parse(row).evidence.last_execution.at).toBeNull();
    expect(observation.safeParse({ ...row, unsafe: true }).success).toBe(false);
    expect(observation.safeParse({ ...row, observed_at: "not-a-date" }).success).toBe(false);
  });
});
