"""Indice SQLite derivado del corpus. Se puede borrar y regenerar sin perdida."""
import json
import pathlib
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone

from .corpus import PacienteCorpus, cargar
from .html2text import to_text
from .labs import extract

SCHEMA_VERSION = "1"

# Una misma profesional aparece con varias firmas. Mapeo explicito, no heuristico:
# fusionar por parecido seria un error clinico.
AUTORES: dict[str, str] = {
    "anselmi, maria eugenia": "Anselmi, María Eugenia",
    "maru anselmi": "Anselmi, María Eugenia",
    "maruanselmi@gmail.com": "Anselmi, María Eugenia",
    "vazquez, virginia": "Vázquez, Virginia",
    # las claves son salida de norm(), que siempre quita diacriticos:
    # "vázquez" con tilde acá nunca matchearia una firma real.
    "virginia vazquez": "Vázquez, Virginia",
}

DDL = """
CREATE TABLE patients (
  consumer_id TEXT PRIMARY KEY, last_name TEXT, first_name TEXT, full_name TEXT,
  name_norm TEXT, dni TEXT, dob TEXT, created_at TEXT,
  n_records INTEGER, first_visit TEXT, last_visit TEXT);
CREATE TABLE records (
  record_id TEXT NOT NULL, consumer_id TEXT NOT NULL, section TEXT NOT NULL,
  date TEXT, author TEXT, author_norm TEXT, text TEXT, html TEXT,
  code TEXT, label TEXT, status TEXT, drug TEXT, link TEXT,
  created_at INTEGER, updated_at INTEGER, raw TEXT);
CREATE VIRTUAL TABLE records_fts USING fts5(
  text, patient_name, tokenize="unicode61 remove_diacritics 2");
CREATE TABLE labs (
  record_id TEXT NOT NULL, consumer_id TEXT NOT NULL, date TEXT,
  analyte TEXT NOT NULL, value REAL, unit TEXT, source TEXT NOT NULL,
  snippet TEXT NOT NULL);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX idx_pat_dni ON patients(dni);
CREATE INDEX idx_pat_norm ON patients(name_norm);
CREATE INDEX idx_pat_last ON patients(last_visit);
CREATE INDEX idx_rec_id ON records(record_id);
CREATE INDEX idx_rec_cons ON records(consumer_id);
CREATE INDEX idx_rec_date ON records(date);
CREATE INDEX idx_rec_sec ON records(section);
CREATE INDEX idx_labs ON labs(consumer_id, analyte, date);
"""


def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", (s or "")).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def fecha(v) -> str | None:
    """Normaliza a YYYY-MM-DD.

    En el corpus real 241 de las 3957 evoluciones traen la fecha como
    timestamp ISO completo (`2021-09-02T21:01:05.098Z`) y el resto como
    fecha simple. La comparacion de strings funciona para `desde`, pero
    `'2026-06-12T10:00:00Z' <= '2026-06-12'` es False: un filtro `hasta`
    excluia en silencio los registros de su propio dia. La hora completa
    sigue disponible en la columna `raw`.
    """
    if not isinstance(v, str):
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", v.strip())
    return m.group(1) if m else None


def _autor(r: dict) -> tuple[str, str]:
    crudo = r.get("createdByName") or r.get("createdBy") or "sin firma"
    return crudo, AUTORES.get(norm(crudo), crudo)


