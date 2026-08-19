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
import os, sys, json, argparse, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from crm_client import TwentyClient, merge_select_options  # noqa: E402  # type: ignore[import-not-found]

BASE = os.environ.get("TWENTY_BASE_URL", "https://twenty.kutsh.fr").rstrip("/")

# Typologie des organisations. Bloc « relais/prescripteurs » + cibles directes +
# (2026-06-25, issue commentaire cadrage 9869940877) segments aval : GSB/distribution,
# constructeurs, installateurs, instructeurs privés, agences immo, courtiers, réseaux pro.
# + (2026-07-23) FINANCEUR : les financeurs de Kutsh, pas de la chaîne urbanisme.
# + (2026-08-18) AGENCE_VERANDA : née dans l'UI, adoptée (cf. decisions/).
CATEGORIE_OPTIONS = [
    {"value": "COLLECTIVITE_EPCI", "label": "Collectivité / EPCI", "color": "blue"},
    {"value": "FEDERATION_PRO", "label": "Fédération professionnelle", "color": "purple"},
    {"value": "FEDERATION_COLLECTIVITES", "label": "Fédération / asso de collectivités", "color": "turquoise"},
    {"value": "RESEAU_ELUS", "label": "Réseau d'élus", "color": "sky"},
    {"value": "RESEAU_PRO", "label": "Réseau pro (franchisés / BTP / BIM)", "color": "purple"},
    # Le `CABINET` générique a été dépassé par l'usage : les catégories fines
    # ci-dessous ont été créées dans l'UI et portent 115 fiches quand lui n'en
    # porte qu'une. Adoptées telles quelles (`--adopt`), libellés d'origine —
    # le vocabulaire vient du terrain. `CABINET` reste pour ce qui n'entre dans
    # aucune des trois (géomètres, cabinets mixtes).
    {"value": "CABINET", "label": "Cabinet (autre / géomètre)", "color": "green"},
    {"value": "CABINET_DESSINATEUR_PROJETEUR", "label": "Cabinet de dessinateur-projeteur", "color": "sky"},
    {"value": "CABINET_ARCHITECTURE", "label": "Cabinet d'architecture", "color": "turquoise"},
    {"value": "BUREAU_ETUDES_TECHNIQUES", "label": "Bureau d'études techniques (BET)", "color": "green"},
    {"value": "INSTRUCTEUR_PRIVE", "label": "Instructeur ADS privé", "color": "green"},
    {"value": "CABINET_AVOCATS", "label": "Cabinet d'avocats", "color": "red"},
    {"value": "EDITEUR_ADS", "label": "Éditeur ADS", "color": "orange"},
    # Séparateurs « · » et non « , » : Twenty refuse la virgule dans un libellé
    # d'option (cf. `crm_client._refuse_les_virgules`).
    {"value": "FABRICANT", "label": "Fabricant / revendeur (véranda · abri · pergola…)", "color": "yellow"},
    {"value": "GSB_DISTRIBUTION", "label": "GSB / distribution / négoce matériaux", "color": "yellow"},
    {"value": "CONSTRUCTEUR", "label": "Constructeur (CMI · bois · modulaire)", "color": "orange"},
    {"value": "INSTALLATEUR", "label": "Installateur (solaire · PAC · piscine)", "color": "yellow"},
    # (2026-08-18) Adoptée depuis l'UI : l'import du 2026-08-11 a typé 206 fiches
    # `AGENCE_VERANDA` — les agences qui *posent* la véranda, distinctes du
    # `FABRICANT` qui la produit ou la revend. Libellé d'origine conservé.
    {"value": "AGENCE_VERANDA", "label": "Agence véranda (pose / installation)", "color": "yellow"},
    {"value": "AGENCE_IMMO", "label": "Agence / réseau immobilier", "color": "pink"},
    {"value": "COURTIER_TRAVAUX", "label": "Courtier travaux", "color": "pink"},
    {"value": "MARCHAND_DE_BIENS", "label": "Marchand de biens", "color": "pink"},
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


def _non_declarees(field):
    """Options présentes dans Twenty et absentes de CATEGORIE_OPTIONS.

    Créer une catégorie depuis l'UI de Twenty est légitime — le vocabulaire
    métier naît de l'usage, pas du dépôt : `CABINET_DESSINATEUR_PROJETEUR` a
    fini sur 105 fiches quand le `CABINET` versionné n'en portait qu'une. Ce
    qui ne l'est pas, c'est qu'une telle catégorie reste sans comportement en
    silence (routage newsletter, qualification) parce que personne n'a su
    qu'elle existait.
    """
    declarees = {o["value"] for o in CATEGORIE_OPTIONS}
    return [o for o in (field.get("options") or []) if o.get("value") not in declarees]


def _compte_fiches(valeurs):
    """Nombre de Companies portant chaque valeur — un audit sans volumétrie ne
    permet pas de trancher entre « à déclarer » et « scorie à supprimer »."""
    from collections import Counter
    c = TwentyClient()
    compte = Counter(co.get("categorie") for co in c.list_all("companies", depth=0))
    return {v: compte.get(v, 0) for v in valeurs}


def check():
    """N'écrit rien. Sort en 1 si le SELECT a dérivé de la liste déclarée.

    C'est la commande cron : sans elle, la dérive n'apparaît qu'à qui pense à
    lancer un dry-run.
    """
    field = _field()
    inconnues = _non_declarees(field)
    if not inconnues:
        print(f"categorie: aucune dérive ({len(CATEGORIE_OPTIONS)} valeurs déclarées)")
        return 0
    fiches = _compte_fiches([o["value"] for o in inconnues])
    print(f"⚠️  {len(inconnues)} catégorie(s) présente(s) dans Twenty mais non déclarée(s) :")
    for o in sorted(inconnues, key=lambda x: -fiches.get(x["value"], 0)):
        print(f"    {o['value']:<32} {fiches.get(o['value'], 0):>4} fiche(s)  « {o.get('label', '')} »")
    print("\n  → les déclarer : `--adopt` imprime le bloc à coller dans CATEGORIE_OPTIONS,")
    print("    puis les mapper dans SEGMENTS (crm_brevo.py) ou CATEGORIES_HORS_NEWSLETTER.")
    return 1


def adopt():
    """Imprime le bloc Python des options non déclarées, à coller tel quel.

    Reprend les libellés et couleurs saisis dans l'UI, sans les réécrire :
    adopter une catégorie née du terrain, c'est prendre son vocabulaire, pas
    lui imposer le nôtre.
    """
    inconnues = _non_declarees(_field())
    if not inconnues:
        print("# rien à adopter — le SELECT Twenty ne contient que des valeurs déclarées")
        return 0
    print("# À coller dans CATEGORIE_OPTIONS (libellés repris de Twenty tels quels) :")
    for o in inconnues:
        ligne = {"value": o["value"], "label": o.get("label") or o["value"],
                 "color": o.get("color") or "gray"}
        print("    " + json.dumps(ligne, ensure_ascii=False) + ",")
    return 0


def _field():
    objs = req("GET", "/rest/metadata/objects?limit=200")["data"]["objects"]
    company = next(o for o in objs if o["nameSingular"] == "company")
    fields = req("GET", f"/rest/metadata/objects/{company['id']}")["data"]["object"]["fields"]
    field = next((f for f in fields if f["name"] == "categorie"), None)
    if field is None:
        raise SystemExit("le champ `categorie` n'existe pas encore — lancer le script sans option")
    return field


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="n'écrit rien ; sort en 1 si Twenty porte des catégories non déclarées")
    ap.add_argument("--adopt", action="store_true",
                    help="imprime le bloc Python des catégories non déclarées (lecture seule)")
    a = ap.parse_args()
    if a.check:
        return check()
    if a.adopt:
        return adopt()

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
        return 0
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
        print("     → `--adopt` imprime le bloc à coller pour les déclarer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
