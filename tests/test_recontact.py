"""Tests de la logique des files de recontact (fonction pure compute_queues)."""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import recontact  # noqa: E402


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _sol(**kw):
    base = {
        "id": kw.get("id", "s1"),
        "dateSollicitation": kw.get("date", _iso(0)),
        "accuseEnvoye": kw.get("accuse"),
        "remercieEnvoye": kw.get("merci"),
        "person": kw.get("person", {"name": {"firstName": "A", "lastName": "B"}}),
        "demande": kw.get("demande", {"id": "d1", "name": "X", "statut": "A_TRIER"}),
    }
    return base


def test_triage_si_pas_de_demande_ou_pas_de_person():
    sols = [
        _sol(id="a", demande=None),
        _sol(id="b", person=None),
        _sol(id="c"),  # complet → pas en triage
    ]
    q = recontact.compute_queues(sols, ack_max_age_days=3)
    ids = {s["id"] for s in q["triage"]}
    assert ids == {"a", "b"}


def test_accuse_seulement_recent_et_demande_active_sans_accuse():
    sols = [
        _sol(id="frais", date=_iso(1), demande={"id": "d", "name": "X", "statut": "RECUE"}),
        _sol(id="vieux", date=_iso(30), demande={"id": "d", "name": "X", "statut": "RECUE"}),  # trop vieux
        _sol(id="deja", date=_iso(1), accuse=_iso(0), demande={"id": "d", "name": "X", "statut": "RECUE"}),  # déjà accusé
        _sol(id="livree", date=_iso(1), demande={"id": "d", "name": "X", "statut": "LIVREE"}),  # plus active
    ]
    q = recontact.compute_queues(sols, ack_max_age_days=3)
    assert {s["id"] for s in q["accuse"]} == {"frais"}


def test_merci_si_livree_et_pas_encore_remercie():
    sols = [
        _sol(id="a", demande={"id": "d", "name": "X", "statut": "LIVREE"}),
        _sol(id="b", merci=_iso(0), demande={"id": "d", "name": "X", "statut": "LIVREE"}),  # déjà remercié
        _sol(id="c", demande={"id": "d", "name": "X", "statut": "EN_COURS"}),  # pas livrée
    ]
    q = recontact.compute_queues(sols, ack_max_age_days=3)
    assert {s["id"] for s in q["merci"]} == {"a"}


def test_une_sollicitation_livree_recente_sans_accuse_va_en_merci_pas_en_accuse():
    # Livrée => on remercie, on n'accuse pas réception (le statut n'est plus actif).
    sols = [_sol(id="x", date=_iso(1), demande={"id": "d", "name": "X", "statut": "LIVREE"})]
    q = recontact.compute_queues(sols, ack_max_age_days=3)
    assert {s["id"] for s in q["merci"]} == {"x"}
    assert q["accuse"] == []
