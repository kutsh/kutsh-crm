#!/usr/bin/env python3
"""sync_twenty_brevo.py — synchronise les contacts Twenty vers des listes Brevo,
crée les brouillons de campagne, et rapatrie les désinscriptions Brevo → Twenty.

Segmentation : la liste Brevo d'un contact est déduite de la `categorie` de son
organisation (Company) dans Twenty. Mapping dans CATEGORIE_TO_SEGMENT ci-dessous.

Sous-commandes :
  plan        Dry-run : compte les contacts par segment, n'écrit rien (Twenty ni Brevo).
  ensure      Idempotent : crée les champs newsletter (Twenty) + le dossier/listes (Brevo).
  sync        Pousse les contacts dans les listes Brevo (upsert, saute les désinscrits).
  reconcile   Rapatrie les désinscrits/blacklistés Brevo dans Twenty (newsletterOptOut).
  drafts      Crée les 3 brouillons de campagne dans Brevo depuis newsletters/*.html.
  all         ensure -> reconcile -> sync (l'enchaînement du cron ; PAS drafts).

Env requis : TWENTY_API_KEY, BREVO_API_KEY.
Env optionnels : TWENTY_BASE_URL (déf. https://twenty.kutsh.fr),
  BREVO_SENDER_EMAIL / BREVO_SENDER_NAME (sinon 1er expéditeur Brevo vérifié),
  BREVO_FOLDER (déf. "Kutsh CRM"), LAZONE_URL (déf. https://lazone.kutsh.fr).

Exemples :
  TWENTY_API_KEY=… BREVO_API_KEY=… python scripts/sync_twenty_brevo.py plan
  … python scripts/sync_twenty_brevo.py all          # cron
  … python scripts/sync_twenty_brevo.py drafts        # (re)crée les brouillons
"""
from __future__ import annotations
import os, sys, json, time, argparse, urllib.request, urllib.parse, urllib.error
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from crm_client import TwentyClient  # noqa: E402  # type: ignore[import-not-found]

# ---------------------------------------------------------------------------
# Configuration segments — catégorie d'organisation (Twenty) -> liste Brevo.
# 3 segments alignés sur les 3 newsletters. Ajuster ici si besoin.
# ---------------------------------------------------------------------------
SEGMENTS = {
    "COLLECTIVITES": {
        "list": "Kutsh — Collectivités & ADS",
        "categories": [
            "COLLECTIVITE_EPCI", "INSTRUCTEUR_PRIVE",
            "FEDERATION_COLLECTIVITES", "RESEAU_ELUS",
        ],
        "html": "collectivites.html",
        "subject": "Instruire une parcelle en 15 secondes, pas 15 minutes",
    },
    "PROS": {
        "list": "Kutsh — Pros de l'urbanisme",
        "categories": [
            "CABINET", "CABINET_AVOCATS", "RESEAU_PRO", "FABRICANT",
            "GSB_DISTRIBUTION", "CONSTRUCTEUR", "INSTALLATEUR",
            "AGENCE_IMMO", "COURTIER_TRAVAUX", "FEDERATION_PRO",
        ],
        "html": "pros.html",
        "subject": "Tout ce qu'un terrain cache, avant même de vous déplacer",
    },
    "ECOSYSTEME": {
        "list": "Kutsh — Écosystème & institutionnels",
        "categories": ["MEDIA", "ACADEMIQUE", "INSTITUTIONNEL", "EDITEUR_ADS"],
        "html": "ecosysteme.html",
        "subject": "Où en est Kutsh — et ce qu'on vient de mettre en ligne",
    },
}
# Catégories volontairement NON ciblées (restent hors newsletter) : AUTRE, null.
CATEGORIE_TO_SEGMENT = {
    cat: seg for seg, cfg in SEGMENTS.items() for cat in cfg["categories"]
}

# Le CRM est polymorphe : People n..1 {Collectivité, Cabinet, Éditeur ADS, Company}.
# La plupart des contacts sont rattachés à un objet CUSTOM (cabinets surtout), pas à
# Company. On route donc le segment via la relation, par ordre de PRIORITÉ ci-dessous
# (1er lien non nul gagne) ; `companyId` retombe sur le mapping par `categorie`.
# Mettre INCLUDE_EDITEURS_ADS=False pour exclure les éditeurs ADS (concurrents).
INCLUDE_EDITEURS_ADS = True
RELATION_ROUTING = [
    ("collectiviteId", "collectivites", "COLLECTIVITES"),
    ("cabinetId", "cabinets", "PROS"),
    ("editeurAdsId", "editeurAds", "ECOSYSTEME" if INCLUDE_EDITEURS_ADS else None),
    # companyId est traité à part (via categorie) — voir gather().
]

