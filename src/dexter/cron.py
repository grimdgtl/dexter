"""Cron iz stare Node verzije: 0/7 je nedelja, 1 je ponedeljak."""

from apscheduler.triggers.cron import CronTrigger


def trigger(expression: str, timezone: str) -> CronTrigger:
    fields = expression.lower().split()
    if len(fields) != 5:
        raise ValueError("Cron mora imati pet polja: minut sat dan mesec dan-u-nedelji.")
    names = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
    weekday = fields[4]
    for number, name in enumerate(
        ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday")
    ):
        weekday = weekday.replace(name, str(number))
    for number, name in enumerate(names):
        weekday = weekday.replace(name, str(number))
    selected = set()
    for part in weekday.split(","):
        base, *step_text = part.split("/")
        if len(step_text) > 1:
            raise ValueError("Neispravan cron korak dana u nedelji.")
        step = int(step_text[0]) if step_text else 1
        if step < 1:
            raise ValueError("Cron korak mora biti pozitivan.")
        if base == "*":
            first, last = 0, 6
        elif "-" in base:
            first, last = map(int, base.split("-"))
        else:
            first = int(base)
            last = 7 if step_text else first
        if not 0 <= first <= last <= 7:
            raise ValueError("Cron dan u nedelji mora biti između 0 i 7.")
        selected.update(n % 7 for n in range(first, last + 1, step))
    fields[4] = ",".join(names[n] for n in sorted(selected))
    return CronTrigger.from_crontab(" ".join(fields), timezone=timezone)
