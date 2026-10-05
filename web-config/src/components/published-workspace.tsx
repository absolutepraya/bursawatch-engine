"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { PublishedDetail } from "@/components/published-detail";
import { PublishedList, type PublishedFilter } from "@/components/published-list";
import type {
  Publication,
  PublicationCoverage,
  PublicationDetail as PublicationDetailData,
  PublicationFilters,
  PublicationPage,
} from "@/lib/publications";
import { publicationTypeLabels } from "@/lib/publications";

type Requester = <T>(
  path: string,
  payload?: unknown,
  options?: { signal?: AbortSignal; method?: "POST" },
) => Promise<T>;
const routes = [
  ["id_stocks_news", "IDX stocks news"],
  ["id_industry_news", "Industry news"],
  ["macro_news", "Macro news"],
  ["us_stocks_news", "US stocks news"],
  ["id_stocks_swing", "IDX swing"],
  ["swing_board", "Swing Board"],
] as const;

const blankFilter: PublishedFilter & {
  route: PublicationFilters["route"] | "all";
  dateFrom: string;
  dateTo: string;
} = {
  group: "all",
  type: "all",
  route: "all",
  ticker: "",
  source: "",
  dateFrom: "",
  dateTo: "",
};

export function PublishedWorkspace({ request }: { request: Requester }) {
  const router = useRouter();
  const search = useSearchParams();
  const selectedId = search.get("publication");
  const [filter, setFilter] = useState(blankFilter);
  const [items, setItems] = useState<Publication[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [coverage, setCoverage] = useState<PublicationCoverage | null>(null);
  const [loading, setLoading] = useState(true);
  const [moreLoading, setMoreLoading] = useState(false);
  const [error, setError] = useState("");
  const [detailResult, setDetailResult] = useState<{
    id: string;
    attempt: number;
    detail?: PublicationDetailData;
    error?: string;
  } | null>(null);
  const [detailRetry, setDetailRetry] = useState(0);
  const listController = useRef<AbortController | null>(null);
  const detailController = useRef<AbortController | null>(null);
  const listGeneration = useRef(0);
  const filterKey = useMemo(() => JSON.stringify(filter), [filter]);
  const currentDetail =
    selectedId && detailResult?.id === selectedId && detailResult.attempt === detailRetry
      ? (detailResult.detail ?? null)
      : null;
  const currentDetailError =
    selectedId && detailResult?.id === selectedId && detailResult.attempt === detailRetry
      ? (detailResult.error ?? "")
      : "";
  const detailLoading = Boolean(
    selectedId && (detailResult?.id !== selectedId || detailResult.attempt !== detailRetry),
  );

  const apiFilters = useMemo(() => {
    const value = JSON.parse(filterKey) as typeof blankFilter;
    return {
      ...(value.group === "all" ? {} : { group: value.group }),
      ...(value.type === "all" ? {} : { type: value.type }),
      ...(value.route === "all" ? {} : { route: value.route }),
      ...(value.ticker.trim() ? { ticker: value.ticker.trim().toUpperCase() } : {}),
      ...(value.source.trim() ? { source: value.source.trim() } : {}),
      ...(value.dateFrom
        ? { date_from: new Date(`${value.dateFrom}T00:00:00+07:00`).toISOString() }
        : {}),
      ...(value.dateTo
        ? { date_to: new Date(`${value.dateTo}T23:59:59.999+07:00`).toISOString() }
        : {}),
    } satisfies Omit<PublicationFilters, "cursor" | "limit">;
  }, [filterKey]);

  const loadPage = useCallback(
    async (append: boolean, nextCursor?: string | null) => {
      const generation = ++listGeneration.current;
      listController.current?.abort();
      const controller = new AbortController();
      listController.current = controller;
      if (!append) {
        setLoading(true);
        setItems([]);
        setCursor(null);
        setError("");
      } else {
        setMoreLoading(true);
        setError("");
      }
      try {
        const params = new URLSearchParams();
        params.set("limit", "50");
        for (const [key, value] of Object.entries(apiFilters))
          if (value !== undefined) params.set(key, String(value));
        if (nextCursor) params.set("cursor", nextCursor);
        const page = await request<PublicationPage>(
          `publications?${params.toString()}`,
          undefined,
          { signal: controller.signal },
        );
        if (controller.signal.aborted || generation !== listGeneration.current) return;
        setItems((previous) => (append ? mergePublications(previous, page.items) : page.items));
        setCursor(page.next_cursor);
      } catch (failure) {
        if (controller.signal.aborted || generation !== listGeneration.current) return;
        setError(
          failure instanceof Error
            ? failure.message
            : "Published records could not be loaded. Try again.",
        );
      } finally {
        if (generation === listGeneration.current) {
          setLoading(false);
          setMoreLoading(false);
        }
      }
    },
    [apiFilters, request],
  );

  useEffect(() => {
    const timer = setTimeout(() => void loadPage(false), 250);
    return () => {
      clearTimeout(timer);
      listController.current?.abort();
    };
  }, [filterKey, loadPage]);

  useEffect(() => {
    const controller = new AbortController();
    void request<PublicationCoverage>("publications/coverage", undefined, {
      signal: controller.signal,
    })
      .then((result) => setCoverage(result))
      .catch((failure) => {
        if (!controller.signal.aborted)
          setError(
            (current) =>
              current ||
              (failure instanceof Error
                ? failure.message
                : "Publisher coverage could not be loaded."),
          );
      });
    return () => controller.abort();
  }, [request]);

  useEffect(() => {
    detailController.current?.abort();
    if (!selectedId) return;
    const controller = new AbortController();
    detailController.current = controller;
    const attempt = detailRetry;
    void request<PublicationDetailData>(
      `publications/${encodeURIComponent(selectedId)}`,
      undefined,
      { signal: controller.signal },
    )
      .then((result) => {
        if (!controller.signal.aborted)
          setDetailResult({ id: selectedId, attempt, detail: result });
      })
      .catch((failure) => {
        if (!controller.signal.aborted)
          setDetailResult({
            id: selectedId,
            attempt,
            error:
              failure instanceof Error ? failure.message : "This publication could not be loaded.",
          });
      });
    return () => controller.abort();
  }, [selectedId, request, detailRetry]);

  const openDetail = (id: string) =>
    router.push(`/workspace/published?publication=${encodeURIComponent(id)}`);
  const closeDetail = () => router.push("/workspace/published");
  const retryDetail = () => setDetailRetry((value) => value + 1);

  return (
    <>
      <div className="control-page-heading">
        <h1>Published</h1>
        <p>Confirmed News and Swing deliveries since the recorded feed boundary.</p>
      </div>
      {selectedId ? (
        detailLoading ? (
          <p role="status">Loading publication…</p>
        ) : currentDetailError ? (
          <div className="control-alert" role="alert">
            <p>{currentDetailError}</p>
            <button type="button" className="button secondary" onClick={retryDetail}>
              Try again
            </button>
          </div>
        ) : currentDetail ? (
          <PublishedDetail detail={currentDetail} onBack={closeDetail} onSelect={openDetail} />
        ) : null
      ) : (
        <>
          <div className="published-filters published-server-filters">
            <label>
              Type
              <select
                value={filter.type}
                onChange={(event) =>
                  setFilter({ ...filter, type: event.target.value as PublishedFilter["type"] })
                }
              >
                <option value="all">All types</option>
                {Object.entries(publicationTypeLabels).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Route
              <select
                value={filter.route}
                onChange={(event) =>
                  setFilter({ ...filter, route: event.target.value as typeof filter.route })
                }
              >
                <option value="all">All routes</option>
                {routes.map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Delivered from
              <input
                type="date"
                value={filter.dateFrom}
                onChange={(event) => setFilter({ ...filter, dateFrom: event.target.value })}
              />
            </label>
            <label>
              Delivered to
              <input
                type="date"
                value={filter.dateTo}
                onChange={(event) => setFilter({ ...filter, dateTo: event.target.value })}
              />
            </label>
          </div>
          <PublishedList
            items={items}
            coverage={coverage}
            cursor={cursor}
            filter={filter}
            loading={loading || moreLoading}
            error={error}
            onFilter={(next) => setFilter({ ...filter, ...next })}
            onMore={() => void loadPage(true, cursor)}
            onSelect={openDetail}
          />
        </>
      )}
    </>
  );
}

function mergePublications(previous: Publication[], next: Publication[]) {
  const unique = new Map(previous.map((item) => [item.publication_id, item]));
  for (const item of next) unique.set(item.publication_id, item);
  return [...unique.values()];
}
