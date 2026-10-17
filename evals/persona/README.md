# Evaluacija persone

`scenarios.jsonl` sadrži 20 javnih sintetičkih razgovora, očekivano ponašanje,
fiksno referentno vreme i primere za kontrolnu simulaciju. `rubric.json` definiše
pet kriterijuma od 1 do 5: konkretnost, bez izmišljanja, kratkoća, latinica i
primereno neslaganje. Primer odgovora se ne daje stvarnom kandidatu ili sudiji.

Pokreni u zasebnoj `_test`/`_bench` bazi uz obavezne projektne promenljive:

```bash
python -m evals.persona_eval --simulacija --prethodni-ref HEAD --output data/persona-control.json
python -m evals.persona_gate --base HEAD
```

Za stvarno poređenje postavi važeći `ANTHROPIC_API_KEY`, izostavi `--simulacija`
i kao `--prethodni-ref` izaberi Git ref PRE izmene prompta. Za necommitovanu izmenu
obično je to `HEAD`; za već commitovanu izmenu navedi odgovarajući roditeljski/bazni ref.
Komanda ponavlja prethodni i aktuelni prompt na istom skupu, sa istim vremenom,
činjenicama, istorijom i kontrolnim alatima. Kandidat koristi `MODEL_MAIN`, a
sudija `MODEL_DEEP`; budžetsko preusmeravanje sudije na slabiji model odbija merenje.
Rezultati se podrazumevano čuvaju u `evals/persona/results/` i mogu se commitovati
uz promenu prompta. Pre commit-a pregledaj odgovore.

Svi alati su lažni i memorija/istorija su odvojene od stvarnog razgovora. Ne šalju
se mejlovi, ne menjaju spoljni servisi i ne brišu činjenice. Potvrdni alati i dalje
koriste isti mehanizam čekanja na dugme. Stvarno merenje pravi plaćene API pozive
za obe verzije i sudiju; tokeni i `persona_judge` potrošnja ulaze u test bazu.

CI čita stari prompt iz baznog Git ref-a AST parserom, bez izvršavanja starog koda.
Ako se `SYSTEM_PROMPT` promenio, zahteva stvarni pre/posle izveštaj sa odgovarajućim
otiscima promptova, scenarija i rubrike, svih 20 ID-jeva i važećim ocenama.
Simulacija ne može zadovoljiti taj uslov. Nepromenjen prompt ne zahteva API pozive.
CI proverava prisustvo kompletnog poređenja; ocene i eventualni pad kvaliteta
pregledaju se u izveštaju. Trenutni kontrolni prolaz nije ocena stvarne persone.
