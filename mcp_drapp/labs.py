"""Extraccion de analitos del texto libre de las evoluciones.

Reglas duras (spec seccion 6):
  1. Ningun valor se devuelve sin su snippet original.
  2. Los tokens ambiguos NO se adivinan: van a `revisar`.
  3. 'PA' es peso actual en kg, no presion arterial (notacion de la clinica,
     confirmada por la medica el 2026-08-18).
  4. Si una tabla tiene mas de una columna candidata a valor y sus
     encabezados parecen fechas, la columna de valor deja de ser
     inequivoca: no se extrae nada de esa tabla, cada fila va a `revisar`
     con su texto original (correccion 2026-08-18, ver test
     test_tabla_multi_fecha_no_extrae_y_manda_a_revisar).
"""
import re
from dataclasses import dataclass

# analito canonico -> (patrones incluidas erratas observadas, unidad)
ANALITOS: dict[str, dict] = {
    "peso":             {"pat": [r"PA", r"peso"],                          "unit": "kg"},
    "hba1c":            {"pat": [r"hba1c", r"hba2c", r"hemoglobina glicosilada", r"glicosilada"], "unit": "%"},
    "glucemia":         {"pat": [r"glucemia", r"gluc"],                    "unit": "mg/dL"},
    "tsh":              {"pat": [r"tsh"],                                  "unit": "µUI/mL"},
    "t4l":              {"pat": [r"t4\s*l", r"t4\s*libre", r"t4"],         "unit": "ng/dL"},
    "ldl":              {"pat": [r"ldl(?:-c)?"],                           "unit": "mg/dL"},
    "hdl":              {"pat": [r"hdl(?:-c)?"],                           "unit": "mg/dL"},
    "colesterol_total": {"pat": [r"col\s*t(?:otal)?", r"colesterol total"], "unit": "mg/dL"},
    "trigliceridos":    {"pat": [r"trigliceridos", r"triglic[eé]ridos", r"tg"], "unit": "mg/dL"},
    "ferritina":        {"pat": [r"ferritina"],                            "unit": "ng/mL"},
    "insulina":         {"pat": [r"insulina"],                             "unit": "µU/mL"},
    "homa":             {"pat": [r"homa(?:-ir)?"],                         "unit": ""},
    "vitamina_d":       {"pat": [r"vitamina\s*d", r"25\s*-?\s*oh"],        "unit": "ng/mL"},
    "b12":              {"pat": [r"vitamina\s*b12", r"b12"],               "unit": "pg/mL"},
    "uricemia":         {"pat": [r"uricemia", r"uric"],                    "unit": "mg/dL"},
    "shbg":             {"pat": [r"shbg"],                                 "unit": "nmol/L"},
}

_NUM = r"(\d+(?:[.,]\d+)?)"
# token alfabetico seguido de numero: candidato a analito no reconocido
_CANDIDATO = re.compile(r"\b([A-Za-zÁÉÍÓÚáéíóúñÑ][A-Za-zÁÉÍÓÚáéíóúñÑ0-9\-]{1,14})\s*:?\s*" + _NUM)
# encabezado de columna con pinta de fecha: 20/06/2024, 04-03-25, etc.
_FECHA_HEADER = re.compile(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}")


@dataclass(frozen=True)
class Lab:
    analyte: str
    value: float
    unit: str
    source: str    # 'tabla' | 'texto'
    snippet: str   # fragmento original; nunca vacio


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _orden_patrones() -> list[tuple[str, str]]:
    """Patrones ordenados de mas largo a mas corto para que 'col t' gane sobre 't4'."""
    pares = [(a, p) for a, d in ANALITOS.items() for p in d["pat"]]
    return sorted(pares, key=lambda ap: -len(ap[1]))


def _es_separador(celda: str) -> bool:
    """True para celdas de fila separadora markdown, ej. '---' o ':--:'."""
    return set(celda.replace("-", "").replace(":", "")) == set()


def _es_fecha(celda: str) -> bool:
    return bool(_FECHA_HEADER.match(celda.strip()))


def _bloques_tabla(texto: str) -> list[list[re.Match]]:
    """Agrupa lineas de tabla markdown consecutivas: una lista por tabla.

    Lineas separadas por texto que no es tabla (o por una linea en blanco)
    arrancan un bloque nuevo. Dentro de un bloque, las lineas son
    consecutivas (una termina justo donde empieza el '\\n' de la
    siguiente), lo que asegura que no mezclamos dos tablas distintas.
    """
    filas = list(re.finditer(r"^\|(.+)\|\s*$", texto, re.M))
    bloques: list[list[re.Match]] = []
    for m in filas:
        if bloques and m.start() == bloques[-1][-1].end() + 1:
            bloques[-1].append(m)
        else:
            bloques.append([m])
    return bloques


