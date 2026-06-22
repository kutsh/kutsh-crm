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
