#!/usr/bin/env python3
"""Configure le pipeline sur l'objet Opportunity de Twenty (issues mfmp, levée 2026-07-23).

Twenty n'expose qu'UN champ `stage` par objet : on adopte un pipeline UNIFIÉ + un
champ `segment` pour distinguer les cycles. Les étapes portent le vocabulaire de
chaque cycle (cf. cadrage / Model Eco) :
  - B2G (marché public) : veille → DCE → offre → audition → notification → exécution
  - B2B (SaaS)          : lead → démo → essai → abonnement
  - B2B2B (API)         : contact → POC → contrat-cadre
  - RELAIS              : partenariat prescripteur (pas une vente directe)
  - LEVEE               : sourcing → pitch → term sheet → due diligence → closing

Le suivi de levée réutilise donc le pipeline commercial plutôt qu'un objet dédié
(ADR 2026-07-23-suivi-levee-pipeline) : mêmes étapes, vocabulaire propre, plus le
champ `tourFinancement` qui rattache chaque ligne à un tour (sans quoi un montant
levé ne s'agrège pas). Le financeur est la Company (`categorie = FINANCEUR`), le
ticket va dans `amount`, la date visée dans `closeDate` — champs standard Twenty.

Idempotent, et **non destructif** : les options des SELECT sont fusionnées par
`crm_client.merge_select_options`, qui préserve les `id` en place (un PATCH naïf
vide la valeur des fiches, cf. sa docstring).

Env : TWENTY_API_KEY (+ TWENTY_BASE_URL).
"""
import os
import sys
import json
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from crm_client import merge_select_options  # noqa: E402  # type: ignore[import-not-found]

BASE = os.environ.get("TWENTY_BASE_URL", "https://twenty.kutsh.fr").rstrip("/")

SEGMENT_OPTIONS = [
    {"value": "B2G", "label": "B2G", "color": "blue"},
    {"value": "B2B", "label": "B2B", "color": "green"},
    {"value": "B2B2B", "label": "B2B2B", "color": "orange"},
    # RELAIS = relation indirecte (fédération / réseau prescripteur), pas une vente
    # directe → pipeline « partenariats » filtrable par ce segment.
    {"value": "RELAIS", "label": "Relais / partenariat", "color": "purple"},
    # LEVEE = financement de Kutsh, pas un revenu client. Même pipeline, autre
    # contrepartie (Company `categorie = FINANCEUR`) : à exclure des vues de
    # prévision commerciale, sans quoi un ticket d'investissement gonfle le CA
    # prévisionnel.
    {"value": "LEVEE", "label": "Levée / financement", "color": "pink"},
]

# Pipeline unifié (UPPER_SNAKE -> label lisible portant le vocabulaire des segments).
STAGE_OPTIONS = [
    {"value": "PROSPECTION", "label": "Prospection (veille / lead / contact / sourcing)", "color": "gray"},
    {"value": "QUALIFICATION", "label": "Qualification (fit thèse)", "color": "blue"},
    {"value": "ECHANGE", "label": "Démo / Échange / Pitch", "color": "sky"},
    {"value": "OFFRE", "label": "Offre (DCE / proposition / POC / term sheet)", "color": "turquoise"},
    {"value": "EVALUATION", "label": "Audition / Essai / Due diligence", "color": "purple"},
    {"value": "GAGNE", "label": "Gagné (notification / abonnement / contrat-cadre / closing)", "color": "green"},
    {"value": "EXECUTION", "label": "En exécution (marché B2G / reporting investisseur)", "color": "yellow"},
    {"value": "PERDU", "label": "Perdu (infructueux / churn / pass)", "color": "red"},
]

# Tour de financement — ne concerne que le segment LEVEE. Sépare le dilutif du
# non-dilutif : une subvention BPI et un ticket de fonds ne se somment pas dans
# la même phrase, et ne se pilotent pas au même rythme.
TOUR_OPTIONS = [
    {"value": "PRE_SEED", "label": "Pre-seed / amorçage", "color": "sky"},
    {"value": "SEED", "label": "Seed", "color": "blue"},
    {"value": "SERIE_A", "label": "Série A", "color": "purple"},
    {"value": "SUBVENTION", "label": "Subvention / aide (BPI · région…)", "color": "green"},
    {"value": "PRET", "label": "Prêt / financement bancaire", "color": "orange"},
    {"value": "AUTRE", "label": "Autre", "color": "gray"},
]

