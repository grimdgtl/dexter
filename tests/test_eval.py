"""Poređenje eval pokretanja mora raditi bez modela i baze."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from evals import rag_eval


def test_comparison_includes_all_runs_without_database(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rag_eval, "HERE", tmp_path)
    connect = AsyncMock(side_effect=AssertionError("Baza ne sme da se pozove"))
    monkeypatch.setattr(rag_eval.db, "connect", connect)
    (tmp_path / "results").mkdir()
    rows = [
        {"oznaka": "staro", "k": 5, "recall_at_k": 0.5, "mrr": 0.4, "ms_po_upitu": 100},
        {
            "datum": "2026-10-15",
            "oznaka": "novo",
            "k": 5,
            "recall_at_k": 0.8,
            "mrr": 0.7,
            "ms_po_upitu": 90,
        },
    ]
    (tmp_path / "results" / "log.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    rag_eval.cli(["--uporedi"])
    text = capsys.readouterr().out
    assert "staro" in text and "novo" in text and "2026-10-15" in text and "—" in text
    connect.assert_not_awaited()


def test_comparison_empty_and_invalid_log(tmp_path):
    assert "Nema prethodnih" in rag_eval.comparison(rag_eval.read_log(tmp_path / "missing"))
    path = tmp_path / "log.jsonl"
    path.write_text('{"oznaka": "ok"}\nloš zapis\n')
    with pytest.raises(ValueError, match=r"log\.jsonl:2"):
        rag_eval.read_log(path)


async def test_eval_records_date_metrics_and_closes_database(tmp_path, monkeypatch):
    monkeypatch.setattr(rag_eval, "HERE", tmp_path)
    (tmp_path / "questions.jsonl").write_text('{"pitanje":"Test?","dokument":"notion:1"}\n')
    monkeypatch.setattr(rag_eval.db, "connect", AsyncMock())
    close = AsyncMock()
    monkeypatch.setattr(rag_eval.db, "close", close)
    monkeypatch.setattr(
        rag_eval.store, "search", AsyncMock(return_value=[SimpleNamespace(document_id="notion:1")])
    )
    result = await rag_eval.main(5, "test")
    assert result["recall_at_k"] == result["mrr"] == 1
    assert result["datum"] and result["n"] == 1
    assert rag_eval.read_log(tmp_path / "results" / "log.jsonl") == [result]
    close.assert_awaited_once()


async def test_missing_questions_do_not_connect(tmp_path, monkeypatch):
    monkeypatch.setattr(rag_eval, "HERE", tmp_path)
    connect = AsyncMock()
    monkeypatch.setattr(rag_eval.db, "connect", connect)
    with pytest.raises(ValueError, match="Napravi"):
        await rag_eval.main(5, "test")
    connect.assert_not_awaited()


def test_negative_metrics_and_deduplication():
    result = rag_eval.metrics([["a", "a", "b"], [], ["c"], []], ["a", None, None, "d"], 5)
    assert result["recall_at_k"] == result["mrr"] == 0.5
    assert result["precision"] == 0.5
    assert result["precision_at_k"] == 0.333
    assert result["negative_accuracy"] == 0.5
    assert result["n_positive"] == result["n_negative"] == 2
    assert rag_eval.metrics([[]], [None], 5)["negative_accuracy"] == 1
    assert rag_eval.metrics([], [], 5)["precision"] == 0
    with pytest.raises(ValueError):
        rag_eval.metrics([], [], 0)


def test_questions_accept_explicit_null_but_reject_missing_id(tmp_path):
    path = tmp_path / "questions.jsonl"
    path.write_text('{"pitanje":"Nema odgovora?","dokument":null}\n')
    assert rag_eval.read_questions(path)[0]["dokument"] is None
    for bad in (
        '{"pitanje":"Test"}',
        '{"pitanje":"Test","dokument":""}',
        '{"pitanje":"Test","dokument":42}',
    ):
        path.write_text(bad)
        with pytest.raises(ValueError):
            rag_eval.read_questions(path)


async def test_negative_question_is_miss_only_when_something_is_returned(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(rag_eval, "HERE", tmp_path)
    (tmp_path / "questions.jsonl").write_text('{"pitanje":"Nepoznato?","dokument":null}\n')
    monkeypatch.setattr(rag_eval.db, "connect", AsyncMock())
    monkeypatch.setattr(rag_eval.db, "close", AsyncMock())
    search = AsyncMock(return_value=[])
    monkeypatch.setattr(rag_eval.store, "search", search)
    assert (await rag_eval.main(5, "negativno"))["negative_accuracy"] == 1
    assert "PROMAŠAJ:" not in capsys.readouterr().out
    search.return_value = [SimpleNamespace(document_id="doc:1")]
    assert (await rag_eval.main(5, "pogrešno"))["negative_accuracy"] == 0
    assert "PROMAŠAJ:" in capsys.readouterr().out


async def test_eval_forwards_source_and_period(tmp_path, monkeypatch):
    from datetime import date

    monkeypatch.setattr(rag_eval, "HERE", tmp_path)
    path = tmp_path / "questions.jsonl"
    path.write_text(
        '{"pitanje":"Orion?","dokument":null,"izvor":"razgovor",'
        '"od":"2026-09-01","do":"2026-09-30"}\n'
    )
    monkeypatch.setattr(rag_eval.db, "connect", AsyncMock())
    monkeypatch.setattr(rag_eval.db, "close", AsyncMock())
    search = AsyncMock(return_value=[])
    monkeypatch.setattr(rag_eval.store, "search", search)
    await rag_eval.main(5, "period")
    search.assert_awaited_once_with(
        "Orion?", limit=15, source="razgovor", date_from=date(2026, 9, 1), date_to=date(2026, 9, 30)
    )
    path.write_text('{"pitanje":"Orion?","dokument":null,"od":"2026-10-01","do":"2026-09-30"}\n')
    with pytest.raises(ValueError, match="neispravan period"):
        rag_eval.read_questions(path)
