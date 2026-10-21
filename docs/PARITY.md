# Pokrivenost funkcija i ručne provere

Ovo je istorijska matrica sa datiranim beleškama, ne prikaz trenutnog stanja
privatnih naloga. Aktuelni postupak i obim automatskih provera su u
[TESTING.md](TESTING.md); rezultati eksperimenata su u [EVAL.md](EVAL.md).

## Završni audit F1b.11 — 19.10.2026.

Katalog ima 46 alata, 14 rasporeda i pet komandi. Dexter ima 54 alata: svih 46
zamena i osam novih (memory_search, commitments_list, commitment_done, proactive_log,
receipt_extract, web_search, contract_get, contract_task_create).
F7.1 dodaje lični /ugovor tok i potvrde predloga, bez promene starih alata.
Perplexity pretraga je dodata 19.10.2026. u F3.6;
HTTP/DB testovi prolaze, stvarni ključ i izvori čekaju ručnu proveru.
Preimenovani su samo semantic_search → knowledge_search i
semantic_reindex → knowledge_reindex.

**Kod i testovi su odvojeni od stvarne operativne potvrde.** ✅ u koloni kod/test
znači da je funkcija preneta i automatski proverena; ne znači da je svaki poziv
izvršen na privatnom nalogu. ✓ znači prosleđen stvarni rezultat ili potvrdu
korisnika, △ posrednu proveru istog servisa, — preostalu ručnu proveru. Rubne
greške, konkurentnost i backend varijante imaju mock/DB testove iz navedenih fajlova.
`tests/fixtures/tool_contract.json` čuva 46 javnih naziva i argumenata;
`tests/test_parity.py` proverava zamene, sve argumente, potvrde, komande
simbolički i registraciju svih rasporeda. Test ne zove prave API-jeve.

### Svih 46 starih alata

| Stari alat | Dexter | Kod/test | Ručna provera |
|---|---|---|---|
| `client_add` | `client_add` | ✅ test_notion_business.py | ✓ 18.10: novi red i dopuna bez duplikata |
| `client_update` | `client_update` | ✅ test_notion_business.py | ✓ 18.10: delimična izmena |
| `client_list` | `client_list` | ✅ test_notion_business.py | ✓ 18.10 |
| `client_find` | `client_find` | ✅ test_notion_business.py | ✓ 18.10 |
| `notion_add_task` | `notion_add_task` | ✅ test_notion_business.py | ✓ 18.10 |
| `notion_list_tasks` | `notion_list_tasks` | ✅ test_notion_business.py | ✓ 18.10 |
| `notion_update_task_status` | `notion_update_task_status` | ✅ test_notion_business.py | ✓ 18.10 |
| `notion_add_knowledge` | `notion_add_knowledge` | ✅ test_notion_business.py | ✓ 18.10 |
| `notion_read_page` | `notion_read_page` | ✅ test_notion.py | ✓ 18.10: čitanje Life stranice |
| `notion_search` | `notion_search` | ✅ test_notion.py | ✓ 18.10 |
| `memory_save` | `memory_save` | ✅ test_memory_update.py, test_integration.py | ✓ 18.10 |
| `memory_list` | `memory_list` | ✅ test_memory_update.py, test_integration.py | ✓ 18.10 |
| `memory_update` | `memory_update` | ✅ test_memory_update.py, test_integration.py | ✓ 18.10: isti ID |
| `memory_forget` | `memory_forget` | ✅ test_memory_update.py, test_integration.py | — zaseban ručni test brisanja nije potvrđen |
| `semantic_search` | `knowledge_search` | ✅ test_integration.py, test_notion.py, test_mail.py | — poslednji indeks prazan; potrebna stvarna pretraga |
| `semantic_reindex` | `knowledge_reindex` | ✅ test_integration.py, test_notion.py, test_mail.py | — potrebno prvo stvarno indeksiranje |
| `monitor_uptime` | `monitor_uptime` | ✅ test_monitor.py | ✓ 18.10: 22 sačuvana uzorka |
| `insights_get` | `insights_get` | ✅ test_checklist.py, test_integration.py | ✓ 18.10 |
| `checklist_get` | `checklist_get` | ✅ test_checklist.py, test_integration.py | ✓ 18.10 |
| `checklist_mark` | `checklist_mark` | ✅ test_checklist.py, test_integration.py | ✓ 18.10 |
| `checklist_create_day` | `checklist_create_day` | ✅ test_checklist.py, test_integration.py | ✓ 18.10: postojeći red bez duplikata; novi red još nije potvrđen |
| `dnevnik_get` | `dnevnik_get` | ✅ test_checklist.py, test_integration.py | — čitanje nije izdvojeno; podaci potvrđeni kroz upis/insights |
| `dnevnik_write` | `dnevnik_write` | ✅ test_checklist.py, test_integration.py | ✓ 18.10: delimičan pa dopunjen zapis |
| `todo_list` | `todo_list` | ✅ test_todo.py, test_integration.py | ✓ 18.10 |
| `todo_add` | `todo_add` | ✅ test_todo.py, test_integration.py | ✓ 18.10 |
| `todo_set_status` | `todo_set_status` | ✅ test_todo.py, test_integration.py | ✓ 18.10 |
| `drive_search` | `drive_search` | ✅ test_google.py | ✓ 18.10 |
| `drive_read` | `drive_read` | ✅ test_google.py | — zaseban ručni poziv nije dostavljen |
| `drive_create` | `drive_create` | ✅ test_google.py | △ isti servis potvrđen kroz generate_report; alat nije izdvojen |
| `calendar_list_events` | `calendar_list_events` | ✅ test_calendar.py | ✓ 18.10 |
| `calendar_find_free_slots` | `calendar_find_free_slots` | ✅ test_calendar.py | ✓ 18.10 |
| `calendar_create_event` | `calendar_create_event` | ✅ test_calendar.py | ✓ 18.10: potvrđen ponavljajući događaj |
| `mail_list_unread` | `mail_list_unread` | ✅ test_mail_tools.py | ✓ 18.10 |
| `mail_search` | `mail_search` | ✅ test_mail_tools.py | ✓ 18.10 |
| `mail_read` | `mail_read` | ✅ test_mail_tools.py | ✓ 18.10: ceo mejl |
| `mail_folders` | `mail_folders` | ✅ test_mail_tools.py | △ pronalaženje Drafts kroz nacrt; direktan poziv nije izdvojen |
| `mail_save_draft` | `mail_save_draft` | ✅ test_mail_tools.py | ✓ 18.10: nacrt bez slanja |
| `mail_send` | `mail_send` | ✅ test_mail_tools.py | ✓ 18.10: potvrda i prijem u inbox (Resend); SMTP mock |
| `monitor_check_sites` | `monitor_check_sites` | ✅ test_monitor.py | ✓ 18.10: 22 sajta |
| `weather_get` | `weather_get` | ✅ test_weather.py | — čeka stvarnu prognozu |
| `invoice_create` | `invoice_create` | ✅ test_invoices.py, test_integration.py | ✓ 18.10: PDF, Odbaci i potvrđeno Sačuvaj |
| `invoice_list` | `invoice_list` | ✅ test_invoices.py, test_integration.py | ✓ 18.10 |
| `birthdays_today` | `birthdays_today` | ✅ test_birthdays.py | ✓ 18.10 |
| `birthdays_upcoming` | `birthdays_upcoming` | ✅ test_birthdays.py | ✓ 18.10 |
| `birthday_mark_greeted` | `birthday_mark_greeted` | ✅ test_birthdays.py | ✓ 18.10: probna osoba |
| `generate_report` | `generate_report` | ✅ test_reports.py | ✓ 18.10: Doc link; sadržaj dokumenta nije nezavisno pregledan |

