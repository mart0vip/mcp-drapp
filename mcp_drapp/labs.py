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
  5. Todo valor fuera del rango plausible de su analito (ver `rango` en
     ANALITOS) NO se emite como Lab: se manda a `revisar` con su snippet
     original, nunca se descarta en silencio (correccion 2026-08-18, ronda
     1: el corpus real tenia HOMA=2024 y vitamina_d=2024 -- años colados
     como si fueran resultados -- y otros imposibles como hba1c=663 o
     peso=113900; ver test_ano_no_se_confunde_con_valor).
  6. 'T4' suelto (sin 'L'/'libre') es dosis de levotiroxina en mcg, NO
     resultado de T4 libre: se saco del patron de t4l, confirmado por la
     medica (ronda de correccion 2, 2026-08-18). No se crea una serie de
     dosis: un T4 suelto va a `revisar` como token no reconocido.
  7. 'PA' sigue siendo peso por defecto (regla 3), salvo que el contexto
     (mmHg, MAPA, "24 h", forma sistole/diastole) indique presion
     arterial: en ese caso no se emite peso y el fragmento va a `revisar`.
     No se agrega un analito de presion arterial, solo se excluye (ronda
     de correccion 2, caso real: "Promedio de PA 24 h: 119/73 mmHg").
"""
import re
from dataclasses import dataclass

# analito canonico -> patrones (incluidas erratas observadas), unidad y
# rango plausible (min, max) inclusive. El rango es deliberadamente ancho:
# busca atrapar lo absurdo (un año, un peso de 2 kg), no lo infrecuente.
ANALITOS: dict[str, dict] = {
    "peso":             {"pat": [r"PA", r"peso"],                          "unit": "kg",      "rango": (25, 350)},
    "hba1c":            {"pat": [r"hba1c", r"hba2c", r"hemoglobina glicosilada", r"glicosilada"], "unit": "%", "rango": (3, 20)},
    "glucemia":         {"pat": [r"glucemia", r"glucosa", r"gluc"],        "unit": "mg/dL",   "rango": (20, 800)},
    "tsh":              {"pat": [r"tsh"],                                  "unit": "µUI/mL",  "rango": (0.001, 200)},
    # 't4' solo (sin 'l'/'libre') se saco del patron: en el corpus real es
    # dosis de levotiroxina en mcg (ej. "T4 100"), no resultado de T4 libre.
    # Confirmado por la medica, ronda de correccion 2 (2026-08-18).
    "t4l":              {"pat": [r"t4\s*l", r"t4\s*libre"],                "unit": "ng/dL",   "rango": (0.1, 12)},
    # "colesterol ldl"/"colesterol hdl" son sinonimos de ldl/hdl (no analitos
    # nuevos), aprobado por la medica ronda 3 (2026-08-18).
    "ldl":              {"pat": [r"ldl(?:-c)?", r"colesterol ldl"],        "unit": "mg/dL",   "rango": (10, 500)},
    "hdl":              {"pat": [r"hdl(?:-c)?", r"colesterol hdl"],        "unit": "mg/dL",   "rango": (5, 200)},
    "colesterol_total": {"pat": [r"col\s*t(?:otal)?", r"colesterol total"], "unit": "mg/dL",  "rango": (50, 600)},
    # "tag" es sinonimo de trigliceridos en esta clinica (no es un analito
    # nuevo), confirmado por la medica, ronda de correccion 2.
    "trigliceridos":    {"pat": [r"trigliceridos", r"triglic[eé]ridos", r"tg", r"tag"], "unit": "mg/dL", "rango": (20, 2000)},
    "ferritina":        {"pat": [r"ferritina"],                            "unit": "ng/mL",   "rango": (1, 3000)},
    "insulina":         {"pat": [r"insulina"],                             "unit": "µU/mL",   "rango": (0.5, 400)},
    "homa":             {"pat": [r"homa(?:-ir)?"],                         "unit": "",        "rango": (0.1, 50)},
    "vitamina_d":       {"pat": [r"vitamina\s*d", r"25\s*-?\s*oh"],        "unit": "ng/mL",   "rango": (1, 150)},
    "b12":              {"pat": [r"vitamina\s*b12", r"b12"],               "unit": "pg/mL",   "rango": (50, 3000)},
    # "acido urico"/"ácido úrico" son sinonimos de uricemia (no analito
    # nuevo), aprobado por la medica ronda 3 (2026-08-18).
    "uricemia":         {"pat": [r"uricemia", r"uric", r"ácido úrico", r"acido urico"], "unit": "mg/dL", "rango": (0.5, 20)},
    "shbg":             {"pat": [r"shbg"],                                 "unit": "nmol/L",  "rango": (1, 300)},
    # tres analitos nuevos confirmados por la medica, ronda de correccion 2.
    "hemoglobina":      {"pat": [r"hb", r"hemoglobina"],                   "unit": "g/dL",    "rango": (5, 20)},
    "hematocrito":      {"pat": [r"hto", r"hematocrito"],                  "unit": "%",       "rango": (15, 60)},
    "imc":              {"pat": [r"imc"],                                  "unit": "",        "rango": (12, 70)},

    # --- ronda 3 (2026-08-18): analitos que hoy caen en `revisar`, medidos
    # contra el corpus real (1569 historias, 3957 evoluciones) y aprobados
    # por la medica. Rangos deliberadamente anchos: atrapan lo absurdo, no
    # lo infrecuente. "creatininemia" es sinonimo de "creatinina", no un
    # analito aparte.
    "creatinina":            {"pat": [r"creatinina", r"creatininemia"],    "unit": "mg/dL",  "rango": (0.2, 15)},
    "homocisteina":          {"pat": [r"homocisteina", r"homocisteína"],   "unit": "µmol/L", "rango": (2, 100)},
    "uremia":                {"pat": [r"uremia", r"urea"],                 "unit": "mg/dL",  "rango": (5, 300)},
    "transferrina":          {"pat": [r"transferrina"],                    "unit": "mg/dL",  "rango": (100, 500)},
    "ferremia":              {"pat": [r"ferremia"],                        "unit": "µg/dL",  "rango": (10, 300)},
    "proteinas_totales":     {"pat": [r"proteinas totales", r"proteínas totales"], "unit": "g/dL", "rango": (3, 12)},
    "albumina":              {"pat": [r"albumina", r"albúmina"],           "unit": "g/dL",   "rango": (1, 7)},
    # "mg" (miligramo) como patron de magnesio SE SACO: verificado contra
    # el corpus, genera falsos positivos claros y frecuentes -- dosis de
    # medicacion ("Lamotrigina 200 mg: 1 comprimido", "LOSARTAN 50 MG 2
    # COMP", "naltrexona 50 mg 1") capturan el numero de comprimidos/veces
    # como si fuera un valor de magnesio, y ese numero (1 o 2) cae dentro
    # del rango plausible (0.5, 5) asi que el filtro de rango no lo frena:
    # 27 de 169 valores (16%) medidos con el patron "mg" eran justamente
    # esto. Se deja solo "magnesio" (ronda 3, 2026-08-18).
    "magnesio":              {"pat": [r"magnesio"],                       "unit": "mg/dL",  "rango": (0.5, 5)},
    "atpo":                  {"pat": [r"atpo", r"anti-tpo", r"anti tpo"],  "unit": "UI/mL",  "rango": (0, 2000)},
    "eritrosedimentacion":   {"pat": [r"eritrosedimentacion", r"eritrosedimentación", r"esd", r"vsg"], "unit": "mm/h", "rango": (1, 150)},
    "vcm":                   {"pat": [r"vcm"],                             "unit": "fL",     "rango": (50, 130)},
    "chcm":                  {"pat": [r"chcm"],                            "unit": "g/dL",   "rango": (25, 40)},
    "eosinofilos":           {"pat": [r"eosinofilos", r"eosinófilos"],     "unit": "%",      "rango": (0, 40)},
    "linfocitos":            {"pat": [r"linfocitos"],                      "unit": "%",      "rango": (0, 80)},
    "monocitos":             {"pat": [r"monocitos"],                       "unit": "%",      "rango": (0, 30)},
    "basofilos":             {"pat": [r"basofilos", r"basófilos"],         "unit": "%",      "rango": (0, 5)},
    "neutrofilos":           {"pat": [r"neutrofilos", r"neutrófilos", r"neutrófilos segmentados", r"neutrofilos segmentados"], "unit": "%", "rango": (0, 95)},
    # "testosterona total" NO se agrega: los valores reales del corpus van
    # de 0.2 a 72.2, lo que indica que conviven dos unidades sin normalizar
    # (ng/mL y ng/dL). Un rango unico mezclaria series incomparables.
    # Queda en `revisar`; decision de la medica, ronda 3 (2026-08-18).
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
    # html2text envuelve todo <th> en **negrita**, asi que el encabezado real
    # llega como "**20/06/2024**". Sin despojar los asteriscos la deteccion de
    # tablas multi-fecha no se activaba nunca en produccion.
    return bool(_FECHA_HEADER.match(re.sub(r"\*+", "", celda).strip()))


# senales de que "PA" es presion arterial (MAPA), no peso: mmHg, MAPA,
# "24 h"/"24h" (monitoreo de 24 horas), o forma sistole/diastole (119/73).
# Regla PA=peso confirmada por la medica; esta es la unica excepcion que
# ella confirmo (ronda de correccion 2, caso real del corpus: "Promedio de
# PA 24 h: 119/73 mmHg"). No se agrega un analito de presion arterial: solo
# se excluye, tal como pidio la medica.
_SENAL_PRESION_LITERAL = re.compile(r"mmHg|MAPA|24\s*h\b", re.I)
# candidato a "NN/NN": se valida por rango antes de aceptarlo como senal,
# porque una fecha DD/MM (omnipresente en estas notas: "31/08", "24/05")
# tiene la misma forma que una sistole/diastole y produciria falsos
# positivos -- se detecto exactamente ese problema al medir contra el
# corpus real (7 de 8 "MAPA" detectados eran en realidad un peso con una
# fecha cerca, alguno con "kg" al lado).
_RATIO_CANDIDATO = re.compile(r"\b(\d{2,3})\s*/\s*(\d{2,3})\b")


def _es_forma_presion(sistole: int, diastole: int) -> bool:
    return 70 <= sistole <= 250 and 40 <= diastole <= 150 and sistole > diastole


def _tiene_senal_presion(fragmento: str) -> bool:
    if _SENAL_PRESION_LITERAL.search(fragmento):
        return True
    return any(
        _es_forma_presion(int(m.group(1)), int(m.group(2)))
        for m in _RATIO_CANDIDATO.finditer(fragmento)
    )


def _en_rango(analito: str, valor: float) -> bool:
    lo, hi = ANALITOS[analito]["rango"]
    return lo <= valor <= hi


def _filtrar_rango(candidatos: list[Lab]) -> tuple[list[Lab], list[str], dict[str, int]]:
    """Aplica el rango plausible de cada analito a una lista de candidatos.

    Nunca descarta en silencio: lo que cae fuera de rango se devuelve en
    `revisar` con su snippet intacto. `rechazos` cuenta cuantos candidatos
    se filtraron por analito (solo para diagnostico/medicion de cobertura;
    no forma parte de la interfaz minima del modulo).
    """
    aceptados, revisar, rechazos = [], [], {}
    for l in candidatos:
        if _en_rango(l.analyte, l.value):
            aceptados.append(l)
        else:
            revisar.append(l.snippet)
            rechazos[l.analyte] = rechazos.get(l.analyte, 0) + 1
    return aceptados, revisar, rechazos


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

    Los `Lab` que devuelve son candidatos: todavia no pasaron el filtro de
    rango plausible (eso lo aplica `_filtrar_rango`, llamado desde
    `extract`/`extract_con_rechazos`).
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
                    if analito == "peso" and pat == "PA" and _tiene_senal_presion(m.group(0)):
                        # excepcion PA=peso: contexto de MAPA en la propia
                        # fila (mmHg, 24h, sistole/diastole). No se emite
                        # ningun Lab; la fila completa va a revisar.
                        revisar.append(m.group(0).strip())
                        spans.add(m.span())
                        break
                    unidad = celdas[1][mv.end():].strip() or ANALITOS[analito]["unit"]
                    labs.append(Lab(analito, _num(mv.group(1)), unidad, "tabla", m.group(0).strip()))
                    spans.add(m.span())
                    break
            else:
                # Ninguna etiqueta del diccionario matcheo. _de_texto tiene su
                # red de contencion (_CANDIDATO) pero las tablas no la tenian:
                # 1132 filas del corpus (creatinina, homocisteina, colesterol
                # hdl/ldl...) desaparecian sin quedar ni en labs ni en revisar.
                revisar.append(m.group(0).strip())
                spans.add(m.span())

    return labs, spans, revisar


def _parece_anio(valor: str) -> bool:
    """Un entero de cuatro digitos en rango de año calendario."""
    return bool(re.fullmatch(r"(?:19|20)\d{2}", valor.strip()))


def _es_derivado(texto: str, inicio: int) -> bool:
    """True si el token del analito es parte de una razon o de un derivado.

    Casos reales del corpus: "CT/HDL 5,4" (razon adimensional), "TG/HDL: 1,54"
    y "no-HDL 148" (otro analito, clinicamente inverso). Los tres se emitian
    como si fueran HDL y el filtro de rango no los atrapaba.
    """
    previo = texto[max(0, inicio - 4):inicio].lower()
    return previo.rstrip().endswith("/") or bool(re.search(r"\bno\s*-?\s*$", previo))


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
            snippet = texto[ini:fin].strip()

            if _es_derivado(texto, m.start()):
                revisar.append(snippet)
                continue

            # "Ferritina 2024: 10,7" -> el primer numero era el año de la nota
            # y el valor real es el que sigue a los dos puntos. Sin esto el
            # 10,7 desaparecia de labs y de revisar.
            valor = m.group(1)
            sig = re.match(rf"\s*:\s*\**\s*{_NUM}", texto[m.end():])
            if sig and _parece_anio(valor):
                valor = sig.group(1)
                fin = min(len(texto), m.end() + sig.end() + 25)
                snippet = texto[ini:fin].strip()
                vistos.add((m.start(), m.end() + sig.end()))

            if analito == "peso" and pat == "PA":
                # excepcion PA=peso: si el contexto (ventana ~40 caracteres
                # alrededor del match) tiene pinta de MAPA/presion arterial,
                # no se adivina un peso; el fragmento va a revisar.
                ventana = texto[max(0, m.start() - 40): min(len(texto), m.end() + 40)]
                if _tiene_senal_presion(ventana):
                    revisar.append(snippet)
                    continue

            labs.append(Lab(analito, _num(valor), ANALITOS[analito]["unit"],
                            "texto", snippet))

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

    Nunca adivina: lo que no esta en ANALITOS, cuya columna de tabla es
    ambigua, o cuyo valor cae fuera del rango plausible del analito
    (ver `rango` en ANALITOS), va a `revisar` en vez de emitirse como Lab.
    """
    labs, revisar, _ = extract_con_rechazos(texto)
    return labs, revisar


def extract_con_rechazos(texto: str | None) -> tuple[list[Lab], list[str], dict[str, int]]:
    """Como extract(), pero ademas devuelve cuantos candidatos se
    descartaron por estar fuera de rango, por analito. Pensada para
    diagnostico y medicion de cobertura (Step 5); no es parte de la
    interfaz minima del modulo (`Lab`, `extract`, `ANALITOS`).
    """
    if not texto:
        return [], [], {}
    candidatos_t, spans, revisar_t = _de_tablas(texto)
    candidatos_x, revisar_x = _de_texto(texto, spans)
    labs, revisar_rango, rechazos = _filtrar_rango(candidatos_t + candidatos_x)
    return labs, revisar_t + revisar_x + revisar_rango, rechazos
