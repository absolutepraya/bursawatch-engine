from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

import requests

import render


CANDIDATE_WINDOW = timedelta(hours=1)
USER_AGENT = "Mozilla/5.0 (X-post-watch; +https://x.com/)"
EDIT_IDS_RE = re.compile(r"edit_tweet_ids(?::\$R\[\d+\])?=\[([^\]]*)\]")
ID_RE = re.compile(r'"(\d+)"')
URL_RE = re.compile(r"https?://[^\s<>()]+")
TOKEN_RE = re.compile(r"[a-z0-9$%]+")
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?%?")
CASHTAG_RE = re.compile(r"\$[a-z][a-z0-9_.-]*")


@dataclass(frozen=True)
class Verification:
    status: str
    reason: str


class EditHistoryVerifier:
    """Fetch the public X edit chain used as replacement authority."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self._cache: dict[tuple[str, str, str], Verification] = {}

    def verify(self, old_url: str, old_id: str, new_id: str) -> Verification:
        key = (old_url, old_id, new_id)
        if key in self._cache:
            return self._cache[key]
        try:
            response = self.session.get(old_url, timeout=30, headers={"User-Agent": USER_AGENT})
        except requests.RequestException as exc:
            result = Verification("unknown", f"X edit history request failed: {type(exc).__name__}")
            self._cache[key] = result
            return result
        if response.status_code >= 400:
            result = Verification("unknown", f"X edit history HTTP {response.status_code}")
            self._cache[key] = result
            return result
        edit_ids = parse_edit_tweet_ids(response.text)
        if not edit_ids:
            result = Verification("unknown", "X edit history was not present")
        elif old_id in edit_ids and new_id in edit_ids and edit_ids.index(new_id) > edit_ids.index(old_id):
            result = Verification("confirmed", "X edit history links the older tweet to the newer version")
        else:
            result = Verification("not_superseded", "X edit history does not link the candidate tweets")
        self._cache[key] = result
        return result


def parse_edit_tweet_ids(document: str) -> list[str]:
    """Parse X's explicit edit_tweet_ids array from the public status page."""
    values: list[str] = []
    for match in EDIT_IDS_RE.finditer(document):
        for post_id in ID_RE.findall(match.group(1)):
            if post_id not in values:
                values.append(post_id)
    return values


def _plain(serialized: dict) -> str:
    authored = render.markdown(str(serialized.get("content_html") or ""))
    quoted = render.markdown(str(serialized.get("quoted_content_html") or ""))
    return "\n".join(item for item in (authored, quoted) if item)


def _normalize(value: str, remove_urls: bool = False) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    if remove_urls:
        value = URL_RE.sub(" ", value)
    value = re.sub(r"[^\w$%]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def _urls(serialized: dict) -> set[str]:
    values = set(URL_RE.findall(_plain(serialized)))
    for key in ("quoted_url", "quoted_article_url", "related_url"):
        value = serialized.get(key)
        if isinstance(value, str) and value.startswith("http"):
            values.add(value.rstrip(".,;:!?"))
    return values


def _fingerprint(posts: list[dict]) -> dict[str, object]:
    text = "\n\n".join(_plain(post) for post in posts).strip()
    normalized = _normalize(text)
    without_urls = _normalize(text, remove_urls=True)
    tokens = set(TOKEN_RE.findall(without_urls))
    trigrams = {without_urls[index:index + 3] for index in range(max(0, len(without_urls) - 2))}
    numbers = set(NUMBER_RE.findall(without_urls))
    paragraphs = {_normalize(part, remove_urls=True) for part in re.split(r"\n{2,}", text) if _normalize(part, remove_urls=True)}
    cashtags = set(CASHTAG_RE.findall(normalized))
    urls: set[str] = set()
    for post in posts:
        urls.update(_urls(post))
    return {
        "normalized": normalized,
        "without_urls": without_urls,
        "tokens": tokens,
        "trigrams": trigrams,
        "numbers": numbers,
        "paragraphs": paragraphs,
        "cashtags": cashtags,
        "urls": urls,
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _published_at(post: dict) -> datetime | None:
    value = post.get("published_at")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _within_window(old: dict, new: dict) -> bool:
    old_time = _published_at(old)
    new_time = _published_at(new)
    if old_time is None or new_time is None:
        return False
    if (old_time.tzinfo is None) != (new_time.tzinfo is None):
        return False
    return abs(new_time - old_time) <= CANDIDATE_WINDOW


def _pair_is_candidate(old: dict, new: dict) -> bool:
    if not _within_window(old, new):
        return False
    left = _fingerprint([old])
    right = _fingerprint([new])
    signals = 0
    if left["without_urls"] and left["without_urls"] == right["without_urls"]:
        signals += 2
    if _jaccard(left["tokens"], right["tokens"]) >= 0.82:
        signals += 1
    if _jaccard(left["trigrams"], right["trigrams"]) >= 0.78:
        signals += 1
    if left["paragraphs"] & right["paragraphs"]:
        signals += 1
    if left["urls"] & right["urls"]:
        signals += 1
    if len(left["numbers"] & right["numbers"]) >= 2:
        signals += 1
    if left["cashtags"] & right["cashtags"]:
        signals += 1
    return signals >= 2


def is_candidate(old_record: dict, new_event: dict) -> bool:
    """Use deterministic similarity only to nominate an edit candidate."""
    old_posts = old_record.get("thread_posts") or []
    new_posts = new_event.get("thread_posts") or []
    if not isinstance(old_posts, list) or not isinstance(new_posts, list):
        return False
    return any(_pair_is_candidate(old, new) for old in old_posts for new in new_posts)


def candidate_pairs(old_record: dict, new_event: dict) -> list[tuple[dict, dict]]:
    old_posts = old_record.get("thread_posts") or []
    new_posts = new_event.get("thread_posts") or []
    if not isinstance(old_posts, list) or not isinstance(new_posts, list):
        return []
    return [(old, new) for old in old_posts for new in new_posts if _pair_is_candidate(old, new)]
