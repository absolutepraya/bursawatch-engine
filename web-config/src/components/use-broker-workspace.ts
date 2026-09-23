"use client";

import { useMemo, useSyncExternalStore } from "react";
import {
  decodeWorkspace,
  emptyWorkspace,
  subscribeWorkspace,
  workspaceSnapshot,
} from "@/lib/broker-workspace";

const serverSnapshot = () => "pending";
export function useBrokerWorkspace() {
  const raw = useSyncExternalStore(subscribeWorkspace, workspaceSnapshot, serverSnapshot);
  return useMemo(() => {
    const pending = raw === "pending";
    const value = decodeWorkspace(raw === "" || pending ? null : raw);
    return {
      state: value ?? emptyWorkspace,
      ready: !pending,
      error:
        value === null
          ? "Your saved settings are unavailable. Existing browser data has not been changed."
          : null,
    };
  }, [raw]);
}
