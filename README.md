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
| `/status` | Aktivni i ugašeni alati, nedostajuća podešavanja, modeli i stanje baze |
| `/poslovi [sati]` | Evidencija zakazanih poslova, uspeha i grešaka (24h podrazumevano) |
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

## Podešavanja integracija

| Promenljiva | Podrazumevano | Uloga |
|---|---|---|
| `NOTION_API_KEY` | prazno | Token Notion integracije; podeli roditeljsku stranicu sa integracijom |
| `SEMANTIC_INDEX_CRON` | `0 4 * * *` | Dnevno osvežavanje znanja po `TIMEZONE` |
| `GOOGLE_CLIENT_ID` | prazno | OAuth klijent iz Google Cloud projekta |
| `GOOGLE_CLIENT_SECRET` | prazno | Tajna istog OAuth klijenta |
| `GOOGLE_REFRESH_TOKEN` | prazno | Trajno odobrenje sa Calendar i Drive scope-ovima |
| `GOOGLE_REDIRECT_URI` | `http://localhost:3000/oauth2callback` | Lokalni callback pomoćne skripte |
| `GOOGLE_CALENDAR_ID` | `primary` | Zajednička priprema za kalendar u Fazi 1b |

`notion_search` traži po naslovu; `notion_read_page` čita i ugnježdene blokove i podstranice.
`knowledge_reindex` osvežava sve podešene izvore ili zadati `izvor`.
Nepromenjen tekst ne troši nove embedding pozive; nestali dokumenti brišu se tek posle
uspešnog obilaska celog izvora. API verzija Notion-a je fiksirana na `2025-09-03`.

Za Google uključi Calendar API i Drive API u istom Google Cloud projektu. Napravi OAuth
klijenta tipa Web application i unesi tačan `GOOGLE_REDIRECT_URI` u dozvoljene redirect URI-je.
Popuni client ID i secret, pa pokreni `python -m scripts.google_auth`. Skripta traži iste
Calendar + Drive dozvole kao stari APU i ispisuje refresh token za `.env`.
Ako je stari token imao samo Calendar pristup, ponovi odobrenje. OAuth aplikacija u
Testing režimu može da izgubi odobrenje posle sedam dana; za stalni rad koristi Production.
`drive_read` vraća do 6000 znakova modelu; indeks čuva ceo tekst Docs, Sheets/CSV, PDF i
tekstualnih fajlova, kroz sve strane rezultata. PDF bez teksta zahteva kasniji OCR (F5.1).

## Uvoz lokalnih dokumenata

Sačuvaj važeće tekstove Zakona o radu, Zakona o zaštiti potrošača i Zakona o PDV-u
kao PDF/txt/md u privatni folder, pa pokreni:

```bash
python -m scripts.ingest_folder /putanja/do/zakona --izvor zakon
```

Uvoz obilazi podfoldere i čuva relativnu putanju u ID-ju (npr. `zakon:rad/zakon.pdf`).
Ponovljeni uvoz preskače nepromenjen sadržaj. Pokvaren fajl se prijavljuje, ostali se
obrađuju, a izlazni kod je 1 ako je makar jedan fajl izazvao grešku. Skripta ne briše
ranije dokumente. Skenirani PDF bez teksta preskače se sa objašnjenjem; OCR je u F5.1.
Pravne dokumente i privatne podatke drži van repozitorijuma ili u ignorisanom `data/`.

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
