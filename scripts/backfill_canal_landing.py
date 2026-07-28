#!/usr/bin/env python3
"""Backfill `canalAcquisition=LANDING_PAGE` sur les contacts venus de la landing.

Source de vérité de la liste : les signalements `📬 Nouveau contact landing page`
postés par kutshbot dans le Campfire « Prospects et partenaires ». Ce script ne
parle PAS à Basecamp (pas de couplage) : on lui passe la liste d'emails extraite
du Campfire, une par ligne, via `--emails-file` (ou stdin).

    # extraction (hors de ce dépôt) :
    basecamp chat messages --in 46108107 --limit 500 \
      --jq '.data[] | select((.content//"")|test("Nouveau contact landing")) | (.content//"")' \
      | grep -oiE 'mailto:[^"]+' | sed 's/^mailto://I' | sort -u > landing_emails.txt

    python scripts/backfill_canal_landing.py --emails-file landing_emails.txt          # dry-run
    python scripts/backfill_canal_landing.py --emails-file landing_emails.txt --apply   # écrit

Idempotent : ne réécrit pas un contact déjà en LANDING_PAGE. Prudent : si un
contact porte DÉJÀ un autre canal, on ne l'écrase pas en silence — on le signale
comme conflit (à trancher à la main, ou `--force` pour imposer LANDING_PAGE).

Env : TWENTY_API_KEY (+ TWENTY_BASE_URL).
"""
from __future__ import annotations
import os, sys, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from crm_client import TwentyClient  # noqa: E402  # type: ignore[import-not-found]

VALUE = "LANDING_PAGE"


def plan_update(person: dict | None, value: str = VALUE, force: bool = False) -> str:
    """Décide l'action pour un contact, sans effet de bord (cœur testable).

    Retourne l'un de : "not_found", "already", "conflict", "set".
    - not_found : email absent du CRM (rien à faire ici — le lead landing n'a
      pas été créé, ou l'a été sous un autre email).
    - already   : le contact porte déjà `value` → no-op (idempotence).
    - conflict  : le contact porte un AUTRE canal non vide → on n'écrase pas
      (sauf `force`, qui bascule alors en "set").
    - set       : canal vide → à renseigner.
    """
    if person is None:
        return "not_found"
    actuel = person.get("canalAcquisition")
    if actuel == value:
        return "already"
    if actuel and not force:
        return "conflict"
    return "set"


def run(emails: list[str], apply: bool, force: bool) -> dict[str, list]:
    c = TwentyClient()
    buckets: dict[str, list] = {"set": [], "already": [], "conflict": [], "not_found": []}
    for email in emails:
        person = c.find_one("people", "emails.primaryEmail", email)
        action = plan_update(person, force=force)
        if action == "set":
            label = email
            if apply:
                c.update("people", person["id"], {"canalAcquisition": VALUE})
            buckets["set"].append(label)
        elif action == "conflict":
            buckets["conflict"].append(f"{email} (canal actuel: {person.get('canalAcquisition')})")
        elif action == "already":
            buckets["already"].append(email)
        else:
            buckets["not_found"].append(email)
    return buckets


def _read_emails(path: str | None) -> list[str]:
    raw = open(path) if path else sys.stdin
    with raw as fh:
        seen, out = set(), []
        for line in fh:
            e = line.strip().lower()
            if e and not e.startswith("#") and e not in seen:
                seen.add(e)
                out.append(e)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--emails-file", help="fichier d'emails (un par ligne) ; défaut : stdin")
    ap.add_argument("--apply", action="store_true", help="écrit dans Twenty (sinon dry-run)")
    ap.add_argument("--force", action="store_true", help="écrase un canal existant différent")
    a = ap.parse_args()

    emails = _read_emails(a.emails_file)
    if not emails:
        raise SystemExit("aucun email en entrée")
    b = run(emails, apply=a.apply, force=a.force)

    mode = "APPLIQUÉ" if a.apply else "DRY-RUN (rien écrit)"
    print(f"== Backfill canalAcquisition=LANDING_PAGE — {mode} ==")
    print(f"  {len(emails)} email(s) en entrée")
    print(f"  → à renseigner : {len(b['set'])}")
    print(f"  → déjà LANDING_PAGE : {len(b['already'])}")
    print(f"  → conflit (autre canal, NON touché) : {len(b['conflict'])}")
    print(f"  → introuvables dans le CRM : {len(b['not_found'])}")
    for titre, cle in [("Renseignés", "set"), ("Conflits", "conflict"), ("Introuvables", "not_found")]:
        if b[cle]:
            print(f"\n  {titre} :")
            for x in b[cle]:
                print(f"    - {x}")
    if not a.apply and b["set"]:
        print("\n  → relancer avec --apply pour écrire.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
