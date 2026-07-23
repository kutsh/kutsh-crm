## Decision: suivre la levée dans le pipeline Opportunity via un segment `LEVEE` + un champ `tourFinancement`, une opportunité par financeur

Le suivi de levée réutilise l'objet Opportunity et son pipeline unifié : segment
`LEVEE`, les 8 étapes existantes enrichies du vocabulaire de la levée (sourcing →
pitch → term sheet → due diligence → closing), et un SELECT `tourFinancement`
(`PRE_SEED` / `SEED` / `SERIE_A` / `SUBVENTION` / `PRET` / `AUTRE`) qui rattache
chaque ligne à un tour. **Une opportunité = un financeur**, pas un tour. Le
financeur est la Company `categorie = FINANCEUR` ([ADR du même jour](2026-07-23-financeurs-categorie-company.md)),
le ticket va dans le champ standard `amount`, la date visée dans `closeDate`.

## Context

L'ADR `2026-07-23-financeurs-categorie-company` a fait entrer les financeurs dans
le CRM comme Companies typées, en reportant explicitement la question du suivi :
« `Opportunity.segment` vaut `B2G`/`B2B`/`B2B2B` et `stage` porte le vocabulaire
commercial — une levée n'y entre pas ». Elle est tranchée ici.

## Alternatives considered

1. **Objet custom `Levee` / `TourFinancement`** avec ses propres étapes.
2. **Segment `LEVEE` dans le pipeline Opportunity** (retenue).
3. **Une opportunité par tour** (et non par financeur), les fonds en contacts liés.
4. **Hors CRM** — un tableur de suivi de levée, comme beaucoup de fondateurs.

## Reasoning

- **Un cycle de levée est un cycle de vente.** Les 8 étapes existantes se
  remplissent sans forcer : sourcing, fit thèse, pitch, term sheet, due diligence,
  closing, reporting, pass. Ce n'est pas un plaquage : ce sont les mêmes objets
  (une contrepartie, un montant, une date, un interlocuteur, un historique
  d'échanges) et le même besoin (savoir qui est où, et ce qui bloque).
- **Tout l'outillage suit gratuitement** : board kanban, notes et tâches liées,
  `pointOfContact`, et surtout `crm_export.py` qui snapshotte déjà `opportunities`
  — un objet custom aurait demandé de rebâtir tout ça, y compris la sauvegarde.
- **Une ligne par financeur, parce que c'est ce qui bouge.** Un tour n'a pas
  d'étape : ses fonds en ont, chacun la sienne. Modéliser le tour comme
  l'enregistrement obligerait à suivre 15 fonds dans un champ texte. `stage` sur
  le financeur, agrégation sur `tourFinancement` : l'inverse ne marche pas.
- **`tourFinancement` plutôt qu'une convention de nommage** : sans lui, « combien
  est engagé sur le seed » se répond en filtrant des noms de deals à la main, et
  le second tour pollue le premier. C'est le champ minimal qui rend le suivi
  agrégeable — et il sépare le dilutif du non-dilutif, qui ne se somment pas.
- **Pas un tableur** : les fonds se croisent avec le reste du CRM (un financeur
  fait des mises en relation clients, ses associés sont des contacts). Sortir la
  levée du CRM dupliquerait ces personnes.

## Trade-offs accepted

- **`amount` mélange CA et financement.** Une vue « pipeline » naïve additionne un
  ticket d'investissement et un contrat client. Mitigé par un filtre
  `segment ≠ LEVEE`, documenté dans `docs/schema.md` — mais c'est une discipline
  d'usage, pas une garantie technique. C'est le prix du pipeline unifié, déjà
  payé pour `RELAIS`.
- **`tourFinancement` est vide sur 95 % des opportunités** : une colonne inutile
  sur les deals commerciaux. Un objet dédié n'aurait pas ce défaut — mais aurait
  eu tous les autres.
- **Le vocabulaire des étapes s'allonge** : les libellés portent maintenant
  jusqu'à quatre cycles (« Offre (DCE / proposition / POC / term sheet) »). Lisible
  en liste, chargé en en-tête de colonne kanban. Seuil atteint : un sixième segment
  demandera de renoncer aux libellés multi-cycles.
- **Pas de champs de levée fins** : ni valorisation, ni pre/post-money, ni
  pourcentage dilué, ni suivi des documents (pacte, BSA). Volontaire — ces
  informations vivent dans le dossier de levée, pas dans le CRM, tant que le
  besoin est « où en est chaque fonds ».

## Notes d'implémentation

Le script `configure_pipeline.py` faisait un `PATCH` **destructif** des options de
`segment` et `stage` (liste renvoyée sans les `id` existants). Ajouter `LEVEE`
l'aurait fait tourner tel quel sur des opportunités réelles, et Twenty aurait
remplacé les options au lieu de les mettre à jour : segment et étape vidés sur les
fiches en place. La leçon était déjà connue — `configure_company_categorie.py` la
portait en commentaire et en avait sa propre implémentation. Elle est désormais
dans `crm_client.merge_select_options` (testée, utilisée par les deux scripts),
qui préserve les `id`, réaligne les libellés et **conserve en les signalant** les
options que la liste déclarée ne mentionne plus.
