// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { controlBrowser } from "@/lib/control-browser";
import { WorkspaceError } from "@/lib/control-browser";
import type { CatalogConfig, EffectiveCatalog, SourceCatalog } from "@/lib/source-catalog";
import { readWorkspaceDraft, setDraftOwner } from "@/lib/workspace-drafts";
import { SourceCatalogView } from "./source-catalog";

const toast = vi.hoisted(() => vi.fn());
vi.mock("./toast-provider", () => ({ useToast: () => toast }));

beforeEach(() => {
  setDraftOwner("fixture-operator");
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
  setDraftOwner(null);
  vi.useRealTimers();
  toast.mockReset();
  vi.restoreAllMocks();
  Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((success, failure) => {
    resolve = success;
    reject = failure;
  });
  return { promise, resolve, reject };
}

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
      {
        id: "swing_chart_context",
        label: "Swing Chart Context",
        pipeline: "swing_chart_context",
        version: 1,
      },
    ],
    compatibility: [
      { endpoint_id: "x:test", capability_id: "company_news", dispatch_group: "x_post_route" },
      {
        endpoint_id: "x:test",
        capability_id: "swing_chart_context",
        dispatch_group: "x_post_route",
      },
    ],
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
        dispatch_group: "x_post_route",
        enabled: false,
        verification_status: "verified",
        settings: {},
        source: "unset",
      },
      {
        endpoint_id: "x:test",
        publisher_id: "my-group",
        platform: "x",
        address: "test",
        provider_id: null,
        credential_ref: null,
        capability_id: "swing_chart_context",
        pipeline: "swing_chart_context",
        dispatch_group: "x_post_route",
        enabled: false,
        verification_status: "verified",
        settings: {},
        source: "unset",
      },
    ],
  };
}
function renderCatalog(request: ReturnType<typeof controlBrowser>) {
  return render(<SourceCatalogView request={request} onDirtyChange={vi.fn()} />);
}

