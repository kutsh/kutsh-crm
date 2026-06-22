#!/usr/bin/env python3
"""crm_client.py — abstraction de l'API Twenty pour le CRM Kutsh.

Point d'isolation unique vis-à-vis du CRM (cf. cadrage : « si on change de CRM,
on repointe crm_client.py »). S'appuie sur l'API REST de Twenty (/rest/*).

Env : TWENTY_API_KEY (requis), TWENTY_BASE_URL (def https://twenty.kutsh.fr).
Sans dépendances externes (urllib).

Conventions Twenty utiles :
- objets pluriels : people, companies, opportunities, collectivites, pluis,
  cabinets, editeurAds, signals.
- relations : exposées en clé `<relation>Id` (ex. editeurAdsId, pluiId).
- SELECT : valeur en UPPER_SNAKE (ex. COMMUNE, RNU, ELEVEE).
- person.name est composite : {"firstName": ..., "lastName": ...}.
"""
from __future__ import annotations
import os, json, urllib.request, urllib.parse, urllib.error

DEFAULT_BASE = "https://twenty.kutsh.fr"


class TwentyError(RuntimeError):
    pass


class TwentyClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        key = api_key or os.environ.get("TWENTY_API_KEY")
        if not key:
            raise TwentyError("TWENTY_API_KEY manquant (env ou argument)")
        self.api_key: str = key
        self.base = (base_url or os.environ.get("TWENTY_BASE_URL", DEFAULT_BASE)).rstrip("/")

    # --- transport ---
    def _req(self, method: str, path: str, params: dict | None = None, body: dict | None = None):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
            "User-Agent": "kutsh-crm/1.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise TwentyError(f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:300]}")

    # --- CRUD générique ---
    def list(self, object_plural: str, filter: str | None = None, limit: int = 60,
             order_by: str | None = None, depth: int | None = None) -> list[dict]:
        params: dict = {"limit": limit}
        if filter:
            params["filter"] = filter
        if order_by:
            params["order_by"] = order_by
        if depth is not None:
            params["depth"] = depth
        return self._req("GET", f"/rest/{object_plural}", params=params)["data"][object_plural]

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

    def upsert(self, object_plural: str, match_field: str, data: dict, match_value=None) -> dict:
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
        return self.upsert("collectivites", "codeInseeSiren",
                           {"codeInseeSiren": code_insee_siren, "name": name, **fields})

    def find_person(self, first_name: str, last_name: str, email: str | None = None) -> dict | None:
        if email:
            hit = self.find_one("people", "emails.primaryEmail", email)
            if hit:
                return hit
        rows = self.list("people", filter=f"name.firstName[eq]:{first_name},name.lastName[eq]:{last_name}", limit=1)
        return rows[0] if rows else None

    def upsert_contact(self, first_name: str, last_name: str, email: str | None = None, **fields) -> dict:
        data = {"name": {"firstName": first_name, "lastName": last_name}, **fields}
        if email:
            data["emails"] = {"primaryEmail": email}
        existing = self.find_person(first_name, last_name, email)
        if existing:
            return self.update("people", existing["id"], data)
        return self.create("people", data)

    def update_deal(self, deal_id: str, **fields) -> dict:
        return self.update("opportunities", deal_id, fields)

    def create_signal(self, name: str, type_signal: str, action_suggeree: str | None = None,
                       statut: str = "NOUVEAU", **fields) -> dict:
        data = {"name": name, "typeSignal": type_signal, "statut": statut, **fields}
        if action_suggeree:
            data["actionSuggeree"] = action_suggeree
        return self.create("signals", data)


def _selftest():
    c = TwentyClient()
    code = "__selftest_99999__"
    print("1. upsert collectivite…")
    r = c.upsert_collectivite(code, name="__selftest__", population=1, typeCollectivite="COMMUNE")
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
