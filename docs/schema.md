# Schéma de données — CRM Kutsh (Twenty)

Source de vérité du modèle. Versionné ici ; reflété dans Twenty via l'API (`crm_client.py`). Toute évolution du modèle passe par ce fichier d'abord.

## Objets custom

### Collectivité
Commune ou EPCI — cœur de cible B2G.

| Champ | Type | Source | Notes |
|-------|------|--------|-------|
| nom | text | manuel / DGCL | |
| code_insee / siren | text | DGCL | identifiant pivot |
| type | select | DGCL | commune \| EPCI |
| population | number | INSEE/DGCL | |
| editeur_ads | relation → Éditeur ADS | enrichissement | éditeur en place |
| plui | relation → PLUi | enrichissement | PLUi applicable |
| volume_dossiers_an | number | SITADEL | dossiers d'urbanisme/an |
| statut_doc | select | GPU | RNU \| PLU \| PLUi |
| date_derniere_revision | date | GPU | |
| maturite_numerique | select | estimation | faible \| moyenne \| élevée |

### PLUi
Document d'urbanisme.

| Champ | Type | Source | Notes |
|-------|------|--------|-------|
| nom | text | GPU | |
| perimetre | text/geo | GPU | périmètre géographique |
| date_approbation | date | GPU | |
| date_derniere_modification | date | GPU | |
| lien_gpu | url | GPU | |
| statut_sru | select | GPU | |
| complexite_estimee | select | scoring | faible \| moyenne \| élevée |

### Cabinet
Dessinateur-projeteur / architecte — cible B2B.

| Champ | Type | Source | Notes |
|-------|------|--------|-------|
| nom | text | manuel | |
| zone_intervention | text | manuel/LinkedIn | |
| volume_estime_dossiers | number | estimation | |
| collectivites_servies | relation → Collectivité (n..n) | enrichissement | |
| taux_refus | number | si connu | indicateur d'opportunité |

### Éditeur ADS
Cart@DS, Oxalis, NetADS, Next'ADS, openADS…

| Champ | Type | Source | Notes |
|-------|------|--------|-------|
| nom | text | manuel | |
| collectivites_clientes | relation → Collectivité (n..n) | enrichissement | |
| part_marche_estimee | number | estimation | |
| potentiel_integration_api | select | analyse | faible \| moyen \| élevé |

### Signal
Événement détecté par le monitoring (Phase 3).

| Champ | Type | Source | Notes |
|-------|------|--------|-------|
| type | select | monitoring | révision PLUi \| marché public \| post LinkedIn \| refus dossier |
| date | date | monitoring | |
| entites_liees | relation (polymorphe) | monitoring | Collectivité / Cabinet / Éditeur ADS / Person / Company… |
| action_suggeree | text | scoring | brief / appel / réponse AO |
| statut | select | workflow | nouveau \| traité \| ignoré |

### Intervention (objet de jonction — issue 1dhk)
Réalise le many-to-many **Cabinet ↔ Collectivité** (absent nativement de Twenty).
Chaque ligne = un cabinet intervenant pour une collectivité.

| Champ | Type | Source | Notes |
|-------|------|--------|-------|
| cabinet | relation → Cabinet (n..1) | manuel/enrichissement | |
| collectivite | relation → Collectivité (n..1) | manuel/enrichissement | |
| typeIntervention | select | manuel | dessinateur-projeteur \| architecte \| AMO \| autre |

## Objets standard Twenty (conservés)

- **People** — contacts individuels (interlocuteurs collectivités, cabinets…).
  Typés par le SELECT `canalAcquisition` (par quel canal le contact est entré :
  `LANDING_PAGE` · `LINKEDIN` · `EVENEMENT` · `RECOMMANDATION` · `PROSPECTION` ·
  `IMPORT` · `AUTRE` — cf. [`decisions/2026-07-28-canal-acquisition-people.md`](../decisions/2026-07-28-canal-acquisition-people.md)).
  Liste de référence : `scripts/configure_person_canal_acquisition.py` (`CANAL_OPTIONS`),
  idempotent. Alimenté à la source par la landing (`landing/src/lib/twenty.ts`,
  dépôt séparé) et rétro-rempli depuis le Campfire par `scripts/backfill_canal_landing.py`.
