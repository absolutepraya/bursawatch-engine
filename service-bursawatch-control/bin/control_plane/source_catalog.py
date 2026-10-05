"""Versioned source registry configuration, independent of watcher configuration."""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse


CAPABILITIES = (
    {"id": "trading_plans", "label": "Trading Plans", "pipeline": "swing_plan", "version": 1},
    {"id": "swing_support", "label": "Swing Supporting Setup", "pipeline": "swing_support", "version": 1},
    {"id": "swing_chart_context", "label": "Swing Chart Context", "pipeline": "swing_chart_context", "version": 1},
    {"id": "company_news", "label": "Company/Stock News", "pipeline": "company_news", "version": 1},
    {"id": "macro_news", "label": "Macro News", "pipeline": "macro_news", "version": 1},
    {"id": "stock_status", "label": "Stock Information/Stock Status", "pipeline": "stock_status", "version": 1},
    {"id": "stockbit_snips", "label": "Stockbit Snips", "pipeline": "stockbit_snips", "version": 1},
)

SECURITIES: tuple[dict[str, str], ...] = ()  # No reviewed finite engine universe exists yet.

# IDs and addresses below come from checked-in watcher configs and Stockbit FEEDS. A
# display name alone is never evidence of a relationship to an institution or
# of a person versus organization subtype, so seeded People & Org kind is null.
INSTITUTIONS = (
    {"id": "phintraco", "name": "Phintraco Sekuritas", "tier": 1},
    {"id": "bri-danareksa", "name": "BRI Danareksa Sekuritas", "tier": 3},
    {"id": "tuntun", "name": "Tuntun Sekuritas", "tier": 3},
    {"id": "samuel-sekuritas", "name": "Samuel Sekuritas Indonesia", "tier": 3},
)

PEOPLE_ORG = (
    {"id": "kelas-investasi", "name": "Kelas Investasi", "kind": None, "tier": 2},
    {"id": "stockbit", "name": "Stockbit", "kind": None, "tier": 3},
    {'id': 'x-kutekians', 'name': 'Almer Sad, CFA', 'kind': None, 'tier': 3},
    {'id': 'x-rickyho1989', 'name': 'Ricky Ho', 'kind': None, 'tier': 3},
    {'id': 'x-writingtorch', 'name': 'Torch', 'kind': None, 'tier': 3},
    {'id': 'x-arvinhonami', 'name': 'Arvin Honami', 'kind': None, 'tier': 3},
    {'id': 'x-insidertracker', 'name': 'Insider Tracker', 'kind': None, 'tier': 3},
    {'id': 'x-doktermarket', 'name': 'Dokter Market', 'kind': None, 'tier': 3},
    {'id': 'x-txthariansaham', 'name': 'Ga Cuan Ga tidur', 'kind': None, 'tier': 3},
    {'id': 'x-wavetiga', 'name': 'Andriy', 'kind': None, 'tier': 3},
    {'id': 'x-aldotjahjadi8', 'name': 'Aldo Tjahjadi', 'kind': None, 'tier': 3},
    {'id': 'x-kobeissiletter', 'name': 'The Kobeissi Letter', 'kind': None, 'tier': 3},
    {'id': 'instagram-beyondthefundamental', 'name': 'Beyond thy Fundamental', 'kind': None, 'tier': 3},
    {'id': 'instagram-investart_id', 'name': 'Investart', 'kind': None, 'tier': 3},
    {'id': 'instagram-avenirresearch_id', 'name': 'Avenir Research', 'kind': None, 'tier': 3},
    {'id': 'instagram-acresresearch', 'name': 'Acres Research', 'kind': None, 'tier': 3},
    {'id': 'instagram-sectorsapp', 'name': 'Sectors', 'kind': None, 'tier': 3},
    {'id': 'instagram-cukhurukuque', 'name': 'Cukhurukuque', 'kind': None, 'tier': 3},
    {'id': 'instagram-notintofinance', 'name': 'NIFI', 'kind': None, 'tier': 3},
    {'id': 'whatsapp-ins', 'name': 'INS', 'kind': None, 'tier': 3},
)

