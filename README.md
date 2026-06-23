# kutsh-crm

Couche Python du CRM Kutsh — le **moteur d'intelligence commerciale** adossé à [Twenty](https://twenty.com) (self-hosted, `twenty.kutsh.fr`).

Twenty est l'interface de consultation ; **ce repo est la source de vérité métier** : abstraction d'API (`crm_client.py`), base PostgreSQL enrichie, monitoring (GPU/SITADEL/BOAMP/LinkedIn), export hebdomadaire versionné.

## Repères

- **Cadrage** : doc Outline « Cadrage CRM Kutsh » + message Basecamp du 2026-05-06 (`Prospects et partenaires`).
- **Choix de Twenty** : [`decisions/2026-06-22-choix-twenty-crm.md`](decisions/2026-06-22-choix-twenty-crm.md).
- **Schéma de données** : [`docs/schema.md`](docs/schema.md).
- **Suivi des tâches** : tracker kata, projet `kutsh-crm` (`kata list`, `kata ready`).

## Architecture

```
Twenty (vue, self-hosted Coolify)  <--REST/GraphQL-->  couche Python (source de vérité)
                                                        crm_client.py · PostgreSQL · cron/DVC
```

Principe : changer de CRM = repointer `crm_client.py`. Les données métier ne bougent pas.

## Composants

- `crm_client.py` — abstraction de l'API Twenty (CRUD, upserts idempotents métier, pagination). Stdlib pur. Point d'isolation anti-lock-in + socle des scripts batch.
- `scripts/` — `import_prospects.py`, `import_campfire_contacts.py`, `configure_pipeline.py`, `export_snapshot.py` (snapshot hebdo, déployé en cron serveur).

## Pilotage par agents (MCP)

Twenty expose un **serveur MCP natif** (HTTP, joignable y compris par les routines cloud) — pas de serveur custom à maintenir. Enregistrement dans Claude :

```json
{
  "mcpServers": {
    "twenty": {
      "url": "https://twenty.kutsh.fr/mcp",
      "headers": { "Authorization": "Bearer <TWENTY_API_KEY>" }
    }
  }
}
```

Il offre le CRUD complet sur tous les objets (`find_many_*`, `create_*`, `update_*`…) plus des actions (`send_email`, `draft_email`, `navigate_app`), des skills et la recherche dans la doc.

> `crm_client.py` reste pour les opérations **batch déterministes / idempotentes** (imports, configuration, export hebdo) — complémentaire du MCP, pas redondant.
