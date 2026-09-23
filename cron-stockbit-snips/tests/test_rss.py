from __future__ import annotations

from models import Feed, FeedLane
from rss import parse_feed, page_url, visible_text


FEED = Feed(FeedLane.UNBOXING_IPO, "Unboxing IPO", "https://example.test/ipo?format=rss")


def test_parse_feed_supports_namespaced_content_and_media() -> None:
    xml = """<?xml version="1.0"?>
    <rss xmlns:content="http://purl.org/rss/1.0/modules/content/"
         xmlns:media="http://search.yahoo.com/mrss/"><channel>
      <item>
        <title>Unboxing IPO $SWAP</title>
        <link>https://snips.stockbit.com/unboxing-ipo/swap</link>
        <guid>guid-swap</guid>
        <pubDate>Wed, 25 Aug 2026 05:25:00 GMT</pubDate>
        <description>Ringkasan singkat</description>
        <content:encoded><![CDATA[<p>Profil <strong>SWAP</strong> dan rencana penawaran.</p>]]></content:encoded>
        <media:content url="https://cdn.test/swap.jpg" />
      </item>
    </channel></rss>"""

    articles = parse_feed(xml, FEED)

    assert len(articles) == 1
    assert articles[0].guid == "guid-swap"
    assert articles[0].source_text == "Profil SWAP dan rencana penawaran."
    assert articles[0].media_url == "https://cdn.test/swap.jpg"


def test_page_url_uses_squarespace_page_query() -> None:
    assert page_url(FEED, 1) == FEED.url
    assert page_url(FEED, 2) == f"{FEED.url}&page=2"


def test_visible_text_removes_scripts_and_collapses_blank_lines() -> None:
    assert visible_text("<script>x</script><p>A</p><div>B</div>") == "A\n\nB"
