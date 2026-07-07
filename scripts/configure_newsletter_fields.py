#!/usr/bin/env python3
"""Ajoute les champs « newsletter » sur l'objet Person de Twenty.

Objectif RGPD : la base est envoyée en soft opt-in (première lettre + désinscription
en un clic). Brevo gère la désinscription ; on **rapatrie** l'info dans Twenty pour
que le CRM reste la source de vérité et qu'on ne re-sollicite jamais un désinscrit.

Champs posés sur Person (idempotent — crée les manquants, ne touche pas l'existant) :
- `newsletterOptOut`   BOOLEAN   — désinscrit (rempli par la réconciliation Brevo→Twenty)
- `newsletterOptOutAt` DATE_TIME — date de la désinscription
- `newsletterSegment`  SELECT    — liste Brevo d'appartenance (COLLECTIVITES / PROS / ECOSYSTEME)

Idempotent. Env : TWENTY_API_KEY (+ TWENTY_BASE_URL).
"""
import os, json, urllib.request, urllib.error

BASE = os.environ.get("TWENTY_BASE_URL", "https://twenty.kutsh.fr").rstrip("/")
KEY = os.environ["TWENTY_API_KEY"]

SEGMENT_OPTIONS = [
    {"value": "COLLECTIVITES", "label": "Collectivités & ADS", "color": "blue"},
    {"value": "PROS", "label": "Pros de l'urbanisme", "color": "green"},
    {"value": "ECOSYSTEME", "label": "Écosystème & institutionnels", "color": "purple"},
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


def _positions(opts):
    return [{**o, "position": i} for i, o in enumerate(opts)]


def main():
    objs = req("GET", "/rest/metadata/objects?limit=200")["data"]["objects"]
    person = next(o for o in objs if o["nameSingular"] == "person")
    fields = req("GET", f"/rest/metadata/objects/{person['id']}")["data"]["object"]["fields"]
    have = {f["name"] for f in fields}

    specs = [
        {"name": "newsletterOptOut", "label": "Newsletter — désinscrit", "type": "BOOLEAN",
         "icon": "IconMailOff", "defaultValue": False,
         "description": "Désinscrit de la newsletter (rapatrié depuis Brevo). Ne jamais re-solliciter."},
        {"name": "newsletterOptOutAt", "label": "Newsletter — désinscrit le", "type": "DATE_TIME",
         "icon": "IconCalendarOff",
         "description": "Horodatage de la désinscription (source Brevo)."},
        {"name": "newsletterSegment", "label": "Newsletter — segment", "type": "SELECT",
         "icon": "IconMail",
         "description": "Liste Brevo d'appartenance (déduite de la catégorie de l'organisation).",
         "options": _positions(SEGMENT_OPTIONS)},
    ]

    created = 0
    for spec in specs:
        if spec["name"] in have:
            print(f"  {spec['name']}: présent, ok")
            continue
        req("POST", "/rest/metadata/fields", {"objectMetadataId": person["id"], **spec})
        print(f"  {spec['name']}: créé sur Person")
        created += 1
    print(f"OK — {created} champ(s) créé(s), {len(specs) - created} déjà présent(s).")


if __name__ == "__main__":
    main()
