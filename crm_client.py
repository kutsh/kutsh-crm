#!/usr/bin/env python3
"""crm_client.py — abstraction de l'API Twenty pour le CRM Kutsh.

Point d'isolation unique vis-à-vis du CRM (cf. cadrage : « si on change de CRM,
on repointe crm_client.py »). S'appuie sur l'API REST de Twenty (/rest/*).

**Module packagé, et seul client Twenty de l'écosystème Kutsh** (kata `jnnf`) :
kutsh-data en portait une réimplémentation divergente sous `scripts/crm_client.py`,
supprimée au profit de ce module. Les consommateurs l'installent :

    uv add "kutsh-crm @ git+https://github.com/kutsh/kutsh-crm.git"

Toute évolution du contrat REST se fait donc ici, une fois — ce qui ne marchait
plus quand il y avait deux copies (un correctif de retry réseau n'avait atterri
que sur l'une des deux).

Env : TWENTY_API_KEY (requis), TWENTY_BASE_URL (def https://twenty.kutsh.fr).
Sans dépendances externes (urllib).

Conventions Twenty utiles :
- objets pluriels : people, companies, opportunities, collectivites, pluis,
  cabinets, editeurAds, signals.
- relations : exposées en clé `<relation>Id` (ex. editeurAdsId, pluiId).
- SELECT : valeur en UPPER_SNAKE (ex. COMMUNE, RNU, ELEVEE) ; les valeurs
  admises de `typeSignal` sont listées dans TYPE_SIGNAL_VALUES.
- person.name est composite : {"firstName": ..., "lastName": ...}.
"""

from __future__ import annotations
import os, json, time, urllib.request, urllib.parse, urllib.error
from collections import deque

DEFAULT_BASE = "https://twenty.kutsh.fr"

# Twenty limite à 100 requêtes / 60 s PAR WORKSPACE (partagé entre tous les
# appelants). On s'auto-throttle sous ce plafond (fenêtre glissante) et on
# retente les 429 (Retry-After) — indispensable quand un batch tourne en
# parallèle (run nationale cabinets, flows Prefect…).
_RATE_LIMIT = 70
_RATE_WINDOW = 60.0
_calls: deque[float] = deque()

# Valeurs autorisées du SELECT `typeSignal` côté Twenty (cf. docs/schema.md).
# Un SELECT refuse toute valeur hors liste : mieux vaut lever ici, avec la liste
# attendue, qu'aller chercher la cause dans un HTTP 400 tronqué à 300 caractères.
TYPE_SIGNAL_VALUES = frozenset(
    {
        "REVISION_PLUI",
        "MARCHE_PUBLIC",
        "POST_LINKEDIN",
        "REFUS_DOSSIER",
        "RENOUVELLEMENT_ADS",
        # Lead entrant qualifié par kutsh-data/scripts/qualify_leads.py. Un Signal
        # plutôt qu'une opportunité : le score trie et présente, il n'engage pas.
        # Le Deal naît d'une décision humaine — la routine précédente convertissait
        # une classification en engagement commercial et a rempli le pipeline à
        # 96 % de deals synthétiques.
        "LEAD_QUALIFIE",
    }
)


