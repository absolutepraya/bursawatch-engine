// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { WorkspaceError } from "@/lib/control-browser";
import { PublishedWorkspace } from "./published-workspace";
import { ToastProvider } from "./toast-provider";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
});

const coverage = {
  cutover: { boundary: "2026-09-29T00:00:00+00:00", owner_ids: ["bursawatch-tg-market-news"] },
  overall_status: "incomplete",
  owners: [{ owner_id: "bursawatch-tg-market-news", status: "unknown", checkpoint: null }],
};

it("sends published filters to the API before paging and forwards the returned cursor", async () => {
  const calls: string[] = [];
  const request = async <T,>(path: string): Promise<T> => {
    calls.push(path);
    if (path === "publications/coverage") return coverage as T;
    if (path.startsWith("publications?"))
      return {
        items: [],
        next_cursor: calls.some((call) => call.includes("cursor=next")) ? null : "next",
      } as T;
    throw new Error("Unexpected route");
  };
  render(
    <ToastProvider>
      <PublishedWorkspace request={request} />
    </ToastProvider>,
  );

  fireEvent.change(screen.getByLabelText("Type"), { target: { value: "broker_swing_update" } });
  fireEvent.change(screen.getByLabelText("Route"), { target: { value: "swing_board" } });
  fireEvent.change(screen.getByLabelText("Delivered from"), { target: { value: "2026-09-29" } });
  fireEvent.change(screen.getByLabelText("Delivered to"), { target: { value: "2026-09-30" } });
  fireEvent.click(screen.getByRole("button", { name: "Swing" }));
  fireEvent.change(screen.getByLabelText("Ticker"), { target: { value: "test" } });
  fireEvent.change(screen.getByLabelText("Source"), { target: { value: "Broker" } });

  await waitFor(() =>
    expect(
      calls.some((path) => {
        const query = new URLSearchParams(path.split("?")[1]);
        return (
          query.get("group") === "swing" &&
          query.get("type") === "broker_swing_update" &&
          query.get("route") === "swing_board" &&
          query.get("date_from") === "2026-09-28T17:00:00.000Z" &&
          query.get("date_to") === "2026-09-30T16:59:59.999Z" &&
          query.get("ticker") === "TEST" &&
          query.get("source") === "Broker"
        );
      }),
    ).toBe(true),
  );
  fireEvent.click(screen.getByRole("button", { name: "Load more" }));
  await waitFor(() =>
    expect(
      calls.some((path) => new URLSearchParams(path.split("?")[1]).get("cursor") === "next"),
    ).toBe(true),
  );
});

const privateItem = {
  publication_id: "a".repeat(64),
  type: "swing_context",
  title: "Synthetic private publication",
  owner_id: "bursawatch-x-account-watch",
  ticker: "TEST",
  source_name: "Synthetic source",
  delivery_confirmed_at: "2026-09-29T07:02:00+00:00",
};

it.each(["auth", "forbidden"])(
  "clears loaded publications and coverage after %s on the next page",
  async (code) => {
    const request = async <T,>(path: string): Promise<T> => {
      if (path === "publications/coverage") return coverage as T;
      if (path.includes("cursor=")) throw new WorkspaceError(code, "Access denied");
      return { items: [privateItem], next_cursor: "next" } as T;
    };
    render(<PublishedWorkspace request={request} />);
    await screen.findByText(privateItem.title);
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await waitFor(() => expect(screen.queryByText(privateItem.title)).toBeNull());
    expect(screen.queryByText("Publisher coverage")).toBeNull();
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
    expect(screen.getByRole("alert").textContent).toMatch(/session has expired|do not have access/);
  },
);

