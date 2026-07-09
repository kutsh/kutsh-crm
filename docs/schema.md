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
- **Companies** — organisations génériques hors objets custom.
- **Deals** — pipeline commercial, segmenté par `segment` (B2G / B2B / B2B2B).

## Relations principales

- Collectivité 1..n PLUi · Collectivité n..1 Éditeur ADS ✅
- Cabinet n..n Collectivité — **via objet Intervention** (1dhk) ✅
- Éditeur ADS n..n Collectivité (clientes) — couvert par l'inverse de Collectivité n..1 Éditeur ADS ✅
- Signal n..1 {Collectivité, Cabinet, Éditeur ADS, Deal, **Person, Company**} (polymorphe = relations nullables) ✅ (1dhk ; Person/Company ajoutés pour le sourcing LinkedIn — un signal « Post LinkedIn » se relie au contact)
- People n..1 {Collectivité, Cabinet, Éditeur ADS, Company} ✅ (1dhk)
- Deal n..1 {Collectivité, Cabinet} + `segment` ✅ (1dhk)

## Pipeline commercial (Opportunity)

Twenty n'expose qu'**un seul champ `stage`** par objet → on adopte un **pipeline unifié** + un champ `segment` pour distinguer les trois cycles (script : `scripts/configure_pipeline.py`, idempotent). Issue `mfmp`.

**`segment`** (SELECT) : `B2G` · `B2B` · `B2B2B`.

**`stage`** (SELECT, 8 étapes, défaut `PROSPECTION`) — chaque étape porte le vocabulaire des trois cycles :

| `stage` | Label | B2G (marché public) | B2B (SaaS) | B2B2B (API) |
|---|---|---|---|---|
| PROSPECTION | Prospection | veille | lead | contact |
| QUALIFICATION | Qualification | qualification | qualification | qualification |
| ECHANGE | Démo / Échange | échange | démo | échange |
| OFFRE | Offre | DCE / offre | proposition | POC |
| EVALUATION | Audition / Essai | audition | essai | pilote |
| GAGNE | Gagné | notification | abonnement | contrat-cadre |
| EXECUTION | En exécution | exécution du marché | — | — |
| PERDU | Perdu | infructueux / non retenu | churn | abandon |

> Vues filtrées par `segment` (à créer côté UI) pour un board par cycle.