def merge_select_options(
    current: list[dict], wanted: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Fusionne les options d'un champ SELECT **sans perdre la valeur des fiches**.

    Twenty identifie une option de SELECT par son `id`. Deux façons de détruire
    de la donnée avec un simple PATCH de métadonnées :

    1. renvoyer une option existante **sans son `id`** — Twenty ne la met pas à
       jour, il la remplace, et les fiches qui la portaient perdent leur valeur ;
    2. **omettre** une option en place — elle est supprimée, même effet.

    D'où cette fusion : on réaligne libellés / couleurs / ordre sur la liste
    déclarée (`wanted`, l'intention versionnée), en réutilisant les `id` en
    place, et on conserve en fin de liste les options présentes dans Twenty mais
    non déclarées, au lieu de les faire disparaître.

    Retourne `(options_à_envoyer, orphelines)`. Les orphelines sont conservées
    dans le premier élément — le second sert à les **signaler** : une option que
    plus aucun code ne déclare est soit un reliquat à retirer à la main (après
    avoir requalifié les fiches), soit le signe que la liste déclarée a dérivé.
    """
    par_valeur = {o.get("value"): o for o in current}
    fusion: list[dict] = []
    for position, opt in enumerate(wanted):
        garde = {**opt, "position": position}
        existante = par_valeur.get(opt["value"])
        if existante and existante.get("id"):
            garde["id"] = existante["id"]
        fusion.append(garde)

    declarees = {o["value"] for o in wanted}
    orphelines = [o for o in current if o.get("value") not in declarees]
    for decalage, opt in enumerate(orphelines):
        fusion.append({
            **{k: opt[k] for k in ("id", "value", "label", "color") if k in opt},
            "position": len(wanted) + decalage,
        })
    return fusion, orphelines


def _retry_after(headers) -> float | None:
    """Délai du header `Retry-After`, en secondes, ou None s'il est inutilisable.

    Twenty renvoie un entier de secondes. La RFC autorise aussi une date HTTP,
    qu'on ne sait pas lire — on retombe alors sur le backoff par défaut plutôt
    que de repartir immédiatement.
    """
    raw = headers.get("Retry-After") if headers else None
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _throttle() -> None:
    now = time.monotonic()
    while _calls and now - _calls[0] > _RATE_WINDOW:
        _calls.popleft()
    if len(_calls) >= _RATE_LIMIT:
        time.sleep(max(0.0, _RATE_WINDOW - (now - _calls[0])) + 0.05)
    _calls.append(time.monotonic())


class TwentyError(RuntimeError):
    pass


class TwentyClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        key = api_key or os.environ.get("TWENTY_API_KEY")
        if not key:
            raise TwentyError("TWENTY_API_KEY manquant (env ou argument)")
        self.api_key: str = key
        self.base = (
            base_url or os.environ.get("TWENTY_BASE_URL", DEFAULT_BASE)
        ).rstrip("/")

    # --- transport ---
    def _req(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        body: dict | None = None,
    ):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(6):
            _throttle()
            req = urllib.request.Request(
                url,
                data=data,
                method=method,
                headers={
                    "Authorization": "Bearer " + self.api_key,
                    "Content-Type": "application/json",
                    "User-Agent": "kutsh-crm/1.0",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                # 429 (rate limit) ou 5xx transitoire → backoff puis retry.
                if e.code in (429, 502, 503, 504) and attempt < 5:
                    delay = _retry_after(e.headers)
                    time.sleep(delay if delay is not None else 20.0)
                    continue
                raise TwentyError(
                    f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:300]}"
                ) from e
            except (urllib.error.URLError, TimeoutError) as e:
                # Erreur réseau transitoire (timeout SSL, connexion coupée) sur un run
                # long → backoff puis retry, sinon un simple blip tue tout le batch.
                if attempt < 5:
                    time.sleep(5)
                    continue
                raise TwentyError(f"{method} {path} -> erreur réseau: {e}") from e
        raise TwentyError(f"{method} {path} -> abandon après retries (réseau/rate limit ?)")

    # --- CRUD générique ---
    def list(
        self,
        object_plural: str,
        filter: str | None = None,
        limit: int = 60,
        order_by: str | None = None,
        depth: int | None = None,
    ) -> list[dict]:
        params: dict = {"limit": limit}
        if filter:
            params["filter"] = filter
        if order_by:
            params["order_by"] = order_by
        if depth is not None:
            params["depth"] = depth
        return self._req("GET", f"/rest/{object_plural}", params=params)["data"][
            object_plural
        ]

    def list_page(
        self,
        object_plural: str,
        limit: int = 60,
        starting_after: str | None = None,
        depth: int = 0,
    ) -> tuple[list[dict], dict]:
        params: dict = {"limit": limit, "depth": depth}
        if starting_after:
            params["starting_after"] = starting_after
        d = self._req("GET", f"/rest/{object_plural}", params=params)
        return d["data"][object_plural], d.get("pageInfo", {})

    def list_all(self, object_plural: str, page_size: int = 60, depth: int = 0):
        """Itère toutes les pages (curseur Twenty) — pour l'export complet."""
        cur = None
        while True:
            rows, pi = self.list_page(
                object_plural, limit=page_size, starting_after=cur, depth=depth
            )
            yield from rows
            if pi.get("hasNextPage") and pi.get("endCursor"):
                cur = pi["endCursor"]
            else:
                return

    def find_one(self, object_plural: str, field: str, value) -> dict | None:
        rows = self.list(object_plural, filter=f"{field}[eq]:{value}", limit=1)
        return rows[0] if rows else None

    def get(self, object_plural: str, record_id: str) -> dict | None:
        return self.find_one(object_plural, "id", record_id)

    def create(self, object_plural: str, data: dict) -> dict:
        d = self._req("POST", f"/rest/{object_plural}", body=data)
        return next(iter(d["data"].values()))

    def update(self, object_plural: str, record_id: str, data: dict) -> dict:
        d = self._req("PATCH", f"/rest/{object_plural}/{record_id}", body=data)
        return next(iter(d["data"].values()))

    def delete(self, object_plural: str, record_id: str) -> dict:
        d = self._req("DELETE", f"/rest/{object_plural}/{record_id}")
        return next(iter(d["data"].values()))

    def upsert(
        self, object_plural: str, match_field: str, data: dict, match_value=None
    ) -> dict:
        """Crée ou met à jour selon match_field (clé naturelle)."""
        mv = match_value if match_value is not None else data.get(match_field)
        if mv is not None:
            existing = self.find_one(object_plural, match_field, mv)
            if existing:
                return self.update(object_plural, existing["id"], data)
        return self.create(object_plural, data)

    # --- conventions CRM (cf. cadrage) ---
    def get_territory(self, code_insee_siren: str) -> dict | None:
        return self.find_one("collectivites", "codeInseeSiren", code_insee_siren)

    def upsert_collectivite(self, code_insee_siren: str, name: str, **fields) -> dict:
        return self.upsert(
            "collectivites",
            "codeInseeSiren",
            {"codeInseeSiren": code_insee_siren, "name": name, **fields},
        )

    def find_person(
        self, first_name: str, last_name: str, email: str | None = None
    ) -> dict | None:
        if email:
            hit = self.find_one("people", "emails.primaryEmail", email)
            if hit:
                return hit
        rows = self.list(
            "people",
            filter=f"name.firstName[eq]:{first_name},name.lastName[eq]:{last_name}",
            limit=1,
        )
        return rows[0] if rows else None

    def upsert_contact(
        self, first_name: str, last_name: str, email: str | None = None, **fields
    ) -> dict:
        data = {"name": {"firstName": first_name, "lastName": last_name}, **fields}
        if email:
            data["emails"] = {"primaryEmail": email}
        existing = self.find_person(first_name, last_name, email)
        if existing:
            return self.update("people", existing["id"], data)
        return self.create("people", data)

    def update_deal(self, deal_id: str, **fields) -> dict:
        return self.update("opportunities", deal_id, fields)

    def create_signal(
        self,
        name: str,
        type_signal: str,
        action_suggeree: str | None = None,
        statut: str = "NOUVEAU",
        **fields,
    ) -> dict:
        if type_signal not in TYPE_SIGNAL_VALUES:
            raise TwentyError(
                f"typeSignal invalide: {type_signal!r} (attendu {sorted(TYPE_SIGNAL_VALUES)})"
            )
        data = {"name": name, "typeSignal": type_signal, "statut": statut, **fields}
        if action_suggeree:
            data["actionSuggeree"] = action_suggeree
        return self.create("signals", data)


def _selftest():
    c = TwentyClient()
    code = "__selftest_99999__"
    print("1. upsert collectivite…")
    r = c.upsert_collectivite(
        code, name="__selftest__", population=1, typeCollectivite="COMMUNE"
    )
    assert r.get("id"), r
    print("   id =", r["id"])
    print("2. get_territory…")
    g = c.get_territory(code)
    assert g and g["id"] == r["id"], g
    print("3. update (upsert idempotent)…")
    r2 = c.upsert_collectivite(code, name="__selftest__", population=2)
    assert r2["id"] == r["id"] and r2["population"] == 2, r2
    print("4. delete (cleanup)…")
    c.delete("collectivites", r["id"])
    assert c.get_territory(code) is None
    print("crm_client selftest OK")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        _selftest()
    else:
        print("usage: TWENTY_API_KEY=… python crm_client.py selftest")
