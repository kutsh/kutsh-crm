#!/usr/bin/env python3
"""Réintègre dans le CRM des contacts landing signalés au Campfire mais absents.

Contrepartie manuelle de `landing/src/lib/twenty.ts` : recrée les fiches People
qui auraient dû l'être si l'intégration landing→Twenty avait existé au moment du
signalement (contacts d'avant l'intégration, ou dont l'upsert avait échoué).

Idempotent (clé naturelle = email) et non destructif : un contact déjà présent
n'est pas recréé ; on complète seulement son `canalAcquisition` s'il est vide.
Le téléphone est parsé comme côté landing (mêmes règles +33).

Entrée : un JSON `[{firstName, lastName, email, phone?}, …]` via `--file`. Le
fichier reste HORS du dépôt (kutsh-crm est public : pas de PII versionnée).

    python scripts/reintegrate_landing_contacts.py --file contacts.json          # dry-run
    python scripts/reintegrate_landing_contacts.py --file contacts.json --apply   # écrit

Env : TWENTY_API_KEY (+ TWENTY_BASE_URL).
"""
from __future__ import annotations
import os, sys, json, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from crm_client import TwentyClient, TwentyError  # noqa: E402  # type: ignore[import-not-found]

CANAL = "LANDING_PAGE"


def parse_phone(phone: str | None) -> dict | None:
    """Normalise un numéro vers un format que Twenty accepte (sinon HTTP 400
    `INVALID_PHONE_NUMBER`).

    Version durcie de `landing/src/lib/twenty.ts` : les numéros du Campfire ont
    été saisis à la main, avec les habitudes françaises que Twenty rejette —
    préfixe international `00` (« 0033… »), et 0 national conservé après `+33`
    (« +330614… »). On ramène tout en E.164 FR : `00`→`+`, puis pour `+33` on
    retire le 0 national. (La landing gagnerait à s'aligner, mais son formulaire
    fournit des numéros déjà propres.)
    """
    if not phone:
        return None
    n = "".join(phone.split())
    if n.startswith("00"):
        n = "+" + n[2:]
    if n.startswith("+33"):
        national = n[3:]
        if national.startswith("0"):
            national = national[1:]
        return {"primaryPhoneNumber": national, "primaryPhoneCallingCode": "+33",
                "primaryPhoneCountryCode": "FR"}
    if n.startswith("0"):  # national FR sans indicatif
        return {"primaryPhoneNumber": n[1:], "primaryPhoneCallingCode": "+33",
                "primaryPhoneCountryCode": "FR"}
    return {"primaryPhoneNumber": n}


def build_payload(contact: dict) -> dict:
    """Construit le corps People à créer (sans effet de bord, testable)."""
    payload: dict = {
        "name": {"firstName": contact.get("firstName") or "",
                 "lastName": contact.get("lastName") or ""},
        "emails": {"primaryEmail": contact["email"]},
        "canalAcquisition": CANAL,
    }
    phones = parse_phone(contact.get("phone"))
    if phones:
        payload["phones"] = phones
    return payload


def _create(c: TwentyClient, contact: dict) -> bool:
    """Crée la fiche ; si Twenty refuse le téléphone, réessaie sans lui.

    Un numéro irrécupérable ne doit pas empêcher la réintégration du contact :
    mieux vaut la fiche sans téléphone que pas de fiche. Retourne True si le
    téléphone a dû être abandonné.
    """
    payload = build_payload(contact)
    try:
        c.create("people", payload)
        return False
    except TwentyError as e:
        if "phones" not in payload or "INVALID_PHONE_NUMBER" not in str(e):
            raise
        payload.pop("phones")
        c.create("people", payload)
        return True


def run(contacts: list[dict], apply: bool) -> dict[str, list]:
    c = TwentyClient()
    buckets: dict[str, list] = {"created": [], "completed": [], "existed": [], "phone_dropped": []}
    for contact in contacts:
        email = contact["email"]
        existing = c.find_one("people", "emails.primaryEmail", email)
        if existing is None:
            if apply:
                if _create(c, contact):
                    buckets["phone_dropped"].append(email)
            buckets["created"].append(email)
        elif not existing.get("canalAcquisition"):
            if apply:
                c.update("people", existing["id"], {"canalAcquisition": CANAL})
            buckets["completed"].append(email)
        else:
            buckets["existed"].append(f"{email} (canal: {existing.get('canalAcquisition')})")
    return buckets


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True, help="JSON [{firstName,lastName,email,phone?}]")
    ap.add_argument("--apply", action="store_true", help="écrit dans Twenty (sinon dry-run)")
    a = ap.parse_args()

    contacts = json.load(open(a.file))
    if not isinstance(contacts, list) or not contacts:
        raise SystemExit("le fichier doit contenir une liste non vide de contacts")
    b = run(contacts, apply=a.apply)

    mode = "APPLIQUÉ" if a.apply else "DRY-RUN (rien écrit)"
    print(f"== Réintégration contacts landing — {mode} ==")
    print(f"  {len(contacts)} contact(s) en entrée")
    print(f"  → créés (canalAcquisition=LANDING_PAGE) : {len(b['created'])}")
    print(f"  → déjà présents, canal complété : {len(b['completed'])}")
    print(f"  → déjà présents, canal déjà posé (intacts) : {len(b['existed'])}")
    if b["phone_dropped"]:
        print(f"  ⚠️  créés SANS téléphone (rejeté par Twenty) : {len(b['phone_dropped'])}")
    for titre, cle in [("Créés", "created"), ("Complétés", "completed"),
                       ("Intacts", "existed"), ("Sans téléphone", "phone_dropped")]:
        if b[cle]:
            print(f"\n  {titre} :")
            for x in b[cle]:
                print(f"    - {x}")
    if not a.apply and (b["created"] or b["completed"]):
        print("\n  → relancer avec --apply pour écrire.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