# Champs standard Twenty sur lesquels s'appuie le suivi de levée. On ne les crée
# pas — on vérifie leur présence, parce que la doc du suivi les suppose et qu'un
# workspace où ils auraient été retirés rendrait la moitié de ce pipeline muette.
CHAMPS_ATTENDUS = {"amount": "ticket / montant", "closeDate": "date visée", "companyId": "financeur"}


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


def _key():
    """Lu à l'appel, pas à l'import : importer ce module (tests des listes
    d'options) ne doit pas exiger de secret."""
    try:
        return os.environ["TWENTY_API_KEY"]
    except KeyError:
        raise SystemExit("TWENTY_API_KEY manquant")


def _sync_select(field, options, quoi, **extra):
    """PATCH non destructif des options d'un SELECT existant."""
    fusion, orphelines = merge_select_options(field.get("options") or [], options)
    req("PATCH", f"/rest/metadata/fields/{field['id']}", {"options": fusion, **extra})
    print(f"{quoi}: {len(options)} valeurs synchronisées")
    if orphelines:
        # Conservées (supprimer viderait les fiches qui les portent), mais dites :
        # une valeur que plus personne ne déclare doit se retirer à la main.
        print(f"  ⚠️  {len(orphelines)} option(s) hors liste déclarée, CONSERVÉE(S) : "
              f"{', '.join(o.get('value', '?') for o in orphelines)}")


def main():
    obj = req("GET", "/rest/metadata/objects?limit=200")["data"]["objects"]
    opp = next(o for o in obj if o["nameSingular"] == "opportunity")
    fields = req("GET", f"/rest/metadata/objects/{opp['id']}")["data"]["object"]["fields"]
    by_name = {f["name"]: f for f in fields}

    # 1. segment (créer si absent, sinon fusionner → ajoute LEVEE)
    if "segment" in by_name:
        _sync_select(by_name["segment"], SEGMENT_OPTIONS, "segment")
    else:
        req("POST", "/rest/metadata/fields", {
            "objectMetadataId": opp["id"], "name": "segment", "label": "Segment",
            "type": "SELECT", "icon": "IconTargetArrow",
            "description": "Cycle : B2G (collectivités) / B2B (cabinets) / B2B2B "
                           "(fabricants) / RELAIS (prescripteur) / LEVEE (financement de Kutsh).",
            "options": [{**o, "position": i} for i, o in enumerate(SEGMENT_OPTIONS)],
        })
        print(f"segment: créé ({len(SEGMENT_OPTIONS)} valeurs)")

    # 2. options du stage (pipeline unifié) + défaut
    _sync_select(by_name["stage"], STAGE_OPTIONS, "stage", defaultValue="'PROSPECTION'")

    # 3. tour de financement (segment LEVEE)
    if "tourFinancement" in by_name:
        _sync_select(by_name["tourFinancement"], TOUR_OPTIONS, "tourFinancement")
    else:
        req("POST", "/rest/metadata/fields", {
            "objectMetadataId": opp["id"], "name": "tourFinancement",
            "label": "Tour de financement", "type": "SELECT", "icon": "IconPigMoney",
            "description": "Tour rattaché à l'opportunité — segment LEVEE uniquement "
                           "(vide ailleurs). Permet d'agréger un tour : montant engagé, "
                           "reste à lever.",
            "options": [{**o, "position": i} for i, o in enumerate(TOUR_OPTIONS)],
        })
        print(f"tourFinancement: créé ({len(TOUR_OPTIONS)} valeurs)")

    # 4. contrôle des champs standard dont dépend le suivi de levée
    manquants = {n: quoi for n, quoi in CHAMPS_ATTENDUS.items()
                 if n not in by_name and n.removesuffix("Id") not in by_name}
    if manquants:
        print("⚠️  champs standard absents du workspace : "
              + ", ".join(f"{n} ({quoi})" for n, quoi in manquants.items()))
    else:
        print("champs standard (amount / closeDate / company) : présents")


if __name__ == "__main__":
    main()
