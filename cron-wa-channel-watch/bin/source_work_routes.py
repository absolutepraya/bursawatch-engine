"""Capability to output-route scope for accepted WhatsApp source work."""
from __future__ import annotations


CAPABILITY_ROUTE_KEYS = {
    "company_news": {"id_stocks_news", "id_industry_news"},
    "macro_news": {"macro_news"},
    "swing_chart_context": {"id_stocks_swing"},
}


def route_keys(capabilities: list[str] | tuple[str, ...]) -> list[str]:
    if type(capabilities) not in {list, tuple} or not capabilities:
        raise ValueError("WhatsApp source capabilities are invalid")
    if any(type(capability) is not str or capability not in CAPABILITY_ROUTE_KEYS for capability in capabilities):
        raise ValueError("WhatsApp source capability is unsupported")
    return sorted({route for capability in capabilities for route in CAPABILITY_ROUTE_KEYS[capability]})


def scoped_routes(record: dict[str, object]) -> set[str] | None:
    """Return frozen pipeline routes, or None for legacy watcher records."""
    if "source_pipeline_route_keys" not in record:
        return None
    value = record["source_pipeline_route_keys"]
    if (
        type(value) is not list
        or not value
        or any(type(route) is not str or route not in {key for keys in CAPABILITY_ROUTE_KEYS.values() for key in keys} for route in value)
        or value != sorted(set(value))
    ):
        raise ValueError("WhatsApp source route scope is invalid")
    return set(value)


def filter_items(record: dict[str, object], items: object) -> tuple[list[dict[str, object]], str | None, list[str]]:
    """Keep only validated classification results covered by frozen subscriptions."""
    if type(items) is not list or any(type(item) is not dict or type(item.get("route")) is not str for item in items):
        raise ValueError("WhatsApp source-scoped analysis items are invalid")
    allowed = scoped_routes(record)
    if allowed is None:
        return items, None, []
    matched = [item for item in items if item["route"] in allowed]
    dropped = sorted({item["route"] for item in items if item["route"] not in allowed})
    outcome = "route_not_subscribed" if not matched else "partially_subscribed" if dropped else "subscribed"
    return matched, outcome, dropped
