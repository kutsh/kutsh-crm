#!/bin/sh
cd /home/joel/kutsh-crm || exit 1
set -a; . ./.env; set +a
python3 scripts/qualify_leads.py --apply --limit 50
