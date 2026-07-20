#!/bin/sh
cd /home/joel/kutsh-crm || exit 1
set -a; . ./.env; set +a
python3 scripts/export_snapshot.py --out /home/joel/twenty-backups/snapshots --keep 12