STOCKBIT_FEED_URLS = {
    "stockbit_commentary": "https://snips.stockbit.com/stockbit-research?format=rss",
    "unboxing": "https://snips.stockbit.com/unboxing?format=rss",
    "unboxing_ipo": "https://snips.stockbit.com/unboxing-ipo?format=rss",
    "ai_reports_stockbit": "https://snips.stockbit.com/ai-reports-stockbit?format=rss",
}

ENDPOINTS = (
    {'id': 'x:kutekians', 'publisher_id': 'x-kutekians', 'platform': 'x', 'address': 'Kutekians', 'provider_id': None, 'system_owned': True},
    {'id': 'x:rickyho_1989', 'publisher_id': 'x-rickyho1989', 'platform': 'x', 'address': 'rickyho_1989', 'provider_id': None, 'system_owned': True},
    {'id': 'x:writingtorch', 'publisher_id': 'x-writingtorch', 'platform': 'x', 'address': 'writingtorch', 'provider_id': None, 'system_owned': True},
    {'id': 'x:arvinhonami', 'publisher_id': 'x-arvinhonami', 'platform': 'x', 'address': 'ArvinHonami', 'provider_id': None, 'system_owned': True},
    {'id': 'x:insidertrackx', 'publisher_id': 'x-insidertracker', 'platform': 'x', 'address': 'InsiderTrackX', 'provider_id': None, 'system_owned': True},
    {'id': 'x:doktermarket', 'publisher_id': 'x-doktermarket', 'platform': 'x', 'address': 'doktermarket', 'provider_id': None, 'system_owned': True},
    {'id': 'x:txthariansaham', 'publisher_id': 'x-txthariansaham', 'platform': 'x', 'address': 'txthariansaham', 'provider_id': None, 'system_owned': True},
    {'id': 'x:wavetiga', 'publisher_id': 'x-wavetiga', 'platform': 'x', 'address': 'wavetiga', 'provider_id': None, 'system_owned': True},
    {'id': 'x:aldotjahjadi8', 'publisher_id': 'x-aldotjahjadi8', 'platform': 'x', 'address': 'aldotjahjadi8', 'provider_id': None, 'system_owned': True},
    {'id': 'x:kobeissiletter', 'publisher_id': 'x-kobeissiletter', 'platform': 'x', 'address': 'KobeissiLetter', 'provider_id': None, 'system_owned': True},
    {'id': 'instagram:beyondthefundamental', 'publisher_id': 'instagram-beyondthefundamental', 'platform': 'instagram', 'address': 'beyondthefundamental', 'provider_id': None, 'system_owned': True},
    {'id': 'instagram:investart_id', 'publisher_id': 'instagram-investart_id', 'platform': 'instagram', 'address': 'investart_id', 'provider_id': None, 'system_owned': True},
    {'id': 'instagram:avenirresearch.id', 'publisher_id': 'instagram-avenirresearch_id', 'platform': 'instagram', 'address': 'avenirresearch.id', 'provider_id': None, 'system_owned': True},
    {'id': 'instagram:acresresearch', 'publisher_id': 'instagram-acresresearch', 'platform': 'instagram', 'address': 'acresresearch', 'provider_id': None, 'system_owned': True},
    {'id': 'instagram:sectorsapp', 'publisher_id': 'instagram-sectorsapp', 'platform': 'instagram', 'address': 'sectorsapp', 'provider_id': None, 'system_owned': True},
    {'id': 'instagram:cukhurukuque', 'publisher_id': 'instagram-cukhurukuque', 'platform': 'instagram', 'address': 'cukhurukuque', 'provider_id': None, 'system_owned': True},
    {'id': 'instagram:notintofinance', 'publisher_id': 'instagram-notintofinance', 'platform': 'instagram', 'address': 'notintofinance', 'provider_id': None, 'system_owned': True},
    {'id': 'whatsapp:0029Vb6qi96ISTkJcDn4op2z', 'publisher_id': 'whatsapp-ins', 'platform': 'whatsapp', 'address': 'https://whatsapp.com/channel/0029Vb6qi96ISTkJcDn4op2z', 'provider_id': '120363405187024421@newsletter', 'system_owned': True},
    {"id": "telegram:phintraprofits", "publisher_id": "phintraco", "platform": "telegram", "address": "phintraprofits", "provider_id": "1444713822", "system_owned": True},
    {"id": "telegram:phintasprofits", "publisher_id": "phintraco", "platform": "telegram", "address": "phintasprofits", "provider_id": None, "system_owned": True},
    {"id": "telegram:kelasinvestasiid", "publisher_id": "kelas-investasi", "platform": "telegram", "address": "kelasinvestasiid", "provider_id": "2142109618", "system_owned": True},
    {"id": "telegram:tuntunsekuritas", "publisher_id": "tuntun", "platform": "telegram", "address": "tuntunsekuritas", "provider_id": None, "system_owned": True},
    {"id": "whatsapp:0029VbAjdnb60eBhwVdJxj1c", "publisher_id": "bri-danareksa", "platform": "whatsapp", "address": "https://www.whatsapp.com/channel/0029VbAjdnb60eBhwVdJxj1c", "provider_id": "120363419226413141@newsletter", "system_owned": True},
    {"id": "whatsapp:0029VagNdGpFMqrXKEcdBb2U", "publisher_id": "samuel-sekuritas", "platform": "whatsapp", "address": "https://whatsapp.com/channel/0029VagNdGpFMqrXKEcdBb2U", "provider_id": "120363319274271353@newsletter", "system_owned": True},
    *(
        {"id": f"rss:stockbit:{lane}", "publisher_id": "stockbit", "platform": "rss", "address": STOCKBIT_FEED_URLS[lane], "provider_id": lane, "system_owned": True}
        for lane in ("stockbit_commentary", "unboxing", "unboxing_ipo", "ai_reports_stockbit")
    ),
)

