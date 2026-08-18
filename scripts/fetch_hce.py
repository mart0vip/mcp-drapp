#!/usr/bin/env python3
"""Baja la historia clinica completa de drapp.la: un JSON por paciente.

Secciones (endpoints reales descubiertos del bundle de la app):
  records/_all -> evoluciones      diagnostics -> diagnosticos
  treatments   -> tratamientos     vitalSigns  -> signos vitales
  files        -> archivos         prescriptions -> recetas
  labs         -> laboratorios     stats       -> conteos (events/records)

Uso:
  export DRAPP_TOKEN='eyJ...'
  python3 scripts/fetch_hce.py --limit 15     # muestra
  python3 scripts/fetch_hce.py                # lote completo
Reanudable: saltea pacientes que ya tienen JSON en data/hce/.
"""
import argparse, json, os, pathlib, sys, threading, time
import urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

TEAM = "48b19010"
BASE = f"https://api.drapp.la/teams/{TEAM}/consumers"
SECTIONS = {
    "evoluciones":    "records/_all",
    "diagnosticos":   "diagnostics",
    "tratamientos":   "treatments",
    "signos_vitales": "vitalSigns",
    "archivos":       "files",
    "recetas":        "prescriptions",
    "laboratorios":   "labs",
    "stats":          "stats",
}
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "hce"
_print_lock = threading.Lock()

def get(url, token, retries=3):
    last = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise SystemExit("ERROR: token invalido o vencido (401). Consegui uno nuevo y volve a correr.")
            if e.code in (429,) or e.code >= 500:
                last = f"HTTP {e.code}"; time.sleep(2 * attempt); continue
            return {"__error__": f"HTTP {e.code}"}
        except Exception as e:
            last = str(e); time.sleep(1.5 * attempt)
    return {"__error__": last}

def fetch_patient(p, token):
    cid = p["consumerId"]
    out = {"patient": p, "sections": {}}
    for name, ep in SECTIONS.items():
        out["sections"][name] = get(f"{BASE}/{cid}/{ep}", token)
    (OUT / f"{cid}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    counts = {
        k: (len(v) if isinstance(v, list) else None)
        for k, v in out["sections"].items() if k != "stats"
    }
    return cid, counts

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0 = todos")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    token = os.environ.get("DRAPP_TOKEN", "").strip()
    if not token:
        sys.exit("ERROR: falta DRAPP_TOKEN")

    patients = json.loads((ROOT / "data" / "patients.json").read_text(encoding="utf-8"))
    if args.limit:
        patients = patients[: args.limit]
    OUT.mkdir(parents=True, exist_ok=True)
    todo = [p for p in patients if not (OUT / f"{p['consumerId']}.json").exists()]
    print(f"total={len(patients)}  ya_bajados={len(patients)-len(todo)}  a_bajar={len(todo)}", flush=True)

    done = fail = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_patient, p, token): p for p in todo}
        for fut in as_completed(futs):
            p = futs[fut]
            try:
                fut.result(); done += 1
            except SystemExit:
                raise
            except Exception as e:
                fail += 1
                with _print_lock:
                    print(f"  FALLO {p['consumerId']}: {e}", flush=True)
            if done % 50 == 0 and done:
                with _print_lock:
                    print(f"  {done}/{len(todo)} ok, {fail} fallidos", flush=True)
    print(f"\nLISTO  ok={done}  fallidos={fail}")

if __name__ == "__main__":
    main()
