#!/usr/bin/env python3
"""import_prescripteurs.py — charge les relais/prescripteurs nommés du commentaire
de cadrage Basecamp (recording 9869940877) comme Entreprises typées dans Twenty.

On ne crée que des **organisations réelles et nommées** (fédérations, ordres,
réseaux identifiés). Les segments génériques cités (réseaux de franchisés habitat,
d'entrepreneurs BTP, BIM, courtiers travaux, top voice…) restent des *catégories*
(RESEAU_PRO / COURTIER_TRAVAUX / AGENCE_IMMO…) à remplir au fil des contacts —
pas de fiche fourre-tout.

Idempotent (upsert par nom via crm_client). Env : TWENTY_API_KEY.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crm_client import TwentyClient  # noqa: E402

# (nom, domaine, catégorie) — domaine omis quand non vérifié.
PRESCRIPTEURS: list[tuple[str, str, str]] = [
    ("Société Française des Urbanistes", "urbaniste.com", "FEDERATION_PRO"),
    ("Fédération Nationale des Agences d'Urbanisme", "fnau.org", "FEDERATION_PRO"),
    ("Ordre des Architectes", "architectes.org", "FEDERATION_PRO"),
    ("Syndicat de l'Architecture", "", "FEDERATION_PRO"),
    ("Réseau des ENSA (écoles d'architecture)", "", "ACADEMIQUE"),
    ("IAD France", "iadfrance.fr", "AGENCE_IMMO"),
]


def main() -> int:
    c = TwentyClient()
    n = 0
    for name, domain, categorie in PRESCRIPTEURS:
        data: dict = {"name": name, "categorie": categorie}
        if domain:
            data["domainName"] = {
                "primaryLinkUrl": f"https://{domain}",
                "primaryLinkLabel": domain,
            }
        rec = c.upsert("companies", "name", data)
        n += 1
        print(f"  {name} [{categorie}] -> {rec['id'][:8]}")
    print(f"\nOK : {n} prescripteurs/relais upsertés")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
