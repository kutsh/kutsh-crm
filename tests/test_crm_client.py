#!/usr/bin/env python3
"""Tests du client Twenty (stdlib pur : `python -m unittest`), sans réseau.

Ce module n'avait aucun test tant qu'il existait en deux exemplaires : la copie
de kutsh-data portait les siens, ce qui donnait l'illusion d'une couverture. La
copie ayant été supprimée (kata `jnnf`), ses tests sont repris ici — plus ceux
du throttle et du retry, que ni l'une ni l'autre ne couvrait alors que c'est
exactement le code mis en cause par l'incident 2026-07-20 (rafales de 429).
"""

from __future__ import annotations

import os
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import crm_client  # noqa: E402
from crm_client import TYPE_SIGNAL_VALUES, TwentyClient, TwentyError  # noqa: E402


class TestConstruction(unittest.TestCase):
    def test_exige_une_cle_api(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(TwentyError):
                TwentyClient()

    def test_base_url_par_defaut_et_override(self):
        with mock.patch.dict(os.environ, {"TWENTY_API_KEY": "k"}, clear=True):
            self.assertEqual(TwentyClient().base, "https://twenty.kutsh.fr")
        # Le slash final est retiré : sinon toutes les URLs sortent en `//rest/...`.
        with mock.patch.dict(os.environ, {"TWENTY_API_KEY": "k"}, clear=True):
            c = TwentyClient(base_url="https://crm.example.invalid/")
            self.assertEqual(c.base, "https://crm.example.invalid")


def _client() -> TwentyClient:
    return TwentyClient(api_key="k", base_url="https://crm.example.invalid")


class TestCreateSignal(unittest.TestCase):
    def test_refuse_un_type_signal_hors_select(self):
        """Un SELECT Twenty refuse toute valeur hors liste : on lève avant l'appel.

        Sans ça l'erreur remonte en HTTP 400 tronqué à 300 caractères, sans la
        liste des valeurs attendues.
        """
        c = _client()
        with mock.patch.object(c, "_req", side_effect=AssertionError("ne doit pas appeler")):
            with self.assertRaises(TwentyError) as ctx:
                c.create_signal("x", "PAS_UN_TYPE")
        self.assertIn("REVISION_PLUI", str(ctx.exception))

    def test_corps_de_requete_attendu(self):
        c = _client()
        with mock.patch.object(c, "_req", return_value={"data": {"signal": {"id": "1"}}}) as req:
            c.create_signal("Révision PLUi Trifouillis", "REVISION_PLUI", action_suggeree="Appeler")
        req.assert_called_once_with(
            "POST",
            "/rest/signals",
            body={
                "name": "Révision PLUi Trifouillis",
                "typeSignal": "REVISION_PLUI",
                "statut": "NOUVEAU",
                "actionSuggeree": "Appeler",
            },
        )

    def test_renouvellement_ads_est_une_valeur_admise(self):
        """Valeur ajoutée par le détecteur de renouvellements ADS de kutsh-data.

        Elle n'existait que dans la copie kutsh-data : la fusion des deux clients
        (kata `jnnf`) la perdrait silencieusement si personne ne la vérifiait.
        """
        self.assertIn("RENOUVELLEMENT_ADS", TYPE_SIGNAL_VALUES)


class TestPagination(unittest.TestCase):
    def test_list_all_suit_le_curseur_et_passe_depth(self):
        c = _client()
        pages = [
            ({"data": {"cabinets": [{"id": "a"}]}, "pageInfo": {"hasNextPage": True, "endCursor": "c1"}}),
            ({"data": {"cabinets": [{"id": "b"}]}, "pageInfo": {"hasNextPage": False}}),
        ]
        with mock.patch.object(c, "_req", side_effect=pages) as req:
            rows = list(c.list_all("cabinets", page_size=60))
        self.assertEqual([r["id"] for r in rows], ["a", "b"])
        # depth=0 par défaut : sans lui Twenty sérialise les relations de chaque
        # enregistrement, ce qui multiplie le volume de l'export par ~10.
        self.assertEqual(req.call_args_list[0].kwargs["params"], {"limit": 60, "depth": 0})
        self.assertEqual(
            req.call_args_list[1].kwargs["params"], {"limit": 60, "depth": 0, "starting_after": "c1"}
        )

    def test_list_all_s_arrete_sans_curseur_meme_si_has_next_page(self):
        """`hasNextPage` sans `endCursor` doit terminer, pas boucler à l'infini."""
        c = _client()
        page = {"data": {"cabinets": [{"id": "a"}]}, "pageInfo": {"hasNextPage": True}}
        with mock.patch.object(c, "_req", return_value=page):
            self.assertEqual(len(list(c.list_all("cabinets"))), 1)


class TestUpsert(unittest.TestCase):
    def test_met_a_jour_quand_la_cle_existe(self):
        c = _client()
        with mock.patch.object(c, "find_one", return_value={"id": "42"}):
            with mock.patch.object(c, "update", return_value={"id": "42"}) as upd:
                with mock.patch.object(c, "create", side_effect=AssertionError("pas de create")):
                    c.upsert_collectivite("13001", "Marseille", population=870000)
        self.assertEqual(upd.call_args.args[0], "collectivites")
        self.assertEqual(upd.call_args.args[1], "42")

    def test_cree_quand_la_cle_est_absente(self):
        c = _client()
        with mock.patch.object(c, "find_one", return_value=None):
            with mock.patch.object(c, "create", return_value={"id": "43"}) as cre:
                c.upsert_collectivite("13002", "Aix")
        self.assertEqual(cre.call_args.args[1]["codeInseeSiren"], "13002")

    def test_cle_nulle_cree_sans_interroger_l_api(self):
        """Un upsert sans valeur de clé ne doit pas partir en `filter=…[eq]:None`."""
        c = _client()
        with mock.patch.object(c, "find_one", side_effect=AssertionError("pas de find_one")):
            with mock.patch.object(c, "create", return_value={"id": "44"}):
                c.upsert("cabinets", "siren", {"name": "sans siren"})


class _FakeHTTPError(urllib.error.HTTPError):
    def __init__(self, code: int, retry_after: str | None = None):
        headers = {"Retry-After": retry_after} if retry_after is not None else {}
        super().__init__("https://x", code, "boom", headers, None)  # type: ignore[arg-type]

    def read(self) -> bytes:  # le corps est relu dans le message d'erreur
        return b"detail"


class TestRetry(unittest.TestCase):
    """Le mode d'échec de l'incident 2026-07-20 : rafales de 429 sur le quota
    partagé du workspace Twenty (100 req/60 s). Le retry est ce qui les absorbe."""

    def setUp(self):
        # Le throttle et les backoffs sont neutralisés : on teste la logique de
        # décision, pas la patience (sinon la suite dure des minutes).
        self.sleeps: list[float] = []
        patches = [
            mock.patch.object(crm_client.time, "sleep", self.sleeps.append),
            mock.patch.object(crm_client, "_throttle", lambda: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _run(self, side_effect):
        c = _client()
        with mock.patch.object(crm_client.urllib.request, "urlopen", side_effect=side_effect):
            return c._req("GET", "/rest/cabinets")

    def test_429_puis_succes(self):
        ok = mock.MagicMock()
        ok.__enter__.return_value.read.return_value = b'{"data": {"cabinets": []}}'
        self.assertEqual(
            self._run([_FakeHTTPError(429, "3"), ok]), {"data": {"cabinets": []}}
        )
        self.assertEqual(self.sleeps, [3.0])  # Retry-After honoré

    def test_retry_after_illisible_retombe_sur_le_backoff_par_defaut(self):
        ok = mock.MagicMock()
        ok.__enter__.return_value.read.return_value = b"{}"
        self._run([_FakeHTTPError(503, "Wed, 21 Oct 2015 07:28:00 GMT"), ok])
        self.assertEqual(self.sleeps, [20.0])

    def test_429_persistant_finit_en_erreur(self):
        with self.assertRaises(TwentyError) as ctx:
            self._run([_FakeHTTPError(429) for _ in range(6)])
        self.assertIn("429", str(ctx.exception))
        self.assertEqual(len(self.sleeps), 5)  # 6 tentatives, 5 attentes

    def test_404_ne_retente_pas(self):
        with self.assertRaises(TwentyError):
            self._run([_FakeHTTPError(404)])
        self.assertEqual(self.sleeps, [])

    def test_blip_reseau_retente(self):
        ok = mock.MagicMock()
        ok.__enter__.return_value.read.return_value = b"{}"
        self._run([urllib.error.URLError("timeout SSL"), ok])
        self.assertEqual(self.sleeps, [5])


class TestThrottle(unittest.TestCase):
    """Fenêtre glissante AU NIVEAU MODULE, et c'est le point : le quota Twenty est
    par workspace, pas par client. Une fenêtre par instance (ce que faisait la
    copie kutsh-data) ne protège pas de deux clients dans le même process."""

    def setUp(self):
        crm_client._calls.clear()
        self.addCleanup(crm_client._calls.clear)

    def test_sous_le_plafond_aucune_attente(self):
        with mock.patch.object(crm_client.time, "sleep") as slp:
            for _ in range(crm_client._RATE_LIMIT - 1):
                crm_client._throttle()
        slp.assert_not_called()

    def test_le_compteur_est_partage_entre_instances(self):
        _client(), _client()  # deux clients, un seul quota
        with mock.patch.object(crm_client.time, "sleep") as slp:
            for _ in range(crm_client._RATE_LIMIT + 1):
                crm_client._throttle()
        slp.assert_called()

    def test_les_appels_hors_fenetre_sont_oublies(self):
        now = crm_client.time.monotonic()
        crm_client._calls.extend(now - crm_client._RATE_WINDOW - 1 for _ in range(crm_client._RATE_LIMIT))
        with mock.patch.object(crm_client.time, "sleep") as slp:
            crm_client._throttle()
        slp.assert_not_called()
        self.assertEqual(len(crm_client._calls), 1)


if __name__ == "__main__":
    unittest.main()