COMPATIBILITY = (
    *((endpoint["id"], "swing_chart_context") for endpoint in ENDPOINTS if endpoint["platform"] == "x"),
    ('x:kutekians', 'company_news'),
    ('x:kutekians', 'macro_news'),
    ('x:rickyho_1989', 'company_news'),
    ('x:rickyho_1989', 'macro_news'),
    ('x:writingtorch', 'company_news'),
    ('x:writingtorch', 'macro_news'),
    ('x:arvinhonami', 'company_news'),
    ('x:arvinhonami', 'macro_news'),
    ('x:insidertrackx', 'company_news'),
    ('x:insidertrackx', 'macro_news'),
    ('x:doktermarket', 'company_news'),
    ('x:doktermarket', 'macro_news'),
    ('x:txthariansaham', 'company_news'),
    ('x:txthariansaham', 'macro_news'),
    ('x:wavetiga', 'company_news'),
    ('x:wavetiga', 'macro_news'),
    ('x:aldotjahjadi8', 'company_news'),
    ('x:aldotjahjadi8', 'macro_news'),
    ('x:kobeissiletter', 'company_news'),
    ('x:kobeissiletter', 'macro_news'),
    ('instagram:beyondthefundamental', 'company_news'),
    ('instagram:beyondthefundamental', 'macro_news'),
    ('instagram:investart_id', 'company_news'),
    ('instagram:investart_id', 'macro_news'),
    ('instagram:avenirresearch.id', 'company_news'),
    ('instagram:avenirresearch.id', 'macro_news'),
    ('instagram:acresresearch', 'company_news'),
    ('instagram:acresresearch', 'macro_news'),
    ('instagram:sectorsapp', 'company_news'),
    ('instagram:sectorsapp', 'macro_news'),
    ('instagram:cukhurukuque', 'company_news'),
    ('instagram:cukhurukuque', 'macro_news'),
    ('instagram:notintofinance', 'company_news'),
    ('instagram:notintofinance', 'macro_news'),
    ('whatsapp:0029Vb6qi96ISTkJcDn4op2z', 'company_news'),
    ('whatsapp:0029Vb6qi96ISTkJcDn4op2z', 'macro_news'),
    ("telegram:phintraprofits", "trading_plans"),
    ("telegram:phintasprofits", "trading_plans"),
    ("telegram:phintasprofits", "company_news"),
    ("telegram:phintasprofits", "macro_news"),
    ("telegram:phintasprofits", "stock_status"),
    ("telegram:kelasinvestasiid", "swing_support"),
    ("telegram:tuntunsekuritas", "company_news"),
    ("telegram:tuntunsekuritas", "macro_news"),
    ("whatsapp:0029VbAjdnb60eBhwVdJxj1c", "swing_chart_context"),
    ("whatsapp:0029VbAjdnb60eBhwVdJxj1c", "company_news"),
    ("whatsapp:0029VbAjdnb60eBhwVdJxj1c", "macro_news"),
    *((f"rss:stockbit:{lane}", "stockbit_snips") for lane in ("stockbit_commentary", "unboxing", "unboxing_ipo", "ai_reports_stockbit")),
)

