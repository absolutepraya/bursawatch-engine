import { describe, expect, it } from "vitest";
import { editableOperatorFieldPaths, operatorFieldCoverage } from "./operator-control-coverage";
import { validateWatcherConfig } from "./watcher-fields";

describe("operator field coverage", () => {
  it("maps every declared control to validation, API, consumer, and bounded effect", () => {
    expect(new Set(editableOperatorFieldPaths).size).toBe(editableOperatorFieldPaths.length);
    for (const field of operatorFieldCoverage) {
      expect(field.editor).toBeTruthy();
      expect(field.validator).toBeTruthy();
      expect(field.api).toBeTruthy();
      expect(field.consumer).toBeTruthy();
      expect(field.effect).toBeTruthy();
    }
    for (const path of [
      "source_catalog:publisher_defaults[].enabled",
      "source_catalog:endpoint_overrides[].enabled",
      "interval_job:enabled",
      "interval_job:interval_seconds",
      "bursawatch-x-account-watch:profiles[].enabled",
      "bursawatch-wa-channel-watch:profiles[].enabled",
      "bursawatch-wa-channel-watch:profiles[].mode",
      "bursawatch-stockbit-snips:feeds[].enabled",
      "bursawatch-stockbit-snips:destinations.id_stocks_news_channel_id",
      "bursawatch-tg-market-news:providers.phintraco.telegram_username",
      "bursawatch-dc-swing-board:destinations.heartbeat_discord_channel_id",
    ])
      expect(editableOperatorFieldPaths).toContain(path);
    expect(editableOperatorFieldPaths).not.toContain(
      "bursawatch-tg-kelas-investasi-gtw:source.telegram_username",
    );
    expect(operatorFieldCoverage).toContainEqual(
      expect.objectContaining({
        path: "bursawatch-tg-kelas-investasi-gtw:source.telegram_username",
        state: "read-only legacy",
      }),
    );
    expect(editableOperatorFieldPaths).not.toContain("source_catalog:settings");
  });

  it("keeps the GTW additive instruction required in a complete config", () => {
    const config = {
      version: 1,
      source: { telegram_channel_id: 2142109618, telegram_username: "kelasinvestasiid" },
      destinations: {
        alert_discord_channel_id: "100000000000000001",
        heartbeat_discord_channel_id: "100000000000000002",
      },
    };
    expect(validateWatcherConfig("bursawatch-tg-kelas-investasi-gtw", config)).toHaveProperty(
      "additional_prompt_instruction",
    );
  });
});
