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
TEST_DATABASE_URL=postgresql://dexter:dexter@localhost:5432/dexter_test \
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
TEST_DATABASE_URL=postgresql://dexter:dexter@localhost:5432/dexter_test \
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

## F3.1 — benchmark troška (17.10.2026)

`evals/prompts.jsonl` sadrži 50 javnih sintetičkih poruka, od kojih deset u simulaciji
traži alat. `cost_bench.py` prolazi kroz pravu agentsku petlju, istoriju i `usage`;
alati i automatsko izvlačenje memorije su zamenjeni, pa nema spoljnih akcija.

| Režim simulacije | Poziva | USD ukupno | Keš ulaza | ms/poruka | p95 ms |
|---|---|---|---|---|---|
| PROMPT_CACHE=off | 60 | 0.379110 | 0.00% | 2.89 | 3.27 |
| PROMPT_CACHE=on | 60 | 0.180648 | 60.10% | 2.66 | 3.17 |

Ovo je kontrolni obračun: tokeni su procenjeni iz dužine teksta, keš simulira samo
statički prefiks, a cena koristi postojeći `usage.PRICES`. Brojke ne dokazuju uštedu,
latenciju ili ponašanje keša pravog pružaoca. SHA-256 skupa:
`f7fd9f7e30f9b1f9ded6ece3cf82956a62d6accedcdfb9bd098d5526ae748aa3`.

Reprodukcija: `python -m evals.cost_bench --simulacija --uporedi` u zasebnoj bazi
čije ime završava sa `_test` ili `_bench`. Bez `--simulacija` poziva pravi model,
meri prijavljene tokene i celokupno trajanje razmene; alati i tada ostaju lažni.
Za produkciono poređenje proveriti cenovnik, koristiti iste modele/alate/skup i
izdvojene pokušaje radi toplog/hladnog keša. Test: `test_cost_benchmark_cache_comparison_and_isolation`.

## F3.2 — izbor modela (17.10.2026)

`evals/router.jsonl`: 40 ručno definisanih sintetičkih slučajeva sa autorskim oznakama
(14 lako, 14 srednje, 12 teško). To nisu korisnikove poruke ni potvrđene ljudske oznake.

| Pristup | Tačnost oznake | Trošak izbora USD | ms/poruka |
|---|---|---|---|
| Postojeće pravilo | 0.525 | 0 | 0.00 |
| Kontrolni klasifikator koji vraća poznatu oznaku | 1.000 | 0.000646 ukupno | 0.35 |

Pravilo bira srednji model za 14 lakih i pet teških poruka. Kontrolni model samo
proverava mapiranje sva tri nivoa, evidenciju 38 poziva i očuvanje dva eksplicitna
prefiksa za jaki model. Njegova tačnost ne meri sposobnost pravog modela; tokeni
(120 ulaznih i 10 izlaznih po pozivu) i cena po `usage.PRICES` su sintetički.
Odluka: **ROUTER_MODE ostaje rule** dok stvarni klasifikator ne pokaže bolji odnos
kvaliteta odgovora, ukupnog troška (klasifikacija + odgovor) i latencije.
`python -m evals.router_eval` meri pravi klasifikator, a `--simulacija` kontrolni.
Korisnik treba da potvrdi oznake i dopuni slučajeve svojim porukama. Neispravan JSON,
nepoznat nivo, API greška ili timeout vraćaju pravilo; eksplicitni `/duboko` ga zaobilazi.

## F3.3 — postepen prikaz odgovora (17.10.2026)

Pre: Telegram dobija tekst tek po završetku agentske petlje. Posle: SDK text stream
šalje prvi raspoloživ tekst odmah, a renderer menja postojeću poruku najviše jednom
u sekundi. Kontrolni sat u testu šalje prvi tekst pri t=0, odbacuje suvišne izmene
pre t=1 i dozvoljava izmene pri t=1 i t=2. Odgovor preko 9000 znakova se čuva u celosti
u porukama do 4000 znakova, uz preslovljavanje pre prikaza.

Ovo je provera granice učestalosti, ne merenje latencije pravog Telegrama ili modela.
Test sa pravim Anthropic SDK-om i HTTP/SSE odgovorom kroz respx proverava prijem teksta,
konačnu poruku i tokene. Integracioni test čuva oba tool_result/istoriju kao ranije.
Prekinut stream evidentira dostupne tokene jednom; kvar Telegram prikaza ostavlja
mogućnost slanja gotovog odgovora. Potvrde i zaključavanje po razgovoru ostaju aktivni.
Ručno proveriti osećaj brzine, mrežne prekide i dug odgovor u pravom Telegramu.

## F3.4 — dnevni budžet (17.10.2026)

Kontrolni integracioni scenario: limit $1, početni trošak $0.79 bez upozorenja,
zapisi do tačno $0.80 daju jedno upozorenje i pri pet paralelnih provera. Tačno $1.00
uključuje brzi model i drugo obaveštenje. Ponovna inicijalizacija čita stanje iz baze
bez ponavljanja poruke. Pri lokalnoj ponoći zbir je 0 i jaki model je ponovo dostupan.
Trošak pre početka lokalnog dana se ne sabira. Proveren je i ponovni pokušaj slanja
posle Telegram greške, bez lažnog beleženja da je upozorenje poslato.

Pre: izbor modela ne zavisi od dnevnog zbira. Posle: zajednički create/stream sloj
primenjuje budžet za sve modelske pozive; upis novih tokena odmah proverava upozorenje.
Testovi koriste lažni model/Telegram i pravu bazu, bez stvarnog troška. Ovo nije tvrda
novčana granica niti potvrda aktuelnog cenovnika: odluka važi za sledeći poziv, a brzi
model i dalje košta. Za dnevni realni profil treba uključiti limit u pravom botu i
proveriti `usage` i upozorenja. Datumi i pragovi ne ulaze u SYSTEM_PROMPT.

## F3.5 — tekući sažetak istorije (17.10.2026)

Pre: prve razmene van HISTORY_TURNS nedostaju u kontekstu. Kontrolni scenario sa četiri
razmene i prozorom od dve čuva rok projekta Orion i status nacrta iz prve dve razmene
u sažetku; poslednje dve ostaju celovite. Posle nove poruke sažima se samo sledeća
ispala razmena uz prethodni sažetak. Ponovljeno čitanje bez novih ispalih razmena ne
zove model. Celokupna sirova istorija ostaje u bazi; u SYSTEM_PROMPT nema promena.
Sažetak se ne kopira u sačuvani kontekst svake nove poruke.

Provereni su tool_use/tool_result parovi, ishodi potvrda bez ponovnog izvršenja,
dugi prefiks preko tri dela sa očuvanjem poslednje poruke, nepotpun modelski odgovor
bez pomeranja napretka i reset tokom sažimanja bez vraćanja obrisanog stanja.
Ovi testovi koriste kontrolni model; vernost sažetka pravog modela treba ručno oceniti.

Benchmark istih 50 poruka sada uključuje i 37 poziva za sažimanje, odnosno 97 ukupno.
Sažimanje uvodi dodatni trošak i latenciju radi očuvanja konteksta:

| Kontrolni režim sa kešom | Poziva | USD ukupno | Keš ulaza | ms/poruka |
|---|---|---|---|---|
| Pre F3.5 | 60 | 0.180648 | 60.10% | 2.66 |
| Posle F3.5 | 97 | 0.184580 | 56.28% | 3.56 |

Isti skup i test baza; cene i keš su simulirani. Vremena obuhvataju lokalnu bazu,
bez modelskog mrežnog čekanja. Simulirani izveštaj nije račun pravog modela.
Za realno poređenje pokrenuti `python -m evals.cost_bench --uporedi` na izdvojenoj bazi,
proveriti trošak `history_summary` i kvalitet odgovora koji zavise od ranijih odluka.

## F4.1 — promena vektorskog prostora (17.10.2026)

Integracioni test nad pravom bazom menja oba skupa vektora 1536 → 384 → 1536.
Tekstovi, ID-jevi, hash dokumenta i parametri seckanja ostaju očuvani. Embedding
funkcija je kontrolna, bez API poziva. Proveren je prekid generisanja, kao i greška
posle ALTER TABLE: transakcija vraća staru dimenziju, vektore i HNSW indeks.
Normalan start odbija neodgovarajući model/provajder/dimenziju.

Ovo potvrđuje bezbedan prelaz šeme, a ne kvalitet novog modela. `scripts/reembed.py`
čita sačuvane delove i činjenice u grupama od 64, bez ponovnog skidanja izvora.
Za stvaran prelaz potreban je ugašen bot i zatim eval istih pitanja (F4.2).

## F4.2 — stvarni lokalni E5 modeli (17.10.2026)

Pravi SentenceTransformer modeli, CPU arm64, OMP_NUM_THREADS=2, PostgreSQL 14 +
pgvector 0.8.1. Biblioteke: torch 2.14.1, sentence-transformers 6.1.0,
transformers 5.20.1. Šest sintetičkih dokumenata, šest pozitivnih i dva negativna upita;
SHA-256 korpusa `01c832948e960960ec4d5a6c49e07b6d69f96c163a324078659fc2a82c1f068c`.
Modeli su zaista preuzeti i izvršeni; ovo nisu kontrolni vektori iz testova.

