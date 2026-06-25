#!/usr/bin/env python3
"""import_fndi_cabinets.py — importe les dessinateurs-projeteurs FNDI dans Twenty.

Source : export CSV de l'annuaire FNDI (`Nom complet;Adresse;Email;Téléphone …;
Région FNDI;Entreprise;Site internet;Spécialité;…`). Pour chaque dessinateur :
  - upsert **Cabinet** (clé = name) : typeCabinet=DESSINATEUR_PROJETEUR,
    zoneIntervention (commune/dept + région FNDI + spécialité), siteWeb.
  - upsert **Person** (clé = email, sinon name) : prénom/nom, email, téléphone,
    jobTitle, city, rattaché au Cabinet (cabinetId) — relation issue 1dhk.

Les dessinateurs n'ont pas de NAF propre (≠ architectes/géomètres chargés depuis
SIRENE) → cette liste fédérale est leur base de référence.

Idempotent (pré-charge cabinets par nom + people par email). DRY-RUN par défaut ;
--apply pour écrire ; --limit N pour tester le chemin d'écriture. Env : TWENTY_API_KEY.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crm_client import TwentyClient  # noqa: E402

CSV_DEFAULT = "/Users/joel/kDrive/Prospection/340_contacts_FNDI.csv"


def split_name(full: str) -> tuple[str, str]:
    """« NOM Prénom » (nom en capitales, prénom en casse titre) → (prénom, nom)."""
    toks = full.split()
    if len(toks) < 2:
        return full, full
    i = len(toks)
    while i > 0 and not toks[i - 1].isupper():
        i -= 1
    last, first = " ".join(toks[:i]), " ".join(toks[i:])
    if not last or not first:  # tout en capitales / aucun token capitale
        last, first = toks[0], " ".join(toks[1:])
    return first.strip(), last.strip()


def parse_addr(addr: str) -> tuple[str, str]:
    """Adresse FNDI → (commune, département). Format usuel : '…, 76000 Rouen, France'."""
    m = re.search(r"(\d{5})\s+([^,]+?),\s*France\s*$", addr.strip())
    if m:
        cp, commune = m.group(1), m.group(2).strip()
    else:
        m2 = re.search(r"\b(\d{5})\b", addr)
        cp, commune = (m2.group(1) if m2 else ""), ""
    dept = cp[:3] if cp.startswith("97") else cp[:2]
    return commune, dept


def valid_url(u: str) -> bool:
    """URL exploitable par le champ LINKS de Twenty (rejette emails, 'https://NON'…)."""
    return bool(re.match(r"https?://[^\s@]+\.[^\s@]+$", (u or "").strip()))


def parse_phone(raw: str) -> dict[str, str] | None:
    """'+33 6 66 15 07 48' → composite Twenty (number + calling code + pays)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    m = re.match(r"(\+\d{2,3})\s*(.*)", raw)
    if not m:
        digits = re.sub(r"\D", "", raw)
        return {"primaryPhoneNumber": digits} if digits else None
    calling, num = m.group(1), re.sub(r"\D", "", m.group(2))
    if not num:
        return None
    out = {"primaryPhoneNumber": num, "primaryPhoneCallingCode": calling}
    if calling == "+33":
        out["primaryPhoneCountryCode"] = "FR"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--apply", action="store_true", help="écrit dans Twenty (sinon dry-run)"
    )
    ap.add_argument(
        "--limit", type=int, help="ne traiter que les N premières lignes (test)"
    )
    ap.add_argument("--csv", default=CSV_DEFAULT)
    a = ap.parse_args()

    c = TwentyClient()
    cab_by_name = {
        x["name"].strip().lower(): x["id"]
        for x in c.list_all("cabinets")
        if x.get("name")
    }
    ppl_emails = {
        em.strip().lower()
        for p in c.list_all("people")
        if (em := (p.get("emails") or {}).get("primaryEmail"))
    }
    stats = {
        "rows": 0,
        "cab_created": 0,
        "cab_reused": 0,
        "ppl_created": 0,
        "ppl_skipped": 0,
    }

    with open(
        a.csv, encoding="utf-8-sig"
    ) as f:  # -sig : retire le BOM (sinon clé « Nom complet » KO)
        for row in csv.DictReader(f, delimiter=";"):
            if a.limit and stats["rows"] >= a.limit:
                break
            stats["rows"] += 1
            full = (row.get("Nom complet") or "").strip()
            ent = (row.get("Entreprise") or "").strip()
            name = (ent or full)[:120]
            if not name:
                continue
            commune, dept = parse_addr(row.get("Adresse") or "")
            region = (row.get("Région FNDI") or "").strip()
            spec = (row.get("Spécialité") or "").strip()
            site = (row.get("Site internet") or "").strip()
            zone = " · ".join(
                p
                for p in (
                    f"{commune} ({dept})" if commune else dept,
                    f"Région {region}" if region else "",
                    spec,
                )
                if p
            )

            key = name.lower()
            cab_id = cab_by_name.get(key)
            if cab_id is None:
                fields: dict[str, Any] = {
                    "name": name,
                    "typeCabinet": "DESSINATEUR_PROJETEUR",
                    "zoneIntervention": zone[:255],
                }
                if valid_url(site):
                    fields["siteWeb"] = {
                        "primaryLinkUrl": site,
                        "primaryLinkLabel": "Site",
                    }
                cab_id = (
                    c.create("cabinets", fields)["id"]
                    if a.apply
                    else f"DRY-{stats['rows']}"
                )
                cab_by_name[key] = cab_id
                stats["cab_created"] += 1
            else:
                stats["cab_reused"] += 1

            email = (row.get("Email") or "").strip()
            if email and email.lower() in ppl_emails:
                stats["ppl_skipped"] += 1
                continue
            first, last = split_name(full)
            pf: dict[str, Any] = {
                "name": {"firstName": first[:60], "lastName": last[:60]},
                "jobTitle": "Dessinateur-projeteur" + (f" · {spec}" if spec else ""),
            }
            if a.apply:
                pf["cabinetId"] = cab_id
            if email:
                pf["emails"] = {"primaryEmail": email}
            if ph := (
                parse_phone(row.get("Téléphone mobile"))
                or parse_phone(row.get("Téléphone fixe"))
            ):
                pf["phones"] = ph
            if commune:
                pf["city"] = commune
            if a.apply:
                c.create("people", pf)
            if email:
                ppl_emails.add(email.lower())
            stats["ppl_created"] += 1

    print(f"\n{'OK' if a.apply else 'DRY-RUN'} : {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
