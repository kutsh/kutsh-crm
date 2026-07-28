## Decision: champ SELECT `canalAcquisition` sur People

Ajout d'un champ `canalAcquisition` (SELECT) sur l'objet People de Twenty, avec
les valeurs `LANDING_PAGE`, `LINKEDIN`, `EVENEMENT`, `RECOMMANDATION`,
`PROSPECTION`, `IMPORT`, `AUTRE`. Créé/synchronisé par le script idempotent
`scripts/configure_person_canal_acquisition.py`. Alimenté à la source par la
landing et rétro-rempli depuis le Campfire.

## Context: pourquoi ça vient sur la table

Félix a demandé dans le Campfire « combien de personnes se sont inscrites via la
landing page depuis sa mise en place ? ». Question restée sans réponse fiable :
aucun champ ne trace le canal d'entrée d'un contact. Les faux amis :
- `crm_brevo.CONTACT_ATTRIBUTES["SOURCE"]` est un attribut **Brevo** = système
  d'origine de la synchro (vaut `"twenty"`), pas le canal marketing ;
- `person.createdBy` vaut `{source: API, name: "claude"}` pour **tout** ce que le
  bot crée (landing, sourcing LinkedIn, saisie agent) — il ne discrimine rien.

## Alternatives considered

1. **Champ texte libre `source`** — rapide, mais pas d'agrégation fiable
   (fautes de frappe, variantes) ; un « combien via la landing ? » resterait
   approximatif.
2. **Objet custom `Canal` en relation** — surdimensionné : un canal est une
   étiquette, pas une entité avec ses attributs et son cycle de vie.
3. **Filtrer par `createdBy`/date de création** — ne marche pas : createdBy est
   identique pour toutes les créations bot ; la date ne dit pas le canal.
4. **SELECT `canalAcquisition`** — retenu.

## Reasoning: pourquoi le SELECT

- Agrégat propre et filtrable (le besoin déclencheur est un **comptage**).
- Même patron que `Company.categorie` : script idempotent + `merge_select_options`
  non destructif, doc dans `schema.md`. Cohérence de maintenance.
- Valeurs au-delà de `LANDING_PAGE` dès le départ (LinkedIn, import, prospection,
  événement) : un SELECT mono-valeur forcerait une 2ᵉ migration au premier
  contact non-landing, alors que ces canaux existent déjà dans le CRM.
- Alimentation **à la source** (`landing/src/lib/twenty.ts` pose la valeur à la
  création du lead) plutôt qu'un rattrapage périodique : le canal est connu au
  moment exact de l'entrée, nulle part mieux qu'à ce point.

## Trade-offs accepted

- **Ordre de déploiement contraint** : le champ doit exister côté Twenty AVANT
  de déployer la modif landing, sinon le POST /rest/people (champ inconnu) est
  rejeté et le lead n'est pas créé. Séquencer : script CRM d'abord, deploy
  landing ensuite.
- **Backfill non exhaustif** : 8 des 40 contacts landing signalés au Campfire
  n'existent pas dans le CRM (entrés avant l'intégration landing→Twenty, ou
  upsert échoué) — ils ne sont pas rattrapables par email. Le total historique
  « depuis la mise en ligne » reste donc à confirmer côté outil de formulaire
  (Plausible/Tally), pas seulement via le CRM.
- **Deux dépôts à faire évoluer ensemble** (kutsh-crm + landing) : couplage
  assumé, le champ n'a de valeur que s'il est alimenté.
