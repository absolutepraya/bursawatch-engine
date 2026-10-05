import { describe, expect, it } from "vitest";
import {
  component,
  componentActivity,
  componentList,
  observation,
  operatorJob,
  operatorJobList,
} from "./operator-inventory";

const time = "2026-09-29T00:00:00Z";
const activity = {
  component_id: "bursawatch-ig-source-ingest",
  endpoints: [
    {
      endpoint_id: "instagram:synthetic.research",
      accepted_at: time,
      status: "observed",
      meaning: "last accepted into Source Inbox",
    },
  ],
  pipelines: [],
  delivery_status: "not instrumented",
};
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
  it.each([
    "instagram:synthetic.research",
    "whatsapp:0029SyntheticMixedCase",
    "rss:stockbit:unboxing_ipo",
  ])(
    "preserves catalog endpoint identity %s and all activity states",
    (endpointId) => {
      for (const status of ["unknown", "stale", "observed"]) {
        const row = {
          ...activity.endpoints[0],
          endpoint_id: endpointId,
          status,
          accepted_at: status === "unknown" ? null : time,
        };
        expect(
          componentActivity.parse({ ...activity, endpoints: [row] })
            .endpoints[0],
        ).toEqual(row);
      }
    },
  );

  it.each([
    "",
    "a".repeat(129),
    "instagram:bad/handle",
    "instagram:bad handle",
    "instagram:bad\n",
    "whatsapp:bad\r\n",
    "whatsapp:bad?query",
    "instagram:bad\u0000",
    "instagram:résumé",
  ])("rejects malformed or oversized endpoint identity %j", (endpointId) => {
    expect(
      componentActivity.safeParse({
        ...activity,
        endpoints: [{ ...activity.endpoints[0], endpoint_id: endpointId }],
      }).success,
    ).toBe(false);
  });

  it("keeps component, pipeline and capability identities narrow", () => {
    expect(
      componentActivity.safeParse({
        ...activity,
        component_id: "Adapter.MixedCase",
      }).success,
    ).toBe(false);
    expect(
      componentActivity.safeParse({
        ...activity,
        pipelines: [
          {
            pipeline_id: "Pipeline.MixedCase",
            work_created_at: null,
            work_status: null,
            status: "unknown",
            meaning: "last pipeline work",
          },
        ],
      }).success,
    ).toBe(false);
    expect(
      component.safeParse({
        ...componentRow,
        capabilities: ["Capability.MixedCase"],
      }).success,
    ).toBe(false);
    expect(
      componentActivity.safeParse({ ...activity, unsafe: true }).success,
    ).toBe(false);
    expect(
      componentActivity.safeParse({
        ...activity,
        endpoints: [{ ...activity.endpoints[0], accepted_at: "not-a-date" }],
      }).success,
    ).toBe(false);
  });
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
    const row = {
      job_id: "global-reader",
      can_edit: false,
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
    };
    const parsed = operatorJob.parse(row);
    expect(
      operatorJob.safeParse({ ...row, job_id: "Job.MixedCase" }).success,
    ).toBe(false);
    expect(parsed.watcher_id).toBeNull();
    expect(parsed.reconciliation).toEqual({
      status: "error",
      applied_revision: null,
      effective: false,
      has_error: true,
    });
    expect(operatorJobList.safeParse([row, row]).success).toBe(false);
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