describe("SourceCatalogView", () => {
  it("initializes saved choices, switches scope safely and removes overrides to restore inheritance", async () => {
    let config: CatalogConfig = structuredClone(emptyConfig);
    config.publisher_defaults = [
      { publisher_id: "my-group", capability_id: "company_news", enabled: true, settings: {} },
    ];
    config.endpoint_overrides = [
      { endpoint_id: "x:test", capability_id: "company_news", enabled: false, settings: {} },
    ];
    let revision = 1;
    const request = vi.fn(async (path: string, body?: { config: CatalogConfig }) => {
      if (path === "source-catalog/config") {
        config = body!.config;
        revision += 1;
        return {};
      }
      return path === "source-catalog" ? catalog(true, config, revision) : effective(revision);
    }) as unknown as ReturnType<typeof controlBrowser>;
    renderCatalog(request);
    await screen.findByText(/Revision 1/);
    fireEvent.click(screen.getByRole("tab", { name: "People & Org" }));
    fireEvent.change(screen.getByLabelText("Account or channel"), { target: { value: "x:test" } });
    fireEvent.change(screen.getByLabelText("Content type"), { target: { value: "company_news" } });
    expect(screen.getByLabelText("Include this content")).toHaveProperty("value", "off");
    expect(screen.getByRole("button", { name: "Apply setting to draft" })).toHaveProperty(
      "disabled",
      true,
    );
    fireEvent.change(screen.getByLabelText("Apply to"), { target: { value: "publisher" } });
    expect(screen.getByLabelText("Include this content")).toHaveProperty("value", "on");
    fireEvent.change(screen.getByLabelText("Content type"), {
      target: { value: "swing_chart_context" },
    });
    expect(screen.getByLabelText("Include this content")).toHaveProperty("value", "default");
    fireEvent.change(screen.getByLabelText("Content type"), { target: { value: "company_news" } });
    fireEvent.change(screen.getByLabelText("Apply to"), { target: { value: "endpoint" } });
    fireEvent.change(screen.getByLabelText("Include this content"), { target: { value: "on" } });
    fireEvent.change(screen.getByLabelText("Content type"), {
      target: { value: "swing_chart_context" },
    });
    fireEvent.change(screen.getByLabelText("Content type"), { target: { value: "company_news" } });
    expect(screen.getByLabelText("Include this content")).toHaveProperty("value", "off");
    fireEvent.change(screen.getByLabelText("Include this content"), {
      target: { value: "default" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply setting to draft" }));
    expect(screen.getByRole("group", { name: "Content choices" }).textContent).toContain(
      "Effective draft: On",
    );
    fireEvent.click(screen.getByRole("button", { name: "Save catalog" }));
    await waitFor(() => expect(toast).toHaveBeenCalled());
    expect(config.endpoint_overrides).toEqual([]);
    expect(config.publisher_defaults[0].enabled).toBe(true);
    expect(
      vi.mocked(request).mock.calls.filter(([path]) => path === "source-catalog/config"),
    ).toHaveLength(1);
  });

  it("searches platform identities, opens source-specific accounts and returns focus to the card", async () => {
    const request = vi.fn(async (path: string) =>
      path === "source-catalog" ? catalog(true) : effective(),
    ) as unknown as ReturnType<typeof controlBrowser>;
    renderCatalog(request);
    await screen.findByText(/Revision 1/);
    fireEvent.click(screen.getByRole("tab", { name: "People & Org" }));
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "x test" } });
    const open = screen.getByRole("button", { name: "View accounts and content for My Group" });
    fireEvent.click(open);
    expect(screen.getByLabelText("Account or channel")).toHaveProperty("value", "x:test");
    expect(screen.getByRole("heading", { name: "Accounts and content · My Group" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Back to all sources" }));
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("button", { name: "View accounts and content for My Group" }),
      ),
    );
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "missing identity" } });
    expect(screen.getByText("No people or organizations match these filters.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(
      screen.getByRole("button", { name: "View accounts and content for My Group" }),
    ).toBeTruthy();
  });

  it("marks invalid identity fields and moves focus to the correction", async () => {
    const request = vi.fn(async (path: string) =>
      path === "source-catalog" ? catalog(true) : effective(),
    ) as unknown as ReturnType<typeof controlBrowser>;
    renderCatalog(request);
    await screen.findByText(/Revision 1/);
    fireEvent.click(screen.getByRole("tab", { name: "People & Org" }));
    const add = within(screen.getByRole("group", { name: "Add People & Org identity" }));
    fireEvent.click(add.getByRole("button", { name: "Add identity to draft" }));
    const input = add.getByLabelText("Name");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById(input.getAttribute("aria-describedby")!)?.textContent).toContain(
      "unique name",
    );
    await waitFor(() => expect(document.activeElement).toBe(input));
    expect(vi.mocked(request).mock.calls).toHaveLength(2);
  });

  it("offers X Swing Chart Context while showing its unset state as off", async () => {
    const request = vi.fn(async (path: string) =>
      path === "source-catalog" ? catalog(true) : effective(),
    ) as unknown as ReturnType<typeof controlBrowser>;
    renderCatalog(request);
    await screen.findByText(/Revision 1/);
    fireEvent.click(screen.getByRole("tab", { name: "People & Org" }));
    const setting = screen.getByRole("group", { name: "Content choices" });
    fireEvent.change(setting.querySelector('select[aria-label="Account or channel"]')!, {
      target: { value: "x:test" },
    });
    expect(setting.querySelector('option[value="swing_chart_context"]')?.textContent).toBe(
      "Swing Chart Context",
    );
    fireEvent.change(setting.querySelector('select[aria-label="Content type"]')!, {
      target: { value: "swing_chart_context" },
    });
    expect((screen.getByLabelText("Include this content") as HTMLSelectElement).value).toBe(
      "default",
    );
    expect(setting.textContent).toContain("Unset");
  });
  it("keeps the skeleton visible and counts each catalog read as it settles", async () => {
    const catalogRead = deferred<SourceCatalog>();
    const effectiveRead = deferred<EffectiveCatalog>();
    const request = vi.fn((path: string) =>
      path === "source-catalog" ? catalogRead.promise : effectiveRead.promise,
    ) as unknown as ReturnType<typeof controlBrowser>;
    renderCatalog(request);

    await waitFor(() => expect(vi.mocked(request)).toHaveBeenCalledTimes(2));
    const loading = screen.getByRole("region", { name: "Loading status" });
    expect(loading.querySelector(".workspace-skeleton")).not.toBeNull();
    expect(loading.getAttribute("aria-label")).toBe("Loading status");
    expect(screen.getByRole("progressbar").getAttribute("aria-valuemin")).toBe("0");
    expect(screen.getByRole("progressbar").getAttribute("aria-valuemax")).toBe("2");
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("0");
    expect(screen.getByText("0 of 2 requests finished.")).toBeTruthy();

    await act(async () => catalogRead.resolve(catalog(false)));
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("1");
    expect(screen.getByText("1 of 2 requests finished.")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Loading status" })).toBeTruthy();
    expect(screen.queryByRole("tab", { name: "Securities" })).toBeNull();

    await act(async () => effectiveRead.resolve(effective()));
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Loading status" })).toBeNull(),
    );
    expect(screen.getByRole("tab", { name: "Securities" })).toBeTruthy();
  });

  it("shows safe per-request details during a long read and recovers from a failed read", async () => {
    vi.useFakeTimers();
    const catalogRead = deferred<SourceCatalog>();
    const effectiveRead = deferred<EffectiveCatalog>();
    const request = vi.fn((path: string) =>
      path === "source-catalog" ? catalogRead.promise : effectiveRead.promise,
    ) as unknown as ReturnType<typeof controlBrowser>;
    renderCatalog(request);
    await act(async () => Promise.resolve());
    expect(vi.mocked(request)).toHaveBeenCalledTimes(2);

    await act(async () => vi.advanceTimersByTime(8_000));
    const loading = screen.getByRole("region", { name: "Loading status" });
    expect(screen.getByText("This is taking longer than usual")).toBeTruthy();
    expect(loading.querySelector("details")?.textContent).toContain("Request details");

    await act(async () =>
      catalogRead.reject(new WorkspaceError("unavailable", "PRIVATE_FIXTURE_PROVIDER_DIAGNOSTIC")),
    );
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("1");
    expect(loading.querySelector("details")?.textContent).toMatch(/could not be loaded|failed/i);
    expect(document.body.textContent).not.toContain("PRIVATE_FIXTURE_PROVIDER_DIAGNOSTIC");

    await act(async () => effectiveRead.resolve(effective()));
    expect(screen.queryByRole("region", { name: "Loading status" })).toBeNull();
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(document.body.textContent).not.toContain("PRIVATE_FIXTURE_PROVIDER_DIAGNOSTIC");
    expect(screen.getByRole("button", { name: "Reload current catalog" })).toBeTruthy();
  });

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
    expect(screen.queryByRole("group", { name: "Add an account or channel" })).toBeNull();
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
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Reload current catalog" }));
    await waitFor(() => expect(screen.getByText(/Revision 2 · Saved catalog/)).toBeTruthy());
    expect(screen.queryByText(/refresh could not be confirmed/i)).toBeNull();
    expect(putCount).toBe(1);
    expect(toast).not.toHaveBeenCalled();
  });
});

