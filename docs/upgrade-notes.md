# Notes d'upgrade Twenty (self-hosted Coolify)

## Procédure générale

1. **Backup d'abord** : `docker exec <pg> pg_dump -U $POSTGRES_USER -d $POSTGRES_DB -Fc > dump`.
2. Cross-version supporté **à partir de v1.22** uniquement. Avant v1.22 → montée **palier par palier** (chaque version mineure) jusqu'à v1.22, puis saut direct vers la dernière.
3. Avant **v2.5** : poser `ENCRYPTION_KEY` (= `APP_SECRET` par défaut) — at-rest secrets chiffrés `enc:v2:`.
4. Le tag d'image est en dur dans le compose Coolify (×2 : server + worker). Le changer via l'API Coolify (`PATCH /services/{uuid}` avec `docker_compose_raw` **base64**) puis `POST /deploy?uuid=...`.
5. Vérifier `docker exec <server> yarn command:prod upgrade:status` → viser « Instance: Up to date · Workspaces: N up to date, 0 failed ».

## Gotcha v1→v2 rencontré le 2026-06-22 (deadlock d'ordonnancement)

Après le saut v1.22 → v2.14.4, `upgrade:status` montrait 1 workspace **failed** sur `BackfillRecordPageLayouts (1.23.0)` :
`column ViewSortEntity.subFieldName does not exist`.

Deadlock : les **commandes instance** (qui ajoutent le schéma core, dont `viewSort.subFieldName`) refusent de tourner tant que les workspaces n'ont pas fini leurs commandes 2.14.0 ; or le workspace est bloqué faute de ce schéma.

**Résolution** :
```bash
# 1) forcer les commandes instance (ajoute le schéma core manquant)
docker exec <server> yarn database:migrate:prod --force
# 2) rejouer les commandes workspace (maintenant que le schéma est là)
docker exec <server> yarn command:prod upgrade
# 3) confirmer
docker exec <server> yarn command:prod upgrade:status   # -> Up to date
# 4) restart propre (cache metadata frais)
docker restart <server> <worker>
```
`--force` contourne le garde-fou « workspaces must be up to date » — acceptable ici car c'est précisément ce garde-fou qui créait le deadlock, et un backup frais existait.
