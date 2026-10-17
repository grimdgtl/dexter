# Merenja kvaliteta i troška

Privatni skup `evals/questions.jsonl` pravi korisnik: približno 30 pitanja nad stvarnim
dokumentima i njihovim ID-jevima. Skup se ne commit-uje. Primer strukture je u
`evals/questions.example.jsonl`. Za uporedivost koristi isti skup, isti indeks i isti `k`.

```bash
python -m evals.rag_eval --k 5 --oznaka "pocetno-hybrid-1200"
python -m evals.rag_eval --uporedi
```

Pokretanje dopisuje UTC datum, oznaku, broj pitanja, `k`, recall@k, MRR i prosečno
vreme u `evals/results/log.jsonl`. `--uporedi` radi bez baze, API ključeva i privatnog skupa.
Stariji zapisi bez datuma prikazuju `—`.

## Rezultati

Još nema merenja nad korisnikovim dokumentima. Vrednosti se unose tek posle pokretanja.

| Datum | Oznaka | recall@5 | MRR | ms po upitu | Šta je promenjeno |
|---|---|---|---|---|---|
| — | početno merenje čeka privatni skup | — | — | — | Hybrid, delovi od 1200 znakova |

Za svaku izmenu iz Faze 2 dodaj red pre i posle promene. Ako koristiš drugi `k`, navedi ga
u oznaci i zaglavlju. Recall@k meri udeo pitanja čiji je dokument među prvih k jedinstvenih
dokumenata; MRR meri prosečnu recipročnu poziciju očekivanog dokumenta u pretraženim
rezultatima. Vreme obuhvata embedding upita i pretragu, bez povezivanja na bazu.

## F2.1 — mejl kao izvor (15.10.2026)

Kontrolisani integracioni test koristi tri jedinstvene sintetičke poruke, jednu kopiju
u INBOX-u i Sent-u, jednu poruku van perioda i jedan upit „Orion”. IMAP server je lažan;
MIME parser, PostgreSQL i pgvector su pravi. Embeddinzi su deterministički test vektori.
Ovo potvrđuje indeksiranje i tok pretrage; ne meri produkcioni kvalitet embedding modela.

| Stanje | Mejl dokumenata | recall@5 | MRR | ms po upitu |
|---|---|---|---|---|
| Pre, prazan mejl indeks | 0 | 0.0 | 0.0 | 7.72 |
| Posle F2.1 | 3 | 1.0 | 1.0 | 8.67 |

Merenje je sa lokalnog PostgreSQL 14 + pgvector 0.8.1 i jednog kontrolnog upita;
vreme je samo provera prolaska kroz bazu. Ponovljeno indeksiranje preskače sva tri
dokumenta i ne zove ponovo embedding funkciju. Test prekida Sent čitanje i proverava
da postojeći indeks ostaje sačuvan, kao i da čišćenje ne dira Notion dokumente.

Reprodukcija sa test bazom:

```bash
TEST_DATABASE_URL=postgresql://apu:apu@localhost:5432/apu_test \
pytest tests/test_integration.py::test_mail_source_evaluation_deduplication_and_safe_cleanup -s
```

Produkcioni pre/posle eval čeka korisnikov `evals/questions.jsonl` i sopstveni mejl nalog.
Stvarni mejlovi i privatna eval pitanja nisu preuzimani niti dodavani u git.

## F2.2 — razgovori kao izvor (17.10.2026)

Kontrolisani integracioni test koristi dva dana razgovora i dva upita („Orion” i „Atlas”).
Brzi model i embeddinzi zamenjeni su determinističkim test funkcijama, dok su PostgreSQL,
pgvector, indeksiranje, evidencija troška i hybrid pretraga pravi. Ovo meri prolazak
kroz novi izvor, ne kvalitet sažimanja pravog modela ili produkcionih embeddinga.

| Stanje | Dokumenata razgovora | recall@5 | MRR | ms po upitu |
|---|---|---|---|---|
| Pre, prazan indeks razgovora | 0 | 0.0 | 0.0 | 1.10 |
| Posle F2.2 | 2 | 1.0 | 1.0 | 2.94 |

Merenje je sa lokalnog PostgreSQL 14 + pgvector 0.8.1; prosečna vremena za dva upita
nisu produkcioni benchmark. Sažimanje i izgradnja indeksa nisu uključeni u vreme pretrage.
Ponovljeno indeksiranje oba dana ne poziva ni model ni embeddinge. Provereni su lokalna
ponoć, izostavljanje tekućeg dana i drugog korisnika, dopuna starog dana, očuvanje sažetaka
posle `/reset` i čuvanje starog indeksa/napretka posle greške modela, praznog ili odsečenog
odgovora i prekida embeddinga. Jedinični test proverava obradu kraja dugog razgovora i
objedinjavanje delimičnih sažetaka, kao i posao u 03:30 kroz evidenciju i retry omotač.