- **Companies** — organisations génériques hors objets custom. Typées par le SELECT
  `categorie` (relais/prescripteurs, segments aval, écosystème, `FINANCEUR` pour les
  investisseurs/financeurs de Kutsh — cf. [`decisions/2026-07-23-financeurs-categorie-company.md`](../decisions/2026-07-23-financeurs-categorie-company.md)).
  Liste de référence : `scripts/configure_company_categorie.py` (`CATEGORIE_OPTIONS`),
  idempotent ; elle pilote aussi la segmentation newsletter (`crm_brevo.py`).
- **Deals** — pipeline commercial, segmenté par `segment` (B2G / B2B / B2B2B).

## Relations principales

- Collectivité 1..n PLUi · Collectivité n..1 Éditeur ADS ✅
- Cabinet n..n Collectivité — **via objet Intervention** (1dhk) ✅
- Éditeur ADS n..n Collectivité (clientes) — couvert par l'inverse de Collectivité n..1 Éditeur ADS ✅
- Signal n..1 {Collectivité, Cabinet, Éditeur ADS, Deal, **Person, Company**} (polymorphe = relations nullables) ✅ (1dhk ; Person/Company ajoutés pour le sourcing LinkedIn — un signal « Post LinkedIn » se relie au contact)
- People n..1 {Collectivité, Cabinet, Éditeur ADS, Company} ✅ (1dhk)
- Deal n..1 {Collectivité, Cabinet} + `segment` ✅ (1dhk)

## Pipeline (Opportunity)

Twenty n'expose qu'**un seul champ `stage`** par objet → on adopte un **pipeline unifié** + un champ `segment` pour distinguer les cycles (script : `scripts/configure_pipeline.py`, idempotent). Issue `mfmp`.

**`segment`** (SELECT) : `B2G` · `B2B` · `B2B2B` · `RELAIS` (partenariat prescripteur) · `LEVEE` (financement de Kutsh — cf. [`decisions/2026-07-23-suivi-levee-pipeline.md`](../decisions/2026-07-23-suivi-levee-pipeline.md)).

**`stage`** (SELECT, 8 étapes, défaut `PROSPECTION`) — chaque étape porte le vocabulaire de chaque cycle :

| `stage` | Label | B2G (marché public) | B2B (SaaS) | B2B2B (API) | LEVEE (financement) |
|---|---|---|---|---|---|
| PROSPECTION | Prospection | veille | lead | contact | sourcing / mise en relation |
| QUALIFICATION | Qualification | qualification | qualification | qualification | fit thèse d'investissement |
| ECHANGE | Démo / Échange | échange | démo | échange | pitch (partner meeting) |
| OFFRE | Offre | DCE / offre | proposition | POC | term sheet |
| EVALUATION | Audition / Essai | audition | essai | pilote | due diligence |
| GAGNE | Gagné | notification | abonnement | contrat-cadre | closing / signature |
| EXECUTION | En exécution | exécution du marché | — | — | reporting investisseur |
| PERDU | Perdu | infructueux / non retenu | churn | abandon | pass |

> Vues filtrées par `segment` (à créer côté UI) pour un board par cycle.
> ⚠️ Les vues de **prévision commerciale doivent exclure `segment = LEVEE`** : un ticket
> d'investissement vit dans `amount` comme un contrat, et gonflerait le CA prévisionnel.

### Suivi de levée (`segment = LEVEE`)

Une opportunité = **un financeur**, pas un tour : c'est la granularité qui bouge (chaque fonds a son étape). Le tour se reconstitue par agrégation sur `tourFinancement`.

| Champ | Type | Notes |
|-------|------|-------|
| tourFinancement | select | `PRE_SEED` \| `SEED` \| `SERIE_A` \| `SUBVENTION` \| `PRET` \| `AUTRE`. Vide hors `LEVEE`. |
| company | relation → Company | le financeur, `categorie = FINANCEUR` |
| pointOfContact | relation → Person | l'interlocuteur (partner, chargé d'affaires BPI…) |
| amount | currency (standard) | ticket envisagé, puis engagé |
| closeDate | date (standard) | date de closing visée |

Montant engagé d'un tour = somme des `amount` des opportunités `LEVEE` du tour en `GAGNE` ; le pipeline restant, les mêmes hors `GAGNE`/`PERDU`.
