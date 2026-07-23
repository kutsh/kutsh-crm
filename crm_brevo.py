#!/usr/bin/env python3
"""crm_brevo.py — synchronise les contacts Twenty vers des listes Brevo,
crée les brouillons de campagne, et rapatrie les désinscriptions Brevo → Twenty.

Segmentation : la liste Brevo d'un contact est déduite de la `categorie` de son
organisation (Company) dans Twenty. Mapping dans CATEGORIE_TO_SEGMENT ci-dessous.

Sous-commandes :
  plan        Dry-run : compte les contacts par segment, n'écrit rien (Twenty ni Brevo).
  ensure      Idempotent : crée les attributs de contact + le dossier + les listes côté Brevo.
  sync        Pousse les contacts dans les listes Brevo (upsert, saute les désinscrits).
  reconcile   Rapatrie les désinscrits/blacklistés Brevo dans Twenty (newsletterOptOut).
  drafts      Crée les 3 brouillons de campagne dans Brevo depuis newsletters/*.html.
  all         reconcile -> sync (retirer les désinscrits AVANT de réalimenter).

**Module packagé** (comme `crm_client` et `crm_export`), pour être appelé depuis
un orchestrateur sans copier de fichier sur une machine :

    from crm_brevo import run
    summary = run("all")          # -> {"reconcile": {...}, "sync": {...}}

`scripts/sync_twenty_brevo.py` reste une façade CLI équivalente. Une différence
assumée entre les deux : la façade fait précéder `ensure` de la création des
champs newsletter côté Twenty (`scripts/configure_newsletter_fields.py`), qui
est une migration de schéma jouée une fois et n'a rien à faire dans un job
récurrent. Le module, lui, ne touche qu'à Brevo.

Env requis : TWENTY_API_KEY, BREVO_API_KEY.
Env optionnels : TWENTY_BASE_URL (déf. https://twenty.kutsh.fr),
  BREVO_SENDER_EMAIL / BREVO_SENDER_NAME (sinon 1er expéditeur Brevo vérifié),
  BREVO_FOLDER (déf. "Kutsh CRM"), LAZONE_URL (déf. https://lazone.kutsh.fr),
  NEWSLETTERS_DIR (déf. `newsletters/` à côté du module — n'existe que dans le
  dépôt, pas dans le wheel : seul `drafts` en a besoin).

Exemples :
  TWENTY_API_KEY=… BREVO_API_KEY=… python -m crm_brevo plan
  … python -m crm_brevo all            # l'enchaînement récurrent
  … python scripts/sync_twenty_brevo.py drafts   # (re)crée les brouillons
"""
from __future__ import annotations
import os, sys, json, time, argparse, urllib.request, urllib.parse, urllib.error
from collections import Counter

from crm_client import TwentyClient  # type: ignore[import-not-found]

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
            # Adoptées le 2026-07-23 depuis l'UI (cf. `--adopt`) : le découpage
            # fin des cabinets, né du terrain, remplace en pratique `CABINET`.
            "CABINET_DESSINATEUR_PROJETEUR", "CABINET_ARCHITECTURE",
            "BUREAU_ETUDES_TECHNIQUES", "MARCHAND_DE_BIENS",
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
# Catégories volontairement NON ciblées (restent hors newsletter), en plus de `null`.
# Les déclarer ici plutôt que de les omettre : une catégorie absente des deux listes
# est un oubli, pas un choix, et le test de couverture le dit (cf. tests).
#   AUTRE      — fourre-tout, pas un public identifié (cf. ADR 2026-07-07).
#   FINANCEUR  — investisseurs/financeurs de Kutsh : relation gérée en direct,
#                une newsletter produit adressée à un fonds serait à contre-emploi.
CATEGORIES_HORS_NEWSLETTER = {"AUTRE", "FINANCEUR"}
CATEGORIE_TO_SEGMENT = {
    cat: seg for seg, cfg in SEGMENTS.items() for cat in cfg["categories"]
}


def known_categories() -> set[str]:
    """Catégories dont le code connaît le comportement : routées ou exclues à dessein.

    C'est la définition, côté paquet, de « déclaré ». `configure_company_categorie`
    porte la liste canonique du SELECT ; ce module porte le comportement newsletter.
    Une catégorie de Twenty absente de cet ensemble n'a **aucun** comportement — ses
    contacts ne reçoivent aucune lettre, sans que rien ne le dise.
    """
    return set(CATEGORIE_TO_SEGMENT) | CATEGORIES_HORS_NEWSLETTER


