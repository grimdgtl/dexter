# Arhitektura Dextera

[Pregled projekta](../README.md) · [Testiranje](TESTING.md) · [Konfiguracija](OPERATIONS.md)

Dexter je modularni servis za jednog korisnika. Python proces obrađuje Telegram
poruke i zakazane poslove, a PostgreSQL čuva razgovore, indeks i trajne ishode.
Spoljni servisi imaju odvojene klijente u `src/dexter/services/`. Aplikacija koristi
njihove API-je; nema javni HTTP endpoint niti zahteva administrativni panel.

## Obrada poruke

1. [Telegram sloj](../src/dexter/telegram_bot.py) proverava vlasnikov chat ID,
   preuzima prilog i pretvara glas u tekst ili sliku u ulazni blok.
2. Zaključavanje po razgovoru sprečava da dve razmene istovremeno učitaju i
   dopišu istu istoriju. Pozivi transkripcije i obrade priloga imaju svoje tokove.
3. [Agentska petlja](../src/dexter/agent/loop.py) bira model, učitava relevantne
   činjenice, poslednje razmene, tekući sažetak i ishode prethodnih potvrda.
4. Model dobija statičan sistemski prompt i šeme dostupnih alata. Promenljivo
   vreme, memorija i sažetak idu u kontekst poruke. Alati imaju stabilan redosled
   radi keširanja, a `cache_control` se ne upisuje u trajnu istoriju.
5. Pozivi alata iz jednog koraka izvršavaju se paralelno. Ako je rezultat jednog
   potreban kao ulaz drugom, model mora da ih rasporedi u odvojene korake;
   izvršavač ne zaključuje zavisnosti između proizvoljnih alata.
6. Gotova razmena se čuva, a izdvajanje trajne memorije i obaveza radi u pozadini.
   Tekst se u Telegramu može prikazivati tokom generisanja; potvrde se pripremaju
   tek iz celovitog rezultata. Kvar pomoćnog statusa kucanja ne prekida odgovor.

Broj agentskih koraka je ograničen. Odgovor prekinut na `max_tokens` ne upisuje
nesparene pozive alata u istoriju. Ako sažimanje ranijih razmena ne uspe, razgovor
može nastaviti sa poslednjim razmenama i prethodnim potvrđenim sažetkom, uz jasnu
napomenu modelu da deo konteksta nedostaje.

## Pretraga i memorija

| Stanje | Namena |
|---|---|
| `messages` | Sirova istorija razgovora i pozivi/rezultati alata. |
| `conversation_context` | Tekući sažetak starijeg prefiksa i granica obrađenih poruka. |
| `facts` | Dugoročne činjenice sa vektorima, nezavisne od prozora istorije. |
| `documents`, `chunks` | Indeks izvora, sačuvan tekst, metapodaci i vektorizovani delovi. |
| `pending_notes` | Ishodi potvrda/otkazivanja za kontekst naredne razmene. |

[Izvori](../src/dexter/sources/) čitaju Notion, Drive, mejlove i dnevne sažetke
razgovora. [Uvoz fajlova](../src/dexter/rag/ingest.py) bira direktno čitanje,
Office parser ili OCR. Nepromenjeni dokumenti preskaču embedding poziv na osnovu
heša sadržaja i otiska konfiguracije indeksa. Nestali dokumenti uklanjaju se iz
indeksa tek posle uspešnog obilaska izvora.

[Hybrid search](../src/dexter/rag/store.py) spaja dva rangiranja: vektorsku
sličnost preko pgvector-a i PostgreSQL full-text. Reciprocal Rank Fusion ne
pretpostavlja da su kosinus i full-text skor na istoj skali. Prag kosinusne
sličnosti primenjuje se na odlomke bez tačnog full-text pogotka; konačni RRF skor
je rang, a ne verovatnoća da je odgovor tačan. Dostupni su izvor, vremenski opseg
i opciono modelsko preslaganje kandidata.

OpenAI i lokalni E5 koriste isti interfejs. Lokalni inference radi u radnoj niti
i ima ograničenu paralelnost. Promena modela ili dimenzije zahteva
[ponovnu vektorizaciju](../scripts/reembed.py); aplikacija odbija nepodudaran
vektorski prostor. Samo uključivanje lokalnih embeddinga ne prebacuje razgovor,
OCR i ostale API funkcije na lokalno izvršavanje.

