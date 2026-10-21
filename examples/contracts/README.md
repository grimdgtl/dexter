# Izmišljeni primeri ugovora

Ovi dokumenti služe demonstraciji obrade skenova. Ne sadrže stvarne ugovorne
strane i nisu namenjeni potpisivanju ili pravnoj upotrebi. Svaka stranica je
označena kao izmišljen test ugovor; PDF ima slike stranica, bez tekstualnog sloja.

| Primer | Namena |
|---|---|
| [Uredan sken](ugovor-uredan-sken.pdf) | Strane, datumi, iznos i obaveza sa konkretnim rokom. |
| [Nepotpun sken](ugovor-nepotpun-sken.pdf) | Nepoznati PIB, rok i naknada; provera da sistem ne dopunjava odsutne podatke. |
| [Uslovni sken](ugovor-uslovni-sken.pdf) | Automatsko produženje i neodređen datum raskida; izostanak bezuslovnog predloga isteka. |

Generator je [scripts/make_contract_examples.py](../../scripts/make_contract_examples.py).
`python -m scripts.make_contract_examples` iz korena repozitorijuma pravi radne
kopije u ignorisanom `output/pdf/`, bez menjanja ovih priloženih primera.

Za offline proveru verifikatora pokreni `python -m evals.contract_eval`.
Za stvarni OCR pošalji Dexteru `/ugovor`, pa jedan od PDF-ova. To koristi
podešene API-je; zadaci se upisuju tek posle pojedinačne potvrde. Za prvu probu
pregledaj izvore i izaberi **Odbaci**.
