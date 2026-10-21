# Uputstvo za AI agente (Codex i drugi)

Pre rada pročitaj `README.md` i relevantne delove `docs/OPERATIONS.md`.

## Kako radiš
- Radi prema aktuelnom zahtevu korisnika i proveri postojeću implementaciju pre izmene.
- Jedan zadatak = jedan commit, poruka `F<id>: <kratko, srpski>`.
- Dokumentaciju uskladi sa konačnim ponašanjem i navedi izvršene provere.

## Komande
```bash
uv venv && uv pip install -e ".[dev]"
ruff format src tests evals && ruff check src tests evals
pytest                                   # bez baze
docker compose up -d db
docker compose exec db createdb -U dexter dexter_test   # jednom
TEST_DATABASE_URL=postgresql://dexter:dexter@localhost:5432/dexter_test pytest   # sa bazom
```
Zadatak nije gotov dok ruff i pytest (sa bazom) ne prolaze.

## Ne radi
- Ne ubacuj ništa promenljivo u `SYSTEM_PROMPT` (razbija prompt caching).
- Ne izvršavaj rizične akcije bez `confirm=True` (mejl, faktura, brisanje).
- Ne uzimaj PIB, MB, adresu ni račun od modela — samo iz Notion-a / `.env`-a.
- Ne zovi prave API-je u testovima; mock-uj (`respx`).
- Ne commit-uj `.env`, `data/`, `evals/questions.jsonl`.
- Ne šalji korisniku ćirilicu; sav izlaz ide kroz `pismo.u_latinicu`.
- Ne menjaj šemu baze bez migracije (posle F1.3).

## Stil
- Python 3.12, async svuda; sinhrone biblioteke kroz `asyncio.to_thread`.
- Alat = pydantic model ulaza + `@tool(...)` (šablon: `src/dexter/tools/weather.py`).
- Komentari i tekst za korisnika na srpskom, latinicom. Komentar objašnjava
  ZAŠTO, ne šta.
- Dužina reda 100, ruff pravila iz `pyproject.toml`.
