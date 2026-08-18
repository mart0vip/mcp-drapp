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
        _p("a1", "Perez Test", "Julian", "99000001", [
            _evo("records/1", "2024-09-02", "<p>MC seguimiento hipotirodismo</p>"),
            _evo("records/2", "2025-11-10", "<p>PA 97.5 inicio wegovy</p>",
                 "Anselmi, MARIA EUGENIA"),
        ]),
        _p("b2", "Gómez", "Ana", "30111222", [
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
