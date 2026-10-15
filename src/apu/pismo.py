"""Ćirilica → latinica, nametnuto u kodu (preneto iz pismo.js).

Uputstvo "piši latinicom" u promptu je samo molba modelu. Whisper transkribuje
srpski u ćirilicu, transkript uđe u istoriju i model počne da je preslikava.
Zato se pismo menja deterministički: na ulazu (transkript) i na izlazu (sve
što ide u Telegram). Prompt je prva linija odbrane, ovo je garancija.
"""

import re

_MALA = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ђ": "đ", "е": "e", "ж": "ž",
    "з": "z", "и": "i", "ј": "j", "к": "k", "л": "l", "љ": "lj", "м": "m", "н": "n",
    "њ": "nj", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "ћ": "ć", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "č", "џ": "dž", "ш": "š",
}  # fmt: skip
_VELIKA = {k.upper(): v.capitalize() for k, v in _MALA.items()}
_CIRILICA = re.compile(r"[Ѐ-ӿ]")


def ima_cirilice(text: str) -> bool:
    return bool(_CIRILICA.search(text or ""))


def u_latinicu(text: str) -> str:
    """Preslovi srpsku ćirilicu; sve ostalo (latinica, brojevi, emodži, URL) ostaje isto."""
    if not ima_cirilice(text):
        return text

    out: list[str] = []
    for i, ch in enumerate(text):
        if ch in _VELIKA:
            lat = _VELIKA[ch]
            nxt = text[i + 1] if i + 1 < len(text) else ""
            # "ЊЕГОВ" → "NJEGOV", ali "Његов" → "Njegov"
            out.append(lat.upper() if len(lat) > 1 and nxt in _VELIKA else lat)
        else:
            out.append(_MALA.get(ch, ch))
    return "".join(out)
