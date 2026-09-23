import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearWorkspaceDrafts,
  discardWorkspaceDraft,
  getDraftOwner,
  hasWorkspaceDrafts,
  readWorkspaceDraft,
  retainWorkspaceDraft,
  setDraftOwner,
} from "./workspace-drafts";

const config = () => ({
  base: { revision: 2, config: { profiles: [{ name: "Saved source" }] } },
  draft: { profiles: [{ name: "Edited source" }] },
});

beforeEach(() => {
  vi.stubGlobal("window", {});
  setDraftOwner("operator-a");
});
afterEach(() => {
  setDraftOwner(null);
  clearWorkspaceDrafts();
  vi.unstubAllGlobals();
});

describe("private in-memory workspace drafts", () => {
  it("isolates each configuration and schedule without browser storage", () => {
    const storage = vi.fn(() => {
      throw new Error("Persistent storage must not be used");
    });
    vi.stubGlobal("localStorage", { getItem: storage, setItem: storage });
    vi.stubGlobal("sessionStorage", { getItem: storage, setItem: storage });
    retainWorkspaceDraft("config:watcher-a", config(), true);
    retainWorkspaceDraft("config:watcher-b", { base: 1, draft: 3 }, true);
    retainWorkspaceDraft("schedule:watcher-a", { base: 4, draft: 5 }, true);
    expect(readWorkspaceDraft("config:watcher-a")).toEqual(config());
    expect(readWorkspaceDraft("config:watcher-b")).toEqual({ base: 1, draft: 3 });
    expect(readWorkspaceDraft("schedule:watcher-a")).toEqual({ base: 4, draft: 5 });
    expect(readWorkspaceDraft("schedule:missing")).toBeNull();
    expect(storage).not.toHaveBeenCalled();
  });

  it("clones both retained and restored data so callers cannot mutate other visits", () => {
    const entry = config();
    retainWorkspaceDraft("config:watcher-a", entry, true);
    entry.base.config.profiles[0].name = "Mutated base";
    entry.draft.profiles[0].name = "Mutated draft";
    const restored = readWorkspaceDraft<typeof entry.base, typeof entry.draft>("config:watcher-a")!;
    expect(restored).toEqual(config());
    restored.base.revision = 9;
    restored.draft.profiles[0].name = "Mutated returned draft";
    expect(readWorkspaceDraft("config:watcher-a")).toEqual(config());
  });

  it("retains a draft's original revision and save block across repeated visits", () => {
    const entry = { ...config(), blocked: true, failure: "Reload before saving." };
    retainWorkspaceDraft("config:watcher-a", entry, true);
    const restored = readWorkspaceDraft<typeof entry.base, typeof entry.draft>("config:watcher-a")!;
    restored.draft.profiles[0].name = "Another edit";
    retainWorkspaceDraft("config:watcher-a", restored, true);
    expect(readWorkspaceDraft("config:watcher-a")).toEqual({
      ...entry,
      draft: { profiles: [{ name: "Another edit" }] },
    });
  });

  it("drops clean, saved, reloaded, or discarded drafts without affecting other editors", () => {
    expect(hasWorkspaceDrafts()).toBe(false);
    retainWorkspaceDraft("config:watcher-a", config(), true);
    retainWorkspaceDraft("schedule:job-a", { base: 1, draft: 2 }, true);
    expect(hasWorkspaceDrafts()).toBe(true);
    retainWorkspaceDraft("config:watcher-a", config(), false);
    expect(readWorkspaceDraft("config:watcher-a")).toBeNull();
    expect(readWorkspaceDraft("schedule:job-a")).not.toBeNull();
    discardWorkspaceDraft("schedule:job-a");
    expect(readWorkspaceDraft("schedule:job-a")).toBeNull();
    expect(hasWorkspaceDrafts()).toBe(false);
    retainWorkspaceDraft("config:watcher-a", config(), true);
    clearWorkspaceDrafts();
    expect(readWorkspaceDraft("config:watcher-a")).toBeNull();
  });

  it("keeps token refreshes but clears all drafts on account changes or sign-out", () => {
    retainWorkspaceDraft("config:watcher-a", config(), true);
    setDraftOwner("operator-a");
    expect(readWorkspaceDraft("config:watcher-a")).not.toBeNull();
    setDraftOwner("operator-b");
    expect(readWorkspaceDraft("config:watcher-a")).toBeNull();
    retainWorkspaceDraft("config:watcher-a", config(), true);
    setDraftOwner(null);
    setDraftOwner("operator-b");
    expect(readWorkspaceDraft("config:watcher-a")).toBeNull();
  });

  it("rejects late writes and clears from an editor belonging to an earlier account", () => {
    const oldOwner = getDraftOwner();
    setDraftOwner("operator-b");
    retainWorkspaceDraft("config:watcher-a", config(), true, oldOwner);
    expect(readWorkspaceDraft("config:watcher-a")).toBeNull();
    retainWorkspaceDraft("config:watcher-a", config(), true);
    discardWorkspaceDraft("config:watcher-a", oldOwner);
    expect(readWorkspaceDraft("config:watcher-a")).not.toBeNull();
  });

  it("does not cache anonymous forms or write on the server", () => {
    setDraftOwner(null);
    retainWorkspaceDraft("config:watcher-a", config(), true);
    expect(readWorkspaceDraft("config:watcher-a")).toBeNull();
    vi.unstubAllGlobals();
    setDraftOwner("server-request");
    retainWorkspaceDraft("config:watcher-a", config(), true, "server-request");
    expect(getDraftOwner()).toBeNull();
    vi.stubGlobal("window", {});
    setDraftOwner("server-request");
    expect(readWorkspaceDraft("config:watcher-a")).toBeNull();
  });
});
