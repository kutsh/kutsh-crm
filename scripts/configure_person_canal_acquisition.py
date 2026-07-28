#!/usr/bin/env python3
"""Ajoute un champ SELECT `canalAcquisition` sur l'objet People de Twenty.

Trace **par quel canal** un contact est entré dans le CRM. Né du besoin concret
« combien d'inscrits via la landing page ? » — question restée sans réponse
faute d'un champ à filtrer (le seul « source » existant, `crm_brevo.CONTACT_ATTRIBUTES`,
est un attribut Brevo = système d'origine de la synchro, pas le canal marketing ;
`createdBy` vaut `API/claude` pour *tout* ce que crée le bot, landing comprise).

Alimentation :
- **Landing** : `landing/src/lib/twenty.ts` pose `canalAcquisition=LANDING_PAGE`
  à la création du lead (dépôt séparé). Le champ doit donc exister AVANT de
  déployer cette modif, sinon le POST /rest/people est rejeté (champ inconnu).
- **Backfill** : `scripts/backfill_canal_landing.py` (historique Campfire).

Idempotent (crée le champ si absent) et non destructif : les options existantes
sont fusionnées par `crm_client.merge_select_options`, qui préserve leurs `id`
— omettre une option en place, ou la renvoyer sans son `id`, effacerait la
valeur des fiches qui la portent.

Env : TWENTY_API_KEY (+ TWENTY_BASE_URL).
"""
import os, sys, json, argparse, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from crm_client import merge_select_options  # noqa: E402  # type: ignore[import-not-found]

BASE = os.environ.get("TWENTY_BASE_URL", "https://twenty.kutsh.fr").rstrip("/")

# Canaux d'acquisition d'un contact. LANDING_PAGE est le besoin déclencheur ;
# les autres couvrent les sources réelles du CRM (sourcing LinkedIn, imports en
# masse, prospection sortante, événements) pour qu'un SELECT à une seule valeur
# ne force pas une seconde migration au premier contact non-landing.
# Libellés sans virgule : Twenty la refuse (cf. `crm_client._refuse_les_virgules`).
CANAL_OPTIONS = [
    {"value": "LANDING_PAGE", "label": "Landing page", "color": "green"},
    {"value": "LINKEDIN", "label": "LinkedIn", "color": "blue"},
    {"value": "EVENEMENT", "label": "Événement / salon", "color": "purple"},
    {"value": "RECOMMANDATION", "label": "Recommandation", "color": "turquoise"},
    {"value": "PROSPECTION", "label": "Prospection sortante", "color": "orange"},
    {"value": "IMPORT", "label": "Import (fichier / liste)", "color": "gray"},
    {"value": "AUTRE", "label": "Autre", "color": "gray"},
]


def _key():
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


def _field():
    objs = req("GET", "/rest/metadata/objects?limit=200")["data"]["objects"]
    person = next(o for o in objs if o["nameSingular"] == "person")
    fields = req("GET", f"/rest/metadata/objects/{person['id']}")["data"]["object"]["fields"]
    return person, next((f for f in fields if f["name"] == "canalAcquisition"), None)


def _non_declarees(field):
    declarees = {o["value"] for o in CANAL_OPTIONS}
    return [o for o in (field.get("options") or []) if o.get("value") not in declarees]


def check():
    """N'écrit rien. Sort en 1 si le SELECT a dérivé de la liste déclarée."""
    _, field = _field()
    if field is None:
        raise SystemExit("le champ `canalAcquisition` n'existe pas encore — lancer le script sans option")
    inconnues = _non_declarees(field)
    if not inconnues:
        print(f"canalAcquisition: aucune dérive ({len(CANAL_OPTIONS)} valeurs déclarées)")
        return 0
    print(f"⚠️  {len(inconnues)} option(s) présente(s) dans Twenty mais non déclarée(s) :")
    for o in inconnues:
        print(f"    {o.get('value'):<20} « {o.get('label', '')} »")
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="n'écrit rien ; sort en 1 si Twenty porte des options non déclarées")
    a = ap.parse_args()
    if a.check:
        return check()

    person, field = _field()
    if field is None:
        req("POST", "/rest/metadata/fields", {
            "objectMetadataId": person["id"], "name": "canalAcquisition",
            "label": "Canal d'acquisition", "type": "SELECT", "icon": "IconRoute",
            "description": "Par quel canal ce contact est entré dans le CRM (landing, LinkedIn, import…).",
            "options": _positions(CANAL_OPTIONS),
        })
        print(f"canalAcquisition: créé sur People ({len(CANAL_OPTIONS)} valeurs)")
        return 0
    # Champ présent → fusion NON destructive (réutilise les `id` en place).
    current = field.get("options") or []
    connues = {o.get("value") for o in current}
    fusion, orphelines = merge_select_options(current, CANAL_OPTIONS)
    ajoutees = [o["value"] for o in CANAL_OPTIONS if o["value"] not in connues]
    req("PATCH", f"/rest/metadata/fields/{field['id']}", {"options": fusion})
    print(f"canalAcquisition: {len(CANAL_OPTIONS)} valeurs synchronisées"
          + (f", +{len(ajoutees)} nouvelle(s) ({', '.join(ajoutees)})" if ajoutees else ""))
    if orphelines:
        print(f"  ⚠️  {len(orphelines)} option(s) hors liste déclarée, CONSERVÉE(S) : "
              f"{', '.join(o.get('value', '?') for o in orphelines)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
