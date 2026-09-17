from __future__ import annotations

import pytest

from search_policy import SearchProviderUnavailable, search_with_fallback


class FakeProvider:
    def __init__(self, name, hits=(), error=None):
        self.name = name
        self.hits = hits
        self.error = error
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.hits


def test_serper_is_primary_and_empty_results_do_not_hide_a_valid_search() -> None:
    primary = FakeProvider("serper", hits=())
    fallback = FakeProvider("brave", hits=({"title": "fallback"},))

    result = search_with_fallback("issuer clue", primary=primary, fallback=fallback)

    assert result.provider == "serper"
    assert result.hits == ()
    assert result.degraded is False
    assert fallback.queries == []


def test_brave_is_used_only_when_serper_is_unavailable() -> None:
    primary = FakeProvider("serper", error=SearchProviderUnavailable("broken"))
    fallback = FakeProvider("brave", hits=({"title": "fallback"},))

    result = search_with_fallback("issuer clue", primary=primary, fallback=fallback)

    assert result.provider == "brave"
    assert result.degraded is True
    assert result.hits == ({"title": "fallback"},)
    assert result.fallback_reason == "SearchProviderUnavailable"


def test_all_provider_failure_is_fail_closed() -> None:
    primary = FakeProvider("serper", error=SearchProviderUnavailable("broken"))
    fallback = FakeProvider("brave", error=SearchProviderUnavailable("also broken"))

    with pytest.raises(SearchProviderUnavailable, match="all search providers unavailable"):
        search_with_fallback("issuer clue", primary=primary, fallback=fallback)