def _de_tablas(texto: str) -> tuple[list[Lab], set[tuple[int, int]], list[str]]:
    """Filas de tablas markdown: alta confianza, salvo ambiguedad de fecha.

    Cada bloque de tabla se procesa por separado. Si la segunda linea del
    bloque es una fila separadora (el patron que produce html2text.to_text
    para *todas* las tablas, incluso las de una sola fila de datos),
    tomamos la primera linea como encabezado real y miramos sus columnas:
    si mas de una tiene pinta de fecha, la tabla es ambigua (no sabemos
    cual columna corresponde a la evolucion actual) y no se extrae nada de
    ella; cada fila de datos se manda a `revisar` con su texto original.

    Si el bloque no tiene esa forma (encabezado + separador), no hay forma
    confiable de distinguir encabezado de datos: se procesa cada fila como
    en la version original (alto valor si la etiqueta matchea un analito
    conocido).
    """
    labs: list[Lab] = []
    spans: set[tuple[int, int]] = set()
    revisar: list[str] = []

    for bloque in _bloques_tabla(texto):
        filas = [[c.strip() for c in m.group(1).split("|")] for m in bloque]

        tiene_encabezado = (
            len(bloque) >= 2
            and len(filas[1]) >= 2
            and _es_separador(filas[1][1])
        )
        header_idx = 0 if tiene_encabezado else None
        ambigua = False
        if tiene_encabezado:
            candidatas_fecha = sum(1 for c in filas[0][1:] if _es_fecha(c))
            ambigua = candidatas_fecha >= 2

        for i, (m, celdas) in enumerate(zip(bloque, filas)):
            if len(celdas) < 2 or _es_separador(celdas[1]):
                continue  # fila separadora, ej. |---|---|
            if i == header_idx:
                continue  # fila de encabezado real (confirmada por el separador)

            if ambigua:
                revisar.append(m.group(0).strip())
                spans.add(m.span())
                continue

            etiqueta = re.sub(r"\*+", "", celdas[0]).strip().lower()
            mv = re.search(_NUM, celdas[1])
            if not mv:
                continue
            for analito, pat in _orden_patrones():
                if re.fullmatch(rf"\s*{pat}\s*", etiqueta, re.I):
                    unidad = celdas[1][mv.end():].strip() or ANALITOS[analito]["unit"]
                    labs.append(Lab(analito, _num(mv.group(1)), unidad, "tabla", m.group(0).strip()))
                    spans.add(m.span())
                    break

    return labs, spans, revisar


def _de_texto(texto: str, excluir: set[tuple[int, int]]) -> tuple[list[Lab], list[str]]:
    labs, vistos, revisar = [], set(), []
    for analito, pat in _orden_patrones():
        for m in re.finditer(rf"\b{pat}\b\s*:?\s*{_NUM}", texto, re.I):
            if any(a <= m.start() < b for a, b in excluir) or any(
                a <= m.start() < b for a, b in vistos
            ):
                continue
            vistos.add(m.span())
            ini, fin = max(0, m.start() - 25), min(len(texto), m.end() + 25)
            labs.append(Lab(analito, _num(m.group(1)), ANALITOS[analito]["unit"],
                            "texto", texto[ini:fin].strip()))

    conocidos = {p for _, p in _orden_patrones()}
    for m in _CANDIDATO.finditer(texto):
        if any(a <= m.start() < b for a, b in vistos | excluir):
            continue
        tok = m.group(1)
        if not any(re.fullmatch(p, tok, re.I) for p in conocidos):
            revisar.append(m.group(0).strip())
    return labs, revisar


def extract(texto: str | None) -> tuple[list[Lab], list[str]]:
    """Devuelve (labs detectados, tokens ambiguos a revisar).

    Nunca adivina: lo que no esta en ANALITOS, o cuya columna de tabla es
    ambigua, va a `revisar`.
    """
    if not texto:
        return [], []
    labs_t, spans, revisar_t = _de_tablas(texto)
    labs_x, revisar_x = _de_texto(texto, spans)
    return labs_t + labs_x, revisar_t + revisar_x
