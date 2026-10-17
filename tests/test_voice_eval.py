import json
import threading
from types import SimpleNamespace

import pytest

from apu import transcribe
from apu.config import settings
from evals import voice_eval


def test_wer_normalization_and_manifest_validation(tmp_path):
    assert voice_eval.normalize("ЉУБАВ, Марко!") == "ljubav marko"
    with pytest.raises(ValueError, match="Pripremi"):
        voice_eval.read_manifest(tmp_path / "manifest.jsonl")
    path = tmp_path / "manifest.jsonl"
    path.write_text('{"fajl":"../van.ogg","tekst":"test"}\n')
    with pytest.raises(ValueError):
        voice_eval.read_manifest(path, required=1)


async def test_voice_benchmark_uses_twenty_same_clips_and_real_wer(
    tmp_path, monkeypatch, respx_mock
):
    rows = []
    for i in range(20):
        name = f"{i}.wav"
        (tmp_path / name).write_bytes(b"test audio")
        rows.append({"fajl": name, "tekst": "Zdravo Marko"})
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("\n".join(json.dumps(r) for r in rows))
    data = voice_eval.read_manifest(manifest)
    monkeypatch.setattr(settings(), "openai_api_key", "test")
    respx_mock.post("https://api.openai.com/v1/audio/transcriptions").respond(
        200, json={"text": "Здраво, Марко!"}
    )
    main = threading.get_ident()
    names = []

    class Model:
        def __init__(self, name):
            self.name = name

        def transcribe(self, audio, **kwargs):
            assert kwargs["language"] == "sr"

            def segments():
                assert threading.get_ident() != main
                yield SimpleNamespace(
                    text="Zdravo Petar" if self.name == "small" else "Zdravo Marko"
                )

            return segments(), None

    def load(name):
        names.append(name)
        return Model(name)

    monkeypatch.setattr(transcribe, "_local_model", load)
    reports = await voice_eval.benchmark(data)
    assert [r["wer"] for r in reports] == [0, 0.5, 0]
    assert all(r["n"] == 20 for r in reports)
    assert len({r["korpus_sha256"] for r in reports}) == 1
    assert "small" in names and "medium" in names
    assert "Zdravo" not in json.dumps(reports)
