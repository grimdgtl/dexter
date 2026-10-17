# Privatna evaluacija glasa

Snimci još nisu pripremljeni. Za stvarno merenje dodaj 20 svojih snimaka i
`manifest.jsonl`, po jedan red za svaki snimak, prema `manifest.example.jsonl`.
Polje `tekst` je ručni prepis onoga što je zaista izgovoreno, bez popravljanja govora.
Prazan tekst koristi samo za namerno označenu tišinu.

Snimci moraju biti unutar ovog foldera ili foldera zasebno zadatog manifesta.
Fajlovi i pravi manifest su izostavljeni iz git-a i Docker konteksta.

Pokreni `python -m evals.voice_eval` uz `.[local,dev]`. `--manifest` može pokazivati
na drugi privatni folder. API se preskače ako nema OPENAI_API_KEY; izbor
`--modeli small medium` sve obrađuje lokalno. Lokalni modeli se preuzimaju pri prvom radu.
Izveštaj u `data/voice-results.json` sadrži samo zbirne metrike i otisak korpusa,
bez transkripata. WER se računa posle preslovljavanja, uklanjanja interpunkcije i
ujednačavanja veličine slova. Vreme učitavanja modela je odvojeno od transkripcije.

Ne biraj najbolji model na istom skupu koji kasnije koristiš kao konačni test.
Rezultati iz lažnih audio testova ne predstavljaju kvalitet govornog modela.
