"""Source-grounded subject contracts for ordinary news, without I/O or sends."""
from __future__ import annotations

from collections.abc import Mapping
import re


CONTRACT = "subject-v1"
KINDS = frozenset({"company", "industry", "macro"})
SUBJECT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "name", "evidence"],
    "properties": {
        "kind": {"type": "string", "enum": sorted(KINDS)},
        "name": {"type": "string", "minLength": 1, "maxLength": 200},
        "evidence": {"type": "string", "minLength": 1, "maxLength": 1000},
    },
}
INSTRUCTION = (
    "Classify each ordinary news item's actual central subject from the complete supplied evidence, before choosing "
    "a channel or resolving a security. Return subject with exactly kind, name, and evidence. Kind is company, industry, "
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
    "Company maps to the appropriate Stock News route; industry maps to id_industry_news; macro maps to macro_news. "
    "Never use Macro News as a fallback for an unknown company, missing ticker, unavailable quote, or unavailable "
    "destination. Keep a clearly named company in Stock News when its ticker cannot be established: use its source "
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
    if not isinstance(value, Mapping) or set(value) != {"kind", "name", "evidence"}:
        raise ValueError("subject has an unexpected schema")
    kind = value["kind"]
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("subject kind must be company, industry, or macro")
    result = {"kind": kind, "name": _text(value["name"], "name", 200),
              "evidence": _text(value["evidence"], "evidence", 1000)}
    if source_text is not None:
        source = " ".join(source_text.split()).casefold()
        if result["evidence"].casefold() not in source:
            raise ValueError("subject evidence must be quoted from supplied source text")
        if kind == "company" and result["name"].casefold() not in source:
            raise ValueError("subject company name must be present in supplied source text")
    return result


def route_for(subject: Mapping[str, str], *, company_route: str = "id_stocks_news") -> str:
    kind = validate_subject(subject)["kind"]
    if company_route not in {"id_stocks_news", "us_stocks_news"}:
        raise ValueError("subject company route is invalid")
    return {"company": company_route, "industry": "id_industry_news", "macro": "macro_news"}[kind]


def validate_route(subject: Mapping[str, str], route: str) -> str:
    company_route = route if route in {"id_stocks_news", "us_stocks_news"} else "id_stocks_news"
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
        "'{\"company\":\"<exact source company name>\",\"market\":\"ID\"}'. Use US only for configured US coverage. "
        "The tool searches Yahoo Finance and returns a verified unique company-name and exchange match, or unresolved. "
        "Use a verified result only for the ticker and exchange, never add lookup facts to the news summary. "
        "Do not guess from a search snippet. On unresolved, ambiguous, unavailable, or failed lookup, submit company-name "
        "Stock News with an empty ticker and no tracker. The owner independently verifies externally proposed tickers. "
    )
