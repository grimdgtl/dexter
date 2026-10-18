"""Prilozi i ishodi potvrde ostaju van modelskih argumenata i agentske istorije."""

from dataclasses import dataclass
from typing import Any

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
