# Dexter — lični AI asistent (Python)

[![CI](https://github.com/grimdgtl/dexter/actions/workflows/ci.yml/badge.svg)](https://github.com/grimdgtl/dexter/actions/workflows/ci.yml)

Dexter je lični AI asistent na Telegramu, naslednik starog APU-a.
Stari APU (Node.js) radi paralelno dok ovaj ne preuzme sve funkcije.

Python paket i komanda za pokretanje zovu se `dexter` (`python -m dexter.main`
ili `dexter` posle instalacije). Telegram ime i username biraš preko BotFather-a.
Ako već imaš bazu ili Docker volume-e sa starim imenom, sačuvaj njihov `DATABASE_URL`
i eksplicitno poveži postojeće volume-e pre pokretanja novog Compose fajla.
Promena naziva u kodu ne preimenuje bazu, DB korisnika ili postojeće volume-e.

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
Lozinke `dexter:dexter` u ovom Compose fajlu namenjene su lokalnom razvoju; produkcionu bazu
podesi zasebno kao u uputstvu ispod.

Lokalni razvoj bez Docker-a za bota:

```bash
docker compose up -d db
uv venv && uv pip install -e ".[dev]"
DATABASE_URL=postgresql://dexter:dexter@localhost:5432/dexter .venv/bin/dexter
```

> Koristi **drugi Telegram bot token** dok stari APU radi — dva procesa na istom
> tokenu daju `409 Conflict`.

## Komande

| Komanda | Šta radi |
|---|---|
| `/status` | Aktivni i ugašeni alati, nedostajuća podešavanja, modeli i stanje baze |
| `/poslovi [sati]` | Evidencija zakazanih poslova, uspeha i grešaka (24h podrazumevano) |
| `/troskovi [dana]` | Cena, broj poziva, procenat keša i latencija po modelu |
| `/memorija` | Sve što Dexter pamti o tebi |
| `/reset` | Briše istoriju razgovora (memorija ostaje) |
| `/duboko <pitanje>` | Forsira najjači model |

Pošalji PDF ili .txt → ide u bazu znanja i pretraživ je odmah.

## Testovi i evaluacija

GitHub Actions pokreće ruff i ceo pytest skup uz `pgvector/pgvector:pg17`, uključujući
integracione testove. Koriste se samo test kredencijali i mock odgovori spoljnih API-ja.

```bash
pytest                                   # logika, bez baze i mreže
docker compose exec db createdb -U dexter dexter_test                         # jednom
TEST_DATABASE_URL=postgresql://dexter:dexter@localhost:5432/dexter_test pytest   # + baza
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
| `DATABASE_URL` | lokalni `dexter:dexter@localhost:5432/dexter` | PostgreSQL veza; na serveru koristi interni host baze |
| `MODEL_FAST` / `MODEL_MAIN` / `MODEL_DEEP` | `.env.example` | ID-jevi brzog, glavnog i dubokog modela |
| `SCHEDULER_ENABLED` | `on`; primer koristi `off` | Automatski poslovi; za prvi test deploy isključi sa `off` |
| `MAX_TOKENS` | `8192` | Ograničenje dužine odgovora modela |
| `HISTORY_TURNS` | `12` | Broj razmena u istoriji modela |
| `EMBED_PROVIDER` | `openai` | `openai` ili `local`; promena dimenzije traži ponovnu vektorizaciju |
| `EMBED_LOCAL_MODEL` | `intfloat/multilingual-e5-small` | E5 small (384) ili `intfloat/multilingual-e5-base` (768); promena traži reembed |
| `PROMPT_CACHE` | `on` | `off` uklanja sve cache breakpointe iz zahteva za poređenje troška |
| `ROUTER_MODE` | `rule` | `classifier` uključuje brzi klasifikator; kvar vraća izbor pravilom |
| `STREAMING` | `on` | Postepen prikaz u Telegramu; `off` šalje samo gotov odgovor |
| `DAILY_BUDGET_USD` | nije postavljeno | Pozitivan dnevni budžet za modele iz `usage`; 80% upozorenje, 100% brzi model |
| `CHUNK_CHARS` | `2000` | Veličina tela dela pre dodavanja naslova; najmanje 100 znakova |
| `CHUNK_OVERLAP` | `200` | Preklapanje, od 0 do manje od `CHUNK_CHARS` |
| `RERANK` | `off` | `on` uključuje brzi model za preslaganje do 20 hybrid kandidata |
| `RAG_MIN_SIMILARITY` | `0.3` | Najmanji kosinus za odlomak bez full-text pogotka; opseg 0–1 |
| `OPENAI_API_KEY` | prazno | Potreban za OpenAI embeddinze, transkripciju i glasovni odgovor |
| `TRANSCRIBE_PROVIDER` | `openai` | `openai` ili `local` |
| `WHISPER_LOCAL_MODEL` | `small` | Lokalni Whisper model uz dodatne `local` zavisnosti |
| `OCR_MAX_PAGES` | `20` | Najviše stranica bez tekstualnog sloja za OCR jednog PDF-a; prekoračenje odbija ceo uvoz |
| `GLAS_ODGOVOR` | `off` | `on` dodaje glasovni odgovor na primljene glasovne/audio poruke; tekst se šalje uvek |
| `TTS_MODEL` | `gpt-4o-mini-tts` | OpenAI model za sintezu glasa, uz `OPENAI_API_KEY` |
| `TTS_VOICE` | `coral` | Glas podržan izabranim TTS modelom |
| `TIMEZONE` | `Europe/Belgrade` | Vremenska zona konteksta i zakazanih poslova |
| `QUIET_HOURS` | `22-07` | Tišina za proaktivne poruke; HH-HH, isti početak/kraj znači ceo dan |
| `WEATHER_LAT` / `WEATHER_LON` | `44.8125` / `20.4612` | Koordinate prognoze |
| `WEATHER_LOCATION` | `Beograd` | Naziv lokacije u porukama |
| `LOG_LEVEL` | `INFO` | Nivo logovanja |
| `NOTION_API_KEY` | prazno | Token Notion integracije; podeli roditeljsku stranicu sa integracijom |
| `NOTION_TASKS_DB_ID` | prazno | TASK BOARD za proaktivni uvid: Name/Status i opciona Date kolona Rok |
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
Sa `RERANK=on`, brzi model preslaže do 20 hybrid odlomaka pre odabira `limit` rezultata.
Vraćeni indeksi moraju biti potpuna permutacija; pri grešci, odsečenom odgovoru ili
čekanju dužem od 10 sekundi ostaje hybrid redosled. Trošak se beleži kao `usage.purpose=rerank`.
Opcija je podrazumevano ugašena dok privatni eval ne potvrdi dobitak u odnosu na cenu i čekanje.
Pre preslaganja se odbacuju odlomci bez full-text pogotka čiji je kosinus ispod
`RAG_MIN_SIMILARITY`. Zato nepoznat upit može dati praznu listu. Tačan full-text pogodak
(npr. PIB) prolazi i sa slabim vektorom. RRF ocena služi za rangiranje i nije kosinus.
Eval prihvata `"dokument": null` za pitanja na koja indeks nema odgovor. Recall i MRR
računaju se samo nad pozitivnim pitanjima; `precision` je udeo upita sa rezultatom čiji
top k sadrži očekivani dokument, a `negative_accuracy` udeo negativnih pitanja bez rezultata.
`precision_at_k` meri relevantne jedinstvene dokumente među svim vraćenim top k dokumentima.
Ako nema vraćenih rezultata, obe preciznosti su 0; bez negativnih pitanja njihova tačnost
je null. Za kalibraciju poredi ista pitanja sa npr. `RAG_MIN_SIMILARITY=0`, `0.15`, `0.3`
i `0.45` kroz `python -m evals.rag_eval --oznaka prag-03`, pa pogledaj `--uporedi`.
`knowledge_search` prihvata `od` i `do` kao uključive datume `YYYY-MM-DD` u `TIMEZONE`.
Na primer, `izvor="razgovor", od="2026-09-01", do="2026-09-30"` pretražuje septembar.
Isti opciono zadati `izvor`, `od` i `do` mogu stajati u redu eval pitanja.
Filter se primenjuje pre limita kandidata i pre preslaganja, u obe grane pretrage.

`documents.modified_at` označava poslednju izmenu Notion/Drive dokumenta, datum slanja
mejla iz zaglavlja, lokalni dan razgovora, `mtime` lokalnog fajla ili vreme uvoza fajla
poslatog Telegramom. Odgovor alata sadrži i `datum` izvora. To nije vreme indeksiranja:
promena seckanja ga čuva, a nova izmena samo metapodataka ne troši embeddinge.
Starim dokumentima migracija ostavlja nepoznat datum kao null. Takvi dokumenti ostaju
pretraživi bez perioda, a pri filtriranju se izostavljaju. Osveži izvore/ponovo uvezi fajlove
da se datumi popune; `scripts.reindex_all` može obnoviti datum starog sažetka iz njegovog ID-ja.
Izmena lokalnog zakonskog fajla označava izmenu fajla, a ne datum stupanja zakona na snagu.
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

Posle promene seckanja pokreni `python -m scripts.reindex_all` (opciono `--izvor zakon`).
Tekstovi se ponovo seckaju iz baze bez preuzimanja izvora. Otisak indeksa uključuje
veličinu, preklapanje i embedding provajdera, pa promena zaobilazi keš sadržaja.
Migracija dodaje izvorni tekst; stare dokumente bez njega prvo obnovi preko
`knowledge_reindex` ili ponovnim uvozom lokalnih fajlova. Skripta prijavljuje sve takve
ID-jeve pre izmena i ne pokušava da rekonstruiše tekst iz preklopljenih delova.
Za stari sažetak čija je sirova istorija već obrisana potreban je ponovni uvoz sačuvanog
teksta; automatska obnova tada nije moguća. Novi sažeci čuvaju tekst u bazi.

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

Dexter je pozadinski proces sa Telegram long polling-om. Potreban je server sa Docker-om,
Coolify instancom i izlaznim HTTPS pristupom za Telegram, Anthropic, OpenAI i podešene
integracije. Instalacija servera i kupovina resursa nisu deo ove procedure.

1. Na istom serveru napravi **poseban PostgreSQL servis** sa image-om
   `pgvector/pgvector:pg17`. Podesi bazu i korisnika `dexter`, svoju jaku lozinku i trajni
   volume na **`/var/lib/postgresql/data`**. Koristi internu Docker mrežu; javni port
   baze nije potreban. Coolify podržava odvojene resurse i
   [trajno skladište](https://coolify.io/docs/core/persistent-storage/storage-mounts/overview).
2. Kreiraj aplikaciju iz ovog Git repozitorijuma. Izaberi **Dockerfile** build,
   build context koren repoa, Dockerfile `/Dockerfile`, podrazumevanu komandu `dexter`.
   Docker build uključuje SQL migracije u instalirani Python paket.
   Detalji podešavanja su u [Coolify Dockerfile dokumentaciji](https://coolify.io/docs/applications/builds/dockerfile).
3. Za bota ostavi **Domains i port mappings prazne** i isključi
   **HTTP Health Check**. Bot nema HTTP server; stanje se proverava kroz logove i Telegram.
   Ako Coolify traži **Ports Exposes**, ostavi `3000` kao internu oznaku bez domena
   i bez mapiranja na host. To ne pokreće HTTP server u botu.
   Health check PostgreSQL servisa ostaje uključen.
4. U aplikaciji podesi trajni **Volume Mount** naziva npr. `dexter-data`, sa Destination
   Path **`/app/data`**. Novi named volume ne traži Source Path. Tu se čuvaju keš
   lokalnih modela i radni fajlovi; razgovori, memorija i indeks su u bazi.
   Image radi kao korisnik `dexter` sa UID **10001**. Ako koristiš postojeći bind mount ili
   vraćen volume, njegov vlasnik mora omogućiti pisanje tom UID-ju.
5. U Runtime Environment Variables unesi vrednosti iz `.env.example`. `DATABASE_URL`
   mora koristiti **interni host produkcione baze**, npr.
   `postgresql://dexter:<lozinka>@<interni-db-host>:5432/dexter`. Specijalne znakove u lozinci
   URL-kodiraj. Bota i bazu poveži u istoj Docker mreži. API ključevi se unose pri
   pokretanju, bez build argumenata i bez `.env` fajla u image-u.
6. Koristi **drugi Telegram bot token dok stari APU radi**. Pokreni jednu repliku
   novog bota. Dva procesa na istom tokenu izazivaju `409 Conflict`, a Faza 1b još
   prenosi ostale stare funkcije. Glavni token preuzima se tek prema F1b.11.
   Za prvi test postavi **`SCHEDULER_ENABLED=off`**; to zaustavlja sve automatske
   poslove, uključujući indeksiranje i proaktivne poruke, dok razgovor i ručni alati
   ostaju dostupni. Promena na `on` zahteva restart/redeploy. Tajne i ovu zastavicu
   unesi kao Runtime promenljive; Build time im nije potreban.
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
`dexter-pg` i `dexter-data`; `docker compose down` ih zadržava, dok `down -v` briše njihove podatke.
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

Benchmark troška: napravi zasebnu PostgreSQL bazu sa sufiksom `_bench` ili `_test`,
podesi `DATABASE_URL`, pa pokreni `python -m evals.cost_bench --uporedi`.
Pušta 50 fiksnih javnih poruka; alati i izvlačenje memorije su lažni. Model je pravi,
a `--simulacija` uključuje kontrolni model bez API poziva. Izveštaj sadrži cenu,
udeo keša, prosečnu/p95 latenciju i otisak skupa. Privremena istorija se briše;
redovi `usage` ostaju u izdvojenoj bazi. `PROMPT_CACHE=off` uklanja breakpointe iz
celog zahteva bez promene statičkog sistemskog prompta.

Izbor modela: `ROUTER_MODE=classifier` dodaje brzi poziv koji vraća lako/srednje/teško.
Neispravan odgovor ili čekanje preko tri sekunde vraća postojeće pravilo. `/duboko`
i `duboko:` direktno biraju jaki model. Slike ostaju na glavnom modelu.
`python -m evals.router_eval` poredi oba pristupa na 40 unapred označenih sintetičkih
poruka; `--simulacija` koristi kontrolne oznake kao odgovor lažnog modela.
Oznake treba potvrditi i proširiti svojim slučajevima pre uključivanja klasifikatora;
podrazumevano ostaje `rule` dok pravi eval ne potvrdi kvalitet i ukupan trošak.

Telegram podrazumevano prikazuje odgovor dok `messages.stream` vraća tekst.
Ista poruka se menja najviše jednom u sekundi; dugi odgovori prelaze u dodatne poruke.
Tekst pre poziva alata ostaje zaseban uvod. Alati i dalje čekaju celovitu SDK poruku,
a rizične akcije dugme za potvrdu. Istorija se upisuje tek posle završene agentske razmene.
Ako prikaz zakaže, bot pokušava da pošalje gotov odgovor; `STREAMING=off` vraća raniji
način slanja. Prekid modelskog streama javlja grešku, bez upisa nepotpune razmene;
već prijavljeni tokeni ulaze u `usage` i pri prekidu.

`DAILY_BUDGET_USD` je opcion pozitivan iznos. Trošak se sabira iz `usage` po danu u
`TIMEZONE`; na 80% bot upozorava, a na 100% svaki sledeći modelski poziv koristi
`MODEL_FAST`, uključujući `/duboko`, streaming i pozadinske poslove. Upozorenja se
pamte u PostgreSQL-u, pa se ne ponavljaju posle restarta. Od lokalne ponoći izbor
modela ponovo radi uobičajeno. Neuspešno slanje upozorenja se ponavlja pri sledećoj proveri.
Ako stanje budžeta ne može da se pročita, koristi se brzi model. Ovo je meko
ograničenje: poziv koji prelazi prag i već započeti paralelni pozivi mogu prekoračiti
iznos; dalji rad brzim modelom i dalje košta. Budžet obuhvata evidentirane modelske
pozive, a ne IMAP/Google/Telegram, embeddinge ili transkripciju koji nisu u `usage`.
Cene u `usage.PRICES` treba proveriti za konkretne modele. Bez promenljive je isključen.

Kontekst starog razgovora: agent zadržava poslednjih `HISTORY_TURNS` celih razmena,
a stariji prefiks sažima brzim modelom u tabelu `conversation_context` (migracija 006).
Sažetak i granica obrađenih poruka preživljavaju restart. U sledećem zahtevu se sažimaju
samo novije razmene koje su izašle iz prozora, uz prethodni sažetak. Sažetak je podatak
u trenutnom `<kontekst>` bloku; ne dodaje se u SYSTEM_PROMPT niti umnožava u porukama
sačuvane istorije. Dugi prefiksi prolaze kroz ograničene delove bez odsecanja kraja.
Sirove poruke ostaju u bazi radi dnevnog izvora `razgovor` i pregleda.

Trošak sažimanja vidi se kao `usage.purpose=history_summary`. Neuspešan ili odsečen
sažetak ne pomera granicu ni prethodni tekst; korisnik dobija grešku i može ponoviti
poruku. `/reset` briše i ovaj sažetak, uz sirovu istoriju i pending napomene, dok
trajna memorija i već indeksirani dnevni sažeci ostaju. Istovremeni reset ne može
vratiti stari kontekst. Slike se predstavljaju oznakom bez base64 sadržaja; potvrde,
otkazivanja i rezultati alata prenose se kao podaci, bez ponovnog izvršavanja.

Promena embedding prostora: zaustavi bot, sačuvaj backup baze, postavi novi
`EMBED_PROVIDER`, pa pokreni `python -m scripts.reembed` sa istim `DATABASE_URL`.
Migracija 007 beleži model i dimenziju. Skripta ponovo vektorizuje SVE sačuvane
`chunks.text` i `facts.text`, bez preuzimanja izvora, uz očuvanje ID-jeva i metapodataka.
Privremene tabele i novi HNSW indeksi prelaze u upotrebu u jednoj transakciji;
greška vraća i stare vektore i šemu. Za to vreme tabele su zaključane, pa bot mora
ostati ugašen. Tek posle uspeha pokreni bot sa novim podešavanjem. Normalan start
odbija model/dimenziju koji ne odgovaraju bazi. Stare popunjene baze bez profila
prepoznaju se po ranijim dimenzijama: 1536 = OpenAI small, 384 = multilingual-e5-small.
Ako si ranije menjao modele mimo ove aplikacije, prvo proveri poreklo vektora.
`reindex_all` menja seckanje; `reembed` čuva postojeće delove i menja samo vektorski prostor.

Za lokalne embeddinze instaliraj `.[local]`, postavi `EMBED_PROVIDER=local` i
`EMBED_LOCAL_MODEL=intfloat/multilingual-e5-small` (384 dimenzije) ili
`intfloat/multilingual-e5-base` (768), pa uz ugašen bot izvrši `scripts.reembed`.
Oba modela se izvršavaju na CPU-u kroz radnu nit; model u memoriji se kešira po imenu,
a serijalizovan inference sprečava nekontrolisano paralelno opterećenje.
E5 dobija obavezne `query:`/`passage:` prefikse i normalizovane vektore.
Kontekst modela je ograničen na 512 tokena: proveri `CHUNK_CHARS` na svom korpusu.
Kosinusni skorovi E5 i OpenAI modela nisu ista kalibracija; posebno ponovo izmeri
`RAG_MIN_SIMILARITY` na pozitivnim i negativnim pitanjima.

`python -m evals.embedding_bench --modeli openai small base` poredi isti sintetički
korpus iz `evals/embedding.example.json` u izdvojenoj `_bench`/`_test` bazi.
`--korpus` prihvata privatni JSON istog formata; privatni korpus drži van git-a.
Baza ne sme imati druge dokumente ili činjenice. Benchmark briše samo prethodni
benchmark indeks i na kraju ostavlja prostor poslednjeg izmerenog modela.
Izveštaj sadrži kvalitet, negativne upite, trajanje indeksiranja (i prvog učitavanja),
ms/upit, dimenziju i API tokene. `--usd-za-milion` prihvata važeću cenu OpenAI tokena;
bez nje iznos ostaje null. Lokalno `api_usd=0` ne uključuje server, struju i vreme CPU-a.
Bez OPENAI_API_KEY OpenAI se jasno označava kao neizmeren.
Modeli: https://huggingface.co/intfloat/multilingual-e5-small i
https://huggingface.co/intfloat/multilingual-e5-base.

Lokalni glas: `TRANSCRIBE_PROVIDER=local`, `WHISPER_LOCAL_MODEL=small` (ili `medium`)
uz `.[local]`. CPU inference koristi int8 i radnu nit; i lenjo čitanje Whisper
segmenata završava se u toj niti. Promena imena modela učitava odgovarajući model.
Svaki transkript prolazi kroz `pismo.u_latinicu`.

Za poređenje sa API-jem pripremi 20 svojih snimaka i ručne prepise prema
[`evals/voice/README.md`](evals/voice/README.md), instaliraj `.[local,dev]` i pokreni
`python -m evals.voice_eval`. Rezultat je zbirni WER i vreme, bez snimaka ili
transkripata u izveštaju. `--modeli small medium` izvršava samo lokalne modele.
Stvarno merenje još nije izvršeno: korisnik je potvrdio da snimci nisu pripremljeni.

Docker slika sa lokalnim modelima gradi se komandom:

```bash
docker compose build --build-arg EXTRAS=local bot
docker compose up -d bot
```

Na Coolify-ju zadaj isti build argument `EXTRAS=local`. Bez njega slika sadrži samo
API zavisnosti. Lokalna varijanta instalira CPU PyTorch prema
[uv dokumentaciji](https://docs.astral.sh/uv/guides/integration/pytorch/), pa ne
preuzima CUDA pakete. Težine modela preuzimaju se pri prvoj upotrebi, uz mrežni pristup;
build ne preuzima težine. `HF_HOME=/app/data/hf` je unutar postojećeg `dexter-data`
volume-a, koji čuva i E5 i faster-whisper keš pri zameni kontejnera. Na serveru
volume mora biti upisiv korisniku UID 10001. Ne uklanjaj ga između deploy-a.

Za promenu postojećeg indeksa prvo zaustavi bot, napravi backup i podesi novi
embedding model u `.env`, pa pokreni `docker compose run --rm bot python -m
scripts.reembed`. Tek posle uspeha pokreni bot. Skripte su uključene u obe slike.

Server sa 8 GB deli RAM između OS-a, PostgreSQL-a, PyTorch-a i Whisper-a. Počni sa
E5 small i Whisper small/int8. Težine u disk kešu nisu isto što i RAM učitanih modela;
oba modela mogu ostati učitana istovremeno. Inference je serijalizovan po vrsti modela,
ali embedding i glas mogu raditi paralelno. Base/medium i prelazak između modela
zahtevaju posebno merenje vršne potrošnje. Pre produkcije prati `docker stats` tokom
prvog učitavanja, reembed-a i obrade glasa; proveri da nema OOM restarta i da ostaje
prostor bazi. Granica od 8 GB nije potvrđena ovim lokalnim benchmark-om.

CI gradi obe Docker varijante, proverava importe lokalnih biblioteka, CPU PyTorch,
migracije, skripte i opstanak upisivog keša između dva kontejnera. U ovoj radnoj
okolini Docker nije dostupan, pa stvarni lokalni build i provera servera ostaju ručni.

Opciono učenje izbora modela (F4.5): migracija 008 povezuje nove poruke i `usage`
pozive jedinstvenim ID-jem razmene, bez spajanja po vremenu. Stari zapisi bez te veze
se ne koriste za učenje. `python -m scripts.router_dataset` izvozi samo tekstualne
poruke vlasnika sa povezanim `purpose=chat` zapisima u `data/router-candidates.jsonl`.
Umetnuti kontekst, rezultati alata i poruke sa slikama se izostavljaju. `nivo` ostaje
prazan za ručnu anotaciju, a `predlog_nivoa` prikazuje zabeleženi izbor; budžet i staro
pravilo mogu taj izbor učiniti pogrešnom oznakom težine. Ponovljen izvoz ne prepisuje fajl.

Posle ručne provere oznaka instaliraj `.[train]` i pokreni:

```bash
python -m scripts.train_router data/router-candidates.jsonl --output data/router-model
```

Na Linux CPU mašini koristi `uv pip install --torch-backend=cpu ".[train]"`.
Podrazumevani model je `distilbert/distilbert-base-multilingual-cased`, CPU,
3 epohe, seed 42 i najviše 128 tokena. Ne pravi se poziv plaćenom API-ju niti upload
modela. Skup mora imati bar pet različitih ručno označenih poruka po nivou. Duplikati
se uklanjaju pre stratifikovane podele 75/25; konfliktne i nepotpune oznake se odbijaju.
Pre konačne evaluacije ručno razdvoji slične teme/šablone koji bi mogli procuriti
iz treninga u test. Ovako mali skup služi proveri postupka, ne izboru produkcionog modela.

`metrics.json` sadrži tačnost, macro-F1, matricu grešaka, vremena i otisak podele;
`split.json` čuva privatnu podelu radi reprodukcije. Model, tokenizer i oba fajla
ostaju u ignorisanom `data/` folderu. Postojeći izlazni folder se ne prepisuje.
Poređenje sa pravilom iz F3.2 koristi isti izdvojeni test. `--uporedi-api` dodatno
izvršava i meri F3.2 API klasifikator na tom testu, uz važeći Anthropic ključ i bazu
za beleženje troška. Trening ne menja aktivni `ROUTER_MODE` niti postavke bota.

Skenirani PDF-ovi: stranice bez tekstualnog sloja prolaze kroz pypdfium2 → PNG →
Claude vision, zatim u isti indeks kao tekstualni dokumenti. Mešoviti PDF čuva
postojeći tekst i prepisuje samo ostale stranice. `OCR_MAX_PAGES=20` ograničava broj
stranica za OCR po dokumentu; prekoračenje odbija ceo uvoz pre modelskog poziva.
Podeli veći sken na manje PDF-ove. Neuspešan ili odsečen prepis ne ostavlja
delimičan dokument. Prazne stranice mogu dati prazan prepis.

Isti postupak važi za Telegram/folder uvoz, Drive PDF i PDF priloge mejla do 5 MB.
OCR koristi `MODEL_MAIN` i evidentira potrošnju kao `usage.purpose=ocr`, uz dnevni
budžet. Dokument se šalje Anthropic-u radi prepisa; `EMBED_PROVIDER=local` ne znači
lokalni OCR. Sadržaj stranice model dobija kao podatak bez ovlašćenja za akcije.
Kvalitet prepisa stvarnih skenova treba proveriti pre oslanjanja na brojeve i datume.

Računi: uz jednu sliku traži izdvajanje ili čuvanje računa. `receipt_extract`
čita aktuelnu sliku kroz forsiran strukturisan tool poziv, validira podatke Pydantic-om
i šalje pregled prodavca, PIB-a sa računa, datuma, ukupnog iznosa, PDV-a i stavki.
Agent ne prosleđuje te podatke kao argumente alata. Tek dugme **Potvrdi** upisuje
u tabelu `expenses` (migracija 009); otkazivanje, istek ili neuspešno izdvajanje
ne upisuju rashod. Pregled proveri prema slici, posebno iznose i datum.

PIB ovde znači prepis PIB-a prodavca sa postojećeg računa; ne koristi se kao podatak
izdavaoca nove fakture. Nedostajući PIB, PDV, valuta i nečitljive stavke ostaju prazni;
prodavac, datum i pozitivan ukupni iznos su obavezni. Iznosi se čuvaju kao Decimal /
PostgreSQL NUMERIC, bez float zaokruživanja. Potpuno ista slika se ne upisuje dva puta;
druga fotografija istog računa zahteva da sam proveriš duplikat. Slika se ne čuva u
`expenses`; ostaje SHA-256 i potvrđeni podaci. Slike u istoriji podležu postojećem
čuvanju razgovora i mogu se ukloniti komandom `/reset`, koja ne briše rashode.

`/rashodi` prikazuje tekući mesec po `TIMEZONE`, a `/rashodi 2026-10` izabrani mesec
prema datumu sa računa. Iznosi se sabiraju zasebno po valuti; nepoznata valuta je
odvojena i nedostajući PDV nije nula. `/troskovi` i dalje prikazuje samo API troškove.
Izdvajanje slike evidentira se kao `usage.purpose=receipt_extract`.

Word/Excel uvoz podržava `.docx` i `.xlsx` iz Telegrama, lokalnog foldera,
Drive fajlova i mejl priloga do 5 MB. Word preuzima pasuse i tabele redom, uključujući
ugnježdene tabele, zaglavlja i podnožja. Slike, tekstualna polja i revizije u Word-u
ne prolaze kroz OCR. Excel svaki list pretvara u tekst sa nazivom lista i brojem reda;
uključeni su i skriveni listovi. Datumi su ISO, a formule su sačuvane kao tekst,
bez računanja, makroa ili otvaranja spoljnih veza. Stari `.doc`/`.xls` nisu podržani.

Parseri rade u radnoj niti. Office ZIP je ograničen na 50 MB raspakovanih podataka;
Excel na 100 listova, 50000 redova/1000 kolona po listu i 500000 obrađenih ćelija.
Prekoračenje odbija ceo uvoz, pa veći fajl podeli pre slanja. Promena dokumenta
ponovo indeksira sadržaj; nepromenjen tekst ne pravi nove delove.

Glasovni odgovor: postavi `GLAS_ODGOVOR=on` i `OPENAI_API_KEY`, pa odgovor na glasovnu
ili audio poruku dobijaš i kao Telegram voice. Tekst ostaje uvek poslat. Za pojedinačni
zahtev dovoljno je „odgovori glasom” u tekstu, transkriptu ili opisu slike; „samo tekst”
ili „ne odgovaraj glasom” isključuju dodatak za tu poruku. Običan tekstualni zahtev
bez te fraze ostaje tekstualan, čak i kada je `GLAS_ODGOVOR=on`.

OpenAI `POST /v1/audio/speech` koristi `TTS_MODEL=gpt-4o-mini-tts`, `TTS_VOICE=coral`
i Opus izlaz u OGG poruci, označenoj „AI generisan glas”. Tekst se pre slanja
preslovljava u latinicu i deli na delove do 1500 UTF-8 bajtova, bez sečenja reči kad
postoji pogodno mesto. To ostavlja prostor ispod ulaznog ograničenja podrazumevanog
modela i izbegava skraćivanje dugog odgovora. Glas može stići u više poruka.
Zahtev koristi zvanični [OpenAI TTS vodič](https://developers.openai.com/api/docs/guides/text-to-speech)
i [ograničenje modela](https://developers.openai.com/api/docs/models/gpt-4o-mini-tts).

Kvar TTS-a ili slanja voice poruke ostavlja već poslati tekst, istoriju i potvrdna
dugmad. Dobijaš kratku napomenu o neuspelom dodatku. Tekst odgovora se pri TTS-u šalje
OpenAI-ju; dodatak ima poseban API trošak. Taj trošak nije obračunat u Anthropic
`usage` izveštaju niti ograničen `DAILY_BUDGET_USD` mehanizmom. Podrazumevano je
isključen. Lokalni TTS nije uveden.

Obaveze iz razgovora (F6.1): isti pozadinski poziv koji izvlači memoriju izdvaja i
izričito preuzete obaveze sa rokom. Referentni datum je početak korisnikove razmene
u `TIMEZONE`. Obaveza mora imati doslovan citat iz korisnikove poruke; predlog
asistenta i izmišljeni citati se odbijaju. Rok bez dovoljno podataka se ne nagađa.
`commitments_list` prikazuje otvorene/završene obaveze, a `commitment_done` ih zatvara.
Migracija 010 čuva tekst, osobu, rok, status i izvorni citat. Ponovljen isti zapis
ne otvara duplikat niti vraća završenu obavezu u otvorene.

Podsetnik u 09:00 obuhvata otvorene obaveze za sutra. `QUIET_HOURS=22-07` sprečava
slanje u tihim satima; jednak početak i kraj znači celodnevnu tišinu. Pokušaj slanja
rezerviše se u bazi pre Telegram poziva da retry/restart ne pošalje duplikat.
Ako veza pukne, ishod može biti neizvestan: automatsko ponovno slanje je izostavljeno,
a `reminder_error` i `reminder_sent_at` omogućavaju ručnu proveru. `/reset` ne briše obaveze.

Dnevni uvid (F6.2) radi u 08:30 po `TIMEZONE`. Čita kalendar danas/sutra, TASK BOARD,
otvorene obaveze, do 30 poslednjih nepročitanih mejlova i relevantne činjenice.
Mejl čitanje je read-only/PEEK. TASK BOARD koristi stare kolone `Name` i `Status`
(`Not started` / `In progress` / `Done`); opciona Date kolona `Rok` omogućava oznaku
kašnjenja. Bez nje rok ostaje nepoznat, a model ga ne izmišlja. Nedostupna ili
nepodešena integracija je tako označena u podacima, nikad predstavljena kao prazna.

Glavni model vraća strogo validiran JSON odluke, bez alata za izvršavanje akcija.
`proactive_log` prikazuje razloge slanja/ćutanja i greške. Migracija 011 čuva sve
pokušaje, dostupnost izvora, odluke i Telegram ID. Trajna dnevna rezervacija i DB
lock sprečavaju dva pokretanja da pošalju isti uvid; odluka „ne šalji” se tog dana
ne ponavlja. Tihi sati se proveravaju i pre izvora i posle modelskog poziva.
Nepoznat ishod slanja je `uncertain`; nema automatskog ponavljanja koje bi moglo
napraviti duplikat. Greške ovih poslova ostaju u evidenciji, bez dodatnog job alarma
koji bi mogao prekršiti tihe sate. Uvid ne šalje mejlove niti menja spoljne podatke.

F1b alati i ostali stari poslovi ostaju zaseban, nezavršen deo plana: ova čitanja
su uvedena radi izričito tražene Faze 6, bez označavanja F1b kao završene.

Nedeljni pregled (F6.3) je zaseban posao nedeljom u 20:00, sa istom zaštitom isporuke
kao dnevni uvid. Obuhvata tekuću nedelju od ponedeljka, završene obaveze prema
`done_at`, otvorene rokove i do 200 poslednjih korisnikovih izjava iz tog perioda.
Predlozi asistenta ne predstavljaju završene poslove. Notion `Done` bez datuma
završetka nije dokaz da je zadatak završen baš ove nedelje. Model vraća odvojene
liste urađenog/kašnjenja i jedno polje predloga, koje kod pretvara u jednu poruku.

Stara nedeljna pohvala navika u 22:00 nije zamenjena ovim pregledom. U Python verziji
njen prenos i dalje čeka F1b.8; novi posao ne označava taj deo pariteta kao završen.

Ocene proaktivnih poruka (F6.4): dnevni uvid, nedeljni pregled i podsetnik za obavezu
imaju 👍/👎 dugmad. Ocena se vezuje za isporučenu poruku i njen Telegram ID, prihvata
se samo od vlasnika i može se promeniti bez pravljenja duplikata. Migracija 012
čuva ocene. Poslednjih deset ocenjenih poruka sa ocenom ulaze u promenljiv kontekst
sledećeg dnevnog uvida, bez izmene SYSTEM_PROMPT-a i bez automatskog treniranja modela.
Dugmad za ocenjivanje imaju zasebnu callback rutu i ne potvrđuju niti otkazuju alate.

Persona eval (F6.5): `evals/persona/` sadrži 20 sintetičkih razgovora i rubriku 1–5
za konkretnost, odsustvo izmišljanja, kratkoću, latinicu i primereno neslaganje.
`python -m evals.persona_eval --simulacija --prethodni-ref HEAD` proverava ceo postupak
bez pravih API-ja. Za stvarno poređenje pre/posle koristi važeći Anthropic ključ i
Git ref pre izmene; kandidat je MODEL_MAIN, a sudija MODEL_DEEP. Izveštaj sadrži
odgovore, ocene, kontrolne alate, tokene i otiske svih ulaza. Alati i istorija su
izolovani od stvarnog razgovora. Detalji su u `evals/persona/README.md`.

CI pri promeni `SYSTEM_PROMPT` zahteva stvarni izveštaj za prethodni i novi prompt
na istom skupu/rubrici; simulacija ne prolazi taj uslov. Nepromenjen prompt ne pravi
API pozive u CI-ju. Brisanje memorije (`memory_forget`) sada takođe traži dugme
potvrde; persona scenario proverava da se brisanje ne izvrši pre potvrde.
