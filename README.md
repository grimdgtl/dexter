# APU 2 — lični AI asistent (Python)

[![CI](https://github.com/grimdgtl/dexter/actions/workflows/ci.yml/badge.svg)](https://github.com/grimdgtl/dexter/actions/workflows/ci.yml)

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

Compose koristi `db:5432` iz kontejnera bota, dok lokalni Python koristi `localhost:5432`.
Lozinke `apu:apu` u ovom Compose fajlu namenjene su lokalnom razvoju; produkcionu bazu
podesi zasebno kao u uputstvu ispod.

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

GitHub Actions pokreće ruff i ceo pytest skup uz `pgvector/pgvector:pg17`, uključujući
integracione testove. Koriste se samo test kredencijali i mock odgovori spoljnih API-ja.

```bash
pytest                                   # logika, bez baze i mreže
docker compose exec db createdb -U apu apu_test                         # jednom
TEST_DATABASE_URL=postgresql://apu:apu@localhost:5432/apu_test pytest   # + baza
python -m evals.rag_eval --k 5 --oznaka "hybrid-1200"                  # kvalitet pretrage
```

Za eval napravi `evals/questions.jsonl` po uzoru na `questions.example.jsonl`
(~30 pitanja nad svojim podacima). Rezultati se dopisuju u `evals/results/log.jsonl`.
`python -m evals.rag_eval --uporedi` prikazuje sva prethodna merenja bez povezivanja na
bazu. Postupak i šablon za beleženje promena su u [`docs/EVAL.md`](docs/EVAL.md).

## Podešavanja integracija

| Promenljiva | Podrazumevano | Uloga |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | obavezno | Token zasebnog Telegram bota |
| `TELEGRAM_OWNER_CHAT_ID` | obavezno | Numerički ID vlasnika; ostali razgovori se ignorišu |
| `ANTHROPIC_API_KEY` | obavezno | Ključ za razgovor i generisanje poruka |
| `DATABASE_URL` | lokalni `apu:apu@localhost:5432/apu` | PostgreSQL veza; na serveru koristi interni host baze |
| `MODEL_FAST` / `MODEL_MAIN` / `MODEL_DEEP` | `.env.example` | ID-jevi brzog, glavnog i dubokog modela |
| `MAX_TOKENS` | `8192` | Ograničenje dužine odgovora modela |
| `HISTORY_TURNS` | `12` | Broj razmena u istoriji modela |
| `EMBED_PROVIDER` | `openai` | `openai` ili `local`; promena dimenzije traži ponovnu vektorizaciju |
| `OPENAI_API_KEY` | prazno | Potreban za OpenAI embeddinze i transkripciju |
| `TRANSCRIBE_PROVIDER` | `openai` | `openai` ili `local` |
| `WHISPER_LOCAL_MODEL` | `small` | Lokalni Whisper model uz dodatne `local` zavisnosti |
| `TIMEZONE` | `Europe/Belgrade` | Vremenska zona konteksta i zakazanih poslova |
| `WEATHER_LAT` / `WEATHER_LON` | `44.8125` / `20.4612` | Koordinate prognoze |
| `WEATHER_LOCATION` | `Beograd` | Naziv lokacije u porukama |
| `LOG_LEVEL` | `INFO` | Nivo logovanja |
| `NOTION_API_KEY` | prazno | Token Notion integracije; podeli roditeljsku stranicu sa integracijom |
| `SEMANTIC_INDEX_CRON` | `0 4 * * *` | Dnevno osvežavanje znanja po `TIMEZONE` |
| `GOOGLE_CLIENT_ID` | prazno | OAuth klijent iz Google Cloud projekta |
| `GOOGLE_CLIENT_SECRET` | prazno | Tajna istog OAuth klijenta |
| `GOOGLE_REFRESH_TOKEN` | prazno | Trajno odobrenje sa Calendar i Drive scope-ovima |
| `GOOGLE_REDIRECT_URI` | `http://localhost:3000/oauth2callback` | Lokalni callback pomoćne skripte |
| `GOOGLE_CALENDAR_ID` | `primary` | Zajednička priprema za kalendar u Fazi 1b |
| `IMAP_HOST` | prazno | TLS IMAP server za indeksiranje mejla |
| `IMAP_PORT` | `993` | TLS IMAP port |
| `IMAP_USER` | prazno | Korisničko ime IMAP naloga |
| `IMAP_PASSWORD` | prazno | IMAP lozinka ili app password provajdera |
| `MAIL_INDEX_MONTHS` | `12` | Broj kalendarskih meseci mejla za indeksiranje |
| `MAIL_INDEX_EXCLUDE` | prazno | CSV spisak punih naziva foldera koji se izostavljaju |
| `MAIL_INDEX_SENT_FOLDER` | automatski | Pun naziv Sent foldera kada ga server ne označava standardno |

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

Mejl izvor (`mail`) se uključuje kada su popunjeni `IMAP_HOST`, `IMAP_USER` i
`IMAP_PASSWORD`. Indeksira pročitane i nepročitane poruke iz INBOX-a i poslatih poruka,
od datuma koji određuje `MAIL_INDEX_MONTHS`, u okviru dnevnog `SEMANTIC_INDEX_CRON` posla.
Možeš zatražiti `knowledge_reindex` sa `izvor="mail"`, pa `knowledge_search` sa istim izvorom.
Čitanje ne menja oznake niti sadržaj sandučeta. Datum IMAP pretrage je datum prijema
poruke na serveru; datum zaglavlja ulazi u naslov dokumenta, uz subjekat i pošiljaoca.

Sent se prvo prepoznaje po oznaci servera, pa po uobičajenim nazivima. Za drugačiji naziv
podesi npr. `MAIL_INDEX_SENT_FOLDER=INBOX.Sent`. `MAIL_INDEX_EXCLUDE` poredi pune nazive
bez obzira na velika i mala slova, npr. `INBOX,[Gmail]/Sent Mail`; naziv koji sadrži zarez
stavi u CSV navodnike. Nepostojeći Sent folder prekida osvežavanje uz očuvanje starog
indeksa. Poruke van perioda ili iz isključenih foldera uklanjaju se samo iz indeksa,
tek posle uspešnog obilaska svih izabranih foldera.

ID dokumenta je `mail:<Message-ID>`; kopije iste poruke u više foldera se spajaju.
Poruke bez tog zaglavlja dobijaju stabilan SHA-256 ID. Indeks čuva telo i čitljiv tekst
PDF/tekstualnih priloga do uključivo 5 MiB; veći i nepodržani prilozi se preskaču.
HTML se svodi na tekst bez skripti i stilova. Poruka se preuzima kao MIME celina,
pa granica priloga ograničava indeksiranje, a ne IMAP mrežni saobraćaj.
Alati za čitanje pojedinačnog mejla, draftovi i slanje ostaju u zasebnoj Fazi 1b.

Razgovori su lokalni izvor `razgovor`, dostupan bez dodatnih ključeva za izvore.
Svakog dana u 03:30, u zoni `TIMEZONE`, brzi model sažima sve ranije završene dane
sa sačuvanim porukama vlasnika (`TELEGRAM_OWNER_CHAT_ID`). Prvo pokretanje obrađuje i
propuštene dane. Današnje poruke čekaju narednu noć da dan ne bi bio nepotpun.
Dokument `razgovor:YYYY-MM-DD` sadrži teme, odluke, dogovore, rokove i imena.
Za pretragu ili ručno osvežavanje koristi `knowledge_search` odnosno `knowledge_reindex`
sa `izvor="razgovor"`. Izvor se proverava i tokom redovnog osvežavanja indeksa.

Nepromenjen dan ne troši ponovo model ni embeddinge; naknadno dodate stare poruke
obnavljaju samo taj dan. Dugi dani sažimaju se u delovima pa objedinjuju, bez odsecanja
kraja istorije. Trošak modela beleži se u `usage` kao `conversation_summary`.
Umetnuti kontekst memorije, pozivi/rezultati alata i bajtovi slika ne ulaze u sažetak;
za sliku ostaje samo oznaka da je poslata. Predlozi asistenta nisu potvrđene odluke.
Greška ili nepotpun odgovor modela čuva prethodni indeks i omogućava ponovni pokušaj
kroz isti omotač poslova kao ostali zakazani zadaci. `/reset` briše sirovu istoriju,
ali već indeksirani sažeci ostaju u znanju; poruke obrisane pre sažimanja ne mogu se vratiti.

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

## Deploy na Hetzner / Coolify

APU je pozadinski proces sa Telegram long polling-om. Potreban je server sa Docker-om,
Coolify instancom i izlaznim HTTPS pristupom za Telegram, Anthropic, OpenAI i podešene
integracije. Instalacija servera i kupovina resursa nisu deo ove procedure.

1. Na istom serveru napravi **poseban PostgreSQL servis** sa image-om
   `pgvector/pgvector:pg17`. Podesi bazu i korisnika `apu`, svoju jaku lozinku i trajni
   volume na **`/var/lib/postgresql/data`**. Koristi internu Docker mrežu; javni port
   baze nije potreban. Coolify podržava odvojene resurse i
   [trajno skladište](https://coolify.io/docs/core/persistent-storage/storage-mounts/overview).
2. Kreiraj aplikaciju iz ovog Git repozitorijuma. Izaberi **Dockerfile** build,
   build context koren repoa, Dockerfile `/Dockerfile`, podrazumevanu komandu `apu`.
   Docker build uključuje SQL migracije u instalirani Python paket.
   Detalji podešavanja su u [Coolify Dockerfile dokumentaciji](https://coolify.io/docs/applications/builds/dockerfile).
3. Za bota ostavi **Domains, Ports Exposes i port mappings prazne** i isključi
   **HTTP Health Check**. Bot nema HTTP server; stanje se proverava kroz logove i Telegram.
   Health check PostgreSQL servisa ostaje uključen.
4. U aplikaciji podesi trajni **Volume Mount** naziva npr. `apu-data`, sa Destination
   Path **`/app/data`**. Novi named volume ne traži Source Path. Tu se čuvaju keš
   lokalnih modela i radni fajlovi; razgovori, memorija i indeks su u bazi.
   Image radi kao korisnik `apu` sa UID **10001**. Ako koristiš postojeći bind mount ili
   vraćen volume, njegov vlasnik mora omogućiti pisanje tom UID-ju.
5. U Runtime Environment Variables unesi vrednosti iz `.env.example`. `DATABASE_URL`
   mora koristiti **interni host produkcione baze**, npr.
   `postgresql://apu:<lozinka>@<interni-db-host>:5432/apu`. Specijalne znakove u lozinci
   URL-kodiraj. Bota i bazu poveži u istoj Docker mreži. API ključevi se unose pri
   pokretanju, bez build argumenata i bez `.env` fajla u image-u.
6. Koristi **drugi Telegram bot token dok stari APU radi**. Pokreni jednu repliku
   novog bota. Dva procesa na istom tokenu izazivaju `409 Conflict`, a Faza 1b još
   prenosi ostale stare funkcije. Glavni token preuzima se tek prema F1b.11.
7. Pokreni bazu, zatim Deploy aplikacije. `db.connect` automatski primenjuje nove
   migracije u transakciji i pamti ih u `schema_migrations`. Ako aplikacioni DB nalog
   nema pravo za instalaciju ekstenzija, administrator prvo izvršava
   `CREATE EXTENSION IF NOT EXISTS vector;` u izabranoj bazi. Aplikacioni nalog mora
   imati pravo da kreira tabele i indekse za migracije.
8. U logovima proveri poruke „Baza spremna”, „Aktivni alati” i „Scheduler pokrenut”.
   U Telegramu proveri `/start`, `/status` i `/poslovi 24`. Potvrdi da dokumenti i
   činjenice ostaju posle redeploy-a. Notion zahteva deljenje stranica sa integracijom;
   Google token se dobija lokalno preko `python -m scripts.google_auth`.

Podesi redovan backup baze (`pg_dump`) i app volume-a, uz proveru vraćanja kopije u
posebnu bazu. Pre izmene šeme napravi backup. Za lokalni Compose named volume-i su
`apu-pg` i `apu-data`; `docker compose down` ih zadržava, dok `down -v` briše njihove podatke.
Zadržavanje samo app volume-a ne čuva razgovore ni indeks — potreban je i PostgreSQL volume.

U ovoj fazi kreirani su kod i uputstvo. Ručna provera pravog Telegram-a, Google naloga,
GitHub CI izvršavanja i server deploy-a zavisi od tvojih naloga i okruženja.

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
