"""Deterministically append one blank page to the captured 33681 source fixture."""

from __future__ import annotations

from pathlib import Path
import subprocess

FIXTURE_DIR = Path(__file__).parent
SOURCE_PDF = FIXTURE_DIR / "33681.pdf"
OUTPUT_PDF = FIXTURE_DIR / "malformed-five-pages.pdf"
BLANK_PDF = FIXTURE_DIR / ".blank-page.pdf"


def blank_page_pdf() -> bytes:
    """Build a fixed one-page, content-free PDF without reading either source PDF."""
    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    objects = (
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n",
    )
    body = bytearray(header)
    offsets = [0]
    for object_bytes in objects:
        offsets.append(len(body))
        body.extend(object_bytes)
    xref_offset = len(body)
    body.extend(b"xref\n0 4\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    body.extend(
        b"trailer\n<< /Size 4 /Root 1 0 R >>\n"
        + f"startxref\n{xref_offset}\n".encode("ascii")
        + b"%%EOF\n"
    )
    return bytes(body)


def main() -> None:
    if not SOURCE_PDF.is_file():
        raise FileNotFoundError(SOURCE_PDF)
    BLANK_PDF.write_bytes(blank_page_pdf())
    try:
        subprocess.run(
            ("pdfunite", str(SOURCE_PDF), str(BLANK_PDF), str(OUTPUT_PDF)),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        BLANK_PDF.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
