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