Reprodukcija sa test bazom:

```bash
TEST_DATABASE_URL=postgresql://apu:apu@localhost:5432/apu_test \
pytest tests/test_integration.py::test_conversation_source_evaluation_dates_retry_and_reset -s
```

Produkcioni pre/posle eval čeka privatni skup pitanja i ručnu proveru sažetaka pravog
brzog modela u Telegramu. Privatni razgovori nisu preuzimani niti dodavani u git.

## F2.3 — parametri seckanja (17.10.2026)

Šest sintetičkih dokumenata o projektima, po šest kontrolnih upita; preklapanje 200.
PostgreSQL 14 i pgvector 0.8.1 su pravi, embedding je deterministička vreća reči.
Kandidati se mere nad istim izvornim tekstom, uz ponovno seckanje iz baze.

| CHUNK_CHARS | recall@5 | MRR | Delova | ms po upitu |
|---|---|---|---|---|
| 600 | 1.0 | 1.0 | 66 | 2.15 |
| 1200 (prethodna podrazumevana vrednost) | 1.0 | 1.0 | 24 | 1.12 |
| 2000 (izabrano posle F2.3) | 1.0 | 1.0 | 18 | 1.09 |

Izabrano je 2000: na ovom skupu nema pada kvaliteta, uz 25% manje delova od 1200.
Razlika vremena 1200/2000 je premala za zaključak o brzini; kriterijum izbora je broj
delova pri jednakom kvalitetu. Ovo nije potvrda optimalne veličine na privatnom korpusu
i pravim embedding modelima: za to ponoviti isti eval nad korisnikovim pitanjima.
Sačuvani tekst, otisak parametara i transakcijska zamena omogućavaju ponavljanje merenja
i nastavak posle greške bez gubitka prethodnog indeksa.

Reprodukcija: `pytest tests/test_integration.py::test_chunk_sizes_evaluation_and_reindex_from_saved_text -s`
uz `TEST_DATABASE_URL`. `scripts/reindex_all.py` prijavljuje stare dokumente bez izvornog
teksta, umesto da ih prećutno preskoči.

## F2.4 — opciono preslaganje (17.10.2026)

Kontrolni test koristi 24 kratka sintetička dokumenta i top 20 hybrid kandidata.
Očekivani dokument bira se na osmom mestu početne pretrage. Lažni model sa poznatim
tačnim odgovorom pomera ga na prvo mesto; dodaje se kontrolisano čekanje od 15 ms.
Ovo proverava primenu redosleda, ograničenje kandidata i evidenciju troška, a ne sposobnost
pravog modela da prepozna relevantan odlomak. Embeddinzi su deterministički.

| Stanje | recall@5 | MRR | ms po upitu | USD po upitu za preslaganje |
|---|---|---|---|---|
| RERANK=off (pre) | 0.0 | 0.125 | 5.54 | 0 |
| RERANK=on (kontrolni model) | 1.0 | 1.0 | 18.35 | 0.000125 |

Cena je obračun iz postojećeg `usage.PRICES` za sintetičkih 1000 ulaznih i 50 izlaznih
tokena; nije račun pružaoca usluge niti provera aktuelnog cenovnika. Neispravan JSON,
dupli/nedostajući indeksi, boolean indeksi, odsečen odgovor, nedostupan model i timeout
zadržavaju hybrid redosled. Gašenje opcije ne zove model.

Odluka: **RERANK ostaje off**. Kontrolisani dobitak ne dokazuje isplativost pravog modela.
Opcija je dostupna za privatni pre/posle eval, gde treba porediti iste upite i indeks,
recall/MRR, stvarne `usage` tokene/cenu i ukupnu latenciju, pa uključiti samo uz koristan dobitak.

Reprodukcija: `pytest tests/test_integration.py::test_rerank_evaluation_top_twenty_cost_and_fallback -s`
uz `TEST_DATABASE_URL`.

## F2.5 — negativna pitanja i prag relevantnosti (17.10.2026)

Tri sintetička dokumenta, tri pozitivna i dva negativna pitanja, uz kontrolisane
jedinične vektore. Pozitivni primeri pokrivaju semantički pogodak bez zajedničkih reči
(kosinus 0.4), jači semantički pogodak (0.8) i tačan PIB sa slabim vektorom (0.01).
Negativni upiti imaju kosinuse do 0.2 odnosno 0. Nema pravih model/API poziva.

