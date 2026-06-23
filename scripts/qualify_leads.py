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
import os, sys, json, re, argparse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from crm_client import TwentyClient  # noqa: E402  # type: ignore[import-not-found]

PERSONAL_DOMAINS = {
    "gmail.com", "hotmail.fr", "hotmail.com", "outlook.fr", "outlook.com",
    "yahoo.fr", "yahoo.com", "orange.fr", "free.fr", "wanadoo.fr", "sfr.fr",
    "laposte.net", "pm.me", "proton.me", "icloud.com",
}
SEGMENTS = {"B2G", "B2B", "B2B2B"}
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

PROMPT = """Tu qualifies un lead entrant pour Kutsh, une startup d'IA de conformité \
urbanisme/PLU. Cibles : collectivités (B2G), cabinets de dessinateurs-projeteurs / \
architectes (B2B), fabricants à réseau de revendeurs / configurateurs (B2B2B).

Lead : prénom={first!r} nom={last!r} email={email!r} (domaine={domain!r}).

Déduis l'organisation probable (nom lisible depuis le domaine, ou null si email \
personnel), le segment, un brief de qualification (2 phrases max), et une action \
suggérée concrète (1 phrase). Réponds STRICTEMENT en JSON :
{{"organisation": <str|null>, "segment": "B2G"|"B2B"|"B2B2B"|"INCONNU", "brief": <str>, "action": <str>}}"""


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
    if domain in PERSONAL_DOMAINS:
        out["organisation"] = None
    return out


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
        print(f"      orga={org!r} segment={seg or 'INCONNU'}")
        print(f"      brief: {q.get('brief')}")
        print(f"      action: {q.get('action')}")
        if not a.apply:
            continue
        # --- écritures Twenty ---
        # Company seulement si classification confiante (orga ET segment) —
        # évite de créer des sociétés douteuses sur les leads INCONNU.
        company_id = None
        if org and seg:
            company = c.upsert("companies", "name", {"name": org})
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
        c.create("opportunities", deal)
        note = c.create("notes", {
            "title": f"Qualification — {first} {last}",
            "bodyV2": {"markdown": f"**Segment** : {seg or 'à préciser'}\n\n"
                                   f"{q.get('brief')}\n\n**Action suggérée** : {q.get('action')}"},
        })
        c.create("noteTargets", {"noteId": note["id"], "targetPersonId": p["id"]})
        done += 1
    if a.apply:
        print(f"\nOK : {done} lead(s) qualifié(s) (Deal + Note créés).")
    else:
        print("\n(DRY-RUN — rien écrit. Relancer avec --apply pour appliquer.)")


if __name__ == "__main__":
    main()
