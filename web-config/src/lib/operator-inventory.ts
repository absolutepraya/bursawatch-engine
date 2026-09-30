import { z } from "zod";

const id = z.string().regex(/^[a-z0-9][a-z0-9:_-]{0,127}$/);
const timestamp = z.iso.datetime({ offset: true });
const inventoryVersion = z.literal(1);

export const component = z
  .object({
    inventory_version: inventoryVersion,
    component_id: id,
    kind: z.enum(["source_adapter", "domain_owner", "delivery_service"]),
    display_name: z.string().min(1).max(200),
    capabilities: z.array(id).max(50),
    pipeline_ids: z.array(id).max(50),
    config_resource_ids: z.array(id).max(50),
    related_component_ids: z.array(id).max(100),
    job_ids: z.array(id).max(100),
    source_gate: z
      .object({
        catalog_revision: z.number().int().positive(),
        capabilities: z
          .array(
            z
              .object({
                capability_id: id,
                endpoint_count: z.number().int().nonnegative(),
                enabled_endpoint_count: z.number().int().nonnegative(),
              })
              .strict(),
          )
          .max(100),
      })
      .strict()
      .optional(),
  })
  .strict();

export const componentList = z
  .object({
    inventory_version: inventoryVersion,
    components: z.array(component).max(100),
  })
  .strict()
  .superRefine((value, ctx) => {
    if (value.components.some((row) => row.inventory_version !== value.inventory_version))
      ctx.addIssue({ code: "custom", message: "Mixed component inventory versions" });
    if (new Set(value.components.map((row) => row.component_id)).size !== value.components.length)
      ctx.addIssue({ code: "custom", message: "Duplicate component IDs" });
  });

export const componentActivity = z
  .object({
    component_id: id,
    endpoints: z
      .array(
        z
          .object({
            endpoint_id: id,
            accepted_at: timestamp.nullable(),
            status: z.enum(["unknown", "stale", "observed"]),
            meaning: z.literal("last accepted into Source Inbox"),
          })
          .strict(),
      )
      .max(500),
    pipelines: z
      .array(
        z
          .object({
            pipeline_id: id,
            work_created_at: timestamp.nullable(),
            work_status: z
              .enum([
                "pending",
                "leased",
                "executing",
                "done",
                "dead_letter",
                "suppressed",
                "superseded",
              ])
              .nullable(),
            status: z.enum(["unknown", "stale", "observed"]),
            meaning: z.literal("last pipeline work"),
          })
          .strict(),
      )
      .max(100),
    delivery_status: z.literal("not instrumented"),
  })
  .strict();

const schedule = z
  .object({
    api_version: z.literal(1),
    job_id: id,
    revision: z.number().int().positive(),
    enabled: z.boolean(),
    interval_seconds: z.number().int().min(60).max(86400).multipleOf(60),
    timezone: z.literal("Asia/Jakarta"),
    schedule_sha256: z.string().regex(/^[0-9a-f]{64}$/),
    updated_at: timestamp,
  })
  .strict();

export const operatorJob = z
  .object({
    job_id: id,
    can_edit: z.boolean(),
    watcher_id: id.nullable(),
    component_ids: z.array(id).max(100),
    display_name: z.string().min(1).max(200),
    runtime_job_key: z.string().min(1).max(200),
    schedule_kind: z.enum(["interval", "fixed"]),
    min_interval_seconds: z.number().int().positive().nullable(),
    max_interval_seconds: z.number().int().positive().nullable(),
    schedule: schedule.nullable(),
    reconciliation: z
      .object({
        status: z.enum(["not_connected", "pending", "applied", "error"]),
        applied_revision: z.number().int().positive().nullable(),
        last_error: z.string().max(2000).nullable(),
        effective: z.boolean(),
      })
      .strict()
      .transform(({ last_error, ...safe }) => ({ ...safe, has_error: Boolean(last_error) })),
  })
  .strict()
  .superRefine((row, ctx) => {
    if (row.schedule && row.schedule.job_id !== row.job_id)
      ctx.addIssue({ code: "custom", message: "Schedule identity mismatch" });
    if (
      row.min_interval_seconds !== null &&
      row.max_interval_seconds !== null &&
      row.min_interval_seconds > row.max_interval_seconds
    )
      ctx.addIssue({ code: "custom", message: "Invalid interval bounds" });
  });

export const operatorJobList = z.array(operatorJob).max(500).superRefine((rows, ctx) => {
  if (new Set(rows.map((row) => row.job_id)).size !== rows.length)
    ctx.addIssue({ code: "custom", message: "Duplicate operator job IDs" });
});

const observationSchedule = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("interval"), minutes: z.number().int().min(1).max(1440) }).strict(),
  z.object({ kind: z.literal("cron"), expr: z.string().regex(/^[0-9*/?,\- ]{1,100}$/) }).strict(),
]);
export const observation = z
  .object({
    api_version: z.literal(1),
    identity_kind: z.literal("job"),
    identity_id: id,
    observer_id: id,
    observed_at: timestamp,
    received_at: timestamp,
    status: z.enum(["enabled", "disabled", "stale"]),
    freshness: z.enum(["fresh", "stale"]),
    evidence: z
      .object({
        runtime_job_key: z.string().min(1).max(200),
        enabled: z.boolean(),
        schedule: observationSchedule,
        last_execution: z
          .object({
            at: timestamp.nullable(),
            status: z.enum(["success", "failed", "running", "skipped"]).nullable(),
          })
          .strict(),
      })
      .strict(),
    comparison: z.enum(["match", "mismatch", "not_comparable"]).optional(),
    desired: schedule.nullable().optional(),
    reconciliation: z
      .object({
        status: z.enum(["not_connected", "pending", "applied", "error"]),
        applied_revision: z.number().int().positive().nullable(),
      })
      .strict()
      .optional(),
  })
  .strict()
  .superRefine((row, ctx) => {
    if (row.desired && row.desired.job_id !== row.identity_id)
      ctx.addIssue({ code: "custom", message: "Observation schedule identity mismatch" });
  });

export type OperatorComponent = z.infer<typeof component>;
export type OperatorComponentActivity = z.infer<typeof componentActivity>;
export type OperatorJob = z.infer<typeof operatorJob>;
export type OperatorObservation = z.infer<typeof observation>;