def construir(db: pathlib.Path, pacientes: list[PacienteCorpus]) -> dict:
    db = pathlib.Path(db)
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    con.executescript(DDL)
    n_rec = n_lab = 0
    for p in pacientes:
        nombre = f"{(p.patient.get('lastName') or '').strip()}, {(p.patient.get('firstName') or '').strip()}".strip(", ")
        fechas = []
        for sec, r in p.registros():
            rid = r.get("id")
            if not rid:
                continue
            texto = to_text(r.get("content")) if sec == "evoluciones" else (r.get("label") or r.get("name") or "")
            crudo, unificado = _autor(r)
            # El mismo "id" puede repetirse entre secciones del mismo paciente
            # (una evolucion con archivo/diagnostico/tratamiento asociado
            # comparte id con su contraparte: 209 casos en el corpus real).
            # record_id no es unico: cada fila se inserta y se toma su rowid
            # real, para que la fila de FTS nunca quede huerfana ni el join
            # pueda reengancharse a un rowid reciclado de otro registro.
            cur = con.execute(
                "INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rid, p.consumer_id, sec, fecha(r.get("date")), crudo, unificado, texto,
                 r.get("content"), r.get("code"), r.get("label"), r.get("status"),
                 r.get("drug"), r.get("link"), r.get("createdAt"), r.get("updatedAt"),
                 json.dumps(r, ensure_ascii=False)))
            con.execute("INSERT INTO records_fts (rowid, text, patient_name) VALUES (?,?,?)",
                        (cur.lastrowid, texto, nombre))
            n_rec += 1
            if fecha(r.get("date")):
                fechas.append(fecha(r.get("date")))
            if sec == "evoluciones":
                for l in extract(texto)[0]:
                    con.execute("INSERT INTO labs VALUES (?,?,?,?,?,?,?,?)",
                                (rid, p.consumer_id, fecha(r.get("date")), l.analyte,
                                 l.value, l.unit, l.source, l.snippet))
                    n_lab += 1
        con.execute("INSERT OR REPLACE INTO patients VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (p.consumer_id, p.patient.get("lastName"), p.patient.get("firstName"),
                     nombre, norm(nombre), p.patient.get("dni"), p.patient.get("dob"),
                     p.patient.get("createdAt"), len(fechas),
                     min(fechas) if fechas else None, max(fechas) if fechas else None))
    for k, v in {"last_refresh": datetime.now(timezone.utc).isoformat(),
                 "schema_version": SCHEMA_VERSION,
                 "n_patients": str(len(pacientes)), "n_records": str(n_rec)}.items():
        con.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, v))
    con.commit()
    con.close()
    return {"n_patients": len(pacientes), "n_records": n_rec, "n_labs": n_lab}


def reconstruir(db: pathlib.Path, corpus_dir: pathlib.Path) -> dict:
    return construir(db, cargar(corpus_dir))


def _con(db):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    return c


def estado(db) -> dict:
    with _con(db) as c:
        m = {k: v for k, v in c.execute("SELECT key, value FROM meta")}
    lr = m.get("last_refresh")
    dias = None
    if lr:
        dias = (datetime.now(timezone.utc) - datetime.fromisoformat(lr)).days
    return {"n_patients": int(m.get("n_patients", 0)),
            "n_records": int(m.get("n_records", 0)),
            "last_refresh": lr, "dias_desde_refresh": dias,
            "schema_version": m.get("schema_version"),
            "advertencia": ("El corpus tiene mas de 7 dias; considera correr refresh."
                            if dias is not None and dias > 7 else None)}


def _proc(db, extra: dict) -> dict:
    e = estado(db)
    return {**extra, "corpus": {"last_refresh": e["last_refresh"],
                                "dias_desde_refresh": e["dias_desde_refresh"],
                                "advertencia": e["advertencia"]}}


def find_patient(db, query: str, limit: int = 20) -> list[dict]:
    q = norm(query)
    with _con(db) as c:
        filas = c.execute(
            """SELECT consumer_id, full_name, dni, dob, n_records, last_visit
               FROM patients
               WHERE name_norm LIKE ? OR dni LIKE ?
               ORDER BY n_records DESC LIMIT ?""",
            (f"%{q}%", f"%{query.strip()}%", limit)).fetchall()
    return [dict(f) for f in filas]


def _resolver(c, consumer_id, dni):
    if consumer_id:
        return consumer_id
    f = c.execute("SELECT consumer_id FROM patients WHERE dni=?", (dni,)).fetchone()
    return f["consumer_id"] if f else None


def get_patient(db, consumer_id=None, dni=None, sections=None,
                desde=None, hasta=None, limit=50) -> dict:
    with _con(db) as c:
        cid = _resolver(c, consumer_id, dni)
        if not cid:
            return _proc(db, {"patient": None, "records": []})
        p = c.execute("SELECT * FROM patients WHERE consumer_id=?", (cid,)).fetchone()
        sql = "SELECT record_id, section, date, author_norm AS author, text, code, label, status, drug, link FROM records WHERE consumer_id=?"
        args = [cid]
        if sections:
            sql += f" AND section IN ({','.join('?' * len(sections))})"
            args += list(sections)
        if desde:
            sql += " AND date >= ?"; args.append(desde)
        if hasta:
            sql += " AND date <= ?"; args.append(hasta)
        sql += " ORDER BY date, created_at LIMIT ?"; args.append(limit)
        rs = [dict(r) for r in c.execute(sql, args)]
    return _proc(db, {"patient": dict(p) if p else None, "records": rs})


