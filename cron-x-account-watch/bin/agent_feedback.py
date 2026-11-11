"""Agent-facing guidance for rejected X analysis submissions, and the retry cap.

A validator message says what failed. The guidance here says how to fix it, in the words the agent needs.
Every message is a fixed string from the validators (never source text), so it is safe to hand back to a later
agent run. `tests/test_agent_feedback.py` fails when a validator raises a message that has no guidance here.
"""
from __future__ import annotations

import json
import re

MAX_REJECTIONS = 3

GENERIC = ("The scanner rejected this submission. Re-read the item's contract, fix the field the error names using only "
           "the supplied text, and resubmit.")
JSON_GUIDANCE = ("The payload was not one valid JSON object. Send exactly one JSON object inside single quotes, escape every "
                 "quote and line break inside a string (write \\n for a line break), and put nothing before or after it.")

_SUBJECT = ("subject needs exactly kind, name and evidence, plus company for a company or industry for an industry. ")
_COMPANY = ("company needs exactly business_home (ID, US, GLOBAL or UNKNOWN), listing_status (listed, private, pre_ipo, "
            "formerly_listed or unknown) and security_market (ID, US or an empty string). ")

# Ordered: the first matching pattern wins, so specific messages come before general ones.
_RULES: tuple[tuple[str, str], ...] = (
    (r"^analysis submission must be an object", "Send one JSON object, not a list or plain text."),
    (r"^(analysis submission requires an event_key|event_key (must be text|is invalid))",
     "Copy item.event_key exactly as supplied, as text."),
    (r"^analysis profile is not enabled", "This account does not take analysis submissions. Do not resubmit."),
    (r"^analysis event is not (awaiting the agent|in durable state)",
     "This item is no longer waiting for your answer (its lease ended or it was already settled). Stop; do not resubmit."),
    (r"^relevant item submission has unexpected fields",
     "For a relevant post send exactly event_key, is_relevant set to true, and items. Put title, summary and route inside each item, not at the top level."),
    (r"^items require generated titles", "This account does not take an items list. Use the single-item form it asked for."),
    (r"^items must contain one to sixteen", "Send between 1 and 16 items."),
    (r"^news item has unexpected fields",
     "Each item has exactly title, summary and route, plus subject and ticker for news. Remove any other key and do not leave one out."),
    (r"^multi-item schema supports news routes only",
     "An items list may only use news routes (company, industry or macro). Send a swing post on its own, in the scalar form."),
    (r"^analysis submission has unexpected or missing fields",
     "Send only the fields this item asked for. An irrelevant post is exactly {event_key, is_relevant: false}. A relevant post is event_key, is_relevant: true and items."),
    (r"^is_relevant must be a boolean", "is_relevant must be the JSON value true or false, not text."),
    (r"^summary must", "summary must be non-empty text within the length limit. Shorten it and keep it plain text."),
    (r"^title must be from (\d+) to (\d+) characters", "Rewrite the title so it is between {0} and {1} characters on a single line."),
    (r"^title must be text", "title must be a string."),
    (r"^title must be a plain headline", "Remove any link from the title, and do not end it with . ! or ?."),
    (r"^route must be a configured channel key",
     "route must be exactly one of the channel keys listed for this account in the item instruction. Do not invent or rename a key."),
    (r"^(route conflicts with the classified subject|subject company route is invalid)",
     "The route must follow the subject. A company goes by business_home (ID, US, or global for GLOBAL and UNKNOWN), an industry by its region, and macro news to macro_news. Make the subject and route agree."),
    (r"^subject has an unexpected schema", _SUBJECT + "Remove any other key."),
    (r"^subject kind must be", "kind must be exactly company, industry or macro."),
    (r"^subject name must", "name must be text of 1 to 200 characters."),
    (r"^subject evidence must be quoted from supplied source text",
     "Copy evidence character for character from the supplied post or linked article. Keep the original parentheses, quotes, punctuation and numbers "
     "(\"Bursa Efek Indonesia (BEI)\" is not \"BEI\", and \"Rp 28\" is not \"Rp28\"). Do not translate, shorten with \"...\", or join separate sentences. "
     "Only letter case and spacing may differ. Pick one short exact span."),
    (r"^subject evidence must", "evidence must be text of 1 to 1000 characters. Copy a shorter exact span."),
    (r"^subject company name must be present in supplied source text",
     "For a company subject, name must appear in the supplied text exactly as the source writes it (case and spacing aside). Do not use a legal name, translation or abbreviation the text lacks."),
    (r"^company details have an unexpected schema", _COMPANY + "Remove any other key."),
    (r"^company (business_home|listing_status|security_market) is invalid", _COMPANY + "Use only those values."),
    (r"^only currently listed companies may identify a security market",
     "Set security_market to an empty string unless listing_status is listed."),
    (r"^industry details have an unexpected schema", "industry needs exactly region, and nothing else."),
    (r"^industry region is invalid", "region must be ID, US, GLOBAL or UNKNOWN."),
    (r"^new company news requires separate company and security details",
     "Add the company block to the subject: " + _COMPANY),
    (r"^ticker must be text", "ticker must be a string. Use an empty string when there is no verified ticker."),
    (r"^ticker has an invalid exchange format",
     "An ID ticker is exactly 4 capital letters. A US ticker is 1 to 20 characters of capitals, digits, . or -. Use an empty string if unsure."),
    (r"^ticker must be established in supplied source evidence|^ticker requires supplied source evidence",
     "Use a ticker only if it appears in the supplied text or lookup-company verified it. Otherwise use an empty string and keep the company name."),
    (r"^noncompany subject cannot have a ticker", "An industry or macro subject has no ticker. Use an empty string."),
)
_COMPILED = tuple((re.compile(pattern), text) for pattern, text in _RULES)


class AgentRejection(ValueError):
    """A rejected submission, carrying the fix and how many rejections this item has now had."""

    def __init__(self, message: str, guidance: str, attempts: int, final: bool):
        super().__init__(message)
        self.guidance = guidance
        self.attempts = attempts
        self.final = final


def guidance_for(error: BaseException) -> str:
    """Return the fixed, agent-facing fix for a validator error."""
    if isinstance(error, json.JSONDecodeError):
        return JSON_GUIDANCE
    message = " ".join(str(error).split())
    for pattern, text in _COMPILED:
        match = pattern.search(message)
        if match:
            return text.format(*match.groups()) if "{" in text and match.groups() else text
    return GENERIC


def retry_note(event: dict) -> str:
    """The note appended to the next wake instruction after this item was rejected."""
    attempts = event.get("agent_rejections")
    guidance = event.get("agent_last_rejection")
    if type(attempts) is not int or attempts < 1 or type(guidance) is not str or not guidance:
        return ""
    return (f"Scanner note: your previous submission for this item was rejected ({attempts} of {MAX_REJECTIONS} allowed). "
            f"Fix: {guidance} Correct only that problem and submit once more. After {MAX_REJECTIONS} rejections the item is skipped. ")