## Predlog, potvrda i spoljne promene

[Registar alata](../src/dexter/tools/registry.py) iz Pydantic modela izvodi šemu
za LLM i validira argumente pre poziva servisa. Alati bez potrebnih podešavanja
nisu dostupni modelu. Osetljive radnje imaju `confirm=True`: model priprema
predlog, a izvršenje zahteva korisnikovo Telegram dugme.

Potvrde na čekanju su u memoriji procesa i ističu posle 30 minuta. Restart ih
poništava; potrebno je pripremiti nov predlog. To nije isto što i trajna zaštita
od ponavljanja: pojedini servisi dodatno čuvaju rezervaciju i ishod u bazi.

Ugovorni zadaci i zakazane dostave rezervišu pokušaj pre mrežnog upisa/slanja.
Potvrđeno odbijanje i neizvestan ishod razlikuju se: timeout posle slanja zahteva
ne dokazuje da upis nije izvršen, pa se takav zahtev ne ponavlja naslepo.
Ovo smanjuje rizik duplikata i zahteva ručnu proveru neizvesnih ishoda; ne
predstavlja garanciju jedne transakcije preko PostgreSQL-a i spoljnih API-ja.

## Obrada ugovora

[Ugovorni tok](../src/dexter/contracts/service.py) odvojen je od običnog RAG uvoza.
Stranice i OCR pasusi ostaju numerisani, a model predlaže polja sa citatima kroz
strogu Pydantic strukturu. [Verifikator](../src/dexter/contracts/evidence.py)
proverava prisustvo citata i vrednosti uz normalizaciju latinice i belina;
datumi imaju dodatnu proveru formata i stvarnog kalendarskog datuma.

Predlozi zadataka izvode se u kodu iz dovoljno potvrđenih polja. Nejasan rok se
ne nagađa. Pri potvrdi se proveravaju poslovno Work odredište, šema i nepromenjen
izbor liste. Izvor ide u opis, a naslov ostaje kratak. Potvrda jednog predloga
ne odobrava ostale.

OCR checkpoint-i i pregled čuvaju se u `kv_state`, vezani za vlasnika, otisak
originalnog fajla i verziju obrade. Ponovno slanje istih bajtova koristi već
sačuvan prepis/pregled. Ugovor ne ulazi automatski u opšti RAG indeks.

Potvrđen citat je dokaz veze sa prepisom, ne pravne ispravnosti. Pogrešan OCR,
pripisivanje obaveze i tumačenje uslova ostaju predmet ljudskog pregleda.

## Zakazani poslovi i troškovi

[Scheduler](../src/dexter/scheduler.py) registruje poslove po korisnikovoj zoni.
[Omotač poslova](../src/dexter/jobs.py) beleži pokušaje, vreme i greške, a
[dostava](../src/dexter/scheduled_delivery.py) odvojeno prati ishod Telegram slanja.
Registracija cron-a nije dokaz da je posao izvršen: to se proverava u `/poslovi`.

[LLM klijent](../src/dexter/llm.py) centralno meri Anthropic potrošnju i latenciju.
Pozivi se povezuju sa razmenom kroz `turn_id`. Cena je procena prema tabeli cena;
račun provajdera je merodavan. Dnevni budžet je meko ograničenje i ne obuhvata
sve servise, uključujući embeddinge, transkripciju i TTS.

`economy` režim bira model lokalnim pravilom. Lokalni klasifikator ima zaseban
eksperimentalni trening i evaluaciju; nije automatski uveden u rad bota.
Pozadinski kratki tekstovi koriste odgovarajuće parametre podržanog modela,
kontrolu završenosti i ograničen ponovni pokušaj kod presečenog odgovora.

## Granice trenutne instalacije

- Jedan vlasnik i jedna polling instanca po tokenu; nema modela za više korisnika.
- Nezavisne instalacije nad istim Notion bazama ne dele lokalne rezervacije.
- Notion zadatak i lokalna obaveza nemaju automatski usklađene statuse završetka.
- Izvori, OCR i API modeli obrađuju podatke van servera prema uključenim integracijama.
- Benchmark nad malim sintetičkim skupom ne zamenjuje evaluaciju stvarnih dokumenata.

Detalji konfiguracije, backup-a i deploy-a nalaze se u [operativnom vodiču](OPERATIONS.md).