_ID = re.compile(r"[a-z0-9][a-z0-9-]{1,63}\Z")
_HANDLE = re.compile(r"[A-Za-z0-9_.]{1,64}\Z")
X_ROUTE_CAPABILITIES = ("company_news", "macro_news", "swing_chart_context")
USER_PLATFORM_CAPABILITIES = {
    "telegram": ("company_news", "macro_news"),
    "x": X_ROUTE_CAPABILITIES,
    "instagram": ("company_news", "macro_news"),
    "whatsapp": ("company_news", "macro_news"),
}
def _dispatch_group(platform: str, capability_id: str) -> str | None:
    return "x_post_route" if platform == "x" and capability_id in X_ROUTE_CAPABILITIES else None


class CatalogConflict(ValueError):
    pass


def initial_config() -> dict[str, Any]:
    return {"selected_securities": [], "people_org": [], "endpoints": [], "publisher_defaults": [], "endpoint_overrides": []}


def validate_config(config: object, registry: dict[str, Any]) -> dict[str, Any]:
    if type(config) is not dict or set(config) != set(initial_config()):
        raise ValueError("catalog config must contain exactly the five documented fields")
    if any(type(config[k]) is not list or len(config[k]) > 500 for k in config):
        raise ValueError("catalog fields must be bounded arrays")
    try:
        encoded = json.dumps(config, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError("catalog config must be finite JSON") from exc
    if len(encoded) > 256_000:
        raise ValueError("catalog config exceeds 256 KB")
    symbols = {x["symbol"] for x in registry["securities"]}
    selected = config["selected_securities"]
    if any(type(x) is not str or x not in symbols for x in selected) or len(set(selected)) != len(selected):
        raise ValueError("selected_securities must contain unique engine-supported symbols")
    publishers = {x["id"]: x for x in registry["institutions"] + registry["people_org"]}
    for person in config["people_org"]:
        if type(person) is not dict or set(person) != {"id", "name", "kind", "asset_ref"}:
            raise ValueError("people_org entry has invalid fields")
        if type(person["id"]) is not str or not _ID.fullmatch(person["id"]) or person["id"] in publishers:
            raise ValueError("people_org identity is duplicate or invalid")
        if person["kind"] not in ("person", "group", "community") or type(person["name"]) is not str or not 1 <= len(person["name"].strip()) <= 120:
            raise ValueError("people_org name or kind is invalid")
        _asset_ref(person["asset_ref"])
        publishers[person["id"]] = person
    endpoints = {x["id"]: x for x in registry["endpoints"]}
    for endpoint in config["endpoints"]:
        if type(endpoint) is not dict or set(endpoint) != {"id", "publisher_id", "platform", "address", "credential_ref"}:
            raise ValueError("endpoint has invalid fields")
        if type(endpoint["id"]) is not str or not _ID.fullmatch(endpoint["id"]) or endpoint["id"] in endpoints:
            raise ValueError("endpoint identity is duplicate or invalid")
        if endpoint["publisher_id"] not in publishers or endpoint["publisher_id"] in {x["id"] for x in registry["institutions"]}:
            raise ValueError("new endpoints require a People & Org publisher")
        platform, address = endpoint["platform"], endpoint["address"]
        if platform not in ("telegram", "x", "instagram", "whatsapp") or type(address) is not str or not _HANDLE.fullmatch(address):
            raise ValueError("endpoint platform or canonical handle is invalid")
        if any(e["platform"] == platform and e["address"].casefold() == address.casefold() for e in endpoints.values()):
            raise ValueError("endpoint canonical address already exists")
        ref = endpoint["credential_ref"]
        if ref is not None and (type(ref) is not str or not re.fullmatch(r"credential:[a-z0-9][a-z0-9-]{1,63}", ref)):
            raise ValueError("credential_ref must be a managed credential reference")
        endpoints[endpoint["id"]] = {**endpoint, "verified": False}
    capabilities = {x["id"] for x in registry["capabilities"]}
    compatibility = {(x["endpoint_id"], x["capability_id"]) for x in registry["compatibility"]}
    compatibility.update((e["id"], capability) for e in config["endpoints"] for capability in USER_PLATFORM_CAPABILITIES[e["platform"]])
    for field, owner_key in (("publisher_defaults", "publisher_id"), ("endpoint_overrides", "endpoint_id")):
        seen = set()
        for item in config[field]:
            if type(item) is not dict or set(item) != {owner_key, "capability_id", "enabled", "settings"}:
                raise ValueError(f"{field} entry has invalid fields")
            owner, capability = item[owner_key], item["capability_id"]
            if capability not in capabilities or type(item["enabled"]) is not bool or type(item["settings"]) is not dict or item["settings"]:
                raise ValueError("capability, enabled or settings is invalid")
            key = (owner, capability)
            if key in seen:
                raise ValueError("duplicate capability setting")
            seen.add(key)
            if field == "publisher_defaults":
                if owner not in publishers or not any((e["id"], capability) in compatibility for e in endpoints.values() if e["publisher_id"] == owner):
                    raise ValueError("publisher capability has no compatible endpoint")
            elif key not in compatibility:
                raise ValueError("unsupported endpoint/capability pair")
    return deepcopy(config)


def _asset_ref(value: object) -> None:
    if value is None:
        return
    if type(value) is not dict or set(value) != {"url", "kind"} or value["kind"] not in ("logo", "profile_picture", "banner"):
        raise ValueError("asset_ref must contain a supported kind and URL")
    url = value["url"]
    if type(url) is not str or len(url) > 2048 or urlparse(url).scheme != "https" or not urlparse(url).hostname or urlparse(url).username or urlparse(url).password:
        raise ValueError("asset_ref must be an HTTPS public URL")


def effective_snapshot(config: dict[str, Any], registry: dict[str, Any], revision: int, updated_at: str) -> dict[str, Any]:
    defaults = {(x["publisher_id"], x["capability_id"]): x for x in config["publisher_defaults"]}
    overrides = {(x["endpoint_id"], x["capability_id"]): x for x in config["endpoint_overrides"]}
    endpoints = {x["id"]: x for x in registry["endpoints"]}
    result = []
    for pair in registry["compatibility"]:
        endpoint = endpoints[pair["endpoint_id"]]
        key = (endpoint["id"], pair["capability_id"])
        inherited = defaults.get((endpoint["publisher_id"], pair["capability_id"]))
        chosen = overrides.get(key) or inherited
        result.append({"endpoint_id": key[0], "publisher_id": endpoint["publisher_id"], "platform": endpoint["platform"], "address": endpoint["address"], "provider_id": endpoint.get("provider_id"), "credential_ref": endpoint.get("credential_ref"), "capability_id": key[1], "pipeline": next(x["pipeline"] for x in registry["capabilities"] if x["id"] == key[1]), "dispatch_group": pair["dispatch_group"], "enabled": bool(chosen and chosen["enabled"] and endpoint.get("system_owned", False)), "verification_status": "verified" if endpoint.get("system_owned", False) else "pending", "settings": chosen["settings"] if chosen else {}, "source": "endpoint_override" if key in overrides else "publisher_default" if inherited else "unset"})
    return {"revision": revision, "updated_at": updated_at, "selected_securities": config["selected_securities"], "subscriptions": result}


def snapshot(config: dict[str, Any], revision: int, actor_id: str, updated_at: str | None = None) -> dict[str, Any]:
    return {"revision": revision, "config": deepcopy(config), "sha256": hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(), "actor_id": actor_id, "updated_at": updated_at or datetime.now(timezone.utc).isoformat()}


def registry() -> dict[str, Any]:
    endpoint_platforms = {endpoint["id"]: endpoint["platform"] for endpoint in ENDPOINTS}
    return {
        "securities": deepcopy(list(SECURITIES)),
        "institutions": deepcopy(list(INSTITUTIONS)),
        "people_org": deepcopy(list(PEOPLE_ORG)),
        "endpoints": deepcopy(list(ENDPOINTS)),
        "capabilities": deepcopy(list(CAPABILITIES)),
        "compatibility": [
            {"endpoint_id": endpoint_id, "capability_id": capability_id, "dispatch_group": _dispatch_group(endpoint_platforms[endpoint_id], capability_id)}
            for endpoint_id, capability_id in COMPATIBILITY
        ],
    }


def catalog_view(config: dict[str, Any], base: dict[str, Any] | None = None) -> dict[str, Any]:
    result = deepcopy(base) if base is not None else registry()
    result["institutions"] = [{**item, "asset_ref": item.get("asset_ref")} for item in result["institutions"]]
    result["people_org"] = [{**item, "asset_ref": item.get("asset_ref")} for item in result["people_org"]]
    result["people_org"].extend({**deepcopy(item), "tier": 3} for item in config["people_org"])
    result["endpoints"] = [
        {**endpoint, "provider_id": endpoint.get("provider_id"), "credential_ref": endpoint.get("credential_ref"), "verified": bool(endpoint["system_owned"])}
        for endpoint in result["endpoints"]
    ]
    result["endpoints"].extend({**deepcopy(item), "provider_id": None, "system_owned": False, "verified": False} for item in config["endpoints"])
    result["compatibility"].extend(
        {"endpoint_id": endpoint["id"], "capability_id": capability, "dispatch_group": _dispatch_group(endpoint["platform"], capability)}
        for endpoint in config["endpoints"]
        for capability in USER_PLATFORM_CAPABILITIES[endpoint["platform"]]
    )
    return result


class MemoryCatalogStore:
    def __init__(self) -> None:
        self._revisions = [snapshot(initial_config(), 1, "source-baseline")]
        self.audit: list[dict[str, Any]] = []

    def get(self) -> dict[str, Any]:
        return deepcopy(self._revisions[-1])

    def registry(self) -> dict[str, Any]:
        return registry()

    def put(self, expected_revision: int, config: dict[str, Any], actor_id: str) -> dict[str, Any]:
        if expected_revision != self._revisions[-1]["revision"]:
            raise CatalogConflict("stale source catalog revision")
        validated = validate_config(config, registry())
        record = snapshot(validated, expected_revision + 1, actor_id)
        self._revisions.append(record)
        self.audit.append({"revision": record["revision"], "actor_id": actor_id, "action": "catalog.put", "config_sha256": record["sha256"]})
        return deepcopy(record)


class PostgresCatalogStore:
    def __init__(self, dsn: str, *, pool: Any | None = None) -> None:
        self.dsn = dsn
        self.pool = pool

    def _connect(self):
        if self.pool is not None:
            return self.pool.connection()
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.dsn, row_factory=dict_row)

    @staticmethod
    def _decode(row: dict[str, Any]) -> dict[str, Any]:
        return {"revision": row["revision"], "config": row["config"], "sha256": row["config_sha256"], "actor_id": row["actor_id"], "updated_at": row["created_at"].isoformat()}

    def get(self, *, connection=None) -> dict[str, Any]:
        with (nullcontext(connection) if connection is not None else self._connect()) as conn:
            row = conn.execute("select revision, config, config_sha256, actor_id, created_at from bursawatch_source_catalog_revisions order by revision desc limit 1").fetchone()
        if row is None:
            raise RuntimeError("source catalog baseline migration is missing")
        return self._decode(row)

    def registry(self, *, connection=None) -> dict[str, Any]:
        with (nullcontext(connection) if connection is not None else self._connect()) as conn:
            securities = conn.execute("select symbol, name, exchange from bursawatch_supported_securities order by symbol").fetchall()
            publishers = conn.execute("select publisher_id as id, category, name, kind, source_tier as tier from bursawatch_source_publishers order by publisher_id").fetchall()
            endpoints = conn.execute("select endpoint_id as id, publisher_id, platform, address, provider_id, system_owned from bursawatch_source_endpoints order by endpoint_id").fetchall()
            capabilities = conn.execute("select capability_id as id, label, pipeline_id as pipeline, capability_version as version from bursawatch_source_capabilities order by capability_id").fetchall()
            compatibility = conn.execute("select endpoint_id, capability_id, dispatch_group from bursawatch_source_compatibility order by endpoint_id, capability_id").fetchall()
        return {
            "securities": securities,
            "institutions": [{k: v for k, v in row.items() if k != "category"} for row in publishers if row["category"] == "institution"],
            "people_org": [{k: v for k, v in row.items() if k != "category"} for row in publishers if row["category"] == "people_org"],
            "endpoints": endpoints,
            "capabilities": capabilities,
            "compatibility": compatibility,
        }

    def put(self, expected_revision: int, config: dict[str, Any], actor_id: str) -> dict[str, Any]:
        validated = validate_config(config, self.registry())
        with self._connect() as conn:
            conn.execute("select pg_advisory_xact_lock(71938142)")
            current = conn.execute("select revision from bursawatch_source_catalog_revisions order by revision desc limit 1").fetchone()
            if current is None or current["revision"] != expected_revision:
                raise CatalogConflict("stale source catalog revision")
            record = snapshot(validated, expected_revision + 1, actor_id)
            row = conn.execute("insert into bursawatch_source_catalog_revisions (revision, config, config_sha256, actor_id) values (%s, %s::jsonb, %s, %s) returning revision, config, config_sha256, actor_id, created_at", (record["revision"], json.dumps(validated, ensure_ascii=False), record["sha256"], actor_id)).fetchone()
            revision = record["revision"]
            for symbol in validated["selected_securities"]:
                conn.execute("insert into bursawatch_source_selections (revision, symbol) values (%s, %s)", (revision, symbol))
            for person in validated["people_org"]:
                conn.execute("insert into bursawatch_source_people_org_revisions (revision, publisher_id, name, kind, asset_ref) values (%s, %s, %s, %s, %s::jsonb)", (revision, person["id"], person["name"], person["kind"], json.dumps(person["asset_ref"])))
                if person["asset_ref"] is not None:
                    conn.execute("insert into bursawatch_source_asset_refs (revision, publisher_id, asset_kind, public_url, provenance) values (%s, %s, %s, %s, 'operator-reference')", (revision, person["id"], person["asset_ref"]["kind"], person["asset_ref"]["url"]))
            for endpoint in validated["endpoints"]:
                conn.execute("insert into bursawatch_source_endpoint_revisions (revision, endpoint_id, publisher_id, platform, address, credential_ref) values (%s, %s, %s, %s, %s, %s)", (revision, endpoint["id"], endpoint["publisher_id"], endpoint["platform"], endpoint["address"], endpoint["credential_ref"]))
            for setting in validated["publisher_defaults"]:
                conn.execute("insert into bursawatch_source_publisher_defaults (revision, publisher_id, capability_id, enabled, settings) values (%s, %s, %s, %s, %s::jsonb)", (revision, setting["publisher_id"], setting["capability_id"], setting["enabled"], json.dumps(setting["settings"])))
            for setting in validated["endpoint_overrides"]:
                conn.execute("insert into bursawatch_source_endpoint_overrides (revision, endpoint_id, capability_id, enabled, settings) values (%s, %s, %s, %s, %s::jsonb)", (revision, setting["endpoint_id"], setting["capability_id"], setting["enabled"], json.dumps(setting["settings"])))
            conn.execute("insert into bursawatch_source_catalog_audit (revision, actor_id, action, details) values (%s, %s, 'catalog.put', %s::jsonb)", (record["revision"], actor_id, json.dumps({"previous_revision": expected_revision, "config_sha256": record["sha256"]})))
        return self._decode(row)