BREVO = "https://api.brevo.com/v3"
NEWSLETTERS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "newsletters"
)


# ---------------------------------------------------------------------------
# Client Brevo minimal (stdlib), throttle léger (limite ~10 req/s côté Brevo).
# ---------------------------------------------------------------------------
class Brevo:
    def __init__(self, key: str | None = None):
        self.key = key or os.environ["BREVO_API_KEY"]

    def _req(self, method: str, path: str, body: dict | None = None, params: dict | None = None):
        url = BREVO + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(6):
            req = urllib.request.Request(url, data=data, method=method, headers={
                "api-key": self.key, "Content-Type": "application/json",
                "Accept": "application/json", "User-Agent": "kutsh-crm/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    raw = r.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 5:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                # 400 « Contact already exists » n'est pas une erreur pour un upsert.
                payload = e.read().decode()
                raise BrevoError(f"{method} {path} -> HTTP {e.code}: {payload[:300]}")
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < 5:
                    time.sleep(3)
                    continue
                raise BrevoError(f"{method} {path} -> réseau: {e}")
        raise BrevoError(f"{method} {path} -> abandon")

    # --- dossiers / listes ---
    def ensure_folder(self, name: str) -> int:
        d = self._req("GET", "/contacts/folders", params={"limit": 50, "offset": 0})
        for f in d.get("folders", []) or []:
            if f["name"] == name:
                return f["id"]
        return self._req("POST", "/contacts/folders", {"name": name})["id"]

    def ensure_list(self, name: str, folder_id: int) -> int:
        offset = 0
        while True:
            d = self._req("GET", "/contacts/lists", params={"limit": 50, "offset": offset})
            lists = d.get("lists", []) or []
            for lst in lists:
                if lst["name"] == name:
                    return lst["id"]
            if len(lists) < 50:
                break
            offset += 50
        return self._req("POST", "/contacts/lists", {"name": name, "folderId": folder_id})["id"]

    def upsert_contact(self, email: str, attributes: dict, list_ids: list[int]):
        self._req("POST", "/contacts", {
            "email": email, "attributes": attributes,
            "listIds": list_ids, "updateEnabled": True,
        })

    def import_contacts(self, list_id: int, contacts: list[dict], chunk: int = 400) -> list:
        """Import groupé (asynchrone côté Brevo) : 1 appel /contacts/import par
        paquet, au lieu d'un POST par contact. contacts = [{email, attributes}]."""
        pids = []
        for i in range(0, len(contacts), chunk):
            batch = contacts[i:i + chunk]
            r = self._req("POST", "/contacts/import", {
                "listIds": [list_id],
                "updateExistingContacts": True,
                "emptyContactsAttributes": False,
                "jsonBody": [{"email": ct["email"], "attributes": ct["attributes"]}
                             for ct in batch],
            })
            pids.append(r.get("processId"))
        return pids

    def list_contacts(self, list_id: int):
        """Itère tous les contacts d'une liste (pagination Brevo, 500/page)."""
        offset = 0
        while True:
            d = self._req("GET", f"/contacts/lists/{list_id}/contacts",
                          params={"limit": 500, "offset": offset})
            contacts = d.get("contacts", []) or []
            yield from contacts
            if len(contacts) < 500:
                return
            offset += 500

    def senders(self) -> list[dict]:
        return self._req("GET", "/senders").get("senders", []) or []

    def campaigns(self) -> list[dict]:
        out, offset = [], 0
        while True:
            d = self._req("GET", "/emailCampaigns", params={"type": "classic", "limit": 100, "offset": offset})
            camp = d.get("campaigns", []) or []
            out.extend(camp)
            if len(camp) < 100:
                return out
            offset += 100

    def create_campaign(self, name, subject, sender, html, list_ids) -> int:
        return self._req("POST", "/emailCampaigns", {
            "name": name, "subject": subject, "sender": sender,
            "htmlContent": html, "recipients": {"listIds": list_ids},
            "inlineImageActivation": False,
        })["id"]

    def update_campaign(self, cid, subject, sender, html, list_ids):
        self._req("PUT", f"/emailCampaigns/{cid}", {
            "subject": subject, "sender": sender,
            "htmlContent": html, "recipients": {"listIds": list_ids},
        })


class BrevoError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Collecte Twenty : contacts par segment.
# ---------------------------------------------------------------------------
def _email(person: dict) -> str | None:
    e = (person.get("emails") or {}).get("primaryEmail")
    return e.strip().lower() if e and e.strip() else None


def _name_map(c: TwentyClient, plural: str) -> dict:
    return {r["id"]: (r.get("name") or "") for r in c.list_all(plural, page_size=60, depth=0)}


def gather(c: TwentyClient, with_names: bool = True):
    """Retourne (buckets, stats, by_source).

    buckets[segment] = [ {email, first, last, company, id} ].
    Routage polymorphe : on résout le segment via la 1re relation non nulle
    (RELATION_ROUTING), puis via companyId -> categorie en dernier recours.

    with_names=False (dry-run) : saute le téléchargement des noms d'organisations
    custom (le segment se déduit de la seule présence de la relation) → bien plus
    rapide. with_names=True (import) : récupère les noms pour l'attribut SOCIETE.
    """
    companies = {co["id"]: (co.get("categorie"), co.get("name"))
                 for co in c.list_all("companies", page_size=60, depth=0)}
    names = {plural: (_name_map(c, plural) if with_names else {})
             for _, plural, _ in RELATION_ROUTING}

    buckets = {seg: [] for seg in SEGMENTS}
    stats = Counter()
    by_source = Counter()
    seen = set()

    for p in c.list_all("people", page_size=60, depth=0):
        stats["total_people"] += 1
        email = _email(p)
        if not email:
            stats["no_email"] += 1
            continue
        if p.get("newsletterOptOut") is True:
            stats["opted_out"] += 1
            continue

        seg = None
        company = ""
        source = None
        # 0) override manuel explicite (newsletterSegment posé sur la Person) —
        #    prime sur toute déduction (cas particuliers, partenaires, exceptions).
        override = p.get("newsletterSegment")
        if override in SEGMENTS:
            seg = override
            source = "override"
        # 1) relations custom, par priorité
        for id_key, plural, target_seg in (RELATION_ROUTING if seg is None else []):
            if p.get(id_key):
                if target_seg is None:      # relation volontairement exclue
                    source = "exclu:" + plural
                    break
                seg = target_seg
                company = names[plural].get(p[id_key], "")
                source = plural
                break
        # 2) sinon, Company standard via categorie
        if seg is None and source is None and p.get("companyId"):
            cat, coname = companies.get(p["companyId"], (None, None))
            seg = CATEGORIE_TO_SEGMENT.get(cat)
            company = coname or ""
            source = "companies" if seg else "company_hors_perimetre"

        if seg is None:
            if source and source.startswith("exclu:"):
                stats["exclu"] += 1
            elif source == "company_hors_perimetre":
                stats["unmapped_categorie"] += 1
            else:
                stats["no_org"] += 1
            continue
        if email in seen:      # un même email ne part qu'une fois
            continue
        seen.add(email)
        name = p.get("name") or {}
        buckets[seg].append({
            "email": email, "id": p["id"],
            "first": (name.get("firstName") or "").strip(),
            "last": (name.get("lastName") or "").strip(),
            "company": company,
        })
        stats["kept"] += 1
        by_source[source] += 1
    return buckets, stats, by_source


def print_plan(buckets, stats, by_source):
    print("\n=== DRY-RUN — répartition des contacts (aucune écriture) ===")
    for seg, cfg in SEGMENTS.items():
        print(f"  {cfg['list']:<38} {len(buckets[seg]):>5} contacts")
    print("  " + "-" * 50)
    print(f"  {'À charger (total)':<38} {stats['kept']:>5}")
    print("\n  Origine (objet Twenty) :")
    labels = {"cabinets": "Cabinet", "collectivites": "Collectivité",
              "editeurAds": "Éditeur ADS", "companies": "Company (catégorie)",
              "override": "Override manuel"}
    for src, n in by_source.most_common():
        print(f"    {labels.get(src, src):<24} {n}")
    print("\n  Diagnostic (écartés) :")
    print(f"    People parcourus ............ {stats['total_people']}")
    print(f"    Sans email .................. {stats['no_email']}")
    print(f"    Déjà désinscrits ............ {stats['opted_out']}")
    print(f"    Sans aucune organisation .... {stats['no_org']}")
    print(f"    Company hors périmètre ...... {stats['unmapped_categorie']}")
    print(f"    Relation exclue (éditeurs) .. {stats['exclu']}")
    print()


# ---------------------------------------------------------------------------
# Actions.
# ---------------------------------------------------------------------------
def ensure_lists(bv: Brevo) -> dict:
    folder = bv.ensure_folder(os.environ.get("BREVO_FOLDER", "Kutsh CRM"))
    ids = {}
    for seg, cfg in SEGMENTS.items():
        ids[seg] = bv.ensure_list(cfg["list"], folder)
        print(f"  liste « {cfg['list']} » -> id {ids[seg]}")
    return ids


def do_sync(c: TwentyClient, bv: Brevo, limit: int | None):
    list_ids = ensure_lists(bv)
    # with_names=False : on saute la récupération des noms d'organisations custom
    # (inutile à l'envoi) — le gather reste rapide même avec des centaines de contacts.
    buckets, stats, by_source = gather(c, with_names=False)
    print_plan(buckets, stats, by_source)
    total = 0
    for seg, contacts in buckets.items():
        subset = contacts[:limit] if limit else contacts
        payload = [{"email": ct["email"],
                    "attributes": {"PRENOM": ct["first"], "NOM": ct["last"],
                                   "SOURCE": "twenty", "SEGMENT": seg}}
                   for ct in subset]
        pids = bv.import_contacts(list_ids[seg], payload)
        total += len(subset)
        print(f"  {seg}: {len(subset)} contacts -> import Brevo (processId {pids})")
    print(f"OK sync — {total} contacts envoyés en import groupé (traitement async côté Brevo).")


def do_reconcile(c: TwentyClient, bv: Brevo):
    """Brevo -> Twenty : marque newsletterOptOut sur les désinscrits/blacklistés."""
    list_ids = ensure_lists(bv)
    marked = 0
    stamp = _now_iso()
    for seg, lid in list_ids.items():
        for contact in bv.list_contacts(lid):
            if not contact.get("emailBlacklisted"):
                continue
            email = (contact.get("email") or "").lower()
            person = c.find_one("people", "emails.primaryEmail", email)
            if not person:
                continue
            if person.get("newsletterOptOut") is True:
                continue
            c.update("people", person["id"],
                     {"newsletterOptOut": True, "newsletterOptOutAt": stamp})
            marked += 1
            print(f"    opt-out -> Twenty : {email}")
    print(f"OK reconcile — {marked} désinscription(s) rapatriée(s) dans Twenty.")


def _pick_sender(bv: Brevo) -> dict:
    want = os.environ.get("BREVO_SENDER_EMAIL")
    senders = bv.senders()
    if not senders:
        raise SystemExit("Aucun expéditeur vérifié dans Brevo. Créez-en un puis relancez.")
    if want:
        for s in senders:
            if s.get("email", "").lower() == want.lower():
                return {"name": s.get("name", "Kutsh"), "email": s["email"]}
        raise SystemExit(f"Expéditeur {want} introuvable/vérifié dans Brevo. Dispo : "
                         + ", ".join(s.get("email", "?") for s in senders))
    s = senders[0]
    return {"name": os.environ.get("BREVO_SENDER_NAME", s.get("name", "Kutsh")), "email": s["email"]}


def do_drafts(bv: Brevo):
    list_ids = ensure_lists(bv)
    sender = _pick_sender(bv)
    print(f"  expéditeur : {sender['name']} <{sender['email']}>")
    existing = {ca["name"]: ca["id"] for ca in bv.campaigns()}
    for seg, cfg in SEGMENTS.items():
        path = os.path.join(NEWSLETTERS_DIR, cfg["html"])
        with open(path, encoding="utf-8") as fh:
            html = fh.read()
        name = f"[Brouillon] {cfg['list']}"
        if name in existing:
            bv.update_campaign(existing[name], cfg["subject"], sender, html, [list_ids[seg]])
            print(f"  brouillon mis à jour : {name} (id {existing[name]})")
        else:
            cid = bv.create_campaign(name, cfg["subject"], sender, html, [list_ids[seg]])
            print(f"  brouillon créé : {name} (id {cid})")
    print("OK drafts — 3 brouillons de campagne prêts (non planifiés) dans Brevo.")


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def main():
    ap = argparse.ArgumentParser(description="Sync Twenty -> Brevo (listes + brouillons).")
    ap.add_argument("cmd", choices=["plan", "ensure", "sync", "reconcile", "drafts", "all"])
    ap.add_argument("--limit", type=int, default=None, help="borne le nb de contacts/segment (test)")
    a = ap.parse_args()

    c = TwentyClient()
    if a.cmd == "plan":
        buckets, stats, by_source = gather(c, with_names=False)
        print_plan(buckets, stats, by_source)
        return

    bv = Brevo()
    if a.cmd == "ensure":
        # champs Twenty + listes Brevo
        import subprocess
        subprocess.run([sys.executable,
                        os.path.join(os.path.dirname(__file__), "configure_newsletter_fields.py")],
                       check=True)
        ensure_lists(bv)
    elif a.cmd == "sync":
        do_sync(c, bv, a.limit)
    elif a.cmd == "reconcile":
        do_reconcile(c, bv)
    elif a.cmd == "drafts":
        do_drafts(bv)
    elif a.cmd == "all":
        do_reconcile(c, bv)   # d'abord retirer les désinscrits…
        do_sync(c, bv, a.limit)  # …puis (ré)alimenter les listes


if __name__ == "__main__":
    main()
