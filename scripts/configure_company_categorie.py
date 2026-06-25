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

# Typologie des organisations. Bloc « relais/prescripteurs » + cibles directes +
# (2026-06-25, issue commentaire cadrage 9869940877) segments aval : GSB/distribution,
# constructeurs, installateurs, instructeurs privés, agences immo, courtiers, réseaux pro.
CATEGORIE_OPTIONS = [
    {"value": "COLLECTIVITE_EPCI", "label": "Collectivité / EPCI", "color": "blue"},
    {"value": "FEDERATION_PRO", "label": "Fédération professionnelle", "color": "purple"},
    {"value": "FEDERATION_COLLECTIVITES", "label": "Fédération / asso de collectivités", "color": "turquoise"},
    {"value": "RESEAU_ELUS", "label": "Réseau d'élus", "color": "sky"},
    {"value": "RESEAU_PRO", "label": "Réseau pro (franchisés / BTP / BIM)", "color": "purple"},
    {"value": "CABINET", "label": "Cabinet (dessinateur-projeteur / archi / géomètre)", "color": "green"},
    {"value": "INSTRUCTEUR_PRIVE", "label": "Instructeur ADS privé", "color": "green"},
    {"value": "CABINET_AVOCATS", "label": "Cabinet d'avocats", "color": "red"},
    {"value": "EDITEUR_ADS", "label": "Éditeur ADS", "color": "orange"},
    {"value": "FABRICANT", "label": "Fabricant / revendeur (véranda, abri, pergola…)", "color": "yellow"},
    {"value": "GSB_DISTRIBUTION", "label": "GSB / distribution / négoce matériaux", "color": "yellow"},
    {"value": "CONSTRUCTEUR", "label": "Constructeur (CMI · bois · modulaire)", "color": "orange"},
    {"value": "INSTALLATEUR", "label": "Installateur (solaire · PAC · piscine)", "color": "yellow"},
    {"value": "AGENCE_IMMO", "label": "Agence / réseau immobilier", "color": "pink"},
    {"value": "COURTIER_TRAVAUX", "label": "Courtier travaux", "color": "pink"},
    {"value": "MEDIA", "label": "Média", "color": "pink"},
    {"value": "ACADEMIQUE", "label": "Académique / recherche (ENSA…)", "color": "red"},
    {"value": "INSTITUTIONNEL", "label": "Institutionnel (CEREMA / CAUE / Ordre…)", "color": "gray"},
    {"value": "AUTRE", "label": "Autre", "color": "gray"},
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
    company = next(o for o in objs if o["nameSingular"] == "company")
    fields = req("GET", f"/rest/metadata/objects/{company['id']}")["data"]["object"]["fields"]
    field = next((f for f in fields if f["name"] == "categorie"), None)
    if field is None:
        req("POST", "/rest/metadata/fields", {
            "objectMetadataId": company["id"], "name": "categorie", "label": "Catégorie",
            "type": "SELECT", "icon": "IconCategory",
            "description": "Nature de l'organisation (relais/prescripteur, cabinet, éditeur, etc.).",
            "options": _positions(CATEGORIE_OPTIONS),
        })
        print(f"categorie: créé sur Company ({len(CATEGORIE_OPTIONS)} valeurs)")
        return
    # Champ présent → ajoute les valeurs manquantes EN PRÉSERVANT l'existant
    # (id + value, sinon les enregistrements déjà typés perdraient leur valeur).
    current = field.get("options") or []
    have = {o["value"] for o in current}
    missing = [o for o in CATEGORIE_OPTIONS if o["value"] not in have]
    if not missing:
        print("categorie: à jour, rien à ajouter")
        return
    keep = [{k: o[k] for k in ("id", "value", "label", "color", "position") if k in o} for o in current]
    base = max((o.get("position", 0) for o in current), default=-1) + 1
    add = [{**o, "position": base + i} for i, o in enumerate(missing)]
    req("PATCH", f"/rest/metadata/fields/{field['id']}", {"options": keep + add})
    print(f"categorie: +{len(missing)} valeurs ({', '.join(o['value'] for o in missing)})")


if __name__ == "__main__":
    main()
