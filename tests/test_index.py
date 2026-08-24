import pytest
from mcp_drapp.corpus import PacienteCorpus
from mcp_drapp.index import (AUTORES, cohort, construir, estado, find_patient,
                             get_patient, lab_series, search_records)


def _p(cid, apellido, nombre, dni, evos):
    return PacienteCorpus(cid,
        {"consumerId": cid, "lastName": apellido, "firstName": nombre,
         "dni": dni, "dob": "1980-05-05"},
        {"evoluciones": evos})


def _evo(rid, fecha, contenido, autor="Maru anselmi"):
    return {"id": rid, "date": fecha, "content": contenido, "createdByName": autor,
            "createdAt": 1, "updatedAt": 1}


@pytest.fixture
def db(tmp_path):
    ruta = tmp_path / "i.db"
    construir(ruta, [
        _p("a1", "Perez Test", "Juan", "99000001", [
            _evo("records/1", "2024-09-02", "<p>MC seguimiento hipotirodismo</p>"),
            _evo("records/2", "2025-11-10", "<p>PA 97.5 inicio wegovy</p>",
                 "Anselmi, MARIA EUGENIA"),
        ]),
        _p("b2", "Gómez Test", "Ana", "99000002", [
            _evo("records/3", "2020-01-05", "<p>control anual sin novedades</p>"),
        ]),
    ])
    return ruta


def test_construir_reporta_conteos(db):
    e = estado(db)
    assert e["n_patients"] == 2
    assert e["n_records"] == 3


def test_find_patient_por_apellido_sin_acento(db):
    assert find_patient(db, "gomez")[0]["consumer_id"] == "b2"


def test_find_patient_por_dni(db):
    assert find_patient(db, "99000001")[0]["consumer_id"] == "a1"


def test_get_patient_devuelve_registros_cronologicos(db):
    r = get_patient(db, consumer_id="a1")
    assert [x["record_id"] for x in r["records"]] == ["records/1", "records/2"]
    assert r["patient"]["dni"] == "99000001"


def test_search_records_encuentra_y_trae_procedencia(db):
    res = search_records(db, "hipotirodismo")
    assert len(res) == 1
    assert res[0]["consumer_id"] == "a1"
    assert res[0]["date"] == "2024-09-02"
    assert "snippet" in res[0]


def test_search_records_ignora_acentos(db):
    """La paciente se llama Gómez; buscar sin acento tiene que encontrarla."""
    res = search_records(db, "gomez")
    assert len(res) >= 1
    assert res[0]["consumer_id"] == "b2"


def test_autores_se_unifican(db):
    res = search_records(db, "wegovy")
    assert res[0]["author"] == AUTORES["anselmi, maria eugenia"]


def test_cohort_sin_visitas_desde(db):
    r = cohort(db, sin_visitas_desde="2023-01-01")
    assert [x["consumer_id"] for x in r] == ["b2"]


def test_cohort_contiene(db):
    r = cohort(db, contiene="wegovy")
    assert [x["consumer_id"] for x in r] == ["a1"]
    assert r[0]["motivo"]


def test_lab_series_incluye_snippet_y_source(db):
    s = lab_series(db, consumer_id="a1")
    peso = s["series"]["peso"]
    assert peso[0]["value"] == 97.5
    assert peso[0]["snippet"]
    assert peso[0]["source"] in ("texto", "tabla")


def test_lab_series_declara_cobertura(db):
    s = lab_series(db, consumer_id="a1")
    assert s["cobertura"]["evoluciones_totales"] == 2
    assert s["cobertura"]["con_labs"] == 1


# --- Normalizacion de fechas: 241 evoluciones del corpus traen timestamp ISO ---

def test_fecha_iso_con_hora_se_normaliza(tmp_path):
    ruta = tmp_path / "i.db"
    construir(ruta, [_p("a1", "Test", "Uno", "111", [
        _evo("records/1", "2021-09-02T21:01:05.098Z", "<p>x</p>"),
    ])])
    r = get_patient(ruta, consumer_id="a1")
    assert r["records"][0]["date"] == "2021-09-02"
    assert r["patient"]["last_visit"] == "2021-09-02"
    assert r["patient"]["first_visit"] == "2021-09-02"


def test_filtro_hasta_incluye_el_mismo_dia(tmp_path):
    """Antes del fix el registro quedaba fuera de su propio dia:
    '2026-06-12T10:00:00.000Z' <= '2026-06-12' es False."""
    ruta = tmp_path / "i.db"
    construir(ruta, [_p("a1", "Test", "Uno", "111", [
        _evo("records/1", "2026-06-12T10:00:00.000Z", "<p>x</p>"),
    ])])
    assert len(get_patient(ruta, consumer_id="a1", hasta="2026-06-12")["records"]) == 1