async function editCatalog(
  request = vi.fn(async (path: string) =>
    path === "source-catalog" ? catalog(true) : effective(),
  ) as unknown as ReturnType<typeof controlBrowser>,
) {
  const onDirtyChange = vi.fn();
  const view = render(<SourceCatalogView request={request} onDirtyChange={onDirtyChange} />);
  await screen.findByText(/Revision 1/);
  fireEvent.click(screen.getByRole("tab", { name: "People & Org" }));
  fireEvent.change(
    screen.getByRole("group", { name: "Add People & Org identity" }).querySelector("input")!,
    {
      target: { value: "Unsaved Analyst" },
    },
  );
  fireEvent.click(screen.getByRole("button", { name: "Add identity to draft" }));
  return { ...view, request, onDirtyChange };
}

it("warns before leaving a source draft and removes the warning on unmount", async () => {
  const { unmount, onDirtyChange } = await editCatalog();
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  const beforeUnload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(beforeUnload);
  expect(beforeUnload.defaultPrevented).toBe(true);
  const link = document.createElement("a");
  link.href = "/workspace/jobs";
  document.body.append(link);
  try {
    expect(fireEvent.click(link)).toBe(false);
    expect(confirm).toHaveBeenCalledOnce();
    expect(screen.getByRole("heading", { name: "Unsaved Analyst" })).toBeTruthy();
  } finally {
    link.remove();
  }
  unmount();
  expect(onDirtyChange).toHaveBeenLastCalledWith(false);
  const cleanUnload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(cleanUnload);
  expect(cleanUnload.defaultPrevented).toBe(false);
});

