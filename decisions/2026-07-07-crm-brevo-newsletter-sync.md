## Decision: synchroniser Twenty → Brevo par un script batch idempotent (`kutsh-crm/scripts/sync_twenty_brevo.py`), segmenté sur la `categorie` de la Company, avec soft opt-in et rapatriement des désinscriptions dans Twenty

Trois listes Brevo (Collectivités & ADS / Pros de l'urbanisme / Écosystème &
institutionnels) alimentées depuis Twenty. Le segment d'un contact est **déduit de
la `categorie` de son organisation** (mapping `CATEGORIE_TO_SEGMENT` dans le script,
seul point à maintenir). Envoi en **soft opt-in** (première lettre + désinscription
en un clic, cadrage explicite dans chaque newsletter). Brevo gère la désinscription ;
un sous-commande `reconcile` **rapatrie** les `emailBlacklisted` dans Twenty
(`newsletterOptOut` + `newsletterOptOutAt` sur Person) — le CRM reste la source de
vérité, on ne re-sollicite jamais un désinscrit. Les 3 brouillons de campagne sont
créés/mis à jour dans Brevo depuis `kutsh-crm/newsletters/*.html` (non planifiés).

## Context: 3 newsletters à diffuser sur la base Twenty via Brevo (outil d'emailing déjà en place)

Demande produit (2026-07-07) : diffuser 3 lettres segmentées (avancées LaZone/Kutsh)
et charger les contacts concernés depuis Twenty dans Brevo comme listes, avec
automatisation de la synchro. Contraintes : aucun champ de consentement marketing
n'existait dans Twenty ; le CRM contient des prospects qualifiés par bot ; Brevo et
Twenty sont déjà branchés côté landing (`brevo.ts`/`twenty.ts`, mêmes noms d'env).

## Alternatives considered

1. **Import manuel (CSV export Twenty → upload Brevo)** : rapide une fois, mais pas
   reproductible, pas de dédup, pas de rapatriement des opt-out, dérive garantie.
2. **Champ SELECT `brevoList` posé à la main sur chaque Person** : contrôle fin mais
   travail manuel non tenable à l'échelle, et redondant avec `categorie` déjà saisie.
3. **Segmentation directement dans Brevo (attributs + segments dynamiques)** :
   déporte la logique métier hors du CRM (source de vérité), duplique la donnée de
   catégorie. Rejeté : la catégorie vit dans Twenty, le mapping doit y rester adossé.
4. **Script batch idempotent segmenté sur `categorie` (retenu)** : une seule règle
   (`CATEGORIE_TO_SEGMENT`), rejouable, dry-run, réconciliation opt-out bidirectionnelle.

## Reasoning

- **Réutilise `categorie`** (ADR 2026-06-24) : pas de nouvelle saisie, le ciblage
  suit la typologie déjà maintenue par la qualif et le bot.
- **Idempotent + dry-run** (`plan`) : on voit les volumes par liste avant tout écrit,
  cohérent avec les autres scripts `kutsh-crm` (upserts idempotents, stdlib pur).
- **Souveraineté du consentement** : Brevo est le canal, mais l'état d'abonnement
  redescend dans Twenty (source de vérité anti-lock-in). `reconcile` avant `sync`
  dans la commande `all` garantit qu'un désinscrit n'est jamais réinjecté.
- **Soft opt-in** : base légale défendable en B2B (intérêt légitime + information
  claire + retrait immédiat), à condition que la désinscription soit triviale et
  tracée — d'où le cadrage en tête de chaque lettre et le champ `newsletterOptOut`.
- **Aligné sur l'architecture** (ADR 2026-06-23) : le batch écrit dans Twenty via
  `crm_client`, comme les pipelines kutsh-data ; la récurrence se pose en cron
  serveur (comme `export_snapshot.py`) ou en déploiement Prefect kutsh-data.

## Trade-offs accepted

- **Soft opt-in ≠ opt-in explicite** : risque résiduel (un contact non intéressé
  reçoit un mail). Mitigé par le cadrage transparent, la désinscription 1-clic et le
  fait de ne cibler que des organisations typées (pas de fourre-tout `AUTRE`/null).
- **Mapping catégorie→segment à maintenir** : une nouvelle valeur `categorie` non
  mappée retombe silencieusement hors newsletter (comptée dans le dry-run, pas
  d'envoi accidentel — c'est le comportement voulu).
- **`reconcile` lit les `emailBlacklisted` des listes** : ne capte pas un opt-out
  d'un contact jamais ajouté à nos listes ; acceptable (on ne sollicite que nos
  listes). Un webhook Brevo temps réel serait plus fin — reporté (cron suffit).
- **Secrets non tirables de Coolify** : l'API Coolify masque les valeurs, donc
  exécution locale via `kutsh-crm/.env` (gitignoré) ; en prod, env du runner
  (cron serveur / Prefect) porte `TWENTY_API_KEY` + `BREVO_API_KEY`.
- **HTML e-mail** : gabarit table inline volontairement sobre (éditable dans Brevo) ;
  pas de dark-mode e-mail géré, pas d'images (poids/délivrabilité).

## Suite

- Cadence cron à trancher : cron serveur (comme `export_snapshot`) vs déploiement
  Prefect kutsh-data. `all` = `reconcile` puis `sync` (pas `drafts`).
- `drafts` reste manuel/à la demande (on ne recrée pas un brouillon à chaque tick).