Dodatni test ugovora proverava da nijedan stari argument nije nestao i da nisu
uvedena nova obavezna polja. To ne dokazuje jednakost svih rezultata: validacija,
limiti, numerički ID memorije i zaštite potvrde namerno se razlikuju, kao što je
objašnjeno u beleškama ispod. knowledge_search ima v2 default limit 6 naspram v1 5,
uz opcion izvor i vremenski opseg; weather_get dodaje opcionih 1–7 dana. Stari
pozivi bez tih dodataka ostaju dozvoljeni. Fiskalna polja nisu dodata invoice ulazu.

### Svih 14 starih rasporeda

Vremena su podrazumevana za TIMEZONE=Europe/Belgrade; podešen ENV ima prednost.
Svi koriste run_job, a test_scheduled_jobs.py i test_parity.py proveravaju cron
nazive, podrazumevane vrednosti, registraciju i omotač. Test_integration.py proverava
trajnost, retry i neizvesne ishode. Registracija svih 18 ukupnih poslova potvrđena
je logom 19.10; to nije potvrda da su svi već stigli na red.

| Cron ENV | Podrazumevano | Dexter posao | Kod/test | Stvarno zakazano izvršavanje |
|---|---|---|---|---|
| SEMANTIC_INDEX_CRON | `0 4 * * *` | knowledge_index | ✅ | — indeks još čeka potvrdu |
| CHECKLIST_CREATE_CRON | `0 5 * * *` | prepare_day | ✅ | — novi dan i veza sa dnevnikom |
| FLOWERS_TASK_CRON | `0 5 * * 1` | weekly_task | ✅ | — nedeljni upis |
| MORNING_GREETING_CRON | `0 6 * * *` | morning | ✅ | — motivacija, prognoza, ponedeljni rođendani |
| MORNING_BRIEFING_CRON | `30 9 * * *` | morning_briefing | ✅ | — poslovni pregled |
| MAIL_CHECK_CRON | `0 8-22 * * *` | mail_check | ✅ | ✓ 19.10: job_runs, novi mejl, bez duplikata posle restarta |
| SITE_CHECK_SILENT_CRON | `0 10 * * *` | site_check_silent | ✅ | — tihi režim |
| BIRTHDAY_MORNING_CRON | `0 11 * * *` | birthday_morning | ✅ | — današnji rođendani po satnici |
| SITE_CHECK_REPORT_CRON | `0 18 * * *` | site_check_report | ✅ | — pun izveštaj |
| BIRTHDAY_EVENING_CRON | `0 19 * * *` | birthday_evening | ✅ | — samo nečestitani |
| CHECKLIST_REMINDER_CRON | `30 21 * * *` | checklist_reminder | ✅ | — večernji podsetnik |
| CHECKLIST_PRAISE_CRON | `0 23 * * *` | checklist_praise | ✅ | — uslovna pohvala |
| WEEKLY_SUMMARY_CRON | `0 22 * * 0` | weekly_summary | ✅ | — nedeljna pohvala |
| TAX_REMINDER_CRON | `0 10 14 * *` | tax_reminder | ✅ | — mesečni termin; neće se desiti u probnoj nedelji |