| Model | Prag | recall@5 | MRR | Preciznost upita | precision@5 | Negativna tačnost | ms/upit | API USD |
|---|---|---|---|---|---|---|---|---|
| OpenAI text-embedding-3-small | — | — | — | — | — | — | — | — |
| E5 small, 384 | 0.3 | 1.0 | 1.0 | 0.75 | 0.15 | 0.0 | 14.93 | 0 |
| E5 base, 768 | 0.3 | 1.0 | 1.0 | 0.75 | 0.15 | 0.0 | 32.40 | 0 |
| E5 small, 384 | 0.8 | 1.0 | 1.0 | 1.00 | 0.60 | 1.0 | 13.89 | 0 |
| E5 base, 768 | 0.8 | 1.0 | 1.0 | 1.00 | 1.00 | 1.0 | 32.59 | 0 |

OpenAI nije izvršen: nema ključa za stvarno poređenje. API simulacija u testu proverava
redosled vektora, tokene i račun, ali ne popunjava ovaj red. Nule lokalnog API troška
ne obuhvataju CPU/server. Prvo indeksiranje sa preuzimanjem/učenjem biblioteka trajalo
je 133.636 s za small i 168.870 s za base; ponovljeno sa keširanim fajlovima 12.129 s
odnosno 5.427 s. To nisu međusobno uporediva merenja hladnog starta; ms/upit se meri
posle indeksiranja i učitavanja. Ovo nije Hetzner benchmark.

