import inspect
import re

import pytest
from mcp_drapp import api


def test_solo_existe_get():
    """Restriccion estructural: no debe haber ninguna operacion de escritura."""
    publicas = {n for n, _ in inspect.getmembers(api, inspect.isfunction)
                if not n.startswith("_")}
    assert "get" in publicas
    for prohibido in ("post", "put", "patch", "delete", "crear", "borrar", "actualizar"):
        assert prohibido not in publicas


def test_no_existen_verbos_de_modificacion():
    """PUT, PATCH y DELETE no deben existir: no hay forma de modificar drapp."""
    fuente = inspect.getsource(api)
    for verbo in ("PUT", "PATCH", "DELETE"):
        assert not re.search(rf'["\']{verbo}["\']', fuente), f"{verbo} presente en api.py"


def test_la_lista_blanca_de_post_es_exactamente_la_declarada():
    """Los POST permitidos son consultas que drapp no expone por GET.

    Agregar una ruta aca debilita la garantia de solo lectura: si este test
    falla, fue una decision deliberada o un descuido.

    - search/consumers: el padron de pacientes.
    - events/query: la agenda de turnos. Es la misma llamada que hace la app
      web al abrir el calendario; autorizada por el usuario el 2026-08-30.
    """
    assert set(api.POST_PERMITIDOS) == {"search/consumers", "events/query"}


def test_buscar_rechaza_rutas_fuera_de_la_lista_blanca():
    for ruta in ("consumers/abc", "records/_all", "consumers/abc/records",
                 "search/otra", ""):
        with pytest.raises(ValueError, match="POST_PERMITIDOS"):
            api.buscar(ruta, {})


def test_solo_buscar_puede_hacer_post():
    """Ningun otro punto del modulo arma un request con body."""
    fuente = inspect.getsource(api)
    cuerpo_buscar = inspect.getsource(api.buscar)
    afuera = fuente.replace(cuerpo_buscar, "")
    assert "data=" not in afuera, "hay un request con body fuera de buscar()"


def test_secciones_cubre_las_siete_mas_stats():
    assert set(api.SECCIONES) == {
        "evoluciones", "diagnosticos", "tratamientos", "signos_vitales",
        "archivos", "recetas", "laboratorios", "stats"}


def test_base_apunta_al_equipo_correcto():
    assert api.BASE == "https://api.drapp.la/teams/48b19010"


def test_buscar_ejecuta_el_camino_feliz(monkeypatch):
    """Los demas tests de este archivo son de inspeccion estatica y no
    ejecutan buscar(). Esa brecha dejo pasar un NameError en la linea del
    token que solo aparecia al llamarla de verdad."""
    llamadas = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'[{"id": "consumers/abc", "lastName": "Test"}]'

    def falso_urlopen(req, timeout=None):
        llamadas["url"] = req.full_url
        llamadas["metodo"] = req.get_method()
        llamadas["body"] = req.data
        return _Resp()

    monkeypatch.setattr(api, "_access_token", lambda: "tok-falso")
    monkeypatch.setattr(api.urllib.request, "urlopen", falso_urlopen)

    r = api.buscar("search/consumers", {"offset": 0})
    assert r == [{"id": "consumers/abc", "lastName": "Test"}]
    assert llamadas["metodo"] == "POST"
    assert llamadas["url"].endswith("/teams/48b19010/search/consumers")
    assert b'"offset": 0' in llamadas["body"]


def test_listar_consumers_pagina_y_normaliza(monkeypatch):
    """Recorre por offset hasta que deja de haber ids nuevos, saltea los
    borrados y devuelve el formato de data/patients.json."""
    paginas = [
        [{"id": "consumers/a", "firstName": "Ana", "lastName": "Uno",
          "identification": "111", "createdAt": "2026-01-01T00:00:00.000Z"},
         {"id": "consumers/b", "firstName": "Beto", "lastName": "Dos",
          "identification": "222", "createdAt": "2026-01-02T00:00:00.000Z"},
         {"id": "consumers/z", "lastName": "Borrado", "deleted": True}],
        [{"id": "consumers/c", "firstName": "Cala", "lastName": "Tres",
          "identification": "333", "createdAt": "2026-01-03T00:00:00.000Z"}],
        [],
    ]
    vistas = []

    def falso_buscar(path, body):
        vistas.append(body.get("offset"))
        return paginas.pop(0) if paginas else []

    monkeypatch.setattr(api, "buscar", falso_buscar)
    r = api.listar_consumers()

    assert [x["consumerId"] for x in r] == ["a", "b", "c"], "sin el borrado"
    assert r[0] == {"consumerId": "a", "firstName": "Ana", "lastName": "Uno",
                    "dni": "111", "createdAt": "2026-01-01T00:00:00.000Z"}
    assert vistas == [0, 3, 4], "avanza por offset segun lo recibido"


def test_createdAt_en_epoch_se_normaliza(monkeypatch):
    """La API devuelve la fecha de alta como epoch en milisegundos, el CSV
    como texto ISO. Las dos rutas tienen que producir lo mismo -- lo detecto
    un AttributeError contra datos reales, no los tests con datos inventados."""
    monkeypatch.setattr(api, "buscar", lambda p, b: (
        [{"id": "consumers/a", "firstName": "Ana", "lastName": "Uno",
          "identification": "111", "createdAt": 1735500000000}]
        if b.get("offset") == 0 else []))
    r = api.listar_consumers()
    assert r[0]["createdAt"].startswith("2024-12-"), r[0]["createdAt"]
