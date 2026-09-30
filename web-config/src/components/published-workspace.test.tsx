// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PublishedWorkspace } from "./published-workspace";
import { ToastProvider } from "./toast-provider";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

afterEach(cleanup);

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
