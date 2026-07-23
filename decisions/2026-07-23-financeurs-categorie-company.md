## Decision: suivre les financeurs de Kutsh comme une valeur `FINANCEUR` du SELECT `Company.categorie`, hors périmètre newsletter

Les investisseurs et financeurs de Kutsh (fonds, business angels, BPI, financeurs
publics/subventions) entrent dans le CRM comme des Companies typées
`categorie = FINANCEUR`, et non comme un objet custom dédié. La catégorie est
déclarée explicitement **hors newsletter** (`CATEGORIES_HORS_NEWSLETTER` dans
`crm_brevo.py`), au même titre que `AUTRE`.

## Context

Le CRM typait jusqu'ici des organisations de la **chaîne de valeur urbanisme** :
cibles directes (collectivités, cabinets), relais/prescripteurs (fédérations,
réseaux d'élus) et segments aval (GSB, constructeurs, installateurs, agences
immo, courtiers). Les financeurs de la boîte n'y avaient pas de place : ni
prospects, ni prescripteurs, ils étaient soit absents, soit rangés en `AUTRE` —
donc indistinguables du fourre-tout.

## Alternatives considered

1. **Objet custom `Financeur`** — comme `Cabinet` ou `Éditeur ADS`.
2. **Valeur `FINANCEUR` du SELECT `categorie`** (retenue).
3. **CRM/tableur séparé pour la levée** — sortir le fundraising du CRM.
4. **Rester sur `AUTRE`** — ne rien ajouter, filtrer à la main.

## Reasoning

- **Volumétrie et champs** : un financeur se décrit avec ce que porte déjà
  Company (nom, domaine, contacts liés, notes). Aucun champ propre ne justifie
  un objet — pas de `ticket`, `thèse d'investissement` ou `stade` à modéliser
  aujourd'hui. C'est exactement l'argument qui a fait choisir un champ plutôt
  qu'un objet `Federation` pour les prescripteurs (script
  `configure_company_categorie.py`) : « léger, promouvable plus tard ».
- **Un seul endroit où sont les contacts** : la relation avec un financeur passe
  par des personnes, déjà modélisées en People n..1 Company. Un CRM séparé
  dupliquerait les contacts (certains financeurs sont aussi des mises en
  relation clients) sans rien apporter.
- **`AUTRE` ne se filtre pas** : `AUTRE` est délibérément le fourre-tout non
  ciblé ; y ranger les financeurs revient à ne pas pouvoir en tirer une liste.
- **Exclusion newsletter explicite plutôt qu'implicite** : le mapping
  `CATEGORIE_TO_SEGMENT` faisait retomber toute catégorie non mappée hors
  newsletter en silence (trade-off assumé de l'ADR 2026-07-07). Correct pour le
  résultat, illisible pour l'intention : rien ne distinguait « décidé hors
  périmètre » de « jamais mappé ». D'où `CATEGORIES_HORS_NEWSLETTER` + un test
  de couverture qui exige que **toute** valeur du SELECT soit dans l'un des deux
  ensembles.

## Trade-offs accepted

- **Financeurs et prospects dans la même typologie** : une vue « toutes les
  Companies » mélange désormais deux populations sans rapport. Mitigé par le
  filtre sur `categorie` côté Twenty.
- **Pas de pipeline de levée** : `Opportunity.segment` vaut `B2G`/`B2B`/`B2B2B`
  et `stage` porte le vocabulaire commercial — une levée n'y entre pas. Les
  financeurs sont donc suivis en contacts/notes, pas en deals. Si le suivi de
  levée devient un vrai processus (étapes, montants, dates), il faudra soit un
  segment `LEVEE` avec son propre vocabulaire d'étapes, soit un objet dédié —
  décision reportée jusqu'à ce que le besoin soit réel.
- **Une catégorie de plus à maintenir** : le SELECT approche la vingtaine de
  valeurs. Le test de couverture empêche l'oubli côté newsletter, pas la
  prolifération elle-même.
