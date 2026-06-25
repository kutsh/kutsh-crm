#!/usr/bin/env python3
"""score_collectivites.py — calcule le score ICP des Collectivités (segment B2G).

Rubric data-driven (0-100) à partir des champs déjà enrichis (issue 6pn1), reflétant
la proposition de valeur Kutsh (intelligence PLU/ADS) — cf. doc Outline « ICP, personas
& scoring ». Pondérations :
  - statutDocument : PLUI 40 / PLU 25 / RNU 5  (un document intercommunal numérisable =
    notre cœur de valeur ; RNU = pas de document à exploiter).
  - volumeDossiersAn : ≥200→30, ≥50→20, ≥10→10, >0→5  (activité d'instruction).
  - population : ≥50k→15, ≥10k→10, ≥3,5k→5, >0→2  (capacité / budget).
  - dateDerniereRevision : ≤3 ans→15, ≤6 ans→8, sinon/inconnu→3  (document actif).
Tier : A≥70, B≥50, C≥30, D<30.

Idempotent (ne met à jour que si score/tier changent). DRY-RUN par défaut ; --apply.
Env : TWENTY_API_KEY.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crm_client import TwentyClient  # noqa: E402

_THIS_YEAR = dt.date.today().year


def _score(col: dict[str, Any]) -> int:
    s = {"PLUI": 40, "PLU": 25, "RNU": 5}.get(str(col.get("statutDocument") or ""), 5)
    vol = col.get("volumeDossiersAn") or 0
    s += (
        30
        if vol >= 200
        else 20
        if vol >= 50
        else 10
        if vol >= 10
        else 5
        if vol > 0
        else 0
    )
    pop = col.get("population") or 0
    s += (
        15
        if pop >= 50000
        else 10
        if pop >= 10000
        else 5
        if pop >= 3500
        else 2
        if pop > 0
        else 0
    )
    rev = str(col.get("dateDerniereRevision") or "")[:4]
    if rev.isdigit():
        age = _THIS_YEAR - int(rev)
        s += 15 if age <= 3 else 8 if age <= 6 else 3
    else:
        s += 3
    return min(100, s)


def _tier(score: int) -> str:
    return "A" if score >= 70 else "B" if score >= 50 else "C" if score >= 30 else "D"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--apply", action="store_true", help="écrit dans Twenty (sinon dry-run)"
    )
    a = ap.parse_args()
    c = TwentyClient()
    dist: Counter[str] = Counter()
    stats = {"total": 0, "maj": 0}
    for col in c.list_all("collectivites"):
        stats["total"] += 1
        score = _score(col)
        tier = _tier(score)
        dist[tier] += 1
        if col.get("scoreIcp") == score and col.get("tierIcp") == tier:
            continue
        if a.apply:
            c.update("collectivites", col["id"], {"scoreIcp": score, "tierIcp": tier})
        stats["maj"] += 1
    print(f"{'OK' if a.apply else 'DRY-RUN'} : {stats}")
    print("répartition tiers :", {k: dist[k] for k in ("A", "B", "C", "D")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
