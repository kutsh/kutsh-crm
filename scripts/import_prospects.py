#!/usr/bin/env python3
"""Importe les prospects du projet Basecamp « Prospects et partenaires » (46108107)
vers Twenty (People + Companies + Notes), via crm_client.

- Les emails / comptes-rendus restent dans Basecamp (source) et sont lus EN DIRECT
  (rien de personnel n'est figé dans ce script — uniquement le mapping métier).
- Idempotent : upsert Company par nom, Person par email (sinon nom), Note par titre.

Env : TWENTY_API_KEY (+ TWENTY_BASE_URL). Basecamp CLI authentifié requis.
Issue kata y89n.
"""
import os, re, sys, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from crm_client import TwentyClient  # noqa: E402  # type: ignore[import-not-found]

PROJECT = "46108107"
# mapping curé par carte (identités B2B + colonne) — pas d'email/CR ici
CARDS = {
 "9838400703": dict(people=[("Djoude","Merabet")]),
 "9801816541": dict(people=[("Jean-Baptiste","Roffini")], company="Delibia", title="Cofondateur"),
 "9784792006": dict(people=[("Antoine","Moriceau")], company="Mon Territoire", title="Responsable produit", city="Sarzeau"),
 "9751217935": dict(people=[("Eric","Piard")], company="CAUE 76"),
 "9746677600": dict(people=[("Delphine","Robin"),("Morgane","Merlin")], company="Territoire & Habitat Normand"),
 "9746564496": dict(people=[("Valérie","Lopes")], company="CAUE 76", title="Architecte conseil"),
 "9745881532": dict(people=[("Vincent","Doussinault")], company="FIBOIS"),
 "9815151825": dict(people=[("John","Galton")], company="ConstructionSalesBoost", title="Fondateur"),
 "9762685319": dict(people=[("Pascal","Montecot")], company="Métropole Aix-Marseille-Provence", title="VP urbanisme · Maire de Pélissanne"),
 "9843983151": dict(people=[("Gilles","Stadelmann")], company="Véranco"),
 "9801202700": dict(people=[("Céline","Duclos")], company="Habitat 76", title="Responsable pôle prospection & développement", city="Rouen"),
 "9788563146": dict(people=[("Stéphane","Buchon")], company="PARSEWAVES", title="Co-founder", city="Caen"),
 "9815446341": dict(people=[("Pascal","Di Stefano")], company="Mù Fangzi", title="Dirigeant"),
}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
LINKEDIN_RE = re.compile(r"linkedin\.com/in/[^\s)\"']+", re.I)


def bc_card(cid):
    out = subprocess.run(["basecamp", "cards", "show", cid, "--in", PROJECT, "--json"],
                         capture_output=True, text=True)
    d = json.loads(out.stdout); m = d.get("data", d)
    raw = m.get("content") or ""
    txt = re.sub(r"<[^>]+>", " ", raw)
    import html; txt = re.sub(r"\s+", " ", html.unescape(txt)).strip()
    col = (m.get("column") or m.get("parent") or {}).get("title", "")
    return m.get("title", "").strip(), txt, col


def main():
    c = TwentyClient()
    n_co = n_pe = n_no = 0
    for cid, meta in CARDS.items():
        title, content, col = bc_card(cid)
        emails = EMAIL_RE.findall(content)
        li = LINKEDIN_RE.search(content)
        li_url = ("https://" + li.group(0)) if li else None
        # company
        company_id = None
        if meta.get("company"):
            co = c.upsert("companies", "name", {"name": meta["company"]})
            company_id = co["id"]; n_co += 1
        people = meta["people"]
        first_pid = None
        for i, (fn, ln) in enumerate(people):
            fields = {}
            if meta.get("title"): fields["jobTitle"] = meta["title"]
            if meta.get("city"): fields["city"] = meta["city"]
            if company_id: fields["companyId"] = company_id
            if li_url and len(people) == 1: fields["linkedinLink"] = {"primaryLinkUrl": li_url}
            email = emails[i] if i < len(emails) and len(people) == 1 else (emails[0] if emails and len(people) == 1 else None)
            pid = c.upsert_contact(fn, ln, email=email, **fields)["id"]
            first_pid = first_pid or pid; n_pe += 1
            print(f"  person {fn} {ln}" + (f" <{email}>" if email else "") + (f" @ {meta.get('company')}" if company_id else ""))
        # note (CR / contexte) attachée au 1er contact, idempotente par titre
        note_title = f"Basecamp — {title}"[:200]
        if content and first_pid and not c.find_one("notes", "title", note_title):
            body = content + (f"\n\n_(Colonne Basecamp : {col})_" if col else "")
            note = c.create("notes", {"title": note_title, "bodyV2": {"markdown": body}})
            c.create("noteTargets", {"noteId": note["id"], "targetPersonId": first_pid})
            n_no += 1
    print(f"OK import: {n_pe} personnes, {n_co} sociétés (upsert), {n_no} notes")


if __name__ == "__main__":
    main()
