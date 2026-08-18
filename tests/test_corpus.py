import json
from mcp_drapp.corpus import PacienteCorpus, cargar, diff


def _escribir(d, cid, records):
    (d / f"{cid}.json").write_text(json.dumps({
        "patient": {"consumerId": cid, "firstName": "A", "lastName": "B",
                    "dni": "1", "dob": "1990-01-01"},
        "sections": {"evoluciones": records, "stats": {"events": 0, "records": len(records)}},
    }), encoding="utf-8")


def test_cargar_lee_pacientes(tmp_path):
    _escribir(tmp_path, "abc", [{"id": "records/1", "date": "2024-01-01", "updatedAt": 10}])
    ps = cargar(tmp_path)
    assert len(ps) == 1
    assert ps[0].consumer_id == "abc"
    assert ps[0].sections["evoluciones"][0]["id"] == "records/1"


def test_diff_detecta_paciente_nuevo(tmp_path):
    _escribir(tmp_path, "abc", [])
    viejo = cargar(tmp_path)
    _escribir(tmp_path, "xyz", [])
    d = diff(viejo, cargar(tmp_path))
    assert d["pacientes_nuevos"] == ["xyz"]


def test_diff_detecta_registro_nuevo_y_modificado(tmp_path):
    _escribir(tmp_path, "abc", [{"id": "records/1", "date": "2024-01-01", "updatedAt": 10}])
    viejo = cargar(tmp_path)
    _escribir(tmp_path, "abc", [
        {"id": "records/1", "date": "2024-01-01", "updatedAt": 99},
        {"id": "records/2", "date": "2024-02-01", "updatedAt": 20},
    ])
    d = diff(viejo, cargar(tmp_path))
    assert d["registros_nuevos"] == ["records/2"]
    assert d["registros_modificados"] == ["records/1"]


def test_corpus_real_carga(corpus_dir):
    ps = cargar(corpus_dir)
    assert len(ps) > 1000
    assert all(p.consumer_id for p in ps)
