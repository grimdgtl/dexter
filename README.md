# Dexter — lični AI asistent

[![CI](https://github.com/grimdgtl/dexter/actions/workflows/ci.yml/badge.svg)](https://github.com/grimdgtl/dexter/actions/workflows/ci.yml)

**Razgovor, dokumenti i svakodnevni posao povezani kroz Telegram.**

Dexter je lični projekat koji razvijam za organizaciju rada male digitalne agencije
i privatnih obaveza. Povezuje Notion, Google Drive, kalendar i mejl, pretražuje moje
dokumente i pretvara dogovore u zadatke koje mogu da pregledam i potvrdim iz razgovora.
Komunicira na srpskom, latinicom, kroz tekst, glas i priloge.

Iza Telegram interfejsa je asinhroni Python backend sa LLM agentom, hibridnom RAG
pretragom u PostgreSQL-u i pgvector-u, obradom skenova i proverom izdvojenih podataka.

[Mogućnosti](#šta-dexter-radi) · [Pregled ugovora](#od-ugovora-do-proverenog-zadatka) ·
[Arhitektura](#arhitektura) · [Rezultati](#testovi-i-eksperimenti) ·
[Proba bez ključeva](#proba-bez-api-ključeva) · [Pokretanje](#pokretanje) ·
[Operativni vodič](docs/OPERATIONS.md)

## Šta Dexter radi

| Oblast | Mogućnosti |
|---|---|
| Dokumenti i znanje | Uvoz PDF, DOCX, XLSX, TXT, Markdown i CSV fajlova; OCR skenova; pretraga Notion-a, Drive-a, mejlova i dnevnih sažetaka razgovora. |
| Poslovna organizacija | Klijenti, poslovni zadaci u Work prostoru, pregled kalendara, slobodni termini, potvrđeno zakazivanje i Google Docs izveštaji. |
| Mejl | Pretraga i čitanje bez označavanja poruke kao pročitane, čuvanje nacrta i slanje tek posle potvrde. |
| Fakture i rashodi | PDF faktura za pregled, numeracija i potvrđeno arhiviranje na Drive-u i u Notion-u; izdvajanje podataka sa računa uz potvrdu upisa rashoda. |
| Ugovori | Strane, datumi, iznosi i obaveze sa izvorom po stranici i pasusu; kod proverava citate, a korisnik bira zadatke. |
| Lična organizacija | Odvojena Life lista, checklista navika, dnevnik, statistika, rođendani i trajna memorija sa izmenom i brisanjem. |
| Praćenje i podsetnici | Provera sajtova, istorija odziva, novi mejlovi, jutarnji pregled, obaveze sa rokom i proaktivni uvidi sa povratnom informacijom. |
| Glas i internet | Whisper transkripcija, opcioni glasovni odgovor i Perplexity pretraga sa linkovima ka izvorima. |

Primeri zahteva:

> „Nađi belešku o redizajnu sajta, čak i ako se ne sećam tačnog naslova.”
>
> „Sačuvaj nacrt odgovora klijentu, bez slanja.”
>
> „Pronađi slobodan termin sutra za sastanak od 45 minuta.”
>
> „Napravi fakturu za klijenta iz baze i pošalji mi PDF na pregled.”

Integracije se uključuju konfiguracijom. `/status` prikazuje dostupne alate i
tačno koja podešavanja nedostaju za ostale.

## Od ugovora do proverenog zadatka

Ovaj tok pomaže da rok iz dokumenta ne ostane zaboravljen u PDF-u:

1. Pošaljem `/ugovor`, pa PDF ili fotografiju.
2. Tekstualni sloj se čita direktno; skenirane stranice prolaze kroz OCR.
   Prepis zadržava brojeve stranica i pasusa.
3. LLM predlaže strukturisane podatke kroz **Pydantic šemu**: strane, datume,
   obaveze, iznose i citate koji ih podržavaju.
4. **Python kod proverava dokaz.** Citat mora da postoji u navedenom pasusu,
   a vrednost da odgovara citatu; datumi imaju dodatnu kalendarsku proveru.
   Neuspešna provera daje oznaku „nepotvrđeno”.
5. Dobijam pregled sa izvornim pasusima i predlozima zadataka izvedenim iz
   dovoljno proverenih podataka.
6. Svaki zadatak potvrđujem zasebno. Tek tada nastaje zapis u **Work** bazi,
   sa kratkim naslovom i izvorom u opisu. Poznat rok omogućava i lokalni
   Telegram podsetnik.

Primer iz izmišljenog test dokumenta:

```text
Obaveza: dostaviti izveštaj do 15.03.2030.
Naknada: 12.000,00 RSD
Izvor: strana 2, pasus 6
Citat: „Izvršilac se obavezuje da dostavi izveštaj do 15.03.2030.
        Naknada je 12.000,00 RSD.”
Status: citat proveren

Predlog: Dostaviti izveštaj — rok 15.03.2030.
[Sačuvaj zadatak] [Odbaci]
```

OCR se čuva po stranici da se uspešan deo obrade ne plaća ponovo posle greške.
Otisak fajla omogućava ponovno otvaranje pregleda, a trajna evidencija upisa
sprečava duplikat istog predloga. Neizvestan mrežni ishod traži proveru umesto
automatskog ponavljanja upisa.

Provera potvrđuje oslonac u **OCR prepisu**. Ne garantuje tačnost samog OCR-a,
pravnog tumačenja ili pripisivanja obaveze određenoj strani. Primeri u repozitorijumu
su izmišljeni; detalji i postupak za probu su u [vodiču](docs/OPERATIONS.md#lični-pregled-ugovora-f71).

## Arhitektura

```mermaid
flowchart TD
    T[Telegram: tekst, glas, slika, dokument] --> I[Ulaz i obrada priloga]
    I --> A[Async agentska petlja]
    A <--> L[LLM: izbor modela i prompt caching]
    A <--> R[Registar alata i Pydantic validacija]
    R -->|Čitanje i ostali alati| S[Notion, Drive, Calendar, mejl, web]
    R -->|Osetljiva radnja| C[Pregled i potvrda]
    C --> S
    I --> D[Ekstrakcija teksta, OCR, seckanje]
    D --> E[OpenAI ili lokalni E5 embeddinzi]
    E --> P[(PostgreSQL i pgvector)]
    R <--> H[Hibridna pretraga: vektori i full-text]
    H <--> P
    A <--> P
    J[Scheduler: poslovi, pokušaji, evidencija] --> S
    J <--> P
```

Aplikacija je modularni Python servis uz zasebnu PostgreSQL bazu. Telegram long
polling je korisnički interfejs; administracija ide kroz komande, logove i Coolify.
Integracije sa spoljnim REST API-jima odvojene su od agentske petlje i alata.
Tokovi, trajno stanje i granice potvrda opisani su u [arhitekturi sistema](docs/ARCHITECTURE.md).

**Tehničke odluke:**

- **Hibridni RAG.** Seckanje prati pasuse i rečenice, uz preklapanje i naslov.
  PostgreSQL full-text nalazi tačne pojmove, a pgvector semantički slične odlomke.
  Rangovi se spajaju kroz Reciprocal Rank Fusion; dostupni su filter izvora i
  datuma, prag relevantnosti i opciono preslaganje rezultata.
- **Kontrolisano izvršavanje alata.** Dekorator i Pydantic model predstavljaju
  jedan izvor definicije alata. Validacija i potvrde rade u kodu; slanje mejla,
  čuvanje fakture i brisanje memorije čekaju korisnikovo dugme.
- **Trošak kao deo sistema.** Svaki Anthropic poziv beleži tokene, cenu i
  latenciju. Statičan sistemski prompt i stabilan redosled alata čuvaju prompt
  cache; `economy` izbor modela ne zahteva dodatni klasifikacioni API poziv.
  Dnevni budžet je meko ograničenje, uz upozorenje i prelazak na brži model.
- **Trajno stanje i oporavak.** SQL migracije, zaključavanje razgovora,
  transakcije i evidencija poslova čuvaju konzistentnost kroz restart.
  Tokovi slanja i ugovornih upisa razlikuju potvrđen neuspeh od neizvesnog ishoda.
  Nepotpun modelski odgovor ne postaje završen sažetak ili zakazana poruka.
- **Kontekst i podaci.** Kratka istorija, tekući sažetak, dugoročne činjenice
  i indeks dokumenata imaju odvojene uloge. Sadržaj izvora tretira se kao podatak,
  a sva komunikacija prolazi kroz preslovljavanje u latinicu.

| Sloj | Tehnologije |
|---|---|
| Backend | Python 3.12, asyncio, Pydantic, asyncpg, httpx, APScheduler |
| Modeli i pretraga | Anthropic Claude, OpenAI embeddings/Whisper/TTS, Perplexity Search |
| Baza | PostgreSQL, pgvector, HNSW i full-text indeksi, SQL migracije |
| Lokalni ML | Hugging Face Transformers, Sentence Transformers, PyTorch, faster-whisper |
| Dokumenti | pypdf, pypdfium2, Claude vision OCR, python-docx, openpyxl, fpdf2 |
| Isporuka i provera | Docker Compose, Hetzner/Coolify, GitHub Actions, pytest, respx, Ruff |

## Testovi i eksperimenti

Na dan **22.10.2026. prolazi 933 testa** sa PostgreSQL/pgvector bazom.
CI proverava formatiranje, statičku analizu, integracione testove i obe Docker
varijante — osnovnu i sa lokalnim ML bibliotekama. Spoljni API odgovori u testovima
su mock-ovani; stvarne provere integracija beleže se zasebno.

Evaluacija obuhvata recall@k, MRR, negativne upite, cenu i latenciju, kao i
eksperimente sa lokalnim modelima. Primeri dokumentovanih nalaza:

| Provera | Rezultat i granice zaključka |
|---|---|
| Lokalni E5 embeddinzi | Stvarni CPU inference: small 13,89 ms/upit, base 32,59 ms/upit; oba recall@5 i MRR 1,0 pri pragu 0,8 na šest dokumenata, šest pozitivnih i dva negativna sintetička upita. Mali skup služi proveri postupka; OpenAI poređenje na istom skupu nije izvršeno. |
| Fine-tuning klasifikatora | Probni trening višejezičnog DistilBERT-a kroz PyTorch/Transformers Trainer: 29 sintetičkih trening primera, jedna epoha. Na 11 izdvojenih test primera tačnost je 36,36%, a pravilo daje 54,55%; trenirani model zato nije uveden u aktivni izbor modela. |
| Provera ugovornih dokaza | Pet kontrolnih slučajeva prolazi offline regresiju: uredan ulaz, izmišljen citat, pogrešan datum, uslovni istek i odsutni podaci. Ovo meri verifikator, ne kvalitet stvarnog OCR-a ili LLM-a. |

Svaki eksperiment ima opis skupa, uslova i ograničenja u
[dnevniku evaluacije](docs/EVAL.md). Dostupni su alati za poređenje seckanja,
embedding modela, rutiranja i keširanja, izvoz skupa za ručnu anotaciju i trening
klasifikatora. Simulirani troškovi su odvojeni od stvarno izmerenih API troškova.

## Proba bez API ključeva

Za prvi pregled dovoljan je Python 3.12. Iz korena kloniranog repozitorijuma:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
python -m evals.contract_eval
python -m scripts.make_contract_examples
```

Ova proba ne zahteva `.env`, Telegram nalog ili bazu. `pytest` izvršava testove
bez baze i preskače DB slučajeve kada `TEST_DATABASE_URL` nije postavljen.
Ugovorni eval proverava pet kontrolnih slučajeva, a poslednja komanda pravi tri
izmišljena skena u `output/pdf/`. Stvarni OCR i razgovor sa botom koriste API-je
i pripadaju zasebnoj ručnoj proveri. [Vodič za testiranje](docs/TESTING.md) opisuje
integracione testove i granice evaluacije.

[Gotovi izmišljeni PDF primeri](examples/contracts/) dostupni su i bez instalacije.

## Pokretanje

Potreban je Docker Compose, zaseban Telegram bot i API ključevi za izabrane servise.
Za podrazumevani tok popuni `TELEGRAM_BOT_TOKEN`, `TELEGRAM_OWNER_CHAT_ID`,
`ANTHROPIC_API_KEY` i `OPENAI_API_KEY`:

```bash
cp .env.example .env
# Unesi ključeve u .env; SCHEDULER_ENABLED=off ostavi za prvi test.
docker compose up -d --build
docker compose logs -f bot
```

Proveri `/start` i `/status` u svom botu. Notion, Google i mejl uključuju se
nezavisno, dodavanjem odgovarajućih kredencijala i dozvola.
Lokalni Compose kredencijali baze su za razvoj; produkciona instalacija koristi
svoju lozinku i internu mrežu.

Detalji: [konfiguracija](docs/OPERATIONS.md#podešavanja-integracija),
[Coolify deploy](docs/OPERATIONS.md#deploy-na-hetzner--coolify) i
[lokalni modeli](docs/OPERATIONS.md#lokalni-embeddinzi-i-promena-vektorskog-prostora).

### Razvoj i provere

```bash
uv venv
uv pip install -e ".[dev]"
source .venv/bin/activate
ruff format --check src tests evals scripts
ruff check src tests evals scripts
pytest

# Integracioni testovi uz posebnu test bazu; createdb se radi jednom.
docker compose up -d db
docker compose exec db createdb -U dexter dexter_test
TEST_DATABASE_URL=postgresql://dexter:dexter@localhost:5432/dexter_test pytest

# Offline kontrolni pregled ugovornog verifikatora, bez plaćenih API poziva.
python -m evals.contract_eval
```

Za demonstraciju ugovornog toka `python -m scripts.make_contract_examples`
pravi tri izmišljena skenirana PDF-a. Primeri ne sadrže stvarne poslovne podatke.

## Gde pogledati kod

| Deo | Ulazna tačka |
|---|---|
| Agent, kontekst i izbor modela | [agent/loop.py](src/dexter/agent/loop.py), [agent/router.py](src/dexter/agent/router.py) |
| Alati i potvrde | [tools/registry.py](src/dexter/tools/registry.py), [actions.py](src/dexter/actions.py) |
| Indeksiranje i hybrid search | [rag/store.py](src/dexter/rag/store.py), [sources/](src/dexter/sources/) |
| Ugovori i provera citata | [contracts/service.py](src/dexter/contracts/service.py), [contracts/evidence.py](src/dexter/contracts/evidence.py) |
| Troškovi i trajna dostava poruka | [llm.py](src/dexter/llm.py), [scheduled_delivery.py](src/dexter/scheduled_delivery.py) |
| Trening i evaluacija | [scripts/train_router.py](scripts/train_router.py), [evals/](evals/), [tests/](tests/) |

## Status i naredne provere

Dexter radi na ličnom serveru kroz Coolify. Glavni tokovi sa Notion-om, Drive-om,
kalendarom, mejlom i probnim ugovorom prošli su ručne provere. Projekat je u aktivnoj
upotrebi i razvoju; posmatranje zakazanih poslova i operativne provere još traju.

Sledeći koraci su veći označeni skup nad sopstvenim dokumentima, merenje stvarnog
troška posle optimizacija i Whisper WER na ručno transkribovanim snimcima.
Postupci su pripremljeni; ta merenja još nisu završena.

Pristup botu je ograničen na vlasnikov chat ID. Dokumenti, prepis i izdvojeni
podaci mogu se slati podešenim API provajderima: lokalni embeddinzi sami po sebi
ne znače da je ceo tok lokalni. Privatni dokumenti, ključevi i trenirani artefakti
ostaju van repozitorijuma.

- [Operativni vodič: integracije, komande, deploy i lokalni modeli](docs/OPERATIONS.md)
- [Arhitektura: obrada poruke, RAG, potvrde i trajno stanje](docs/ARCHITECTURE.md)
- [Testiranje i reprodukcija eksperimenata](docs/TESTING.md)
- [Evaluacija: metodologija, rezultati i ograničenja](docs/EVAL.md)
- [Pokrivenost funkcija i status ručnih provera](docs/PARITY.md)
