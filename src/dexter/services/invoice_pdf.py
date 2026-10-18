"""Montserrat obrazac iz v1, sa prelomom dugih opisa i više stranica."""

import io
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import MethodReturnValue

from dexter.pismo import u_latinicu

FONTS = Path(__file__).resolve().parents[1] / "assets" / "fonts"
if not FONTS.is_dir():
    FONTS = Path(__file__).resolve().parents[3] / "assets" / "fonts"
CENT = Decimal("0.01")


def money(value: Decimal) -> str:
    return f"{value.quantize(CENT, rounding=ROUND_HALF_UP):,.2f}".translate(
        str.maketrans(",.", ".,")
    )


def display_date(value: str) -> str:
    day = date.fromisoformat(value)
    return f"{day.day}.{day.month}.{day.year}."


def total(items: list | tuple) -> Decimal:
    return sum((item.kolicina * item.cena).quantize(CENT, rounding=ROUND_HALF_UP) for item in items)


def render(invoice) -> bytes:
    pdf = FPDF(unit="pt", format="A4")
    pdf.set_margins(50, 50, 50)
    pdf.set_auto_page_break(False)
    pdf.c_margin = 0
    for style, file in (("", "Regular"), ("B", "Bold")):
        pdf.add_font("Montserrat", style, FONTS / f"Montserrat-{file}.ttf")
    pdf.add_font("Semi", "", FONTS / "Montserrat-SemiBold.ttf")
    pdf.add_font("Medium", "", FONTS / "Montserrat-Medium.ttf")
    pdf.add_page()
    left, right, width, bottom = 50, pdf.w - 50, pdf.w - 100, pdf.h - 50

    def font(size=9.5, style=""):
        pdf.set_font("Semi" if style == "S" else "Montserrat", "" if style == "S" else style, size)

    def lines(text, w, size=9.5, style=""):
        font(size, style)
        text = u_latinicu(str(text))
        missing = [ch for ch in text if ch not in "\n\r\t" and ord(ch) not in pdf.current_font.cmap]
        if missing:
            raise ValueError(
                f"Montserrat ne podržava znak U+{ord(missing[0]):04X}; prilagodi tekst."
            )
        pdf.set_xy(left, 50)
        return pdf.multi_cell(w, size * 1.25, text, dry_run=True, output=MethodReturnValue.LINES)

    def put(text, x, y, w, size=9.5, style="", align="L", h=None):
        wrapped = lines(text, w, size, style)
        font(size, style)
        line_h = h or size * 1.25
        pdf.set_xy(x, y)
        pdf.multi_cell(w, line_h, u_latinicu(str(text)), align=align)
        return y + len(wrapped) * line_h

    def block(values, x, y, w, align="L"):
        for value in filter(None, values):
            y = max(y + 14, put(value, x, y, w, align=align))
        return y

    def rule(y):
        pdf.set_line_width(1)
        pdf.line(left, y, right, y)

    put("Račun", left, 50, 240, 34)
    put(invoice.broj, left, 90, 240, 17)
    issuer, customer = invoice.issuer, invoice.customer
    if invoice.logo:
        pdf.image(
            io.BytesIO(invoice.logo), x=right - 170, y=54, w=170, h=42, keep_aspect_ratio=True
        )
    else:
        brand_size = 20
        while len(lines(issuer["brand"], 220, brand_size, "S")) * brand_size * 1.25 > 50:
            brand_size -= 1
            if brand_size < 8:
                raise ValueError("INVOICE_ISSUER_BRAND je predugačak za zaglavlje.")
        put(issuer["brand"], right - 220, 62, 220, brand_size, "S", "R")
    rule(128)
    issuer_end = block(
        [
            issuer["name"],
            f"{issuer['address']}, {issuer['city']}",
            issuer["phone"],
            f"PIB: {issuer['pib']}",
            f"MB: {issuer['mb']}",
            f"Broj računa: {issuer['account']}",
            issuer["bank"],
        ],
        left,
        142,
        235,
    )
    customer_end = block(
        [
            customer["naziv"],
            customer["adresa"],
            customer["grad"],
            f"PIB: {customer['pib']}" if customer["pib"] else None,
            f"MB: {customer['mb']}" if customer["mb"] else None,
        ],
        right - 235,
        142,
        235,
        "R",
    )
    if max(issuer_end, customer_end) > bottom - 200:
        raise ValueError(
            "Podaci izdavaoca/klijenta su predugački za zaglavlje; skrati ih u izvoru."
        )
    y = max(issuer_end, customer_end) + 24
    put(f"Račun: {invoice.broj}", left, y, width, 11, "B", "C")
    y = block(
        [
            f"Datum izdavanja računa: {display_date(invoice.datumIzdavanja)}",
            f"Mesto izdavanja: {invoice.mesto}",
            f"Datum prometa usluge: {display_date(invoice.datumPrometa)}",
            f"Mesto prometa usluge: {invoice.mesto}.",
        ],
        left,
        y + 44,
        width,
    )

    def new_page():
        pdf.add_page()
        put(f"Račun: {invoice.broj} - nastavak", left, 50, width, 11, "B")
        return 80

    def table_header(top):
        for title, x, w in (
            ("Usluga", 58, 235),
            ("Količina", 300, 70),
            ("Jedinična cena", 375, 90),
            ("Ukupna cena", 470, 75),
        ):
            put(title, x, top + 8, w, align="C")
        rule(top + 26)
        return top + 36

    table_top = y + 26
    if table_top + 64 > bottom:
        table_top = new_page()
    row_y = table_header(table_top)
    for item in invoice.stavke:
        remaining = lines(item.opis, 235)
        first_fragment = True
        while remaining:
            available = int((bottom - row_y - 12) / 12)
            if available < 1:
                pdf.rect(left, table_top, width, row_y - table_top)
                table_top = new_page()
                row_y = table_header(table_top)
                available = int((bottom - row_y - 12) / 12)
            chunk, remaining = remaining[:available], remaining[available:]
            height = max(14, len(chunk) * 12)
            put("\n".join(chunk), 58, row_y, 235, h=12)
            if first_fragment:
                for text, x, w in (
                    (format(item.kolicina.normalize(), "f"), 300, 70),
                    (money(item.cena), 375, 90),
                    (money(item.kolicina * item.cena), 470, 75),
                ):
                    font()
                    size = min(9.5, 9.5 * w / max(w, pdf.get_string_width(text)))
                    put(text, x, row_y + (height - 12) / 2, w, size, align="C")
            first_fragment = False
            row_y += height + 12
    pdf.rect(left, table_top, width, row_y - table_top)
    y = row_y + 18
    footer_height = (
        len(lines(invoice.comment, width, 9)) * 12
        + max(
            len(lines(invoice.vat_note, 280, 9)), len(lines(issuer["responsible_person"], 200, 9))
        )
        * 12
        + 115
    )
    if y + footer_height > bottom:
        y = new_page()
    put(f"Ukupno RSD: {money(total(invoice.stavke))}", left, y, width, 13, align="R")
    rule(y + 34)
    y += 64
    put("Komentar:", left, y, width, 8.5, "B")
    end = put(invoice.comment, left, y + 13, width, 9)
    y = max(y + 46, end + 18)
    put("Napomena o poreskom oslobođenju:", left, y, 280, 8.5, "B")
    put(invoice.vat_note, left, y + 13, 280, 9)
    put("Odgovorno lice:", right - 200, y, 200, 8.5, "B", "R")
    put(issuer["responsible_person"], right - 200, y + 13, 200, 9, align="R")
    return bytes(pdf.output())
