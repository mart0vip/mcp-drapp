from mcp_drapp.labs import Lab, extract


def test_PA_es_peso_no_presion_arterial():
    """Regla de la casa confirmada 2026-08-18. Ver spec seccion 6."""
    labs, _ = extract("PA 108.6")
    assert len(labs) == 1
    assert labs[0].analyte == "peso"
    assert labs[0].value == 108.6
    assert labs[0].unit == "kg"
    assert all(l.analyte != "presion_arterial" for l in labs)


def test_todo_valor_trae_snippet_y_source():
    labs, _ = extract("Lab 9-9-24: COL T 153 - HDL 33 - LDL 71 - TSH 4.83")
    assert labs, "deberia detectar analitos"
    for l in labs:
        assert l.snippet, "ningun valor puede venir sin su fragmento original"
        assert l.source in ("texto", "tabla")


def test_errata_hba2c_se_mapea_a_hba1c():
    labs, _ = extract("hba2c 5.3")
    assert [l.analyte for l in labs] == ["hba1c"]
    assert labs[0].value == 5.3


def test_extrae_de_tabla_markdown_con_alta_confianza():
    texto = (
        "| Parámetro | Resultado |\n|---|---|\n"
        "| Glucemia | 88 mg/dL |\n| HbA1c | 5.4 % |\n"
    )
    labs, _ = extract(texto)
    por = {l.analyte: l for l in labs}
    assert por["glucemia"].value == 88
    assert por["glucemia"].source == "tabla"
    assert por["hba1c"].value == 5.4


def test_token_desconocido_va_a_revisar_y_no_se_adivina():
    """Caso real: 'tsdh 3.64' aparece junto a shbg y no esta claro que es."""
    labs, revisar = extract("shbg 17 tsdh 3.64")
    assert any("tsdh" in r.lower() for r in revisar)
    assert all(l.analyte != "tsdh" for l in labs)


def test_coma_decimal():
    labs, _ = extract("uric 6,7")
    assert labs[0].value == 6.7


def test_texto_sin_labs():
    labs, revisar = extract("El paciente refiere astenia y mala calidad del sueño.")
    assert labs == []


def test_tabla_multi_fecha_no_extrae_y_manda_a_revisar():
    """CORRECCION 2026-08-18: el corpus real tiene tablas de laboratorio con
    varias columnas de fecha (una visita por columna), por ejemplo:

        | Parametro | 20/06/2024 | 04/03/2025 | Valores de Referencia |
        |---|---|---|---|
        | Glucemia | 91 mg/dL | 114 mg/dL | 74-100 mg/dL |

    Tomar celdas[1] como "el" valor le asignaria a la evolucion actual el
    resultado de junio 2024: un dato falso y ademas plausible, lo que viola
    la regla de no adivinar. Cuando el encabezado tiene mas de una columna
    con pinta de fecha, la columna de valor deja de ser inequivoca: no se
    extrae ningun Lab de esa tabla y cada fila de datos va a `revisar` con
    su texto original.
    """
    texto = (
        "| Parámetro | 20/06/2024 | 04/03/2025 | Valores de Referencia |\n"
        "|---|---|---|---|\n"
        "| Glucemia | 91 mg/dL | 114 mg/dL | 74-100 mg/dL |\n"
    )
    labs, revisar = extract(texto)

    assert all(l.analyte != "glucemia" for l in labs), (
        "no debe emitirse un Lab con el valor de una columna de fecha"
    )
    assert not any(l.value in (91, 114) for l in labs)
    assert any("glucemia" in r.lower() for r in revisar)
    assert any("91" in r and "114" in r for r in revisar)


def test_ano_no_se_confunde_con_valor():
    """El corpus tenia HOMA=2024, vitamina_d=2024: eran años, no resultados."""
    labs, revisar = extract("homa 2024")
    assert all(l.analyte != "homa" for l in labs)
    assert any("2024" in r for r in revisar)


def test_valor_fuera_de_rango_va_a_revisar_con_snippet():
    labs, revisar = extract("hba1c 663")
    assert labs == []
    assert any("663" in r for r in revisar)


