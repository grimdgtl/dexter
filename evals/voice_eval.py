"""WER i trajanje na istih 20 privatnih snimaka, bez njihovog upisa u rezultate."""

import argparse
import asyncio
import hashlib
import json
import re
import statistics
import time
import unicodedata
from pathlib import Path
from unittest.mock import patch

from apu import transcribe
from apu.config import settings
from apu.pismo import u_latinicu

HERE = Path(__file__).parent


def normalize(text: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", u_latinicu(text)).casefold()))


def read_manifest(path: Path, *, required: int = 20) -> list[dict]:
    if not path.is_file():
        raise ValueError(
            "Pripremi manifest sa 20 snimaka i ručnim transkriptima; primer je u evals/voice/."
        )
    root = path.parent.resolve()
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len(rows) != required:
        raise ValueError(f"Manifest mora imati tačno {required} snimaka.")
    seen = set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("fajl"), str)
            or not isinstance(row.get("tekst"), str)
        ):
            raise ValueError(
                "Svaki red mora imati fajl i ručni tekst (može biti prazan za tišinu)."
            )
        audio = (root / row["fajl"]).resolve()
        if not audio.is_relative_to(root) or not audio.is_file() or audio in seen:
            raise ValueError(
                "Snimci moraju biti jedinstveni postojeći fajlovi unutar foldera manifesta."
            )
        row["path"] = audio
        seen.add(audio)
    return rows


async def benchmark(rows, models=("openai", "small", "medium")) -> list[dict]:
    from jiwer import wer

    if not rows:
        raise ValueError("Nema snimaka za merenje.")
    clips = [await asyncio.to_thread(r["path"].read_bytes) for r in rows]
    refs = [normalize(r["tekst"]) for r in rows]
    fingerprint = hashlib.sha256(
        json.dumps(
            [
                (hashlib.sha256(audio).hexdigest(), ref)
                for audio, ref in zip(clips, refs, strict=True)
            ]
        ).encode()
    ).hexdigest()
    reports = []
    for model in models:
        if model not in {"openai", "small", "medium"}:
            raise ValueError("Model mora biti openai, small ili medium.")
        if model == "openai" and not settings().openai_api_key:
            reports.append(
                {"model": "whisper-1", "izvršeno": False, "razlog": "Nema OPENAI_API_KEY."}
            )
            continue
        with (
            patch.object(
                settings(), "transcribe_provider", "openai" if model == "openai" else "local"
            ),
            patch.object(settings(), "whisper_local_model", model),
        ):
            started = time.perf_counter()
            if model != "openai":
                await asyncio.to_thread(transcribe._local_model, model)
            load = time.perf_counter() - started
            hypotheses, times = [], []
            for row, audio in zip(rows, clips, strict=True):
                start = time.perf_counter()
                hypotheses.append(normalize(await transcribe.transcribe(audio, row["path"].name)))
                times.append(time.perf_counter() - start)
            reports.append(
                {
                    "model": "whisper-1" if model == "openai" else model,
                    "izvršeno": True,
                    "n": len(rows),
                    "wer": round(wer(refs, hypotheses), 4),
                    "load_seconds": round(load, 3),
                    "seconds_per_clip": round(statistics.mean(times), 3),
                    "total_seconds": round(sum(times), 3),
                    "korpus_sha256": fingerprint,
                }
            )
    return reports


async def main(manifest, models, output):
    rows = await asyncio.to_thread(read_manifest, manifest)
    reports = await benchmark(rows, models)
    text = u_latinicu(json.dumps(reports, ensure_ascii=False, indent=2))
    print(text)
    if output:
        await asyncio.to_thread(output.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(output.write_text, text + "\n")
    return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="WER za 20 sopstvenih snimaka: API, small i medium."
    )
    parser.add_argument("--manifest", type=Path, default=HERE / "voice" / "manifest.jsonl")
    parser.add_argument(
        "--modeli",
        nargs="+",
        choices=["openai", "small", "medium"],
        default=["openai", "small", "medium"],
    )
    parser.add_argument("--output", type=Path, default=Path("data/voice-results.json"))
    args = parser.parse_args()
    try:
        asyncio.run(main(args.manifest, args.modeli, args.output))
    except ValueError as exc:
        parser.error(u_latinicu(str(exc)))
