# Testiranje i evaluacija

[Pregled projekta](../README.md) · [Arhitektura](ARCHITECTURE.md) · [Rezultati](EVAL.md)

Automatski testovi proveravaju ugovore i rubne slučajeve uz kontrolisane spoljne
odgovore. Eksperimenti sa stvarnim modelima i probe na ličnim nalozima imaju
zasebne rezultate. Broj prolaznih testova nije mera kvaliteta modela niti procenat
pokrivenosti koda.

## Prva proba bez ključeva

Iz korena kloniranog repozitorijuma, uz Python 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
ruff format --check src tests evals scripts
ruff check src tests evals scripts
pytest
python -m evals.contract_eval
python -m scripts.make_contract_examples
```

Ne treba praviti `.env` za ovu probu. Testovi koriste test kredencijale i lažne
spoljne odgovore. Bez `TEST_DATABASE_URL` DB slučajevi se preskaču.
`contract_eval` ima pet unapred definisanih kontrolnih ulaza i ne poziva LLM.
Generator pravi tri izmišljena skenirana PDF-a u `output/pdf/`: uredan ugovor,
ugovor bez dovoljno podataka i ugovor sa uslovnim produženjem.
[Priloženi primeri](../examples/contracts/) mogu se pregledati bez instalacije.

PDF-ovi služe za ručni pregled i kasniju probu `/ugovor`. Njihovo generisanje ne
izvršava OCR; slanje botu pokreće stvarne API pozive prema podešavanjima instalacije.

## Integracioni testovi sa bazom

Koristi **posebnu test bazu**: fixture-i brišu test podatke između slučajeva.
Lokalni Compose izlaže PostgreSQL samo na `127.0.0.1`.

```bash
docker compose up -d db
# Kreiranje test baze je potrebno samo jednom.
docker compose exec db createdb -U dexter dexter_test
TEST_DATABASE_URL=postgresql://dexter:dexter@localhost:5432/dexter_test pytest
```

Na dan 22.10.2026. ceo skup ima **933 prolazna testa** sa PostgreSQL-om i
pgvector-om. Integracioni testovi koriste pravu bazu, SQL migracije i vektorske
upite, uz determinističke test vektore i mock HTTP odgovore.

| Oblast | Primeri provera | Ulaz u testove |
|---|---|---|
| Agent i kontekst | Paralelne poruke, kompletne razmene, nespareni tool blokovi, oporavak sažimanja. | [test_core.py](../tests/test_core.py), [test_history_summary.py](../tests/test_history_summary.py) |
| Pretraga i indeks | Promena sadržaja/konfiguracije, datumi, negativni upiti i očuvanje indeksa pri grešci. | [test_integration.py](../tests/test_integration.py), [test_embeddings.py](../tests/test_embeddings.py) |
| Ugovori i dokumenti | Citat, vrednost i datum, OCR prekid, Work odredište, potvrda i dupli upis. | [test_contracts.py](../tests/test_contracts.py), [test_ocr.py](../tests/test_ocr.py), [test_office.py](../tests/test_office.py) |
| Osetljive radnje | Pregled i dugme, istek, numeracija fakture i delimičan/neizvestan ishod. | [test_invoices.py](../tests/test_invoices.py), [test_confirmation_display.py](../tests/test_confirmation_display.py) |
| Automatika | Cron izrazi, retry, čuvanje ishoda i izostanak ponovljenog slanja. | [test_scheduled_jobs.py](../tests/test_scheduled_jobs.py), [test_scheduler.py](../tests/test_scheduler.py) |
| Integracije i ulaz | IMAP bez promene Seen stanja, API greške, vlasnik bota, voice i TTS tok. | [test_mail_tools.py](../tests/test_mail_tools.py), [test_telegram_bot.py](../tests/test_telegram_bot.py), [test_tts.py](../tests/test_tts.py) |

## Šta CI izvršava

[GitHub Actions](../.github/workflows/ci.yml) na push i pull request pokreće:

1. Ruff format/check i ceo pytest skup uz `pgvector/pgvector:pg17`.
2. Proveru da promena persona prompta ima stvarni pre/posle evaluacioni izveštaj;
   nepromenjen prompt ne pravi API pozive.
3. Sastavljanje wheel paketa, README metapodatke, fontove/licencu fonta i SQL migracije.
4. Docker build osnovne slike i slike sa lokalnim ML bibliotekama.
5. Proveru prisustva fontova, migracija i skripti, rada bez root naloga i
   opstanka upisivog keša između kontejnera.

Build ne preuzima težine lokalnih modela. CI ne koristi privatne naloge niti
izvršava stvarno slanje mejlova, pravih faktura ili Notion upise.

## Reprodukcija eksperimenata

| Oblast | Komanda | Zahtevi i tumačenje |
|---|---|---|
| RAG | `python -m evals.rag_eval --k 5 --oznaka provera` | Popunjen indeks i sopstveni `evals/questions.jsonl`; recall/MRR ne ocenjuju automatski kvalitet generisanog odgovora. |
| Ugovorni dokazi | `python -m evals.contract_eval` | Bez baze i API-ja; proverava verifikator na kontrolnim strukturama. |
| Izbor modela | `python -m evals.economy_eval` | Bez API-ja; raspodela modela na sintetičkim porukama i hipotetički račun. |
| Lokalni embeddinzi | `python -m evals.embedding_bench --modeli small base` | `.[local]`, preuzimanje modela i izdvojena prazna `_bench`/`_test` baza. |
| Glas | `python -m evals.voice_eval` | Dvadeset snimaka sa ručnim prepisima prema [uputstvu](../evals/voice/README.md); stvarni WER još nije izmeren. |
| Fine-tuning | `python -m scripts.train_router --help` | Obuka zahteva `.[train]` i označeni skup; probni rezultat i poređenje sa pravilom su u EVAL.md. |

Poređenja koriste isti skup, indeks i uslove. Posebno navodi da li su model,
embedding, HTTP i baza stvarni ili kontrolisani. Izvoz privatnih skupova, glasovni
snimci i trenirani artefakti ostaju van repozitorijuma.

Za aktuelne rezultate i ograničenja vidi [EVAL.md](EVAL.md). Istorijska matrica
integracija je u [PARITY.md](PARITY.md); njene datirane ručne provere nisu potvrda
trenutnog stanja svakog povezanog naloga.
