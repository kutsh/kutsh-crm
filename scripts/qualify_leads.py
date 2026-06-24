#!/usr/bin/env python3
"""qualify_leads.py — qualifie les leads entrants du CRM Twenty (issue swpx).

Trouve les People sans Deal (= leads non qualifiés), classe chacun via OpenRouter
(organisation, segment B2G/B2B/B2B2B, brief + action suggérée), puis écrit dans
Twenty : upsert Company + lien Person, création du Deal (stage PROSPECTION) et
d'une Note de qualification. Idempotent (skip si la personne a déjà un Deal).

Rôle « batch/compute » de la couche Python (ADR 2026-06-23) : écrit dans Twenty.
La diffusion dans Basecamp reste à kutshbot.

Usage :
  TWENTY_API_KEY=… OPENROUTER_API_KEY=… python scripts/qualify_leads.py [--apply] [--limit N] [--model M]
Sans --apply : DRY-RUN (n'écrit rien, montre le plan).
"""
from __future__ import annotations
import os
import sys
import json
import re
import argparse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from crm_client import TwentyClient  # noqa: E402  # type: ignore[import-not-found]

PERSONAL_DOMAINS = {
    "gmail.com", "hotmail.fr", "hotmail.com", "outlook.fr", "outlook.com",
    "yahoo.fr", "yahoo.com", "orange.fr", "free.fr", "wanadoo.fr", "sfr.fr",
    "laposte.net", "pm.me", "proton.me", "icloud.com",
}
SEGMENTS = {"B2G", "B2B", "B2B2B"}
CATEGORIES = {
    "COLLECTIVITE_EPCI", "FEDERATION_PRO", "FEDERATION_COLLECTIVITES", "RESEAU_ELUS",
    "CABINET", "EDITEUR_ADS", "FABRICANT", "MEDIA", "ACADEMIQUE", "INSTITUTIONNEL", "AUTRE",
}
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

PROMPT = """Tu qualifies un lead entrant pour Kutsh, une startup d'IA de conformité \
urbanisme/PLU. Cibles : collectivités (B2G), cabinets de dessinateurs-projeteurs / \
architectes (B2B), fabricants à réseau de revendeurs / configurateurs (B2B2B).

Lead : prénom={first!r} nom={last!r} email={email!r} (domaine={domain!r}).

Déduis l'organisation probable (nom lisible depuis le domaine, ou null si email \
personnel), le segment, la catégorie d'organisation, un brief de qualification \
(2 phrases max), et une action suggérée concrète (1 phrase).

Catégories possibles (ou null si indéterminable) : COLLECTIVITE_EPCI (mairie, \
métropole, EPCI), CABINET (dessinateur-projeteur / architecte), FABRICANT, \
EDITEUR_ADS (éditeur de logiciel ADS / urbanisme), FEDERATION_PRO (fédération ou \
syndicat professionnel, ex FNDI), FEDERATION_COLLECTIVITES (asso/fédération de \
collectivités, ex AMF / France urbaine), RESEAU_ELUS, MEDIA, ACADEMIQUE, \
INSTITUTIONNEL (CEREMA / CAUE…), AUTRE.

Réponds STRICTEMENT en JSON :
{{"organisation": <str|null>, "segment": "B2G"|"B2B"|"B2B2B"|"INCONNU", \
"categorie": <str|null>, "brief": <str>, "action": <str>}}"""


def classify(first: str, last: str, email: str, model: str) -> dict:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY manquant")
    domain = email.split("@")[-1] if "@" in email else ""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT.format(
            first=first, last=last, email=email, domain=domain)}],
        "response_format": {"type": "json_object"},
        "max_tokens": 400,
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        OPENROUTER_URL, data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    content = (data["choices"][0]["message"]["content"] or "").strip()
    content = re.sub(r"^```(?:json)?|```$", "", content).strip()  # retire d'éventuels fences
    out = json.loads(content)
    seg = (out.get("segment") or "").upper()
    out["segment"] = seg if seg in SEGMENTS else None
    cat = (out.get("categorie") or "").upper()
    out["categorie"] = cat if cat in CATEGORIES else None
    if domain in PERSONAL_DOMAINS:
        out["organisation"] = None
        out["categorie"] = None
    return out


