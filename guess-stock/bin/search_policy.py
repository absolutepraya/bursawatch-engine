"""Provider-order policy shared by clue and issuer research paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence


class SearchProviderUnavailable(RuntimeError):
    """A provider could not serve a query and a fallback may be attempted."""


class SearchProvider(Protocol):
    name: str

    def search(self, query: str) -> Sequence[Mapping[str, object]]:
        ...


@dataclass(frozen=True, slots=True)
class SearchResponse:
    provider: str
    hits: tuple[Mapping[str, object], ...]
    degraded: bool = False
    fallback_reason: str | None = None


def search_with_fallback(
    query: str,
    *,
    primary: SearchProvider,
    fallback: SearchProvider,
) -> SearchResponse:
    """Use Serper first and Brave only for provider failure, not empty results."""

    if not query.strip():
        raise ValueError("query must not be empty")
    try:
        return SearchResponse(primary.name, tuple(primary.search(query)))
    except SearchProviderUnavailable as primary_error:
        try:
            hits = tuple(fallback.search(query))
        except SearchProviderUnavailable as fallback_error:
            raise SearchProviderUnavailable("all search providers unavailable") from fallback_error
        return SearchResponse(
            fallback.name,
            hits,
            degraded=True,
            fallback_reason=type(primary_error).__name__,
        )
