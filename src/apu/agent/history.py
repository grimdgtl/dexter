"""Istorija razgovora u Postgresu + pravila koja je čuvaju ispravnom.

Dve lekcije iz stare verzije su ovde pravila u kodu:
  1. Skraćivanje istorije sme da seče SAMO na početku prave korisničke poruke,
     inače `tool_use` ostane bez `tool_result` i API odbije svaki sledeći zahtev.
  2. Presečen odgovor (max_tokens usred alata) ne sme da uđe u istoriju.
     `sanitize` je druga linija odbrane: izbaci nesparene pozive ako ipak uđu.
"""

from apu.db import pool


def is_user_turn(m: dict) -> bool:
    """Prava korisnička poruka (tekst/slika), a ne tool_result koji vraćamo modelu."""
    if m["role"] != "user":
        return False
    c = m["content"]
    if isinstance(c, str):
        return True
    return not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)


def trim_turns(messages: list[dict], max_turns: int) -> list[dict]:
    starts = [i for i, m in enumerate(messages) if is_user_turn(m)]
    if len(starts) <= max_turns:
        return messages[starts[0] :] if starts else []
    return messages[starts[-max_turns] :]


def _tool_use_ids(m: dict) -> set[str]:
    if m["role"] != "assistant" or isinstance(m["content"], str):
        return set()
    return {b["id"] for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_use"}


def _tool_result_ids(m: dict) -> set[str]:
    if m["role"] != "user" or isinstance(m["content"], str):
        return set()
    return {
        b["tool_use_id"]
        for b in m["content"]
        if isinstance(b, dict) and b.get("type") == "tool_result"
    }


def sanitize(messages: list[dict]) -> list[dict]:
    """Izbacuje tool_use bez rezultata i tool_result bez poziva, uz očuvanje ostatka."""
    out: list[dict] = []
    for i, m in enumerate(messages):
        if m["role"] == "assistant":
            calls = _tool_use_ids(m)
            if calls:
                nxt = messages[i + 1] if i + 1 < len(messages) else None
                answered = _tool_result_ids(nxt) if nxt else set()
                if not calls <= answered:
                    # Zadrži samo tekst iz poruke, baci nesparene pozive.
                    text = [b for b in m["content"] if b.get("type") == "text"]
                    if text:
                        out.append({"role": "assistant", "content": text})
                    continue
        if m["role"] == "user" and _tool_result_ids(m):
            prev_calls = _tool_use_ids(out[-1]) if out else set()
            if not _tool_result_ids(m) <= prev_calls:
                continue
        out.append(m)
    return out


async def load(chat_id: int, max_turns: int) -> list[dict]:
    # Uzmi dovoljno redova unazad (jedna razmena sa alatima ima 4+ poruke).
    rows = await pool().fetch(
        """SELECT role, content FROM (
               SELECT id, role, content FROM messages WHERE chat_id = $1
               ORDER BY id DESC LIMIT $2) t ORDER BY id""",
        chat_id, max_turns * 10,
    )  # fmt: skip
    msgs = [{"role": r["role"], "content": r["content"]} for r in rows]
    return sanitize(trim_turns(msgs, max_turns))


async def append(chat_id: int, messages: list[dict]) -> None:
    if messages:
        await pool().executemany(
            "INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3)",
            [(chat_id, m["role"], m["content"]) for m in messages],
        )


async def clear(chat_id: int) -> None:
    await pool().execute("DELETE FROM messages WHERE chat_id = $1", chat_id)
