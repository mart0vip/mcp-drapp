import pytest
from mcp_drapp import server


@pytest.mark.asyncio
async def test_expone_las_nueve_herramientas():
    nombres = {t.name for t in await server.mcp.list_tools()}
    assert nombres == {"login", "status", "refresh", "find_patient",
                       "get_patient", "search_records", "cohort", "lab_series",
                       "agenda"}


@pytest.mark.asyncio
async def test_ninguna_herramienta_escribe_en_drapp():
    for t in await server.mcp.list_tools():
        desc = (t.description or "").lower()
        assert not any(v in desc for v in ("crea ", "modifica", "elimina", "escribe en drapp"))


def test_search_records_usa_evoluciones_por_defecto():
    import inspect
    p = inspect.signature(server.search_records).parameters
    assert p["section"].default == "evoluciones"


# --- refresh: el parametro `mode` ahora hace algo ---

def test_refresh_expone_mode_y_alta_entre():
    """Los dos huecos que marco la revision final: `mode` estaba documentado
    pero no se usaba, y `alta_entre` figuraba en el spec sin implementar."""
    import inspect
    pr = inspect.signature(server.refresh).parameters
    assert pr["mode"].default == "nuevos"
    assert "consumer_id" in pr
    assert "alta_entre" in inspect.signature(server.cohort).parameters


def test_refresh_usa_el_contador_para_saltear(monkeypatch, tmp_path):
    """En modo 'nuevos' solo se bajan las 8 secciones de quien cambio.

    El paciente sin cambios se resuelve con 1 request al contador; el que
    cambio, con el contador mas la descarga completa.
    """
    import json
    from mcp_drapp import corpus as mod_corpus

    corpus_dir = tmp_path / "hce"
    corpus_dir.mkdir()
    for cid, n in (("igual", 2), ("cambio", 2)):
        (corpus_dir / f"{cid}.json").write_text(json.dumps({
            "patient": {"consumerId": cid, "firstName": "A", "lastName": "B",
                        "dni": cid, "dob": "1990-01-01"},
            "sections": {"evoluciones": [
                {"id": f"records/{cid}{i}", "date": "2024-01-01", "content": "<p>x</p>",
                 "updatedAt": 1} for i in range(n)]},
        }), encoding="utf-8")

    monkeypatch.setattr(server, "CORPUS", corpus_dir)
    monkeypatch.setattr(server, "DB", tmp_path / "i.db")
    monkeypatch.setattr(server, "ROOT", tmp_path)   # sin patients.json -> usa el corpus

    contadores, descargas = [], []

    def falso_get(path):
        contadores.append(path)
        # 'cambio' declara 3 evoluciones contra las 2 locales
        return {"records": 3 if "cambio" in path else 2, "events": 0}

    def falsas_secciones(cid):
        descargas.append(cid)
        return {"evoluciones": [
            {"id": f"records/{cid}{i}", "date": "2024-01-01", "content": "<p>x</p>",
             "updatedAt": 1} for i in range(3)]}

    monkeypatch.setattr(server, "get", falso_get)
    monkeypatch.setattr(server, "secciones_de", falsas_secciones)
    # el padron se pide a drapp; en el test se sirve local para no salir a la red
    monkeypatch.setattr(server, "listar_consumers", lambda: [
        {"consumerId": "igual"}, {"consumerId": "cambio"}])

    r = server.refresh(mode="nuevos")

    assert len(contadores) == 2, "consulta el contador de cada paciente"
    assert descargas == ["cambio"], "solo baja al que cambio"
    assert r["revisados"] == 1
    assert r["errores"] == []


