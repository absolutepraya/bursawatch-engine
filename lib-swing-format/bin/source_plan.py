"""Validate LLM-selected evidence spans and display source plan levels without inference."""
from __future__ import annotations

from dataclasses import dataclass
import re

from swing_format import SwingField

_KEYS = {"label", "value", "source_start", "source_end"}
_LABEL = re.compile(r"(?:Entry|Stop-loss(?: [2-9][0-9]*| 1[0-9]+)?|Target [1-9][0-9]*)\Z")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_OPERATORS = re.compile(r"<=|>=|<|>|≤|≥")
_LEVEL = re.compile(r"(?:<=|>=|<|>|≤|≥)?\s*\d+(?:[.,]\d+)*(?:\s*[-–]\s*\d+(?:[.,]\d+)*)?\Z")
_SOURCE_LABEL = re.compile(r"^(watch\s+on|buy\s+area|entry|support\s+utama|stop[-\s]?loss\s*\d*|sl\s*\d*|target\s*\d*|tp\s*\d*)\b\s*:?\s*",re.IGNORECASE)


@dataclass(frozen=True)
class SourcePlanField:
    label: str
    value: str
    source_start: int
    source_end: int


@dataclass(frozen=True)
class PlanNormalization:
    fields: tuple[SourcePlanField, ...]
    rejected_count: int


def _supported(source: str, raw: object) -> SourcePlanField | None:
    if not isinstance(raw, dict) or set(raw) != _KEYS:
        return None
    label, value, start, end = (raw[key] for key in ("label","value","source_start","source_end"))
    if (not isinstance(label,str) or not _LABEL.fullmatch(label) or not isinstance(value,str)
            or not _LEVEL.fullmatch(value) or len(value)>100 or type(start) is not int
            or type(end) is not int or not 0 <= start < end <= len(source) or end-start>500):
        return None
    excerpt = source[start:end].strip().strip("*_ ")
    match = _SOURCE_LABEL.match(excerpt)
    if match is None:
        return None
    name = match.group(1).lower()
    evidence = excerpt[match.end():].strip().strip("*_ ")
    if not _LEVEL.fullmatch(evidence):
        return None
    number = re.search(r"\d+", name)
    if name.startswith(("target","tp")):
        expected = f'Target {int(number.group()) if number else 1}'
    elif name.startswith(("sl","stop")):
        expected = f'Stop-loss {int(number.group())}' if number and int(number.group()) >= 2 else "Stop-loss"
    elif name.startswith("support"):
        expected = "Stop-loss"
    else:
        expected = "Entry"
    if label != expected or _NUMBER.findall(value) != _NUMBER.findall(evidence):
        return None
    # This approved transform applies only to bare Support utama, not generic support.
    expected_operators = _OPERATORS.findall(evidence)
    if name == "support utama" and not expected_operators:
        expected_operators = ["<"]
    if _OPERATORS.findall(value) != expected_operators:
        return None
    # Do not turn an entry range into a point or alter its source range separator.
    if re.sub(r"\s+", "", value).lstrip("<") != re.sub(r"\s+", "", evidence).lstrip("<"):
        return None
    return SourcePlanField(label, value.strip(), start, end)


def validate_source_plan_fields(source_text: str, payload: object) -> PlanNormalization:
    if not isinstance(source_text,str) or not isinstance(payload,list) or len(payload)>32:
        return PlanNormalization((),1)
    accepted: dict[str, SourcePlanField] = {}
    conflicted: set[str] = set()
    rejected = 0
    for raw in payload:
        field = _supported(source_text,raw)
        if field is None:
            rejected += 1
        elif field.label in conflicted:
            rejected += 1
        elif field.label in accepted and accepted[field.label].value != field.value:
            accepted.pop(field.label)
            conflicted.add(field.label)
            rejected += 2
        else:
            accepted.setdefault(field.label,field)
    return PlanNormalization(tuple(accepted.values()),rejected)


def source_plan_display(fields: tuple[SourcePlanField, ...]) -> tuple[SwingField, ...]:
    values = {field.label:field.value for field in fields}
    targets = sorted({1, *(int(label.split()[-1]) for label in values if label.startswith("Target "))})
    stops = sorted(int(label.split()[-1]) for label in values if label.startswith("Stop-loss "))
    labels = ["Entry","Stop-loss",*(f"Target {number}" for number in targets),*(f"Stop-loss {number}" for number in stops)]
    return tuple(SwingField(label,values.get(label,"-")) for label in labels)


def fields_from_canonical_message(content: str) -> tuple[SourcePlanField, ...]:
    """Only already canonical fields, never publisher synonyms or Board evaluation data."""
    result = []
    pattern = re.compile(r"^\*\*(Entry|Stop-loss(?: [2-9][0-9]*| 1[0-9]+)?|Target [1-9][0-9]*):\*\*\s*(.+)$",re.MULTILINE)
    for match in pattern.finditer(content):
        value = match.group(2).strip()
        if _LEVEL.fullmatch(value):
            result.append(SourcePlanField(match.group(1),value,match.start(),match.end()))
    return tuple(result)
