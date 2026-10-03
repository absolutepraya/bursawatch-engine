import news_format
import pytest


def test_macro_instruction_preserves_figure_roles():
    # The owner-facing composition must supply category guidance, not silently lose it.
    assert callable(getattr(news_format, "category_instruction", None))
    instruction = news_format.category_instruction("macro")
    assert instruction and instruction in news_format.WRITING_INSTRUCTION
    with pytest.raises(ValueError):
        news_format.category_instruction("unexpected")


def test_macro_fixture_survives_frozen_card():
    summary = "Inflasi Sep 2026 aktual 2,5% YoY, dibanding konsensus 2,7% dan periode sebelumnya 2,4%. Revisi sebesar 0,2 poin persentase.\n\nAngka MoM dicatat terpisah. Dua angka aktual utama belum direkonsiliasi oleh sumber."
    cards = news_format.freeze_cards([{"title": "Inflasi September", "summary": summary, "route": "macro_news"}], heading_for=lambda _: "### Inflasi September", source_url="https://example.com/news", source_label="View source", target_for=lambda _: "123")
    assert cards[0]["summary"] == summary
    assert summary in cards[0]["messages"][0]