def search_records(db, query: str, section: str = "evoluciones", desde=None,
                   hasta=None, author=None, limit: int = 30) -> list[dict]:
    sql = """SELECT r.record_id, r.consumer_id, p.full_name, r.date,
                    r.author_norm AS author, r.section,
                    snippet(records_fts, 0, '[', ']', ' … ', 18) AS snippet
             FROM records_fts f
             JOIN records r ON r.rowid = f.rowid
             JOIN patients p ON p.consumer_id = r.consumer_id
             WHERE records_fts MATCH ?"""
    args: list = [query]
    if section:
        sql += " AND r.section = ?"; args.append(section)
    if desde:
        sql += " AND r.date >= ?"; args.append(desde)
    if hasta:
        sql += " AND r.date <= ?"; args.append(hasta)
    if author:
        sql += " AND r.author_norm LIKE ?"; args.append(f"%{author}%")
    sql += " ORDER BY bm25(records_fts) LIMIT ?"; args.append(limit)
    with _con(db) as c:
        return [dict(r) for r in c.execute(sql, args)]


def cohort(db, contiene=None, sin_visitas_desde=None, diagnostico=None,
           droga=None, limit: int = 100) -> list[dict]:
    cond, args, motivos = [], [], []
    if contiene:
        cond.append("""p.consumer_id IN (SELECT r.consumer_id FROM records_fts f
                       JOIN records r ON r.rowid=f.rowid WHERE records_fts MATCH ?)""")
        args.append(contiene); motivos.append(f"menciona '{contiene}'")
    if sin_visitas_desde:
        cond.append("(p.last_visit IS NULL OR p.last_visit < ?)")
        args.append(sin_visitas_desde); motivos.append(f"sin visitas desde {sin_visitas_desde}")
    if diagnostico:
        cond.append("""p.consumer_id IN (SELECT consumer_id FROM records
                       WHERE section='diagnosticos' AND (code=? OR label LIKE ?))""")
        args += [diagnostico, f"%{diagnostico}%"]; motivos.append(f"diagnostico {diagnostico}")
    if droga:
        cond.append("""p.consumer_id IN (SELECT consumer_id FROM records
                       WHERE section='tratamientos' AND (drug LIKE ? OR label LIKE ?))""")
        args += [f"%{droga}%", f"%{droga}%"]; motivos.append(f"tratamiento {droga}")
    if not cond:
        return []
    sql = ("SELECT consumer_id, full_name, dni, n_records, last_visit FROM patients p WHERE "
           + " AND ".join(cond) + " ORDER BY last_visit DESC LIMIT ?")
    args.append(limit)
    with _con(db) as c:
        filas = [dict(r) for r in c.execute(sql, args)]
    for f in filas:
        f["motivo"] = "; ".join(motivos)
    return filas


def lab_series(db, consumer_id=None, dni=None, analitos=None, desde=None, hasta=None) -> dict:
    with _con(db) as c:
        cid = _resolver(c, consumer_id, dni)
        if not cid:
            return _proc(db, {"series": {}, "cobertura": {}})
        sql = "SELECT analyte, value, unit, date, source, snippet FROM labs WHERE consumer_id=?"
        args: list = [cid]
        if analitos:
            sql += f" AND analyte IN ({','.join('?' * len(analitos))})"; args += list(analitos)
        if desde:
            sql += " AND date >= ?"; args.append(desde)
        if hasta:
            sql += " AND date <= ?"; args.append(hasta)
        sql += " ORDER BY date"
        series: dict[str, list] = {}
        for r in c.execute(sql, args):
            series.setdefault(r["analyte"], []).append(dict(r))
        tot = c.execute("SELECT COUNT(*) n FROM records WHERE consumer_id=? AND section='evoluciones'",
                        (cid,)).fetchone()["n"]
        conl = c.execute("""SELECT COUNT(DISTINCT record_id) n FROM labs WHERE consumer_id=?""",
                         (cid,)).fetchone()["n"]
    return _proc(db, {"series": series,
                      "cobertura": {"evoluciones_totales": tot, "con_labs": conl,
                                    "nota": "La ausencia de un valor no significa valor normal."}})
