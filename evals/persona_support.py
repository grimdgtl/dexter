"""Zajednički otisci i čitanje statičnog prompta iz Git-a, bez izvršavanja izvora."""

import ast
import asyncio
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).parent / "persona"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def read_cases(path: Path = HERE / "scenarios.jsonl") -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if (
        len(rows) != 20
        or len({r["id"] for r in rows}) != 20
        or any(not r.get("poruka") or not r.get("očekivanje") or not r.get("primer") for r in rows)
    ):
        raise ValueError("Persona eval zahteva 20 različitih scenarija sa očekivanjem.")
    return rows


def corpus_hash(rows) -> str:
    return digest(json.dumps(rows, ensure_ascii=False, sort_keys=True))


def prompt_from_source(source: str) -> str:
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "SYSTEM_PROMPT" for t in node.targets
        ):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
    raise ValueError("SYSTEM_PROMPT mora biti statična string konstanta.")


async def git_prompt(ref: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./^-]{0,127}", ref):
        raise ValueError("Neispravan Git ref.")
    # Stari commit-i zadržavaju putanju paketa pre preimenovanja u Dexter.
    for path in ("src/dexter/agent/prompts.py", "src/apu/agent/prompts.py"):
        proc = await asyncio.create_subprocess_exec(
            "git",
            "show",
            "--no-ext-diff",
            f"{ref}:{path}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await proc.communicate()
        if not proc.returncode:
            return prompt_from_source(out.decode())
    raise ValueError(f"Git ref {ref} nema dostupan prethodni prompt.")