it("keeps coverage failure separate from page loading and retries coverage independently", async () => {
  let coverageReads = 0;
  let pageReads = 0;
  const request = async <T,>(path: string): Promise<T> => {
    if (path === "publications/coverage") {
      if (++coverageReads === 1) throw new WorkspaceError("unavailable", "Coverage read failed");
      return coverage as T;
    }
    pageReads++;
    return { items: [privateItem], next_cursor: "next" } as T;
  };
  render(<PublishedWorkspace request={request} />);
  await screen.findByText(privateItem.title);
  expect(screen.queryByText("Publication feed not started")).toBeNull();
  expect(screen.getByText("Publisher coverage unavailable")).toBeTruthy();
  expect(screen.getByText("Coverage read failed")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Load more" }));
  await waitFor(() => expect(pageReads).toBe(2));
  expect(screen.getByText("Coverage read failed")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Retry publisher coverage" }));
  await screen.findByText(/Published since/);
  expect(screen.queryByText("Coverage read failed")).toBeNull();
  expect(pageReads).toBe(2);
  expect(coverageReads).toBe(2);
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

it("ignores a late coverage response after access is lost", async () => {
  const pendingCoverage = deferred<typeof coverage>();
  let coverageSignal: AbortSignal | undefined;
  const request = async <T,>(
    path: string,
    _payload?: unknown,
    options?: { signal?: AbortSignal },
  ): Promise<T> => {
    if (path === "publications/coverage") {
      coverageSignal = options?.signal;
      return pendingCoverage.promise as Promise<T>;
    }
    if (path.includes("cursor=")) throw new WorkspaceError("auth", "Access denied");
    return { items: [privateItem], next_cursor: "next" } as T;
  };
  const onSignIn = vi.fn();
  render(<PublishedWorkspace request={request} onSignIn={onSignIn} />);
  await screen.findByText(privateItem.title);
  expect(screen.getByText("Loading publisher coverage…")).toBeTruthy();
  expect(screen.queryByText("Publication feed not started")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Load more" }));
  await screen.findByText("Your session has expired. Sign in again.");
  expect(coverageSignal?.aborted).toBe(true);
  await act(async () => pendingCoverage.resolve(coverage));
  expect(screen.queryByText(/Published since/)).toBeNull();
  expect(screen.queryByText(privateItem.title)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Sign in again" }));
  expect(onSignIn).toHaveBeenCalledOnce();
});

it("clears prior records on coverage permission failure and rereads after explicit retry", async () => {
  const pendingCoverage = deferred<typeof coverage>();
  let coverageReads = 0;
  let pageReads = 0;
  const request = async <T,>(path: string): Promise<T> => {
    if (path === "publications/coverage") {
      return (
        ++coverageReads === 1 ? pendingCoverage.promise : Promise.resolve(coverage)
      ) as Promise<T>;
    }
    pageReads++;
    return { items: [privateItem], next_cursor: null } as T;
  };
  render(<PublishedWorkspace request={request} />);
  await screen.findByText(privateItem.title);
  await act(async () => pendingCoverage.reject(new WorkspaceError("forbidden", "Access denied")));
  expect(screen.queryByText(privateItem.title)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByText(privateItem.title);
  await screen.findByText(/Published since/);
  expect(pageReads).toBe(2);
  expect(coverageReads).toBe(2);
});

it("treats a detail authentication failure as lost access to the whole feed", async () => {
  window.history.replaceState({}, "", "/workspace/published?publication=fixture");
  const pendingCoverage = deferred<typeof coverage>();
  const request = async <T,>(path: string): Promise<T> => {
    if (path === "publications/coverage") return pendingCoverage.promise as Promise<T>;
    if (path === "publications/fixture") throw new WorkspaceError("auth", "Access denied");
    return { items: [privateItem], next_cursor: null } as T;
  };
  const view = render(<PublishedWorkspace request={request} />);
  await screen.findByText("Your session has expired. Sign in again.");
  await act(async () => pendingCoverage.resolve(coverage));
  window.history.replaceState({}, "", "/workspace/published");
  // Changing the selected URL must not expose records after the failed detail read.
  view.rerender(<PublishedWorkspace request={request} />);
  expect(screen.queryByText(privateItem.title)).toBeNull();
  expect(screen.queryByText(/Published since/)).toBeNull();
});

it("preserves loaded records and coverage on a transient pagination failure", async () => {
  const request = async <T,>(path: string): Promise<T> => {
    if (path === "publications/coverage") return coverage as T;
    if (path.includes("cursor=")) throw new WorkspaceError("timeout", "Page timed out");
    return { items: [privateItem], next_cursor: "next" } as T;
  };
  render(<PublishedWorkspace request={request} />);
  await screen.findByText(privateItem.title);
  fireEvent.click(screen.getByRole("button", { name: "Load more" }));
  await screen.findByText("Page timed out");
  expect(screen.getByText(privateItem.title)).toBeTruthy();
  expect(screen.getByText(/Published since/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Load more" })).toBeTruthy();
});