def test_refresh_reindexa_aunque_falle_una_descarga(monkeypatch, tmp_path):
    """Si una descarga falla, el indice igual se reconstruye: antes quedaba
    desincronizado del corpus sin que nadie lo notara."""
    import json
    corpus_dir = tmp_path / "hce"; corpus_dir.mkdir()
    (corpus_dir / "roto.json").write_text(json.dumps({
        "patient": {"consumerId": "roto", "firstName": "A", "lastName": "B",
                    "dni": "1", "dob": "1990-01-01"},
        "sections": {"evoluciones": []},
    }), encoding="utf-8")
    monkeypatch.setattr(server, "CORPUS", corpus_dir)
    monkeypatch.setattr(server, "DB", tmp_path / "i.db")
    monkeypatch.setattr(server, "ROOT", tmp_path)

    def explota(cid):
        raise RuntimeError("HTTP 500")
    monkeypatch.setattr(server, "secciones_de", explota)
    monkeypatch.setattr(server, "listar_consumers", lambda: [{"consumerId": "roto"}])

    r = server.refresh(mode="todos")
    assert len(r["errores"]) == 1
    assert "HTTP 500" in r["errores"][0]["error"]
    assert r["n_patients"] == 1, "el indice se reconstruyo igual"


def test_refresh_avisa_si_no_pudo_traer_el_padron(monkeypatch, tmp_path):
    """Si la enumeracion falla se usa la copia local y se avisa, en vez de
    aparentar que el padron esta al dia."""
    import json
    corpus_dir = tmp_path / "hce"; corpus_dir.mkdir()
    (corpus_dir / "uno.json").write_text(json.dumps({
        "patient": {"consumerId": "uno", "firstName": "A", "lastName": "B",
                    "dni": "1", "dob": "1990-01-01"},
        "sections": {"evoluciones": []},
    }), encoding="utf-8")
    monkeypatch.setattr(server, "CORPUS", corpus_dir)
    monkeypatch.setattr(server, "DB", tmp_path / "i.db")
    monkeypatch.setattr(server, "ROOT", tmp_path)

    def sin_red():
        raise RuntimeError("sin conexion")
    monkeypatch.setattr(server, "listar_consumers", sin_red)
    monkeypatch.setattr(server, "secciones_de", lambda cid: {"evoluciones": []})

    r = server.refresh(mode="todos")
    assert r["padron_al_dia"] is False
    assert r["n_patients"] == 1, "igual refresca lo que ya se tiene"


# --- agenda ------------------------------------------------------------

def test_agenda_sin_argumentos_pide_el_dia_de_hoy(monkeypatch):
    import datetime
    visto = {}
    monkeypatch.setattr(server._agenda, "consultar",
                        lambda *a: visto.update(args=a) or {"total": 0})
    server.agenda()
    hoy = datetime.date.today().isoformat()
    assert visto["args"][0] == hoy and visto["args"][1] == hoy


def test_agenda_con_desde_solo_devuelve_ese_dia(monkeypatch):
    visto = {}
    monkeypatch.setattr(server._agenda, "consultar",
                        lambda *a: visto.update(args=a) or {"total": 0})
    server.agenda(desde="2026-09-15")
    assert visto["args"][:2] == ("2026-09-15", "2026-09-15")


def test_agenda_excluye_cancelados_y_bloqueos_por_defecto(monkeypatch):
    visto = {}
    monkeypatch.setattr(server._agenda, "consultar",
                        lambda *a: visto.update(args=a) or {"total": 0})
    server.agenda(desde="2026-09-15", hasta="2026-09-16")
    assert visto["args"][3] is False and visto["args"][4] is False


# --- la ficha tiene que seguir andando sin conexion --------------------

def test_sin_sesion_la_ficha_se_devuelve_igual(monkeypatch):
    from mcp_drapp.auth import NecesitaLogin

    def cae(cid):
        raise NecesitaLogin("vencio")

    monkeypatch.setattr(server._agenda, "de_paciente", cae)
    r = server._turnos_de("c1")
    assert "login" in r["no_disponible"].lower()


def test_sin_internet_la_ficha_se_devuelve_igual(monkeypatch):
    def cae(cid):
        raise RuntimeError("Fallo tras 3 intentos: timeout")

    monkeypatch.setattr(server._agenda, "de_paciente", cae)
    r = server._turnos_de("c1")
    assert "no se pudo consultar la agenda" in r["no_disponible"].lower()


def test_los_turnos_se_pueden_apagar(monkeypatch):
    import inspect
    firma = inspect.signature(server.get_patient)
    assert firma.parameters["incluir_turnos"].default is True
