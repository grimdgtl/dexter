"""Model bira čitanje računa, a podatke za upis dobija samo iz pripreme slike."""

from apu import receipts
from apu.tools.registry import tool


@tool(
    "receipt_extract",
    "Čita jednu sliku računa poslatu u tekućoj poruci i priprema rashod za potvrdu. "
    "Pozovi kad korisnik traži izdvajanje ili čuvanje računa. Ne prosleđuj prodavca, "
    "PIB, datum ni iznose: čitaju se isključivo sa slike. Korisnik pregleda sve podatke "
    "i potvrđuje dugmetom; pre toga ništa nije sačuvano. Za staru sliku traži da je ponovo pošalje.",
    confirm=True,
    prepare=receipts.prepare,
    preview=receipts.preview,
    requires=["ANTHROPIC_API_KEY"],
)
async def receipt_extract(args: receipts.ExtractArgs) -> dict:
    return await receipts.save(args)
