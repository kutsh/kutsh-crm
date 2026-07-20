## Decision: `kutsh-crm/crm_client.py` est le seul client Twenty ; la copie `kutsh-data/scripts/crm_client.py` est supprimée

Corollaires actés en même temps :

- `kutsh-crm` devient une **dépendance directe déclarée** de kutsh-data (extra
  `orchestration`), au lieu d'être tirée en transitif par `kutsh-veille-marches`.
- Le sync Brevo est **packagé** en module racine `crm_brevo` (comme `crm_export`),
  et son deployment Prefect est créé **sans cron**.

## Context

Kata `jnnf`, découvert en implémentant `f154` (migration de la chaîne CRM du cron
kutsh-prod vers Prefect).

kutsh-data embarquait `scripts/crm_client.py`, présenté comme un « miroir réduit »
de `kutsh-crm/crm_client.py`. Ce n'était plus un miroir : 172 insertions / 126
suppressions d'écart, et deux conceptions différentes.

- **throttle** : fenêtre glissante par *instance* (`self._req_times`) côté
  kutsh-data, au *niveau module* (`_calls`) côté paquet. Le quota Twenty est de
  100 req/60 s **par workspace** : une fenêtre par instance ne protège pas de
  deux clients dans le même process.
- **`list_all`** : sans `depth` côté kutsh-data, `depth=0` côté paquet.
- Le correctif de retry réseau (`c07e6fd`) n'avait atterri que sur la copie.

Le tout ne cassait pas *encore* : les 9 appelants de kutsh-data importent
`scripts.crm_client` (chemin qualifié, non ambigu), et `flows/crm_snapshot.py`
importe `crm_export` du paquet. Mais la marge tenait à un `sys.path` : `crm_export`
fait un `import crm_client` **nu**, et deux fichiers de tests
(`test_extract_cross_references.py`, `test_ingest_sitadel_national.py`) insèrent
`scripts/` en tête de `sys.path` pour toute la session pytest. Dans ce contexte,
le `crm_export` installé s'exécute contre le client local — celui sans `depth` —
et part en `TypeError`. Un test de `f154` est effectivement tombé comme ça.

La justification d'origine de la copie (« pour que le worker n'ait pas à dépendre
du repo CRM ») était par ailleurs devenue caduque : le worker dépend déjà de
`kutsh-crm`, et `weekly-crm-snapshot` en importe `crm_export`.

## Alternatives considered

1. **Garder les deux et resynchroniser** — c'est le statu quo qui a produit la
   divergence. Rien ne rend la copie détectablement périmée.
2. **Garder la copie et neutraliser seulement la pollution `sys.path`** — désarme
   le piège du jour sans traiter la cause. Le prochain correctif de contrat REST
   continue d'atterrir sur une seule des deux copies.
3. **Faire de la copie kutsh-data la référence** — elle est plus étroite
   (pas de `delete`, pas de `get`, pas de `find_person`/`upsert_contact`, pas de
   `depth`), et elle vit dans le dépôt data, pas dans le dépôt CRM. À rebours du
   cadrage (« changer de CRM = repointer `crm_client.py` »).
4. **Supprimer la copie, le paquet devient la référence** — retenu.

## Reasoning

Le cadrage CRM pose `crm_client.py` comme **le** point d'isolation anti-lock-in :
il ne peut pas y en avoir deux. Le paquet est déjà le sur-ensemble fonctionnel
(`delete`, `get`, `find_person`, `upsert_contact`, `depth`, throttle correct au
niveau module), il est déjà installé dans le worker, et il est déjà consommé par
kutsh-veille-marches. La copie n'apportait que deux choses, reportées ici avant
suppression : `TYPE_SIGNAL_VALUES` (avec la validation de `create_signal`, qui
transforme un HTTP 400 tronqué en message listant les valeurs admises) et la
valeur `RENOUVELLEMENT_ADS`.

Déclarer `kutsh-crm` en dépendance **directe** est la contrepartie : compter sur
un transitif via `kutsh-veille-marches` pour fournir le client de 9 scripts et
d'un flow, c'est une dépendance réelle que rien ne documente — et qui disparaît
le jour où veille-marches change de client HTTP.

Le sync Brevo est packagé par le même raisonnement que `crm_export` avant lui
(`f154`) : un job orchestré ne doit pas dépendre d'un fichier copié à la main sur
une machine. Son deployment est en revanche créé **sans cron**. Automatiser une
poussée de contacts vers un service externe est une décision produit (RGPD,
cadence d'envoi, volume), pas un effet de bord d'un chantier d'orchestration :
le run devient observable et rejouable, mais il reste déclenché à la main tant
que personne n'a tranché la cadence.

## Trade-offs accepted

- **kutsh-data ne tourne plus sans l'extra `orchestration`.** `uv sync` nu ne
  fournit plus `crm_client` : les 9 scripts CRM et leurs tests exigent
  `uv sync --all-extras`. La CI le fait déjà (`--frozen --all-extras`), le worker
  aussi ; c'est l'environnement de dev local nu qui perd quelque chose. Accepté
  parce que le paquet est stdlib pur — il ne coûte rien à installer.
- **Un changement de contrat REST devient un aller-retour à deux dépôts** :
  modifier kutsh-crm, merger, `uv lock --upgrade-package kutsh-crm`, reconstruire
  l'image. C'est plus lent qu'éditer un fichier local. C'est aussi exactement ce
  qui rend le changement visible partout au lieu d'une seule copie.
- **`ensure` diverge entre le module et la façade CLI** : la façade crée d'abord
  les champs newsletter dans Twenty, le module non. Assumé — c'est une migration
  de schéma, elle n'a rien à faire dans un job récurrent.
- **`drafts` n'est pas exécutable depuis le wheel** : le corps HTML des campagnes
  vit dans `newsletters/`, qui n'est pas packagé. Le module lève un message
  explicite et `NEWSLETTERS_DIR` permet de le pointer. Packager des gabarits
  d'e-mail dans un client d'API n'aurait pas de sens.