def test_valor_dentro_de_rango_se_emite_normal():
    labs, _ = extract("hba1c 5.4")
    assert len(labs) == 1 and labs[0].value == 5.4


def test_t4_solo_es_dosis_no_resultado():
    """Confirmado por la medica: 'T4 100' son mcg de levotiroxina, no T4 libre."""
    labs, revisar = extract("T4 100")
    assert all(l.analyte != "t4l" for l in labs)


def test_t4_libre_si_es_resultado():
    for txt in ("T4L 1.3", "T4 libre 1.3", "t4 l 1.3"):
        labs, _ = extract(txt)
        assert any(l.analyte == "t4l" and l.value == 1.3 for l in labs), txt


def test_PA_en_contexto_de_MAPA_no_es_peso():
    """Excepcion real del corpus: en un MAPA, PA si es presion arterial."""
    labs, _ = extract("Promedio de PA 24 h: 119/73 mmHg")
    assert all(l.analyte != "peso" for l in labs)


def test_PA_sigue_siendo_peso_en_contexto_normal():
    labs, _ = extract("PA 108.6")
    assert len(labs) == 1 and labs[0].analyte == "peso" and labs[0].value == 108.6


def test_PA_con_fecha_cerca_no_se_confunde_con_MAPA():
    """Bug encontrado al medir contra el corpus real (ronda 2): una fecha
    DD/MM cerca (omnipresente en estas notas) tiene la misma forma "NN/NN"
    que una sistole/diastole y disparaba la excepcion MAPA por error,
    perdiendo un peso real. Casos reales: 'PA 86,9 kg' cerca de '31/08',
    'pa 64 kg' cerca de '22/01/2026'."""
    labs, _ = extract("ya que tiene HTA.\n\nPA 86,9 kg\n\nProximo control 31/08")
    assert any(l.analyte == "peso" and l.value == 86.9 for l in labs)

    labs2, _ = extract("pa 64 kg\n\nLABORATORIO 22/01/2026")
    assert any(l.analyte == "peso" and l.value == 64 for l in labs2)


def test_hb_no_pisa_hba1c():
    labs, _ = extract("hba1c 5.4 - HB 13.4 - HTO 41.3")
    por = {l.analyte: l.value for l in labs}
    assert por["hba1c"] == 5.4
    assert por["hemoglobina"] == 13.4
    assert por["hematocrito"] == 41.3


def test_tag_es_trigliceridos():
    labs, _ = extract("TAG 197")
    assert [l.analyte for l in labs] == ["trigliceridos"]


# --- Ronda 3: hallazgos de la revision independiente, verificados contra el corpus ---

def test_tabla_multi_fecha_con_encabezado_en_negrita():
    """El caso que rompia en produccion (data/hce/28d12c3e.json).

    html2text envuelve todo <th> en **negrita**, asi que el encabezado real
    llega como `**20/06/2024**`. El test anterior usaba encabezados SIN
    negrita -- una forma que no existe en el pipeline -- y por eso la
    proteccion de tablas multi-fecha nunca se ejercitaba de verdad.

    En la evolucion real, fechada 2025-03-11, se emitia glucemia=91 (la
    columna de junio 2024) cuando el valor de esa fecha era 114.
    """
    texto = (
        "| **Parámetro** | **20/06/2024** | **04/03/2025** | **Valores de Referencia** |\n"
        "|---|---|---|---|\n"
        "| **Glucemia** | 91 mg/dL | 114 mg/dL | 74-100 mg/dL |\n"
        "| **Insulina** | 8.4 µUI/mL | 9.5 µUI/mL | 2.6-24.6 µUI/mL |\n"
    )
    labs, revisar = extract(texto)
    assert all(l.analyte not in ("glucemia", "insulina") for l in labs)
    assert not any(l.value in (91, 8.4) for l in labs)
    assert any("Glucemia" in r for r in revisar)


