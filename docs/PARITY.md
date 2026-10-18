# Paritet sa starim APU-om

F1b je i dalje nezavršena. Korisnik je izričito tražio Faze 2–6 pre njenog završetka;
novi zadaci ne označavaju stare alate i poslove kao prenete.

| Deo | Python stanje |
|---|---|
| Kalendar: pregled, slobodni termini, zakazivanje | F1b.1: sva tri alata preneta; F6 uvid koristi isti servis. Stvarni nalog čeka proveru posle deploy-a. |
| Lična To-do lista i nedeljni zadatak | F1b.2: tri alata proverena na pravom Notion-u; automatski nedeljni posao čeka uključivanje. |
| Čitanje TASK BOARD-a za uvid | F6.2: Name/Status, opciona nova Date kolona Rok; alati čekaju F1b.5 |
| Mejl: pregled, pretraga, čitanje, folderi, draft i slanje | F1b.3: preneto; IMAP čitanje i draft, očuvan Seen, otkazivanje i potvrđeno Resend slanje provereni na pravom nalogu. SMTP ostaje mock provera. |
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
