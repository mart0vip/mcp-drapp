#!/usr/bin/env python3
"""Convierte el CSV de pacientes que exporta drapp en data/patients.json.

Es el primer paso de una instalacion desde cero: fetch_hce.py necesita esa
lista para saber que historias bajar. La API de drapp no expone un endpoint
de listado, asi que el CSV es la unica via.

Como obtener el CSV:
  app.drapp.la -> Reportes -> Pacientes -> se descarga consumers-<equipo>.csv

Uso:
  python3 scripts/importar_csv.py ~/Downloads/consumers-48b19010.csv
"""
import csv
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(f"uso: python3 {sys.argv[0]} <archivo.csv>")
    origen = pathlib.Path(sys.argv[1]).expanduser()
    if not origen.exists():
        sys.exit(f"ERROR: no existe {origen}")

    pacientes, sin_id = [], 0
    with origen.open(encoding="utf-8-sig", newline="") as fh:
        for fila in csv.DictReader(fh):
            # la columna 'id' viene como "consumers/cc5a662a"
            crudo = (fila.get("id") or "").strip()
            cid = crudo.split("/")[-1]
            if not cid:
                sin_id += 1
                continue
            pacientes.append({
                "consumerId": cid,
                "firstName": (fila.get("firstName") or "").strip(),
                "lastName": (fila.get("lastName") or "").strip(),
                "dni": (fila.get("identification") or "").strip(),
                "dob": (fila.get("dob") or "").strip(),
            })

    if not pacientes:
        sys.exit("ERROR: el CSV no tiene ninguna fila con columna 'id'. "
                 "Verifica que sea el export de Reportes -> Pacientes.")

    destino = ROOT / "data" / "patients.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(pacientes, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    print(f"LISTO  {len(pacientes)} pacientes -> {destino}")
    if sin_id:
        print(f"  ({sin_id} filas sin id, salteadas)")
    print("\nSiguiente paso:  python3 scripts/fetch_hce.py")


if __name__ == "__main__":
    main()
