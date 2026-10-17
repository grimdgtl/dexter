import threading
from types import SimpleNamespace

import pytest

from apu.config import settings
from apu.rag import embed


async def test_openai_sorts_indices_and_checks_dimensions(monkeypatch, respx_mock):
    monkeypatch.setattr(settings(), "openai_api_key", "test")
    respx_mock.post("https://api.openai.com/v1/embeddings").respond(
        200,
        json={
            "data": [
                {"index": 1, "embedding": [0.0, 1.0] + [0.0] * 1534},
                {"index": 0, "embedding": [1.0] + [0.0] * 1535},
            ],
            "usage": {"total_tokens": 4},
        },
    )
    with embed.measure() as measured:
        vectors = await embed.embed(["prvi", "drugi"])
    assert vectors[0][0] == vectors[1][1] == 1
    assert measured[0]["api_tokens"] == 4


@pytest.mark.parametrize(
    "model,dim", [("intfloat/multilingual-e5-small", 384), ("intfloat/multilingual-e5-base", 768)]
)
async def test_local_prefix_normalization_worker_and_dimensions(monkeypatch, model, dim):
    monkeypatch.setattr(settings(), "embed_provider", "local")
    monkeypatch.setattr(settings(), "embed_local_model", model)
    main = threading.get_ident()

    class Model:
        def encode(self, texts, **kwargs):
            assert threading.get_ident() != main
            assert texts == ["query: Proba"] and kwargs["normalize_embeddings"]
            return [SimpleNamespace(tolist=lambda: [1.0] + [0.0] * (dim - 1))]

    monkeypatch.setattr(embed, "_local_model", lambda name: Model())
    assert len((await embed.embed(["Proba"], kind="query"))[0]) == dim
    assert settings().embed_dim == dim


async def test_invalid_embedding_vectors_fail_before_database(monkeypatch, respx_mock):
    monkeypatch.setattr(settings(), "openai_api_key", "test")
    route = respx_mock.post("https://api.openai.com/v1/embeddings")
    for data in (
        [{"index": 0, "embedding": [1.0]}],
        [{"index": 1, "embedding": [1.0] + [0.0] * 1535}],
        [{"index": 0, "embedding": [0.0] * 1536}],
    ):
        route.respond(200, json={"data": data})
        with pytest.raises(ValueError):
            await embed.embed(["tekst"])
