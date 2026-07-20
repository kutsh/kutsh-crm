#!/usr/bin/env python3
"""purge_auto_leads.py — retire du pipeline les opportunités fabriquées par
l'ancienne routine `qualify_leads.py` (arrêtée le 2026-07-19).

Contexte : cette routine créait un Deal en PROSPECTION pour *toute* personne sans
opportunité — abonnés newsletter, imports LinkedIn, contacts Campfire compris — à
partir d'une classification LLM faite sur le seul couple (nom, domaine mail). Le
pipeline s'est retrouvé à ~96 % de deals synthétiques, ce qui lui retire toute
valeur de mesure.

Critères de suppression (conjonction, volontairement stricte) :
  - ``name`` commence par ``Lead — `` (préfixe posé par la routine) ;
  - ``stage`` toujours à ``PROSPECTION`` (personne ne l'a fait avancer) ;
  - ``createdBy.name`` == ``claude`` (créé par l'API, pas à la main) ;
  - ``updatedBy.name`` == ``claude`` (jamais retouché depuis).

Tout ce qui porte le préfixe mais échoue un des trois derniers critères est classé
SUSPECT et **jamais supprimé** : c'est le cas d'un deal auto-généré qu'un humain a
ensuite fait vivre, et qui est donc devenu réel. Le reste est intact.

Les Notes « Qualification — … » produites par la même routine sont listées et
supprimées avec les deals (``--with-notes``), sinon elles restent orphelines sur
les fiches contact.

DRY-RUN par défaut (écrit un CSV, ne touche à rien) ; ``--apply`` pour supprimer.
Env : TWENTY_API_KEY, TWENTY_BASE_URL.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crm_client import TwentyClient, TwentyError  # noqa: E402

AUTO_PREFIX = "Lead — "
AUTO_NOTE_PREFIX = "Qualification — "
AUTO_AUTHOR = "claude"


def _author(rec: dict[str, Any], field: str) -> str:
    return ((rec.get(field) or {}).get("name") or "").strip().lower()


def classify(opp: dict[str, Any]) -> str:
    """AUTO (supprimable) | SUSPECT (préfixe mais touché) | KEEP (hors périmètre)."""
    if not (opp.get("name") or "").startswith(AUTO_PREFIX):
        return "KEEP"
    if opp.get("stage") != "PROSPECTION":
        return "SUSPECT"
    if _author(opp, "createdBy") != AUTO_AUTHOR:
        return "SUSPECT"
    if _author(opp, "updatedBy") != AUTO_AUTHOR:
        return "SUSPECT"
    return "AUTO"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="supprime (sinon dry-run)")
    ap.add_argument(
        "--with-notes",
        action="store_true",
        help="supprime aussi les Notes « Qualification — … » de la routine",
    )
    ap.add_argument(
        "--out",
        default="purge_auto_leads_report.csv",
        help="chemin du rapport CSV (dry-run comme apply)",
    )
    a = ap.parse_args()
    mode = "APPLY" if a.apply else "DRY-RUN"
    c = TwentyClient()

    print(f"[{mode}] lecture des opportunités…")
    opps = list(c.list_all("opportunities", depth=0))
    buckets: dict[str, list[dict]] = {"AUTO": [], "SUSPECT": [], "KEEP": []}
    for o in opps:
        buckets[classify(o)].append(o)

    print(f"  {len(opps)} opportunités : ", end="")
    print(
        f"{len(buckets['AUTO'])} AUTO (supprimables), "
        f"{len(buckets['SUSPECT'])} SUSPECT (conservées, à revoir), "
        f"{len(buckets['KEEP'])} hors périmètre"
    )
    print("  stages conservés :", dict(Counter(
        o.get("stage") for o in buckets["SUSPECT"] + buckets["KEEP"]
    )))
    print("  segments AUTO :", dict(Counter(o.get("segment") for o in buckets["AUTO"])))

    notes = []
    if a.with_notes:
        notes = [
            n
            for n in c.list_all("notes", depth=0)
            if (n.get("title") or "").startswith(AUTO_NOTE_PREFIX)
            and _author(n, "createdBy") == AUTO_AUTHOR
        ]
        print(f"  {len(notes)} note(s) « {AUTO_NOTE_PREFIX}… » associée(s)")

    out = Path(a.out)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["verdict", "id", "nom", "stage", "segment", "créé le", "créé par", "modifié par"])
        for verdict in ("AUTO", "SUSPECT", "KEEP"):
            for o in buckets[verdict]:
                w.writerow([
                    verdict,
                    o.get("id"),
                    o.get("name"),
                    o.get("stage"),
                    o.get("segment") or "",
                    (o.get("createdAt") or "")[:10],
                    _author(o, "createdBy"),
                    _author(o, "updatedBy"),
                ])
    print(f"  rapport : {out.resolve()}")

    if not a.apply:
        print(
            f"\n(DRY-RUN — rien supprimé. {len(buckets['AUTO'])} deal(s) "
            + (f"+ {len(notes)} note(s) " if a.with_notes else "")
            + "seraient supprimés. Relancer avec --apply.)"
        )
        return 0

    deleted = 0
    for o in buckets["AUTO"]:
        try:
            c.delete("opportunities", o["id"])
            deleted += 1
        except TwentyError as e:
            print(f"  ⚠ échec suppression {o.get('name')!r} : {e}")
    notes_deleted = 0
    for n in notes:
        try:
            c.delete("notes", n["id"])
            notes_deleted += 1
        except TwentyError as e:
            print(f"  ⚠ échec suppression note {n.get('title')!r} : {e}")

    print(f"\nOK : {deleted}/{len(buckets['AUTO'])} deal(s) supprimé(s)", end="")
    print(f", {notes_deleted}/{len(notes)} note(s)." if a.with_notes else ".")
    print(f"Pipeline restant : {len(opps) - deleted} opportunité(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
