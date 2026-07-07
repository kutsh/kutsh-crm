#!/usr/bin/env python3
"""enrich_newsletter_contacts.py — enrichit Twenty avec les contacts externes issus
des échanges Basecamp récents, validés manuellement (2026-07-07).

Pour chaque contact : upsert d'une Company (clé = nom, avec `categorie`) + upsert de
la Person (clé = email) reliée à la Company (`companyId`) et taguée `newsletterSegment`
(override explicite pour la synchro Brevo). Idempotent. DRY-RUN par défaut ; --apply
pour écrire. Env : TWENTY_API_KEY (+ TWENTY_BASE_URL).

Segments : COLLECTIVITES / PROS / ECOSYSTEME. segment=None => créé dans le CRM mais
hors newsletter (orgs non identifiées, à segmenter plus tard).
"""
from __future__ import annotations
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from crm_client import TwentyClient  # noqa: E402  # type: ignore[import-not-found]

# email, first, last, société, categorie(Company), newsletterSegment(Person|None)
CONTACTS = [
    ("arnaud.dawidowicz@ville-cannes.fr", "Arnaud", "Dawidowicz", "Ville de Cannes", "COLLECTIVITE_EPCI", "COLLECTIVITES"),
    ("chloe.klein@normandie-incubation.com", "Chloé", "Klein", "Normandie Incubation", "INSTITUTIONNEL", "ECOSYSTEME"),
    ("clemence.bury@normandie-incubation.com", "Clémence", "Bury", "Normandie Incubation", "INSTITUTIONNEL", "ECOSYSTEME"),
    ("clemence.grincourt@normandie-incubation.com", "Clémence", "Grincourt", "Normandie Incubation", "INSTITUTIONNEL", "ECOSYSTEME"),
    ("alexandre.pauchet@insa-rouen.fr", "Alexandre", "Pauchet", "INSA Rouen", "ACADEMIQUE", "ECOSYSTEME"),
    ("simon.bernard@univ-rouen.fr", "Simon", "Bernard", "Université de Rouen", "ACADEMIQUE", "ECOSYSTEME"),
    ("maxime.parlier@iadfrance.fr", "Maxime", "Parlier", "IAD France", "AGENCE_IMMO", "PROS"),
    ("projet@urbadirect.fr", "", "", "UrbaDirect", "CABINET", "PROS"),
    ("camille.urbadirect@gmail.com", "Camille", "", "UrbaDirect", "CABINET", "PROS"),
    ("np@jumea-conseils.fr", "", "", "Jumea Conseils", "CABINET", "PROS"),
    # Vraiment Vraiment — partenaire, routé Écosystème par override explicite.
    ("alexandra@vraimentvraiment.com", "Alexandra", "", "Vraiment Vraiment", "AUTRE", "ECOSYSTEME"),
    ("louis.c@vraimentvraiment.com", "Louis", "Castel", "Vraiment Vraiment", "AUTRE", "ECOSYSTEME"),
    ("romain@vraimentvraiment.com", "Romain", "Beaucher", "Vraiment Vraiment", "AUTRE", "ECOSYSTEME"),
    ("salome@vraimentvraiment.com", "Salomé", "Hallensleben", "Vraiment Vraiment", "AUTRE", "ECOSYSTEME"),
    # Orgs non identifiées — créées hors newsletter (segment None).
    ("remi@kohortz.fr", "Rémi", "", "Kohortz", "AUTRE", None),
    ("yoan@manufacture-osint.fr", "Yoan", "", "Manufacture OSINT", "AUTRE", None),
    ("pascal@mufangzi.fr", "Pascal", "", "Mufangzi", "AUTRE", None),
    ("maeva.aletas@value-park.com", "Maëva", "Aletas", "Value Park", "AUTRE", None),
    ("alexandre@so-infinity.com", "Alexandre", "", "So Infinity", "AUTRE", None),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="écrit dans Twenty (sinon dry-run)")
    a = ap.parse_args()
    c = TwentyClient()
    company_ids: dict[str, str] = {}

    for email, first, last, org, categorie, segment in CONTACTS:
        tag = f"[{segment or 'hors NL'}]"
        if not a.apply:
            print(f"  DRY {tag:<14} {email:<42} {org}")
            continue
        # 1) Company (upsert par nom), catégorie posée seulement si absente
        if org not in company_ids:
            existing = c.find_one("companies", "name", org)
            if existing:
                cid = existing["id"]
                if not existing.get("categorie") and categorie:
                    c.update("companies", cid, {"categorie": categorie})
            else:
                cid = c.create("companies", {"name": org, "categorie": categorie})["id"]
            company_ids[org] = cid
        cid = company_ids[org]
        # 2) Person — upsert PAR EMAIL directement (clé naturelle). On évite
        #    volontairement crm_client.upsert_contact : son fallback par nom
        #    échoue sur les inboxes génériques (prénom/nom vides -> filtre invalide).
        data = {"name": {"firstName": first, "lastName": last},
                "emails": {"primaryEmail": email}, "companyId": cid}
        if segment:
            data["newsletterSegment"] = segment
        existing = c.find_one("people", "emails.primaryEmail", email)
        if existing:
            c.update("people", existing["id"], data)
        else:
            c.create("people", data)
        print(f"  OK  {tag:<14} {email:<42} {org}")

    if not a.apply:
        print(f"\n(dry-run) {len(CONTACTS)} contacts. Relancer avec --apply pour écrire.")
    else:
        print(f"\nOK — {len(CONTACTS)} contacts upsertés (Company + Person) dans Twenty.")


if __name__ == "__main__":
    main()
