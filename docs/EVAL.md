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
