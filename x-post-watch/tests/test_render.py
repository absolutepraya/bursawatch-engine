from datetime import datetime, UTC

import render
from models import PostKind, SourcePost


def test_render_quote_post_exact(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "Market note", PostKind.QUOTE, "https://x.com/original/status/101", "Kepala Warga Tai.: Quote note", (), ())
    assert render.render_post(profile, post) == ["### <:twitter:1531672630602498129><:kutekians:1531673483459821729> Almer Sad, CFA\n\nMarket note [View on X](<https://x.com/Kutekians/status/102>)\n> **Kepala Warga Tai.**\n> Quote note\n> [View quoted on X](<https://x.com/original/status/101>)"]


def test_render_splits_long_post(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "word " * 1000, PostKind.NORMAL, None, None, (), ())
    messages = render.render_post(profile, post)
    assert len(messages) > 1
    assert all(len(message) <= 2000 for message in messages)
    assert messages[-1].endswith("[View on X](<https://x.com/Kutekians/status/102>)")


def test_render_keeps_view_link_and_quote_block_atomic_when_source_is_long(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "word " * 1000, PostKind.QUOTE, "https://x.com/a/status/1", "Quoted author: " + "quoted " * 100, (), ())
    messages = render.render_post(profile, post)
    joined = "\n".join(messages)
    assert all(len(message) <= 2000 for message in messages)
    assert "[View on\nX]" not in joined
    assert "[View quoted on\nX]" not in joined
    assert sum("[View on X]" in message for message in messages) == 1
    assert sum("[View quoted on X]" in message for message in messages) == 1
    assert all(not message.startswith("> ") or "[View quoted on X]" in message for message in messages[1:])


def test_render_truncates_quote_text_at_word_boundary(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "Own", PostKind.QUOTE, "https://x.com/a/status/1", "quoted " * 100, (), ())
    rendered = render.render_post(profile, post)[0]
    assert "quoted quoted" in rendered
    assert "…\n> [View quoted on X]" in rendered
    assert len(rendered) < 700


def test_render_preserves_blank_quote_paragraph_without_bare_marker(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "Own", PostKind.QUOTE, "https://x.com/a/status/1", "Name: First paragraph\n\nSecond paragraph", (), ())
    rendered = render.render_post(profile, post)[0]
    assert "> \u200b" in rendered
    assert "> Second paragraph\n> [View quoted on X]" in rendered


def test_render_summary_retains_quoted_post_text(config_path, profile_payload):
    profile_payload["enable_llm_title"] = True
    profile_payload["enable_llm_summary"] = True
    config_path.write_text(__import__("json").dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "Raw original", PostKind.QUOTE, "https://x.com/original/status/101", "Quoted raw", (), ())
    summary = "*(Ringkasan)* Ini ringkasan inti."
    assert render.render_post(profile, post, summary, "Pasar: Ringkasan Inti") == ["### <:twitter:1531672630602498129> Pasar: Ringkasan Inti\n-# <:kutekians:1531673483459821729> Almer Sad, CFA\n\n*(Ringkasan)* Ini ringkasan inti.\n\n[View on X](<https://x.com/Kutekians/status/102>)\n> **Quoted post**\n> Quoted raw\n> [View quoted on X](<https://x.com/original/status/101>)"]


def test_render_article_quote_block_is_visible_without_article_body(config_path, profile_payload):
    profile_payload["enable_llm_title"] = True
    profile_payload["enable_llm_summary"] = True
    config_path.write_text(__import__("json").dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "Raw authored post", PostKind.NORMAL, None, None, (), (), quoted_article_url="https://x.com/i/article/123", quoted_article_label="Ricky Ho")
    rendered = "\n".join(render.render_post(profile, post, "*(Ringkasan)* Ringkasan inti.", "Pasar: Artikel"))
    assert "> **Ricky Ho**" in rendered
    assert "> *(Article)*" in rendered
    assert "[Read Article on X](<https://x.com/i/article/123>)" in rendered
    assert "Raw authored post" not in rendered


def test_render_quoted_source_url_as_anchor_without_raw_url(config_path, profile_payload):
    profile_payload["enable_llm_title"] = True
    profile_payload["enable_llm_summary"] = True
    config_path.write_text(__import__("json").dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    source_url = "https://www.bloomberg.com/news/articles/2026-08-14/example?utm_source=twitter"
    post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "Author text", PostKind.QUOTE, "https://x.com/business/status/101", f"Bloomberg: Source context {source_url} trailing text that should not render", (), ())
    rendered = "\n".join(render.render_post(profile, post, "*(Ringkasan)* Ringkasan inti.", "Pasar: Ringkasan"))
    assert f"Source context {source_url}" not in rendered
    assert f"[Read source](<{source_url}>)" in rendered
    assert f"[Read source](<{source_url}>)\n> [View quoted on X]" in rendered
    assert "trailing text that should not render" not in rendered


def test_render_title_places_writer_in_muted_byline(config_path, profile_payload):
    profile_payload["enable_llm_title"] = True
    config_path.write_text(__import__("json").dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "Raw original", PostKind.NORMAL, None, None, (), ())
    rendered = render.render_post(profile, post, title="BI: Tiga Indikator untuk Membaca Pasar")[0]
    assert rendered.startswith("### <:twitter:1531672630602498129> BI: Tiga Indikator untuk Membaca Pasar\n-# <:kutekians:1531673483459821729> Almer Sad, CFA\n\nRaw original")
