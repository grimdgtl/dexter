"""Izbor modela po poruci.

Tri nivoa: brzi (Haiku), glavni (Sonnet) i jaki (Opus). Haiku ide za
pozadinske stvari (memorija, podsetnici), Sonnet za skoro sve razgovore, a
Opus kad korisnik eksplicitno traži dubinu ili je zahtev očigledno težak.

Ovo je namerno jednostavno pravilo. Faza 3 plana: napraviti klasifikator
(Haiku sa jednim pitanjem "jednostavno/srednje/teško") i izmeriti da li
štedi novac bez gubitka kvaliteta. Bez merenja ne menjamo.
"""

import re

from apu.config import settings

DEEP_PREFIX = ("/duboko", "duboko:")
DEEP_HINTS = re.compile(
    r"\b(strategij\w*|analiz\w*|uporedi\w*|plan\s+za|razradi\w*|ugovor\w*|"
    r"pregovar\w*|odluk\w*|za i protiv)\b",
    re.IGNORECASE,
)


def pick_model(text: str) -> tuple[str, str]:
    """Vraća (model, tekst bez prefiksa)."""
    cfg = settings()
    stripped = text.strip()
    for p in DEEP_PREFIX:
        if stripped.lower().startswith(p):
            return cfg.model_deep, stripped[len(p) :].strip()
    if len(stripped) > 800 or len(DEEP_HINTS.findall(stripped)) >= 2:
        return cfg.model_deep, stripped
    return cfg.model_main, stripped
