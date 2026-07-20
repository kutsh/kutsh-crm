#!/usr/bin/env python3
"""crm_export.py — snapshot JSON portable de tout le CRM Twenty (issue snxn).

Anti lock-in : dump CRM-agnostique de tous les objets de données (standard +
custom) en JSONL, paginé via l'API REST. Snapshot daté + manifeste, archivé en
.tar.gz, avec rétention. Complémentaire du dump Postgres quotidien de Coolify
(qui, lui, est lié à Twenty).

Un snapshot dégradé est archivé quand même (on ne jette pas de la donnée), mais
le script sort en **code retour non nul** et la rétention est suspendue — pour
qu'un backup vide ne soit ni silencieux ni capable d'évincer les bons.

Incident 2026-07-20 : pendant trois semaines, les snapshots n'ont contenu qu'un
seul objet sur treize — les douze autres échouaient en HTTP 429. Le manifeste
enregistrait déjà ces erreurs, mais personne ne les relisait : le script
imprimait « OK snapshot » et sortait en 0. Trois semaines de backups
inexploitables, sans la moindre alerte.

**Module packagé** (au même titre que `crm_client`), pour être appelé depuis un
orchestrateur sans copier de fichier sur une machine :

    from crm_export import run
    archive, healthy = run(out_dir, keep=12, stamp="2026-07-20")

`scripts/export_snapshot.py` reste une façade CLI équivalente.

Usage : TWENTY_API_KEY=… python -m crm_export [--out DIR] [--keep N]
Env : TWENTY_API_KEY (+ TWENTY_BASE_URL), SNAPSHOT_DIR (déf. ./snapshots), SNAPSHOT_KEEP (déf. 12).
Sortie : 0 = snapshot sain, 1 = snapshot dégradé (archivé, mais à investiguer).
"""
from __future__ import annotations
import os, sys, json, argparse, tarfile, shutil
from crm_client import TwentyClient  # type: ignore[import-not-found]

# Une baisse de plus de moitié sur un objet un peu peuplé est signalée sans être
# fatale : une purge légitime (purge_auto_leads.py) en produit, un incident
# aussi. Seul le passage à zéro est traité comme une erreur certaine.
WARN_DROP_RATIO = 0.5
WARN_MIN_PREVIOUS = 100


def objects_to_export(c: TwentyClient) -> list[dict]:
    objs = c._req("GET", "/rest/metadata/objects", params={"limit": 200})["data"]["objects"]
    out = []
    for o in objs:
        if o.get("isSystem") or o.get("isRemote") or not o.get("isActive", True):
            continue
        out.append({"singular": o["nameSingular"], "plural": o["namePlural"], "custom": o.get("isCustom")})
    return sorted(out, key=lambda x: x["plural"])


def previous_manifest(base: str) -> dict | None:
    """Manifeste du snapshot archivé le plus récent, ou None s'il n'y en a pas.

    Sert de référence pour détecter un objet qui se vide. Lu depuis l'archive
    elle-même : pas de fichier d'état parallèle à maintenir.
    """
    try:
        arch = sorted(
            f for f in os.listdir(base)
            if f.startswith("twenty-snapshot-") and f.endswith(".tar.gz")
        )
    except OSError:
        return None
    for name in reversed(arch):  # du plus récent au plus ancien
        try:
            with tarfile.open(os.path.join(base, name), "r:gz") as tar:
                for m in tar.getmembers():
                    if os.path.basename(m.name) == "manifest.json":
                        fh = tar.extractfile(m)
                        if fh is not None:
                            return json.load(fh)
        except Exception:
            continue  # archive corrompue ou illisible : on tente la précédente
    return None