def test_fecha_invalida_no_rompe(tmp_path):
    ruta = tmp_path / "i.db"
    construir(ruta, [_p("a1", "Test", "Uno", "111", [
        _evo("records/1", "sin fecha", "<p>x</p>"),
    ])])
    assert get_patient(ruta, consumer_id="a1")["records"][0]["date"] is None


# --- cohort: filtro alta_entre (fecha de alta del paciente en drapp) ---

def _pf(cid, apellido, dni, alta, evos):
    """Paciente con fecha de alta, para probar alta_entre."""
    return PacienteCorpus(cid,
        {"consumerId": cid, "lastName": apellido, "firstName": "X",
         "dni": dni, "dob": "1980-01-01", "createdAt": alta},
        {"evoluciones": evos})


def test_cohort_alta_entre(tmp_path):
    ruta = tmp_path / "i.db"
    construir(ruta, [
        _pf("a1", "Vieja", "111", "2021-03-15T10:00:00.000Z", []),
        _pf("b2", "Nueva", "222", "2026-08-16T10:00:00.000Z", []),
    ])
    r = cohort(ruta, alta_entre=["2026-01-01", "2026-12-31"], limit=50)
    assert [x["consumer_id"] for x in r] == ["b2"]
    assert "alta entre" in r[0]["motivo"]


def test_cohort_alta_entre_se_combina_con_otros_criterios(tmp_path):
    ruta = tmp_path / "i.db"
    construir(ruta, [
        _pf("a1", "Uno", "111", "2026-02-01T00:00:00.000Z",
            [_evo("records/1", "2026-02-02", "<p>inicia wegovy</p>")]),
        _pf("b2", "Dos", "222", "2026-02-01T00:00:00.000Z",
            [_evo("records/2", "2026-02-02", "<p>control anual</p>")]),
    ])
    r = cohort(ruta, contiene="wegovy", alta_entre=["2026-01-01", "2026-12-31"], limit=50)
    assert [x["consumer_id"] for x in r] == ["a1"]


def test_alta_en_formato_iso_se_normaliza(tmp_path):
    ruta = tmp_path / "i.db"
    construir(ruta, [_pf("a1", "Uno", "111", "2026-02-01T13:41:18.942Z", [])])
    r = cohort(ruta, alta_entre=["2026-02-01", "2026-02-01"], limit=50)
    assert len(r) == 1, "la fecha de alta con hora tiene que caer dentro de su propio dia"


# --- Adjuntos indexados y consultas con sintaxis FTS accidental ---

def test_texto_de_adjunto_se_indexa_y_se_encuentra(tmp_path, monkeypatch):
    """El contenido del adjunto (capa PDF u OCR) tiene que ser buscable, no
    solo el nombre del archivo."""
    from mcp_drapp import index as mod
    monkeypatch.setattr(mod, "leer_texto",
                        lambda cid, rid: "TIROTROFINA TSH 3,23 uUI/ml"
                        if rid == "arch1" else "")
    ruta = tmp_path / "i.db"
    construir(ruta, [PacienteCorpus("a1",
        {"consumerId": "a1", "lastName": "Uno", "firstName": "X",
         "dni": "111", "dob": "1980-01-01"},
        {"archivos": [{"id": "records/arch1", "date": "2026-05-07",
                       "name": "lab.pdf", "createdAt": 1, "updatedAt": 1}]})])
    r = search_records(ruta, "tirotrofina", section="archivos")
    assert len(r) == 1 and r[0]["consumer_id"] == "a1"
    assert search_records(ruta, "lab.pdf", section="archivos"), "el nombre tambien"


def test_consulta_con_guion_no_rompe(db):
    """`bi-rads`, `HOMA-IR`, `25-OH`: el guion es sintaxis en FTS5 y hacia
    fallar la consulta con 'no such column'."""
    for q in ("bi-rads", "HOMA-IR", "25-OH", "algo-inexistente-xyz"):
        assert isinstance(search_records(db, q, section=None), list), q


def test_sintaxis_fts_valida_sigue_funcionando(db):
    """La tolerancia no debe romper las consultas bien formadas."""
    assert isinstance(search_records(db, "wegovy OR hipotirodismo", section=None), list)
    assert isinstance(search_records(db, '"seguimiento hipotirodismo"', section=None), list)