Prag 0.3 je pogrešan za negativne primere ovog E5 korpusa. Pri 0.8 oba modela čuvaju
svih šest očekivanih dokumenata i odbacuju oba negativna upita; base vraća manje
nepotrebnih dokumenata, a small je ovde oko dva puta brži. Lokalni podrazumevani izbor
ostaje small; globalni provajder i korisnikov prag se ne menjaju automatski.
Za lokalni prelaz testirati 0.8 kao kandidata, pa kalibrisati na privatnom skupu.
[Model card E5 base](https://huggingface.co/intfloat/multilingual-e5-base) objašnjava
specifičan opseg kosinusnih skorova, obavezne prefikse i granicu od 512 tokena.

Reprodukcija u izdvojenoj praznoj `_bench` bazi:
`RAG_MIN_SIMILARITY=0.8 python -m evals.embedding_bench --modeli small base`.
Privatni korpus i ključ su potrebni za završno OpenAI poređenje; javnih osam upita
nije dovoljno za izbor najboljeg modela u produkciji.

## F4.3 — evaluacija glasa (17.10.2026)

Stvarni WER i vreme za Whisper API, small i medium **nisu izmereni**. Korisnik je
potvrdio da 20 sopstvenih snimaka sa ručnim prepisima još nije pripremljeno.
`evals/voice_eval.py` zahteva tačno 20 jedinstvenih postojećih fajlova, koristi isti
skup i normalizaciju za sve modele i meri zbirni WER pomoću jiwer-a. Učitavanje
lokalnog modela meri se odvojeno; API red ostaje neizvršen ako nema ključa.
Izveštaj sadrži otisak korpusa i zbirne metrike, bez privatnih prepisa.

Pre: keš lokalnog Whisper-a nije razlikovao imena modela. Posle: small i medium
imaju odgovarajuće učitavanje, uz CPU/int8 i serijalizovanu obradu u radnoj niti.
Mock test sa 20 kontrolnih ulaza proverava HTTP, izbor oba modela, normalizaciju,
pravi jiwer obračun i izvršavanje lenjog generatora van event loop-a. Kontrolni WER
ne predstavlja kvalitet modela. Posle pripreme snimaka pokrenuti
`python -m evals.voice_eval` i ovde uneti stvarne rezultate sva tri modela.

## F4.4 — Docker za lokalne modele (17.10.2026)

Pre: slika uvek instalira osnovne zavisnosti. Posle: `EXTRAS=local` uključuje
sentence-transformers i faster-whisper, uz CPU PyTorch. Build proverava importe,
ali ne preuzima modele. Postojeći volume `/app/data`, sa `HF_HOME=/app/data/hf`,
čuva preuzete težine kroz zamenu kontejnera; skripte za migraciju dostupne su u slici.
CI ima build matricu za obe varijante i proveru upisivog trajnog keša kao UID 10001.

Docker CLI/daemon nisu dostupni u ovoj okolini: stvarni build i CI izvršenje nisu
potvrđeni. Ruff i svi testovi sa PostgreSQL-om prolaze. Na serveru od 8 GB treba
posebno izmeriti vršni RAM za E5 small + Whisper small, zatim eventualno base/medium.
Lokalna E5 vremena iz F4.2 ne predstavljaju Docker ili Hetzner merenje.

## F4.5 — fine-tuning izbora modela (17.10.2026)

Migracija 008 povezuje nove zapise `messages` i `usage` preko UUID-a razmene.
Kontekst je izolovan po async zadatku i resetuje se i pri grešci. Izvoz uzima samo
tekstualne poruke vlasnika sa povezanim chat pozivima, bez sistemskog konteksta,
slika i rezultata alata. Stari redovi bez veze se ne spajaju po vremenu. Izbor
modela je samo predlog oznake, pošto pravilo i dnevni budžet mogu promeniti odluku;
obavezne ručne oznake `nivo` ostaju prazne do pregleda.

Stvarni probni CPU trening javnog `distilbert/distilbert-base-multilingual-cased`
izvršen je pomoću transformers Trainer-a i PyTorch-a na javnih 40 sintetičkih
poruka iz `evals/router.jsonl`, bez lične istorije i bez plaćenih API poziva.
Posle uklanjanja duplikata podela je stratifikovana: trening 29, test 11,
seed 42, jedna epoha, dužina 128 tokena, batch 4, learning rate 2e-5,
weight decay 0.01, CPU arm64 sa dve niti. Biblioteke: torch 2.14.1,
transformers 5.20.1, datasets 5.1.0, accelerate 1.15.0.
SHA-256 podele: `50589526c1247bfda88df02a631c9b0603da1acda8612e981adcc4aec35db6d3`.

| Izbor na istih 11 test poruka | Tačnost | Macro-F1 | ms/poruka |
|---|---|---|---|
| Pravilo iz F3.2 | 0.5455 | 0.4718 | nije mereno |
| DistilBERT posle jedne epohe | 0.3636 | 0.3000 | 11.66 |
| API klasifikator F3.2 | nije izvršeno | — | — |

Preuzimanje/učitavanje trajalo je 83.927 s, sam trening 16.536 s.
Sačuvan model i tokenizer ponovo su učitani bez mreže i reprodukovali su svih
11 predikcija. Na ovom skupu trenirani model je lošiji; aktivni izbor ostaje pravilo.
Ovo potvrđuje funkcionalan trening postupak, ne kvalitet na ličnim porukama.
Test skup je premali za zaključak o generalizaciji i ne treba ga koristiti za
ponovljeno podešavanje hiperparametara. Podrazumevana komanda trenira tri epohe;
navedeno merenje je eksplicitni probni prolaz sa `--epohe 1`.

Model i privatna podela čuvaju se van git-a (`data/` po podrazumevanom podešavanju).
Za završnu proveru sakupiti nove povezane razmene, ručno označiti primere i razdvojiti
slične teme, pa izmeriti pravilo, lokalni model i pravi F3.2 klasifikator na istom
izdvojenom skupu (`--uporedi-api`, uz svesno pokretanje API troška).
Testovi koriste lažne modele/API-je, a proveravaju vezu sa bazom, izolaciju razmena,
privatnost izvoza, odbijanje neoznačenih/konfliktnih redova i curenje duplikata.

## F5.1 — OCR skeniranih PDF-ova (17.10.2026)

Pre: PDF bez tekstualnog sloja nije ulazio u indeks. Posle: stvarni pypdfium2
renderer pravi PNG u radnoj niti, Claude vision prepisuje stranicu i ceo uspešan
tekst ulazi u postojeći indeks. Mešoviti dokument zadržava tekstualne stranice;
limit se proverava pre prvog modelskog poziva. PDFium je zaštićen globalnim mutex-om
jer biblioteka nije thread-safe ni nad odvojenim dokumentima.

Kontrolne provere: PNG za stranicu 240×320 ima 480×640 piksela; native PDF ne zove
OCR; dve skenirane stranice uz limit 1 ne šalju nijedan poziv. Odsečen odgovor ne
upisuje dokument. Respx odgovor kroz pravi Anthropic SDK proverava sliku, latinicu
i beleženje `purpose=ocr`; integracioni test nalazi prepis u PostgreSQL pretrazi.
Proveren je i skenirani mejl prilog kroz read-only IMAP tok. Ovo nisu stvarni OCR
rezultati modela: tačnost, latenciju i trošak na ličnim skenovima proveriti ručno.

## F5.2 — računi i rashodi (17.10.2026)

Pre: slika je bila samo ulaz za razgovor. Posle: alat bez slobodnih fiskalnih
argumenata uzima jednu sliku iz tekuće razmene, forsira `receipt_data` tool poziv,
proverava strukturisan izlaz i čuva pripremljeni snimak podataka za dugme potvrde.
Nema INSERT-a pre potvrde; otkazivanje/istek ne upisuju podatke. Migracija 009 uvodi
`expenses`, tačne decimalne iznose i jedinstven otisak slike protiv duplog upisa.

Pravi SDK kroz izolovan respx transport proverava tool_choice, sliku, latinicu i
potrošnju. Negativni testovi odbijaju nevažeći datum/PIB, NaN, negativan iznos,
više od dve decimale i PDV veći od ukupnog iznosa. Kontekst slike je izolovan između
razgovora; tekstualni zahtev ne koristi prethodnu sliku. Test baze potvrđuje da
naknadno izdvajanje druge slike ne menja prvi nacrt, ponovni upis iste slike ostaje
jedan rashod, a oktobarski izveštaj odvojeno sabira RSD/EUR i isključuje novembar.
Provereni su dugi pregledi i neuspešna potvrda bez lažne poruke o uspehu.

Ovo su kontrolni računi i mock modelski odgovori. Ručno proveriti kvalitet čitanja
stvarnih računa i dugmad u Telegramu; automatski testovi ne mere tačnost vision modela.

## F5.3 — Word i Excel (17.10.2026)

Pre: Office fajlovi se odbijaju ili preskaču. Posle: python-docx čita telo, tabele,
ugnježdene ćelije, zaglavlja i podnožja u odgovarajućem redosledu. Openpyxl čita
sve listove, uključujući skrivene, kao redove tabele sa naslovom lista. Formule se
čuvaju kao tekst i ne izvršavaju; čitanje ne menja izvorne fajlove.

Testovi koriste stvarne DOCX/XLSX ZIP fajlove iz memorije. Provereni su ćirilica →
latinica, redosled teksta/tabela, drugi skriveni list, nula/False, datum i formula,
kao i neispravan Excel dimension A1:A1 koji ne sme sakriti kasniji red. Velika ZIP
arhiva se odbija pre parsiranja/upisa. Google SDK kroz respx čita oba Office tipa;
native Google Doc nazvan .docx i dalje koristi tekstualni export. Test baze indeksira
oba fajla kroz folder, nalazi tekst iz ugnježdene tabele i drugog Excel lista, pa
ponovni uvoz ne pravi nove delove. Nema modelskih API poziva za samo Office čitanje.

## F5.4 — dodatni glasovni odgovor (17.10.2026)

Pre: glas se samo transkribuje, a odgovor je tekst. Posle: `GLAS_ODGOVOR=on` na
glasovnom/audio ulazu ili izričit zahtev „odgovori glasom” dodaje voice posle teksta.
Tekst je uvek prvi, streaming ostaje dostupan, a „samo tekst” isključuje dodatak za
jednu poruku. Svaki voice nosi oznaku AI generisanog glasa.

Kontrolni HTTP test proverava endpoint, ključ, model, glas, Opus format i latinicu;
dugačak odgovor se bez gubitka reči raspoređuje u zahteve do 1500 UTF-8 bajtova.
Za stari tts-1 ne šalje se nepodržano instructions polje. Provereni su nedostajući
ključ, HTTP greška i neispravan audio. Telegram testovi za streaming on/off čuvaju
redosled tekst → voice, a TTS greška ne skriva tekst niti potvrdnu dugmad.
Integracioni test potvrđuje i očuvanje cele razmene u bazi posle HTTP 503 iz TTS-a.

Ovo su mock audio odgovori, ne snimci pravog modela. Izgovor srpskog, stvarnu
latenciju, cenu i reprodukciju OGG/Opus poruke u Telegramu proveriti ručno sa ključem.
TTS nije deo Anthropic obračuna `usage` niti njegovog dnevnog budžeta; nema tvrdnje o
nultom trošku. Ugovor zahteva oslanja se na zvanični
[TTS vodič](https://developers.openai.com/api/docs/guides/text-to-speech) i
[model card](https://developers.openai.com/api/docs/models/gpt-4o-mini-tts).

## F6.1 — obaveze iz razgovora (17.10.2026)

Pre: prolazna obećanja sa rokom nisu imala zasebno stanje. Posle: memorija istim
pozivom vraća trajne činjenice i strukturisane obaveze; prihvata se samo obaveza sa
citatom iz korisnikove poruke. Datum poruke se hvata pre modelskog odgovora radi
relativnih rokova. Test baze odbija citat asistenta, čuva latinicu, ne duplira zapis
pri ponovljenoj ekstrakciji i omogućava idempotentno zatvaranje kroz alat.
Dva paralelna podsetnika za isti lokalni dan daju jedan Telegram poziv. Tišina se
proverava na granicama 22:00 i 07:00. Mrežna greška ostaje u bazi, bez slepog retry-a.
Modelski odgovori i Telegram su kontrolni; stvarno prepoznavanje rokova i isporuku
podsetnika treba ručno proveriti. SYSTEM_PROMPT nije menjan.

## F6.2 — dnevni uvid (17.10.2026)

Pre: nema uslovnog dnevnog javljanja ni evidencije ćutanja. Posle: posao u 08:30
skuplja izvore i poziva glavni model za strogi JSON. Nepodešeni/neuspešni izvori su
razlikovani od praznih rezultata. Task bez opcionog datuma Rok nema izmišljeno kašnjenje.
Google i Notion SDK testovi kroz respx potvrđuju paginaciju; IMAP test proverava
UNSEEN + read-only/PEEK. Nema upisa u spoljna čitanja.

Test stvarne baze pokreće dva paralelna dnevna uvida i zatim novo pokretanje: jedan
model poziv, jedna rezervacija i jedan Telegram poziv. „Ne šalji”, tišina i neizvesna
mrežna isporuka ostaju zabeleženi. Prelaz 21:59 → 22:00 tokom modelskog poziva sprečava
slanje. Pravi Anthropic SDK sa respx odgovorom proverava JSON i usage, uz promenljive
podatke izvan statičnog prompta. Ručno proveriti relevantnost uvida i stvarne naloge.

## F6.3 — nedeljni pregled (17.10.2026)

Novi raspored koristi eksplicitno `day_of_week='sun'`, 20:00 u TIMEZONE; test proverava
sledeći termin za nedelju, uz očuvane jutarnje/dnevne poslove. Model dobija događaje
tekuće nedelje, potvrđene done_at zapise i korisnikove izjave; asistentski predlozi su
izostavljeni iz potvrda završetka. Strukturisan izlaz ima dva spiska i jedno polje
predloga. Test baze čuva jedan nedeljni pregled, latinicu i odvojenu oznaku weekly_review, bez ponovljene isporuke. Kvalitet sažetka pravog modela ostaje ručna provera.
Pohvala navika u 22:00 iz v1 nije preneta u ovom zadatku i ostaje F1b.8.

## F6.4 — povratna informacija (17.10.2026)

Pre: nema trajnih ocena korisnosti proaktivnog javljanja. Posle: sve tri nove vrste
proaktivnih poruka imaju zasebnu vote rutu. Vlasnik može zameniti ocenu iste poruke;
tuđ chat i pogrešan Telegram ID se odbijaju. Test čuva 11 primera, menja prvi,
a dnevni uvid dobija tačno poslednjih deset sa najnovijom ocenom. Primeri nisu deo
statičnog prompta. Callback test potvrđuje da ocena ne odlazi na potvrdu alata.
Uticaj stvarnih korisnikovih ocena na korisnost narednih uvida treba ručno oceniti.

## F6.5 — eval persone (17.10.2026)

Pripremljeno je 20 javnih sintetičkih scenarija, pet kriterijuma 1–5 i postupak
poređenja starog/novog sistemskog prompta. Fiksni datum, istorija i činjenice su isti
za obe verzije. Kandidat prolazi kroz agentsku petlju, a svi alati i upis istorije
su kontrolni. Jaki model je zaseban sudija; nevažeći JSON, ocene van 1–5 i budžetsko
preusmeravanje sudije odbijaju merenje. Pravi SDK kroz respx proverava ugovor sudije.

Izvršen je kontrolni CLI prolaz: 20 pre + 20 posle, po 46 simuliranih poziva,
oba prompt otiska su ista jer SYSTEM_PROMPT nije menjan. Svih 40 korisničkih izlaza
prolazi latinicu; scenariji slanja i brisanja čekaju potvrdu i ne pozivaju kontrolnu
funkciju izvršenja. Brisanje memorije je zato usklađeno sa pravilom confirm=True.
Provereno je i zaustavljanje niza podsetnika kada počnu tihi sati.

Otisak skupa: `e983baf821accb48dc5eef780c397aa72c6150abc4b35127ce04ae214229f657`.
Otisak rubrike: `c46a2259c75068593a354513f505ff4fc32b683603660d79360b8e1e36cdd936`.
Simulirani sudija vraća kontrolne ocene; one se NE koriste kao brojke kvaliteta
persone. Stvarni MODEL_MAIN/MODEL_DEEP eval nije izvršen i ostaje ručna provera.
CI uslov proverava stvarni, kompletni pre/posle izveštaj pri promeni SYSTEM_PROMPT-a;
kontrolni izveštaj ne može zadovoljiti taj uslov. Automatskih plaćenih poziva u CI-ju nema.

## F0.1 — preimenovanje u Dexter (18.10.2026)

Na zahtev korisnika novi Python paket, CLI, promptovi, logovi, Docker/Compose,
CI i dokumentacija koriste Dexter/dexter. Reference na stari Node.js APU i čitanje
istorijskih Git putanja ostaju radi poređenja i prenosa funkcija. Baze i volume-i
nisu automatski preimenovani; README opisuje povezivanje postojećih podataka.

SYSTEM_PROMPT ostaje statična konstanta. Njegova jedina promena je ime u prvoj
rečenici. Persona provera prihvata samo tu tačnu zamenu, uz doslovno isti ostatak;
regresioni test potvrđuje da bilo koja dodatna izmena i dalje zahteva stvarni eval.
Git čitanje podržava novu i staru putanju paketa. Kontrolni CLI prolaz izvršio je
20 pre + 20 posle scenarija, po 46 simuliranih poziva i latinicu u svih 40 izlaza.
Stvarno ocenjivanje modelom nije izvršeno; kontrolne ocene ne mere kvalitet.

Ruff prolazi, kao i svih 241 test sa izolovanom PostgreSQL 14 + pgvector 0.8.1 bazom.
Otkrivena je i uklonjena zavisnost testa ponoćnog budžeta od stvarnog datuma DB upisa;
poslovna logika budžeta nije menjana. Izgrađen je `dexter-2.0.0` wheel i instaliran
u izdvojeni direktorijum: provereni su uvoz paketa, CLI entrypoint i svih 12 SQL
migracija unutar instaliranog paketa. Docker build i pravi Telegram deploy ostaju
ručna provera.

## F0.2 — kontrola automatskih poslova pri test deploy-u (18.10.2026)

`SCHEDULER_ENABLED=off` zaustavlja kreiranje scheduler-a pre registracije poslova.
Test pokretanja potvrđuje da inicijalizacija baze i bota ostaje dostupna, a nijedan
scheduler nije napravljen. `/status` prikazuje isključene poslove; test sa `on`
potvrđuje očuvane automatske poslove. Podrazumevano `on` čuva prethodno ponašanje,
dok `.env.example` i uputstvo za prvi test deploy koriste `off`.
Ruff i svih 243 testa sa izolovanom bazom prolaze. SYSTEM_PROMPT nije menjan.
Server deploy i potvrda poruka u Telegramu ostaju ručna provera.

## F1b.1 — Google kalendar (18.10.2026)

Pre prenosa pročitani su v1 `src/services/calendar.js`, kalendarske definicije
alata, registracija i README odeljci za OAuth i ponavljanje. Preneta su sva tri
alata sa istim imenima/argumentima i zajedničkim Google OAuth podešavanjima.
`calendar_create_event` čeka potvrdu, uključujući slanje pozivnica učesnicima.
Jedno RRULE pravilo pravi jedan insert; otkazivanje ne poziva Google, a ponovljena
potvrda istog zahteva ne ponavlja insert. Pregled potvrde prikazuje lokalno vreme,
kalendar, pravilo ponavljanja i primaoce pozivnica.

Pravi Google SDK kroz respx proverava osvežavanje OAuth tokena, list paginaciju,
celodnevne događaje, filtriranje otkazanih, 403 za sva tri postupka i zatvaranje
SDK klijenta pri grešci. HTTP se izvršava van glavne niti. Freebusy testovi pokrivaju
preklapanje zauzetosti, ograničenje na traženi period, odbijanje prošlih termina,
prazan kalendar, vikend i promenu UTC offseta 24/25.10.2026. Nepoznata zauzetost
ili Google greška ne pretvaraju se u prazan, slobodan kalendar.

Zadržani su kraj UTC dana za `do`, alternativa `broj`, podrazumevani sati 9–18 i
vikendi iz v1. Razlike i popravljene granice perioda su u `docs/PARITY.md`.
[Google events list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list),
[freebusy](https://developers.google.com/workspace/calendar/api/v3/reference/freebusy/query)
i [ponavljanje](https://developers.google.com/workspace/calendar/api/concepts/events-calendars#recurring_events)
su reference za paginaciju, dostupnost i oblik RRULE zahteva.

Ruff i svih 263 testa sa izolovanom PostgreSQL bazom prolaze. SYSTEM_PROMPT nije
menjan; persona provera prolazi bez novog merenja. Korisnik bira `primary` umesto
test kalendara. Pravi Google nalog nije pozivan iz testova; ručno proveriti pregled,
slobodne termine, potvrdni upis i ponavljanje nakon deploy-a.

## F1b.2 — Lična To-do lista (18.10.2026)

Pročitani su v1 `src/services/todo.js`, nedeljni posao iz `scheduler.js`, računanje
sedmice iz `checklist.js`, definicije tri alata i README šema lične liste.
Preneti su pregled, dodavanje, promena statusa i posao ponedeljkom u 05:00.
Koristi se postojeći database ID uz data source otkrivanje prema
[Notion vodiču za API 2025-09-03](https://developers.notion.com/guides/get-started/upgrade-guide-2025-09-03).

SDK/respx provere pokrivaju paginaciju, otvorene/završene zadatke, sva opciona
polja i prazne vrednosti, latinicu, 403 za sva tri alata, odbijanje višeznačne
baze i promene statusa van lične liste. Provereni su neispravni datumi i enum
vrednosti, registracija sa `requires`, uslovno zakazivanje i `run_job` omotač.
Cron testovi proveravaju ponedeljak=1, nedelju=0/7, nazive, opsege i korake.

Integracioni testovi sa PostgreSQL-om potvrđuju jedan create pri paralelnom
pokretanju, trajni ključ i ponovni poziv dok je Notion rezultat još prazan,
nov zadatak sledeće sedmice, postojeći Notion red bez novog upisa, bezbedno
zaustavljanje posle timeout-a/503 i ponovni pokušaj posle definitivnog 403.
Kalendarska sedmica proverena je i preko nove godine i promene sata.

Ruff i svih 290 testova sa bazom prolaze. Novi testovi koriste mock HTTP;
pravi Notion nije pozivan. SYSTEM_PROMPT je nepromenjen. Ručna provera posle
deploy-a: pregled lične liste, dodavanje probnog zadatka sa rokom, promena na
Done; automatski nedeljni posao proveriti tek kada se uključi scheduler.

Ručna provera F1b.2: korisnik je 18.10.2026. potvrdio pregled lične liste,
dodavanje probnog zadatka i promenu na Done na pravom Notion-u. Scheduler
ostaje off, pa automatski nedeljni posao još nije proveren na pravom nalogu.

## F1b.3 — Mejl alati (18.10.2026)

Pre prenosa pročitani su v1 `src/services/mail.js`, svih šest definicija i
registracija alata, config i README mail/SMTP/Resend odeljak. Preneti su
nepročitane poruke, kombinovana pretraga, puna poruka do 20000 znakova,
folderi, MIME draft i slanje isključivo potvrdom. Razlike su u `docs/PARITY.md`.

Pravi `imap-tools` i MIME parser rade nad lažnim IMAP protokolom; testovi
proveravaju read-only izbor, BODY.PEEK, Seen i Unseen filtere, sve filtere
zajedno, UTF-8 upit, isključivi before datum, najnovije UID-eve, limit, naziv
foldera, tela preko 12000 znakova, HTML fallback, priložene fajlove, skraćivanje
na 20000, nepostojeći UID i nestandardno From zaglavlje/izostavljen datum.
Veza se zatvara i pri grešci prijave; ne izvršava se STORE/EXPUNGE.

Draft provere proveravaju APPEND sa Draft oznakom, special-use folder i dva
poznata naziva, UTF-8 MIME zaglavlja/telo, CC i grešku bez Drafts foldera.
Resend koristi respx prema [zvaničnom send API-ju](https://resend.com/docs/api-reference/emails/send-email).
Provereni su payload, više primalaca, reference odgovora, greška 403, timeout,
neispravan JSON i nedostajući ID bez SMTP fallback-a. Lažni SMTP proverava TLS,
STARTTLS pre prijave, izvršavanje van event loop-a, MIME/envelope primaoce,
delimično odbijanje, zatvaranje i grešku autentikacije bez ponavljanja.

Potvrdni testovi proveravaju da pre dugmeta nema slanja, dve paralelne potvrde
šalju jednom, otkazivanje i istek posle 30 minuta ne šalju, ceo pregled prolazi
kroz Telegram poruke sa dugmetom Pošalji tek na kraju. Model ne vidi From/sender
polje; pošiljalac se uzima iz konfiguracije. CRLF/kontrolni znakovi u zaglavljima,
neispravni primaoci i neispravni datumi odbijaju se pre upisa ili slanja. /status
prepoznaje alternativne Resend/SMTP uslove nezavisno od IMAP podešavanja.

Ruff i svih 325 testova sa izolovanom PostgreSQL bazom prolaze. SYSTEM_PROMPT
nije menjan. Pravi servisi nisu pozivani iz testova. Ručno posle deploy-a:
nepročitana pošta i jedna puna poruka bez promene Seen, draft u stvarnom folderu,
otkazivanje pripreme i zatim potvrđeno slanje na sopstvenu adresu.

Završna provera kompatibilnosti: minimum `imap-tools` podignut je na 1.16,
verziju korišćenu u ovih 325 testova. Stari minimum 1.7 nema `fetch(uid_list=...)`
koji omogućava neposredno PEEK čitanje konkretnog UID-a. Time instalacija ne može
zadržati staru biblioteku koja ne podržava novu funkciju.

## F3.5 — oporavak posle neuspelog sažimanja (18.10.2026)

Tokom ručne F1b.3 provere korisnik je uspešno dobio pregled pošte i sadržaj mejla
kao sažetak. Sledeći zahtev za doslovan tekst završio se generičkom greškom.
Produkcioni traceback pokazuje `summary.load_context`, validaciju nepotpunog ili
predugačkog sažetka, pre novog poziva mail_read; ne pokazuje problem IMAP-a ili
Telegram slanja. Tačan razlog validacije nije bio beležen u starom logu.

Pre: jedan neispravan sažetak prekida celu razmenu. Posle: 1800-token odgovor koji
je odsečen, prazan ili preko 6000 znakova dobija jedan pokušaj sa 3600 tokena.
Ako ni on ne prođe, model dobija prethodni potvrđeni sažetak i poslednje cele
razmene, uz izričito označeno ograničenje konteksta. Sirove poruke, sažetak i
through_id ostaju netaknuti; sledeći zahtev može ponovo pokušati. Greška API-ja
ili timeout od 30 sekundi prelaze na isti rezervni kontekst bez dodatnog retry-a.
Otkazivanje zahteva se i dalje propagira. Log beleži stop_reason, dužinu i budžet,
odnosno tip greške, bez sadržaja arhive ili odgovora provajdera.

Kontrolni scenario sa bazom: dva neispravna history_summary odgovora zatim jedan
uspešan chat odgovor umesto blokirane poruke. Provereni su uspeh drugog pokušaja,
očuvanje prethodnog napretka i sirove arhive, odbacivanje delimičnog sažetka pri
kasnijem neuspehu, pending napomene, oporavak sledećeg zahteva i reset usred oba
ishoda. Unit provere pokrivaju prazan/predugačak/odsečen odgovor, timeout, otkazivanje
i privatnost loga. Sve koristi lažne modele; nema pravih API poziva. Dodatni trošak
je najviše jedan modelski retry po neispravnom delu, evidentiran kao history_summary.
SYSTEM_PROMPT nije menjan. Stvarni zahtev za doslovan mejl ponoviti posle deploy-a.

Ruff i svih 335 testova sa izolovanom PostgreSQL bazom prolaze.

## F1b.3 — završena ručna provera (18.10.2026)

Korisnik je kroz stvarni Telegram bot i svoj nalog potvrdio pregled nepročitanih
poruka, pretragu poslednjih primljenih poruka i prikaz celog tela mejla nakon
ispravke F3.5. Zatim je potvrđeno čuvanje nacrta u Drafts bez slanja, otkazivanje
pripreme bez slanja i slanje drugim pokušajem tek posle dugmeta Pošalji.
Resend je vratio uspešan rezultat, a korisnik je potvrdio prijem u inbox.
Na kraju je postojeću poruku ručno označio kao nepročitanu, zatražio čitanje od
Dextera i potvrdio da je poruka u sandučetu ostala nepročitana.

Stvarni SMTP rezervni transport, CC i istek potvrde nisu posebno isprobani na
nalogu; njihove provere ostaju mock testovi. Automatski poslovi su i dalje off.
Ova dopuna beleži ručne rezultate; izvršni kod je isti kao u zelenom CI prolazu
sa 335 testova. Privatni sadržaj poruka, adrese i ID-jevi isporuke nisu preneti
u repozitorijum.

## F1b.4 — Checklista, dnevnik i statistika navika (18.10.2026)

Pre prenosa pročitani su stari `checklist.js`, `dnevnik.js`, `insights.js`,
njihovi opisi alata, konfiguracija i README šeme. Dodati su `checklist_get`,
`checklist_mark`, `checklist_create_day`, `dnevnik_get`, `dnevnik_write`,
`insights_get`, svi sa `requires`. Notion zahtevi koriste API 2025-09-03 i
data source otkriven iz postojećeg database ID-a.

Pre: 335 testova; posle: 371 test sa izolovanom PostgreSQL + pgvector bazom.
Ruff format/check prolaze za src/tests/evals/scripts. Svi Notion HTTP pozivi su
mock-ovani kroz respx uz pravi SDK; nijedan test ne pristupa stvarnom nalogu.
Nema merenja troška/latencije LLM-a: računica je deterministička, SYSTEM_PROMPT
nije menjan.

Provere obuhvataju tačne prilagođene CSV nazive, nedeljni cilj 4, lokalni datum,
strogi boolean i ISO ulaz, obe vrednosti „Bez…” stavke, očuvanje nenavedenih
polja i listu praznih polja dnevnika, nedeljni rezime, paginaciju i loš cursor,
prava pristupa i grešku za svaki alat. PostgreSQL testovi proveravaju paralelan
create, trajni ključ pri nevidljivom novom redu, sledeći dan, kreiranje pri
mark/write, odvojene baze, vezu dnevnika i checkliste, timeout/503 bez ponovnog
create-a, naknadno pronalaženje i oslobađanje ključa posle 403. Pomeranje,
arhiviranje i promena datuma potvrđenog reda ne prave novi red.

Statističke provere pokrivaju prosek/skor, nedostajuće dane i prekid niza,
tekući naspram starog niza, rezultate po danu nedelje, isključivanje duplikata
i neispravnih datuma, prazan period i opcioni dnevnik. Veza se pojavljuje tek
uz 3+3 uparena dana sa poznatom ocenom; nedostajuće/nepoznate ocene ne ulaze u
grupu i napomena ograničava tumačenje. Razlike prema v1 su u `docs/PARITY.md`.

Ručna provera posle deploy-a završena je 18.10.2026. Korisnik je potvrdio
`/status` sa šest novih aktivnih alata, svih 17 svojih naziva i cilj 4,
označavanje obične stavke uz ostale netaknute i ponovljen zahtev za kreiranje
postojećeg dana bez novog reda. Delimičan dnevnik sa samo ključnom reči ostavio
je ostala polja prazna; naknadna dopuna raspoloženja i energije sačuvala je
prethodni tekst. Statistika je vratila stvarni period od 30 dana, skorove,
nizove i napomenu da nema dovoljno uparenih dnevnika za veze sa ocenama.

Stvarno kreiranje dana koji nedostaje, prelaz „Bez…” stavke na true i zaseban
poziv `dnevnik_get` nisu izdvojeno ručno provereni; njihove provere ostaju
mock/DB testovi. Privatni ID-jevi i sadržaj ličnog dnevnika nisu preneti u repo.
Ova dopuna menja samo dokumentaciju; izvršni kod je iz zelenog CI prolaza sa
371 testom. Automatski jutarnji upis, povezivanje i podsetnici ostaju F1b.8,
uz `SCHEDULER_ENABLED=off` tokom provera.

## F1b.5 — Notion klijenti, poslovni zadaci i baza znanja (18.10.2026)

Pročitani su stari `services/notion.js` (klijenti, TASK BOARD i Knowledge Base),
definicije svih osam alata i README kolone. Preneti su `client_add`,
`client_update`, `client_list`, `client_find`, `notion_add_task`,
`notion_list_tasks`, `notion_update_task_status`, `notion_add_knowledge`.
Koriste stare ENV ID-jeve uz API 2025-09-03; uvedena su dva polja konfiguracije
koja nedostaju: `NOTION_CLIENTS_DB_ID`, `NOTION_KB_PAGE_ID`.

Pre: 371 test sa bazom. Posle: 432 testa sa izolovanom PostgreSQL + pgvector
bazom (9,45 s), odnosno 351 bez baze uz 81 preskočen integracioni test.
Ruff format/check prolaze za src/tests/evals/scripts. Novih 61 test koristi
respx i pravi Notion SDK, bez stvarnih API poziva. Nema promene SYSTEM_PROMPT-a,
migracije baze ni novih zakazanih poslova.

Pokriveni su prioritet tačnog naziva nad dužim kandidatom, pravni oblici,
dijakritici i ćirilica, najmanje dve značajne reči kod sadržavanja, zaseban
podniz za pretragu/izmenu, dvosmislen i nepostojeći klijent. Proveren je novi
klijent sa minimalnim podrazumevanim poljima, dopuna bez promene naslova,
popunjavanje samo praznog pravnog naziva, upis svih kolona, čuvanje početnih
nula i nenavedenih polja, cena nula, no-op i serijalizovani paralelni add pozivi.
Prepoznavanje prati sve stranice pre odluke; obrađuju se i neispravni cursori.

TASK BOARD testovi proveravaju tačan `Name`/`Status`, sva tri dozvoljena statusa,
čitanje svih statusa bez filtera, paginaciju do limita i zaštitu tuđe baze,
arhive i korpe pri promeni statusa. Za svaki od osam alata proverena je greška
pristupa i `requires`. Pydantic odbija nepoznata polja/opcije, loše ID-jeve,
limite i nekonačnu/negativnu cenu. Fiskalna polja se ne popunjavaju bez ulaza.

KB provere obuhvataju roditeljsku stranicu, prazan sadržaj, neprazne redove,
dug rich text, granicu posle preslovljavanja, 205 pasusa bez odsecanja i
neizvestan 503 pri dopuni: rezultat čuva link i broj potvrđenih pasusa bez
ponavljanja upisa ili tvrdnje o potpunom uspehu. Limit od 1000 pasusa odbija
preveliku belešku pre create-a. API granice prate
[Notion ograničenja zahteva](https://developers.notion.com/reference/request-limits).
Nema stvarnog merenja LLM troška/latencije za ovu funkcionalnu fazu.

Ručna provera posle deploy-a završena je 18.10.2026. `/status` je prikazao svih
osam aktivnih alata. Korisnik je potvrdio pregled prvih pet aktivnih klijenata
i pretragu skraćenog naziva, dodavanje probnog klijenta u Arhivu, zatim dopunu
alternativnim pravnim nazivom bez drugog reda. Naslov, Arhiva i tip Interni
ostali su sačuvani; promenjen je dostavljeni opis i popunjen prazan pravni naziv.
Zasebna izmena samo opisa takođe je sačuvala ostala polja.

U poslovnom TASK BOARD-u provereni su pregled zadataka, dodavanje probnog
zadatka sa statusom Not started i promena istog reda u Done. KB beleška je
sačuvana kao podstranica; korisnik je potvrdio da je na pravom mestu i da ima
oba pasusa. Reindeksiranje nije pokretano. Dvosmisleni klijenti, paginacija,
dugi tekstovi i delimičan HTTP neuspeh ostaju pokriveni mock testovima.

Ova dopuna menja samo dokumentaciju; izvršni kod je isti kao u zelenom CI
prolazu sa 432 testa. Tajne, privatni ID-jevi i fiskalni podaci nisu preneti
u repo. `SCHEDULER_ENABLED` ostaje off.

## F1b.6 — PDF fakture i potvrđeno arhiviranje (18.10.2026)

Pročitani su v1 `invoice.js`, `invoices.js`, numeracija/lista/arhiva u
`notion.js`, Drive upload, opisi oba alata, README i konfiguracija izdavaoca.
Preneti su `invoice_create` i `invoice_list` uz privatni PDF prilog registra,
Sačuvaj/Odbaci dugmad, fpdf2 i četiri statička Montserrat reza sa SIL OFL licencom.
SYSTEM_PROMPT i PostgreSQL šema nisu menjani; trajni trag koristi `kv_state`.

Pre: 432 testa sa bazom. Posle: 484 testa sa izolovanom PostgreSQL + pgvector
bazom (oko 12 s); bez baze 397 prolazi, 87 integracionih je preskočeno.
Ruff format/check prolaze za src/tests/evals/scripts. Svi spoljni HTTP zahtevi
su respx mock-ovi uz stvarni Notion i Google SDK/OAuth transport; Telegram je mock.

Provere pokrivaju godišnji prelaz, prag samo za svoju godinu, datum unazad,
ručni noviji red, paginaciju arhive i neizvestan raniji pokušaj; pri potvrdi
ponovo biraju broj i crtaju konačni PDF. Dve paralelne potvrde dobijaju različite
brojeve čak i kada Notion pretraga još ne vidi nove redove. Dupli klik i ponovljen
poziv iste operacije ne ponavljaju upload/upis. Nacrt, odbacivanje i istek
ne ostavljaju rezervaciju. Stvarni session lock i trajni kv_state upisi su DB testovi.

Za svaki obavezan podatak izdavaoca provereno je odbijanje sa imenom ENV polja
pre čitanja klijenta/crtanja; bez logo fajla traži se i brand. Logo fajl dozvoljava
izostavljen brand. Model ne može proslediti broj, fiskalni snapshot ili PDF;
klijent mora doći iz Notion-a. Prazni podaci klijenta ostaju prazni uz upozorenje.
Promena računa u konfiguraciji nakon pregleda ne menja već pregledani snapshot.
Decimal zbir jednak je zbiru prikazanih redova; opis postaje latinica pre validacije.

Telegram provere potvrđuju da PDF stiže pre dugmeta, neuspeh slanja ukida
potvrdu, konačni novi broj dobija novi PDF i neuspeh tog dodatnog slanja ne
ponavlja arhiviranje. Delimičan Notion neuspeh vraća poznati Drive link i
upozorenje; neizvestan upload se proverava po unapred dobijenom ID-ju, veličini
i checksum-u, bez drugog upload-a. Neuspešno potvrđen pokušaj zadržava svoj broj.
Nova priprema uklanja istekle PDF priloge iz memorije. Oba alata imaju API grešku
i requires provere; čitanje arhive radi i bez konfigurisanog izdavaoca/Google-a.

Vizuelna provera: originalni Node/pdfkit obrazac i novi fpdf2 nacrt generisani
su sa istim izmišljenim podacima i renderovani Poppler-om. Upoređene su slike
A4 strane: naslov/broj, brand, linija, dva bloka podataka, centriran broj,
datumi, tabela, zbir i podnožje poklapaju raspored v1. Dugi primer sa 15 stavki
pregledan je na svih 7 strana, sa celim opisima, ponovljenim zaglavljima i
završnim zbirom/podnožjem. Automatska provera drugog višestraničnog primera
potvrđuje sve stavke, zbir i tekst unutar granica papira. Nema privatnih podataka
ni stvarnih faktura u repo-u.

Wheel je izgrađen i proveren: sadrži sva četiri TTF fajla i OFL licencu.
Docker kopira fontove, a CI za obe slike proverava njihovu prisutnost u paketu.
Implementacija koristi [fpdf2](https://py-pdf.github.io/fpdf2/Tables.html) i
[Google Drive upload](https://developers.google.com/workspace/drive/api/guides/manage-uploads).
Nema novog LLM poziva u PDF crtanju/arhiviranju; cena i latencija modela nisu merene.

Prvobitno je čekalo ručnu proveru: ENV izdavaoca/brand ili logo, `/status`, stvarni invoice_list,
PDF u Telegramu sa tačnim podacima, Odbaci bez spoljnog upisa, pa zasebna izričita
potvrda Sačuvaj i poređenje istog broja/iznosa/PDF-a u Drive-u i FAKTURE arhivi.
Automatski poslovi ostaju off. Stvarno čuvanje se ne pokreće ovim koderskim testovima.

### F1b.6 — imena klijenata u pregledu arhive (18.10.2026)

Stvarni `/status` potvrđuje oba alata i pregled vraća fakture iz Notion-a.
Korisnikov odgovor pokazao je da, kao v1, alat nije razrešavao vezu Klijent.
Sada vraća `klijent` i `klijenti` (ID/naziv), čitajući samo povezane stranice.
Keš važi za jedan poziv; više faktura iste firme zahteva samo jedan GET imena.
Nema dodatnog LLM poziva, promene šeme, SYSTEM_PROMPT-a ni novih ENV promenljivih.

Pre: 484 testa sa bazom. Posle: 493 testa sa izolovanom PostgreSQL + pgvector
bazom (13,15 s), ruff prolazi. Devet novih mock provera obuhvata latinicu,
rad bez `NOTION_CLIENTS_DB_ID`, ponovno korišćenje imena, praznu vezu/naziv,
403/404 i timeout, više klijenata, paginaciju veze i neispravan cursor.
Podaci fakture ostaju dostupni uz napomenu ako klijent ne može da se utvrdi.
Paginacija prati [Notion čitanje svojstva stranice](https://developers.notion.com/reference/retrieve-a-page-property).
Ručna provera posle redeploy-a opisana je ispod. Zakazani poslovi ostaju isključeni.

### F1b.6 — završetak ručne provere (18.10.2026)

Korisnik je potvrdio da `/status` prikazuje oba alata i da pregled arhive
vraća klijente iz Notion veze. PDF nacrt je stigao u Telegram sa dugmadima
Sačuvaj/Odbaci; na uputstvo da proveri izdavaoca, klijenta, račun i iznos
odgovorio je „sve super”. Nakon Odbaci prosleđena provera nije našla fakturu
u Notion arhivi ni na Drive-u. Na završno uputstvo za Sačuvaj tok (Drive +
Notion) korisnik je odgovorio „Radi”; čuvanje se beleži na osnovu te potvrde,
bez prepisivanja privatnih podataka ili nedostavljenih linkova konačne fakture.

Glavni ručni tok F1b.6 je završen. Prelaz godine, konkurentne potvrde,
ponovno crtanje zauzetog broja i delimične spoljne greške provereni su kroz
mock/DB testove, bez izazivanja tih slučajeva na stvarnom nalogu. Ova dopuna
menja samo dokumentaciju; izvršni kod odgovara zelenom CI prolazu sa 493 testa.
`SCHEDULER_ENABLED` ostaje off.

## F1b.7 — rođendani, monitoring, izveštaji i izmena memorije (18.10.2026)

Preneto je sedam alata uz čitanje v1 services/birthdays.js, monitor.js,
monitorHistory.js, reports.js, memory.js, Notion čitača i odgovarajućih opisa
i README-a. Migracija 013 uvodi birthday_greetings i monitor_checks. Nova
podešavanja zadržavaju nazive NOTION_BIRTHDAYS_DB_ID, SITE_MONITOR_TIMEOUT_MS
i SITE_MONITOR_SLOW_MS iz v1. SYSTEM_PROMPT i rasporedi nisu menjani.

Pre: 493 testa sa bazom. Posle: 592 testa sa izolovanom PostgreSQL + pgvector
bazom, 13,10 s. Ruff format/check prolaze za src/tests/evals/scripts. Dodato
je 99 provera: Notion/Google/Anthropic i HTTP sajtova koriste SDK/respx mock,
trajnost, migracije, rotacija i izmene vektora koriste pravu izolovanu bazu.
Nisu pozivani privatni nalozi, pravi sajtovi niti plaćeni modeli.

Rođendani: svi v1 podaci/kolone i latinica, izostavljen datum, neispravan datum,
paginacija, arhiva, prestupne godine uključujući vekove, godišnji prelaz,
uključeni današnji dan, nepoznate godine i lokalni dan preko UTC ponoći.
Provereni su nedeljni nazivi dana, precizan/podeljen/prazan/nepoznat naziv i
tri API greške alata. DB test potvrđuje da četiri paralelne čestitke daju
jedan red, stanje preživljava reset i novu vezu, a sledeće godine ne važi
prethodna čestitka. Dvosmislen ili pogrešan naziv ne menja bazu.

Monitoring: samo aktivni domeni, sve Notion stranice, najviše pet paralelnih
provera, GET status bez čitanja tela i zatvaranje stream-a. Provereni su
originalni Host/SNI prema javnoj provernoj IP adresi, sledeća adresa posle
neuspelog ili isteklog IPv6 povezivanja, javno preusmeravanje, interna/mešovita DNS adresa,
privatne IPv4/IPv6/multicast adrese, nevažeća shema, URL sa kredencijalima,
redirect petlja, spori/404/500 odgovori, DNS/mrežne greške i ukupan rok koji
obuhvata DNS. Greška čuvanja istorije ostavlja rezultat uz napomenu.
DB provere pokrivaju procentualni zbir uspešnih uzoraka, spor odgovor kao
problem, poslednji pad, period/podniz imena, nepoznat procenat bez uzoraka,
rad bez novih HTTP zahteva i rotaciju pod paralelnim upisima. Zaštita javnog
odredišta koristi dokumentovani [Host/SNI mehanizam](https://www.encode.io/httpcore/extensions/#sni_hostname).

Izveštaj: podrazumevani lokalni opseg i sva tri statusa TASK BOARD-a, opcion
monitoring, isključeni izvori, režim bez čuvanja, 50 stavki po statusu uz
oznaku ograničenja, nedostupna/nepodešena grupa uz trajnu napomenu u tekstu.
Bez izvora, sa neispravnim datumima, prevelikim ulazom ili prekinutim/praznim
izlazom nema čuvanja. Cancel se propagira. Neizvestan Drive upis se ne ponavlja.
Poseban HTTP test koristi stvarni Notion, Google Calendar, Anthropic i Google
Drive SDK sa respx odgovorima: jedan model poziv, merenje purpose=report,
latinica i ispravan Google Doc upload. Poziv koristi brzi model; stvarna
LLM cena/latencija i kvalitet konačnog izveštaja nisu mereni na privatnim podacima.

Memorija: validacija ID-ja/praznog teksta/kategorije i internih argumenata,
odbijanje nepostojećeg ID-ja pre embedding poziva, greška embed servisa bez
upisa. DB proverava isti ID/izvor, nenavedena polja, tačan novi vektor teksta,
promenu samo kategorije bez embedding poziva i paralelne delimične promene
koje se ne prepisuju međusobno. Činjenica se ne briše niti pravi ponovo.

Prvobitno je čekalo ručnu proveru: redeploy, /status sa sedam novih alata; današnji/budući
rođendani iz pravog Notion-a, evidentiranje izričito potvrđene čestitke;
ručna provera aktivnih sajtova pa čitanje zabeleženog uptime-a; izveštaj sa
Google Doc linkom (otvoriti i proveriti podatke/napomene); izmena samo probne
činjenice uz isti ID. Scheduler ostaje off; rasporedi i automatske poruke su F1b.8.

### F1b.7 — rezultati ručnih provera (18.10.2026)

Posle redeploy-a korisnik je prosledio /status sa sedam novih aktivnih alata
i dostupnom bazom. Pregled je vratio da danas nema rođendana i jednog narednog
slavljenika sa datumom, odnosom i godinama, bez izmišljenih praznih podataka.
Zatim je na uputstvo za probni današnji red i označavanje čestitke odgovorio
„Radi”. Stvarni reset/restart i rubni datumi nisu zasebno izazivani.

Ručni monitoring je vratio 22 sajta sa HTTP 200, dva preko praga sporog odgovora.
Istorija za 30 dana zatim je vratila istih 22 uzorka, po jedan za svaki sajt,
20 uspešnih i 90,91% ukupnog uspeha uzorka. Spori sajtovi nisu predstavljeni
kao nedostupni; ograničenje jednog uzorka je izričito navedeno. Uptime čitanje
nije dodalo novu proveru. Automatski monitoring ostaje isključen.

Izveštaj „Dexter proba F1b.7” vratio je Google Doc link i pregled sadržaja:
trenutne poslovne zadatke po statusu odvojene od kalendarskih događaja u opsegu.
Done nije proglašen završenim u tom periodu. Ova evidencija se zasniva na
prosleđenom rezultatu bota; dokument nije nezavisno otvoren kroz alat ove sesije,
niti je korisnik posebno potvrdio detalje celodnevnog događaja. Linkovi,
lični podaci i sadržaj klijentskih zadataka nisu preneti u repo.

Probna činjenica je sačuvana sa oznakom Alfa i kategorijom projekat, zatim
promenjena u Beta. Korisnik je prosledio naknadni pregled sa istim ID-jem i
kategorijom. Prvi prikaz pozvan paralelno sa upisom pokazao je staru verziju;
ponovljeno čitanje posle upisa potvrdilo je novo stanje. Obnova vektora,
očuvanje izvora i paralelne delimične promene ostaju DB provere.

Glavni ručni tokovi F1b.7 su provereni. Ova dopuna menja samo dokumentaciju;
izvršni kod je isti kao u zelenom CI prolazu sa 592 testa. Rasporedi i
automatske poruke ostaju F1b.8, uz SCHEDULER_ENABLED=off do dogovorenog uključivanja.

## F1b.8 — svih 14 zakazanih poslova (18.10.2026)

Pročitani su stari services/scheduler.js, motivation.js, jobs.js, konfiguracija,
README, definicije i servisi koje poslovi koriste. Preneti su isti cron ENV
nazivi i podrazumevana vremena iz Dodatka B. Migracija 014 uvodi motivacionu
istoriju; SYSTEM_PROMPT nije menjan. SCHEDULER_ENABLED ostaje off u uputstvu.

Pre: 592 testa sa bazom. Posle: 656 testova sa izolovanom PostgreSQL 14 +
pgvector bazom, 14,83 s. Ruff format/check prolaze za src/tests/evals/scripts.
Dodate su 64 provere: 48 konfiguracionih/servisnih/SDK mock testova i 16 slučajeva
sa stvarnom test bazom. Spoljni Notion, Google, IMAP, Anthropic i Telegram pozivi
koriste mock; nisu pokrenuti poslovi na privatnim nalozima niti plaćeni modeli.
Bez TEST_DATABASE_URL: 546 prolaza i 110 očekivano preskočenih DB slučajeva, 6,34 s.
GitHub CI dodatno proverava PostgreSQL 17 i Docker pakovanje.

Rasporedi: svih 14 registrovanih poslova plus četiri postojeća F2/F6 posla,
TIMEZONE, standardni Node dani (0/7 nedelja), zasebna promena svakog cron ENV-a,
wrapper run_job, uslovi dostupnosti integracija, coalesce/max_instances i
neispravna konfiguracija. Globalno isključivanje ostaje pokriveno starim testom.
Jutarnja priprema je tiha i povezuje dnevnik; DB/Notion testovi proveravaju
idempotentnost, popunu prazne veze bez prepisivanja dnevnika i odbijanje konflikta.

Poruke: tihi/puni monitoring, prazni i nečestitani rođendani, prag pohvale ispod,
na i iznad granice, dan bez reda ili stavki, večernji skor/nedeljni cilj/dnevnik/
zadatak, delimično nedostupan dodatak i nedeljni dinamičan zbir. Jutarnji pozdrav
ima ponedeljne rođendane i podnosi nedostupnu prognozu. Poslovni pregled dobija
kalendarski lokalni dan od 25 sati preko oktobarske promene sata, samo dva otvorena
statusa, oznaku za više od 15 zadataka i napomenu pri grešci kalendara, bez poziva
prognoze. Poreski prompt izričito izbegava tvrdnju o pravnom roku/iznosu.

Stvarni Anthropic SDK/respx test proverava MODEL_FAST, purpose=scheduler,
latinicu i fiksno uputstvo odvojeno od sirovog sadržaja. Prekinut/prazan ili
predug izlaz ne pravi slanje. Motivacija čita prethodne tekstove i ugao,
prepoznaje istu/skoro istu formulaciju (uključujući ćirilicu/interpunkciju),
ponavlja generisanje i normalizuje navodnike. DB test proverava trajnost,
rotaciju na N, status sent i zaštitu ponovljenog teksta pri rezervaciji.
Semantička raznovrsnost, kvalitet pravih jutarnjih poruka, cena i latencija
nisu izmereni; sličnost teksta nije dokaz različite poente.

Pravi imap-tools kod radi preko lažnog IMAP protokola: UIDVALIDITY, svi
nepročitani UID-jevi uz samo 15 BODY.PEEK[HEADER] učitavanja, readonly i bez
Seen/STORE promene; prazan skup ne pokreće FETCH svih poruka. DB testovi
proveravaju trajnost posle obnove konekcija, uklanjanje samo pročitanih UID-jeva,
starije nepročitane van prikaza, novu UIDVALIDITY vrednost, paralelne provere,
neuspešno generisanje bez rezervacije, poslovni pregled bez narednog duplog
obaveštenja i neizvestan ishod koji zadržava prijavljene poruke. Ograničenje:
starije nove poruke van najnovijih 15 čekaju da uđu u prikaz, kao u v1.

Isporuka: potvrđen trag preskače ponovno pripremanje/slanje; paralelan claim
šalje jednom. Telegram odbijanje oslobađa claim/motivaciju i vraća IMAP stanje.
Timeout ostavlja unknown, tri run_job pokušaja dele isti ID i datum, nema drugog
slanja originala, a završno upozorenje se šalje jednom. Cancel se propagira i
ostavlja sending; ponovni poziv odbija slepi resend. Nema tvrdnje o exactly-once
isporuci niti distribuisanom zaključavanju svih rasporeda između više botova.

Pri implementaciji su redeploy, uključivanje i izvršavanje na pravom nalogu
čekali ručnu proveru. Rezultati naknadne provere slede ispod. Stara JSON
istorija nije uvezena (F1b.10); prvi pregled može prijaviti postojeće nepročitane poruke.

### F1b.8 — rezultati ručne provere (19.10.2026)

Posle redeploy-a korisnik je prosledio /status sa svim aktivnim alatima,
dostupnom bazom i automatskim poslovima prvo off. Izričito je prihvatio da
stari APU nastavi paralelno da radi, uz objašnjenje mogućih duplih podsetnika
i upisa dva bota. Zatim je postavio SCHEDULER_ENABLED=on i prosledio novi
/status koji potvrđuje uključenost. Ova saglasnost ne znači da dva bota dele
zaštitu od duplikata; svaka instalacija i dalje ima svoje stanje.

Prvobitno /poslovi nije imao pokretanja, očekivano pre prvog termina.
Produkcioni log potom je potvrdio „Scheduler pokrenut (18 poslova).”, dostupnu
bazu i start aplikacije bez prikazane greške. Sa privremenim
MAIL_CHECK_CRON=* * * * * korisnik je prosledio /poslovi 1: mail_check 1/1
uspeha, bez neuspeha ili pokretanja u toku, 19.10.2026. u 11:27 po prikazu bota.
To potvrđuje stvarni prolazak scheduler-a kroz evidenciju job_runs.

Na uputstvo za novi probni mejl korisnik je prosledio jedno Telegram obaveštenje
sa pošiljaocem i naslovom. Potom je, na uputstvo da mejl ostane nepročitan,
restartuje Dexter i sačeka dva minuta, odgovorio „Nema” na pitanje o ponovljenom
obaveštenju. Time je za taj slučaj potvrđeno da prijavljeni mejl nije ponovljen
posle restarta. Nije rađena nezavisna IMAP/DB provera, niti je prikazan novi
/poslovi posle restarta. Adresa i sadržaj probnog mejla nisu preneti u repo.

Na kraju je korisnik potvrdio vraćanje MAIL_CHECK_CRON=0 8-22 * * * po uputstvu
za čuvanje i redeploy. Udaljeni ENV i log posle tog koraka nisu nezavisno očitani.
SCHEDULER_ENABLED ostaje on; Auto Deploy nije tražen da se uključi. Probni
minutni raspored više nije dogovorena konfiguracija.

Ostaju za stvarno posmatranje: automatska priprema dana, nedeljni lični upis,
jutarnji pozdrav/motivacija i poslovni pregled, monitoring po satnici,
rođendanski i večernji uslovni podsetnici/pohvale, nedeljni pregled i porez.
Ovi tokovi imaju postojeće mock/DB provere; nisu svi ručno potvrđeni samo zato
što je mail_check uspeo. Uvoz istorije je i dalje F1b.10. Ova dopuna menja samo
dokumentaciju; izvršni kod je isti kao u zelenom CI prolazu sa 656 testova.

## F1b.9 — komande i provera Notion šema (19.10.2026)

Pročitani su v1 services/schema.js, /provera iz services/telegram.js, startup
poziv iz index.js, README i odgovarajući opisi Notion alata. Postojeće
/status i /poslovi ostaju, dodata je /provera i pozadinska provera pri startu.
Nema novih ENV promenljivih, šeme PostgreSQL-a ili promene SYSTEM_PROMPT-a.
kv_state čuva otisak nalaza i ishod pokušaja obaveštenja.

Pre: 656 testova sa bazom. Posle: 695 testova sa izolovanom PostgreSQL 14 +
pgvector bazom, 16,23 s. Bez baze: 573 prolaza i 122 očekivano preskočena DB
slučaja, 7,56 s. Ruff format/check prolaze za src/tests/evals/scripts. Dodato
je 39 provera, od toga 27 servisnih/SDK/Telegram mock i 12 DB slučajeva.
Spoljni Notion i Telegram pozivi su mock; nisu pozivani privatni nalozi,
plaćeni modeli niti menjane stvarne kolone. CI proverava i PostgreSQL 17 i Docker.

Šema: sedam minimalnih v1 ugovora, tačna razlika status/select, FAKTURE nezavisno
od Google-a, dinamična checklista i obavezna veza Dnevnik → Checklista samo
kada su obe baze podešene. Izdvojeno se prijavljuju prazne/ponovljene navike,
cilj van spiska i nepraćene checkbox kolone, bez proglašavanja opcionih
fiskalnih/kontakt podataka obaveznim. Nepodešene baze ne prave HTTP zahteve.
Respx test koristi pravi Notion SDK: GET baze pa njenog data_source-a, verzija
2025-09-03, bez query/create/update poziva. Prazan/višestruk izbor izvora se
odbija; nedostajuće properties nisu zdrav rezultat. Provereni su odsutna
kolona, pogrešan tip, timeout, HTTP 400/401/403/404 bez reflektovanja serverovih
tajni i jedna nedostupna baza uz očuvane nalaze druge. Cancel se propagira.

Komanda je registrovana i ograničena na vlasnika; veliki izveštaj je latinicom,
bez gubitka teksta i ispod 3900 UTF-16 jedinica po poruci. Neočekivana greška
ima bezbednu poruku. Start ne čeka mrežnu proveru; zaseban test potvrđuje
nedovršen zadatak posle post_init, njegovo otkazivanje i idempotentno čišćenje
pri gašenju. Postojeći scheduler-off test potvrđuje da se pomoćna provera
ipak pokrene. Ne dodaje se novi cron niti se menjaju postojeći rasporedi.

DB: prvi zdrav nalaz je tih i ostaje preko novih konekcija. Prvi problem,
nov problem posle zdravog nalaza, izmenjen problem i oporavak javljaju se jednom;
ponovljen isti nalaz i tri paralelna starta ne prave ponovljene poruke. Otisak
ignoriše redosled nalaza/kolona, ali razlikuje stvarnu promenu. Bez podešenih
baza i pri neočekivanom prekidu provere prethodno stanje se ne briše. Ručna
komanda ne piše startup stanje i ne potiskuje sledeće startno obaveštenje.

Definitivno odbijeno prvo Telegram slanje vraća prethodni otisak ili briše
prvi pokušaj, pa sledeći start može ponovo. Timeout čuva unknown i posle
obnove konekcija ne šalje ponovo isti nalaz. Cancel ostavlja attempted i
oslobađa advisory lock. Kod dužeg izveštaja, uspešan prvi deo pa odbijen drugi
deo ne ponavlja već poslati deo. Izveštaj se može dobiti ručno kroz /provera.
Ovo nije garancija isporuke svakog upozorenja: posle neizvesnog/otkazanog slanja
prednost ima izbegavanje restart petlje i duplih poruka.

Pri implementaciji su redeploy, /provera na pravim bazama i ponašanje posle
restarta čekali ručnu proveru. Rezultati slede ispod. Stvarna promena šeme i
oporavak nisu izazivani na produkcionim kolonama; pokriveni su SDK/mock/DB
proverama. Ne menjati stvarne kolone samo radi testa bez izričitog dogovora.

### F1b.9 — rezultati ručne provere (19.10.2026)

Posle uputstva za redeploy bez promena ENV-a korisnik je prosledio odgovor
na /provera: „Notion šeme su u redu (provereno baza: 7).” Time je potvrđeno
čitanje stvarnih metapodataka sedam podešenih Notion baza i ispravan ručni
izveštaj. To nije provera sadržaja redova, svih opcionih polja ili dozvola za upis.

Zatim je, na uputstvo da u Coolify-u restartuje Dexter i sačeka oko minut,
korisnik odgovorio da nije stiglo ništa. To odgovara očekivanom tihom startu
za nepromenjen zdrav nalaz. Restart log, izvršenje pomoćnog zadatka i kv_state
nisu nezavisno očitani u ovoj sesiji; odsustvo poruke samo po sebi ne proverava
putanju upozorenja za neispravnu šemu. Ta putanja, promena problema i oporavak
ostaju pokriveni SDK/mock/DB testovima, bez menjanja stvarnih kolona za probu.

Glavni ručni tok F1b.9 je potvrđen. SCHEDULER_ENABLED i redovni MAIL_CHECK_CRON
ostaju po prethodnom dogovoru, bez nove konfiguracije. Ova dopuna menja samo
dokumentaciju; izvršni kod odgovara zelenom CI prolazu sa 695 testova.
