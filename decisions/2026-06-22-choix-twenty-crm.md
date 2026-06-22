## Decision: Twenty (open source, self-hosted) comme CRM de Kutsh

On adopte **Twenty** comme CRM, déployé en self-hosted sur notre infra Hetzner via Coolify (`twenty.kutsh.fr`). Twenty est l'**interface de consultation** ; la **source de vérité** reste une couche Python (`crm_client.py` + PostgreSQL enrichi) qui pousse les données vers Twenty via API. Cf. cadrage complet : message Basecamp du 2026-05-06 « Notre CRM : pourquoi Twenty, et comment on le pense » + doc Outline « Cadrage CRM Kutsh ».

## Context: pourquoi cette décision

Kutsh ne veut pas un CRM d'enregistrement du passé, mais un moteur d'intelligence commerciale capable de modéliser son marché (collectivités, PLUi, cabinets dessinateurs-projeteurs, éditeurs ADS) et de déclencher des actions. Deux exigences en découlent : (1) un modèle de données entièrement personnalisable (objets métier non standard) ; (2) une API ouverte pour brancher notre enrichissement Python. S'ajoutent nos contraintes : souveraineté des données / posture ISO 27001-ready, et messagerie Infomaniak (IMAP, pas Gmail/M365).

## Alternatives considered

- **Attio** — modèle flexible, API solide, plan gratuit 3 sièges. Rédhibitoire : sync email limitée à Gmail / Microsoft 365, pas d'IMAP générique → pas de connecteur natif Infomaniak (contournable seulement par bricolage autour d'une limite d'un outil propriétaire).
- **Folk** — API derrière le plan Premium (48 €/mois/utilisateur). Sans API, pas d'enrichissement métier. Écarté.
- **Breakcold** — excellent social selling LinkedIn mais modèle de données figé (Contacts/Entreprises/Deals), impossible de créer « Collectivité » ou « PLUi ». Écarté comme CRM principal (complément outbound éventuel).
- **CRM maison (FastAPI + React)** — possible mais coût de construction/maintenance disproportionné au stade actuel ; gardé comme repli.

## Reasoning: pourquoi Twenty l'emporte

- Open source (GPL), self-hostable → contrôle total des données, cohérent avec « self-hosted par défaut » et la souveraineté.
- Modèle de données 100 % custom → nos 5 objets métier (Collectivité, PLUi, Cabinet, Éditeur ADS, Signal).
- API REST + GraphQL → la couche Python écrit directement, sans intermédiaire.
- PostgreSQL accessible en dessous → accès direct en dernier recours.
- IMAP développable en self-hosted → compatible Infomaniak.
- Coût zéro hors infra Hetzner déjà budgétée.
- Lock-in quasi nul : données dans notre PostgreSQL + abstraction `crm_client.py` → migration en un week-end.

## Trade-offs accepted

- Twenty est jeune : pas d'app mobile, pas de marketplace d'intégrations, reporting basique.
- Ops à notre charge : déploiement, mises à jour (suivi des releases d'un produit en évolution rapide), sauvegardes/restore.
- Connecteur email Infomaniak à développer nous-mêmes (pas natif).
- Mitigations : export JSON hebdomadaire versionné (DVC) pour garantir un snapshot frais et la portabilité ; schéma de données versionné dans ce repo.
