#!/usr/bin/env python3
"""Convierte los JSON de data/hce/ en un .md legible por paciente (data/md/).

Nombre de archivo: Apellido_Nombre_DNI.md  (ordenable alfabeticamente)
Uso: python3 scripts/render_md.py
"""
import html, json, pathlib, re, unicodedata
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC, OUT = ROOT / "data" / "hce", ROOT / "data" / "md"

SECCIONES = [
    ("evoluciones", "Evoluciones"), ("diagnosticos", "Diagnósticos"),
    ("tratamientos", "Tratamientos"), ("signos_vitales", "Signos vitales"),
    ("recetas", "Recetas"), ("laboratorios", "Laboratorios"), ("archivos", "Archivos"),
]

def slug(s, fallback=""):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9]+", "_", s)).strip("_") or fallback

def _celda(c):
    """Contenido de una celda -> texto plano en una sola linea."""
    c = re.sub(r"(?i)<br\s*/?>", " ", c)
    c = re.sub(r"<[^>]+>", "", c)
    c = html.unescape(c).replace("\xa0", " ")
    return re.sub(r"\s+", " ", c).strip().replace("|", "\\|")

def _tabla(m):
    """<table> -> tabla markdown. Primera fila = encabezado."""
    filas = []
    for tr in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", m.group(0)):
        celdas = [_celda(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", tr)]
        if any(celdas):
            filas.append(celdas)
    if not filas:
        return ""
    ancho = max(len(f) for f in filas)
    filas = [f + [""] * (ancho - len(f)) for f in filas]
    enc, cuerpo = filas[0], filas[1:]
    out = ["| " + " | ".join(enc) + " |", "|" + "---|" * ancho]
    out += ["| " + " | ".join(f) + " |" for f in cuerpo]
    return "\n\n" + "\n".join(out) + "\n\n"

def to_md(h):
    """HTML del editor -> markdown, preservando tablas, listas y saltos."""
    if not isinstance(h, str) or not h.strip():
        return ""
    h = re.sub(r"(?is)<(script|style).*?</\1>", "", h)

    # las tablas se convierten aparte y se reinsertan al final
    tablas = []
    def _stash(m):
        tablas.append(_tabla(m))
        return f"\x00TABLA{len(tablas)-1}\x00"
    h = re.sub(r"(?is)<table[^>]*>.*?</table>", _stash, h)

    h = re.sub(r"(?i)<br\s*/?>", "\n", h)
    h = re.sub(r"(?i)</(p|div|h[1-6])>", "\n\n", h)
    h = re.sub(r"(?i)<li[^>]*>", "\n- ", h)
    h = re.sub(r"(?is)<(b|strong)[^>]*>(.*?)</\1>", r"**\2**", h)
    h = re.sub(r"(?is)<(i|em)[^>]*>(.*?)</\1>", r"*\2*", h)
    h = re.sub(r"<[^>]+>", "", h)
    h = html.unescape(h).replace("\xa0", " ")
    h = "\n".join(l.rstrip() for l in h.split("\n"))
    h = re.sub(r"\n{3,}", "\n\n", h).strip()
    h = re.sub(r"\*\*\s*\*\*", "", h)

    for i, t in enumerate(tablas):
        h = h.replace(f"\x00TABLA{i}\x00", t)
    return re.sub(r"\n{3,}", "\n\n", h).strip()

def ts(ms):
    if not isinstance(ms, (int, float)):
        return ""
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")

def firma(r):
    return r.get("createdByName") or r.get("createdBy") or "sin firma"

def bloque_generico(item):
    """Render de secciones sin esquema conocido: campos utiles + fallback JSON."""
    campos, usados = [], {"id", "rev", "type", "teamID", "deleted", "consumers",
                          "computedAt", "createdByResourceID", "updatedByResourceID",
                          "createdByLicense", "createdAt", "updatedAt", "updatedBy"}
    for k, v in item.items():
        if k in usados or v in (None, "", [], {}):
            continue
        if isinstance(v, str) and "<" in v and ">" in v:
            v = to_md(v)
        elif isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        campos.append(f"- **{k}:** {v}")
    return "\n".join(campos)

ESTADOS = {"chronic": "crónico", "active": "activo", "inactive": "inactivo",
           "resolved": "resuelto", "suspended": "suspendido", "finished": "finalizado"}

def _kb(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"

def bloque_diagnostico(it):
    L = []
    if it.get("label"):
        L.append(f"**{it['label']}**" + (f" (CIE `{it['code']}`)" if it.get("code") else ""))
    est = ESTADOS.get(it.get("status"), it.get("status"))
    if est:
        L.append(f"- Estado: {est}")
    if it.get("startsAt"):
        L.append(f"- Desde: {it['startsAt']}")
    if it.get("endsAt"):
        L.append(f"- Hasta: {it['endsAt']}")
    if it.get("notes"):
        L.append(f"- Notas: {to_md(it['notes'])}")
    return "\n".join(L)

def bloque_tratamiento(it):
    L = []
    if it.get("label"):
        L.append(f"**{it['label']}**")
    if it.get("drug"):
        L.append(f"- Droga: {it['drug']}")
    if it.get("presentation"):
        L.append(f"- Presentación: {it['presentation']}")
    if it.get("company"):
        L.append(f"- Laboratorio: {it['company']}")
    if it.get("posology") or it.get("dose"):
        L.append(f"- Posología: {it.get('posology') or it.get('dose')}")
    est = ESTADOS.get(it.get("status"), it.get("status"))
    if est:
        L.append(f"- Estado: {est}")
    if it.get("startsAt"):
        L.append(f"- Desde: {it['startsAt']}")
    if it.get("endsAt"):
        L.append(f"- Hasta: {it['endsAt']}")
    if it.get("notes"):
        L.append(f"- Notas: {to_md(it['notes'])}")
    return "\n".join(L)

def bloque_archivo(it):
    nom = it.get("name") or "archivo"
    L = [f"**[{nom}]({it['link']})**" if it.get("link") else f"**{nom}**"]
    det = [x for x in (it.get("contentType"), _kb(it.get("size"))) if x]
    if det:
        L.append("- " + " · ".join(det))
    if it.get("deleted"):
        L.append("- ⚠️ eliminado")
    if it.get("notes"):
        L.append(f"- Notas: {to_md(it['notes'])}")
    return "\n".join(L)

RENDERERS = {"diagnosticos": bloque_diagnostico, "tratamientos": bloque_tratamiento,
             "archivos": bloque_archivo}

def render(d):
    p = d["patient"]
    nom = f"{p.get('lastName','').strip()}, {p.get('firstName','').strip()}".strip(", ")
    L = [f"# {nom}", ""]
    meta = [f"- **DNI:** {p.get('dni') or '—'}",
            f"- **Fecha de nacimiento:** {p.get('dob') or '—'}",
            f"- **ID drapp:** `{p['consumerId']}`"]
    st = d["sections"].get("stats")
    if isinstance(st, dict) and "__error__" not in st:
        meta.append(f"- **Turnos registrados:** {st.get('events', 0)}")
    L += meta + [""]

    resumen = []
    for key, tit in SECCIONES:
        v = d["sections"].get(key)
        resumen.append(f"{tit}: {len(v) if isinstance(v, list) else '?'}")
    L += ["> " + " · ".join(resumen), "", "---", ""]

    vacio = True
    for key, tit in SECCIONES:
        v = d["sections"].get(key)
        if isinstance(v, dict) and "__error__" in v:
            L += [f"## {tit}", "", f"> ⚠️ error al descargar: {v['__error__']}", ""]
            vacio = False
            continue
        if not isinstance(v, list) or not v:
            continue
        vacio = False
        L += [f"## {tit}", ""]
        items = sorted(v, key=lambda x: (x.get("date") or "", x.get("createdAt") or 0))
        for it in items:
            fecha = it.get("date") or ts(it.get("createdAt")) or "sin fecha"
            L += [f"### {fecha} — {firma(it)}", ""]
            if key == "evoluciones":
                cuerpo = to_md(it.get("content"))
            else:
                cuerpo = RENDERERS.get(key, bloque_generico)(it)
            if not cuerpo:
                cuerpo = bloque_generico(it)
            L += [cuerpo or "_(sin contenido)_", ""]
            if it.get("updatedAt") and it.get("updatedAt") != it.get("createdAt"):
                L += [f"<sub>editado {ts(it['updatedAt'])} por {it.get('updatedBy','?')}</sub>", ""]
        L += ["---", ""]

    if vacio:
        L += ["_Sin registros clínicos cargados._", ""]
    return nom, "\n".join(L).rstrip() + "\n"

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = sorted(SRC.glob("*.json"))
    if not files:
        raise SystemExit("No hay JSON en data/hce/. Corre primero fetch_hce.py")
    idx, con, sin = [], 0, 0
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        p = d["patient"]
        nom, md = render(d)
        name = (f"{slug(p.get('lastName'), 'SinApellido')}"
                f"_{slug(p.get('firstName'), 'SinNombre')}"
                f"_{slug(p.get('dni'), 'sinDNI')}.md")
        if (OUT / name).exists():                      # colision: desempatar con el id
            name = name[:-3] + f"_{p['consumerId']}.md"
        (OUT / name).write_text(md, encoding="utf-8")
        n = sum(len(v) for k, v in d["sections"].items()
                if k != "stats" and isinstance(v, list))
        con, sin = (con + 1, sin) if n else (con, sin + 1)
        idx.append((nom, name, n))

    idx.sort(key=lambda r: r[0].lower())
    ind = ["# Historias clínicas — Centro Anselmi", "",
           f"{len(idx)} pacientes · {con} con registros · {sin} sin registros", "",
           "| Paciente | Registros | Archivo |", "|---|---:|---|"]
    ind += [f"| {n} | {c} | [{fn}](./{fn}) |" for n, fn, c in idx]
    (OUT / "INDICE.md").write_text("\n".join(ind) + "\n", encoding="utf-8")
    print(f"LISTO  {len(idx)} .md generados en {OUT}  ({con} con datos / {sin} vacios)")

if __name__ == "__main__":
    main()
