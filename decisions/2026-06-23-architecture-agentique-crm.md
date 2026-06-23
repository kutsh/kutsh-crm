## Decision: architecture du « moteur d'intelligence commerciale » en 3 rôles — Twenty (système de référence + MCP), kutshbot (orchestrateur agentique), kutsh-data/Prefect (pipelines de données)

On précise (et on amende partiellement) le cadrage initial. Trois couches aux rôles explicites :

1. **Twenty** = **système de référence du CRM** + **surface d'outils MCP**. Détient les objets (People, Companies, Deals, Collectivité, PLUi, Cabinet, Éditeur ADS, Signal), le pipeline, l'historique. Expose un **MCP natif** (`https://twenty.kutsh.fr/mcp`) pour lecture/écriture par les agents, et — une fois un LLM configuré — des **workflows + étapes IA** natives pour l'enrichissement *in‑CRM* (classification, summarization, custom prompts).
2. **kutshbot** = **orchestrateur agentique multi-canaux** (déjà en prod : Basecamp webhooks/Campfire, email IMAP/SMTP, Outline, GitHub, Cal.com, KDrive ; runtime Task/Run/Step/**Approval**/Artifact/Memory ; LLM via **OpenRouter** + tool-calling). C'est lui le « cerveau » conversationnel et proactif : il **qualifie les leads, pousse les signaux et rédige les briefs**, et **délivre** ces actions dans les canaux humains (Basecamp, email) **avec validation**. Il gagne un **connecteur Twenty** (via le MCP natif) pour lire/écrire le CRM.
3. **kutsh-data / Prefect** = **pipelines de données déterministes** (scraping/ingestion BOAMP, GPU, SITADEL, DGCL, LinkedIn). Calcule les enrichissements et les signaux bruts ; `kutsh-crm/crm_client.py` les **écrit dans Twenty** (batch idempotent).

## Context: pourquoi cette décision

Le cadrage initial (message Basecamp 2026-05-06) posait « Twenty = simple vue de consultation, une couche Python = le cerveau/source de vérité ». Deux faits le rendent partiellement obsolète :

- **Twenty est agent-native** (v2.14.4) : MCP natif riche (CRUD complet + `send_email`/`draft_email`/`navigate_app` + skills), agents/workflows IA, SDK TS (`defineSkill`/`defineAgent`/`runAgent`), respect du modèle de permissions. Construire un « cerveau » Python externe redondant n'a plus de sens (cf. retrait du serveur MCP custom, issue 7k36).
- **kutshbot existe déjà** et est un **runtime agentique mature en production** : multi-canaux, OpenRouter, tool-calling, et surtout un **modèle d'autonomie avec checkpoints d'approbation** (lire/résumer/brouillon = libre ; email tiers / Cal.com / PR / note Outline officielle = validation). Réécrire cette logique en agents Twenty natifs (encore **beta/alpha**, LLM non configuré sur notre instance) serait du gaspillage.

Par ailleurs, un **trou** est constaté : les leads de la landing (`landing.kutsh.fr` → `POST /api/subscribe`) partent vers **Brevo** + un message Basecamp « 📬 Nouveau contact landing page » (fire‑and‑forget), mais **jamais dans Twenty** — d'où l'import manuel des 24 contacts du Campfire (issue y89n).

## Alternatives considered

- **Tout en agents Twenty natifs** : élégant (un seul système) mais les features IA Twenty sont beta/alpha, sans LLM configuré, sans le modèle d'approbation ni les canaux (Basecamp/email) dont Kutsh a besoin ; jetterait l'investissement kutshbot.
- **Tout en couche Python externe (cadrage initial)** : réinvente la roue (agent runtime, tool-calling, MCP) que Twenty et kutshbot fournissent déjà ; plus de code à maintenir.
- **kutshbot écrit en base Postgres Twenty en direct** : couplage fort au schéma interne de Twenty, contourne permissions/validations/audit → rejeté au profit du **MCP natif** (ou `crm_client` REST) comme contrat stable.

## Reasoning: pourquoi ce découpage l'emporte

- **Zéro redondance, rôles nets** : Twenty = vérité + outils ; kutshbot = agent + canaux + approbation ; kutsh-data = données. Chacun fait ce qu'il fait déjà le mieux.
- **Réutilise l'existant** : kutshbot (prod, OpenRouter, approbation, mémoire) devient l'exécuteur des cas P3/P4 sans réécriture ; il lui suffit d'un connecteur Twenty (MCP).
- **Cohérence LLM** : Twenty *et* kutshbot peuvent partager **OpenRouter** (déjà dans la stack Kutsh).
- **Contrat stable anti-lock-in** : Twenty MCP (runtime/agents) + `crm_client.py` (batch déterministe) ; si on change de CRM, on repointe ces deux contrats.
- **Bouche le trou des leads** : la landing (et/ou kutshbot) écrit désormais les leads dans Twenty (upsert idempotent par email).

## Trade-offs accepted

- **Deux runtimes agentiques** coexistent (kutshbot + agents Twenty natifs). On assume : kutshbot porte le proactif multi-canaux ; Twenty natif sert l'enrichissement *in‑CRM* léger (quand LLM configuré). Frontière à tenir pour éviter le doublon.
- **Dépendance au MCP / à l'API Twenty** comme contrat d'intégration (mitigée par `crm_client.py`).
- **Confusion de nommage** non résolue : repo `kutshbot` / service Coolify `kutsh-agent` / blueprint `kutsh-agent-core`. À clarifier hors de cette décision.
- **Prérequis** : configurer un fournisseur LLM (OpenRouter) dans Twenty pour activer les workflows/agents IA natifs ; aujourd'hui aucun n'est configuré.
