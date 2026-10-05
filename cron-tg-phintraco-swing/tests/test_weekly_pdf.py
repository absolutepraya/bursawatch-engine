from __future__ import annotations

from dataclasses import dataclass

import pymupdf
import pytest

from weekly_pdf import WeeklyPdfError, parse_weekly_pdf


@dataclass(frozen=True)
class Section:
    ticker: str
    heading: str
    entry: str
    target_lines: tuple[str, ...]
    trend: str = "Uptrend"
    ma_indicator: str = "Below, Bull tendency"
    upside: str = "6%-11%"
    downside: str = "-4%"


def _jpeg_bytes(shade: int = 230) -> bytes:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 200), 0)
    pixmap.clear_with(shade)
    return pixmap.tobytes("jpeg")


CHART_BYTES = _jpeg_bytes()


def _sections() -> list[list[Section]]:
    return [
        [
            Section(
                "AADI",
                "Base Formation Indication",
                ">=11000",
                ("Target Price 2: 12200", "Target Price 1: 11600 ; SL <10600"),
                trend="Uptrend",
                ma_indicator="Above, Bear tendency",
                upside="5%-11%",
                downside="-3%",
            ),
            Section(
                "ITMG",
                "On support",
                ">=25000",
                ("Target Price : 26050; SL <24400",),
                trend="Bullish",
                ma_indicator="Above, Bear Tendency",
                upside="4%",
                downside="-2%",
            ),
        ],
        [
            Section("PTBA", "On Support", ">=3000", ("Target Price 2: 3330", "Target Price 1: 3200 ; SL <2900")),
            Section("SUPA", "On Support", ">=488", ("Target Price 2: 550", "Target Price 1: 520 ; SL <478")),
        ],
        [
            Section("KETR", "On Support", ">=940", ("Target Price 2: 1050", "Target Price 1: 1000 ; SL <900")),
            Section(
                "INDF",
                "On Support",
                ">=6600",
                ("Target Price : 6900-7000 SL <6500",),
                trend="Minor Bearish",
                ma_indicator="Above, Bear tendency",
                upside="4%-6%",
                downside="-2%",
            ),
        ],
    ]


def make_pdf(
    pages: list[list[Section]] | None = None,
    *,
    chartless: set[str] | None = None,
    extra_chart_for: set[str] | None = None,
) -> bytes:
    pages = pages or _sections()
    chartless = chartless or set()
    extra_chart_for = extra_chart_for or set()
    document = pymupdf.open()
    for page_index, page_sections in enumerate(pages):
        page = document.new_page(width=1008, height=612)
        if page_index == 0:
            page.insert_text((50, 32), "Monday, September 28th, 2026", fontsize=14)
        else:
            page.insert_text((650, 32), "Phintraco Sekuritas | Weekly Swing Trading Ideas", fontsize=12)

        for section_index, section in enumerate(page_sections):
            top = 80 + section_index * 260
            section_number = page_index * 2 + section_index + 1
            lines = [
                f"{section_number}. {section.ticker} - {section.heading}",
                f"Trend : {section.trend}",
                f"MA. Indicator : {section.ma_indicator}",
                f"Potential Upside : {section.upside}",
                f"Potential Downside : {section.downside}",
                "ACTION : Buy",
                f"Entry : {section.entry}",
                *section.target_lines,
            ]
            for line_index, line in enumerate(lines):
                page.insert_text((50, top + line_index * 24), line, fontsize=13)
            if section.ticker not in chartless:
                chart_top = top - 8
                chart_bottom = chart_top + 205
                page.insert_image(
                    pymupdf.Rect(560, chart_top, 970, chart_bottom),
                    stream=_jpeg_bytes(100 + section_number * 10),
                )
                if section.ticker in extra_chart_for:
                    page.insert_image(
                        pymupdf.Rect(560, chart_top + 5, 970, chart_bottom - 5),
                        stream=_jpeg_bytes(100 + section_number * 10),
                    )
    return document.tobytes()


def make_empty_pdf() -> bytes:
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for item in objects:
        offsets.append(len(payload))
        payload.extend(item)
    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode())
    payload.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(payload)


