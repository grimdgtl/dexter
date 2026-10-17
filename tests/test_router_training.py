import asyncio
import json

import pytest

from apu import usage
from scripts import router_dataset, train_router


async def test_turn_scope_isolated_across_concurrent_chats():
    async def task(chat):
        with usage.turn(chat):
            before = usage.turn_id(chat)
            await asyncio.sleep(0)
            assert before == usage.turn_id(chat)
            assert usage.turn_id(chat + 10) is None
            return before

    ids = await asyncio.gather(task(1), task(2))
    assert len(set(ids)) == 2 and usage.turn_id() is None
    with pytest.raises(RuntimeError), usage.turn(1):
        raise RuntimeError("prekid")
    assert usage.turn_id() is None


def test_reviewed_stratified_split_has_no_duplicates_or_leakage(tmp_path):
    rows = [
        {"poruka": f"{level} Poruka {i}", "nivo": level}
        for level in train_router.LEVELS
        for i in range(8)
    ]
    rows.append({"poruka": "ЛАКО, порука 0!", "nivo": "lako"})
    path = tmp_path / "reviewed.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    train, test = train_router.load_split(path)
    assert len(train) == 18 and len(test) == 6
    assert train_router.load_split(path) == (train, test)
    key = train_router.canonical
    assert not {key(r["poruka"]) for r in train} & {key(r["poruka"]) for r in test}
    assert {r["nivo"] for r in test} == set(train_router.LEVELS)
    assert train_router.metrics(["lako", "teško"], ["lako", "srednje"])["tačnost"] == 0.5
    rows.append({"poruka": "lako poruka 0", "nivo": "teško"})
    path.write_text("\n".join(json.dumps(r) for r in rows))
    with pytest.raises(ValueError, match="suprotstavljene"):
        train_router.load_split(path)
    path.write_text('{"poruka":"test","nivo":null}')
    with pytest.raises(ValueError, match="ručno"):
        train_router.load_split(path)


def test_dataset_export_never_overwrites_annotations(tmp_path):
    path = tmp_path / "data.jsonl"
    router_dataset.write_rows(path, [{"poruka": "test", "nivo": "lako"}])
    with pytest.raises(FileExistsError):
        router_dataset.write_rows(path, [])
    assert json.loads(path.read_text())["nivo"] == "lako"
