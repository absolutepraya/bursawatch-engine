"""Closed saved Swing presentation, without delivery or Board authority."""
from __future__ import annotations
import re
from typing import Mapping
from swing_format import discord_length


def valid_presentation(value: object) -> bool:
    if (not isinstance(value, dict) or set(value) != {"version","fields","messages","destination"}
            or type(value["version"]) is not int or value["version"] != 2
            or not isinstance(value["destination"],str) or re.fullmatch(r"[0-9]{17,20}",value["destination"]) is None
            or not isinstance(value["messages"],list) or not value["messages"] or len(value["messages"])>32
            or any(not isinstance(text,str) or not text or discord_length(text)>2000 for text in value["messages"])
            or not isinstance(value["fields"],list) or len(value["fields"])>32):
        return False
    return all(isinstance(field,dict) and set(field)=={"label","value","source_start","source_end"}
               and isinstance(field["label"],str) and isinstance(field["value"],str)
               and type(field["source_start"]) is int and type(field["source_end"]) is int
               and 0<=field["source_start"]<field["source_end"] for field in value["fields"])


def saved_presentation(event: Mapping[str, object]) -> dict | None:
    value = event.get("presentation")
    if value is None and "presentation" not in event:
        return None
    if not valid_presentation(value):
        raise ValueError("saved Swing presentation is invalid")
    return value


def without_board(messages: list[str]) -> list[str]:
    pattern = re.compile(r"^\*\*Board:\*\*[^\n]*\n?",re.MULTILINE)
    return [pattern.sub("",message) for message in messages]
