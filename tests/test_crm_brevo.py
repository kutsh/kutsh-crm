#!/usr/bin/env python3
"""Tests du routage de segmentation Brevo (stdlib pur, sans réseau).

Ce qui est testé ici, c'est `gather()` : la fonction qui décide dans QUELLE
liste Brevo part un contact. Une erreur de routage n'échoue pas — elle envoie
un mail au mauvais public, ce qu'aucun code retour ne rattrape ensuite. Le CRM
étant polymorphe (People n..1 {Collectivité, Cabinet, Éditeur ADS, Company}),
c'est aussi la partie la plus facile à casser en ajoutant une relation.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import crm_brevo  # noqa: E402
from crm_brevo import CONTACT_ATTRIBUTES, SEGMENTS, BrevoError, ensure_attributes, gather  # noqa: E402


class FakeClient:
    """Client Twenty en dur : `gather` ne consomme que `list_all`."""

    def __init__(self, people=(), companies=(), collectivites=(), cabinets=(), editeurs=()):
        self._rows = {
            "people": list(people),
            "companies": list(companies),
            "collectivites": list(collectivites),
            "cabinets": list(cabinets),
            "editeurAds": list(editeurs),
        }
        self.appels: list[str] = []

    def list_all(self, plural, page_size=60, depth=0):
        self.appels.append(plural)
        yield from self._rows.get(plural, [])


def person(pid="p1", email="a@exemple.fr", first="Ada", last="L", **fields):
    return {"id": pid, "emails": {"primaryEmail": email}, "name": {"firstName": first, "lastName": last}, **fields}


class TestRoutage(unittest.TestCase):
    def _segments(self, buckets):
        return {seg: [ct["email"] for ct in rows] for seg, rows in buckets.items() if rows}

    def test_relation_cabinet_route_vers_pros(self):
        c = FakeClient(people=[person(cabinetId="cab1")], cabinets=[{"id": "cab1", "name": "Atelier X"}])
        buckets, stats, by_source = gather(c)
        self.assertEqual(self._segments(buckets), {"PROS": ["a@exemple.fr"]})
        self.assertEqual(buckets["PROS"][0]["company"], "Atelier X")
        self.assertEqual(by_source["cabinets"], 1)

    def test_la_relation_collectivite_prime_sur_cabinet(self):
        """RELATION_ROUTING est ordonné : la 1re relation non nulle gagne.

        Un contact rattaché aux deux est un élu qui exerce aussi en cabinet — il
        doit recevoir la newsletter collectivités, pas celle des pros.
        """
        c = FakeClient(
            people=[person(collectiviteId="col1", cabinetId="cab1")],
            collectivites=[{"id": "col1", "name": "Trifouillis"}],
            cabinets=[{"id": "cab1", "name": "Atelier X"}],
        )
        buckets, _, _ = gather(c)
        self.assertEqual(self._segments(buckets), {"COLLECTIVITES": ["a@exemple.fr"]})

    def test_override_manuel_prime_sur_toute_deduction(self):
        c = FakeClient(
            people=[person(cabinetId="cab1", newsletterSegment="ECOSYSTEME")],
            cabinets=[{"id": "cab1", "name": "Atelier X"}],
        )
        buckets, _, by_source = gather(c)
        self.assertEqual(self._segments(buckets), {"ECOSYSTEME": ["a@exemple.fr"]})
        self.assertEqual(by_source["override"], 1)

    def test_override_inconnu_est_ignore_au_profit_de_la_deduction(self):
        c = FakeClient(
            people=[person(cabinetId="cab1", newsletterSegment="PAS_UN_SEGMENT")],
            cabinets=[{"id": "cab1", "name": "Atelier X"}],
        )
        buckets, _, _ = gather(c)
        self.assertEqual(self._segments(buckets), {"PROS": ["a@exemple.fr"]})

    def test_company_route_par_categorie(self):
        c = FakeClient(
            people=[person(companyId="co1")],
            companies=[{"id": "co1", "categorie": "MEDIA", "name": "La Gazette"}],
        )
        buckets, _, by_source = gather(c)
        self.assertEqual(self._segments(buckets), {"ECOSYSTEME": ["a@exemple.fr"]})
        self.assertEqual(by_source["companies"], 1)

    def test_categorie_hors_perimetre_n_est_pas_envoyee(self):
        """AUTRE et les catégories non mappées restent hors newsletter, par défaut.

        C'est le sens de la lecture : on n'envoie qu'à un public qualifié, on ne
        retombe pas sur un segment fourre-tout.
        """
        c = FakeClient(
            people=[person(companyId="co1")],
            companies=[{"id": "co1", "categorie": "AUTRE", "name": "Divers"}],
        )
        buckets, stats, _ = gather(c)
        self.assertEqual(self._segments(buckets), {})
        self.assertEqual(stats["unmapped_categorie"], 1)


class TestExclusions(unittest.TestCase):
    def test_sans_email_exclu(self):
        c = FakeClient(people=[{"id": "p1", "emails": {}, "cabinetId": "cab1"}])
        buckets, stats, _ = gather(c)
        self.assertEqual(stats["no_email"], 1)
        self.assertEqual(stats["kept"], 0)

    def test_desinscrit_exclu(self):
        c = FakeClient(
            people=[person(newsletterOptOut=True, cabinetId="cab1")],
            cabinets=[{"id": "cab1", "name": "Atelier X"}],
        )
        buckets, stats, _ = gather(c)
        self.assertEqual(stats["opted_out"], 1)
        self.assertEqual(stats["kept"], 0)

    def test_sans_organisation_exclu(self):
        c = FakeClient(people=[person()])
        buckets, stats, _ = gather(c)
        self.assertEqual(stats["no_org"], 1)

    def test_un_meme_email_ne_part_qu_une_fois(self):
        """Deux fiches Twenty pour la même personne = un seul envoi.

        Le CRM en contient (import LinkedIn + import Campfire), et Brevo compte
        les contacts, pas les fiches.
        """
        c = FakeClient(
            people=[person("p1", cabinetId="cab1"), person("p2", cabinetId="cab1")],
            cabinets=[{"id": "cab1", "name": "Atelier X"}],
        )
        buckets, stats, _ = gather(c)
        self.assertEqual(len(buckets["PROS"]), 1)
        self.assertEqual(stats["kept"], 1)

    def test_email_normalise_en_minuscules(self):
        c = FakeClient(
            people=[person(email="  Ada@Exemple.FR ", cabinetId="cab1")],
            cabinets=[{"id": "cab1", "name": "Atelier X"}],
        )
        buckets, _, _ = gather(c)
        self.assertEqual(buckets["PROS"][0]["email"], "ada@exemple.fr")

    def test_editeurs_ads_exclus_quand_la_relation_est_desactivee(self):
        """INCLUDE_EDITEURS_ADS=False → un éditeur ADS (concurrent) ne reçoit rien,
        et ne retombe pas sur un autre segment via sa Company."""
        routing = [
            (id_key, plural, None if plural == "editeurAds" else seg)
            for id_key, plural, seg in crm_brevo.RELATION_ROUTING
        ]
        c = FakeClient(
            people=[person(editeurAdsId="ed1", companyId="co1")],
            companies=[{"id": "co1", "categorie": "EDITEUR_ADS", "name": "Concurrent"}],
            editeurs=[{"id": "ed1", "name": "Concurrent"}],
        )
        original = crm_brevo.RELATION_ROUTING
        crm_brevo.RELATION_ROUTING = routing
        try:
            buckets, stats, _ = gather(c)
        finally:
            crm_brevo.RELATION_ROUTING = original
        self.assertEqual(stats["exclu"], 1)
        self.assertEqual(stats["kept"], 0)


class TestDryRun(unittest.TestCase):
    def test_with_names_false_saute_les_noms_d_organisations(self):
        """Le dry-run ne descend pas les noms : c'est ce qui le rend rapide.

        Un `plan` qui listerait cabinets + collectivites + editeurAds paierait
        plusieurs milliers d'appels pour un affichage qui n'en a pas besoin.
        """
        c = FakeClient(people=[person(cabinetId="cab1")], cabinets=[{"id": "cab1", "name": "Atelier X"}])
        buckets, _, _ = gather(c, with_names=False)
        self.assertEqual(buckets["PROS"][0]["company"], "")
        self.assertNotIn("cabinets", c.appels)


class FakeBrevo:
    """Brevo en dur pour `ensure_attributes` : schéma d'attributs + création.

    `refuse` reproduit le comportement qui a produit l'incident : l'API accepte
    le POST, renvoie 2xx, et ne stocke rien.
    """

    def __init__(self, existants=(), refuse=False):
        self._attrs = list(existants)
        self.refuse = refuse
        self.crees: list[str] = []

    def attributes(self):
        return [{"name": n} for n in self._attrs]

    def create_attribute(self, name, type_="text"):
        self.crees.append(name)
        if not self.refuse:
            self._attrs.append(name)


class TestEnsureAttributes(unittest.TestCase):
    """Le défaut du 2026-07-21 : `SOURCE` et `SEGMENT` étaient envoyés par le
    sync mais absents du schéma Brevo. L'import a rendu un `processId`, le
    processus est passé `completed`, et les 376 contacts ont été créés avec ces
    deux attributs vides — sans une ligne d'erreur nulle part."""

    def test_cree_les_attributs_manquants(self):
        bv = FakeBrevo(existants=["PRENOM", "NOM"])
        self.assertEqual(sorted(ensure_attributes(bv)), ["SEGMENT", "SOURCE"])
        self.assertEqual(sorted(bv.crees), ["SEGMENT", "SOURCE"])

    def test_idempotent_quand_tout_existe(self):
        bv = FakeBrevo(existants=list(CONTACT_ATTRIBUTES))
        self.assertEqual(ensure_attributes(bv), [])
        self.assertEqual(bv.crees, [])

    def test_leve_si_brevo_accepte_sans_stocker(self):
        """Le garde-fou : on relit le schéma au lieu de croire le code retour.

        Sans cette relecture, un POST accepté mais sans effet laisserait repartir
        exactement le même import silencieusement amputé.
        """
        bv = FakeBrevo(existants=["PRENOM", "NOM"], refuse=True)
        with self.assertRaises(BrevoError) as ctx:
            ensure_attributes(bv)
        self.assertIn("SEGMENT", str(ctx.exception))
        self.assertIn("SOURCE", str(ctx.exception))

    def test_les_attributs_envoyes_sont_tous_declares(self):
        """Le lien qui manquait, vérifié sur le VRAI payload du sync.

        Ce que `contact_attributes` pose doit être dans la liste que
        `ensure_attributes` garantit. Ajouter un attribut au payload sans le
        déclarer reproduirait le défaut à l'identique — et tout aussi
        silencieusement, puisque Brevo ne s'en plaint pas.
        """
        envoyes = crm_brevo.contact_attributes(
            {"first": "Ada", "last": "L", "email": "a@b.fr"}, "PROS"
        )
        self.assertEqual(set(envoyes), set(CONTACT_ATTRIBUTES))
        self.assertEqual(envoyes["SEGMENT"], "PROS")
        self.assertEqual(envoyes["SOURCE"], "twenty")


class TestConfiguration(unittest.TestCase):
    def test_chaque_segment_a_une_liste_et_un_html(self):
        for seg, cfg in SEGMENTS.items():
            self.assertTrue(cfg["list"], seg)
            self.assertTrue(cfg["html"].endswith(".html"), seg)
            self.assertTrue(cfg["subject"], seg)

    def test_aucune_categorie_ne_pointe_vers_deux_segments(self):
        """Deux segments qui revendiquent la même catégorie = envoi en double.

        Le mapping est aplati dans un dict, donc la collision serait silencieuse :
        le dernier segment déclaré gagnerait sans que rien ne le signale.
        """
        vues: dict[str, str] = {}
        for seg, cfg in SEGMENTS.items():
            for cat in cfg["categories"]:
                self.assertNotIn(cat, vues, f"{cat} revendiquée par {vues.get(cat)} et {seg}")
                vues[cat] = seg

    def test_les_relations_routent_vers_des_segments_connus(self):
        for _, _, seg in crm_brevo.RELATION_ROUTING:
            if seg is not None:
                self.assertIn(seg, SEGMENTS)


if __name__ == "__main__":
    unittest.main()
