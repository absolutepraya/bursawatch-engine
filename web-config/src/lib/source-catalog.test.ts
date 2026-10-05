import { describe, expect, it } from "vitest";
import {
  catalogWrite,
  compatibleCapabilities,
  effectiveChoice,
  effectiveCatalog,
  sourceCatalog,
  type SourceCatalog,
} from "./source-catalog";

const config = {
  selected_securities: [],
  people_org: [],
  endpoints: [],
  publisher_defaults: [
    { publisher_id: "firm", capability_id: "company_news", enabled: true, settings: {} },
  ],
  endpoint_overrides: [
    { endpoint_id: "x:firm", capability_id: "company_news", enabled: false, settings: {} },
  ],
};
const catalog = {
  can_edit: true,
  securities: [],
  institutions: [{ id: "firm", name: "Firm", tier: 1, asset_ref: null }],
  people_org: [],
  endpoints: [
    {
      id: "x:firm",
      publisher_id: "firm",
      platform: "x",
      address: "firm",
      provider_id: null,
      credential_ref: null,
      system_owned: true,
      verified: true,
    },
  ],
  capabilities: [
    { id: "company_news", label: "Company news", pipeline: "company_news", version: 1 },
    { id: "trading_plans", label: "Trading plans", pipeline: "swing_plan", version: 1 },
  ],
  compatibility: [{ endpoint_id: "x:firm", capability_id: "company_news", dispatch_group: "x_post_route" }],
  config: {
    revision: 1,
    config,
    sha256: "a".repeat(64),
    actor_id: "baseline",
    updated_at: "2026-09-24T00:00:00Z",
  },
} as SourceCatalog;
describe("catalog settings", () => {
  it.each([
    "instagram:synthetic.research",
    "whatsapp:0029SyntheticMixedCase",
    "a".repeat(128),
  ])(
    "preserves bounded endpoint identity %s in the catalog projection",
    (endpointId) => {
      const parsed = sourceCatalog.parse({
        ...catalog,
        endpoints: [{ ...catalog.endpoints[0], id: endpointId }],
        compatibility: [
          { ...catalog.compatibility[0], endpoint_id: endpointId },
        ],
        config: {
          ...catalog.config,
          config: {
            ...config,
            endpoint_overrides: [{ ...config.endpoint_overrides[0], endpoint_id: endpointId }],
          },
        },
      });
      expect(parsed.endpoints[0].id).toBe(endpointId);
      expect(parsed.compatibility[0].endpoint_id).toBe(endpointId);
      expect(parsed.config.config.endpoint_overrides[0].endpoint_id).toBe(endpointId);
      const write = catalogWrite.parse({ expected_revision: 1, config: parsed.config.config });
      expect(write.config.endpoint_overrides[0].endpoint_id).toBe(endpointId);
    },
  );
  it.each([
    "",
    "a".repeat(129),
    "instagram:bad/handle",
    "whatsapp:bad?query",
    "x:bad handle",
    "x:bad\u0000handle",
    "x:badé",
    "x:firm\n",
  ])("rejects malformed saved override identity %j on reads and writes", (endpointId) => {
    const invalidConfig = {
      ...config,
      endpoint_overrides: [{ ...config.endpoint_overrides[0], endpoint_id: endpointId }],
    };
    expect(sourceCatalog.safeParse({
      ...catalog,
      config: { ...catalog.config, config: invalidConfig },
    }).success).toBe(false);
    expect(catalogWrite.safeParse({ expected_revision: 1, config: invalidConfig }).success).toBe(false);
  });
  it.each(["", "a".repeat(129), "instagram:bad/handle", "whatsapp:bad?query"])(
    "rejects invalid endpoint identity %j in catalog projections",
    (endpointId) => {
      expect(
        sourceCatalog.safeParse({
          ...catalog,
          endpoints: [{ ...catalog.endpoints[0], id: endpointId }],
        }).success,
      ).toBe(false);
    },
  );
  it("shows only compatible endpoint capabilities", () =>
    expect(compatibleCapabilities(catalog, "x:firm").map((item) => item.id)).toEqual([
      "company_news",
    ]));
  it("accepts grouped X Swing compatibility and an unset effective subscription", () => {
    const xCatalog = {
      ...catalog,
      capabilities: [...catalog.capabilities, { id: "swing_chart_context", label: "Swing Chart Context", pipeline: "swing_chart_context", version: 1 }],
      compatibility: [
        { endpoint_id: "x:firm", capability_id: "company_news", dispatch_group: "x_post_route" },
        { endpoint_id: "x:firm", capability_id: "swing_chart_context", dispatch_group: "x_post_route" },
      ],
    };
    expect(sourceCatalog.parse(xCatalog).compatibility[1].dispatch_group).toBe("x_post_route");
    expect(compatibleCapabilities(xCatalog, "x:firm").map((item) => item.id)).toEqual(["company_news", "swing_chart_context"]);
    expect(effectiveCatalog.parse({
      revision: 1, updated_at: "2026-09-24T00:00:00Z", selected_securities: [],
      subscriptions: [{ endpoint_id: "x:firm", publisher_id: "firm", platform: "x", address: "firm", provider_id: null, credential_ref: null, capability_id: "swing_chart_context", pipeline: "swing_chart_context", dispatch_group: "x_post_route", enabled: false, verification_status: "verified", settings: {}, source: "unset" }],
    }).subscriptions[0].dispatch_group).toBe("x_post_route");
    expect(effectiveChoice(config, "firm", "x:firm", "swing_chart_context")).toEqual({ source: "Unset", enabled: false });
    expect(sourceCatalog.safeParse({ ...xCatalog, compatibility: [{ ...xCatalog.compatibility[0], dispatch_group: "Invalid Group" }] }).success).toBe(false);
  });
  it("resolves endpoint overrides before publisher defaults", () => {
    expect(effectiveChoice(config, "firm", "x:firm", "company_news")).toEqual({
      source: "Endpoint override",
      enabled: false,
    });
    expect(
      effectiveChoice({ ...config, endpoint_overrides: [] }, "firm", "x:firm", "company_news"),
    ).toEqual({ source: "Publisher default", enabled: true });
  });
  it("rejects unreviewed settings and malformed endpoints before the proxy write", () => {
    expect(
      catalogWrite.safeParse({
        expected_revision: 1,
        config: {
          ...config,
          endpoints: [
            {
              id: "custom",
              publisher_id: "firm",
              platform: "rss",
              address: "url",
              credential_ref: null,
            },
          ],
        },
      }).success,
    ).toBe(false);
    expect(
      catalogWrite.safeParse({
        expected_revision: 1,
        config: {
          ...config,
          endpoint_overrides: [{ ...config.endpoint_overrides[0], settings: { secret: "bad" } }],
        },
      }).success,
    ).toBe(false);
  });
});
