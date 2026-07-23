#!/usr/bin/env python3
"""Tests des listes d'options du pipeline Opportunity (stdlib pur, sans réseau).

Ce qui est testé ici n'est pas du code mais une **déclaration** : les valeurs de
`segment`, `stage` et `tourFinancement`. C'est justement ce qui la rend fragile —
renommer une valeur ne casse aucun appel, ne lève aucune erreur, et se contente
de rendre orphelines les fiches qui la portaient. Le script conserve désormais
ces orphelines (`merge_select_options`), mais mieux vaut ne pas en créer.
"""

from __future__ import annotations

import os
import sys
import unittest

_RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RACINE)
sys.path.insert(0, os.path.join(_RACINE, "scripts"))
from crm_client import merge_select_options  # noqa: E402
from configure_pipeline import (  # noqa: E402
    SEGMENT_OPTIONS, STAGE_OPTIONS, TOUR_OPTIONS,
)

# Valeurs déclarées AVANT le suivi de levée (issue mfmp). Aucune ne doit
# disparaître : des opportunités les portent en base.
SEGMENTS_HISTORIQUES = {"B2G", "B2B", "B2B2B", "RELAIS"}
STAGES_HISTORIQUES = {
    "PROSPECTION", "QUALIFICATION", "ECHANGE", "OFFRE",
    "EVALUATION", "GAGNE", "EXECUTION", "PERDU",
}


class TestOptionsDeclarees(unittest.TestCase):
    def test_pas_de_valeur_en_double(self):
        for nom, opts in (("segment", SEGMENT_OPTIONS), ("stage", STAGE_OPTIONS),
                          ("tourFinancement", TOUR_OPTIONS)):
            valeurs = [o["value"] for o in opts]
            self.assertEqual(len(valeurs), len(set(valeurs)), nom)

    def test_chaque_option_a_un_libelle_et_une_couleur(self):
        for nom, opts in (("segment", SEGMENT_OPTIONS), ("stage", STAGE_OPTIONS),
                          ("tourFinancement", TOUR_OPTIONS)):
            for o in opts:
                self.assertTrue(o.get("label"), f"{nom}/{o['value']}")
                self.assertTrue(o.get("color"), f"{nom}/{o['value']}")

    def test_aucune_valeur_historique_n_a_disparu(self):
        """Renommer une valeur ne casse rien à l'exécution — ça strande des fiches.

        Une opportunité en base porte la chaîne `B2G`, pas un identifiant : si la
        liste déclarée cesse de la mentionner, l'option devient orpheline et sort
        de tout filtre. Ce test fige les valeurs de l'issue mfmp.
        """
        self.assertLessEqual(SEGMENTS_HISTORIQUES, {o["value"] for o in SEGMENT_OPTIONS})
        self.assertLessEqual(STAGES_HISTORIQUES, {o["value"] for o in STAGE_OPTIONS})

    def test_le_segment_levee_existe(self):
        self.assertIn("LEVEE", {o["value"] for o in SEGMENT_OPTIONS})


class TestSynchronisationNonDestructive(unittest.TestCase):
    def test_un_run_sur_la_config_precedente_ne_cree_aucune_orpheline(self):
        """Le run réel : Twenty porte la config mfmp, on y applique la nouvelle.

        Simule l'état d'avant (options avec leurs `id`) et vérifie que la fusion
        n'orpheline rien et réutilise tous les `id` — c'est-à-dire qu'aucune
        opportunité ne perd son segment ni son étape en jouant le script.
        """
        avant = [{"id": f"id-{v}", "value": v, "label": v, "color": "blue", "position": i}
                 for i, v in enumerate(sorted(SEGMENTS_HISTORIQUES))]
        fusion, orphelines = merge_select_options(avant, SEGMENT_OPTIONS)
        self.assertEqual(orphelines, [])
        ids = {o["value"]: o.get("id") for o in fusion}
        for v in SEGMENTS_HISTORIQUES:
            self.assertEqual(ids[v], f"id-{v}", f"{v} a perdu son id")
        self.assertIsNone(ids["LEVEE"])  # nouvelle option : id attribué par Twenty

        avant_stages = [{"id": f"id-{v}", "value": v, "label": v, "color": "gray", "position": i}
                        for i, v in enumerate(sorted(STAGES_HISTORIQUES))]
        fusion, orphelines = merge_select_options(avant_stages, STAGE_OPTIONS)
        self.assertEqual(orphelines, [])
        self.assertTrue(all(o.get("id") for o in fusion))


if __name__ == "__main__":
    unittest.main()
