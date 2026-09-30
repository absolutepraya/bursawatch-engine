// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { Publication, PublicationCoverage } from "@/lib/publications";
import { PublishedList } from "./published-list";

afterEach(cleanup);

const item = {
  publication_id: "a".repeat(64),
  type: "swing_context",
  title: "Synthetic swing context",
  owner_id: "bursawatch-x-account-watch",
  ticker: "TEST",
  source_name: "Synthetic source",
  delivery_confirmed_at: "2026-09-29T07:02:00+00:00",
} as Publication;
const coverage: PublicationCoverage = {
  cutover: { boundary: "2026-09-29T07:01:00+00:00", owner_ids: ["bursawatch-x-account-watch"] },
  overall_status: "incomplete",
  owners: [{ owner_id: "bursawatch-x-account-watch", status: "unknown", checkpoint: null }],
};

it("labels context separately and warns when a publisher checkpoint is unknown", () => {
  render(
    <PublishedList
      items={[item]}
      coverage={coverage}
      cursor={null}
      filter={{ group: "all", type: "all", ticker: "", source: "" }}
      loading={false}
      error=""
      onFilter={vi.fn()}
      onMore={vi.fn()}
      onSelect={vi.fn()}
    />,
  );
  expect(screen.getAllByText("Swing context")).toHaveLength(2);
  expect(screen.getByText(/Coverage is incomplete or unverified/)).toBeTruthy();
  fireEvent.click(screen.getByText("Publisher coverage"));
  expect(screen.getByText("unknown")).toBeTruthy();
});

it("offers an explicit next page and keeps the empty state bounded to the cutover", () => {
  const onMore = vi.fn();
  render(
    <PublishedList
      items={[]}
      coverage={coverage}
      cursor="next-page"
      filter={{ group: "all", type: "all", ticker: "", source: "" }}
      loading={false}
      error=""
      onFilter={vi.fn()}
      onMore={onMore}
      onSelect={vi.fn()}
    />,
  );
  expect(screen.getByText(/No confirmed publications in this view since the cutover/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Load more" }));
  expect(onMore).toHaveBeenCalledOnce();
});
