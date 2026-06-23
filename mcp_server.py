#!/usr/bin/env python3
"""Serveur MCP du CRM Kutsh — expose crm_client.py aux agents (issue 7k36).

Rend le CRM (Twenty) pilotable par Claude : lecture, contacts, collectivités,
opportunités, signaux, notes. Transport stdio.

Lancement : TWENTY_API_KEY=… uv run kutsh-crm-mcp
Enregistrement Claude Code : voir README (claude mcp add).
"""
from __future__ import annotations
from typing import Any, Optional
from mcp.server.fastmcp import FastMCP
from crm_client import TwentyClient

mcp = FastMCP("kutsh-crm")
_client: Optional[TwentyClient] = None


def client() -> TwentyClient:
    global _client
    if _client is None:
        _client = TwentyClient()  # lit TWENTY_API_KEY / TWENTY_BASE_URL
    return _client


def _phone(raw: Optional[str]) -> Optional[dict]:
    if not raw:
        return None
    n = raw.replace(" ", "")
    if n.startswith("+33"):
        return {"primaryPhoneNumber": n[3:], "primaryPhoneCallingCode": "+33", "primaryPhoneCountryCode": "FR"}
    return {"primaryPhoneNumber": n}


@mcp.tool()
def list_crm_objects() -> list[str]:
    """Liste les objets de données du CRM (people, companies, opportunities, et objets métier custom : collectivites, pluis, cabinets, editeursAds, signals)."""
    objs = client()._req("GET", "/rest/metadata/objects", params={"limit": 200})["data"]["objects"]
    return sorted(o["namePlural"] for o in objs if not o.get("isSystem") and not o.get("isRemote"))


@mcp.tool()
def list_records(object_plural: str, filter: Optional[str] = None, limit: int = 30) -> list[dict]:
    """Liste des enregistrements d'un objet. `filter` au format Twenty, ex. "name.lastName[eq]:Dupont" ou "statut[eq]:NOUVEAU"."""
    return client().list(object_plural, filter=filter, limit=limit)


@mcp.tool()
def find_person(first_name: str, last_name: str = "", email: Optional[str] = None) -> Optional[dict]:
    """Retrouve une personne par email (prioritaire) ou par nom/prénom. Renvoie l'enregistrement ou null."""
    return client().find_person(first_name, last_name, email)


@mcp.tool()
def upsert_contact(first_name: str, last_name: str, email: Optional[str] = None,
                   phone: Optional[str] = None, job_title: Optional[str] = None,
                   city: Optional[str] = None) -> dict:
    """Crée ou met à jour une personne (idempotent par email puis par nom). `phone` accepté en format +33…."""
    fields: dict[str, Any] = {}
    ph = _phone(phone)
    if ph:
        fields["phones"] = ph
    if job_title:
        fields["jobTitle"] = job_title
    if city:
        fields["city"] = city
    return client().upsert_contact(first_name, last_name, email=email, **fields)


@mcp.tool()
def get_territory(code_insee_siren: str) -> Optional[dict]:
    """Récupère une Collectivité par son code INSEE/SIREN, ou null."""
    return client().get_territory(code_insee_siren)


@mcp.tool()
def upsert_collectivite(code_insee_siren: str, name: str, population: Optional[int] = None,
                        statut_doc: Optional[str] = None, fields_json: Optional[str] = None) -> dict:
    """Crée/met à jour une Collectivité (idempotent par codeInseeSiren). `statut_doc` ∈ {RNU,PLU,PLUI}. `fields_json` = JSON d'attributs additionnels."""
    import json
    extra = json.loads(fields_json) if fields_json else {}
    if population is not None:
        extra["population"] = population
    if statut_doc:
        extra["statutDoc"] = statut_doc
    return client().upsert_collectivite(code_insee_siren, name, **extra)


@mcp.tool()
def create_opportunity(name: str, segment: str, stage: str = "PROSPECTION",
                       amount: Optional[float] = None, company_id: Optional[str] = None,
                       point_of_contact_id: Optional[str] = None) -> dict:
    """Crée une opportunité. `segment` ∈ {B2G,B2B,B2B2B}. `stage` ∈ {PROSPECTION,QUALIFICATION,ECHANGE,OFFRE,EVALUATION,GAGNE,EXECUTION,PERDU}."""
    data: dict[str, Any] = {"name": name, "segment": segment, "stage": stage}
    if amount is not None:
        data["amount"] = {"amountMicros": int(amount * 1_000_000), "currencyCode": "EUR"}
    if company_id:
        data["companyId"] = company_id
    if point_of_contact_id:
        data["pointOfContactId"] = point_of_contact_id
    return client().create("opportunities", data)


@mcp.tool()
def update_deal(opportunity_id: str, fields_json: str) -> dict:
    """Met à jour une opportunité. `fields_json` = JSON des champs (ex. {"stage":"OFFRE"})."""
    import json
    return client().update_deal(opportunity_id, **json.loads(fields_json))


@mcp.tool()
def create_signal(name: str, type_signal: str, action_suggeree: Optional[str] = None,
                  statut: str = "NOUVEAU") -> dict:
    """Crée un Signal (événement détecté : révision PLUi, marché public, post LinkedIn, refus de dossier…) avec action suggérée."""
    return client().create_signal(name, type_signal, action_suggeree=action_suggeree, statut=statut)


@mcp.tool()
def add_note(title: str, body: str = "", person_id: Optional[str] = None,
             company_id: Optional[str] = None, opportunity_id: Optional[str] = None) -> dict:
    """Crée une note, éventuellement rattachée à une personne / société / opportunité (via noteTarget)."""
    note = client().create("notes", {"title": title, "bodyV2": {"markdown": body}} if body else {"title": title})
    target: dict[str, Any] = {"noteId": note["id"]}
    if person_id:
        target["personId"] = person_id
    if company_id:
        target["companyId"] = company_id
    if opportunity_id:
        target["opportunityId"] = opportunity_id
    if len(target) > 1:
        client().create("noteTargets", target)
    return note


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
