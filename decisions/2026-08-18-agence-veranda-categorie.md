## Decision: adopter `AGENCE_VERANDA` telle quelle (libellé d'origine) et la router vers le segment newsletter `PROS`

La catégorie `AGENCE_VERANDA`, créée dans l'UI de Twenty et portée par 206
Companies, est déclarée dans `CATEGORIE_OPTIONS`
(`scripts/configure_company_categorie.py`) avec son libellé d'origine « Agence
véranda (pose / installation) », et mappée vers le segment `PROS` de
`crm_brevo.py`. Elle n'est **pas** fusionnée dans `FABRICANT` ni `INSTALLATEUR`.

## Context

L'audit de dérive (`audit_categories`, cron Prefect kutsh-data) a remonté le
2026-08-18 une catégorie non déclarée : `AGENCE_VERANDA`, 206 fiches. Le CRM
compte 987 Companies : c'est **la première catégorie du CRM en volume** après le
non-typé (370). Origine : un import par Workflow Twenty le 2026-08-11
(`createdBy.source = WORKFLOW`), qui a créé 206 organisations et 228 People
(`canalAcquisition = IMPORT`, 145 avec email) — poseurs et réseaux de vérandas
(VIE ET VERANDA, Vérandaline, PERGOLA NORMANDE, menuisiers…).

Conséquence tant que la catégorie reste non déclarée : ces 145 contacts
adressables n'entrent dans aucun segment et ne reçoivent aucune lettre, en
silence — exactement le défaut que l'ADR
[`2026-07-23-categories-ui-vs-code.md`](2026-07-23-categories-ui-vs-code.md) a
outillé.

## Alternatives considered

1. **Fusionner dans `FABRICANT`** — dont le libellé mentionne déjà « véranda ·
   abri · pergola ».
2. **Fusionner dans `INSTALLATEUR`** — le métier est bien la pose.
3. **Adopter `AGENCE_VERANDA` telle quelle, segment `PROS`** (retenue).
4. **Déclarer hors newsletter** (`CATEGORIES_HORS_NEWSLETTER`) — le temps de
   qualifier l'import.

## Reasoning

- **La règle de l'ADR du 2026-07-23 s'applique sans exception à faire** : le
  vocabulaire naît de l'usage, on prend son libellé, on ne le réécrit pas. Le
  rapport de force est encore plus net qu'alors : 206 fiches contre 38 pour
  `FABRICANT` et 5 pour `INSTALLATEUR`.
- **La distinction est réelle, pas cosmétique.** `FABRICANT` est le
  fabricant/revendeur (cible B2B2B : son réseau de revendeurs, son
  configurateur) ; `AGENCE_VERANDA` est l'agence qui pose chez le particulier —
  c'est elle qui se heurte au PLU sur un chantier. `INSTALLATEUR` porte un
  libellé explicitement autre (« solaire · PAC · piscine »). Fusionner aurait
  écrasé une segmentation commerciale utile pour économiser une valeur de SELECT.
- **`PROS` est le bon segment** : même public que `FABRICANT`, `CONSTRUCTEUR`,
  `INSTALLATEUR` — un pro du chantier à qui la lettre parle du risque
  réglementaire avant le devis. Aucun argument pour une quatrième newsletter à
  206 fiches.
- **Hors newsletter (option 4) aurait été un faux prudent** : l'exclusion
  explicite est faite pour des publics qu'on décide de ne pas adresser
  (`AUTRE`, `FINANCEUR`), pas pour gagner du temps sur une qualification. Elle
  aurait rendu le silence *légitime* au lieu de le lever.

## Trade-offs accepted

- **On fait confiance au typage de l'import** sans avoir requalifié les 206
  fiches une à une : si le Workflow du 11/08 a rangé là des fabricants ou des
  menuisiers généralistes, ils recevront la lettre « pros » — la même que celle
  qu'ils auraient reçue via `FABRICANT`. Le risque de mauvais adressage est donc
  nul en pratique tant que ces catégories partagent un segment ; il redeviendrait
  réel le jour où `AGENCE_VERANDA` aurait sa propre lettre.
- **145 contacts sur 228 seulement sont adressables** (email renseigné) : adopter
  la catégorie ne suffit pas à toucher le public importé, il manque
  l'enrichissement des 83 autres. Hors scope ici.
- **Le SELECT passe à 25 valeurs.** La prolifération continue ; le test de
  couverture empêche l'oubli, pas l'inflation.
- **`scripts/qualify_leads.py` n'est pas mis à jour** : sa liste `CATEGORIES` est
  déjà en retard des adoptions du 2026-07-23, et le script est arrêté depuis le
  2026-07-19 (cf. [`ops/README.md`](../ops/README.md)) — la refonte se fait côté
  kutsh-data. Le remettre à jour ici entretiendrait un mort.
