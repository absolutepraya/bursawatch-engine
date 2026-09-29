"""Stable, read-only inventory of migrated BursaWatch components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


INVENTORY_VERSION = 1


@dataclass(frozen=True)
class ComponentDefinition:
    component_id: str
    kind: str
    display_name: str
    capabilities: tuple[str, ...]
    pipeline_ids: tuple[str, ...]
    config_resource_ids: tuple[str, ...]
    related_component_ids: tuple[str, ...]
    job_ids: tuple[str, ...]


_COMPONENTS = (
    ComponentDefinition("bursawatch-tg-source-ingest", "source_adapter", "Telegram Source Adapter", ("telegram_source_intake",), (), ("source-catalog",), ("bursawatch-tg-market-news", "bursawatch-tg-phintraco-swing", "bursawatch-tg-kelas-investasi-gtw"), ("bursawatch-tg-source-ingest",)),
    ComponentDefinition("bursawatch-x-source-ingest", "source_adapter", "X Source Adapter", ("x_source_intake",), (), ("source-catalog",), ("bursawatch-x-account-watch",), ("bursawatch-x-account-watch",)),
    ComponentDefinition("bursawatch-ig-source-ingest", "source_adapter", "Instagram Source Adapter", ("instagram_source_intake",), (), ("source-catalog",), ("bursawatch-ig-account-watch",), ()),
    ComponentDefinition("bursawatch-wa-source-ingest", "source_adapter", "WhatsApp Source Adapter", ("whatsapp_source_intake",), (), ("source-catalog",), ("bursawatch-wa-channel-watch",), ("bursawatch-wa-channel-watch",)),
    ComponentDefinition("bursawatch-rss-source-ingest", "source_adapter", "Stockbit RSS Source Adapter", ("rss_source_intake",), ("stockbit_snips",), ("source-catalog",), ("bursawatch-stockbit-snips",), ("bursawatch-stockbit-snips",)),
    ComponentDefinition("bursawatch-tg-market-news", "domain_owner", "Telegram Market News", ("company_news", "macro_news", "stock_status"), ("company_news", "macro_news", "stock_status"), ("watcher:bursawatch-tg-market-news",), ("bursawatch-tg-source-ingest", "bursawatch-discord-delivery"), ("bursawatch-tg-source-ingest", "bursawatch-tg-market-news")),
    ComponentDefinition("bursawatch-tg-phintraco-swing", "domain_owner", "Phintraco Swing", ("trading_plans",), ("swing_plan",), ("watcher:bursawatch-tg-phintraco-swing",), ("bursawatch-tg-source-ingest", "bursawatch-discord-delivery"), ("bursawatch-tg-source-ingest", "bursawatch-tg-phintraco-swing")),
    ComponentDefinition("bursawatch-tg-kelas-investasi-gtw", "domain_owner", "Kelas Investasi GTW", ("swing_support",), ("swing_support",), ("watcher:bursawatch-tg-kelas-investasi-gtw",), ("bursawatch-tg-source-ingest", "bursawatch-discord-delivery"), ("bursawatch-tg-source-ingest", "bursawatch-tg-kelas-investasi-gtw")),
    ComponentDefinition("bursawatch-dc-swing-board", "domain_owner", "Discord Swing Board", ("cash_swing_lifecycle", "source_context"), ("swing_plan", "swing_support", "swing_chart_context"), ("watcher:bursawatch-dc-swing-board",), ("bursawatch-x-account-watch", "bursawatch-wa-channel-watch", "bursawatch-discord-delivery"), ("bursawatch-dc-swing-board-close", "bursawatch-dc-swing-board-retry", "f2b6c4f0995b")),
    ComponentDefinition("bursawatch-x-account-watch", "domain_owner", "X Account Watch", ("x_post_routing", "chart_context"), ("swing_chart_context", "company_news", "macro_news"), ("watcher:bursawatch-x-account-watch",), ("bursawatch-x-source-ingest", "bursawatch-discord-delivery"), ("bursawatch-x-account-watch", "bursawatch-x-account-watch-queue-worker")),
    ComponentDefinition("bursawatch-ig-account-watch", "domain_owner", "Instagram Account Watch", ("instagram_post_routing",), ("company_news", "macro_news"), ("watcher:bursawatch-ig-account-watch",), ("bursawatch-ig-source-ingest", "bursawatch-discord-delivery"), ("bursawatch-ig-account-watch",)),
    ComponentDefinition("bursawatch-wa-channel-watch", "domain_owner", "WhatsApp Channel Watch", ("whatsapp_channel_routing", "chart_context"), ("company_news", "macro_news", "swing_chart_context"), ("watcher:bursawatch-wa-channel-watch",), ("bursawatch-wa-source-ingest", "bursawatch-discord-delivery"), ("bursawatch-wa-channel-watch",)),
    ComponentDefinition("bursawatch-stockbit-snips", "domain_owner", "Stockbit Snips", ("stockbit_snips",), ("stockbit_snips",), ("watcher:bursawatch-stockbit-snips",), ("bursawatch-rss-source-ingest", "bursawatch-discord-delivery"), ("bursawatch-stockbit-snips",)),
)

# Keep the shared delivery relationship explicit without constructing definitions
# recursively. Tuple values make both the registry and its public projections stable.
_COMPONENTS = _COMPONENTS + (
    ComponentDefinition(
        "bursawatch-discord-delivery",
        "delivery_service",
        "Discord Delivery Owner",
        ("discord_delivery",),
        (),
        ("service:bursawatch-discord-delivery",),
        tuple(item.component_id for item in _COMPONENTS if item.kind == "domain_owner"),
        (),
    ),
)
_BY_ID = {component.component_id: component for component in _COMPONENTS}


def list_components() -> tuple[ComponentDefinition, ...]:
    return _COMPONENTS


def component_view(component_id: str) -> dict[str, Any]:
    component = _BY_ID[component_id]
    return {
        "inventory_version": INVENTORY_VERSION,
        "component_id": component.component_id,
        "kind": component.kind,
        "display_name": component.display_name,
        "capabilities": list(component.capabilities),
        "pipeline_ids": list(component.pipeline_ids),
        "config_resource_ids": list(component.config_resource_ids),
        "related_component_ids": list(component.related_component_ids),
        "job_ids": list(component.job_ids),
    }
