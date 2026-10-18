# Paritet sa starim APU-om

F1b je i dalje nezavršena. Korisnik je izričito tražio Faze 2–6 pre njenog završetka;
novi zadaci ne označavaju stare alate i poslove kao prenete.

| Deo | Python stanje |
|---|---|
| Kalendar: pregled, slobodni termini, zakazivanje | F1b.1: sva tri alata preneta; F6 uvid koristi isti servis. Stvarni nalog čeka proveru posle deploy-a. |
| Lična To-do lista i nedeljni zadatak | F1b.2: tri alata proverena na pravom Notion-u; automatski nedeljni posao čeka uključivanje. |
| Klijenti, TASK BOARD i upis Knowledge Base beleške | F1b.5: osam alata preneto; pregled, pretraga, dodavanje/dopuna/izmena klijenta, poslovni zadatak i KB podstranica potvrđeni na pravom nalogu. |
| Fakture: priprema PDF-a, potvrda, Drive i arhiva | F1b.6: oba alata i PDF tok implementirani; mock/DB i vizuelne provere, stvarni nalog čeka deploy. |
| Mejl: pregled, pretraga, čitanje, folderi, draft i slanje | F1b.3: preneto; IMAP čitanje i draft, očuvan Seen, otkazivanje i potvrđeno Resend slanje provereni na pravom nalogu. SMTP ostaje mock provera. |
| Checklista, dnevnik i statistika navika | F1b.4: šest alata preneto; korisnik potvrdio pregled, upis, dnevnik, statistiku i postojeći red bez duplikata na pravom Notion-u. |
| Nedeljna pohvala navika u 22:00 | Čeka checklistu i F1b.8; novi pregled u 20:00 je zaseban posao |

Ovo je evidencija razlika nastalih radom van redosleda F1b. Konačna tabela svih 46
alata, 14 poslova i komandi ostaje zadatak F1b.11; ova tabela nije potvrda punog pariteta.

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
Šema PostgreSQL-a i SYSTEM_PROMPT nisu menjani. Stvarni nalog još čeka ručnu proveru.
