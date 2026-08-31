"""Tests de la agenda.

Los eventos de ejemplo reproducen la forma real que devuelve drapp, incluida
la mezcla de turnos con bloqueos (type == "lock") que fue el hallazgo que
motivo el filtro. Los pacientes son ficticios.
"""
from datetime import datetime

import pytest

from mcp_drapp import agenda, api


def turno(**kw):
    base = {
        "id": "events/aaa111", "type": "appointment", "day": "2026-09-15",
        "time": "10:20", "duration": 30, "status": "booked", "deleted": False,
        "remote": False,
        "resource": {"id": "resources/r1", "label": "Anselmi, Maria Eugenia"},
        "service": {"id": "services/s1", "label": "Endocrinologia / Consulta"},
        "consumer": {"id": "consumers/c1", "label": "Perez, Juana",
                     "identification": "11111111", "phones": "+54 9 11 1234"},
    }
    base.update(kw)
    return base


BLOQUEO = {"id": "events/lock1", "type": "lock", "day": "2026-09-15",
           "time": "08:00", "duration": 60, "status": "booked"}


# --- ventana de tiempo -------------------------------------------------

def test_ms_usa_medianoche_local():
    assert agenda._ms("2026-09-15") == int(
        datetime(2026, 9, 15).timestamp() * 1000)


def test_ms_fin_del_dia_cubre_hasta_el_ultimo_milisegundo():
    ini, fin = agenda._ms("2026-09-15"), agenda._ms("2026-09-15", True)
    assert fin - ini == 86_399_999


def test_un_solo_dia_incluye_sus_turnos(monkeypatch):
    monkeypatch.setattr(api, "consultar_eventos",
                        lambda a, b: [turno(day="2026-09-15", time="23:59")])
    assert agenda.consultar("2026-09-15", "2026-09-15")["total"] == 1


def test_se_pide_un_dia_de_margen_a_cada_lado(monkeypatch):
    """La ventana del servidor filtra por fecha UTC y se desborda; se compensa
    pidiendo de mas y recortando despues contra 'day'."""
    visto = {}
    monkeypatch.setattr(api, "consultar_eventos",
                        lambda a, b: visto.update(rango=(a, b)) or [])
    agenda.consultar("2026-09-15", "2026-09-15")
    ini, fin = visto["rango"]
    assert ini == agenda._ms("2026-09-14")
    assert fin == agenda._ms("2026-09-16", fin_del_dia=True)


# --- la regresion que motivo el recorte propio ------------------------

def test_no_se_cuelan_los_turnos_de_manana(monkeypatch):
    """Bug real: al pedir el 2026-08-30 el servidor devolvia 12 eventos, los
    12 del 31/8, porque su ventana filtra por fecha UTC y desde UTC-3 el fin
    del dia local cae en el dia siguiente. La herramienta habria informado
    turnos de manana como si fueran de hoy."""
    monkeypatch.setattr(api, "consultar_eventos", lambda a, b: [
        turno(id="events/hoy", day="2026-08-30", time="09:00"),
        turno(id="events/man", day="2026-08-31", time="09:00"),
        turno(id="events/ayer", day="2026-08-29", time="09:00")])
    r = agenda.consultar("2026-08-30", "2026-08-30")
    assert [t["event_id"] for t in r["turnos"]] == ["hoy"]
    assert r["descartados_fuera_de_rango"] == 2


def test_un_dia_vacio_se_informa_vacio(monkeypatch):
    """El mismo bug, en su forma mas enganosa: el dia real no tenia ningun
    turno y la herramienta reportaba seis."""
    monkeypatch.setattr(api, "consultar_eventos",
                        lambda a, b: [turno(day="2026-08-31")] * 6)
    r = agenda.consultar("2026-08-30", "2026-08-30")
    assert r["total"] == 0 and r["por_dia"] == {}


def test_el_rango_es_inclusivo_en_los_dos_extremos(monkeypatch):
    monkeypatch.setattr(api, "consultar_eventos", lambda a, b: [
        turno(id="events/a", day="2026-09-01"),
        turno(id="events/b", day="2026-09-30"),
        turno(id="events/c", day="2026-10-01")])
    r = agenda.consultar("2026-09-01", "2026-09-30")
    assert [t["event_id"] for t in r["turnos"]] == ["a", "b"]


# --- el hallazgo: bloqueos mezclados con turnos ------------------------

def test_los_bloqueos_no_son_turnos(monkeypatch):
    monkeypatch.setattr(api, "consultar_eventos",
                        lambda a, b: [turno(), BLOQUEO])
    r = agenda.consultar("2026-09-01", "2026-09-30")
    assert r["total"] == 1
    assert r["descartados_no_turno"] == 1


def test_los_bloqueos_se_pueden_pedir(monkeypatch):
    monkeypatch.setattr(api, "consultar_eventos",
                        lambda a, b: [turno(), BLOQUEO])
    r = agenda.consultar("2026-09-01", "2026-09-30", incluir_bloqueos=True)
    assert r["total"] == 2


# --- filtros -----------------------------------------------------------

