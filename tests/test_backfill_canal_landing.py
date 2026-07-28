#!/usr/bin/env python3
"""Tests de la décision de backfill `canalAcquisition` (stdlib : `python -m unittest`).

On ne teste pas les appels réseau : seulement `plan_update`, le cœur qui décide
d'écrire ou non. Ce qui compte pour ne pas abîmer le CRM, c'est l'idempotence
(ne pas réécrire) et la prudence (ne pas écraser un canal déjà posé).
"""
from __future__ import annotations
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from backfill_canal_landing import plan_update  # noqa: E402


class TestPlanUpdate(unittest.TestCase):
    def test_email_absent_du_crm(self):
        self.assertEqual(plan_update(None), "not_found")

    def test_canal_vide_a_renseigner(self):
        self.assertEqual(plan_update({"id": "1", "canalAcquisition": None}), "set")
        self.assertEqual(plan_update({"id": "1"}), "set")  # clé absente = vide

    def test_deja_landing_page_est_idempotent(self):
        self.assertEqual(plan_update({"id": "1", "canalAcquisition": "LANDING_PAGE"}), "already")

    def test_autre_canal_non_ecrase(self):
        self.assertEqual(plan_update({"id": "1", "canalAcquisition": "LINKEDIN"}), "conflict")

    def test_force_ecrase_un_autre_canal(self):
        self.assertEqual(plan_update({"id": "1", "canalAcquisition": "LINKEDIN"}, force=True), "set")

    def test_force_reste_idempotent_si_deja_landing(self):
        self.assertEqual(
            plan_update({"id": "1", "canalAcquisition": "LANDING_PAGE"}, force=True), "already"
        )


if __name__ == "__main__":
    unittest.main()
