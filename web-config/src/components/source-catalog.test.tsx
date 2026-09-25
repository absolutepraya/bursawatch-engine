// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { controlBrowser } from "@/lib/control-browser";
import { WorkspaceError } from "@/lib/control-browser";
import type { CatalogConfig, EffectiveCatalog, SourceCatalog } from "@/lib/source-catalog";
import { SourceCatalogView } from "./source-catalog";

const toast = vi.hoisted(() => vi.fn());
vi.mock("./toast-provider", () => ({ useToast: () => toast }));

afterEach(() => {
  cleanup();
  toast.mockReset();
});

const emptyConfig: CatalogConfig = {
  selected_securities: [],
  people_org: [{ id: "my-group", name: "My Group", kind: "group", asset_ref: null }],
  endpoints: [],
  publisher_defaults: [],
  endpoint_overrides: [],
};
function catalog(canEdit: boolean, config = emptyConfig, revision = 1): SourceCatalog {
  return {
    can_edit: canEdit,
    securities: [{ symbol: "TEST", name: "Test Security" }],
    institutions: [],
    people_org: [{ id: "my-group", name: "My Group", kind: "group", tier: 3, asset_ref: null }],
    endpoints: [
      {
        id: "x:test",
        publisher_id: "my-group",
        platform: "x",
        address: "test",
        provider_id: null,
        credential_ref: null,
        system_owned: true,
        verified: true,
      },
    ],
    capabilities: [
      { id: "company_news", label: "Company News", pipeline: "company_news", version: 1 },
    ],
    compatibility: [{ endpoint_id: "x:test", capability_id: "company_news" }],
    config: {
      revision,
      config,
      sha256: "a".repeat(64),
      actor_id: "fixture",
      updated_at: "2026-09-24T00:00:00Z",
    },
  };
}
function effective(revision = 1): EffectiveCatalog {
  return {
    revision,
    updated_at: "2026-09-24T00:00:00Z",
    selected_securities: [],
    subscriptions: [
      {
        endpoint_id: "x:test",
        publisher_id: "my-group",
        platform: "x",
        address: "test",
        provider_id: null,
        credential_ref: null,
        capability_id: "company_news",
        pipeline: "company_news",
        enabled: false,
        verification_status: "verified",
        settings: {},
        source: "unset",
      },
    ],
  };
}
function renderCatalog(request: ReturnType<typeof controlBrowser>) {
  render(<SourceCatalogView request={request} onDirtyChange={vi.fn()} />);
}

describe("SourceCatalogView", () => {
  it("renders backend-confirmed viewers without mutation controls", async () => {
    const request = vi.fn(async (path: string) =>
      path === "source-catalog" ? catalog(false) : effective(),
    ) as unknown as ReturnType<typeof controlBrowser>;
    renderCatalog(request);
    expect(
      await screen.findByText("View access. An admin can change source catalog settings."),
    ).toBeTruthy();
    expect((screen.getByRole("checkbox", { name: /TEST/ }) as HTMLInputElement).disabled).toBe(
      true,
    );
    fireEvent.click(screen.getByRole("tab", { name: "People & Org" }));
    expect(screen.getByRole("heading", { name: "My Group" })).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Add People & Org identity" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Add an endpoint for People & Org" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Apply setting to draft" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Save catalog" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Name" })).toBeNull();
    expect(vi.mocked(request).mock.calls.some(([path]) => path === "source-catalog/config")).toBe(
      false,
    );
  });

  it("locks and preserves a draft when the PUT succeeds but the catalog refresh fails", async () => {
    let catalogReads = 0;
    let putCount = 0;
    let persisted = emptyConfig;
    const request = vi.fn(async (path: string, payload?: unknown) => {
      if (path === "source-catalog/config") {
        putCount++;
        persisted = (payload as { config: CatalogConfig }).config;
        return { revision: 2 };
      }
      if (path === "source-catalog") {
        catalogReads++;
        if (catalogReads === 2) throw new WorkspaceError("unavailable", "Catalog read failed.");
        return catalog(true, persisted, catalogReads > 1 ? 2 : 1);
      }
      return effective(catalogReads > 1 ? 2 : 1);
    }) as unknown as ReturnType<typeof controlBrowser>;
    renderCatalog(request);
    await screen.findByText(/Revision 1/);
    fireEvent.click(screen.getByRole("tab", { name: "People & Org" }));
    fireEvent.change(
      screen.getByRole("group", { name: "Add People & Org identity" }).querySelector("input")!,
      { target: { value: "New Analyst" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Add identity to draft" }));
    fireEvent.click(screen.getByRole("button", { name: "Save catalog" }));
    expect(
      await screen.findByText(
        /save response was received, but the catalog refresh could not be confirmed/i,
      ),
    ).toBeTruthy();
    expect(screen.getByRole("heading", { name: "New Analyst" })).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "Save catalog" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.getByText(/Save acknowledged, refresh unconfirmed/)).toBeTruthy();
    expect(toast).not.toHaveBeenCalled();
    expect(putCount).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Reload current catalog" }));
    await waitFor(() => expect(screen.getByText(/Revision 2 · Saved catalog/)).toBeTruthy());
    expect(screen.queryByText(/refresh could not be confirmed/i)).toBeNull();
    expect(putCount).toBe(1);
    expect(toast).not.toHaveBeenCalled();
  });
});
