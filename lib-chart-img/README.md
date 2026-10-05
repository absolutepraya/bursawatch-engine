# Shared Chart-IMG integration

Status: configuration scaffolding and design only. No client implementation exists yet.

This package will own reusable Chart-IMG transport, request validation, image-byte validation and shared request/rate coordination. Each cron or caller supplies its own symbol, layout ID, rendering profile, freshness requirements and publication behavior.

Local credentials belong in the ignored package `.env`, linked across worktrees. The canonical file is in the main project checkout, mode `0600`; `.env.example` lists field names only. `CHART_IMG_LAYOUT_ID` is currently a private validation input, not a global library default.

See the [architecture note](../docs/notes/2026-10-05-shared-chart-img-client-architecture.md) for ownership boundaries, configuration and remaining checks. No library import, runtime deployment or public chart has been created.