def test_no_hdl_y_razones_no_se_emiten_como_hdl():
    """Caso real: una sola nota emitia tres HDL, dos falsos."""
    texto = ("Lipidos: LDL 90 mg/dl, HDL 34 mg/dl (bajo), TG 292 mg/dl, "
             "CT 182, no-HDL 148, CT/HDL 5,4 (alto).")
    labs, revisar = extract(texto)
    hdl = [l.value for l in labs if l.analyte == "hdl"]
    assert hdl == [34.0], f"solo el HDL real; se obtuvo {hdl}"
    assert any("148" in r for r in revisar)
    assert any("5,4" in r for r in revisar)


def test_razon_tg_hdl_tampoco_se_emite():
    labs, _ = extract("TG/HDL: 1,54")
    assert all(l.analyte != "hdl" for l in labs)


def test_fila_de_tabla_no_reconocida_va_a_revisar():
    """Regla 2: nada se descarta en silencio, tampoco en tablas.

    Antes, 1132 filas del corpus (creatinina, homocisteina, colesterol
    hdl/ldl) desaparecian sin quedar ni en labs ni en revisar. Ronda 3
    (2026-08-18): creatinina y homocisteina pasaron a ser analitos
    reconocidos (ver test_creatinina_se_extrae y
    test_homocisteina_se_extrae), asi que este ejemplo se actualizo a dos
    etiquetas que siguen sin reconocerse: testosterona total (dos unidades
    sin normalizar en el corpus real, se deja en revisar a proposito) y
    plaquetas (no pedida en esta ronda).
    """
    texto = ("| Parámetro | Resultado |\n|---|---|\n"
             "| Testosterona total | 6.7 ng/mL |\n| Plaquetas | 250 x10e3/µL |\n")
    labs, revisar = extract(texto)
    assert all(l.analyte not in ("testosterona_total", "plaquetas") for l in labs)
    assert any("Testosterona" in r for r in revisar)
    assert any("Plaquetas" in r for r in revisar)


def test_glucosa_es_glucemia():
    """27 apariciones reales de 'Glucosa: NN mg/dL' que se perdian."""
    labs, _ = extract("Glucosa: 85 mg/dL")
    assert [(l.analyte, l.value) for l in labs] == [("glucemia", 85.0)]


def test_anio_antes_del_valor_toma_el_valor_real():
    """`Ferritina 2024: 10,7` -> el 2024 es el año de la nota.

    Antes se emitia ferritina=2024 y el 10,7 desaparecia por completo.
    """
    labs, _ = extract("**Ferritina 2024:** 10,7 ng/mL (ya baja).")
    fe = [l for l in labs if l.analyte == "ferritina"]
    assert len(fe) == 1
    assert fe[0].value == 10.7
    assert "10,7" in fe[0].snippet


# --- Ronda 3 (2026-08-18): analitos aprobados por la medica, medidos contra
# el corpus real (1569 historias, 3957 evoluciones). Cuatro etiquetas son
# sinonimos de analitos existentes (fusiones); el resto son analitos nuevos.

def test_colesterol_hdl_es_hdl():
    """'colesterol hdl' es sinonimo de hdl, no un analito nuevo."""
    labs, _ = extract("colesterol hdl 55")
    assert [(l.analyte, l.value) for l in labs] == [("hdl", 55.0)]


def test_colesterol_ldl_es_ldl():
    """'colesterol ldl' es sinonimo de ldl, no un analito nuevo."""
    labs, _ = extract("colesterol ldl 126")
    assert [(l.analyte, l.value) for l in labs] == [("ldl", 126.0)]


def test_acido_urico_es_uricemia():
    """'ácido úrico'/'acido urico' son sinonimos de uricemia, no un analito nuevo."""
    for txt in ("ácido úrico 4.4", "acido urico 4.4"):
        labs, _ = extract(txt)
        assert [(l.analyte, l.value) for l in labs] == [("uricemia", 4.4)], txt


def test_creatininemia_es_creatinina():
    """'creatininemia' es sinonimo de creatinina, no un analito nuevo."""
    labs, _ = extract("creatininemia 1.0")
    assert [(l.analyte, l.value) for l in labs] == [("creatinina", 1.0)]


