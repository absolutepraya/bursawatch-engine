// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WatcherConfigEditor } from "./watcher-config-editor";
import { ScheduleEditor } from "./schedule-editor";
import type { DraftAttempt } from "@/hooks/use-operator-draft";
import { readWorkspaceDraft, setDraftOwner } from "@/lib/workspace-drafts";
import type { ConfigSnapshot } from "@/lib/watcher-fields";
import type { ControlJob } from "@/server/control-plane";

const toast = vi.hoisted(() => vi.fn());
vi.mock("./toast-provider", () => ({ useToast: () => toast }));
const snapshot: ConfigSnapshot = {
  api_version: 1,
  watcher_id: "bursawatch-tg-market-news",
  revision: 1,
  config_version: 1,
  config_sha256: "a".repeat(64),
  updated_at: "2026-10-23T00:00:00Z",
  config: {
    version: 1,
    providers: {
      phintraco: { telegram_username: "exampleph" },
      tuntun: { telegram_username: "exampletuntun" },
    },
    destinations: {
      id_stocks_news_discord_channel_id: "100000000000000001",
      macro_news_discord_channel_id: "100000000000000002",
      industry_news_discord_channel_id: "100000000000000003",
      heartbeat_discord_channel_id: "100000000000000004",
    },
    additional_prompt_instruction: "",
  },
};
const job: ControlJob = {
  job_id: "example",
  display_name: "Example job",
  watcher_id: "example",
  schedule_kind: "interval",
  min_interval_seconds: 300,
  max_interval_seconds: 3600,
  schedule: {
    api_version: 1,
    job_id: "example",
    revision: 1,
    enabled: true,
    interval_seconds: 600,
    timezone: "Asia/Jakarta",
    schedule_sha256: "a".repeat(64),
    updated_at: snapshot.updated_at,
  },
  reconciliation: { status: "applied", applied_revision: 1, effective: true },
};
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
beforeEach(() => {
  setDraftOwner("operator");
  vi.stubGlobal("requestAnimationFrame", (fn: () => void) => {
    fn();
    return 0;
  });
});
afterEach(() => {
  cleanup();
  setDraftOwner(null);
  toast.mockReset();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

for (const kind of ["configuration", "schedule"] as const) {
  describe(`${kind} recovery`, () => {
    const key =
      kind === "configuration"
        ? (`config:${snapshot.watcher_id}` as const)
        : (`schedule:${job.job_id}` as const);
    function view(save: () => Promise<unknown>, revision = 1, refresh = async () => job) {
      return kind === "configuration"
        ? render(
            <WatcherConfigEditor
              snapshot={{ ...snapshot, revision }}
              onSave={save as () => Promise<ConfigSnapshot>}
            />,
          )
        : render(
            <ScheduleEditor
              job={{ ...job, schedule: { ...job.schedule!, revision } }}
              onSave={save as () => Promise<ControlJob>}
              onRefresh={refresh}
            />,
          );
    }
    function edit() {
      if (kind === "configuration")
        fireEvent.change(document.querySelector("textarea")!, {
          target: { value: "Keep my draft" },
        });
      else
        fireEvent.change(screen.getByLabelText("Check every (minutes)"), {
          target: { value: "15" },
        });
    }
    function saveButton() {
      return screen.getByRole("button", {
        name: kind === "configuration" ? "Save configuration" : "Save schedule",
      }) as HTMLButtonElement;
    }
    function result() {
      return kind === "configuration"
        ? {
            ...snapshot,
            revision: 2,
            config: { ...snapshot.config, additional_prompt_instruction: "Keep my draft" },
          }
        : {
            ...job,
            schedule: { ...job.schedule!, revision: 2, interval_seconds: 900 },
            reconciliation: { ...job.reconciliation, applied_revision: 2 },
          };
    }

    it("restores edits and locks a draft against a newer revision", () => {
      const first = view(vi.fn());
      edit();
      first.unmount();
      view(vi.fn(), 2);
      expect(screen.getByText(/changed while you were away/)).toBeTruthy();
      expect(saveButton().disabled).toBe(true);
      expect(readWorkspaceDraft(key)?.base).toMatchObject(
        kind === "configuration" ? { revision: 1 } : { schedule: { revision: 1 } },
      );
    });
    it.each(["resolve", "reject"] as const)(
      "keeps a returned unconfirmed draft when the obsolete save later %ss",
      async (outcome) => {
        const pending = deferred<unknown>();
        const save = vi.fn(() => pending.promise);
        const first = view(save);
        edit();
        fireEvent.click(saveButton());
        expect(save).toHaveBeenCalledOnce();
        first.unmount();
        view(vi.fn());
        const retained = readWorkspaceDraft(key);
        expect(retained?.blocked).toBe(true);
        await act(async () => {
          if (outcome === "resolve") pending.resolve(result());
          else pending.reject(new Error("Old failure"));
        });
        expect(readWorkspaceDraft(key)).toEqual(retained);
        expect(saveButton().disabled).toBe(true);
        expect(toast).not.toHaveBeenCalled();
        expect(screen.queryByText("Old failure")).toBeNull();
      },
    );
    it("keeps ordinary failures retryable, including after returning", async () => {
      const first = view(async () => {
        throw new Error("Service unavailable");
      });
      edit();
      fireEvent.click(saveButton());
      await act(async () => {});
      expect(saveButton().disabled).toBe(false);
      expect(screen.getByText("Service unavailable")).toBeTruthy();
      first.unmount();
      view(vi.fn());
      expect(saveButton().disabled).toBe(false);
      expect(screen.getByText("Service unavailable")).toBeTruthy();
    });
    it.each(["conflict", "unknown-outcome"])("locks %s without retrying", async (code) => {
      const save = vi.fn(async () => {
        throw Object.assign(new Error("Reload required"), { code });
      });
      view(save);
      edit();
      fireEvent.click(saveButton());
      await act(async () => {});
      expect(saveButton().disabled).toBe(true);
      expect(readWorkspaceDraft(key)?.blocked).toBe(true);
      expect(save).toHaveBeenCalledOnce();
    });
    it("rejects a completion after signing out and back into the same account", async () => {
      const pending = deferred<unknown>();
      view(() => pending.promise);
      edit();
      fireEvent.click(saveButton());
      act(() => {
        setDraftOwner(null);
        setDraftOwner("operator");
      });
      await act(async () => {
        pending.resolve(result());
      });
      expect(readWorkspaceDraft(key)).toBeNull();
      expect(toast).not.toHaveBeenCalled();
    });
    it("clears a draft only after a current save succeeds", async () => {
      view(async () => result());
      edit();
      fireEvent.click(saveButton());
      await act(async () => {});
      expect(readWorkspaceDraft(key)).toBeNull();
      expect(saveButton().disabled).toBe(true);
      expect(toast).toHaveBeenCalledOnce();
    });
  });
}

it("requires explicit schedule reload after an uncertain save, even after a successful status refresh", async () => {
  const save = vi.fn(async () => {
    throw Object.assign(new Error("Reload required"), { code: "unknown-outcome" });
  });
  const refresh = vi.fn(async () => job);
  render(<ScheduleEditor job={job} onSave={save} onRefresh={refresh} />);
  const minutes = screen.getByLabelText("Check every (minutes)") as HTMLInputElement;
  fireEvent.change(minutes, { target: { value: "15" } });
  fireEvent.click(screen.getByRole("button", { name: "Save schedule" }));
  await act(async () => {});
  fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
  await act(async () => {});
  expect(minutes.value).toBe("15");
  expect(minutes.closest("fieldset")!.disabled).toBe(true);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Reload schedule" }));
  await act(async () => {});
  expect(minutes.value).toBe("10");
  expect(minutes.closest("fieldset")!.disabled).toBe(false);
  expect(readWorkspaceDraft(`schedule:${job.job_id}`)).toBeNull();
  expect(save).toHaveBeenCalledOnce();
});

it("reports saved separately from applied and polls only for the saved revision", async () => {
  vi.useFakeTimers();
  const pending: ControlJob = {
    ...job,
    schedule: { ...job.schedule!, revision: 2, interval_seconds: 900 },
    reconciliation: { status: "pending", applied_revision: 1, effective: false },
  };
  const applied: ControlJob = {
    ...pending,
    reconciliation: { status: "applied", applied_revision: 2, effective: true },
  };
  const refresh = vi.fn(async () => applied);
  render(<ScheduleEditor job={job} onSave={async () => pending} onRefresh={refresh} />);
  fireEvent.change(screen.getByLabelText("Check every (minutes)"), { target: { value: "15" } });
  fireEvent.click(screen.getByRole("button", { name: "Save schedule" }));
  await act(async () => {});
  expect(toast).toHaveBeenCalledWith("Schedule saved. Waiting for it to take effect.");
  expect(toast).not.toHaveBeenCalledWith("Schedule applied.");
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000);
  });
  expect(refresh).toHaveBeenCalledOnce();
  expect(toast).toHaveBeenLastCalledWith("Schedule applied.");
  vi.useRealTimers();
});

