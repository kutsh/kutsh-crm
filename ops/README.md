# `ops/` — points d'entrée historiques du cron kutsh-prod

Ces deux scripts étaient **les points d'entrée réels de la production** et
n'existaient **qu'à un seul endroit** : `~/kutsh-crm/` sur kutsh-prod, hors de
tout dépôt git (`git remote` y répondait « not a repository »). Ils sont
rapatriés ici tels quels, avant tout déclassement de la machine — c'est le point 1
du scope du kata `f154`. Sans ça, ils disparaissent avec le serveur, et avec eux
la seule trace de comment les jobs étaient réellement invoqués.

Ils sont versionnés **pour mémoire**, pas pour être rejoués : la chaîne CRM
tourne désormais sur Prefect (kutsh-batch).

| Script | Cron kutsh-prod | Statut |
|---|---|---|
| `run_export.sh` | hebdomadaire | **Remplacé** par le deployment Prefect `weekly-crm-snapshot` (kutsh-data, `flows/crm_snapshot.py`). Ligne retirée du crontab le 2026-07-20 après un run COMPLETED de bout en bout. |
| `run_qualify.sh` | `30 6 * * *` | **Arrêté le 2026-07-19** — la qualification de leads telle qu'elle était écrite créait un Deal en PROSPECTION pour *toute* personne sans opportunité, ce qui a rempli le pipeline à ~96 % de deals synthétiques (nettoyage : `scripts/purge_auto_leads.py`). Refonte par résolution d'entité côté kutsh-data. |

Le crontab de `joel` sur kutsh-prod est **vide** depuis le 2026-07-20 ; une
sauvegarde reste dans `~/crontab.backup-2026-07-20` sur la machine (rollback =
ré-injecter ce fichier).

## Ce qu'ils apprennent

Les deux suivent le même patron, et c'est ce patron qui compte :

```sh
cd /home/joel/kutsh-crm || exit 1
set -a; . ./.env; set +a          # secrets lus depuis un .env local, jamais versionné
python3 scripts/<script>.py …     # python3 système, pas de venv
```

- **Secrets** : `~/kutsh-crm/.env` sur l'hôte porte `TWENTY_API_KEY`,
  `TWENTY_BASE_URL`, `OPENROUTER_API_KEY`, `BASECAMP_CHATBOT_LINES_URL`. Côté
  Prefect, les deux premières sont déjà injectées dans le worker par Coolify.
  `OPENROUTER_API_KEY` ne l'est **pas** — à prévoir si un jour la qualification
  repasse par un LLM depuis le worker.
- **Pas de venv, pas de verrou** : deux runs pouvaient se chevaucher et se
  partager le quota Twenty de 100 req/60 s. C'est l'hypothèse la plus probable
  des rafales de 429 qui ont vidé trois snapshots consécutifs (kata `dfct`) ;
  les deployments Prefect posent un `concurrency_limit=1` par job.
- **Pas de `MAILTO`, pas de timeout** : la sortie partait dans un `.log` que
  personne ne lisait, et un run bloqué pouvait tourner 20 h sans que rien ne le
  signale. C'est exactement ce que `f154` corrige.
