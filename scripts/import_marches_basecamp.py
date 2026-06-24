#!/usr/bin/env python3
"""Backfill one-shot : importe la veille MARCHÉS PUBLICS passée de Basecamp
(projet Veille 46486516, posts « Marchés publics — … ») en Signaux Twenty.

Pour chaque post marché : crée un Signal MARCHE_PUBLIC (idempotent sur le nom),
crée/retrouve la Collectivité acheteuse (clé = nom normalisé) et relie le signal
à la collectivité (signal.collectivite). Peuple ainsi signaux + relation
Signal→Collectivité depuis l'historique de veille (issues d5td/1dhk).

Lit Basecamp via le CLI `basecamp` (local, authentifié). Écrit Twenty via
crm_client. DRY-RUN par défaut ; --apply pour écrire.
Env : TWENTY_API_KEY (+ TWENTY_BASE_URL).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

sys.path.insert(0, __file__.rsplit("/", 2)[0])
from crm_client import TwentyClient  # noqa: E402  # type: ignore[import-not-found]

VEILLE_PROJECT = "46486516"
SUBJECT_RE = re.compile(r"^Marchés publics\s*[—-]\s*(.+)$")


def _fetch_marche_posts() -> list[dict]:
    out = subprocess.run(
        ["basecamp", "messages", "list", "-p", VEILLE_PROJECT, "--all", "--json"],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out).get("data", [])
    posts = []
    for m in data:
        subj = (m.get("subject") or "").strip()
        if SUBJECT_RE.match(subj):  # « Marchés publics — … » en début de sujet
            posts.append(m)
    return posts


def _buyer_from_subject(subject: str) -> str:
    """Extrait l'acheteur : 'Marchés publics — <acheteur> (détails…)' → <acheteur> normalisé."""
    m = SUBJECT_RE.match(subject)
    raw = (m.group(1) if m else subject).strip()
    raw = raw.split("(")[0].strip()  # retire « (détails, clôture…) »
    raw = re.sub(r"^Opportunit[ée]\s+", "", raw, flags=re.I).strip()  # « Opportunité X » → X
    raw = re.sub(r"^Mairie d[e']\s+", "", raw, flags=re.I).strip()  # « Mairie de X » → X
    return raw


def _is_epci(name: str) -> bool:
    return bool(re.search(r"m[ée]tropole|agglom|communaut[ée]|\bCC\b|\bCA\b|\bCU\b|EPCI", name, re.I))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="écrit dans Twenty (sinon dry-run)")
    a = ap.parse_args()
    c = TwentyClient()
    posts = _fetch_marche_posts()
    print(f"[{'APPLY' if a.apply else 'DRY-RUN'}] {len(posts)} post(s) marché trouvé(s)\n")
    created_sig = created_col = linked = 0
    for m in posts:
        subject = (m.get("subject") or "").strip()
        buyer = _buyer_from_subject(subject)
        url = m.get("app_url") or ""
        typ = "EPCI" if _is_epci(buyer) else "COMMUNE"
        print(f"• {subject}")
        print(f"    acheteur={buyer!r} type={typ}")
        if not a.apply:
            continue
        # 1) collectivité acheteuse (clé = nom ; pas d'INSEE pour les non-watchlist)
        col = c.find_one("collectivites", "name", buyer)
        if col is None:
            col = c.create("collectivites", {"name": buyer, "typeCollectivite": typ})
            created_col += 1
        # 2) signal MARCHE_PUBLIC (idempotent sur le nom = sujet)
        sig = c.find_one("signals", "name", subject)
        if sig is None:
            action = "Analyser le DCE et décider d'une réponse à l'AO."
            if url:
                action += f" (source veille : {url})"
            sig = c.create("signals", {
                "name": subject, "typeSignal": "MARCHE_PUBLIC", "statut": "NOUVEAU",
                "actionSuggeree": action, "collectiviteId": col["id"],
            })
            created_sig += 1
            linked += 1
        elif not sig.get("collectiviteId"):
            c.update("signals", sig["id"], {"collectiviteId": col["id"]})
            linked += 1
    if a.apply:
        print(f"\nOK : {created_sig} signal(aux) créé(s), {created_col} collectivité(s) créée(s), "
              f"{linked} lien(s) signal→collectivité.")
    else:
        print("\n(DRY-RUN — relancer avec --apply pour écrire.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