def audit_categories(c: "TwentyClient | None" = None) -> list[tuple[str, int]]:
    """Catégories portées par des Companies mais inconnues du code, par effectif.

    Lecture seule — aucune écriture Twenty ni Brevo, pas de clé Brevo requise.
    Point d'entrée **packagé** de l'audit de dérive : le garde-fou opérationnel
    (cron Prefect kutsh-data) en dépend, là où `configure_company_categorie
    --check` est l'outil local du développeur. Les deux disent la même chose ;
    celui-ci vit dans le wheel, donc importable par le worker.

    On remonte une catégorie dès qu'**une seule** Company la porte, sans attendre
    qu'un contact y soit rattaché : au moment où un contact arrivera, la lettre
    lui échappera déjà. Trié par nombre de fiches décroissant — la volumétrie est
    ce qui distingue « à déclarer d'urgence » d'une scorie.
    """
    from crm_client import TwentyClient  # local : garde le module importable sans réseau

    c = c or TwentyClient()
    known = known_categories()
    compte: Counter = Counter(
        co.get("categorie") for co in c.list_all("companies", page_size=60, depth=0)
    )
    return sorted(
        ((cat, n) for cat, n in compte.items() if cat and cat not in known),
        key=lambda kv: (-kv[1], kv[0]),
    )

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
# Attributs de contact posés par `do_sync`. Ils doivent exister dans le schéma
# Brevo AVANT l'import, sans quoi ils sont silencieusement jetés (cf.
# `ensure_attributes`). `PRENOM`/`NOM` y figurent aussi : ils existent déjà sur
# le compte, mais la liste n'a d'intérêt que si elle est exhaustive — sur un
# compte neuf, c'est elle qui décrit ce dont le sync a besoin.
CONTACT_ATTRIBUTES = {"PRENOM": "text", "NOM": "text", "SOURCE": "text", "SEGMENT": "text"}
# Le corps HTML des campagnes vit dans le dépôt, pas dans le wheel : `drafts` est
# une commande d'atelier, pas un job récurrent. Surchargeable pour le cas où le
# module tournerait ailleurs que depuis un checkout.
NEWSLETTERS_DIR = os.environ.get(
    "NEWSLETTERS_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "newsletters"),
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

    # --- attributs de contact ---
    def attributes(self) -> list[dict]:
        return self._req("GET", "/contacts/attributes").get("attributes", []) or []

    def create_attribute(self, name: str, type_: str = "text") -> None:
        self._req("POST", f"/contacts/attributes/normal/{name}", {"type": type_})

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
                # Trois raisons très différentes de ne pas envoyer, longtemps
                # comptées ensemble : la catégorie manque (saisie à faire), elle
                # est hors périmètre par décision, ou elle existe dans Twenty
                # sans être déclarée dans le code — une catégorie créée depuis
                # l'UI. Seul le 3e cas est une dérive, et c'est le seul qui
                # prive un public de lettre sans que personne l'ait décidé.
                if not cat:
                    stats["categorie_absente"] += 1
                elif cat in CATEGORIES_HORS_NEWSLETTER:
                    stats["hors_perimetre_assume"] += 1
                else:
                    stats[f"categorie_inconnue:{cat}"] += 1

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
    print(f"      dont sans catégorie ....... {stats['categorie_absente']}")
    print(f"      dont hors périmètre décidé  {stats['hors_perimetre_assume']}")
    print(f"    Relation exclue (éditeurs) .. {stats['exclu']}")
    for cat, n in categories_inconnues(stats):
        print(f"    ⚠️  catégorie non déclarée « {cat} » : {n} contact(s) sans lettre")
    print()


def categories_inconnues(stats) -> list[tuple[str, int]]:
    """Catégories vues dans Twenty mais absentes du code, par nombre de contacts.

    Le test de couverture (`tests/test_crm_brevo.py`) compare la liste déclarée
    au mapping : il ne peut rien voir d'une catégorie créée dans l'UI de Twenty.
    C'est donc à l'exécution, seul endroit où le CRM réel est visible, que la
    dérive doit se dire — et en nommant la catégorie, pas en gonflant un total.
    """
    prefixe = "categorie_inconnue:"
    return sorted(
        ((k[len(prefixe):], n) for k, n in stats.items() if k.startswith(prefixe)),
        key=lambda kv: (-kv[1], kv[0]),
    )


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


def ensure_attributes(bv: Brevo) -> list[str]:
    """Déclare dans Brevo les attributs posés par le sync. Retourne ceux créés.

    Brevo n'accepte QUE les attributs déclarés dans le schéma du compte. Un
    attribut inconnu est **ignoré à l'import sans la moindre erreur** : l'API
    rend un `processId`, le processus passe `completed`, et la valeur disparaît.

    C'est arrivé au premier run réel (2026-07-21) : les 376 contacts sont partis
    avec `SOURCE` et `SEGMENT` vides, ni le log du flow ni l'état du run ne
    permettant de le voir. Seule une relecture de l'API Brevo l'a montré.
    """
    existants = {a.get("name") for a in bv.attributes()}
    crees = [nom for nom in CONTACT_ATTRIBUTES if nom not in existants]
    for nom in crees:
        bv.create_attribute(nom, CONTACT_ATTRIBUTES[nom])
        print(f"  attribut de contact « {nom} » créé")

    # Relecture systématique : on ne se fie pas au code retour du POST, puisque
    # le mode d'échec qu'on ferme est précisément « Brevo accepte sans stocker ».
    manquants = sorted(set(CONTACT_ATTRIBUTES) - {a.get("name") for a in bv.attributes()})
    if manquants:
        raise BrevoError(
            f"attribut(s) de contact absent(s) du schéma Brevo après création : {manquants}. "
            "Un import les jetterait en silence — on s'arrête avant d'écrire."
        )
    return crees


def contact_attributes(ct: dict, seg: str) -> dict:
    """Attributs Brevo d'un contact. Ses clés DOIVENT être dans CONTACT_ATTRIBUTES.

    Isolée du corps de `do_sync` pour que le test puisse vérifier ce lien sur le
    vrai payload : ajouter un attribut ici sans le déclarer là-bas reproduirait
    l'incident du 2026-07-21 à l'identique, et tout aussi silencieusement.
    """
    return {"PRENOM": ct["first"], "NOM": ct["last"], "SOURCE": "twenty", "SEGMENT": seg}


def do_sync(c: TwentyClient, bv: Brevo, limit: int | None) -> dict:
    # AVANT l'import, pas après : un attribut non déclaré est jeté en silence,
    # et l'import est la seule opération qui en pose.
    ensure_attributes(bv)
    list_ids = ensure_lists(bv)
    # with_names=False : on saute la récupération des noms d'organisations custom
    # (inutile à l'envoi) — le gather reste rapide même avec des centaines de contacts.
    buckets, stats, by_source = gather(c, with_names=False)
    print_plan(buckets, stats, by_source)
    total = 0
    par_segment: dict[str, int] = {}
    for seg, contacts in buckets.items():
        subset = contacts[:limit] if limit else contacts
        payload = [{"email": ct["email"], "attributes": contact_attributes(ct, seg)}
                   for ct in subset]
        pids = bv.import_contacts(list_ids[seg], payload)
        total += len(subset)
        par_segment[seg] = len(subset)
        print(f"  {seg}: {len(subset)} contacts -> import Brevo (processId {pids})")
    print(f"OK sync — {total} contacts envoyés en import groupé (traitement async côté Brevo).")
    return {"total": total, "par_segment": par_segment, "diagnostic": dict(stats)}


def do_reconcile(c: TwentyClient, bv: Brevo) -> dict:
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
    return {"opt_out_rapatries": marked}


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


def do_drafts(bv: Brevo) -> dict:
    if not os.path.isdir(NEWSLETTERS_DIR):
        raise SystemExit(
            f"newsletters/ introuvable ({NEWSLETTERS_DIR}). Le corps HTML des campagnes "
            "vit dans le dépôt et n'est pas embarqué dans le wheel : lancer `drafts` "
            "depuis un checkout, ou pointer NEWSLETTERS_DIR dessus."
        )
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
    return {"brouillons": len(SEGMENTS)}


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


COMMANDS = ("plan", "ensure", "sync", "reconcile", "drafts", "all")


def run(cmd: str, limit: int | None = None) -> dict:
    """Exécute une sous-commande et retourne un résumé sérialisable.

    Point d'entrée des appelants programmatiques (orchestrateur Prefect) : un
    dict plutôt qu'un code retour, pour que le run porte ses chiffres dans ses
    logs — ce qui manquait au cron de kutsh-prod (kata `f154`).
    """
    if cmd not in COMMANDS:
        raise ValueError(f"commande inconnue: {cmd!r} (attendu {list(COMMANDS)})")

    c = TwentyClient()
    if cmd == "plan":
        buckets, stats, by_source = gather(c, with_names=False)
        print_plan(buckets, stats, by_source)
        return {
            "par_segment": {seg: len(rows) for seg, rows in buckets.items()},
            "total": stats["kept"],
            "diagnostic": dict(stats),
        }

    bv = Brevo()
    if cmd == "ensure":
        return {"attributs_crees": ensure_attributes(bv), "listes": ensure_lists(bv)}
    if cmd == "sync":
        return {"sync": do_sync(c, bv, limit)}
    if cmd == "reconcile":
        return {"reconcile": do_reconcile(c, bv)}
    if cmd == "drafts":
        return {"drafts": do_drafts(bv)}
    # all : d'abord retirer les désinscrits, ensuite seulement réalimenter — dans
    # l'autre ordre on repousse dans Brevo quelqu'un qui vient de s'y désinscrire.
    return {"reconcile": do_reconcile(c, bv), "sync": do_sync(c, bv, limit)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sync Twenty -> Brevo (listes + brouillons).")
    ap.add_argument("cmd", choices=list(COMMANDS))
    ap.add_argument("--limit", type=int, default=None, help="borne le nb de contacts/segment (test)")
    a = ap.parse_args(argv)
    run(a.cmd, a.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