| Prag | recall@5 | MRR | Preciznost upita | precision@5 | Tačnost negativnih | ms/upit |
|---|---|---|---|---|---|---|
| 0 (pre, bez odbacivanja) | 1.0 | 1.0 | 0.60 | 0.20 | 0.0 | 1.81 |
| 0.15 | 1.0 | 1.0 | 0.75 | 0.50 | 0.5 | 0.80 |
| 0.30 (izabrano) | 1.0 | 1.0 | 1.00 | 1.00 | 1.0 | 0.76 |
| 0.45 | 0.667 | 0.667 | 1.00 | 1.00 | 1.0 | 0.76 |

Izabrano je `RAG_MIN_SIMILARITY=0.3`: odbacuje oba negativna primera, a čuva sva tri
pozitivna. Prag 0.45 gubi slabiji semantički pogodak. Tačan full-text pogodak za PIB
ostaje čak i pri pragu 1. Prag se primenjuje pre preslaganja; RRF rang nije prag relevantnosti.
Ovo je provera granica na kontrolisanoj geometriji, ne kalibracija produkcionog modela.
Za svaki embedding model/provajder treba ponoviti kalibraciju na privatnim pitanjima.

Recall/MRR koriste samo pozitivna pitanja. Preciznost upita je broj pozitivnih upita
sa očekivanim dokumentom u top k, podeljen brojem svih upita sa nepraznim top k (uključujući
negativne). `precision_at_k` deli broj relevantnih jedinstvenih top k dokumenata ukupnim
brojem vraćenih jedinstvenih dokumenata. Bez odgovora preciznosti su 0. Tačnost negativnih
je udeo negativnih pitanja bez pogodaka, odnosno null kad negativnih pitanja nema.
Stari logovi ostaju čitljivi; poređenje prikazuje i preciznost i tačnost negativnih.

Reprodukcija: `pytest tests/test_integration.py::test_relevance_threshold_calibration -s`
uz `TEST_DATABASE_URL`. Privatna kalibracija: za svaku vrednost postavi
`RAG_MIN_SIMILARITY`, pokreni `python -m evals.rag_eval --oznaka prag-03` i uporedi logove.

## F2.6 — filtriranje po vremenu (17.10.2026)

Kontrolni test koristi 38 sintetičkih dokumenata i upit „Orion” za septembar:
35 boljih doslovnih pogodaka iz avgusta, jedan očekivani septembarski dokument,
jedan oktobarski i jedan bez poznatog datuma. PostgreSQL/pgvector su pravi;
embeddinzi su deterministički. Bez filtera očekivani dokument nije u top 5.

| Stanje | recall@5 | MRR | ms po upitu |
|---|---|---|---|
| Pre, bez perioda | 0.0 | 0.0 | 5.53 |
| Posle, od 2026-09-01 do 2026-09-30 | 1.0 | 1.0 | 1.01 |

Filter se primenjuje u SQL-u pre limita od 30 kandidata po grani: avgustovski pogoci
ne mogu da istisnu septembarski dokument. To potvrđuje tok filtriranja, ne opšti dobitak
u kvalitetu ili brzini na privatnim podacima. Vremena su za jedan kontrolni upit.

Migracija `005_document_dates.sql` dodaje vreme izvora i indeks. Provereni su uključive
granice dana, otvoreni periodi, kombinovanje sa izvorom, nepoznati datumi, dan od 25 sati
pri promeni vremena i filtriranje pre opcionog preslaganja. Testovi izvora proveravaju
Notion `last_edited_time`, Drive `modifiedTime`, datum zaglavlja mejla, lokalni datum
razgovora i `mtime` fajla. Nova izmena samo metapodataka ne traži embeddinge, a ponovno
seckanje ne menja vreme izvora. Stari sažetak dobija datum iz ID-ja čak i bez sirove istorije.
Stari dokumenti bez pouzdanog datuma ostaju null i izostavljaju se samo kada se zada period.

Reprodukcija: `pytest tests/test_integration.py::test_date_filter_evaluation_applies_before_candidate_limits -s`
uz `TEST_DATABASE_URL`. Eval pitanja sada mogu da sadrže `izvor`, `od` i `do` za merenje
istog perioda na privatnim podacima. Stvarne API metapodatke i Telegram upit proveriti ručno.

## Šablon zapisa promene

- Datum i verzija/commit:
- Skup pitanja i broj pitanja:
- Indeks/izvori i embedding model:
- Parametri i razlog promene:
- Pre: recall@5, MRR, ms po upitu:
- Posle: recall@5, MRR, ms po upitu:
- Primeri promašaja i odluka da li promena ostaje:

## Kasnija merenja

- Faza 3: cena po poruci, udeo prompt keša i latencija pre/posle optimizacije.
- Faza 4: API i lokalni embeddinzi, Whisper WER i vreme obrade.
- Faza 6: ocena persone pre i posle izmene system prompt-a.