it("keeps sample and signed-in drafts separate", () => {
  const sample = render(<WatcherConfigEditor snapshot={snapshot} sampleMode onSave={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Additional instructions"), {
    target: { value: "Sample draft" },
  });
  sample.unmount();
  const live = render(<WatcherConfigEditor snapshot={snapshot} onSave={vi.fn()} />);
  expect((screen.getByLabelText("Additional instructions") as HTMLTextAreaElement).value).toBe("");
  fireEvent.change(screen.getByLabelText("Additional instructions"), {
    target: { value: "Workspace draft" },
  });
  live.unmount();
  render(<WatcherConfigEditor snapshot={snapshot} sampleMode onSave={vi.fn()} />);
  expect((screen.getByLabelText("Additional instructions") as HTMLTextAreaElement).value).toBe(
    "Sample draft",
  );
  expect(readWorkspaceDraft(`config:${snapshot.watcher_id}`)?.draft).toMatchObject({
    additional_prompt_instruction: "Workspace draft",
  });
});

it("validates before saving and preserves unknown watcher fields", async () => {
  const config = { ...snapshot.config, future_option: { enabled: true } };
  const save = vi.fn(async (draft) => ({ ...snapshot, revision: 2, config: draft }));
  render(<WatcherConfigEditor snapshot={{ ...snapshot, config }} onSave={save} />);
  fireEvent.change(screen.getByLabelText("Phintraco provider username"), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
  expect(save).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Phintraco provider username"), {
    target: { value: "newprovider" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
  await act(async () => {});
  expect(save.mock.calls[0][0].future_option).toEqual({ enabled: true });
  expect(snapshot.config).toMatchObject({
    providers: { phintraco: { telegram_username: "exampleph" } },
  });
});

it("polls an initially pending schedule without a draft", async () => {
  vi.useFakeTimers();
  const pending: ControlJob = {
    ...job,
    reconciliation: { status: "pending", applied_revision: null, effective: false },
  };
  const refresh = vi.fn(async () => job);
  render(<ScheduleEditor job={pending} onSave={vi.fn()} onRefresh={refresh} />);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000);
  });
  expect(refresh).toHaveBeenCalledOnce();
  expect(toast).toHaveBeenCalledWith("Schedule applied.");
});

it("does not announce an obsolete polling result after navigation", async () => {
  vi.useFakeTimers();
  const response = deferred<ControlJob>();
  const pending: ControlJob = {
    ...job,
    reconciliation: { status: "pending", applied_revision: null, effective: false },
  };
  const refresh = vi.fn<(attempt: DraftAttempt) => Promise<ControlJob>>(() => response.promise);
  const first = render(<ScheduleEditor job={pending} onSave={vi.fn()} onRefresh={refresh} />);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000);
  });
  first.unmount();
  await act(async () => {
    response.resolve(job);
  });
  expect(toast).not.toHaveBeenCalled();
  expect(refresh.mock.calls[0][0].isCurrent()).toBe(false);
});
