// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { PublicationDetail as Detail } from "@/lib/publications";
import { PublishedDetail } from "./published-detail";

afterEach(cleanup);

it("shows exact confirmed legs and broker levels only for a broker plan", () => {
  const detail = {
    publication_id: "a".repeat(64),
    versions: [
      {
        publication_id: "a".repeat(64),
        owner_id: "bursawatch-tg-phintraco-swing",
        type: "broker_swing_plan",
        title: "Synthetic broker setup",
        source_name: "Synthetic broker",
        ticker: "TEST",
        version: 1,
        delivery_confirmed_at: "2026-09-29T07:02:00+00:00",
        source_published_at: "2026-09-29T07:00:00+00:00",
        market_data_as_of: null,
        source_url: "https://example.test/source",
        parent_publication_id: null,
        broker_levels: {
          entry: "100 to 105",
          stop: "95",
          targets: ["120", "130"],
          units: "IDR per share",
          attribution: "Synthetic broker",
        },
        legs: [
          {
            operation_key: "synthetic-op",
            destination: "123456789012345678",
            text: "Exact delivered plan text",
            attachments: [],
            message_url:
              "https://discord.com/channels/123456789012345678/123456789012345678/987654321098765432",
          },
        ],
      },
    ],
    linked: [],
  } as unknown as Detail;
  render(<PublishedDetail detail={detail} onBack={vi.fn()} onSelect={vi.fn()} />);
  expect(screen.getByText("Broker swing plan · Phintraco Swing")).toBeTruthy();
  expect(screen.getByText("Exact delivered plan text")).toBeTruthy();
  expect(screen.getByText("100 to 105")).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "Open confirmed Discord message" }).getAttribute("href"),
  ).toContain("987654321098765432");
});

it("links a Board update to its parent publication", () => {
  const parent = "b".repeat(64);
  const onSelect = vi.fn();
  const detail = {
    publication_id: "a".repeat(64),
    versions: [
      {
        publication_id: "a".repeat(64),
        owner_id: "bursawatch-dc-swing-board",
        type: "swing_board_update",
        title: "Synthetic Board reply",
        source_name: "Swing Board",
        ticker: null,
        version: 1,
        delivery_confirmed_at: "2026-09-29T07:02:00+00:00",
        source_published_at: null,
        market_data_as_of: null,
        source_url: null,
        parent_publication_id: parent,
        broker_levels: null,
        legs: [
          {
            operation_key: "op",
            destination: "123456789012345678",
            text: "Exact Board reply",
            attachments: [],
            message_url: null,
          },
        ],
      },
    ],
    linked: [],
  } as unknown as Detail;
  render(<PublishedDetail detail={detail} onBack={vi.fn()} onSelect={onSelect} />);
  fireEvent.click(screen.getByRole("button", { name: "Open parent publication" }));
  expect(onSelect).toHaveBeenCalledWith(parent);
  expect(screen.queryByText("Broker plan levels")).toBeNull();
});
