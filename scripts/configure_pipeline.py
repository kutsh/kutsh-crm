#!/usr/bin/env python3
"""Configure le pipeline commercial sur l'objet Opportunity de Twenty (issue mfmp).

Twenty n'expose qu'UN champ `stage` par objet : on adopte un pipeline UNIFIÉ + un
champ `segment` (B2G / B2B / B2B2B) pour distinguer les cycles. Les étapes portent
le vocabulaire des trois cycles (cf. cadrage / Model Eco) :
  - B2G (marché public) : veille → DCE → offre → audition → notification → exécution
  - B2B (SaaS)          : lead → démo → essai → abonnement
  - B2B2B (API)         : contact → POC → contrat-cadre

Idempotent. Env : TWENTY_API_KEY (+ TWENTY_BASE_URL).
"""
import os
import json
import urllib.request
import urllib.error

BASE = os.environ.get("TWENTY_BASE_URL", "https://twenty.kutsh.fr").rstrip("/")
KEY = os.environ["TWENTY_API_KEY"]

SEGMENT_OPTIONS = [
    {"value": "B2G", "label": "B2G", "position": 0, "color": "blue"},
    {"value": "B2B", "label": "B2B", "position": 1, "color": "green"},
    {"value": "B2B2B", "label": "B2B2B", "position": 2, "color": "orange"},
    # RELAIS = relation indirecte (fédération / réseau prescripteur), pas une vente
    # directe → pipeline « partenariats » filtrable par ce segment.
    {"value": "RELAIS", "label": "Relais / partenariat", "position": 3, "color": "purple"},
]

# Pipeline unifié (UPPER_SNAKE -> label lisible portant le vocabulaire des 3 segments)
STAGE_OPTIONS = [
    {"value": "PROSPECTION", "label": "Prospection (veille / lead / contact)", "position": 0, "color": "gray"},
    {"value": "QUALIFICATION", "label": "Qualification", "position": 1, "color": "blue"},
    {"value": "ECHANGE", "label": "Démo / Échange", "position": 2, "color": "sky"},
    {"value": "OFFRE", "label": "Offre (DCE / proposition / POC)", "position": 3, "color": "turquoise"},
    {"value": "EVALUATION", "label": "Audition / Essai", "position": 4, "color": "purple"},
    {"value": "GAGNE", "label": "Gagné (notification / abonnement / contrat-cadre)", "position": 5, "color": "green"},
    {"value": "EXECUTION", "label": "En exécution (B2G)", "position": 6, "color": "yellow"},
    {"value": "PERDU", "label": "Perdu", "position": 7, "color": "red"},
]


def req(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + KEY, "Content-Type": "application/json",
        "User-Agent": "kutsh-crm/1.0"})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:400]}")


def main():
    obj = req("GET", "/rest/metadata/objects?limit=200")["data"]["objects"]
    opp = next(o for o in obj if o["nameSingular"] == "opportunity")
    fields = req("GET", f"/rest/metadata/objects/{opp['id']}")["data"]["object"]["fields"]
    by_name = {f["name"]: f for f in fields}

    # 1. champ segment (créer si absent, sinon synchroniser les options → ajoute RELAIS)
    if "segment" in by_name:
        req("PATCH", f"/rest/metadata/fields/{by_name['segment']['id']}", {
            "options": SEGMENT_OPTIONS,
        })
        print(f"segment: {len(SEGMENT_OPTIONS)} valeurs synchronisées (dont RELAIS)")
    else:
        req("POST", "/rest/metadata/fields", {
            "objectMetadataId": opp["id"], "name": "segment", "label": "Segment",
            "type": "SELECT", "icon": "IconTargetArrow",
            "description": "Segment commercial : B2G (collectivités) / B2B (cabinets) / "
                           "B2B2B (fabricants) / RELAIS (fédération, réseau prescripteur).",
            "options": SEGMENT_OPTIONS,
        })
        print("segment: créé (B2G / B2B / B2B2B / RELAIS)")

    # 2. options du stage (pipeline unifié)
    stage = by_name["stage"]
    req("PATCH", f"/rest/metadata/fields/{stage['id']}", {
        "options": STAGE_OPTIONS, "defaultValue": "'PROSPECTION'",
    })
    print(f"stage: {len(STAGE_OPTIONS)} étapes configurées (défaut PROSPECTION)")


if __name__ == "__main__":
    main()
