"""Source-grounded subject contracts for ordinary news, without I/O or sends."""
from __future__ import annotations

from collections.abc import Mapping
import re


CONTRACT = "subject-v2"
LEGACY_CONTRACT = "subject-v1"
COMPANY_ROUTES = frozenset({"id_stocks_news", "us_stocks_news", "global_company_news"})
INDUSTRY_ROUTES = frozenset({"id_industry_news", "us_industry_news", "global_industry_news"})
GEOGRAPHIC_NEWS_ROUTES = COMPANY_ROUTES | INDUSTRY_ROUTES
INDUSTRY_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["region"],
    "properties": {"region": {"type": "string", "enum": ["ID", "US", "GLOBAL", "UNKNOWN"]}}}
COMPANY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["business_home", "listing_status", "security_market"],
    "properties": {
        "business_home": {"type": "string", "enum": ["ID", "US", "GLOBAL", "UNKNOWN"]},
        "listing_status": {"type": "string", "enum": ["listed", "private", "pre_ipo", "formerly_listed", "unknown"]},
        "security_market": {"type": "string", "enum": ["ID", "US", ""]},
    },
}
KINDS = frozenset({"company", "industry", "macro"})
SUBJECT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "name", "evidence"],
    "properties": {
        "kind": {"type": "string", "enum": sorted(KINDS)},
        "company": COMPANY_SCHEMA,
        "industry": INDUSTRY_SCHEMA,
        "name": {"type": "string", "minLength": 1, "maxLength": 200},
        "evidence": {"type": "string", "minLength": 1, "maxLength": 1000},
    },
}
INSTRUCTION = (
    "Classify each ordinary news item's actual central subject from the complete supplied evidence, before choosing "
    "a channel or resolving a security. Return subject with kind, name, evidence, and company for company news or industry for industry news only. Kind is company, industry, "
    "or macro; name identifies the central company, industry, or economic subject. Evidence is a short exact quotation "
    "from supplied authored text or retrieved article context supporting that subject. Do not invent evidence. "
    "Company means the central development concerns a particular company's business, earnings, guidance, contracts, "
    "ownership, financing, valuation, or corporate action. Sector background, economic context, and other company "
    "mentions do not turn its own development into an industry or macro story. A connected company transaction stays "
    "one company story. Where the owner supports multiple items, split independent company developments into ordered items; a mixed list is not a macro story. For a scalar-only owner, classify the most material central story in that bounded candidate instead of inventing a combined Macro story. "
    "Industry means the central development concerns an industry or sector as a whole, such as demand, production, "
    "capacity, supply chains, industry regulation, or sector-wide economics. Companies mentioned as examples, affected "
    "members, or top picks do not turn an industry thesis into company news. An industry-focused policy is industry "
    "news even when announced by a government. Do not select macro merely because an industry has many companies. "
    "Macro means an economy-wide, market-wide, cross-industry, or cross-asset development, such as general inflation, "
    "monetary or fiscal policy, currencies, aggregate liquidity, or the overall stock market. Company examples alone "
    "do not change a genuinely broad thesis. A commodity-price headline is classified by its central economic scope, "
    "not by the presence of a commodity word. Source brand, headline template, capital letters, ticker position, "
    "number of tickers, and source section labels are context, never the subject classification. "
    "Company news covers substantive developments about public, private, pre-IPO, and formerly listed companies worldwide. Every company card has exactly one focus company; counterparties are context, not duplicate transaction cards. For a company subject, include company with exactly business_home, listing_status, security_market. business_home is ID, US, GLOBAL (other countries), or UNKNOWN; use the principal business home supported by evidence, never the listing exchange, legal shell, source language or publisher location. When uncertain choose UNKNOWN. listing_status is listed, private, pre_ipo, formerly_listed, or unknown. security_market is ID, US, or empty, separately from business_home, and is nonempty only for a verified current focus-company listing. Never inherit a parent or counterparty security. Company maps by business_home to id_stocks_news for ID, us_stocks_news for US, or global_company_news for GLOBAL/UNKNOWN; For industry subjects include industry with exactly region: ID, US, GLOBAL, or UNKNOWN. Classify the central industry market from supplied evidence: Indonesia to id_industry_news, US to us_industry_news, other countries or genuinely cross-border/global to global_industry_news. Unknown region also uses Global without inventing a country. Publisher location, source language, currency and example company listing do not establish industry geography. US sector indices and industry-wide US company aggregates are US; Malaysian palm oil or global oil shipping are Global, even with Indonesian investors affected. Macro maps to macro_news. "
    "Never use Macro News as a fallback for an unknown company, missing ticker, unavailable quote, or unavailable "
    "destination. Keep a clearly named company in Company News when its ticker cannot be established: use its source "
    "name, leave ticker empty, and do not invent a ticker or price tracker. Resolve a ticker only from reliable supplied or owner-verified identity-lookup "
    "evidence; a ticker hint is optional evidence, not a classification. Existing relevance exclusions, configured "
    "market coverage, and specialized Swing/status contracts still apply. "
)


