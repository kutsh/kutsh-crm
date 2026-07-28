#!/usr/bin/env python3
"""Tests du parsing téléphone / payload de réintégration (stdlib : unittest).

On vérifie la cohérence avec `landing/src/lib/twenty.ts` (mêmes règles +33) et
que le payload porte bien le canal — pas d'appel réseau.
"""
from __future__ import annotations
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from reintegrate_landing_contacts import parse_phone, build_payload  # noqa: E402


class TestParsePhone(unittest.TestCase):
    def test_vide(self):
        self.assertIsNone(parse_phone(None))
        self.assertIsNone(parse_phone(""))

    def test_plus_33(self):
        self.assertEqual(
            parse_phone("+33643866839"),
            {"primaryPhoneNumber": "643866839", "primaryPhoneCallingCode": "+33",
             "primaryPhoneCountryCode": "FR"},
        )

    def test_plus_33_retire_le_zero_national(self):
        # cas réel du Campfire : « +330614295836 » → E.164 sans le 0 national.
        self.assertEqual(parse_phone("+330614295836")["primaryPhoneNumber"], "614295836")

    def test_prefixe_international_00(self):
        # « 0033673732803 » : 00 → +, puis règle +33 (Twenty rejetait le format brut).
        self.assertEqual(
            parse_phone("0033673732803"),
            {"primaryPhoneNumber": "673732803", "primaryPhoneCallingCode": "+33",
             "primaryPhoneCountryCode": "FR"},
        )

    def test_national_fr(self):
        self.assertEqual(
            parse_phone("0643866839"),
            {"primaryPhoneNumber": "643866839", "primaryPhoneCallingCode": "+33",
             "primaryPhoneCountryCode": "FR"},
        )

    def test_espaces_ignores(self):
        self.assertEqual(parse_phone("+33 6 43 86 68 39")["primaryPhoneNumber"], "643866839")


class TestBuildPayload(unittest.TestCase):
    def test_payload_minimal_porte_le_canal(self):
        p = build_payload({"firstName": "Marie", "lastName": "COEUR", "email": "m@x.fr"})
        self.assertEqual(p["canalAcquisition"], "LANDING_PAGE")
        self.assertEqual(p["emails"], {"primaryEmail": "m@x.fr"})
        self.assertEqual(p["name"], {"firstName": "Marie", "lastName": "COEUR"})
        self.assertNotIn("phones", p)

    def test_payload_avec_telephone(self):
        p = build_payload({"firstName": "T", "lastName": "F", "email": "t@x.fr",
                           "phone": "+33643866839"})
        self.assertEqual(p["phones"]["primaryPhoneCountryCode"], "FR")


if __name__ == "__main__":
    unittest.main()
