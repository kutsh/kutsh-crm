#!/usr/bin/env python3
"""Tests du contrôle de santé des snapshots CRM (stdlib pur : `python -m unittest`).

Les deux fixtures sont les manifestes RÉELS de l'incident 2026-07-20 :
- `manifest-degrade-2026-07-12.json` : 12 objets sur 13 en HTTP 429, 5
  enregistrements au total. Le script d'alors imprimait « OK snapshot » et
  sortait en 0 — trois semaines de backups vides sans alerte.
- `manifest-sain-2026-07-20.json` : le run d'après correction, 48 584
  enregistrements, dont deux objets légitimement à 0 (editeursAds,
  interventions) qui ne doivent PAS déclencher de faux positif.
"""
from __future__ import annotations
import json
import os
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from export_snapshot import check_health, previous_manifest  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name: str) -> dict:
    with open(os.path.join(FIXTURES, name)) as fh:
        return json.load(fh)


def manifest(objects: dict, stamp: str = "2026-01-01") -> dict:
    return {"snapshot": stamp, "base_url": "https://example.invalid", "objects": objects}


class TestIncidentReel(unittest.TestCase):
    """Régression : le snapshot du 12/07 doit être refusé, celui du 20/07 accepté."""

    def test_le_snapshot_degrade_du_12_07_est_detecte(self):
        errors, _ = check_health(fixture("manifest-degrade-2026-07-12.json"), None)
        self.assertTrue(errors, "le snapshot à 5 enregistrements doit lever des erreurs")
        # Une erreur par objet en échec (12), sans référence antérieure.
        self.assertEqual(len(errors), 12)
        self.assertTrue(any("people" in e and "429" in e for e in errors))

    def test_le_snapshot_sain_du_20_07_passe(self):
        errors, warnings = check_health(fixture("manifest-sain-2026-07-20.json"), None)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_zeros_legitimes_ne_sont_pas_des_faux_positifs(self):
        """editeursAds et interventions valent 0 dans les deux snapshots réels."""
        sain = fixture("manifest-sain-2026-07-20.json")
        self.assertEqual(sain["objects"]["editeursAds"]["count"], 0)
        errors, _ = check_health(sain, sain)
        self.assertEqual(errors, [])

    def test_la_chute_du_20_07_vers_le_12_07_serait_detectee(self):
        """Le scénario réel : un bon snapshot, puis l'effondrement."""
        errors, _ = check_health(
            fixture("manifest-degrade-2026-07-12.json"),
            fixture("manifest-sain-2026-07-20.json"),
        )
        # 12 échecs de lecture + les objets peuplés retombés à 0.
        self.assertTrue(any("43187" in e and "cabinets" in e for e in errors))
        self.assertTrue(any("452" in e and "people" in e for e in errors))


class TestReglesDeSante(unittest.TestCase):
    def test_erreur_de_lecture_est_fatale(self):
        errors, _ = check_health(
            manifest({"people": {"count": 0, "error": "HTTP 429"}, "notes": {"count": 3}}), None
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("people", errors[0])

    def test_snapshot_totalement_vide_est_fatal(self):
        errors, _ = check_health(manifest({"people": {"count": 0}, "notes": {"count": 0}}), None)
        self.assertEqual(errors, ["snapshot totalement vide (0 enregistrement, tous objets confondus)"])

    def test_objet_qui_se_vide_est_fatal(self):
        errors, _ = check_health(
            manifest({"people": {"count": 0}, "notes": {"count": 3}}),
            manifest({"people": {"count": 452}, "notes": {"count": 3}}, "2026-07-20"),
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("452", errors[0])
        self.assertIn("2026-07-20", errors[0])

    def test_zero_reste_zero_sans_erreur(self):
        errors, warnings = check_health(
            manifest({"people": {"count": 0}, "notes": {"count": 3}}),
            manifest({"people": {"count": 0}, "notes": {"count": 3}}),
        )
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_grosse_baisse_avertit_sans_bloquer(self):
        """Une purge légitime (purge_auto_leads) ne doit pas faire échouer le backup."""
        errors, warnings = check_health(
            manifest({"cabinets": {"count": 4000}}),
            manifest({"cabinets": {"count": 43187}}, "2026-07-20"),
        )
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("-91 %", warnings[0])

    def test_petit_objet_en_baisse_reste_silencieux(self):
        """Sous 100 enregistrements, les variations sont trop bruitées pour alerter."""
        _, warnings = check_health(
            manifest({"notes": {"count": 3}}), manifest({"notes": {"count": 26}})
        )
        self.assertEqual(warnings, [])

    def test_nouvel_objet_absent_du_precedent(self):
        """Un objet créé depuis le dernier snapshot ne doit pas alerter."""
        errors, warnings = check_health(
            manifest({"nouveaute": {"count": 0}, "notes": {"count": 3}}),
            manifest({"notes": {"count": 3}}),
        )
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])