Četiri nova rasporeda ostaju zasebna: conversation_summaries (03:30),
commitment_reminders (09:00), daily_insight (08:30), weekly_review (nedelja 20:00).
F6 poštuje svoju tišinu i ograničenja; eksplicitni v1 rasporedi poštuju cron.
Uslovni posao može uspešno završiti bez poruke; proverava se /poslovi, ne samo inbox.

### Svih pet starih komandi

| Komanda | Dexter handler | Kod/test | Ručno |
|---|---|---|---|
| `/start` | cmd_start | ✅ test_parity.py | ✓ 18.10: pozdrav |
| `/reset` | cmd_reset | ✅ test_integration.py: samo svoj razgovor, činjenice ostaju | — ne brisati stvarni razgovor samo za probu |
| `/status` | cmd_status | ✅ test_status.py, test_integration.py | ✓ 18/19.10: alati, baza, scheduler |
| `/poslovi [sati]` | cmd_jobs | ✅ test_parity.py, test_integration.py | ✓ 19.10: uspešan mail_check |
| `/provera` | cmd_schema | ✅ test_schema.py, test_integration.py | ✓ 19.10: sedam baza, tih restart |

Nove komande `/troskovi`, `/memorija`, `/duboko`, `/rashodi` ne zamenjuju ove komande.
Sve komande su ograničene na vlasnika; dodatni argumenti /poslovi imaju kontrolu opsega.

### Operativne provere

