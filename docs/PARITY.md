# Paritet sa starim APU-om

F1b je i dalje nezavršena. Korisnik je izričito tražio Faze 2–6 pre njenog završetka;
novi zadaci ne označavaju stare alate i poslove kao prenete.

| Deo | Python stanje |
|---|---|
| Kalendar: pregled, slobodni termini, zakazivanje | F1b.1: sva tri alata preneta; F6 uvid koristi isti servis. Stvarni nalog čeka proveru posle deploy-a. |
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
