## Decision: l'UI de Twenty possède l'existence d'une catégorie, le code possède son comportement — la dérive est conservée et signalée, jamais écrasée

Le SELECT `Company.categorie` est déclaré dans `scripts/configure_company_categorie.py`,
mais les utilisateurs peuvent créer des valeurs depuis Twenty. On ne ferme pas cette
porte. La synchronisation ne supprime jamais une option non déclarée ; à la place,
trois mécanismes rendent l'écart audible : conservation + signalement au run
(`merge_select_options`), `--check` sortant en 1 pour une tâche planifiée, et
`--adopt` qui imprime le bloc Python à coller pour déclarer une catégorie née de
l'usage, libellés d'origine compris.

## Context

Le run du 2026-07-23 a révélé **4 catégories présentes dans Twenty et absentes du
dépôt**, créées à la main : `CABINET_DESSINATEUR_PROJETEUR` (105 fiches),
`CABINET_ARCHITECTURE` (8), `BUREAU_ETUDES_TECHNIQUES` (2), `MARCHAND_DE_BIENS` (0).
Le `CABINET` versionné, lui, n'en portait qu'**une**. Conséquence invisible : les
contacts de ces organisations n'entraient dans aucun segment de newsletter, sans
qu'aucune alerte ne le dise — 10 contacts effectivement privés de lettre.

## Alternatives considered

1. **Le code est autoritaire** : la synchro aligne Twenty sur la liste déclarée et
   supprime le reste.
2. **Fermer la porte côté rôles** : retirer aux utilisateurs le droit d'éditer les
   métadonnées, pour que seul le script crée des valeurs.
3. **L'UI est libre, le code déclare ce qui porte un comportement** (retenue).
4. **Statu quo** : conserver sans rien dire (le comportement d'avant).

## Reasoning

- **L'usage avait raison contre le dépôt.** 105 fiches contre 1 : le découpage fin des
  cabinets, né du terrain, décrit mieux le métier que la catégorie générique écrite au
  bureau. L'option 1 aurait supprimé les quatre valeurs et vidé la catégorie de 115
  fiches — détruire de la donnée pour faire respecter une liste qui avait tort.
- **Le vocabulaire métier ne se décrète pas depuis un dépôt git.** Interdire la création
  (option 2) déplace le problème : la catégorie manquante ne serait pas créée, elle
  serait *contournée* (fourre-tout `AUTRE`, ou nom d'organisation bricolé), et on
  perdrait le signal en plus de la souplesse.
- **Ce qui doit rester au code, c'est le comportement.** Routage newsletter,
  qualification, scoring : ces règles vivent dans le dépôt, se testent et se relisent.
  Une catégorie inconnue n'a donc pas de comportement — c'est correct. Le défaut
  n'était pas là, il était dans le **silence** de ce vide.
- **Un test ne peut pas voir l'UI.** Le test de couverture compare la liste déclarée au
  mapping newsletter : par construction, il ignore ce qui n'est que dans Twenty. La
  détection doit donc se faire **au run**, seul moment où le CRM réel est visible. D'où
  le signalement nommé (et non un total agrégé) dans `crm_brevo plan`/`sync`, et
  `--check` pour ne pas dépendre de quelqu'un qui pense à regarder.
- **`--adopt` fait tenir la règle dans le temps.** Une discipline qui coûte cher n'est
  pas suivie : rendre l'adoption d'une catégorie possible en dix secondes (copier-coller
  d'un bloc généré) est ce qui distingue une règle appliquée d'une règle affichée.

## Trade-offs accepted

- **La dérive est signalée, pas empêchée.** Entre le moment où une catégorie est créée
  dans l'UI et celui où quelqu'un la déclare, ses contacts ne reçoivent aucune lettre.
  On raccourcit ce délai, on ne le supprime pas. L'accepter, c'est accepter que le CRM
  puisse être en avance sur le dépôt.
- **`--check` doit être branché quelque part pour servir.** Tant qu'il n'est pas dans la
  chaîne planifiée (Prefect, kutsh-data), le garde-fou repose sur la même bonne volonté
  qu'avant. C'est la moitié du dispositif qui reste à câbler, hors de ce dépôt.
- **Les options orphelines s'accumulent.** Rien ne supprime jamais : une catégorie créée
  par erreur reste dans le SELECT jusqu'à ce qu'on la retire à la main, après avoir
  requalifié les fiches. Assumé — l'inverse fait perdre de la donnée.
- **Deux sources à lire pour connaître la liste réelle** : le dépôt et le CRM. `--check`
  rend l'écart visible, mais la liste vraie reste celle de Twenty.

## Suite

- `MARCHAND_DE_BIENS` (0 fiche) a été **conservée et déclarée** sur décision explicite,
  plutôt que retirée : la catégorie a un sens métier même sans fiche aujourd'hui.
- Les quatre valeurs adoptées sont mappées vers le segment newsletter `PROS`.
- `CABINET` garde le libellé « Cabinet (autre / géomètre) » : ce qui n'entre dans aucun
  des trois découpages fins.