def test_creatinina_se_extrae():
    labs, _ = extract("creatinina 0.9")
    assert [(l.analyte, l.value) for l in labs] == [("creatinina", 0.9)]


def test_homocisteina_se_extrae():
    for txt in ("homocisteina 9.8", "homocisteína 9.8"):
        labs, _ = extract(txt)
        assert [(l.analyte, l.value) for l in labs] == [("homocisteina", 9.8)], txt


def test_uremia_se_extrae_y_urea_no_pisa_uremia():
    """'urea' y 'uremia' son dos patrones del mismo analito ('uremia');
    ninguno debe pisar al otro ni producir un analito distinto."""
    for txt in ("uremia 41", "urea 41"):
        labs, _ = extract(txt)
        assert [(l.analyte, l.value) for l in labs] == [("uremia", 41.0)], txt


def test_transferrina_se_extrae():
    labs, _ = extract("transferrina 248")
    assert [(l.analyte, l.value) for l in labs] == [("transferrina", 248.0)]


def test_ferremia_se_extrae():
    labs, _ = extract("ferremia 95")
    assert [(l.analyte, l.value) for l in labs] == [("ferremia", 95.0)]


def test_proteinas_totales_se_extrae():
    for txt in ("proteinas totales 6.8", "proteínas totales 6.8"):
        labs, _ = extract(txt)
        assert [(l.analyte, l.value) for l in labs] == [("proteinas_totales", 6.8)], txt


def test_albumina_se_extrae():
    for txt in ("albumina 4.5", "albúmina 4.5"):
        labs, _ = extract(txt)
        assert [(l.analyte, l.value) for l in labs] == [("albumina", 4.5)], txt


def test_magnesio_se_extrae_pero_no_el_patron_mg():
    """Se agrega 'magnesio' pero NO 'mg': verificado contra el corpus, "mg"
    como patron genera falsos positivos claros (dosis de medicacion, ej.
    'Lamotrigina 200 mg: 1 comprimido' capturaria magnesio=1, un valor
    dentro del rango plausible que el filtro de rango no frena)."""
    labs, _ = extract("magnesio 2.3")
    assert [(l.analyte, l.value) for l in labs] == [("magnesio", 2.3)]

    labs2, revisar2 = extract("Lamotrigina 200 mg: 1 comprimido diario")
    assert all(l.analyte != "magnesio" for l in labs2)


def test_atpo_se_extrae():
    for txt in ("atpo 12.9", "anti-tpo 12.9", "anti tpo 12.9"):
        labs, _ = extract(txt)
        assert [(l.analyte, l.value) for l in labs] == [("atpo", 12.9)], txt


def test_eritrosedimentacion_se_extrae_esd_y_vsg_no_colisionan():
    """'esd' y 'vsg' son siglas cortas; verificado contra el corpus que no
    colisionan con otros tokens."""
    for txt in ("eritrosedimentacion 10", "eritrosedimentación 10", "esd 10", "vsg 10"):
        labs, _ = extract(txt)
        assert [(l.analyte, l.value) for l in labs] == [("eritrosedimentacion", 10.0)], txt


def test_vcm_se_extrae():
    labs, _ = extract("vcm 88")
    assert [(l.analyte, l.value) for l in labs] == [("vcm", 88.0)]


def test_chcm_se_extrae():
    labs, _ = extract("chcm 33.3")
    assert [(l.analyte, l.value) for l in labs] == [("chcm", 33.3)]


def test_eosinofilos_se_extrae():
    for txt in ("eosinofilos 4", "eosinófilos 4"):
        labs, _ = extract(txt)
        assert [(l.analyte, l.value) for l in labs] == [("eosinofilos", 4.0)], txt


def test_linfocitos_se_extrae():
    labs, _ = extract("linfocitos 32")
    assert [(l.analyte, l.value) for l in labs] == [("linfocitos", 32.0)]


def test_monocitos_se_extrae():
    labs, _ = extract("monocitos 7")
    assert [(l.analyte, l.value) for l in labs] == [("monocitos", 7.0)]


