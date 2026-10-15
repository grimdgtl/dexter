"""Seckanje dokumenata na delove (chunks) pre vektorizacije.

Stara verzija je pravila JEDAN vektor od prvih 2000 znakova dokumenta — sve
posle toga pretraga nije videla. Ovde se dokument deli na delove od ~1200
znakova (oko 300 tokena), sa preklapanjem, da rečenica koja pada na granicu
ne izgubi kontekst.

Redosled sečenja: prvo po naslovima/praznim redovima (prirodne celine), pa
tek ako je pasus predugačak — po rečenicama, pa po rečima. Svaki deo dobija
naslov dokumenta na početak, da vektor "zna" odakle je deo.

Ovo su parametri koje vredi menjati i meriti eval setom (faza 2).
"""

import re

CHUNK_CHARS = 1200
OVERLAP_CHARS = 200

_PARAGRAPH = re.compile(r"\n\s*\n|\n(?=#{1,6} )|\n(?=Član \d+)")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _split_long(text: str, limit: int) -> list[str]:
    """Pasus duži od limita deli po rečenicama, a rečenicu dužu od limita po rečima."""
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    for sent in _SENTENCE.split(text):
        if len(sent) <= limit:
            pieces.append(sent)
            continue
        words, cur = sent.split(), ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > limit:
                pieces.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            pieces.append(cur)
    return pieces


def chunk_text(
    text: str,
    title: str = "",
    size: int = CHUNK_CHARS,
    overlap: int = OVERLAP_CHARS,
) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []

    units: list[str] = []
    for para in _PARAGRAPH.split(text):
        para = para.strip()
        if para:
            units.extend(_split_long(para, size))

    chunks: list[str] = []
    cur = ""
    for u in units:
        if cur and len(cur) + 2 + len(u) > size:
            chunks.append(cur)
            # Preklapanje: kraj prethodnog dela ide na početak sledećeg.
            tail = cur[-overlap:] if overlap else ""
            cut = tail.find(" ")
            tail = tail[cut + 1 :] if cut != -1 else tail
            cur = f"{tail}\n\n{u}" if tail else u
        else:
            cur = f"{cur}\n\n{u}" if cur else u
    if cur:
        chunks.append(cur)

    prefix = f"{title}\n" if title else ""
    return [prefix + c for c in chunks]
