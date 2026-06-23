#!/usr/bin/env python3
"""export_snapshot.py — snapshot JSON portable de tout le CRM Twenty (issue snxn).

Anti lock-in : dump CRM-agnostique de tous les objets de données (standard +
custom) en JSONL, paginé via l'API REST. Snapshot daté + manifeste, archivé en
.tar.gz, avec rétention. Complémentaire du dump Postgres quotidien de Coolify
(qui, lui, est lié à Twenty).

Usage : TWENTY_API_KEY=… python scripts/export_snapshot.py [--out DIR] [--keep N]
Env : TWENTY_API_KEY (+ TWENTY_BASE_URL), SNAPSHOT_DIR (déf. ./snapshots), SNAPSHOT_KEEP (déf. 12).
"""
from __future__ import annotations
import os, sys, json, argparse, tarfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from crm_client import TwentyClient  # noqa: E402  # type: ignore[import-not-found]


def objects_to_export(c: TwentyClient) -> list[dict]:
    objs = c._req("GET", "/rest/metadata/objects", params={"limit": 200})["data"]["objects"]
    out = []
    for o in objs:
        if o.get("isSystem") or o.get("isRemote") or not o.get("isActive", True):
            continue
        out.append({"singular": o["nameSingular"], "plural": o["namePlural"], "custom": o.get("isCustom")})
    return sorted(out, key=lambda x: x["plural"])


def run(out_dir: str, keep: int, stamp: str) -> str:
    c = TwentyClient()
    base = os.path.abspath(out_dir)
    os.makedirs(base, exist_ok=True)
    work = os.path.join(base, stamp)
    os.makedirs(work, exist_ok=True)
    manifest = {"snapshot": stamp, "base_url": c.base, "objects": {}}
    for obj in objects_to_export(c):
        plural = obj["plural"]
        n = 0
        try:
            with open(os.path.join(work, f"{plural}.jsonl"), "w") as fh:
                for rec in c.list_all(plural, page_size=60, depth=0):
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    n += 1
            manifest["objects"][plural] = {"count": n, "custom": obj["custom"]}
        except Exception as e:  # un objet illisible ne casse pas le snapshot
            manifest["objects"][plural] = {"error": str(e)[:200], "custom": obj["custom"]}
        print(f"  {plural}: {n}")
    with open(os.path.join(work, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    archive = os.path.join(base, f"twenty-snapshot-{stamp}.tar.gz")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(work, arcname=stamp)
    shutil.rmtree(work)

    # rétention : ne garder que les `keep` archives les plus récentes
    arch = sorted(f for f in os.listdir(base) if f.startswith("twenty-snapshot-") and f.endswith(".tar.gz"))
    for old in arch[:-keep] if keep > 0 else []:
        os.remove(os.path.join(base, old))
    total = sum(v.get("count", 0) for v in manifest["objects"].values())
    print(f"OK snapshot {stamp}: {total} enregistrements, {len(manifest['objects'])} objets -> {archive}")
    return archive


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.environ.get("SNAPSHOT_DIR", "./snapshots"))
    ap.add_argument("--keep", type=int, default=int(os.environ.get("SNAPSHOT_KEEP", "12")))
    ap.add_argument("--stamp", default=None, help="horodatage (déf. date du jour, fourni par le cron)")
    a = ap.parse_args()
    stamp = a.stamp or __import__("datetime").date.today().isoformat()
    run(a.out, a.keep, stamp)


if __name__ == "__main__":
    main()