Automatski testovi i ručna provera dostupnosti integracija su odvojeni koraci.
Pre završne procene stabilnosti treba posmatrati zakazane poslove, proveriti
indeksiranje i pretragu sopstvenih izvora i pregledati neuspešna izvršavanja.
Detaljan postupak je u [operativnom vodiču](OPERATIONS.md#operativne-provere).

## Beleške nastale tokom prenosa F1b.1–F1b.9

Ovo su istorijske beleške razvoja; aktuelna matrica i preostale provere su iznad.
Navodi da neka faza ili uključivanje „čeka” odnose se na trenutak te beleške.

F1b.1 zadržava argumente, RRULE i `sendUpdates` ponašanje iz v1. Pregled više nije
ograničen na prvih 50 događaja: prolazi sve stranice. Slobodni intervali se ograničavaju
na traženi kraj i računaju u korisnikovoj zoni preko promene sata; stari kod je mogao
vratiti interval posle `timeMax`. Zakazivanje sada obavezno traži potvrdu po pravilima
ovog projekta. Ako su zadati i `do` i `broj`, ulaz se odbija umesto tihog ignorisanja
broja. Rok `do` i dalje znači kraj UTC dana; vikendi se ne preskaču.

F1b.2 zadržava otvorene zadatke kao podrazumevani pregled, status `Not started`
pri dodavanju, opcione oblast/prioritet/rok i nedeljni zadatak sa rokom u nedelju.
Postojeći nedeljni zadatak se prepoznaje po delu naslova i roku unutar sedmice,
uključujući završen zadatak. Notion API `2025-09-03` zahteva otkrivanje data source-a
iz starog database ID-a; više izvora se odbija umesto proizvoljnog izbora tabele.
Promena statusa proverava pripadnost ličnoj bazi. Ulaz sada proverava datum,
UUID, prazne naslove i granice limita (1–100); pregled prati paginaciju do limita.

Nedeljni upis koristi trajni jedinstveni ključ u `kv_state` uz Notion proveru:
paralelni proces, restart ili neizvestan HTTP ishod ne ponavljaju create naslepo.
Ako upis nije potvrđen ni naknadno pronađen, traži se ručna provera. Zadatak
obrisan ili premešten u istoj sedmici neće se automatski ponovo napraviti.
Definitivno odbijen zahtev (4xx osim timeout-a) oslobađa pokušaj za novi retry.
Obaveštenje se šalje samo pri novom potvrđenom upisu, kao u v1; greška slanja
ne ponavlja upis zadatka. Tekst ne obećava kasnije podsetnike, jer checklista
i večernji podsetnici još čekaju F1b.4/F1b.8. Raspored radi samo kada je globalni
scheduler uključen; `FLOWERS_TASK_CRON` zadržava standardni ponedeljak = 1.

F1b.3 zadržava argumente i podrazumevane limite v1 (10 nepročitanih, 20 u pretrazi,
500 znakova pregleda, 20000 za čitanje), kombinovane filtere, Seen stanje, UID i
folder, CC, Message-ID i reference odgovora. Limit je sada validiran na 1–100;
datum i UID se proveravaju pre IMAP poziva. Nazivi/putanje foldera ostaju tačni,
a prikaz i sadržaj odgovora su latinicom. HTML ima tekstualni prikaz, a telo
priloženog dokumenta nije telo mejla. mail_read ima veći rezultat u registru da
standardni limit od 12000 znakova ne bi odsekao telo od 20000 znakova.

Draft koristi MIME umesto ručnog spajanja zaglavlja; prvenstvo ima serverov
special-use Drafts folder, zatim poznati nazivi iz v1 i INBOX.Drafts/INBOX/Drafts.
Kada ga nema, prijavljuje grešku bez upisa drugde. From za draft može pasti na
IMAP_USER kada MAIL_FROM_ADDRESS i SMTP_USER nisu podešeni. Novi redovi/kontrolni
znakovi u zaglavljima sada se odbijaju umesto tihog uklanjanja. Primaoci se parsiraju
kao pojedinačne adrese, pa lista više primalaca radi i preko Resend-a.

Slanje koristi Resend kada ima ključ, bez SMTP fallback-a nakon greške; bez
ključa koristi SMTP sa TLS ili obaveznim STARTTLS. Plaintext SMTP nije podržan.
Resend slanje je dostupno bez IMAP-a kada postoji From adresa. Alternativna
konfiguracija je objašnjena kroz `requires_any` u /status. Potvrda traje 30 minuta,
jednokratna je i vezana za prikazani pošiljalac/primaoce/tekst; model ne može da
prosledi From adresu. SMTP rezultat sadrži prihvaćene i odbijene primaoce da se
delimično poslat mejl ne bi ponavljao svima. Kopiranje u Sent nije dodato:
kao v1, uspeh znači da je transport prihvatio poruku, ne potvrdu dostave.

F1b.4 čuva šest potpisa alata, ENV nazive navika, obrnute `Bez ` stavke,
nedeljni cilj, srpska imena dana i stare Notion kolone. Skor je broj označenih
podešenih navika; formula u Notion-u se ne menja. Tačni nazivi se dobijaju preko
`checklist_get`, umesto da se lične navike ugrađuju u opis alata ili SYSTEM_PROMPT.
Izostavljena polja dnevnika ostaju netaknuta, a `prazno` traži potpitanje; kad
red ne postoji, vraćaju se imena sva tri polja umesto neodređenog „sve”.

Čitanje ne kreira red. Kreiranje dana koristi trajni ključ `kv_state` po data
source-u i datumu radi zaštite između procesa/restarta/neizvesnog HTTP ishoda.
Ako je prethodno potvrđen red privremeno nevidljiv u pretrazi, čita se direktno
po sačuvanom ID-ju uz proveru baze, datuma i arhive. Obrisani/premešteni red ne
pravi se automatski ponovo. Definitivno odbijen 4xx zahtev oslobađa pokušaj.
Dupli dnevni redovi se odbijaju umesto nasumične izmene; nepoklapanje naziva
Checkbox kolone prijavljuje grešku umesto da tiho proizvede loš skor iz v1.

Statistika sada prati sve stranice (v1 najviše 100), ograničava period na
1–366 dana, izostavlja neispravne/duple datume uz napomenu i navodi broj dana
bez reda. Prosek se i dalje računa samo za postojeće redove. Prag uspešnog dana
je 70%; tekući niz mora završiti poslednjeg dana perioda, umesto da stari niz
iz prošlosti bude prikazan kao tekući. Veze zahtevaju najmanje 3 uparena dana
po grupi sa poznatom ocenom, uz upozorenje da nisu dokaz uzročnosti. Dnevnik je
opcion za statistiku. Interno kreiranje dnevnika podržava vezu `Checklista`
kao v1; automatski zajednički upis i raspored čekaju F1b.8. U ovoj fazi nema
novih zakazanih poruka.

Korisnik je 18.10.2026. na stvarnom nalogu potvrdio 17 konfigurisanih stavki i
nedeljni cilj 4, označavanje obične stavke uz ostale netaknute, upis samo ključne
reči dnevnika pa dopunu raspoloženja i energije bez gubitka teksta, statistiku
za 30 dana sa napomenom o nedovoljno uparenih dnevnika i ponovljeno kreiranje
postojećeg dana bez duplikata. Stvarno kreiranje nedostajućeg reda, prelaz
„Bez…” stavke na true i zaseban poziv `dnevnik_get` nisu izdvojeno ručno
provereni; pokriveni su mock/DB testovima. Automatski poslovi ostaju off.

F1b.5 prenosi svih osam alata iz starog `services/notion.js` i odgovarajuće
opise/kolone. Upsert klijenta prati iste nivoe prepoznavanja: doslovno,
normalizovano, pa skup reči (najmanje dve kod sadržavanja). Tačan naziv ima
prednost nad dužim sličnim nazivom. `client_find` i `client_update` tek potom
pokušavaju podniz; `client_add` ne spaja firme samo na osnovu podniza jedne reči.
Više kandidata ne proizvodi upis. Dopuna čuva naslov i nenavedena polja,
drugačiji dostavljeni naziv smešta u prazno `Naziv za fakturu`, a prazan/null
ulaz preskače kao v1. `dopunjen=false` uz `poruka` može značiti postojeći red
bez novih podataka, kao u v1; nije dokaz da je kreiran novi klijent.

Normalizacija sada radi i nad srpskom ćirilicom; nazivi sa samo pravnim oblikom
se odbijaju umesto pretrage praznog jezgra. PIB/MB ostaju tekst (početne nule
se čuvaju); cena mora biti konačan nenegativan broj, nula se upisuje. Select
opcije su iste kao u v1. Prikaz klijenta dodatno vraća `ponuda`, `elementor`,
`mojHosting` i dva postojeća datuma, bez izmene tih datuma. Paginacija prati sve
klijente pre prepoznavanja; list filter/limit se primenjuju u Notion upitu.
Paralelni add/update pozivi u jednom procesu su serijalizovani po data source-u.
Ovo nije trajna zaštita pri restartu, više procesa ili kašnjenju vidljivosti
Notion upisa: posle neizvesnog create-a prvo proveriti postojeće redove.

Poslovni zadaci čuvaju `Name`/`Status`, podrazumevani `Not started` pri upisu
i sve statuse pri čitanju bez filtera. Limit je 1–100 uz paginaciju; status
može da se promeni samo na aktivnom redu podešenog TASK BOARD-a. KB beleška
ostaje podstranica sa po jednim pasusom za neprazan red. Nova ograničenja su
100000 ulaznih znakova i 1000 pasusa; rich text se deli na do 2000 znakova
posle preslovljavanja, blokovi u grupe do 100. Delimično neuspešna dopuna
vraća link i broj potvrđenih pasusa, bez tvrdnje da je beleška potpuno upisana.
Ne pokreće se automatsko ponovno kreiranje niti reindeksiranje. SYSTEM_PROMPT
ostaje isti; Notion šema i trajno stanje baze nisu menjani.

Ručna provera završena je 18.10.2026: korisnik je potvrdio pregled aktivnih
klijenata i pretragu skraćenog naziva, zatim dodavanje probnog klijenta u Arhivu,
dopunu alternativnim pravnim nazivom bez duplikata i izmenu samo opisa uz
očuvanje naslova, pravnog naziva i statusa. Poslovni TASK BOARD je pročitan,
probni zadatak dodat pa promenjen u Done na istom redu. KB beleška je nastala
na pravom mestu sa oba pasusa. Dvosmisleni nazivi, veliki sadržaj i delimični
HTTP neuspeh ostaju mock provere. Automatski poslovi su isključeni.

F1b.6 prenosi `invoice_create` i `invoice_list`, automatski broj iz FAKTURE,
godišnji prag INVOICE_LAST_NUMBER i isti Montserrat raspored. Klijent dolazi iz
KLIJENTI, izdavalac iz ENV-a bez rezervnih ličnih podataka; model nema argumente
za broj, PIB, MB, račun ni PDF. Nedostajući podaci klijenta ostaju prazni uz
upozorenje kao v1; nedostajući izdavalac blokira izradu sa imenima promenljivih.
Brand je potreban samo ako stvarni logo fajl ne postoji. Privatni logo se ne pakuje.

Registar dobija privatni PDF prilog, posebne oznake dugmadi i strukturisani ishod
potvrde. Stari mejl/kalendar tokovi ostaju tekstualni. Telegram prvo šalje PDF,
zatim dugmad; neuspeh slanja PDF-a ukida potvrdu. Rok je zajedničkih 30 minuta,
umesto v1 sat vremena. Novi predlog oslobađa istekle priloge iz memorije; restart
poništava nacrte. Nacrt/odustanak ne rezervišu broj. Na Sačuvaj se ponovo bira
broj; promenjen broj ponovo crta isti pregledani sadržaj i konačni PDF se šalje
posle arhiviranja. Google/Notion su jedini spoljašnji upisi, isključivo posle dugmeta.

Decimal računanje zaokružuje svaki red na pare pa sabira te iste iznose;
v1 je koristio floating point zbir. Ulaz odbija loše datume, nekonačne/negativne
cene, nepozitivnu količinu i interne/fiskalne argumente. Granice su 50 stavki,
cena do 1e9 RSD, količina do 1e6, ukupno do 1e12 RSD. Predugačka zaglavlja ili
znaci koje Montserrat ne podržava prijavljuju grešku umesto odsečenog dokumenta.
Duži opis se nastavlja na sledećoj strani sa ponovljenim zaglavljem tabele.
Tekst Stavke se više ne seče na 1900 znakova; Notion dobija sve dozvoljene opise.

Potvrđen pokušaj ostavlja kv_state trag po bazi/godini/operaciji; session advisory
lock sprečava dva Dexter procesa da uzmu isti broj i pri kasnoj vidljivosti
Notion reda. Neizvestan pokušaj zadržava broj za ručnu proveru, a ne za ponovno
korišćenje. Drive upload koristi unapred dobijen ID i proveru sadržaja posle
izgubljenog odgovora. Delimičan neuspeh čuva poznati link i ne tvrdi da je sve
izvršeno, za razliku od generičke greške v1. Ne pokreće se automatski drugi upis;
kv_state čuva ishod i preko restarta. Ručni upisi i drugi botovi nisu deo tog lock-a.
`invoice_list` traži samo Notion, zadržava status/limit i paginira do limita.
Šema PostgreSQL-a i SYSTEM_PROMPT nisu menjani.

Posle prvog stvarnog pregleda arhive 18.10.2026. `invoice_list` je dopunjen
imenima iz Notion veze `Klijent` (v1 ih takođe nije vraćao). Čita samo povezane
stranice, jednom po klijentu u tom pozivu, bez dodatnog ENV ID-ja i bez upisa.
Višestruke veze vraćaju listu i napomenu; prazna/nedostupna veza ili nepotpuna
paginacija ne proizvodi izmišljeno ime i ne skriva dostupne podatke fakture.
Korisnik je nakon redeploy-a 18.10.2026. potvrdio imena klijenata u pregledu,
izgled i podatke PDF nacrta, zatim Odbaci uz proveru da nema novog reda/fajla
u Notion-u i na Drive-u. Na kraju je na uputstvo za Sačuvaj tok odgovorio
„Radi”, čime je potvrđeno i stvarno čuvanje. Detalji konačne fakture nisu
dostavljeni niti preneti u repo. Konkurentnost, promena broja i delimične API
greške ostaju pokrivene mock/DB testovima. Automatski poslovi ostaju off.

F1b.7 prenosi sedam alata iz v1: tri za rođendane, dva za sajtove,
generate_report i memory_update. Pročitani su birthdays.js, monitor.js,
monitorHistory.js, reports.js, memory.js, odgovarajući Notion čitači,
tool definicije, README i feature/config uslovi. Migracija 013 uvodi
birthday_greetings i monitor_checks; stari JSON podaci još čekaju F1b.10.

Rođendani čuvaju stare nazive kolona, podatke o osobi, godišnje ponavljanje,
nepoznate godine van opsega 1–119 i vreme iz TIMEZONE. Paginacija obuhvata
sve aktivne redove. Pravilo 29. februar → 28. februar sada važi i za upcoming
(v1 upcoming je kroz Date.UTC mogao pogrešno preći na 1. mart). Neispravan
datum se prijavljuje umesto tihog nestanka osobe. Čestitke imaju jedinstveni
ključ dan/osoba, opstaju kroz reset/restart i čuvaju istoriju umesto rotacije
starog JSON-a na 7 dana. Tačno ime ima prednost nad podnizom; prazan ulaz bira
jedinog slavljenika. Za razliku od v1, pogrešno eksplicitno ime ne označava
automatski drugu osobu samo zato što danas slavi jedina. Više kandidata traži
preciziranje. Helpers za nedelju i nečestitane osobe su spremni za F1b.8.

Monitoring zadržava status <400, prag sporog odgovora i timeout iz istih ENV
promenljivih; prati sve stranice KLIJENTI umesto prvih 100. Paralelnost je
ograničena na 5; telo HTTP odgovora se ne učitava. DNS i svako od najviše pet
preusmeravanja moraju voditi isključivo na javne IP adrese, bez korisničkih
podataka u URL-u. Zahtev koristi proverenu IP uz izvorni Host/SNI i proveru
sertifikata, bez proxy ENV-a i bez deljenja TLS sesije među redirect hostovima.
Ako prva adresa ne može da se poveže, pokušava sledeću javnu adresu u istom roku.
Ovo zatvara rupe stare provere hosta kod DNS-a/preusmeravanja. Jedan loš sajt
vraća svoju grešku; problem sa čuvanjem istorije dodaje jasnu napomenu.

Istorija čuva poslednjih 8000 uzoraka, serijalizovano u transakciji. Dostupnost
prati stari zbir uspešnih uzoraka, sortiranje najlošijih prvo, poslednji problem
i podniz imena sajta. Spor odgovor i dalje umanjuje procenat; rezultat zato
izričito govori da nije reč o neprekidnom uptime merenju. Bez uzoraka vraća
nepoznat procenat, ne 100%. monitor_uptime radi i bez Notion-a jer čita samo DB.

Izveštaj čuva stare argumente i podrazumevane izvore/opseg. TASK BOARD je
trenutno stanje sa do 50 stavki po statusu; dodatni 51. red proverava da li je
lista ograničena. Ne tvrdi da je Done zadatak završen u traženom periodu, jer
datum završetka nije dostupan. Kalendarski opseg se validira, najviše 366 dana;
monitoring ostaje trenutni snimak. Izvori se skupljaju paralelno. Delimične
greške ostavljaju vidljivu napomenu i u sačuvanom tekstu, umesto prekida svih
izvora; bez dostupnog izvora nema poziva modela ni praznog dokumenta. Brzi
model dobija fiksno uputstvo o podacima/neizmišljanju, odvojeno od izvora.
Prekinut ili prazan izlaz se ne čuva. Drive greška vraća tekst i neizvestan
ishod, bez ponavljanja create-a. Google kredencijali i dalje uključuju alat
kao v1, dok saveToDoc=false preskače upis. Učitani podaci imaju granicu 80000
znakova sa eksplicitnim odbijanjem; izlaz modela do 4096 tokena.

memory_update čuva postojeći celobrojni ID iz v2 (v1 je imao kratke string ID-jeve),
izvor i nenavedena polja; tekst i novi vektor idu u jednom UPDATE-u, bez deduplikacije
ili stvaranja novog reda. Samo kategorija ne troši embedding poziv. Nepoznat ID,
prazan tekst, nepoznata kategorija i zahtev bez izmene se odbijaju; v2 kategorija
cilj ostaje dozvoljena. Ne menjaju se SYSTEM_PROMPT, scheduler ni postojeće činjenice.
Ručni glavni tokovi potvrđeni su 18.10.2026. posle redeploy-a: /status prikazuje
sedam alata, rođendani vraćaju danas/uskoro, a korisnik je potvrdio čestitanje
probnoj osobi. Monitoring je proverio 22 sajta, svi HTTP 200, od kojih su dva
bila spora. Istorija je vratila po jedan isti uzorak i 20/22 uspešnih provera,
uz ograničenje da je reč o uzorcima, ne neprekidnom uptime-u.

generate_report je vratio Google Doc link i pregled trenutnog TASK BOARD-a
odvojeno od kalendarskog perioda, bez pretpostavljenog datuma za Done zadatke.
To je potvrđeno prosleđenim rezultatom bota; sadržaj samog dokumenta nije
nezavisno pregledan u ovoj sesiji. memory_update je promenio probni tekst
Alfa → Beta uz isti ID i kategoriju; naknadno učitana lista potvrđuje izmenu.
Prvi paralelni pregled pokazao je staru vrednost, pa za proveru treba čitati
posle završenog upisa. Rubni datumi, reset/restart čestitki, HTTP greške,
delimičan izveštaj i vektori ostaju mock/DB provere. Scheduler ostaje off.

F1b.8 prenosi svih 14 rasporeda iz v1 services/scheduler.js, uz pročitane
motivation.js, jobs.js, config i odgovarajuće servise/opise. Svaki stari cron
ENV ostaje isti, sa TIMEZONE i standardnim Node brojevima dana u nedelji.
Sve akcije idu kroz run_job (do tri pokušaja, 30/60 s, job_runs, završno upozorenje).
Zadržana su i četiri postojeća F2/F6 rasporeda; ukupno do 18, zavisno od integracija.
F6 tišina, povratne informacije i ograničenja nisu prošireni na eksplicitne stare
rasporede u 06:00/23:00. Prvi test deploy koristi isključenu automatiku;
posle provere korisnik je 19.10.2026. uključio scheduler.

Jutarnji pozdrav dobija prognozu i ponedeljkom poznate rođendane te nedelje.
Poslovni pregled dobija lokalni dan iz kalendara (uključujući promenu sata),
In progress i Not started zadatke (15 po statusu uz oznaku ograničenja) i do
15 nepročitanih mejlova; nema prognoze. Nedostupnost jednog izvora ne postaje
izmišljena prazna lista. Checklista i dnevnik nastaju tiho, bez duplih redova;
ako dnevnik već postoji, dopunjava se samo prazna Checklista veza, a konflikt
se odbija. Večernji podsetnik dobija skor, neoznačene stavke, nedeljni cilj,
prazna polja dnevnika i nedeljni lični zadatak. Pohvala koristi zaokružen
procenat ≥ CHECKLIST_PRAISE_THRESHOLD, prema planu (v1 je imao strogo >).
Nedeljna pohvala koristi broj stvarno zabeleženih dana i dinamičan broj navika.
Lični poreski podsetnik ne izmišlja pravni rok, iznos ili dug. Tihi monitoring
šalje samo problem/napomenu; večernji pun izveštaj i prazno stanje. Rođendanski
poslovi ćute bez današnjih/još nečestitanih osoba; ne čestitaju drugoj osobi.

Sve nove generisane poruke koriste MODEL_FAST i zajedničko merenje purpose=scheduler,
sa fiksnim uputstvom odvojenim od sirovih podataka. Motivacija više ne koristi
v1 OpenAI MOTIVATION_MODEL/fallback; poseban ključ nije potreban. Migracija 014
uvodi tabelu motivation_messages sa pripremljenim/poslatim/neizvesnim ishodom.
Poslednjih MOTIVATION_HISTORY tekstova i rotacija 12 uglova ulaze u upit.
Normalizovana sličnost ≥0,85 izaziva ponovni pokušaj generisanja, a ponovljen
tekst se ne šalje. Provera se ponavlja pod DB lock-om pri rezervaciji; posle
uspeha čuvaju se poslednjih N poruka. Neizvesni tekstovi ostaju do sledeće
uspešne rotacije kako ih novi posao ne bi ponovio. Ovo proverava formulaciju,
ne garantuje semantički potpuno novu poentu bez stvarne LLM evaluacije.

Poslovni pregled i satna provera dele prijavljene IMAP UID-jeve u kv_state.
Ključ uključuje nalog, INBOX i UIDVALIDITY, pa promena identiteta sandučeta ne
skriva ponovo upotrebljene brojeve. Čitaju se svi nepročitani UID-jevi, ali
samo 15 najnovijih zaglavlja bez Seen izmene. Evidencija se čisti samo prema
celom nepročitanom skupu, umesto v1 zamene trenutnom listom od 15. Višak starijih
novih poruka čeka da uđe u prikaz. Account advisory lock sprečava da pregled i
satni posao istovremeno prijave iste poruke. Rezervacija nastaje tek uz gotov
tekst, u istoj transakciji sa pokušajem Telegram slanja.

Trajni ključ slanja vezan je za run_job ID; datum početka i ključ ostaju isti
tokom retry-ja. Potvrđen uspeh preskače ponovno generisanje/slanje. Definitivan
Telegram 400/403/429 oslobađa pokušaj i IMAP/motivacionu rezervaciju; mrežna
greška, timeout ili cancel ostavljaju neizvestan pokušaj bez slepog resenda.
To bira izostanak mogućeg duplikata uz potrebu ručne provere isporuke. Završno
upozorenje je zasebna poruka. Novi redovni posao ima svoj ID; ovo nije globalno
zaključavanje rasporeda između dva različita bota. Nedeljni lični zadatak
zadržava raniju zaštitu upisa i obaveštenje samo pri novom redu: ponovni pokušaj
ne pravi drugi red, ali posle greške obaveštenja ne šalje naknadnu potvrdu.
Tragovi drugih slanja rotiraju se na 30 dana. Nema promene SYSTEM_PROMPT-a.
Uvoz stare motivacione/mejl istorije i dalje čeka F1b.10. Prvi redeploy je
proveren sa SCHEDULER_ENABLED=off, zatim je korisnik uključio on.
Produkcioni log 19.10.2026. potvrđuje
18 registrovanih poslova, a /poslovi uspešan zakazani mail_check. Uz privremeni
minutni raspored novi probni mejl je prijavljen; korisnik je ostavio mejl
nepročitan, restartovao Dexter po uputstvu i potvrdio da nema novog obaveštenja.
Zatim je potvrdio vraćanje redovnog MAIL_CHECK_CRON=0 8-22 * * *. Nije nezavisno
očitana udaljena ENV vrednost posle vraćanja. Ostali poslovi i nedeljna pohvala
nisu još pojedinačno potvrđeni na pravim terminima; to nije potvrda kompletnog
operativnog pariteta niti zaštite od upisa drugog bota.

F1b.9 prenosi schema.js i /provera iz services/telegram.js, uz pročitane
startup poziv iz index.js, README i opise Notion alata. Postojeći /status i
/poslovi zadržavaju ponašanje iz F1.4/F1.5, već potvrđeno na pravom botu.
Nova komanda je dostupna samo vlasniku i proverava sedam konfigurisanih baza.
Minimalna očekivana imena/tipovi ostaju kao u v1, uključujući razliku
select/status i proveru FAKTURE bez uslova da je Google Drive podešen.
PIB, telefon i druga opciona polja nisu proizvoljno proglašena obaveznim.

Notion API 2025-09-03 zahteva čitanje properties iz data_source metapodataka;
baza mora imati tačno jedan izvor, kao ostali v2 servisi. Provera ne bira prvi
od više izvora. Ne čita redove, ne upisuje Notion i ne koristi LLM. Dodatno
proverava prazne/ponovljene nazive konfiguracije navika i cilj van praćenog
spiska; Dnevnik zahteva Checklista relation samo kada je i checklista podešena.
Nepraćene checkbox kolone vraća kao nalaz, kao v1. Nedostajuća kolona više se
ne opisuje kao sigurno „uvek neurađena”, jer v2 na nekim čitanjima već odbija
neispravnu šemu. Nepoklapanje ostaje informacija, bez automatske popravke.
Ne proverava sve opcione kolone, select/status opcije ni cilj relation veze.

Do tri baze se čitaju paralelno, po 15 s za bazu i njen izvor; jedan neuspeh
ne skriva ostale nalaze. API/timeout greške imaju stabilan lokalni opis bez
prosleđivanja serverovog teksta, tajni ili privatnih URL-ova. Cancel se ne
pretvara u ispravnu proveru. Izveštaji su latinicom i podeljeni prema Telegram
UTF-16 granici; dugačak nalaz se ne odseca. Ručna komanda ne čita niti menja
poslednji startup otisak. Zdrav prvi start je tih kao v1, pa odgovor na
/provera može potvrditi stanje i kada nije stiglo startup obaveštenje.

Startna provera je zaseban pomoćni async zadatak, nezavisno od SCHEDULER_ENABLED,
sa otkazivanjem pri zaustavljanju aplikacije. Ne blokira polling/scheduler.
kv_state čuva SHA-256 otisak nalaza i stanje slanja, bez nove migracije.
Kanonski otisak ignoriše redosled nalaza/kolona, a PostgreSQL advisory lock
serijalizuje paralelne startove iste instalacije. Nov problem ili promena
problema šalju izveštaj; uklanjanje svih nalaza šalje kratku potvrdu oporavka.
Bez konfigurisanih baza prethodni nalaz ostaje sačuvan, bez lažnog oporavka.

Kao v1, pokušaj se pamti pre slanja da restart petlja ne ponovi upozorenje.
Poboljšanje je da definitivno odbijen prvi deo vraća prethodni otisak i
omogućava naredni start; neizvesno, delimično ili otkazano slanje zadržava novi
otisak i ne ponavlja poruku naslepo. Ručna /provera vraća pun aktuelni nalaz.
Neočekivan neuspeh provere/baze se loguje bez tajni i ne prekida start.
Nema nove ENV promenljive, izmene SYSTEM_PROMPT-a ili broja zakazanih poslova.
Korisnik je 19.10.2026. posle uputstva za redeploy prosledio /provera odgovor
„Notion šeme su u redu (provereno baza: 7).” Zatim je na uputstvo da restartuje
Dexter i sačeka oko minut potvrdio da nije stiglo automatsko obaveštenje.
Time je potvrđen stvarni ručni izveštaj i očekivana tišina za nepromenjen zdrav
nalaz. Nije nezavisno pročitan startup log ili kv_state posle restarta.
Neispravan nalaz, njegova promena i oporavak nisu izazivani na produkcionim
kolonama; ostaju SDK/mock/DB provere. Scheduler ostaje on prema poslednjem
izboru korisnika. Ova dopuna menja samo dokumentaciju.

### Work/Life odredišta — ispravka F7.5 (20.10.2026)

Lični todo_* ostaje Life preko NOTION_TODO_DB_ID, poslovni notion_* zadaci Work
preko NOTION_TASKS_DB_ID. Opisi izričito razlikuju oblasti; nejasan zahtev traži
razjašnjenje. Poslovni servis odbija da oba podešavanja pokazuju na istu bazu.
Novi ugovorni upis koristi poslovnu bazu sa Name/Status/Rok, proverenu preko
Work roditelja, i prikazuje stvarno odredište pre potvrde. Stara implementacija
F7.1 koristila je Life; trajni ključevi i podsetnici ne brišu se radi ponovnog
upisa. Već sačuvan predlog vraća postojeći link bez duplikata, uz napomenu za
proveru/premeštanje. Nema automatske migracije starih zadataka.

/provera liste dopunjuje postojeću /provera komandu: podešene putanje, ID-jevi,
izvori i kolone, uz ograničenu pretragu dostupnih lista i označene delimične
nalaze. Samo metadata GET/search; nema modela ni izmene podešavanja/šeme/redova.
Native UI potvrđuje Work → FIRMA → TASKS i postojeći Rok. Probni ugovorni red
je premešten iz Life u TASKS sa istim page ID-jem, statusom i rokom, bez novog
podsetnika. Raniji F1b.5 poslovni zapis već jeste u Work. Neidentifikovani stariji
zapisi i produkcioni ENV čekaju zasebnu proveru; masovna migracija nije rađena.