def check_health(manifest: dict, previous: dict | None) -> tuple[list[str], list[str]]:
    """(erreurs, avertissements) — une erreur rend le snapshot non fiable."""
    errors: list[str] = []
    warnings: list[str] = []
    objects: dict = manifest["objects"]

    for plural, entry in sorted(objects.items()):
        if entry.get("error"):
            errors.append(f"{plural} : lecture en échec ({entry['error']})")

    total = sum(entry.get("count", 0) for entry in objects.values())
    if total == 0:
        errors.append("snapshot totalement vide (0 enregistrement, tous objets confondus)")

    if previous:
        before_all: dict = previous.get("objects", {})
        for plural, entry in sorted(objects.items()):
            before = before_all.get(plural, {}).get("count", 0)
            now = entry.get("count", 0)
            if before > 0 and now == 0:
                errors.append(
                    f"{plural} : {before} enregistrement(s) dans le snapshot "
                    f"{previous.get('snapshot', '?')}, 0 maintenant"
                )
            elif before >= WARN_MIN_PREVIOUS and now < before * WARN_DROP_RATIO:
                warnings.append(
                    f"{plural} : {before} -> {now} "
                    f"(-{round(100 * (before - now) / before)} %) depuis "
                    f"{previous.get('snapshot', '?')}"
                )
    return errors, warnings


def run(out_dir: str, keep: int, stamp: str) -> tuple[str, bool]:
    """Écrit le snapshot. Retourne (chemin de l'archive, snapshot sain)."""
    c = TwentyClient()
    base = os.path.abspath(out_dir)
    os.makedirs(base, exist_ok=True)
    previous = previous_manifest(base)  # avant d'écrire la nouvelle archive
    work = os.path.join(base, stamp)
    os.makedirs(work, exist_ok=True)
    manifest: dict = {"snapshot": stamp, "base_url": c.base, "objects": {}}
    for obj in objects_to_export(c):
        plural = obj["plural"]
        n = 0
        entry: dict = {"custom": obj["custom"]}
        try:
            with open(os.path.join(work, f"{plural}.jsonl"), "w") as fh:
                for rec in c.list_all(plural, page_size=60, depth=0):
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    n += 1
        except Exception as e:  # un objet illisible ne casse pas le snapshot...
            entry["error"] = str(e)[:200]
        # ...mais son compte est enregistré même en cas d'échec : une lecture
        # interrompue en cours de pagination laisse un .jsonl tronqué, et c'est
        # `count` qui permet de le voir.
        entry["count"] = n
        manifest["objects"][plural] = entry
        print(f"  {plural}: {n}" + ("  [ECHEC]" if entry.get("error") else ""))
    with open(os.path.join(work, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    archive = os.path.join(base, f"twenty-snapshot-{stamp}.tar.gz")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(work, arcname=stamp)
    shutil.rmtree(work)

    errors, warnings = check_health(manifest, previous)
    total = sum(entry.get("count", 0) for entry in manifest["objects"].values())

    for w in warnings:
        print(f"ATTENTION {w}", file=sys.stderr)

    if errors:
        # Rétention suspendue : un snapshot dégradé ne doit jamais évincer les
        # bons. C'est ce qui aurait sauvé les archives pendant les 3 semaines de
        # l'incident 2026-07-20 si la panne avait duré plus longtemps.
        for e in errors:
            print(f"ERREUR {e}", file=sys.stderr)
        print(
            f"ECHEC snapshot {stamp}: {total} enregistrements, "
            f"{len(manifest['objects'])} objets, {len(errors)} probleme(s) -> {archive}",
            file=sys.stderr,
        )
        print("Archive conservee, retention suspendue (aucune ancienne archive supprimee).", file=sys.stderr)
        return archive, False

    # rétention : ne garder que les `keep` archives les plus récentes
    arch = sorted(f for f in os.listdir(base) if f.startswith("twenty-snapshot-") and f.endswith(".tar.gz"))
    for old in arch[:-keep] if keep > 0 else []:
        os.remove(os.path.join(base, old))
    print(f"OK snapshot {stamp}: {total} enregistrements, {len(manifest['objects'])} objets -> {archive}")
    return archive, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.environ.get("SNAPSHOT_DIR", "./snapshots"))
    ap.add_argument("--keep", type=int, default=int(os.environ.get("SNAPSHOT_KEEP", "12")))
    ap.add_argument("--stamp", default=None, help="horodatage (déf. date du jour, fourni par le cron)")
    a = ap.parse_args()
    stamp = a.stamp or __import__("datetime").date.today().isoformat()
    _, healthy = run(a.out, a.keep, stamp)
    sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()
