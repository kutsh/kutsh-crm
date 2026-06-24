#!/usr/bin/env python3
"""Reclassement des Companies du CRM (issue 1dhk — peuplement des relations).

Deux actions, selon un mapping validé avec Joël :
- PROMOTE : la Company est en fait une Collectivité/Cabinet → on (ré)utilise/crée
  l'objet typé, on y rattache ses contacts (person.{fk}) et deals (opportunity.{fk}),
  on vide leur companyId, puis on supprime la Company devenue doublon.
- CATEGORIZE : la Company reste une Company mais on pose son champ `categorie`
  (cabinet/éditeur/institutionnel/fédération/média/autre). Non destructif.

Les deals ne se relient qu'à Collectivité/Cabinet (pas Éditeur) → seuls
collectivités et cabinets sont promus en objets ; les éditeurs restent Company
catégorisés. DRY-RUN par défaut ; --apply pour écrire. Env : TWENTY_API_KEY.
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, __file__.rsplit("/", 2)[0])
from crm_client import TwentyClient  # noqa: E402  # type: ignore[import-not-found]

# PROMOTE : nom Company -> (objet cible, clé FK person/opp, spec de résolution de l'objet)
#   resolve = ("insee", "<code>") pour réutiliser un objet existant, ou ("create", {champs})
PROMOTE = {
    "Métropole Aix-Marseille-Provence": ("collectivites", "collectiviteId", ("insee", "200054807")),
    "Falaises du Talou": ("collectivites", "collectiviteId",
                          ("create", {"typeCollectivite": "EPCI"})),
    "Urbanis": ("cabinets", "cabinetId", ("create", {})),
    "Ateliers Lion": ("cabinets", "cabinetId", ("create", {})),
}

# CATEGORIZE : nom Company -> valeur du SELECT `categorie`
CATEGORIZE = {
    "Sogefi SIG": "EDITEUR_ADS",
    "Delibia": "AUTRE",  # CivicTech (partenaire potentiel) — cf. Joël
    "Territoire & Habitat Normand": "AUTRE",  # bailleur social — cf. Joël
    "Habitat 76": "AUTRE",  # bailleur social
    "CAUE 76": "INSTITUTIONNEL",
    "Cerema": "INSTITUTIONNEL",
    "FNDI": "FEDERATION_PRO",
    "FIBOIS": "FEDERATION_PRO",
    "Smart City Mag": "MEDIA",
    "Civiteo": "AUTRE",
    "Geosophie": "AUTRE",
    "Realia": "AUTRE",
    "Datactivist": "AUTRE",
    "Mon Territoire": "AUTRE",
    "Samusocial de Paris": "AUTRE",
    "Véranco": "FABRICANT",  # vendeur de vérandas — cible B2B2B (réseau revendeurs) — cf. Joël
    "Mù Fangzi": "AUTRE",
    "ConstructionSalesBoost": "AUTRE",
    "Parsewaves": "AUTRE",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="écrit dans Twenty (sinon dry-run)")
    a = ap.parse_args()
    c = TwentyClient()
    apply = a.apply

    companies = {(x.get("name") or ""): x for x in c.list_all("companies")}
    people = list(c.list_all("people"))
    opps = list(c.list_all("opportunities"))
    print(f"[{'APPLY' if apply else 'DRY-RUN'}] {len(companies)} companies, "
          f"{len(people)} people, {len(opps)} opportunities\n")

    stats = {"promues": 0, "contacts_reliés": 0, "deals_reliés": 0, "categorisees": 0, "supprimees": 0}

    # --- PROMOTE ---
    for name, (obj, fk, resolve) in PROMOTE.items():
        comp = companies.get(name)
        if comp is None:
            print(f"• PROMOTE {name!r} : Company absente (déjà traitée ?) — skip")
            continue
        cid = comp["id"]
        n_p = sum(1 for p in people if p.get("companyId") == cid)
        n_d = sum(1 for o in opps if o.get("companyId") == cid)
        print(f"• PROMOTE {name!r} → {obj} : {n_p} contact(s), {n_d} deal(s), puis suppression Company")
        if not apply:
            continue
        # résoudre / créer l'objet cible
        if resolve[0] == "insee":
            target = c.find_one("collectivites", "codeInseeSiren", resolve[1])
            if target is None:
                print(f"    ⚠ collectivité INSEE/SIREN {resolve[1]} introuvable — skip")
                continue
        else:
            target = c.create(obj, {"name": name, **resolve[1]})
        tid = target["id"]
        for p in people:
            if p.get("companyId") == cid:
                c.update("people", p["id"], {fk: tid, "companyId": None})
                stats["contacts_reliés"] += 1
        for o in opps:
            if o.get("companyId") == cid:
                c.update("opportunities", o["id"], {fk: tid, "companyId": None})
                stats["deals_reliés"] += 1
        c.delete("companies", cid)
        stats["promues"] += 1
        stats["supprimees"] += 1

    # --- CATEGORIZE ---
    for name, cat in CATEGORIZE.items():
        comp = companies.get(name)
        if comp is None:
            print(f"• CATEGORIZE {name!r} : absente — skip")
            continue
        if comp.get("categorie") == cat:
            continue
        print(f"• CATEGORIZE {name!r} → {cat}")
        if apply:
            c.update("companies", comp["id"], {"categorie": cat})
            stats["categorisees"] += 1

    print(f"\n{'OK' if apply else 'DRY-RUN'} : {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
