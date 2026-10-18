# Paritet sa starim APU-om

F1b je i dalje nezavršena. Korisnik je izričito tražio Faze 2–6 pre njenog završetka;
novi zadaci ne označavaju stare alate i poslove kao prenete.

| Deo | Python stanje |
|---|---|
| Kalendar: pregled, slobodni termini, zakazivanje | F1b.1: sva tri alata preneta; F6 uvid koristi isti servis. Stvarni nalog čeka proveru posle deploy-a. |
| Lična To-do lista i nedeljni zadatak | F1b.2: tri alata proverena na pravom Notion-u; automatski nedeljni posao čeka uključivanje. |
| Čitanje TASK BOARD-a za uvid | F6.2: Name/Status, opciona nova Date kolona Rok; alati čekaju F1b.5 |
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