def test_cancelados_y_ausentes_quedan_fuera_por_defecto(monkeypatch):
    monkeypatch.setattr(api, "consultar_eventos", lambda a, b: [
        turno(), turno(id="events/b", status="cancelled"),
        turno(id="events/c", status="noshow")])
    assert agenda.consultar("2026-09-01", "2026-09-30")["total"] == 1


def test_cancelados_se_pueden_pedir(monkeypatch):
    monkeypatch.setattr(api, "consultar_eventos", lambda a, b: [
        turno(), turno(id="events/b", status="cancelled")])
    r = agenda.consultar("2026-09-01", "2026-09-30", incluir_cancelados=True)
    assert r["total"] == 2
    assert [t["vigente"] for t in r["turnos"]] == [True, False]


def test_los_borrados_nunca_aparecen(monkeypatch):
    monkeypatch.setattr(api, "consultar_eventos",
                        lambda a, b: [turno(deleted=True)])
    r = agenda.consultar("2026-09-01", "2026-09-30", incluir_cancelados=True)
    assert r["total"] == 0


def test_filtro_por_profesional_ignora_tildes_y_mayusculas(monkeypatch):
    monkeypatch.setattr(api, "consultar_eventos", lambda a, b: [
        turno(), turno(id="events/b",
                       resource={"id": "resources/r2", "label": "Vazquez, Virginia"})])
    r = agenda.consultar("2026-09-01", "2026-09-30", profesional="vázquez")
    assert r["total"] == 1
    assert r["turnos"][0]["profesional"] == "Vazquez, Virginia"


# --- normalizacion -----------------------------------------------------

def test_normalizar_extrae_los_campos_utiles():
    t = agenda.normalizar(turno())
    assert t["fecha"] == "2026-09-15" and t["hora"] == "10:20"
    assert t["duracion_min"] == 30
    assert t["estado"] == "reservado" and t["estado_crudo"] == "booked"
    assert t["profesional"] == "Anselmi, Maria Eugenia"
    assert t["paciente"]["consumer_id"] == "c1"
    assert t["paciente"]["dni"] == "11111111"
    assert t["event_id"] == "aaa111"


def test_un_estado_desconocido_se_devuelve_crudo():
    t = agenda.normalizar(turno(status="loquesea"))
    assert t["estado"] == "loquesea" and t["vigente"] is True


def test_evento_sin_paciente_no_rompe():
    t = agenda.normalizar({"id": "events/x", "status": "booked"})
    assert t["paciente"]["consumer_id"] is None


# --- orden y agrupacion ------------------------------------------------

def test_los_turnos_salen_en_orden_cronologico(monkeypatch):
    monkeypatch.setattr(api, "consultar_eventos", lambda a, b: [
        turno(id="events/2", day="2026-09-16", time="09:00"),
        turno(id="events/3", day="2026-09-15", time="15:00"),
        turno(id="events/1", day="2026-09-15", time="08:00")])
    r = agenda.consultar("2026-09-01", "2026-09-30")
    assert [t["event_id"] for t in r["turnos"]] == ["1", "3", "2"]
    assert r["por_dia"] == {"2026-09-15": 2, "2026-09-16": 1}


# --- por paciente ------------------------------------------------------

def test_de_paciente_separa_proximo_y_ultimo(monkeypatch):
    monkeypatch.setattr(api, "eventos_de", lambda cid: {
        "next": [turno(id="events/f2", day="2026-10-01"),
                 turno(id="events/f1", day="2026-09-15")],
        "past": [turno(id="events/p1", day="2026-01-10", status="fulfilled"),
                 turno(id="events/p2", day="2026-06-10", status="fulfilled")]})
    r = agenda.de_paciente("c1")
    assert r["proximo"]["fecha"] == "2026-09-15"
    assert r["ultimo"]["fecha"] == "2026-06-10"
    assert len(r["futuros"]) == 2 and len(r["pasados"]) == 2


def test_de_paciente_sin_turnos(monkeypatch):
    monkeypatch.setattr(api, "eventos_de", lambda cid: {"next": [], "past": []})
    r = agenda.de_paciente("c1")
    assert r["proximo"] is None and r["ultimo"] is None


# --- la garantia de solo lectura ---------------------------------------

def test_la_lista_blanca_crecio_de_forma_deliberada():
    assert set(api.POST_PERMITIDOS) == {"search/consumers", "events/query"}


def test_events_query_sigue_pasando_por_la_lista_blanca():
    with pytest.raises(ValueError, match="POST_PERMITIDOS"):
        api.buscar("events/create", {})


def test_consultar_eventos_manda_el_body_que_espera_drapp(monkeypatch):
    visto = {}

    def falso(ruta, body, **kw):
        visto.update(ruta=ruta, body=body)
        return []

    monkeypatch.setattr(api, "buscar", falso)
    api.consultar_eventos(1000, 2000)
    assert visto["ruta"] == "events/query"
    # sin estos dos flags el servidor esconde cancelados y ausentes
    assert visto["body"] == {"cancelled": True, "noshow": True,
                             "startsAt": 1000, "endsAt": 2000}


def test_consultar_eventos_tolera_una_respuesta_inesperada(monkeypatch):
    monkeypatch.setattr(api, "buscar", lambda r, b, **k: {"error": "x"})
    assert api.consultar_eventos(1, 2) == []
