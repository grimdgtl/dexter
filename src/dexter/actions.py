"""Prilozi i ishodi potvrde ostaju van modelskih argumenata i agentske istorije."""

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel


@dataclass(frozen=True)
class Document:
    data: bytes
    filename: str


@dataclass
class PreparedAction:
    args: BaseModel
    document: Document | None = None


@dataclass
class ConfirmedAction:
    result: Any
    document: Document | None = None
    successful: bool = True


def confirmation_text(raw: str) -> str:
    """Potvrda prikazuje poslovni ishod; tehnički rezultat ostaje za agentski kontekst."""
    try:
        result = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if not isinstance(result, dict):
        return "Akcija je obrađena."
    lines = []
    if result.get("poruka"):
        lines.append(str(result["poruka"]))
    else:
        for key, label in (("broj", "Faktura"), ("klijent", "Klijent")):
            if result.get(key):
                lines.append(f"{label}: {result[key]}")
        if result.get("poslato") is True:
            lines.append("Mejl je poslat.")
    note = result.get("napomena")
    if note:
        lines.append(str(note))
    for key, label in (
        ("notion", "Notion"),
        ("drive", "Drive"),
        ("driveProvera", "Proveri Drive"),
        ("url", "Link"),
        ("htmlLink", "Kalendar"),
    ):
        value = result.get(key)
        if isinstance(value, dict):
            link = value.get("url") or value.get("link")
            if key == "notion" and value.get("id"):
                try:
                    link = f"https://www.notion.so/{UUID(value['id']).hex}"
                except ValueError:
                    pass
            value = link
        if isinstance(value, str) and value.startswith("https://"):
            lines.append(f"{label}: {value}")
    if result.get("brojPromenjen"):
        lines.append("Broj fakture je ažuriran; koristi konačni PDF.")
    return "\n".join(lines)
