## Decision: import de prospects LinkedIn dans Twenty via un outil batch du bot Kutsh (kutshbot), avec traçabilité par Signal lié

Félix ou Joël passent au bot Kutsh (Basecamp / Campfire / email) **soit une liste d'URLs LinkedIn, soit un CSV Sales Navigator** ; le bot les upserte dans Twenty (People + Companies liées), enrichit au mieux, et trace la source.

Décisions retenues :

1. **Où vit la logique** : un **outil natif du bot** `crm_import_linkedin_prospects` (repo `kutshbot`, `agent/tools/twenty_import_tools.py`), branché sur le `TwentyApiClient` du bot. Pas de dépendance à `kutsh-crm/crm_client.py` (les deux clients restent des points d'isolation séparés, cf. [2026-06-23-architecture-agentique-crm](2026-06-23-architecture-agentique-crm.md)).
2. **Deux modes d'entrée, un seul outil** :
   - `csv_text` + `column_map` → le CSV Sales Navigator / Evaboot est parsé **côté serveur** (module `csv`). Le LLM fournit juste le mapping colonnes→champs déduit de l'en-tête (peu de tokens, robuste aux variantes d'export).
   - `prospects[]` structuré → pour une liste d'URLs collée, enrichie en amont.
3. **Enrichissement** : best-effort via `web_search` (déjà branché), **orchestré par le LLM** (l'outil reste déterministe). Une URL LinkedIn nue ne peut pas être scrapée de façon fiable (mur de login + CGU) ; on remplit ce que `web_search` trouve avec confiance, sinon on crée un stub marqué « à enrichir ».
4. **Déduplication** : sur l'**URL LinkedIn normalisée** (identifiant stable) en priorité, puis email, puis (prénom, nom). Corrige le trou « dédup par nom seul » de `upsert_contact` quand il n'y a pas d'email.
5. **Traçabilité** : **extension du modèle** — ajout des relations `Signal → Person` et `Signal → Company` (`scripts/create_objects.py`). Chaque prospect **nouvellement créé** génère un Signal `POST_LINKEDIN` **relié au contact** (navigable depuis la fiche). Idempotence : le signal n'est créé qu'au **premier repérage** (personne créée), jamais sur ré-import (personne mise à jour).

## Context: pourquoi cette décision

Repérage de prospects sur LinkedIn (manuel par Félix/Joël, ou export Sales Navigator) sans chemin d'entrée dans Twenty. Le bot est déjà l'interface conversationnelle multi-canaux (Basecamp/Campfire/email) et sait lire des pièces jointes (`basecamp_read_upload` + `file_extraction`, CSV/xlsx gérés). Il possède déjà des outils CRM (`crm_upsert_contact`, `crm_upsert_company` avec dédup domaine/nom, `crm_create_signal`) mais aucun ne portait le lien LinkedIn, le rattachement personne↔société, ni l'ingestion en lot.

## Alternatives considered

- **Généraliser `import_prospects.py` (kutsh-crm) en script CLI** : bon pour un batch/cron, mais pas « appelable par le bot » — le bot tourne en service (Coolify) et n'a pas kutsh-crm sur son PATH ; shell-out cross-repo fragile. Gardé comme chemin batch/Prefect, pas comme surface bot.
- **Boucle d'appels `crm_upsert_contact` / `crm_upsert_company` par le LLM** : 100+ appels d'outils pour un CSV de 50 lignes, sans liaison personne↔société, coûteux et fragile. Rejeté au profit d'un outil batch.
- **Scraping LinkedIn depuis l'URL** : viole les CGU, techniquement bloqué (mur de login), risque de blocage de compte. Rejeté ; enrichissement limité à `web_search` (best-effort) ou service payant ultérieur (Apollo/Clay).
- **Traçabilité par Signal orphelin** : l'objet Signal ne se reliait pas à Person/Company → signal non navigable depuis la fiche. Rejeté au profit de l'extension du modèle.
- **Traçabilité par Note sur la personne** : navigable et déjà en place (`import_prospects.py`), mais ne répond pas au besoin « un signal systématique ». Écarté au profit du Signal lié.

## Reasoning: pourquoi ce découpage l'emporte

- **Appelable par le bot** nativement, sans nouvelle infra ni couplage cross-repo.
- **Scalable** : parsing CSV serveur → un seul appel d'outil pour tout un export, peu de tokens.
- **Idempotent et sûr** : dédup sur l'URL LinkedIn, signal créé une seule fois, sociétés rapprochées (pas de doublon) via la dédup domaine/nom existante.
- **Traçabilité navigable** : Signal `POST_LINKEDIN` lié au contact ; améliore le modèle en général (un post LinkedIn concerne bien une personne).
- **Honnête sur l'enrichissement** : pas de scraping ; ce que `web_search` sait, sinon « à enrichir ».

## Trade-offs accepted

- **Migration métadonnées Twenty** requise avant le premier import (`create_objects.py`, additive/idempotente, deux relations nullables).
- **Logique dupliquée** (mapping LinkedIn) entre le client du bot et `crm_client.py` — assumé : les deux clients sont des points d'isolation distincts (idem `twenty_tools.py` qui ne réimporte pas `crm_client`).
- **Enrichissement partiel** pour les URLs nues (best-effort) : certains prospects resteront « à enrichir » jusqu'à un CSV ou une saisie manuelle.
- **Filtre Twenty sur `linkedinLink.primaryLinkUrl`** (URL avec `:` `/`) potentiellement fragile → dédup best-effort avec repli email/nom.
