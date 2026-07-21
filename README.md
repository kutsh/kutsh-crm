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

- `crm_client.py` — abstraction de l'API Twenty (CRUD, upserts idempotents métier, pagination). Stdlib pur. Point d'isolation anti-lock-in + socle des scripts batch. **Seul client Twenty de l'écosystème** : kutsh-data en portait une copie divergente, supprimée (kata `jnnf`, cf. [`decisions/2026-07-21-client-twenty-unique.md`](decisions/2026-07-21-client-twenty-unique.md)).
- `crm_export.py`, `crm_brevo.py` — les deux autres modules packagés (snapshot anti lock-in, sync newsletter). Cf. ci-dessous.
- `scripts/` — `import_prospects.py`, `import_campfire_contacts.py`, `configure_pipeline.py`, `purge_auto_leads.py`, façades CLI (`export_snapshot.py`, `sync_twenty_brevo.py`) + `configure_newsletter_fields.py` et `enrich_newsletter_contacts.py`.
- `ops/` — points d'entrée historiques du cron kutsh-prod, rapatriés pour mémoire. Cf. [`ops/README.md`](ops/README.md).

Les trois modules racine (`crm_client`, `crm_export`, `crm_brevo`) constituent le
wheel ; c'est par eux que les autres services consomment ce dépôt :

```bash
uv add "kutsh-crm @ git+https://github.com/kutsh/kutsh-crm.git"
```

## Snapshot d'export (anti lock-in)

`crm_export.py` dumpe tous les objets du CRM en JSONL, archive en `.tar.gz` daté
et applique une rétention.

C'est un **module packagé** (comme `crm_client`), pour qu'un orchestrateur puisse
l'appeler sans qu'on ait à copier un fichier sur une machine :

```python
from crm_export import run
archive, healthy = run(out_dir, keep=12, stamp="2026-07-20")
```

`scripts/export_snapshot.py` reste une façade CLI équivalente, et
`python -m crm_export` fonctionne aussi.

**Contrat de sortie** — un backup vide doit être bruyant :

| Code | Situation |
|---|---|
| `0` | snapshot sain ; rétention appliquée |
| `1` | snapshot **dégradé** : un objet illisible, un objet passé de N>0 à 0 depuis le snapshot précédent, ou total à 0. L'archive est **conservée** (on ne jette pas de la donnée) mais la **rétention est suspendue** — un backup dégradé ne peut pas évincer les bons. |

Une chute de plus de moitié sur un objet d'au moins 100 enregistrements est
signalée en `ATTENTION` sur stderr sans faire échouer le run : une purge
légitime (`purge_auto_leads.py`) en produit.

> Incident 2026-07-20 : pendant trois semaines, les snapshots n'ont contenu qu'un
> seul objet sur treize — les douze autres échouaient en HTTP 429. Le manifeste
> enregistrait déjà ces erreurs, mais le script ne les relisait pas : il
> imprimait « OK snapshot » et sortait en 0. Trois semaines de backups
> inexploitables sans la moindre alerte. Les fixtures de test reproduisent la
> structure de ces manifestes (effectifs synthétiques, dépôt public).

```bash
python -m unittest discover -s tests    # stdlib pur, aucune dépendance
```

## Newsletter → Brevo

Diffusion des lettres d'information segmentées via Brevo, alimentées depuis Twenty.
Décision : [`decisions/2026-07-07-crm-brevo-newsletter-sync.md`](decisions/2026-07-07-crm-brevo-newsletter-sync.md).

- **Segmentation** : le segment d'un contact (→ liste Brevo) est déduit de son
  organisation : relation custom (`cabinetId`→Pros, `collectiviteId`→Collectivités,
  `editeurAdsId`→Écosystème), sinon `Company.categorie`, avec **override explicite**
  par le champ Person `newsletterSegment`. Mapping dans `SEGMENTS` (`crm_brevo.py`).
- **RGPD** : soft opt-in (désinscription 1-clic dans chaque lettre) ; les désinscrits
  Brevo sont **rapatriés** dans Twenty (`newsletterOptOut`) — jamais re-sollicités.
- **Attributs de contact** : `PRENOM`, `NOM`, `SOURCE`, `SEGMENT` (`CONTACT_ATTRIBUTES`),
  créés dans Brevo par `ensure_attributes` avant tout import. ⚠️ Brevo n'accepte que
  les attributs **déclarés dans le schéma du compte** et **jette les autres en
  silence** : l'import rend un `processId`, le processus passe `completed`, la
  valeur disparaît. Au premier run réel (2026-07-21), 376 contacts sont partis avec
  `SOURCE` et `SEGMENT` vides sans une ligne d'erreur. D'où la relecture du schéma
  après création, plutôt qu'une confiance au code retour du POST.
- **Gabarits** : `newsletters/*.html` (Collectivités / Pros / Écosystème).

C'est un **module packagé** (comme `crm_export`), appelable depuis un orchestrateur :

```python
from crm_brevo import run
summary = run("all")     # {"reconcile": {...}, "sync": {...}}
```

```bash
# env : TWENTY_API_KEY + BREVO_API_KEY (+ BREVO_SENDER_EMAIL). cf. .env.example
python -m crm_brevo plan                       # dry-run : compte par liste, 0 écriture
python -m crm_brevo all                         # reconcile (opt-out) puis sync
python scripts/sync_twenty_brevo.py drafts      # (re)crée les 3 brouillons de campagne
python scripts/enrich_newsletter_contacts.py --apply   # enrichit Twenty (contacts validés)
```

`scripts/sync_twenty_brevo.py` reste une façade CLI équivalente, à ceci près que
son `ensure` joue d'abord `configure_newsletter_fields.py` (migration de schéma
Twenty, une fois pour toutes) — le module, lui, ne touche qu'à Brevo.

`all` est l'enchaînement destiné à l'orchestrateur (jamais `drafts`, qui reste
manuel et a besoin de `newsletters/*.html`, absent du wheel). Le deployment
Prefect `crm-brevo-sync` (kutsh-data) est **sans cron** : il se déclenche à la
main. Un envoi vers un service externe ne se met pas en pilote automatique par
effet de bord d'un chantier d'orchestration — c'est une décision à part.

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
