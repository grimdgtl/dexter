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
| `EMBED_LOCAL_MODEL` | `intfloat/multilingual-e5-small` | E5 small (384) ili `intfloat/multilingual-e5-base` (768); promena traži reembed |
| `PROMPT_CACHE` | `on` | `off` uklanja sve cache breakpointe iz zahteva za poređenje troška |
| `ROUTER_MODE` | `rule` | `classifier` uključuje brzi klasifikator; kvar vraća izbor pravilom |
| `STREAMING` | `on` | Postepen prikaz u Telegramu; `off` šalje samo gotov odgovor |
| `DAILY_BUDGET_USD` | nije postavljeno | Pozitivan dnevni budžet za modele iz `usage`; 80% upozorenje, 100% brzi model |
| `CHUNK_CHARS` | `2000` | Veličina tela dela pre dodavanja naslova; najmanje 100 znakova |
| `CHUNK_OVERLAP` | `200` | Preklapanje, od 0 do manje od `CHUNK_CHARS` |
| `RERANK` | `off` | `on` uključuje brzi model za preslaganje do 20 hybrid kandidata |
| `RAG_MIN_SIMILARITY` | `0.3` | Najmanji kosinus za odlomak bez full-text pogotka; opseg 0–1 |
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
