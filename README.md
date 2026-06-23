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

- `crm_client.py` — abstraction de l'API Twenty (CRUD, upserts métier, pagination). `uv run python crm_client.py selftest`.
- `mcp_server.py` — **serveur MCP** exposant le CRM aux agents (10 outils : contacts, collectivités, opportunités, signaux, notes, lectures). Transport stdio.
- `scripts/` — `import_prospects.py`, `import_campfire_contacts.py`, `configure_pipeline.py`, `export_snapshot.py` (snapshot hebdo, déployé en cron serveur).

## Serveur MCP

Rend le CRM pilotable par Claude. Lancement local :

```bash
TWENTY_API_KEY=… TWENTY_BASE_URL=https://twenty.kutsh.fr uv run kutsh-crm-mcp
```

Enregistrement dans Claude Code :

```bash
claude mcp add kutsh-crm \
  -e TWENTY_API_KEY=… -e TWENTY_BASE_URL=https://twenty.kutsh.fr \
  -- uv run --directory /Users/joel/Dropbox/Kutsh/kutsh-crm kutsh-crm-mcp
```

Outils : `list_crm_objects`, `list_records`, `find_person`, `upsert_contact`, `get_territory`,
`upsert_collectivite`, `create_opportunity`, `update_deal`, `create_signal`, `add_note`.
