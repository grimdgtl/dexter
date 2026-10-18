# Paritet sa starim APU-om

F1b je i dalje nezavršena. Korisnik je izričito tražio Faze 2–6 pre njenog završetka;
novi zadaci ne označavaju stare alate i poslove kao prenete.

| Deo | Python stanje |
|---|---|
| Kalendar: pregled, slobodni termini, zakazivanje | F1b.1: sva tri alata preneta; F6 uvid koristi isti servis. Stvarni nalog čeka proveru posle deploy-a. |
| Lična To-do lista i nedeljni zadatak | F1b.2: tri alata, iste kolone/enum vrednosti, cron i rok; pravi Notion čeka proveru posle deploy-a. |
| Čitanje TASK BOARD-a za uvid | F6.2: Name/Status, opciona nova Date kolona Rok; alati čekaju F1b.5 |
| Čitanje nepročitanog INBOX-a za uvid | F6.2: read-only/PEEK; ostali mejl alati čekaju F1b.3 |
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