it("preserves a draft when catalog reload is declined and discards only after confirmation", async () => {
  const { request } = await editCatalog();
  // Adding an empty identity exposes the local validation error and reload action.
  fireEvent.click(screen.getByRole("button", { name: "Add identity to draft" }));
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  fireEvent.click(screen.getByRole("button", { name: "Reload current catalog" }));
  await act(async () => Promise.resolve());
  expect(confirm).toHaveBeenCalledOnce();
  expect(vi.mocked(request)).toHaveBeenCalledTimes(2);
  expect(screen.getByRole("heading", { name: "Unsaved Analyst" })).toBeTruthy();
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Reload current catalog" }));
  await waitFor(() => expect(vi.mocked(request)).toHaveBeenCalledTimes(4));
  await waitFor(() =>
    expect(screen.queryByRole("heading", { name: "Unsaved Analyst" })).toBeNull(),
  );
  const beforeUnload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(beforeUnload);
  expect(beforeUnload.defaultPrevented).toBe(false);
});

it("restores source drafts across history visits and drops them after explicit reload", async () => {
  const first = await editCatalog();
  first.unmount();
  renderCatalog(first.request);
  expect(await screen.findByRole("heading", { name: "Unsaved Analyst" })).toBeTruthy();
  expect(screen.getByText(/unsaved change/i)).toBeTruthy();
  expect((screen.getByRole("button", { name: "Save catalog" }) as HTMLButtonElement).disabled).toBe(
    false,
  );
  fireEvent.click(screen.getByRole("button", { name: "Add identity to draft" }));
  vi.spyOn(window, "confirm").mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Reload current catalog" }));
  await waitFor(() =>
    expect(screen.queryByRole("heading", { name: "Unsaved Analyst" })).toBeNull(),
  );
  expect(readWorkspaceDraft("source-catalog")).toBeNull();
});

it("locks a restored source draft when the server revision changed", async () => {
  const first = await editCatalog();
  first.unmount();
  const request = vi.fn(async (path: string) =>
    path === "source-catalog" ? catalog(true, emptyConfig, 2) : effective(2),
  ) as unknown as ReturnType<typeof controlBrowser>;
  renderCatalog(request);
  expect(await screen.findByRole("heading", { name: "Unsaved Analyst" })).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toMatch(/catalog changed while you were away/i);
  expect((screen.getByRole("button", { name: "Save catalog" }) as HTMLButtonElement).disabled).toBe(
    true,
  );
  fireEvent.click(screen.getByRole("button", { name: "Save catalog" }));
  expect(vi.mocked(request).mock.calls.some(([path]) => path === "source-catalog/config")).toBe(
    false,
  );
});

it.each(["auth", "forbidden"])("clears the retained catalog draft after %s", async (code) => {
  const first = await editCatalog();
  first.unmount();
  const denied = vi.fn(async () => {
    throw new WorkspaceError(code, "Access denied");
  }) as unknown as ReturnType<typeof controlBrowser>;
  const visit = renderCatalog(denied);
  await screen.findByRole("alert");
  expect(readWorkspaceDraft("source-catalog")).toBeNull();
  visit.unmount();
  renderCatalog(first.request);
  await screen.findByText(/Revision 1/);
  fireEvent.click(screen.getByRole("tab", { name: "People & Org" }));
  expect(screen.queryByRole("heading", { name: "Unsaved Analyst" })).toBeNull();
});

