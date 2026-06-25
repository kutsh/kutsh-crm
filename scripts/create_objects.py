#!/usr/bin/env python3
"""Crée (idempotent) les objets custom du CRM Kutsh dans Twenty via l'API metadata.

6 objets : Collectivité, PLUi, Cabinet, Éditeur ADS, Signal + jonction Intervention
(Cabinet × Collectivité, m2m absent nativement de Twenty — issue 1dhk). Plus les
relations MANY_TO_ONE (People/Opportunity/Signal → entités).
Env requis : TWENTY_API_KEY, TWENTY_BASE_URL (def https://twenty.kutsh.fr).
Modèle de référence : ../docs/schema.md. Voir issues kata c2we, 1dhk."""
import os, json, unicodedata, urllib.request

BASE = os.environ.get("TWENTY_BASE_URL", "https://twenty.kutsh.fr").rstrip("/")
KEY = os.environ["TWENTY_API_KEY"]
PALETTE = ["green","turquoise","sky","blue","purple","pink","red","orange","yellow","gray"]

def gql(query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(BASE + "/metadata", data=body, method="POST",
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json",
                 "User-Agent": "kutsh-crm/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read())
    if d.get("errors"):
        raise RuntimeError(json.dumps(d["errors"], ensure_ascii=False))
    return d["data"]

def slug(label):
    s = unicodedata.normalize("NFKD", label).encode("ascii","ignore").decode()
    return "".join(c if c.isalnum() else "_" for c in s).strip("_").upper()

def opts(values):
    return [{"label": v, "value": slug(v), "color": PALETTE[i % len(PALETTE)], "position": i}
            for i, v in enumerate(values)]

OBJECTS = [
 dict(ns="collectivite", np="collectivites", ls="Collectivité", lp="Collectivités", icon="IconBuildingCommunity",
   fields=[
     dict(name="codeInseeSiren", label="Code INSEE/SIREN", type="TEXT"),
     dict(name="typeCollectivite", label="Type", type="SELECT", options=opts(["Commune","EPCI"])),
     dict(name="population", label="Population", type="NUMBER"),
     dict(name="volumeDossiersAn", label="Volume dossiers/an", type="NUMBER"),
     dict(name="statutDocument", label="Statut document", type="SELECT", options=opts(["RNU","PLU","PLUi"])),
     dict(name="dateDerniereRevision", label="Date dernière révision", type="DATE"),
     dict(name="maturiteNumerique", label="Maturité numérique", type="SELECT", options=opts(["Faible","Moyenne","Élevée"])),
   ]),
 dict(ns="plui", np="pluis", ls="PLUi", lp="PLUi", icon="IconMap2",
   fields=[
     dict(name="perimetre", label="Périmètre", type="TEXT"),
     dict(name="dateApprobation", label="Date d'approbation", type="DATE"),
     dict(name="dateDerniereModification", label="Date dernière modification", type="DATE"),
     dict(name="lienGpu", label="Lien GPU", type="LINKS"),
     dict(name="statutSru", label="Statut SRU", type="TEXT"),
     dict(name="complexiteEstimee", label="Complexité estimée", type="SELECT", options=opts(["Faible","Moyenne","Élevée"])),
   ]),
 dict(ns="cabinet", np="cabinets", ls="Cabinet", lp="Cabinets", icon="IconRulerMeasure",
   fields=[
     dict(name="zoneIntervention", label="Zone d'intervention", type="TEXT"),
     dict(name="volumeEstimeDossiers", label="Volume estimé dossiers", type="NUMBER"),
     dict(name="tauxRefus", label="Taux de refus (%)", type="NUMBER"),
   ]),
 dict(ns="editeurAds", np="editeursAds", ls="Éditeur ADS", lp="Éditeurs ADS", icon="IconDatabase",
   fields=[
     dict(name="partMarcheEstimee", label="Part de marché estimée (%)", type="NUMBER"),
     dict(name="potentielIntegrationApi", label="Potentiel intégration API", type="SELECT", options=opts(["Faible","Moyen","Élevé"])),
   ]),
 dict(ns="signal", np="signals", ls="Signal", lp="Signaux", icon="IconBolt",
   fields=[
     dict(name="typeSignal", label="Type", type="SELECT", options=opts(["Révision PLUi","Marché public","Post LinkedIn","Refus dossier","Renouvellement ADS"])),
     dict(name="dateSignal", label="Date", type="DATE_TIME"),
     dict(name="actionSuggeree", label="Action suggérée", type="TEXT"),
     dict(name="statut", label="Statut", type="SELECT", options=opts(["Nouveau","Traité","Ignoré"])),
   ]),
 # Objet de jonction Cabinet <-> Collectivité (m2m, absent nativement de Twenty) — issue 1dhk.
 dict(ns="intervention", np="interventions", ls="Intervention", lp="Interventions", icon="IconArrowsLeftRight",
   fields=[
     dict(name="typeIntervention", label="Rôle", type="SELECT", options=opts(["Dessinateur-projeteur","Architecte","AMO","Autre"])),
   ]),
]

# relations MANY_TO_ONE : (objet source, nom champ, label, objet cible, label champ inverse, icône)
RELATIONS = [
 ("collectivite","editeurAds","Éditeur ADS","editeurAds","Collectivités","IconDatabase"),
 ("collectivite","plui","PLUi","plui","Collectivités","IconMap2"),
 # Jonction Cabinet <-> Collectivité (m2m via Intervention) — issue 1dhk.
 ("intervention","cabinet","Cabinet","cabinet","Interventions","IconRulerMeasure"),
 ("intervention","collectivite","Collectivité","collectivite","Interventions","IconBuildingCommunity"),
 # Contacts : People n..1 {Collectivité, Cabinet, Éditeur ADS} — issue 1dhk.
 ("person","collectivite","Collectivité","collectivite","Contacts","IconBuildingCommunity"),
 ("person","cabinet","Cabinet","cabinet","Contacts","IconRulerMeasure"),
 ("person","editeurAds","Éditeur ADS","editeurAds","Contacts","IconDatabase"),
 # Deals : Opportunity n..1 {Collectivité, Cabinet} — issue 1dhk (segment déjà posé).
 ("opportunity","collectivite","Collectivité","collectivite","Opportunités","IconBuildingCommunity"),
 ("opportunity","cabinet","Cabinet","cabinet","Opportunités","IconRulerMeasure"),
 # Signaux : Signal n..1 {Collectivité, Cabinet, Éditeur ADS, Deal} (polymorphe = relations
 # nullables, l'idiome Twenty) — issue 1dhk. Relie les signaux d5td aux territoires.
 ("signal","collectivite","Collectivité","collectivite","Signaux","IconBuildingCommunity"),
 ("signal","cabinet","Cabinet","cabinet","Signaux","IconRulerMeasure"),
 ("signal","editeurAds","Éditeur ADS","editeurAds","Signaux","IconDatabase"),
 ("signal","opportunity","Opportunité","opportunity","Signaux","IconTargetArrow"),
]

def fetch_objects():
    q = "{ objects(paging:{first:200}){ edges { node { id nameSingular fields(paging:{first:200}){ edges { node { name } } } } } } }"
    out = {}
    for e in gql(q)["objects"]["edges"]:
        n = e["node"]
        out[n["nameSingular"]] = {"id": n["id"], "fields": {f["node"]["name"] for f in n["fields"]["edges"]}}
    return out

def main():
    objs = fetch_objects()
    # 1) objets
    for o in OBJECTS:
        if o["ns"] in objs:
            print(f"= objet {o['ns']} existe ({objs[o['ns']]['id']})")
            continue
        d = gql("mutation($input:CreateOneObjectInput!){createOneObject(input:$input){id nameSingular}}",
                {"input":{"object":{"nameSingular":o["ns"],"namePlural":o["np"],
                  "labelSingular":o["ls"],"labelPlural":o["lp"],"icon":o["icon"],"isLabelSyncedWithName":False}}})
        print(f"+ objet créé {o['ns']} -> {d['createOneObject']['id']}")
    objs = fetch_objects()
    # 2) champs scalaires
    for o in OBJECTS:
        oid = objs[o["ns"]]["id"]; have = objs[o["ns"]]["fields"]
        for f in o["fields"]:
            if f["name"] in have:
                print(f"  = {o['ns']}.{f['name']} existe"); continue
            fi = {"objectMetadataId":oid,"type":f["type"],"name":f["name"],"label":f["label"],"isNullable":True}
            if "options" in f: fi["options"] = f["options"]
            gql("mutation($input:CreateOneFieldMetadataInput!){createOneField(input:$input){id name}}", {"input":{"field":fi}})
            print(f"  + {o['ns']}.{f['name']} ({f['type']})")
    objs = fetch_objects()
    # 3) relations
    for src, fname, flabel, tgt, tlabel, ticon in RELATIONS:
        if fname in objs[src]["fields"]:
            print(f"  = relation {src}.{fname} existe"); continue
        fi = {"objectMetadataId":objs[src]["id"],"type":"RELATION","name":fname,"label":flabel,"icon":ticon,"isNullable":True,
              "relationCreationPayload":{"targetObjectMetadataId":objs[tgt]["id"],"type":"MANY_TO_ONE",
                                          "targetFieldLabel":tlabel,"targetFieldIcon":OBJECTS[0]["icon"]}}
        gql("mutation($input:CreateOneFieldMetadataInput!){createOneField(input:$input){id name}}", {"input":{"field":fi}})
        print(f"  + relation {src}.{fname} (MANY_TO_ONE -> {tgt})")
    print("OK")

if __name__ == "__main__":
    main()