def test_basofilos_se_extrae():
    for txt in ("basofilos 1", "basófilos 1"):
        labs, _ = extract(txt)
        assert [(l.analyte, l.value) for l in labs] == [("basofilos", 1.0)], txt


def test_neutrofilos_se_extrae_incluido_segmentados():
    for txt in ("neutrofilos 57", "neutrófilos 57",
                "neutrófilos segmentados 57", "neutrofilos segmentados 57"):
        labs, _ = extract(txt)
        assert [(l.analyte, l.value) for l in labs] == [("neutrofilos", 57.0)], txt


def test_testosterona_total_no_se_agrega_queda_en_revisar():
    """Los valores reales del corpus van de 0.2 a 72.2: conviven dos
    unidades sin normalizar (ng/mL y ng/dL). No se agrega como analito;
    el valor sigue sin adivinarse (va a revisar via `_CANDIDATO`, que
    captura el token inmediatamente antes del numero: 'total 6.7')."""
    labs, revisar = extract("testosterona total 6.7")
    assert all(l.analyte != "testosterona_total" for l in labs)
    assert any("total" in r.lower() and "6.7" in r for r in revisar)


# --- Revision final: dos fallas de atribucion verificadas contra el corpus ---

def test_tabla_comparativa_con_encabezado_mes_anio():
    """Caso real (data/hce/4f6733ee.json, evolucion 2025-07-01).

    La deteccion de ambiguedad miraba la FORMA del encabezado (DD/MM/AAAA),
    asi que 'Ene 2025 | Jun 2025' la esquivaba y se emitia la columna vieja
    como si fuera actual: HDL 68 de enero en una evolucion de julio, cuando
    el valor real era 101 y la propia medica lo marco como llamativo.
    """
    texto = (
        "| Parámetro | Ene 2025 | Jun 2025 | Comentario |\n"
        "|---|---|---|---|\n"
        "| **Colesterol HDL** | 68 mg/dL | **101 mg/dL** | Aumento llamativo |\n"
    )
    labs, revisar = extract(texto)
    assert all(l.analyte != "hdl" for l in labs)
    assert not any(l.value in (68.0, 101.0) for l in labs)
    assert any("HDL" in r for r in revisar)


def test_tabla_comparativa_sin_unidades():
    """Caso real (data/hce/2dfa8b70.json): B12 1354 de feb-2023 se emitia en
    una evolucion de 2025; el valor reciente era 378."""
    texto = ("| Parámetro | Feb 2023 | Oct 2023 | Rango |\n|---|---|---|---|\n"
             "| Vitamina B12 | 1354 | 378 | 187–883 |\n")
    labs, revisar = extract(texto)
    assert all(l.analyte != "b12" for l in labs)
    assert any("1354" in r for r in revisar)


def test_tabla_sana_con_columna_de_referencia_sigue_funcionando():
    """La columna de referencia NO debe confundirse con una segunda columna
    de valor: '70-100' es un rango, no un resultado."""
    texto = ("| Parámetro | Resultado | Referencia | Interpretación |\n|---|---|---|---|\n"
             "| Glucemia | 88 mg/dL | 70-100 | Normal |\n"
             "| HbA1c | 5.4 % | <5.7 | Normal |\n"
             "| HOMA-IR | 2,2 | Hasta 2,5 | Límite |\n")
    labs, _ = extract(texto)
    por = {l.analyte: l.value for l in labs}
    assert por["glucemia"] == 88.0
    assert por["hba1c"] == 5.4
    assert por["homa"] == 2.2


def test_fila_con_valor_en_otra_columna_no_se_pierde():
    """Caso real: '| Vitamina D | *No se hizo* | 34,4 ng/mL | Suficiencia |'.
    El 34,4 desaparecia sin quedar ni en labs ni en revisar."""
    texto = ("| Parámetro | Ene | Jun | Estado |\n|---|---|---|---|\n"
             "| **Vitamina D** | *No se hizo* | 34,4 ng/mL | Suficiencia |\n")
    labs, revisar = extract(texto)
    assert all(l.analyte != "vitamina_d" for l in labs)
    assert any("34,4" in r for r in revisar), "el valor real tiene que quedar visible"
