# APU 2 — lični AI asistent (Python)

Nova verzija APU-a: isti Telegram asistent, ali sa pravom AI osnovom.
Stari APU (Node.js) radi paralelno dok ovaj ne preuzme sve funkcije.

```
Telegram (tekst / glas / slika / PDF)
   │
   ▼
telegram_bot.py ── transkripcija (Whisper API ili lokalno) ── ćirilica → latinica
   │
   ▼
agent/loop.py  ←── memorija: relevantne činjenice uz poruku
   │  ├─ router: Haiku / Sonnet / Opus po težini
   │  ├─ prompt caching: alati + system + istorija
   │  └─ alati se izvršavaju paralelno
   ▼
tools/registry.py ── weather, memory_*, knowledge_search, (+ stari alati, faza 1b)
   │                   └─ alati sa confirm=True čekaju dugme ✅/❌
   ▼
PostgreSQL + pgvector: messages · facts · documents · chunks · usage
```

## Pokretanje

```bash
cp .env.example .env        # popuni TELEGRAM_*, ANTHROPIC_API_KEY, OPENAI_API_KEY
docker compose up -d --build
docker compose logs -f bot
```

Lokalni razvoj bez Docker-a za bota:

```bash
docker compose up -d db
uv venv && uv pip install -e ".[dev]"
DATABASE_URL=postgresql://apu:apu@localhost:5432/apu .venv/bin/apu
```

> Koristi **drugi Telegram bot token** dok stari APU radi — dva procesa na istom
> tokenu daju `409 Conflict`.

## Komande

| Komanda | Šta radi |
|---|---|
| `/troskovi [dana]` | Cena, broj poziva, procenat keša i latencija po modelu |
| `/memorija` | Sve što APU pamti o tebi |
| `/reset` | Briše istoriju razgovora (memorija ostaje) |
| `/duboko <pitanje>` | Forsira najjači model |

Pošalji PDF ili .txt → ide u bazu znanja i pretraživ je odmah.

## Testovi i evaluacija

```bash
pytest                                   # logika, bez baze i mreže
docker compose exec db createdb -U apu apu_test                         # jednom
TEST_DATABASE_URL=postgresql://apu:apu@localhost:5432/apu_test pytest   # + baza
python -m evals.rag_eval --k 5 --oznaka "hybrid-1200"                  # kvalitet pretrage
```

Za eval napravi `evals/questions.jsonl` po uzoru na `questions.example.jsonl`
(~30 pitanja nad svojim podacima). Rezultati se dopisuju u `evals/results/log.jsonl`.

## Plan razvoja

Ceo plan po fazama, sa kriterijumima prihvatanja, je u [`PLAN.md`](PLAN.md).
Pravila za AI agente (Codex) su u [`AGENTS.md`](AGENTS.md).

## Struktura

| Fajl | Uloga |
|---|---|
| `agent/loop.py` | Agentska petlja, caching, paralelni alati |
| `agent/prompts.py` | Persona sagovornika + kontekst po poruci |
| `agent/router.py` | Izbor modela |
| `agent/history.py` | Istorija + zaštita od nesparenih tool poziva |
| `tools/registry.py` | Alat = funkcija + pydantic šema, potvrde, skraćivanje |
| `memory.py` | Dugoročna memorija sa vektorima i automatskim izvlačenjem |
| `rag/` | Seckanje, embeddinzi (OpenAI ili Hugging Face), hybrid pretraga |
| `usage.py` | Tokeni, cena, latencija |
| `pismo.py` | Latinica nametnuta u kodu |