class TestPreviousManifest(unittest.TestCase):
    def test_lit_le_manifeste_de_l_archive_la_plus_recente(self):
        with tempfile.TemporaryDirectory() as base:
            for stamp, count in (("2026-07-05", 1), ("2026-07-20", 452)):
                work = os.path.join(base, stamp)
                os.makedirs(work)
                with open(os.path.join(work, "manifest.json"), "w") as fh:
                    json.dump(manifest({"people": {"count": count}}, stamp), fh)
                with tarfile.open(os.path.join(base, f"twenty-snapshot-{stamp}.tar.gz"), "w:gz") as tar:
                    tar.add(work, arcname=stamp)
            found = previous_manifest(base)
            self.assertIsNotNone(found)
            self.assertEqual(found["snapshot"], "2026-07-20")
            self.assertEqual(found["objects"]["people"]["count"], 452)

    def test_repertoire_sans_archive(self):
        with tempfile.TemporaryDirectory() as base:
            self.assertIsNone(previous_manifest(base))

    def test_archive_corrompue_ne_fait_pas_planter(self):
        """Une archive illisible doit être ignorée au profit de la précédente."""
        with tempfile.TemporaryDirectory() as base:
            work = os.path.join(base, "2026-07-05")
            os.makedirs(work)
            with open(os.path.join(work, "manifest.json"), "w") as fh:
                json.dump(manifest({"people": {"count": 1}}, "2026-07-05"), fh)
            with tarfile.open(os.path.join(base, "twenty-snapshot-2026-07-05.tar.gz"), "w:gz") as tar:
                tar.add(work, arcname="2026-07-05")
            with open(os.path.join(base, "twenty-snapshot-2026-07-20.tar.gz"), "wb") as fh:
                fh.write(b"ceci n'est pas une archive")
            found = previous_manifest(base)
            self.assertIsNotNone(found)
            self.assertEqual(found["snapshot"], "2026-07-05")


class FakeClient:
    """Client Twenty minimal : `plans` décrit ce que renvoie chaque objet."""

    base = "https://example.invalid"

    def __init__(self, plans: dict):
        self.plans = plans

    def _req(self, method, path, params=None):
        objects = [
            {"nameSingular": p[:-1], "namePlural": p, "isCustom": False}
            for p in sorted(self.plans)
        ]
        return {"data": {"objects": objects}}

    def list_all(self, plural, page_size=60, depth=0):
        for i, rec in enumerate(self.plans[plural]):
            if rec is RuntimeError:  # échec APRÈS quelques lignes déjà écrites
                raise RuntimeError("HTTP 429: Limit reached")
            yield {"id": f"{plural}-{i}"}


class TestRunBoutEnBout(unittest.TestCase):
    def setUp(self):
        import export_snapshot

        self.mod = export_snapshot
        self.vrai_client = export_snapshot.TwentyClient
        self.addCleanup(setattr, export_snapshot, "TwentyClient", self.vrai_client)

    def _run(self, plans, base, stamp, keep=2):
        self.mod.TwentyClient = lambda: FakeClient(plans)
        return self.mod.run(base, keep, stamp)

    def test_run_sain_retourne_vrai_et_applique_la_retention(self):
        with tempfile.TemporaryDirectory() as base:
            for stamp in ("2026-01-01", "2026-01-02", "2026-01-03"):
                _, healthy = self._run({"people": [{}] * 5}, base, stamp)
                self.assertTrue(healthy)
            restants = sorted(f for f in os.listdir(base) if f.endswith(".tar.gz"))
            self.assertEqual(len(restants), 2, "keep=2 doit purger la plus ancienne")
            self.assertNotIn("twenty-snapshot-2026-01-01.tar.gz", restants)

    def test_run_degrade_retourne_faux_et_suspend_la_retention(self):
        with tempfile.TemporaryDirectory() as base:
            for stamp in ("2026-01-01", "2026-01-02"):
                self._run({"people": [{}] * 5}, base, stamp)
            # 3e run : lecture qui casse après 2 lignes -> dégradé
            archive, healthy = self._run(
                {"people": [{}, {}, RuntimeError]}, base, "2026-01-03"
            )
            self.assertFalse(healthy, "un objet en échec doit rendre le run non sain")
            self.assertTrue(os.path.exists(archive), "l'archive est conservée malgré tout")
            restants = sorted(f for f in os.listdir(base) if f.endswith(".tar.gz"))
            self.assertEqual(len(restants), 3, "retention suspendue : rien n'est supprime")
            self.assertIn("twenty-snapshot-2026-01-01.tar.gz", restants)

    def test_le_manifeste_garde_le_compte_partiel_en_cas_d_echec(self):
        """Une pagination interrompue laisse un .jsonl tronqué : `count` le révèle."""
        with tempfile.TemporaryDirectory() as base:
            archive, healthy = self._run(
                {"people": [{}, {}, RuntimeError]}, base, "2026-01-01"
            )
            self.assertFalse(healthy)
            with tarfile.open(archive, "r:gz") as tar:
                fh = tar.extractfile("2026-01-01/manifest.json")
                man = json.load(fh)
            self.assertEqual(man["objects"]["people"]["count"], 2)
            self.assertIn("429", man["objects"]["people"]["error"])


if __name__ == "__main__":
    unittest.main()