it("does not restore source drafts after losing edit access", async () => {
  const first = await editCatalog();
  first.unmount();
  const viewer = vi.fn(async (path: string) =>
    path === "source-catalog" ? catalog(false) : effective(),
  ) as unknown as ReturnType<typeof controlBrowser>;
  renderCatalog(viewer);
  await screen.findByText("View access. An admin can change source catalog settings.");
  fireEvent.click(screen.getByRole("tab", { name: "People & Org" }));
  expect(screen.queryByRole("heading", { name: "Unsaved Analyst" })).toBeNull();
  expect(readWorkspaceDraft("source-catalog")).toBeNull();
});

it("retains an unfinished save as locked and ignores its late completion after leaving", async () => {
  const pending = deferred<{ revision: number }>();
  const request = vi.fn((path: string) => {
    if (path === "source-catalog/config") return pending.promise;
    return Promise.resolve(path === "source-catalog" ? catalog(true) : effective());
  }) as unknown as ReturnType<typeof controlBrowser>;
  const first = await editCatalog(request);
  fireEvent.click(screen.getByRole("button", { name: "Save catalog" }));
  await screen.findByRole("button", { name: "Saving…" });
  first.unmount();
  renderCatalog(request);
  await screen.findByRole("heading", { name: "Unsaved Analyst" });
  expect(screen.getByRole("alert").textContent).toMatch(
    /previous catalog save has not been confirmed/i,
  );
  expect((screen.getByRole("button", { name: "Save catalog" }) as HTMLButtonElement).disabled).toBe(
    true,
  );
  await act(async () => pending.resolve({ revision: 2 }));
  expect(toast).not.toHaveBeenCalled();
  expect(readWorkspaceDraft("source-catalog")).not.toBeNull();
  expect(vi.mocked(request)).toHaveBeenCalledTimes(5);
});

it("does not discard a retained draft when a failed return read is reloaded without confirmation", async () => {
  const first = await editCatalog();
  first.unmount();
  const unavailable = vi.fn(async () => {
    throw new WorkspaceError("unavailable", "Read unavailable");
  }) as unknown as ReturnType<typeof controlBrowser>;
  renderCatalog(unavailable);
  await screen.findByRole("alert");
  expect(readWorkspaceDraft("source-catalog")).not.toBeNull();
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  fireEvent.click(screen.getByRole("button", { name: "Reload current catalog" }));
  expect(confirm).toHaveBeenCalledOnce();
  expect(vi.mocked(unavailable)).toHaveBeenCalledTimes(2);
  expect(readWorkspaceDraft("source-catalog")).not.toBeNull();
});

it.each(["auth", "forbidden"])("clears a source draft when saving returns %s", async (code) => {
  const request = vi.fn(async (path: string) => {
    if (path === "source-catalog/config") throw new WorkspaceError(code, "Access denied");
    return path === "source-catalog" ? catalog(true) : effective();
  }) as unknown as ReturnType<typeof controlBrowser>;
  await editCatalog(request);
  expect(readWorkspaceDraft("source-catalog")).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Save catalog" }));
  await screen.findByRole("alert");
  expect(readWorkspaceDraft("source-catalog")).toBeNull();
  expect(screen.queryByRole("heading", { name: "Unsaved Analyst" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Save catalog" })).toBeNull();
});

it("clears retained source changes after a confirmed save", async () => {
  let saved = emptyConfig;
  let revision = 1;
  const request = vi.fn(async (path: string, payload?: unknown) => {
    if (path === "source-catalog/config") {
      saved = (payload as { config: CatalogConfig }).config;
      return { revision: ++revision };
    }
    return path === "source-catalog" ? catalog(true, saved, revision) : effective(revision);
  }) as unknown as ReturnType<typeof controlBrowser>;
  await editCatalog(request);
  expect(readWorkspaceDraft("source-catalog")).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Save catalog" }));
  await waitFor(() => expect(toast).toHaveBeenCalledOnce());
  expect(readWorkspaceDraft("source-catalog")).toBeNull();
  expect(screen.getByRole("heading", { name: "Unsaved Analyst" })).toBeTruthy();
  expect(screen.getByText(/Revision 2 · Saved catalog/)).toBeTruthy();
});