def post_basecamp_digest(items: list[dict]) -> None:
    """Poste un digest des leads qualifiés dans le Campfire Basecamp (même
    mécanisme que la landing : lines_url signée). Non bloquant."""
    url = os.environ.get("BASECAMP_CHATBOT_LINES_URL")
    if not url or not items:
        return
    base = (os.environ.get("TWENTY_BASE_URL") or "https://twenty.kutsh.fr").rstrip("/")
    rows = []
    for it in items:
        seg = it.get("segment") or "à préciser"
        org_part = f" — {it['org']}" if it.get("org") else ""
        # Le nom pointe vers la carte Deal (le pipeline = là où on agit) ; + lien fiche contact.
        deal_url = f"{base}/object/opportunity/{it['deal_id']}" if it.get("deal_id") else None
        person_url = f"{base}/object/person/{it['person_id']}" if it.get("person_id") else None
        name = f'<a href="{deal_url}">{it["name"]}</a>' if deal_url else it["name"]
        action = it.get("action") or ""
        fiche = f' · <a href="{person_url}">fiche contact ↗</a>' if person_url else ""
        rows.append(f"• <b>{name}</b>{org_part} <i>[{seg}]</i><br>&nbsp;&nbsp;↳ {action}{fiche}")
    content = (f"🎯 <b>Qualification — {len(items)} lead(s)</b> "
               f'(<a href="{base}/objects/opportunities">pipeline ↗</a>)<br>' + "<br>".join(rows))
    try:
        req = urllib.request.Request(
            url, data=json.dumps({"content": content}).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20)
    except Exception:
        print("  ⚠ digest Basecamp non posté (lines_url ?)")


def unqualified_leads(c: TwentyClient) -> list[dict]:
    contacted = {
        o.get("pointOfContactId")
        for o in c.list_all("opportunities", depth=0)
        if o.get("pointOfContactId")
    }
    return [p for p in c.list_all("people", depth=0) if p["id"] not in contacted]


def fullname(p: dict) -> tuple[str, str]:
    n = p.get("name") or {}
    return (n.get("firstName") or "", n.get("lastName") or "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="écrit dans Twenty (sinon dry-run)")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--model", default=os.environ.get("QUALIFY_MODEL", "openai/gpt-4o-mini"))
    a = ap.parse_args()
    mode = "APPLY" if a.apply else "DRY-RUN"
    c = TwentyClient()

    leads = unqualified_leads(c)[: a.limit]
    print(f"[{mode}] {len(leads)} lead(s) non qualifié(s) à traiter (modèle {a.model})\n")
    done = 0
    qualified: list[dict] = []
    for p in leads:
        first, last = fullname(p)
        email = ((p.get("emails") or {}).get("primaryEmail")) or ""
        try:
            q = classify(first, last, email, a.model)
        except Exception as e:  # un lead illisible ne bloque pas le lot
            print(f"  ⚠ {first} {last}: classification KO ({e})")
            continue
        org, seg = q.get("organisation"), q.get("segment")
        print(f"  • {first} {last} <{email}>")
        print(f"      orga={org!r} segment={seg or 'INCONNU'} categorie={q.get('categorie') or '—'}")
        print(f"      brief: {q.get('brief')}")
        print(f"      action: {q.get('action')}")
        if not a.apply:
            continue
        # --- écritures Twenty ---
        # Company seulement si classification confiante (orga ET segment) —
        # évite de créer des sociétés douteuses sur les leads INCONNU.
        company_id = None
        if org and seg:
            existing = c.find_one("companies", "name", org)
            payload = {"name": org}
            cat = q.get("categorie")
            # Catégorie posée seulement si absente (ne pas écraser une curation humaine).
            if cat and not (existing and existing.get("categorie")):
                payload["categorie"] = cat
            company = c.upsert("companies", "name", payload)
            company_id = company["id"]
            # Ne pas écraser un rattachement existant (contacts déjà curés).
            if not p.get("companyId"):
                c.update("people", p["id"], {"companyId": company_id})
        deal: dict = {
            "name": f"Lead — {first} {last}" + (f" ({org})" if org else ""),
            "stage": "PROSPECTION",
            "pointOfContactId": p["id"],
        }
        if seg:
            deal["segment"] = seg
        if company_id:
            deal["companyId"] = company_id
        deal_rec = c.create("opportunities", deal)
        note = c.create("notes", {
            "title": f"Qualification — {first} {last}",
            "bodyV2": {"markdown": f"**Segment** : {seg or 'à préciser'}\n\n"
                                   f"{q.get('brief')}\n\n**Action suggérée** : {q.get('action')}"},
        })
        c.create("noteTargets", {"noteId": note["id"], "targetPersonId": p["id"]})
        done += 1
        qualified.append({"name": f"{first} {last}", "org": org, "segment": seg,
                          "action": q.get("action"), "deal_id": deal_rec.get("id"), "person_id": p["id"]})
    if a.apply:
        post_basecamp_digest(qualified)
        print(f"\nOK : {done} lead(s) qualifié(s) (Deal + Note créés"
              + (", digest Basecamp posté)." if qualified else ")."))
    else:
        print("\n(DRY-RUN — rien écrit. Relancer avec --apply pour appliquer.)")


if __name__ == "__main__":
    main()
