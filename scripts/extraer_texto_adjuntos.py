#!/usr/bin/env python3
"""Extrae el texto de los adjuntos ya descargados, para que la busqueda los alcance.

Usa la capa de texto del PDF cuando existe y OCR (framework Vision de Apple)
cuando no. **El OCR corre entero en esta maquina**: ningun documento clinico
sale a un servicio externo.

Uso:
  python3 scripts/extraer_texto_adjuntos.py          # solo lo que falta
  python3 scripts/extraer_texto_adjuntos.py --todo   # rehace todo
"""
import argparse
import collections
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp_drapp.adjuntos import ADJUNTOS, TEXTOS, extraer, ruta_texto  # noqa: E402

CORPUS = ROOT / "data" / "hce"


def inventario() -> list[tuple[str, str, pathlib.Path]]:
    """(consumer_id, record_id, archivo) de cada adjunto descargado."""
    out = []
    for f in sorted(CORPUS.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        cid = d["patient"].get("consumerId") or f.stem
        carpeta = ADJUNTOS / cid
        if not carpeta.is_dir():
            continue
        for a in d["sections"].get("archivos") or []:
            if a.get("deleted"):
                continue
            rid = (a.get("id") or "").split("/")[-1]
            if not rid:
                continue
            hallados = list(carpeta.glob(f"{rid}_*"))
            if hallados:
                out.append((cid, rid, hallados[0]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--todo", action="store_true",
                    help="rehace tambien los que ya tienen texto")
    args = ap.parse_args()

    items = inventario()
    if not items:
        sys.exit("No hay adjuntos descargados. Corre antes scripts/bajar_adjuntos.py")

    origenes = collections.Counter()
    t0 = time.time()
    print(f"adjuntos: {len(items)}", flush=True)
    for n, (cid, rid, archivo) in enumerate(items, 1):
        destino = ruta_texto(cid, rid)
        if destino.exists() and not args.todo:
            origenes["ya_estaba"] += 1
            continue
        texto, origen = extraer(archivo)
        origenes[origen] += 1
        if texto:
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(texto, encoding="utf-8")
        if n % 25 == 0:
            print(f"  {n}/{len(items)}  ({time.time()-t0:.0f}s)", flush=True)

    print(f"\nLISTO en {time.time()-t0:.0f}s")
    for k, v in origenes.most_common():
        print(f"  {k:12} {v}")
    con = sum(1 for p in TEXTOS.rglob("*.txt"))
    chars = sum(len(p.read_text(encoding='utf-8', errors='ignore'))
                for p in TEXTOS.rglob("*.txt"))
    print(f"\n  archivos con texto: {con}   ({chars/1000:.0f} mil caracteres)")


if __name__ == "__main__":
    main()
