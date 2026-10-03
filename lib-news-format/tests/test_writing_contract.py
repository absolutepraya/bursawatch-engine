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


def test_industry_guidance_is_supplied_to_routing_owner():
    instruction = news_format.category_instruction("industry")
    assert instruction
    assert instruction in news_format.WRITING_INSTRUCTION


@pytest.mark.parametrize("summary", [
    "Sumber menyebut penambahan kapasitas jaringan sebagai sasaran kebijakan.",
    "Menurut sumber, bisnis kabel perusahaan terkait dapat menerima tambahan permintaan jika pembangunan terlaksana.",
    "Sumber memperkirakan permintaan meningkat dengan asumsi anggaran direalisasikan.",
    "Kebijakan diumumkan; sumber belum memberikan bukti kontrak atau besaran dampak perusahaan.",
])
def test_industry_supported_summary_stays_deliverable(summary):
    cards = news_format.freeze_cards([{"title": "Pembangunan jaringan", "summary": summary, "route": "id_industry_news"}], lambda _: "### Jaringan", "https://example.com/news", "View source", target_for=lambda _: "industry")
    assert cards[0]["destination"] == "industry"
    assert summary in cards[0]["messages"][0]
