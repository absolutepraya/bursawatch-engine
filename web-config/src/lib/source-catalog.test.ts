import { describe, expect, it } from "vitest";
import {
  catalogWrite,
  compatibleCapabilities,
  effectiveChoice,
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
  compatibility: [{ endpoint_id: "x:firm", capability_id: "company_news" }],
  config: {
    revision: 1,
    config,
    sha256: "a".repeat(64),
    actor_id: "baseline",
    updated_at: "2026-09-24T00:00:00Z",
  },
} as SourceCatalog;
describe("catalog settings", () => {
  it("shows only compatible endpoint capabilities", () =>
    expect(compatibleCapabilities(catalog, "x:firm").map((item) => item.id)).toEqual([
      "company_news",
    ]));
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
