#!/usr/bin/env python3
"""Resumen del dataset descargado: cobertura, volumen y rango temporal."""
import json, pathlib, collections, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "hce"
SEC = ["evoluciones","diagnosticos","tratamientos","signos_vitales",
       "recetas","laboratorios","archivos"]

tot = collections.Counter(); porpac = []; anios = collections.Counter()
autores = collections.Counter(); con = sin = 0; errores = []

for f in sorted(SRC.glob("*.json")):
    d = json.loads(f.read_text(encoding="utf-8")); s = d["sections"]
    p = d["patient"]; nom = f"{p.get('lastName','').strip()}, {p.get('firstName','').strip()}"
    n = 0
    for k in SEC:
        v = s.get(k)
        if isinstance(v, dict) and "__error__" in v:
            errores.append((nom, k, v["__error__"])); continue
        if isinstance(v, list):
            tot[k] += len(v); n += len(v)
    for r in (s.get("evoluciones") or []):
        if isinstance(r, dict):
            m = re.match(r"(\d{4})", r.get("date") or "")
            if m: anios[m.group(1)] += 1
            autores[r.get("createdByName") or r.get("createdBy") or "?"] += 1
    porpac.append((n, nom)); con, sin = (con+1, sin) if n else (con, sin+1)

print(f"PACIENTES: {len(porpac)}   con registros: {con}   vacios: {sin}\n")
print("REGISTROS POR SECCION")
for k in SEC: print(f"  {k:16} {tot[k]:>6}")
print(f"  {'TOTAL':16} {sum(tot.values()):>6}\n")
print("EVOLUCIONES POR AÑO")
for a in sorted(anios): print(f"  {a}  {anios[a]:>5}  {'#'*max(1,anios[a]//40)}")
print("\nPROFESIONALES (top 10)")
for a, n in autores.most_common(10): print(f"  {n:>5}  {a}")
print("\nTOP 10 PACIENTES POR VOLUMEN")
for n, nom in sorted(porpac, reverse=True)[:10]: print(f"  {n:>4}  {nom}")
print(f"\nERRORES: {len(errores)}")
for e in errores[:20]: print("  ", e)
