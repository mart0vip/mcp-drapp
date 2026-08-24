#!/usr/bin/env python3
"""Descarga los adjuntos de la HCE a data/adjuntos/.

El corpus guarda la metadata de cada archivo (nombre, tipo, tamano y link al
CDN) pero no el binario. Este script baja los binarios, uno por paciente en
su carpeta, y es reanudable: saltea lo que ya esta con el tamano correcto.

Uso:
  python3 scripts/bajar_adjuntos.py               # todos
  python3 scripts/bajar_adjuntos.py --max-mb 20   # saltea los muy pesados
"""
import argparse
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "hce"
DESTINO = ROOT / "data" / "adjuntos"


def limpio(nombre: str) -> str:
    nombre = re.sub(r"[^\w\s.-]", "_", nombre or "", flags=re.UNICODE)
    return re.sub(r"\s+", "_", nombre).strip("._")[:80] or "archivo"


def inventario() -> list[dict]:
    """Adjuntos vigentes del corpus, con a que paciente pertenecen."""
    out = []
    for f in sorted(CORPUS.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        cid = d["patient"].get("consumerId") or f.stem
        for a in d["sections"].get("archivos") or []:
            if a.get("deleted") or not a.get("link"):
                continue
            ext = pathlib.Path(a["link"]).suffix or ""
            base = limpio(a.get("name") or "")
            if not base.lower().endswith(ext.lower()):
                base += ext
            out.append({"consumer_id": cid,
                        "record_id": (a.get("id") or "").split("/")[-1],
                        "link": a["link"], "size": a.get("size") or 0,
                        "content_type": a.get("contentType") or "",
                        "destino": DESTINO / cid / f"{(a.get('id') or '').split('/')[-1]}_{base}"})
    return out


def bajar(item: dict, reintentos: int = 3) -> str:
    ruta = item["destino"]
    if ruta.exists() and (not item["size"] or ruta.stat().st_size == item["size"]):
        return "ya_estaba"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ultimo = None
    for intento in range(1, reintentos + 1):
        try:
            req = urllib.request.Request(item["link"], headers={"Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=120) as r, \
                 ruta.open("wb") as fh:
                while chunk := r.read(262144):
                    fh.write(chunk)
            if item["size"] and ruta.stat().st_size != item["size"]:
                ultimo = f"tamano {ruta.stat().st_size} != {item['size']}"
                time.sleep(1.5 * intento)
                continue
            return "bajado"
        except urllib.error.HTTPError as e:
            return f"HTTP {e.code}"
        except Exception as e:
            ultimo = f"{type(e).__name__}"
            time.sleep(1.5 * intento)
    return f"fallo: {ultimo}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-mb", type=float, default=0,
                    help="saltea archivos mas grandes que esto (0 = sin limite)")
    ap.add_argument("--workers", type=int, default=5)
    args = ap.parse_args()

    todos = inventario()
    if not todos:
        sys.exit("No hay adjuntos en el corpus. Corre antes scripts/fetch_hce.py")

    salteados = []
    if args.max_mb:
        tope = args.max_mb * 1e6
        salteados = [i for i in todos if i["size"] > tope]
        todos = [i for i in todos if i["size"] <= tope]

    total_mb = sum(i["size"] for i in todos) / 1e6
    print(f"adjuntos: {len(todos)}   ~{total_mb:.0f} MB", flush=True)
    if salteados:
        print(f"  salteados por tamano: {len(salteados)}", flush=True)

    res = {"bajado": 0, "ya_estaba": 0}
    errores = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(bajar, i): i for i in todos}
        for n, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            if r in res:
                res[r] += 1
            else:
                errores.append((futs[fut]["destino"].name, r))
            if n % 25 == 0:
                print(f"  {n}/{len(todos)}", flush=True)

    print(f"\nLISTO  bajados={res['bajado']}  ya_estaban={res['ya_estaba']}  "
          f"errores={len(errores)}")
    for nombre, err in errores[:15]:
        print(f"  {err}  {nombre}")


if __name__ == "__main__":
    main()
