import ast
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cron-x-account-watch" / "bin"))
sys.path.insert(0, str(ROOT / "lib-news-classification" / "bin"))
import agent_feedback
from agent_feedback import GENERIC, JSON_GUIDANCE, guidance_for, retry_note

# Functions whose ValueError messages an agent can trigger by what it submits.
_SOURCES = {
    "cron-x-account-watch/bin/agent_protocol.py": {"validate_summary", "validate_title", "normalize_route", "validate_route", "validate_submission"},
    "lib-news-classification/bin/news_subject.py": {"_text", "validate_subject", "route_for", "validate_route", "validate_ticker", "require_company_details"},
    "cron-x-account-watch/bin/state.py": {"awaiting_analysis_event"},
}


def _messages():
    found = []
    for relative, names in _SOURCES.items():
        tree = ast.parse((ROOT / relative).read_text())
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef) or function.name not in names:
                continue
            for node in ast.walk(function):
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "ValueError" and node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        found.append(arg.value)
                    elif isinstance(arg, ast.JoinedStr):
                        parts = [p.value if isinstance(p, ast.Constant) else "X" for p in arg.values]
                        found.append("".join(parts))
    return sorted(set(found))


def test_every_agent_triggerable_validator_message_has_specific_guidance():
    messages = _messages()
    assert len(messages) > 30                                   # the scan really found the validators
    # "X" stands in for an f-string field, so allow it to resolve against the real wording.
    unguided = [m for m in messages if guidance_for(ValueError(m.replace("subject X", "subject name").replace("company X", "company business_home").replace("to X characters", "to 120 characters"))) == GENERIC]
    assert unguided == [], f"add guidance in agent_feedback.py for: {unguided}"


def test_guidance_is_plain_actionable_text_without_em_dashes():
    for _, text in agent_feedback._RULES:
        assert "—" not in text and text.strip() and len(text) < 600


def test_quote_rejection_names_the_exact_mistake_the_agent_made():
    text = guidance_for(ValueError("subject evidence must be quoted from supplied source text"))
    assert "character for character" in text and "Bursa Efek Indonesia (BEI)" in text and "Rp 28" in text


def test_title_guidance_reports_the_real_limits():
    assert "between 5 and 120" in guidance_for(ValueError("title must be from 5 to 120 characters"))


def test_malformed_json_gets_its_own_guidance():
    try:
        json.loads('{"a": "line\nbreak"}')
    except json.JSONDecodeError as error:
        assert guidance_for(error) == JSON_GUIDANCE and "\\n" in JSON_GUIDANCE


def test_unknown_error_falls_back_to_a_generic_fix():
    assert guidance_for(ValueError("something new")) == GENERIC


@pytest.mark.parametrize("event,expected", [
    ({}, ""),
    ({"agent_rejections": 0, "agent_last_rejection": "x"}, ""),
    ({"agent_rejections": 2, "agent_last_rejection": "Copy exactly."},
     "Scanner note: your previous submission for this item was rejected (2 of 3 allowed). Fix: Copy exactly. Correct only that problem and submit once more. After 3 rejections the item is skipped. "),
])
def test_retry_note_only_appears_after_a_rejection(event, expected):
    assert retry_note(event) == expected
