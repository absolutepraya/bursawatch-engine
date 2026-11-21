"""Deterministic output-language guard for generated news text.

Generated titles and summaries must be Bahasa Indonesia. The model sometimes
copies a Spanish, Portuguese or English source verbatim. This module counts
common function words and rejects text that is clearly written in one of those
languages. It never rewrites text and stays silent on mixed text, short
quotations, names and tickers.
"""

from __future__ import annotations

import re

_INDONESIAN = frozenset("""yang dan di ke dari untuk dengan pada ini itu akan dalam juga tidak oleh sebagai
atau karena setelah mereka telah sebesar hingga antara serta bahwa adalah namun sementara para sudah
masih lebih saat sekitar menjadi dapat yaitu tetapi sebelum terhadap secara""".split())
_FOREIGN = {
    "es": frozenset("de la el los las del que en y con por una es su al fue más como sus entre sobre fueron tiene hoy".split()),
    "pt": frozenset("e de por sobre os do da dos das em com uma é seu sua ao não mais como após antes nos nas pelo pela foram tem".split()),
    "en": frozenset("the and of to in is for on with that by at from its has will are was after over their been".split()),
}
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_URL = re.compile(r"https?://\S+")


def foreign_language(text: str) -> str | None:
    """Return "es", "pt" or "en" when text is clearly not Indonesian, else None."""
    words = [w.lower() for w in _WORD.findall(_URL.sub(" ", text))]
    if len(words) < 5:
        return None
    indonesian = sum(w in _INDONESIAN for w in words)
    best, best_count = None, 0
    for language, markers in _FOREIGN.items():
        count = sum(w in markers for w in words)
        if count > best_count:
            best, best_count = language, count
    if best is None:
        return None
    if best_count >= 3 and best_count > 2 * indonesian:
        return best
    if best_count >= 2 and indonesian == 0 and len(words) <= 14:
        return best
    return None
