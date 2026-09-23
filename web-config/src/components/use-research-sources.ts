"use client";
import { useMemo, useSyncExternalStore } from "react";
import {
  decodeResearch,
  emptyResearch,
  researchSnapshot,
  subscribeResearch,
} from "@/lib/research-sources";
const serverSnapshot = () => "pending";
export function useResearchSources() {
  const raw = useSyncExternalStore(subscribeResearch, researchSnapshot, serverSnapshot);
  return useMemo(
    () => ({
      ready: raw !== "pending",
      state: decodeResearch(raw === "pending" ? null : raw) ?? emptyResearch,
      error: raw !== "pending" && decodeResearch(raw) === null,
    }),
    [raw],
  );
}
