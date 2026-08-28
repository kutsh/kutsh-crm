#!/usr/bin/env python3
"""recontact.py — moteur de recontact des demandeurs (objets `demande` /
`sollicitation` du CRM Twenty).

Calcule les files de travail du process « qui m'a demandé quoi → accuser
réception → remercier à la livraison », et tamponne les dates de recontact.

Rôle « batch/compute » de la couche Python (ADR 2026-06-23) : ce script CALCULE
les files et ÉCRIT les tampons (`accuseEnvoye` / `remercieEnvoye`) dans Twenty.
Il n'envoie AUCUN message : la rédaction (en joel-style) et la diffusion sur le
canal d'origine (mail, LinkedIn, Basecamp) restent à Claude / kutshbot.

Files calculées :
  - TRIAGE    : sollicitation sans `demande` ou sans `person` (capture brute à
                rattacher — typiquement un retour in-app fraîchement tombé).
  - ACCUSE    : sollicitation sans `accuseEnvoye`, dont la `demande` est encore
                active (À trier / Reçue / En cours) ET RÉCENTE (≤ N jours) — on
                n'accuse pas réception d'un retour vieux de plusieurs semaines.
  - MERCI      : sollicitation sans `remercieEnvoye` dont la `demande` est LIVRÉE
                → remerciement à rédiger, en citant le verbatim.

Usage :
  TWENTY_API_KEY=… python scripts/recontact.py queue [--json] [--ack-max-age-days N]
  TWENTY_API_KEY=… python scripts/recontact.py mark-acked   <sollicitation_id> [--at ISO] --apply
  TWENTY_API_KEY=… python scripts/recontact.py mark-thanked <sollicitation_id> [--at ISO] --apply

Sans --apply, les commandes `mark-*` sont en DRY-RUN (montrent ce qu'elles
feraient). `queue` est en lecture seule.
"""
from __future__ import annotations
import os
import sys
import json
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from crm_client import TwentyClient  # noqa: E402  # type: ignore[import-not-found]

# Statuts de l'objet `demande` (SELECT). Cf. objets créés via la Metadata API.
STATUT_ACTIFS = {"A_TRIER", "RECUE", "EN_COURS"}
STATUT_LIVREE = "LIVREE"
ACK_MAX_AGE_DAYS_DEFAULT = 3


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_iso(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_days(iso: str | None) -> float | None:
    d = _parse_iso(iso)
    if d is None:
        return None
    return (datetime.now(timezone.utc) - d).total_seconds() / 86400.0


def _person_label(person: dict | None) -> str:
    if not person:
        return "(sans contact)"
    name = person.get("name") or {}
    full = " ".join(x for x in (name.get("firstName"), name.get("lastName")) if x).strip()
    company = (person.get("company") or {}).get("name")
    return " ".join(x for x in (full or None, f"[{company}]" if company else None) if x) or "(contact sans nom)"


def _load_sollicitations(client: TwentyClient) -> list[dict]:
    """Récupère toutes les sollicitations avec `demande` et `person` imbriqués
    (depth=1) pour éviter un appel par relation."""
    return client.list_all("sollicitations", depth=1)


def compute_queues(sols: list[dict], ack_max_age_days: float) -> dict:
    triage, accuse, merci = [], [], []
    for s in sols:
        demande = s.get("demande") or None
        person = s.get("person") or None
        statut = (demande or {}).get("statut")

        if demande is None or person is None:
            triage.append(s)
            continue

        if not s.get("remercieEnvoye") and statut == STATUT_LIVREE:
            merci.append(s)

        if (
            not s.get("accuseEnvoye")
            and statut in STATUT_ACTIFS
        ):
            age = _age_days(s.get("dateSollicitation"))
            if age is not None and age <= ack_max_age_days:
                accuse.append(s)
    return {"triage": triage, "accuse": accuse, "merci": merci}


def _brief(s: dict) -> dict:
    """Contexte compact d'une sollicitation, pour la rédaction du message."""
    demande = s.get("demande") or {}
    return {
        "sollicitation_id": s.get("id"),
        "demande_id": demande.get("id"),
        "demande": demande.get("name"),
        "statut": demande.get("statut"),
        "canal": s.get("canal"),
        "date": s.get("dateSollicitation"),
        "contact": _person_label(s.get("person")),
        "email": s.get("emailBrut"),
        "verbatim": s.get("verbatim"),
        "lien_source": (s.get("lienSource") or {}).get("primaryLinkUrl"),
    }


def cmd_queue(client: TwentyClient, args) -> int:
    sols = _load_sollicitations(client)
    q = compute_queues(sols, args.ack_max_age_days)
    briefs = {k: [_brief(s) for s in v] for k, v in q.items()}
    if args.json:
        print(json.dumps(briefs, ensure_ascii=False, indent=2))
        return 0
    titres = {
        "triage": "À TRIER (rattacher contact / demande)",
        "accuse": f"ACCUSÉ DE RÉCEPTION (demande active, ≤ {args.ack_max_age_days} j)",
        "merci": "REMERCIEMENT (demande livrée, non remerciée)",
    }
    for k in ("triage", "accuse", "merci"):
        rows = briefs[k]
        print(f"\n=== {titres[k]} — {len(rows)} ===")
        for b in rows:
            print(f"  • {b['contact']}  ·  {b['canal']}  ·  {b['date'][:10] if b['date'] else '?'}")
            print(f"    demande : {b['demande']}  [{b['statut']}]")
            print(f"    verbatim: « {(b['verbatim'] or '')[:120]} »")
            print(f"    id={b['sollicitation_id']}  email={b['email']}")
    print(
        f"\nRésumé : {len(briefs['triage'])} à trier · "
        f"{len(briefs['accuse'])} accusés · {len(briefs['merci'])} remerciements."
    )
    return 0


def _mark(client: TwentyClient, args, field: str) -> int:
    at = args.at or _now_iso()
    if not args.apply:
        print(f"[DRY-RUN] {field} <- {at} sur sollicitation {args.id} (ajouter --apply pour écrire)")
        return 0
    client.update("sollicitations", args.id, {field: at})
    print(f"OK : {field} = {at} sur sollicitation {args.id}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Moteur de recontact des demandeurs (Twenty).")
    sub = p.add_subparsers(dest="cmd", required=True)

    pq = sub.add_parser("queue", help="Affiche les files triage/accusé/remerciement.")
    pq.add_argument("--json", action="store_true", help="Sortie JSON (pour la rédaction assistée).")
    pq.add_argument("--ack-max-age-days", type=float, default=ACK_MAX_AGE_DAYS_DEFAULT,
                    help=f"Âge max d'un retour pour proposer un accusé (défaut {ACK_MAX_AGE_DAYS_DEFAULT}).")

    pa = sub.add_parser("mark-acked", help="Tamponne accuseEnvoye après envoi de l'accusé.")
    pa.add_argument("id")
    pa.add_argument("--at", help="Horodatage ISO (défaut maintenant).")
    pa.add_argument("--apply", action="store_true")

    pt = sub.add_parser("mark-thanked", help="Tamponne remercieEnvoye après envoi du remerciement.")
    pt.add_argument("id")
    pt.add_argument("--at", help="Horodatage ISO (défaut maintenant).")
    pt.add_argument("--apply", action="store_true")

    args = p.parse_args(argv)
    client = TwentyClient()
    if args.cmd == "queue":
        return cmd_queue(client, args)
    if args.cmd == "mark-acked":
        return _mark(client, args, "accuseEnvoye")
    if args.cmd == "mark-thanked":
        return _mark(client, args, "remercieEnvoye")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