def _text(value: object, label: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"subject {label} must be text")
    value = " ".join(value.split())
    if not value or len(value) > limit:
        raise ValueError(f"subject {label} must contain bounded nonempty text")
    return value


def validate_subject(value: object, source_text: str | None = None) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) not in [{"kind", "name", "evidence"}, {"kind", "name", "evidence", "company"}, {"kind", "name", "evidence", "industry"}]:
        raise ValueError("subject has an unexpected schema")
    kind = value["kind"]
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("subject kind must be company, industry, or macro")
    result = {"kind": kind, "name": _text(value["name"], "name", 200),
              "evidence": _text(value["evidence"], "evidence", 1000)}
    if "company" in value:
        company = value["company"]
        if kind != "company" or not isinstance(company, Mapping) or set(company) != set(COMPANY_SCHEMA["required"]):
            raise ValueError("company details have an unexpected schema")
        for key, field in COMPANY_SCHEMA["properties"].items():
            if not isinstance(company[key], str) or company[key] not in field["enum"]:
                raise ValueError(f"company {key} is invalid")
        if company["listing_status"] != "listed" and company["security_market"]:
            raise ValueError("only currently listed companies may identify a security market")
        result["company"] = dict(company)
    if "industry" in value:
        industry = value["industry"]
        if kind != "industry" or not isinstance(industry, Mapping) or set(industry) != {"region"}:
            raise ValueError("industry details have an unexpected schema")
        if not isinstance(industry["region"], str) or industry["region"] not in {"ID", "US", "GLOBAL", "UNKNOWN"}:
            raise ValueError("industry region is invalid")
        result["industry"] = dict(industry)
    if source_text is not None:
        source = " ".join(source_text.split()).casefold()
        if result["evidence"].casefold() not in source:
            raise ValueError("subject evidence must be quoted from supplied source text")
        if kind == "company" and result["name"].casefold() not in source:
            raise ValueError("subject company name must be present in supplied source text")
    return result


def route_for(subject: Mapping[str, str], *, company_route: str = "id_stocks_news") -> str:
    kind = validate_subject(subject)["kind"]
    if company_route not in COMPANY_ROUTES:
        raise ValueError("subject company route is invalid")
    if kind == "company" and "company" in subject:
        company_route = {"ID": "id_stocks_news", "US": "us_stocks_news"}.get(subject["company"]["business_home"], "global_company_news")
    industry_route = {"ID": "id_industry_news", "US": "us_industry_news"}.get(subject.get("industry", {}).get("region"), "global_industry_news") if "industry" in subject else "id_industry_news"
    return {"company": company_route, "industry": industry_route, "macro": "macro_news"}[kind]


def validate_route(subject: Mapping[str, str], route: str) -> str:
    company_route = route if route in COMPANY_ROUTES else "id_stocks_news"
    if route != route_for(subject, company_route=company_route):
        raise ValueError("route conflicts with the classified subject")
    return route


def validate_ticker(value: object, source_text: str, *, market: str = "ID", verified_ticker: str | None = None) -> str | None:
    if not isinstance(value, str):
        raise ValueError("ticker must be text")
    if not value:
        return None
    pattern = r"[A-Z]{4}" if market == "ID" else r"[A-Z][A-Z0-9.\-]{0,19}"
    if not re.fullmatch(pattern, value):
        raise ValueError("ticker has an invalid exchange format")
    if value == verified_ticker:
        return value
    if re.search(rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])", source_text) is None:
        raise ValueError("ticker must be established in supplied source evidence")
    return value


def lookup_instruction(wrapper: str) -> str:
    return (
        "When a company is clearly named but its ticker is missing, you may run only this bounded read-only "
        f"identity tool: \"$HOME/.hermes/scripts/{wrapper}\" lookup-company --json "
        "'{\"company\":\"<exact source company name>\",\"market\":\"ID\"}'. Use ID or US for supported current securities independently of the company destination. "
        "The tool searches Yahoo Finance and returns a verified unique company-name and exchange match, or unresolved. "
        "Use a verified result only for the ticker and exchange, never add lookup facts to the news summary. "
        "Do not guess from a search snippet. On unresolved, ambiguous, unavailable, or failed lookup, submit company-name "
        "Company News with an empty ticker and no tracker. The owner independently verifies externally proposed tickers. "
    )


def require_company_details(subject: Mapping) -> None:
    if subject["kind"] == "company" and "company" not in subject:
        raise ValueError("new company news requires separate company and security details")


def quote_route(subject: Mapping | None, fallback: str) -> str | None:
    if subject is not None and "company" in subject:
        company = subject["company"]
        return {"ID": "id_stocks_news", "US": "us_stocks_news"}.get(company["security_market"]) if company["listing_status"] == "listed" else None
    return fallback if fallback in {"id_stocks_news", "us_stocks_news"} else None


def ticker_market(subject: Mapping, fallback: str = "ID") -> str:
    if "company" in subject:
        return subject["company"]["security_market"] or fallback
    return fallback