def test_extracts_six_plans_and_their_matching_images_in_source_order():
    result = parse_weekly_pdf(
        "PHINTAS Weekly Swing Trading Ideas_20260928.pdf",
        make_pdf(),
    )

    assert result.report_date.isoformat() == "2026-09-28"
    assert [setup.ticker for setup in result.setups] == [
        "AADI", "ITMG", "PTBA", "SUPA", "KETR", "INDF"
    ]
    assert all(
        setup.chart_bytes == _jpeg_bytes(100 + index * 10)
        for index, setup in enumerate(result.setups, start=1)
    )
    assert len({setup.chart_bytes for setup in result.setups}) == 6
    assert all(setup.page_number == index // 2 + 1 for index, setup in enumerate(result.setups))
    assert all(setup.section_number == index + 1 for index, setup in enumerate(result.setups))
    assert result.quarantined_pages == ()


def test_preserves_combined_stop_loss_and_numbered_target_lines():
    result = parse_weekly_pdf(
        "PHINTAS Weekly Swing Trading Ideas_20260928.pdf",
        make_pdf(),
    )
    ket = next(setup for setup in result.setups if setup.ticker == "KETR")

    assert ket.entry == ">=940"
    assert ket.stop_loss == "<900"
    assert [(target.number, target.value) for target in ket.targets] == [
        (1, "1000"), (2, "1050")
    ]


def test_preserves_an_unnumbered_target_range_and_plan_context():
    result = parse_weekly_pdf(
        "PHINTAS Weekly Swing Trading Ideas_20260928.pdf",
        make_pdf(),
    )
    indf = next(setup for setup in result.setups if setup.ticker == "INDF")

    assert indf.entry == ">=6600"
    assert indf.stop_loss == "<6500"
    assert [(target.number, target.value) for target in indf.targets] == [(None, "6900 to 7000")]
    assert indf.descriptor == "On Support"
    assert indf.trend == "Minor Bearish"
    assert indf.ma_indicator == "Above, Bear tendency"
    assert indf.potential_upside == "4%-6%"
    assert indf.potential_downside == "-2%"


@pytest.mark.parametrize(
    "filename,payload",
    [
        ("weekly-swing.pdf", make_pdf()),
        ("PHINTAS Weekly Swing Trading Ideas_20260928.pdf", b"not a PDF"),
        ("PHINTAS Weekly Swing Trading Ideas_20260928.pdf", b"%PDF-" + b"0" * (8 * 1024 * 1024)),
    ],
)
def test_rejects_wrong_filename_invalid_pdf_and_oversized_document(filename, payload):
    with pytest.raises(WeeklyPdfError):
        parse_weekly_pdf(filename, payload)


def test_rejects_documents_outside_page_count_limit():
    with pytest.raises(WeeklyPdfError):
        parse_weekly_pdf(
            "PHINTAS Weekly Swing Trading Ideas_20260928.pdf",
            make_empty_pdf(),
        )

    document = pymupdf.open()
    for _ in range(13):
        document.new_page()

    with pytest.raises(WeeklyPdfError):
        parse_weekly_pdf(
            "PHINTAS Weekly Swing Trading Ideas_20260928.pdf",
            document.tobytes(),
        )


def test_rejects_encrypted_document():
    document = pymupdf.open()
    document.new_page()
    payload = document.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner",
        user_pw="user",
    )

    with pytest.raises(WeeklyPdfError):
        parse_weekly_pdf(
            "PHINTAS Weekly Swing Trading Ideas_20260928.pdf",
            payload,
        )


def test_quarantines_only_a_page_with_a_missing_chart():
    result = parse_weekly_pdf(
        "PHINTAS Weekly Swing Trading Ideas_20260928.pdf",
        make_pdf(chartless={"PTBA"}),
    )

    assert [setup.ticker for setup in result.setups] == ["AADI", "ITMG", "KETR", "INDF"]
    assert [(page.page_number, page.reason) for page in result.quarantined_pages] == [
        (2, "weekly plan page has an ambiguous chart association")
    ]


def test_quarantines_a_page_with_duplicate_ticker_sections():
    pages = _sections()
    pages[1][1] = Section("PTBA", "On Support", ">=3100", ("Target Price : 3300; SL <2900",))

    result = parse_weekly_pdf(
        "PHINTAS Weekly Swing Trading Ideas_20260928.pdf",
        make_pdf(pages),
    )

    assert [setup.ticker for setup in result.setups] == ["AADI", "ITMG", "KETR", "INDF"]
    assert result.quarantined_pages[0].page_number == 2
    assert result.quarantined_pages[0].reason == "weekly plan page has duplicate ticker sections"


def test_quarantines_all_pages_that_reuse_a_ticker_identity():
    pages = _sections()
    pages[2][0] = Section("PTBA", "On Support", ">=3100", ("Target Price : 3300; SL <2900",))

    result = parse_weekly_pdf(
        "PHINTAS Weekly Swing Trading Ideas_20260928.pdf",
        make_pdf(pages),
    )

    assert [setup.ticker for setup in result.setups] == ["AADI", "ITMG"]
    assert [page.page_number for page in result.quarantined_pages] == [2, 3]


def test_quarantines_a_page_with_an_extra_chart_without_unique_association():
    result = parse_weekly_pdf(
        "PHINTAS Weekly Swing Trading Ideas_20260928.pdf",
        make_pdf(extra_chart_for={"PTBA"}),
    )

    assert [setup.ticker for setup in result.setups] == ["AADI", "ITMG", "KETR", "INDF"]
    assert any(page.page_number == 2 for page in result.quarantined_pages)


@pytest.mark.parametrize(
    "replacement",
    [
        ("Entry : >=940",),
        ("Target Price 1: 1000",),
        ("Target Price 1: 1000 ; SL <900", "Target Price 1: 1050"),
    ],
)
def test_quarantines_malformed_plan_levels(replacement):
    pages = _sections()
    pages[2][0] = Section("KETR", "On Support", ">=940", replacement)

    result = parse_weekly_pdf(
        "PHINTAS Weekly Swing Trading Ideas_20260928.pdf",
        make_pdf(pages),
    )

    assert "KETR" not in [setup.ticker for setup in result.setups]
    assert any(page.page_number == 3 for page in result.quarantined_pages)


def test_rejects_a_report_date_that_disagrees_with_the_filename():
    document = pymupdf.open(stream=make_pdf(), filetype="pdf")
    page = document[0]
    page.add_redact_annot(pymupdf.Rect(40, 12, 300, 40), fill=(1, 1, 1))
    page.apply_redactions()
    page.insert_text((50, 32), "Monday, September 21st, 2026", fontsize=14)

    with pytest.raises(WeeklyPdfError):
        parse_weekly_pdf(
            "PHINTAS Weekly Swing Trading Ideas_20260928.pdf",
            document.tobytes(),
        )
