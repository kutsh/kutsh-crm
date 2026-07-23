#!/usr/bin/env python3
"""Ajoute un champ SELECT `categorie` sur l'objet Company de Twenty.

Permet de typer les organisations du CRM — distinguer notamment les **relais /
prescripteurs** (fédérations pro, fédérations/associations de collectivités,
réseaux d'élus) des clients/prospects directs. Léger (champ, pas objet dédié) ;
un objet `Federation` pourra être promu plus tard si le canal devient central.

Idempotent (crée le champ si absent) et non destructif : les options existantes
sont fusionnées par `crm_client.merge_select_options`, qui préserve leurs `id`.

Env : TWENTY_API_KEY (+ TWENTY_BASE_URL).
"""
import os, sys, json, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from crm_client import merge_select_options  # noqa: E402  # type: ignore[import-not-found]

BASE = os.environ.get("TWENTY_BASE_URL", "https://twenty.kutsh.fr").rstrip("/")

# Typologie des organisations. Bloc « relais/prescripteurs » + cibles directes +
# (2026-06-25, issue commentaire cadrage 9869940877) segments aval : GSB/distribution,
# constructeurs, installateurs, instructeurs privés, agences immo, courtiers, réseaux pro.
# + (2026-07-23) FINANCEUR : les financeurs de Kutsh, pas de la chaîne urbanisme.
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
    {"value": "FINANCEUR", "label": "Financeur / investisseur (fonds · BA · BPI · subvention)", "color": "green"},
    {"value": "AUTRE", "label": "Autre", "color": "gray"},
]


def _key():
    """Lu à l'appel, pas à l'import : `CATEGORIE_OPTIONS` est la liste de
    référence des catégories (les tests la comparent au mapping newsletter de
    `crm_brevo`), donc importer ce module ne doit pas exiger de secret."""
    try:
        return os.environ["TWENTY_API_KEY"]
    except KeyError:
        raise SystemExit("TWENTY_API_KEY manquant")


def req(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + _key(), "Content-Type": "application/json",
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
    # Champ présent → fusion NON destructive : les `id` en place sont réutilisés,
    # sinon les fiches déjà typées perdraient leur valeur (cf. la docstring de
    # `merge_select_options`, qui porte cette leçon pour les deux scripts de
    # configuration — ce fichier en avait sa propre version).
    current = field.get("options") or []
    connues = {o.get("value") for o in current}
    fusion, orphelines = merge_select_options(current, CATEGORIE_OPTIONS)
    ajoutees = [o["value"] for o in CATEGORIE_OPTIONS if o["value"] not in connues]
    req("PATCH", f"/rest/metadata/fields/{field['id']}", {"options": fusion})
    print(f"categorie: {len(CATEGORIE_OPTIONS)} valeurs synchronisées"
          + (f", +{len(ajoutees)} nouvelle(s) ({', '.join(ajoutees)})" if ajoutees else ""))
    if orphelines:
        print(f"  ⚠️  {len(orphelines)} option(s) hors liste déclarée, CONSERVÉE(S) : "
              f"{', '.join(o.get('value', '?') for o in orphelines)}")


if __name__ == "__main__":
    main()
