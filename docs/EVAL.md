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
