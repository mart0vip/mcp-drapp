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
