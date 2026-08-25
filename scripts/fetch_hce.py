#!/usr/bin/env python3
"""Descarga la historia clinica completa del equipo: un JSON por paciente.

Es el paso de instalacion inicial. Despues de esto, para mantener el corpus
al dia alcanza con la herramienta `refresh` del MCP.

El padron se pide a drapp, asi que NO hace falta exportar ningun CSV. Si por
algun motivo la API no responde, se usa data/patients.json si existe (lo
genera scripts/importar_csv.py a partir del export de Reportes -> Pacientes).

Requiere sesion iniciada:
    python3 -c "from mcp_drapp import auth; print(auth.login())"

Uso:
    python3 scripts/fetch_hce.py            # todo el padron
    python3 scripts/fetch_hce.py --limit 15 # una muestra, para probar
Reanudable: saltea los pacientes que ya tienen su JSON.
"""
import argparse
import json
import pathlib
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp_drapp.api import listar_consumers, secciones_de  # noqa: E402
from mcp_drapp.auth import NecesitaLogin  # noqa: E402

OUT = ROOT / "data" / "hce"
LISTA = ROOT / "data" / "patients.json"
_lock = threading.Lock()


def padron() -> list[dict]:
    """Padron desde drapp; si la red falla, la copia local."""
    try:
        gente = listar_consumers()
        LISTA.parent.mkdir(parents=True, exist_ok=True)
        LISTA.write_text(json.dumps(gente, ensure_ascii=False, indent=1),
                         encoding="utf-8")
        print(f"padron desde drapp: {len(gente)} pacientes", flush=True)
        return gente
    except NecesitaLogin:
        raise
    except Exception as e:
        if LISTA.exists():
            gente = json.loads(LISTA.read_text(encoding="utf-8"))
            print(f"AVISO: no se pudo pedir el padron ({type(e).__name__}); "
                  f"se usa la copia local de {len(gente)} pacientes", flush=True)
            return gente
        raise SystemExit(
            f"ERROR: no se pudo obtener el padron ({e}) y no hay copia local.\n"
            "Si el problema persiste, exporta el CSV desde Reportes -> Pacientes\n"
            "y converti con: python3 scripts/importar_csv.py <archivo.csv>")


def bajar(p: dict) -> str:
    cid = p["consumerId"]
    datos = secciones_de(cid)
    (OUT / f"{cid}.json").write_text(
        json.dumps({"patient": p, "sections": datos}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return cid


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0 = todos")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    try:
        gente = padron()
    except NecesitaLogin as e:
        raise SystemExit(f"ERROR: {e}")

    if args.limit:
        gente = gente[: args.limit]
    OUT.mkdir(parents=True, exist_ok=True)
    todo = [p for p in gente if not (OUT / f"{p['consumerId']}.json").exists()]
    print(f"total={len(gente)}  ya_bajados={len(gente)-len(todo)}  "
          f"a_bajar={len(todo)}", flush=True)

    hechos = fallidos = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(bajar, p): p for p in todo}
        for fut in as_completed(futs):
            try:
                fut.result(); hechos += 1
            except NecesitaLogin as e:
                raise SystemExit(f"\nERROR: {e}")
            except Exception as e:
                fallidos += 1
                with _lock:
                    print(f"  FALLO {futs[fut]['consumerId']}: "
                          f"{type(e).__name__}", flush=True)
            if hechos and hechos % 50 == 0:
                with _lock:
                    print(f"  {hechos}/{len(todo)}", flush=True)

    print(f"\nLISTO  ok={hechos}  fallidos={fallidos}")
    if fallidos:
        print("  volve a correr el mismo comando: retoma donde quedo")


if __name__ == "__main__":
    main()
