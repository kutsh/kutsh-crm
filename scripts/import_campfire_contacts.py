#!/usr/bin/env python3
"""Importe les contacts entrants déposés dans le Campfire Basecamp du projet
« Prospects et partenaires » (lignes « Nouveau contact landing page » de kutshbot)
vers Twenty comme People (nom, email, téléphone). Idempotent par email.

Lecture EN DIRECT depuis Basecamp (rien de personnel figé dans le repo).
Env : TWENTY_API_KEY (+ TWENTY_BASE_URL). Basecamp CLI requis. Issue kata y89n.
"""
import os, re, sys, json, html, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from crm_client import TwentyClient  # noqa: E402  # type: ignore[import-not-found]

PROJECT = "46108107"
MARKER = "Nouveau contact landing page"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"T[ée]l[ée]phone\s*:?\s*(\+?\d[\d ]+)")


def title(s: str) -> str:
    return " ".join(w.title() if not any(c.isdigit() for c in w) else w for w in s.split())


def parse_phone(raw: str | None):
    if not raw:
        return None
    num = raw.replace(" ", "")
    if num.startswith("+33"):
        return {"primaryPhoneNumber": num[3:], "primaryPhoneCallingCode": "+33", "primaryPhoneCountryCode": "FR"}
    return {"primaryPhoneNumber": num}


def chat_lines():
    out = subprocess.run(["basecamp", "chat", "messages", "--in", PROJECT, "--json"],
                         capture_output=True, text=True)
    for ln in (json.loads(out.stdout).get("data") or []):
        c = ln.get("content") or ""
        c = re.sub(r"<[^>]+>", " ", c)
        c = re.sub(r"\s+", " ", html.unescape(c)).strip()
        yield c


def main():
    c = TwentyClient()
    n = 0
    seen = set()
    for line in chat_lines():
        if MARKER not in line:
            continue
        after = line.split(MARKER, 1)[1].strip()
        em = EMAIL_RE.search(after)
        if not em:
            continue
        email = em.group(0).lower()
        if email in seen:
            continue
        seen.add(email)
        # nom = avant le tiret cadratin (ou avant l'email)
        name_part = re.split(r"\s[—–-]\s", after)[0].strip()
        name_part = name_part.split(em.group(0))[0].strip(" —–-")
        toks = name_part.split()
        if not toks:
            continue
        first = title(toks[0])
        last = title(" ".join(toks[1:])) if len(toks) > 1 else ""
        ph = PHONE_RE.search(after)
        fields = {}
        phones = parse_phone(ph.group(1) if ph else None)
        if phones:
            fields["phones"] = phones
        c.upsert_contact(first, last, email=email, **fields)
        n += 1
        print(f"  {first} {last} <{email}>" + (" 📞" if phones else ""))
    print(f"OK Campfire: {n} contacts entrants (upsert par email)")


if __name__ == "__main__":
    main()
