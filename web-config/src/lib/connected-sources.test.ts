import { describe, expect, it } from "vitest";
import { brokerSettingsLinks, matchSourceIdentity, sourceSettingsLink } from "./connected-sources";

describe("public identity on configured sources", () => {
  it.each([null, undefined, 12, "Kutekians", [], true])(
    "ignores malformed profile %s",
    (profile) => {
      expect(matchSourceIdentity("x", profile)).toBeUndefined();
    },
  );
  it("recognizes exact handles and canonical profile URLs without relying on internal IDs", () => {
    expect(matchSourceIdentity("x", { handle: " @Kutekians " })?.id).toBe("kutekians");
    expect(matchSourceIdentity("x", { profile_url: "https://twitter.com/Kutekians/" })?.id).toBe(
      "kutekians",
    );
    expect(
      matchSourceIdentity("x", {
        id: "arbitrary",
        handle: "rickyho_1989",
        profile_url: "https://x.com/RICKYHO_1989",
      })?.id,
    ).toBe("rickyho1989");
    expect(
      matchSourceIdentity("instagram", { id: "avenirresearch_id", handle: "avenirresearch.id" })
        ?.id,
    ).toBe("avenirresearch_id");
    expect(matchSourceIdentity("x", { handle: "InsiderTrackX" })?.image).toBe("");
  });

  it("rejects a known name or internal ID without matching public identity", () => {
    expect(
      matchSourceIdentity("x", { id: "kutekians", display_name: "Almer Sad" }),
    ).toBeUndefined();
    expect(matchSourceIdentity("x", { id: "kutekians", handle: "anotherperson" })).toBeUndefined();
    expect(matchSourceIdentity("instagram", { handle: "avenirresearch_id" })).toBeUndefined();
    expect(matchSourceIdentity("instagram", { handle: "Kutekians" })).toBeUndefined();
  });

  it("withholds an avatar when the handle and URL disagree or either identity is malformed", () => {
    expect(
      matchSourceIdentity("x", { handle: "Kutekians", profile_url: "https://x.com/writingtorch" }),
    ).toBeUndefined();
    expect(
      matchSourceIdentity("x", { handle: "Kutekians", profile_url: "not a URL" }),
    ).toBeUndefined();
    expect(
      matchSourceIdentity("x", {
        handle: "invalid handle",
        profile_url: "https://x.com/kutekians",
      }),
    ).toBeUndefined();
    expect(
      matchSourceIdentity("x", { handle: 123, profile_url: "https://x.com/kutekians" }),
    ).toBeUndefined();
    expect(
      matchSourceIdentity("x", {
        handle: "Kutekians",
        profile_url: { url: "https://x.com/kutekians" },
      }),
    ).toBeUndefined();
  });

  it.each([
    "https://x.com.evil.test/kutekians",
    "https://x.com@evil.test/kutekians",
    "https://someone@x.com/kutekians",
    "https://x.com:8443/kutekians",
    "http://x.com/kutekians",
    "https://x.com/kutekians/status/123",
    "https://x.com/%6butekians",
    "https://x.com/kutekians?next=writingtorch",
    "https://x.com/kutekians#writingtorch",
  ])("rejects non-profile or ambiguous URL %s", (profile_url) => {
    expect(matchSourceIdentity("x", { profile_url })).toBeUndefined();
  });

  it("identifies WhatsApp by the exact public channel URL, never a name or newsletter ID", () => {
    const channel_url = "https://whatsapp.com/channel/0029VbAjdnb60eBhwVdJxj1c/";
    expect(matchSourceIdentity("whatsapp", { channel_url })?.id).toBe("bri-danareksa-sekuritas");
    expect(
      matchSourceIdentity("whatsapp", { channel_url: channel_url.toLowerCase() }),
    ).toBeUndefined();
    expect(
      matchSourceIdentity("whatsapp", {
        display_name: "BRI Danareksa Sekuritas",
        channel_jid: "123456789@newsletter",
      }),
    ).toBeUndefined();
    expect(
      matchSourceIdentity("whatsapp", {
        channel_url: "https://whatsapp.com.evil.test/channel/0029VbAjdnb60eBhwVdJxj1c",
      }),
    ).toBeUndefined();
  });
});

describe("source library configuration entry points", () => {
  it("offers only configuration links for exact watcher IDs supplied by the authenticated catalog", () => {
    expect(sourceSettingsLink("x", [])).toBeUndefined();
    expect(sourceSettingsLink("x", ["bursawatch-x-account-watch-copy"])).toBeUndefined();
    expect(sourceSettingsLink("x", ["bursawatch-x-account-watch"])).toEqual({
      label: "Open X settings",
      href: "/workspace/workflows?watcher=bursawatch-x-account-watch",
    });
    expect(sourceSettingsLink("instagram", ["bursawatch-x-account-watch"])).toBeUndefined();
  });

  it("routes broker references only to available relevant settings without inventing a provider endpoint", () => {
    expect(brokerSettingsLinks("bri-danareksa", ["bursawatch-wa-channel-watch"])).toEqual([
      {
        label: "Open WhatsApp settings",
        href: "/workspace/workflows?watcher=bursawatch-wa-channel-watch",
      },
    ]);
    expect(brokerSettingsLinks("phintraco", ["bursawatch-tg-market-news"])).toEqual([
      {
        label: "Open market news settings",
        href: "/workspace/workflows?watcher=bursawatch-tg-market-news",
      },
    ]);
    expect(brokerSettingsLinks("phintraco", ["bursawatch-wa-channel-watch"])).toEqual([]);
    expect(brokerSettingsLinks("unknown", ["bursawatch-tg-market-news"])).toEqual([]);
  });
});
