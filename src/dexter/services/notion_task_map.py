"""Odredišta zadataka se proveravaju čitanjem metapodataka, bez upisa ili LLM-a."""

from uuid import UUID

from dexter.config import settings
from dexter.pismo import u_latinicu
from dexter.services import notion

MAX_SOURCES = 50


class Inspector:
    def __init__(self, api):
        self.api = api
        self.cache = {}

    async def get(self, kind, identity):
        identity = str(UUID(identity))
        key = (kind, identity)
        if key not in self.cache:
            endpoint = {
                "page": self.api.pages,
                "database": self.api.databases,
                "data_source": self.api.data_sources,
                "block": self.api.blocks,
            }[kind]
            self.cache[key] = await endpoint.retrieve(**{f"{kind}_id": identity})
        return self.cache[key]

    async def path(self, obj):
        labels, seen, complete = [], set(), False
        for _ in range(12):
            identity = (obj.get("object"), obj.get("id"))
            if identity in seen:
                break
            seen.add(identity)
            title = notion.title_of(obj)
            if not labels or labels[-1] != title:
                labels.append(title)
            parent = obj.get("parent", {})
            if parent.get("type") == "workspace" and parent.get("workspace"):
                complete = True
                break
            kind = parent.get("type", "").removesuffix("_id")
            if kind not in {"page", "database", "data_source", "block"}:
                break
            try:
                obj = await self.get(kind, parent[f"{kind}_id"])
            except Exception:
                break
        scopes = {label.casefold().strip() for label in labels} & {"work", "life"}
        scope = next(iter(scopes)).title() if len(scopes) == 1 else "nije potvrđeno"
        prefix = "" if complete else "[deo putanje nije dostupan] → "
        return prefix + " → ".join(reversed(labels)), scope

    async def database(self, identity):
        database = await self.get("database", identity)
        path, scope = await self.path(database)
        sources = []
        for source in database.get("data_sources", []):
            schema = await self.get("data_source", source["id"])
            props = schema.get("properties", {})
            sources.append(
                {
                    "id": source["id"],
                    "kolone": {name: prop.get("type", "nepoznato") for name, prop in props.items()},
                }
            )
        return {"id": str(UUID(identity)), "putanja": path, "oblast": scope, "izvori": sources}


async def inspect() -> dict:
    cfg = settings()
    if not cfg.notion_api_key:
        return {"greska": "Nedostaje NOTION_API_KEY."}
    configured, candidates, errors = [], [], []
    incomplete = False
    async with notion.client() as api:
        reader = Inspector(api)
        for label, identity in (
            ("Work / NOTION_TASKS_DB_ID", cfg.notion_tasks_db_id),
            ("Life / NOTION_TODO_DB_ID", cfg.notion_todo_db_id),
        ):
            if not identity:
                configured.append({"podesavanje": label, "greska": "Nije podešeno."})
                continue
            try:
                configured.append({"podesavanje": label, **await reader.database(identity)})
            except Exception as exc:
                configured.append({"podesavanje": label, "greska": type(exc).__name__})
        cursor, seen, count, databases = None, set(), 0, set()
        try:
            while count < MAX_SOURCES:
                response = await api.search(
                    filter={"property": "object", "value": "data_source"},
                    page_size=min(100, MAX_SOURCES - count),
                    **({"start_cursor": cursor} if cursor else {}),
                )
                for result in response["results"]:
                    count += 1
                    if result.get("in_trash") or result.get("archived"):
                        continue
                    identity = result.get("parent", {}).get("database_id")
                    if not identity or identity in databases:
                        continue
                    databases.add(identity)
                    try:
                        candidate = await reader.database(identity)
                        if any(
                            "title" in s["kolone"].values() and "status" in s["kolone"].values()
                            for s in candidate["izvori"]
                        ):
                            candidates.append(candidate)
                    except Exception as exc:
                        errors.append(type(exc).__name__)
                incomplete = bool(response.get("has_more"))
                if not incomplete:
                    break
                cursor = response.get("next_cursor")
                if not cursor or cursor in seen:
                    raise ValueError("Neispravna paginacija metapodataka.")
                seen.add(cursor)
        except Exception as exc:
            incomplete = True
            errors.append(type(exc).__name__)
    return {
        "podeseno": configured,
        "dostupne_liste": candidates,
        "nepotpun_pregled": incomplete,
        "greske": sorted(set(errors)),
    }


def format_report(result: dict) -> str:
    if result.get("greska"):
        return result["greska"]
    lines = ["Notion liste — samo čitanje; ništa nije menjano."]

    def add(item):
        if item.get("greska"):
            lines.append("⚠️ " + item["greska"])
            return
        lines.extend(
            [
                f"Putanja: {item['putanja']}",
                f"Oblast: {item['oblast']}",
                f"Baza: {item['id']}",
                f"Link: https://www.notion.so/{item['id'].replace('-', '')}",
            ]
        )
        for source in item["izvori"]:
            lines.append(f"Izvor: {source['id']}")
            lines.append("Kolone: " + ", ".join(f"{k} ({v})" for k, v in source["kolone"].items()))

    for item in result["podeseno"]:
        lines.append("\nPodešeno: " + item["podesavanje"])
        add(item)
        expected = item["podesavanje"].split(" / ")[0]
        if item.get("oblast") in {"Work", "Life"} and item["oblast"] != expected:
            lines.append("⚠️ Podešeno odredište pripada drugoj oblasti.")
    lines.append("\nDostupne liste sa naslovom i statusom:")
    for item in result["dostupne_liste"]:
        add(item)
    if result["nepotpun_pregled"] or result["greske"]:
        lines.append(
            f"⚠️ Pregled je delimičan (najviše {MAX_SOURCES} izvora). Ne bira se baza automatski."
        )
    lines.append(
        "Prikazane su izvorne baze; povezani prikazi na drugim stranicama nisu zasebne baze."
    )
    return u_latinicu("\n".join(lines))
