"""Tri izmišljena skenirana ugovora za privatnu probu; bez stvarnih API poziva."""

import io
from pathlib import Path

from fpdf import FPDF
from pypdf import PdfReader

from dexter.rag.ocr import render_page
from dexter.services.invoice_pdf import FONTS
from evals.contract_cases import PAGES


def make(pages: list[list[str]]) -> bytes:
    native = FPDF()
    native.set_auto_page_break(False)
    native.add_font("Montserrat", fname=str(FONTS / "Montserrat-Regular.ttf"))
    native.add_font("Montserrat", style="B", fname=str(FONTS / "Montserrat-Bold.ttf"))
    for i, paragraphs in enumerate(pages, 1):
        native.add_page()
        native.set_font("Montserrat", "B", 15)
        native.multi_cell(0, 9, "IZMIŠLJEN TEST UGOVOR", new_x="LMARGIN", new_y="NEXT")
        native.set_font("Montserrat", size=10)
        native.multi_cell(
            0,
            7,
            "Probni dokument za Dexter. Nije za potpisivanje ni pravnu upotrebu.",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        native.ln(8)
        native.set_font("Montserrat", size=11)
        for paragraph in paragraphs:
            native.multi_cell(0, 8, paragraph, new_x="LMARGIN", new_y="NEXT")
            native.ln(5)
        native.set_y(-20)
        native.set_font("Montserrat", size=9)
        native.cell(0, 8, f"Test primer - stranica {i}")
    source = bytes(native.output())
    scan = FPDF()
    for i in range(len(PdfReader(io.BytesIO(source)).pages)):
        scan.add_page()
        scan.image(io.BytesIO(render_page(source, i)), x=0, y=0, w=210, h=297)
    result = bytes(scan.output())
    assert all(not (p.extract_text() or "").strip() for p in PdfReader(io.BytesIO(result)).pages)
    return result


def main():
    output = Path("output/pdf")
    output.mkdir(parents=True, exist_ok=True)
    samples = {
        "ugovor-uredan-sken.pdf": PAGES,
        "ugovor-nepotpun-sken.pdf": [
            [
                "Studio Primer, uloga: Izvršilac. PIB nije naveden.",
                "Firma Primer, uloga: Naručilac. PIB nije naveden.",
                "Izvršilac se obavezuje da održava sajt. Rok i naknada nisu određeni.",
                "Trajanje će biti naknadno dogovoreno. Datum isteka nije naveden.",
            ]
        ],
        "ugovor-uslovni-sken.pdf": [
            [
                "Studio Primer, PIB: 000000001, uloga: Izvršilac.",
                "Firma Primer, PIB: 000000002, uloga: Naručilac.",
                "Ugovor važi do 31.12.2030.",
                "Ugovor se automatski produžava ako nije otkazan u skladu sa naknadnim dogovorom.",
                "Datum raskida zavisi od prijema obaveštenja; nije unapred određen.",
            ]
        ],
    }
    for name, pages in samples.items():
        path = output / name
        path.write_bytes(make(pages))
        print(path)


if __name__ == "__main__":
    main()
