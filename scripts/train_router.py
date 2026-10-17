"""CPU fine-tuning i poređenje sa F3.2 na istom izdvojenom skupu."""

import argparse
import asyncio
import hashlib
import json
import random
import re
import time
import unicodedata
from pathlib import Path

from apu.agent.router import pick_model
from apu.config import settings
from apu.pismo import u_latinicu

LEVELS = ("lako", "srednje", "teško")


def canonical(text: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", u_latinicu(text)).casefold()))


def load_split(path: Path, *, seed: int = 42) -> tuple[list[dict], list[dict]]:
    unique = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("poruka"), str)
            or row.get("nivo") not in LEVELS
        ):
            raise ValueError(
                "Svaka poruka mora imati ručno proveren nivo: lako, srednje ili teško."
            )
        key = canonical(row["poruka"])
        if not key:
            raise ValueError("Poruka ne sme biti prazna.")
        if key in unique and unique[key]["nivo"] != row["nivo"]:
            raise ValueError("Ista poruka ima suprotstavljene oznake.")
        unique[key] = {"poruka": u_latinicu(row["poruka"]).strip(), "nivo": row["nivo"]}
    rng, train, test = random.Random(seed), [], []
    for level in LEVELS:
        group = [unique[k] for k in sorted(unique) if unique[k]["nivo"] == level]
        if len(group) < 5:
            raise ValueError("Potrebno je bar pet različitih označenih poruka po nivou.")
        rng.shuffle(group)
        n = max(1, round(len(group) * 0.25))
        test.extend(group[:n])
        train.extend(group[n:])
    rng.shuffle(train)
    rng.shuffle(test)
    return train, test


def metrics(gold, predicted) -> dict:
    if not gold or len(gold) != len(predicted):
        raise ValueError("Za metrike su potrebne uparene oznake.")
    confusion = {}
    for expected, got in zip(gold, predicted, strict=True):
        pair = f"{expected} → {got}"
        confusion[pair] = confusion.get(pair, 0) + 1
    f1 = []
    for level in LEVELS:
        tp = sum(a == b == level for a, b in zip(gold, predicted, strict=True))
        count = gold.count(level) + predicted.count(level)
        f1.append(2 * tp / count if count else 0)
    return {
        "n": len(gold),
        "tačnost": round(sum(a == b for a, b in zip(gold, predicted, strict=True)) / len(gold), 4),
        "macro_f1": round(sum(f1) / len(f1), 4),
        "matrica": confusion,
    }


def train_model(train, test, output: Path, *, model_name, epochs, seed=42):
    import torch
    from datasets import Dataset
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        DataCollatorWithPadding,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    if epochs <= 0:
        raise ValueError("Broj epoha mora biti pozitivan.")
    # Privatni skup i gotov model se ne prepisuju pri ponovljenoj komandi.
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2)
    set_seed(seed)
    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=False)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_name,
        num_labels=3,
        id2label=dict(enumerate(LEVELS)),
        label2id={label: i for i, label in enumerate(LEVELS)},
        trust_remote_code=False,
    )
    load_seconds = time.perf_counter() - started

    def dataset(rows):
        data = Dataset.from_list(
            [{"poruka": r["poruka"], "labels": LEVELS.index(r["nivo"])} for r in rows]
        )
        return data.map(
            lambda batch: tokenizer(batch["poruka"], truncation=True, max_length=128),
            batched=True,
            remove_columns=["poruka"],
        )

    trainer = Trainer(
        model=model,
        processing_class=tokenizer,
        args=TrainingArguments(
            output_dir=str(output),
            use_cpu=True,
            num_train_epochs=epochs,
            per_device_train_batch_size=4,
            per_device_eval_batch_size=4,
            learning_rate=2e-5,
            weight_decay=0.01,
            optim="adamw_torch",
            seed=seed,
            data_seed=seed,
            save_strategy="no",
            report_to=[],
            dataloader_pin_memory=False,
            disable_tqdm=True,
        ),
        data_collator=DataCollatorWithPadding(tokenizer),
        train_dataset=dataset(train),
    )
    started = time.perf_counter()
    trainer.train()
    train_seconds = time.perf_counter() - started
    evaluation = dataset(test)
    started = time.perf_counter()
    predictions = trainer.predict(evaluation).predictions.argmax(axis=-1).tolist()
    ms = 1000 * (time.perf_counter() - started) / len(test)
    gold = [r["nivo"] for r in test]
    cfg = settings()
    tiers = {cfg.model_fast: "lako", cfg.model_main: "srednje", cfg.model_deep: "teško"}
    rule = [tiers[pick_model(r["poruka"])[0]] for r in test]
    split_data = {"trening": train, "test": test}
    fingerprint = hashlib.sha256(
        json.dumps(split_data, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    result = {
        "model": model_name,
        "seed": seed,
        "epohe": epochs,
        "trening_n": len(train),
        "test_n": len(test),
        "podela_sha256": fingerprint,
        "load_seconds": round(load_seconds, 3),
        "train_seconds": round(train_seconds, 3),
        "lokalni": {
            **metrics(gold, [LEVELS[i] for i in predictions]),
            "ms_po_poruci": round(ms, 2),
        },
        "pravilo_f3_2": metrics(gold, rule),
        "api_f3_2": {"izvršeno": False, "razlog": "Pokreni eksplicitno --uporedi-api."},
    }
    trainer.save_model(str(output))
    tokenizer.save_pretrained(output)
    (output / "split.json").write_text(json.dumps(split_data, ensure_ascii=False, indent=2))
    (output / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


async def main(args):
    train, test = await asyncio.to_thread(load_split, args.dataset, seed=args.seed)
    result = await asyncio.to_thread(
        train_model,
        train,
        test,
        args.output,
        model_name=args.model,
        epochs=args.epohe,
        seed=args.seed,
    )
    if args.uporedi_api:
        from apu import db
        from evals.router_eval import evaluate

        try:
            await db.connect()
            result["api_f3_2"] = await evaluate(rows=test)
            await asyncio.to_thread(
                (args.output / "metrics.json").write_text,
                json.dumps(result, ensure_ascii=False, indent=2),
            )
        finally:
            await db.close()
    print(u_latinicu(json.dumps(result, ensure_ascii=False, indent=2)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Trening lokalnog klasifikatora iz proverenih oznaka."
    )
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/router-model"))
    parser.add_argument("--model", default="distilbert/distilbert-base-multilingual-cased")
    parser.add_argument("--epohe", type=float, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--uporedi-api", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(main(args))
    except (ValueError, FileExistsError) as exc:
        parser.error(u_latinicu(str(exc)))
