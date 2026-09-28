import { z } from "zod";

const id = z.string().regex(/^[a-z0-9][a-z0-9-]{1,63}$/);
const dispatchGroup = z.string().regex(/^[a-z][a-z0-9_]{0,63}$/).nullable();
const asset = z
  .object({
    url: z.url().startsWith("https://"),
    kind: z.enum(["logo", "profile_picture", "banner"]),
  })
  .strict()
  .nullable();
const person = z
  .object({
    id,
    name: z.string().trim().min(1).max(120),
    kind: z.enum(["person", "group", "community"]),
    asset_ref: asset,
  })
  .strict();
const endpoint = z
  .object({
    id,
    publisher_id: z.string(),
    platform: z.enum(["telegram", "x", "instagram", "whatsapp"]),
    address: z.string().regex(/^[A-Za-z0-9_.]{1,64}$/),
    credential_ref: z
      .string()
      .regex(/^credential:[a-z0-9][a-z0-9-]{1,63}$/)
      .nullable(),
  })
  .strict();
const setting = z.object({
  capability_id: z.string(),
  enabled: z.boolean(),
  settings: z.object({}).strict(),
});
export const catalogConfig = z
  .object({
    selected_securities: z.array(z.string()).max(500),
    people_org: z.array(person).max(500),
    endpoints: z.array(endpoint).max(500),
    publisher_defaults: z.array(setting.extend({ publisher_id: z.string() }).strict()).max(500),
    endpoint_overrides: z.array(setting.extend({ endpoint_id: z.string() }).strict()).max(500),
  })
  .strict();
export const catalogWrite = z
  .object({ expected_revision: z.number().int().positive(), config: catalogConfig })
  .strict();
export const catalogRevision = z.object({
  revision: z.number().int().positive(),
  config: catalogConfig,
  sha256: z.string().regex(/^[0-9a-f]{64}$/),
  actor_id: z.string(),
  updated_at: z.string(),
});
const publisher = z.object({
  id: z.string(),
  name: z.string(),
  tier: z.number(),
  kind: z.string().nullable().optional(),
  asset_ref: asset,
});
const registryEndpoint = z.object({
  id: z.string(),
  publisher_id: z.string(),
  platform: z.string(),
  address: z.string(),
  provider_id: z.string().nullable(),
  credential_ref: z.string().nullable(),
  system_owned: z.boolean(),
  verified: z.boolean(),
});
export const sourceCatalog = z.object({
  can_edit: z.boolean(),
  securities: z.array(z.object({ symbol: z.string(), name: z.string() }).passthrough()).max(500),
  institutions: z.array(publisher).max(500),
  people_org: z.array(publisher).max(500),
  endpoints: z.array(registryEndpoint).max(1000),
  capabilities: z
    .array(
      z.object({ id: z.string(), label: z.string(), pipeline: z.string(), version: z.number() }),
    )
    .max(100),
  compatibility: z
    .array(z.object({ endpoint_id: z.string(), capability_id: z.string(), dispatch_group: dispatchGroup }))
    .max(5000),
  config: catalogRevision,
});
export const effectiveCatalog = z.object({
  revision: z.number().int().positive(),
  updated_at: z.string(),
  selected_securities: z.array(z.string()),
  subscriptions: z
    .array(
      z.object({
        endpoint_id: z.string(),
        publisher_id: z.string(),
        platform: z.string(),
        address: z.string(),
        provider_id: z.string().nullable(),
        credential_ref: z.string().nullable(),
        capability_id: z.string(),
        pipeline: z.string(),
        dispatch_group: dispatchGroup,
        enabled: z.boolean(),
        verification_status: z.enum(["verified", "pending"]),
        settings: z.record(z.string(), z.unknown()),
        source: z.enum(["endpoint_override", "publisher_default", "unset"]),
      }),
    )
    .max(5000),
});
export type SourceCatalog = z.infer<typeof sourceCatalog>;
export type CatalogConfig = z.infer<typeof catalogConfig>;
export type EffectiveCatalog = z.infer<typeof effectiveCatalog>;

export function compatibleCapabilities(catalog: SourceCatalog, endpointId: string) {
  const ids = new Set(
    catalog.compatibility
      .filter((pair) => pair.endpoint_id === endpointId)
      .map((pair) => pair.capability_id),
  );
  return catalog.capabilities.filter((capability) => ids.has(capability.id));
}

export function effectiveChoice(
  config: CatalogConfig,
  publisherId: string,
  endpointId: string,
  capabilityId: string,
) {
  const override = config.endpoint_overrides.find(
    (entry) => entry.endpoint_id === endpointId && entry.capability_id === capabilityId,
  );
  const inherited = config.publisher_defaults.find(
    (entry) => entry.publisher_id === publisherId && entry.capability_id === capabilityId,
  );
  return {
    source: override ? "Endpoint override" : inherited ? "Publisher default" : "Unset",
    enabled: (override ?? inherited)?.enabled ?? false,
  };
}
