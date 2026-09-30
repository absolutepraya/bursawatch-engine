import { describe, expect, it } from "vitest";
import {
  appendPublicationPage,
  publication,
  publicationCoverage,
  publicationPage,
  publicationFilters,
} from "./publications";

function sample(id = "a".repeat(64)) {
  return {
    api_version: 1,
    publication_id: id,
    owner_id: "bursawatch-x-account-watch",
    owner_key: `synthetic:${id.slice(0, 8)}`,
    version: 1,
    supersedes_version: null,
    type: "swing_context",
    route: "id_stocks_swing",
    source_event_key: "synthetic-event",
    source_name: "Synthetic source",
    source_url: "https://example.test/source/1",
    source_published_at: "2026-09-29T07:00:00+00:00",
    market_data_as_of: null,
    delivery_confirmed_at: "2026-09-29T07:02:00+00:00",
    title: "Synthetic chart context",
    ticker: "TEST",
    broker_levels: null,
    parent_publication_id: null,
    board_episode_id: null,
    config_revision: 2,
    renderer_version: "synthetic-v1",
    source_version: null,
    required_operation_keys: ["synthetic-op"],
    legs: [
      {
        operation_key: "synthetic-op",
        operation_digest: "b".repeat(64),
        receipt_operation_id: "synthetic-receipt-op",
        destination: "123456789012345678",
        receipt_id: "987654321098765432",
        status: "delivered",
        message_url:
          "https://discord.com/channels/123456789012345678/123456789012345678/987654321098765432",
        text: "Synthetic delivered chart text",
        attachments: [],
      },
    ],
    digest: "c".repeat(64),
  };
}

describe("published read contract", () => {
  it("keeps context distinct from a validated broker plan and rejects private fields", () => {
    expect(publication.parse(sample()).type).toBe("swing_context");
    expect(publication.safeParse({ ...sample(), type: "broker_swing_plan" }).success).toBe(false);
    expect(publication.safeParse({ ...sample(), raw_source_payload: "private" }).success).toBe(
      false,
    );
    const withPrivateMedia = sample();
    expect(
      publication.safeParse({
        ...withPrivateMedia,
        legs: [{ ...withPrivateMedia.legs[0], private_media_ref: "secret://object" }],
      }).success,
    ).toBe(false);
  });

  it("accepts a linked broker update without presenting it as a complete plan", () => {
    const parsed = publication.parse({ ...sample(), type: "broker_swing_update" });
    expect(parsed.type).toBe("broker_swing_update");
    expect(parsed.broker_levels).toBeNull();
  });

  it("validates server-side group, date, source, route, ticker and type filters", () => {
    expect(publicationFilters.parse({
      group: "swing",
      date_from: "2026-09-29T00:00:00+07:00",
      date_to: "2026-09-30T23:59:59+07:00",
      source: "Synthetic source",
      route: "swing_board",
      ticker: "TEST",
      type: "broker_swing_update",
    })).toMatchObject({ group: "swing", route: "swing_board", ticker: "TEST", type: "broker_swing_update" });
    expect(publicationFilters.safeParse({ route: "arbitrary" }).success).toBe(false);
  });

  it("rejects omitted required legs and mismatched Discord receipt links", () => {
    expect(
      publication.safeParse({
        ...sample(),
        required_operation_keys: ["synthetic-op", "missing-op"],
      }).success,
    ).toBe(false);
    const value = sample();
    value.legs[0].message_url =
      "https://discord.com/channels/123456789012345678/123456789012345678/987654321098765433";
    expect(publication.safeParse(value).success).toBe(false);
  });

  it("retains unique cursor pages with tied confirmation times", () => {
    const first = publicationPage.parse({
      items: [sample("a".repeat(64))],
      next_cursor: "page-two",
    });
    const second = publicationPage.parse({
      items: [sample("a".repeat(64)), sample("b".repeat(64))],
      next_cursor: null,
    });
    const rows = appendPublicationPage(appendPublicationPage([], first), second);
    expect(rows.map((row) => row.publication_id)).toEqual(["a".repeat(64), "b".repeat(64)]);
  });

  it("does not accept an all-publisher completion claim with missing owners", () => {
    const cutover = {
      boundary: "2026-09-29T07:01:00+00:00",
      owner_ids: ["bursawatch-x-account-watch", "bursawatch-tg-market-news"],
    };
    const checkpoint = {
      compared_at: "2026-09-30T07:00:00+00:00",
      confirmed_through_at: null,
      accepted_through_at: null,
      outstanding_count: 0,
    };
    const partial = {
      cutover,
      overall_status: "incomplete",
      owners: [
        { owner_id: "bursawatch-x-account-watch", status: "complete", checkpoint },
        { owner_id: "bursawatch-tg-market-news", status: "unknown", checkpoint: null },
      ],
    };
    expect(publicationCoverage.parse(partial).owners[1].status).toBe("unknown");
    expect(publicationCoverage.safeParse({ ...partial, overall_status: "complete" }).success).toBe(
      false,
    );
  });
});
