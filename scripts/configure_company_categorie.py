#!/usr/bin/env python3
"""Ajoute un champ SELECT `categorie` sur l'objet Company de Twenty.

Permet de typer les organisations du CRM — distinguer notamment les **relais /
prescripteurs** (fédérations pro, fédérations/associations de collectivités,
réseaux d'élus) des clients/prospects directs. Léger (champ, pas objet dédié) ;
un objet `Federation` pourra être promu plus tard si le canal devient central.

Idempotent (crée le champ si absent). Env : TWENTY_API_KEY (+ TWENTY_BASE_URL).
"""
import os, json, urllib.request, urllib.error

BASE = os.environ.get("TWENTY_BASE_URL", "https://twenty.kutsh.fr").rstrip("/")
KEY = os.environ["TWENTY_API_KEY"]

CATEGORIE_OPTIONS = [
    {"value": "COLLECTIVITE_EPCI", "label": "Collectivité / EPCI", "position": 0, "color": "blue"},
    {"value": "FEDERATION_PRO", "label": "Fédération professionnelle", "position": 1, "color": "purple"},
    {"value": "FEDERATION_COLLECTIVITES", "label": "Fédération / asso de collectivités", "position": 2, "color": "turquoise"},
    {"value": "RESEAU_ELUS", "label": "Réseau d'élus", "position": 3, "color": "sky"},
    {"value": "CABINET", "label": "Cabinet (dessinateur-projeteur / archi)", "position": 4, "color": "green"},
    {"value": "EDITEUR_ADS", "label": "Éditeur ADS", "position": 5, "color": "orange"},
    {"value": "FABRICANT", "label": "Fabricant", "position": 6, "color": "yellow"},
    {"value": "MEDIA", "label": "Média", "position": 7, "color": "pink"},
    {"value": "ACADEMIQUE", "label": "Académique / recherche", "position": 8, "color": "red"},
    {"value": "INSTITUTIONNEL", "label": "Institutionnel (CEREMA / CAUE…)", "position": 9, "color": "gray"},
    {"value": "AUTRE", "label": "Autre", "position": 10, "color": "gray"},
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
    objs = req("GET", "/rest/metadata/objects?limit=200")["data"]["objects"]
    company = next(o for o in objs if o["nameSingular"] == "company")
    fields = req("GET", f"/rest/metadata/objects/{company['id']}")["data"]["object"]["fields"]
    if any(f["name"] == "categorie" for f in fields):
        print("categorie: déjà présent")
        return
    req("POST", "/rest/metadata/fields", {
        "objectMetadataId": company["id"], "name": "categorie", "label": "Catégorie",
        "type": "SELECT", "icon": "IconCategory",
        "description": "Nature de l'organisation (relais/prescripteur, cabinet, éditeur, etc.).",
        "options": CATEGORIE_OPTIONS,
    })
    print(f"categorie: créé sur Company ({len(CATEGORIE_OPTIONS)} valeurs)")


if __name__ == "__main__":
    main()
