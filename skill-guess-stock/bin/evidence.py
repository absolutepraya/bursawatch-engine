"""Evidence normalization and path-comparison primitives for guess-stock.

The module deliberately has no network or model dependency. It turns visible
facts into a small, auditable manifest and provides the math used by the
candidate matcher.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
import re
from typing import Any, Iterable, Mapping, Sequence


EVIDENCE_KINDS = frozenset(
    {"chart", "keystats", "clue", "transaction", "social", "official-source", "other"}
)

_FIELD_ALIASES = {
    "close": "price",
    "current": "price",
    "current_price": "price",
    "last_price": "price",
    "volume_current": "volume",
    "current_volume": "volume",
    "avg_volume": "volume_average",
    "volume_avg": "volume_average",
    "volume_sma": "volume_average",
    "volume_average": "volume_average",
    "average_volume_10d_calc": "volume_average_10d",
    "average_volume_20d_calc": "volume_average",
    "macd_macd": "macd",
    "macd_line": "macd",
    "macd_signal": "macd_signal",
    "signal": "macd_signal",
    "histogram": "macd_hist",
    "macd_histogram": "macd_hist",
    "macd_hist": "macd_hist",
    "rsi_14": "rsi",
    "pivot_trace": "pivots",
    "path": "pivots",
    "trace": "pivots",
}

_SUFFIXES = {"K": 1_000.0, "M": 1_000_000.0, "B": 1_000_000_000.0, "T": 1_000_000_000_000.0}


def canonical_field_name(name: object) -> str:
    """Return the stable field name used by the matcher."""

    normalized = re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")
    return _FIELD_ALIASES.get(normalized, normalized)


def parse_number(value: object) -> float | None:
    """Parse common screenshot numbers without guessing non-numeric text."""

    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if isfinite(number) else None
    if not isinstance(value, str):
        return None

    text = value.strip().replace("−", "-")
    if not text:
        return None
    suffix = 1.0
    suffix_match = re.search(r"(?i)([kmbt])\s*$", text)
    if suffix_match:
        suffix = _SUFFIXES[suffix_match.group(1).upper()]
        text = text[: suffix_match.start()]

    text = re.sub(r"(?i)\b(?:rp|idr)\b", "", text)
    text = re.sub(r"[^0-9,.+-]", "", text)
    if not text or text in {"+", "-", ".", ","}:
        return None

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif text.count(",") == 1 and "." not in text:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")

    try:
        number = float(text) * suffix
    except ValueError:
        return None
    return number if isfinite(number) else None


def _normalize_value(name: str, value: object) -> object:
    if name == "pivots" and isinstance(value, str):
        value = [item for item in re.split(r"[\s,;]+", value.strip()) if item]
    if name == "pivots" and isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        parsed = tuple(number for number in (parse_number(item) for item in value) if number is not None)
        return parsed
    number = parse_number(value)
    return number if number is not None else value


@dataclass(frozen=True, slots=True)
class EvidenceField:
    name: str
    value: object
    kind: str
    source: str
    as_of: str | None

    def to_dict(self) -> dict[str, object]:
        value: object = list(self.value) if isinstance(self.value, tuple) else self.value
        return {
            "name": self.name,
            "value": value,
            "kind": self.kind,
            "source": self.source,
            "as_of": self.as_of,
        }


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    fields: tuple[EvidenceField, ...]
    as_of: str | None
    sources: tuple[str, ...]
    kinds: tuple[str, ...]
    issues: tuple[str, ...] = ()

    def values(self, name: str) -> tuple[object, ...]:
        canonical = canonical_field_name(name)
        return tuple(field.value for field in self.fields if field.name == canonical)

    def first(self, name: str) -> object | None:
        values = self.values(name)
        return values[0] if values else None

    def visible_names(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(field.name for field in self.fields))

    def to_dict(self) -> dict[str, object]:
        return {
            "as_of": self.as_of,
            "sources": list(self.sources),
            "kinds": list(self.kinds),
            "issues": list(self.issues),
            "fields": [field.to_dict() for field in self.fields],
        }


def normalize_evidence(items: Mapping[str, object] | Sequence[Mapping[str, object]]) -> EvidenceBundle:
    """Normalize raw evidence items while preserving unknown values as unknown.

    Each item is expected to contain `kind`, `source`, optional `as_of`, and a
    `fields` mapping. Fields marked `visible: false` or set to `None` are not
    treated as observations.
    """

    if isinstance(items, Mapping):
        nested_items = items.get("items")
        raw_items: Sequence[Mapping[str, object]] = (
            nested_items
            if isinstance(nested_items, Sequence) and not isinstance(nested_items, (str, bytes))
            else (items,)
        )
    else:
        raw_items = items

    fields: list[EvidenceField] = []
    sources: list[str] = []
    kinds: list[str] = []
    as_of_values: list[str] = []
    issues: list[str] = []

    for index, item in enumerate(raw_items):
        if not isinstance(item, Mapping):
            issues.append(f"item_{index}_not_mapping")
            continue
        kind = str(item.get("kind", "other")).strip().lower() or "other"
        if kind not in EVIDENCE_KINDS:
            issues.append(f"item_{index}_unknown_kind")
            kind = "other"
        source = str(item.get("source", "user-input")).strip() or "user-input"
        as_of = item.get("as_of")
        as_of_text = str(as_of).strip() if as_of is not None and str(as_of).strip() else None
        if as_of_text:
            as_of_values.append(as_of_text)
        if source not in sources:
            sources.append(source)
        if kind not in kinds:
            kinds.append(kind)

        raw_fields = item.get("fields", {})
        if not isinstance(raw_fields, Mapping):
            issues.append(f"item_{index}_fields_not_mapping")
            continue
        for raw_name, raw_value in raw_fields.items():
            if raw_value is None:
                continue
            if isinstance(raw_value, Mapping) and raw_value.get("visible") is False:
                continue
            value = raw_value.get("value") if isinstance(raw_value, Mapping) and "value" in raw_value else raw_value
            if value is None or (isinstance(raw_value, Mapping) and raw_value.get("visible") is False):
                continue
            name = canonical_field_name(raw_name)
            fields.append(EvidenceField(name, _normalize_value(name, value), kind, source, as_of_text))

    unique_as_of = tuple(dict.fromkeys(as_of_values))
    if len(unique_as_of) > 1:
        issues.append("conflicting_as_of")
    bundle_as_of = unique_as_of[0] if len(unique_as_of) == 1 else None
    return EvidenceBundle(tuple(fields), bundle_as_of, tuple(sources), tuple(kinds), tuple(issues))


def parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def compare_as_of(observed: object, candidate: object) -> str:
    observed_date = parse_date(observed)
    candidate_date = parse_date(candidate)
    if observed_date is None or candidate_date is None:
        return "unknown"
    return "exact" if observed_date == candidate_date else "mismatch"


def normalized_path(values: Iterable[object]) -> tuple[float, ...]:
    parsed = tuple(number for number in (parse_number(value) for value in values) if number is not None)
    if not parsed:
        return ()
    low, high = min(parsed), max(parsed)
    span = high - low
    if span == 0:
        return tuple(0.0 for _ in parsed)
    return tuple((value - low) / span for value in parsed)


def resample_path(values: Sequence[float], length: int) -> tuple[float, ...]:
    if length <= 0 or not values:
        return ()
    if len(values) == length:
        return tuple(values)
    if len(values) == 1:
        return tuple(values[0] for _ in range(length))
    result: list[float] = []
    for index in range(length):
        position = index * (len(values) - 1) / (length - 1)
        lower = int(position)
        upper = min(lower + 1, len(values) - 1)
        fraction = position - lower
        result.append(values[lower] + (values[upper] - values[lower]) * fraction)
    return tuple(result)


def normalized_mae(left: Sequence[object], right: Sequence[object]) -> float | None:
    left_path, right_path = normalized_path(left), normalized_path(right)
    if not left_path or not right_path:
        return None
    right_path = resample_path(right_path, len(left_path))
    return sum(abs(a - b) for a, b in zip(left_path, right_path)) / len(left_path)


def path_correlation(left: Sequence[object], right: Sequence[object]) -> float | None:
    left_path, right_path = normalized_path(left), normalized_path(right)
    if not left_path or not right_path:
        return None
    right_path = resample_path(right_path, len(left_path))
    left_mean = sum(left_path) / len(left_path)
    right_mean = sum(right_path) / len(right_path)
    left_delta = tuple(value - left_mean for value in left_path)
    right_delta = tuple(value - right_mean for value in right_path)
    left_norm = sum(value * value for value in left_delta) ** 0.5
    right_norm = sum(value * value for value in right_delta) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 1.0 if left_path == right_path else 0.0
    return sum(a * b for a, b in zip(left_delta, right_delta)) / (left_norm * right_norm)
