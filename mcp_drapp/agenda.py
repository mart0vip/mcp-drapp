"""Agenda de turnos de drapp. Solo lectura.

A diferencia del resto del MCP, que responde desde la copia local y funciona
sin internet, la agenda es dato vivo: siempre sale a la red y necesita sesion.
Por eso nunca se indexa ni se guarda en data/.

Tres cuidados que impone la forma real de los datos, medidos sobre los 4073
eventos del equipo entre 2025 y 2026:

1. El endpoint mezcla dos cosas. 813 de esos eventos son type == "lock":
   bloqueos de agenda, horas que la profesional cerro. No tienen paciente ni
   servicio y no son turnos. Se descartan salvo que se pidan expresamente.

2. Los flags 'cancelled' y 'noshow' del body significan "incluilos", y por
   omision el servidor los esconde. api.consultar_eventos() los pide siempre
   y el filtrado se hace aca, para que el resultado no dependa de un default
   ajeno.

3. El contador stats['events'] de la HCE NO sirve para contar turnos: dice 2
   para un paciente que tiene 1 futuro y 3 pasados. Se ignora.

Y un cuarto, que es el que mas duele si se ignora: la ventana startsAt/endsAt
del servidor NO delimita lo que uno pide. Filtra por fecha UTC, asi que desde
Argentina (UTC-3) el fin del dia local cae en el dia siguiente en UTC y el
servidor devuelve los turnos de manana. Pedir el 30/8 devolvia 12 eventos, los
12 del 31/8: la herramienta habria dicho "tenes 6 turnos hoy" cuando eran de
manana. Por eso la ventana se pide con un dia de margen a cada lado y el
recorte fino se hace aca contra el campo 'day', que es la fecha local de la
clinica -- lo que la profesional entiende por "los turnos del jueves".
"""
from datetime import datetime, timedelta

from . import api
from .index import norm

# Vocabulario observado en el corpus real. Los valores que no esten aca se
# devuelven tal cual vinieron: es preferible mostrar un estado crudo que
# inventarle un significado.
ESTADOS = {
    "booked": "reservado", "fulfilled": "atendido", "cancelled": "cancelado",
    "noshow": "ausente", "arrived": "en sala", "pending": "pendiente",
    "active": "activo",
}

# Un turno cuenta como "vigente" si no fue cancelado ni el paciente falto.
NO_VIGENTES = frozenset({"cancelled", "noshow"})


def _ms(f: str, fin_del_dia: bool = False, dias: int = 0) -> int:
    """'YYYY-MM-DD' a epoch en milisegundos, en la zona horaria local.

    'dias' corre el limite para pedir margen: la ventana del servidor no es de
    fiar (ver el punto 4 del encabezado) y se compensa pidiendo de mas.
    """
    d = datetime.strptime(f.strip(), "%Y-%m-%d") + timedelta(days=dias)
    if fin_del_dia:
        d = d + timedelta(days=1) - timedelta(milliseconds=1)
    return int(d.timestamp() * 1000)


def _paciente(e: dict) -> dict:
    c = e.get("consumer") or {}
    ident = c.get("id") or ""
    return {"consumer_id": ident.split("/")[-1] or None,
            "nombre": c.get("label"),
            "dni": c.get("identification") or None,
            "telefono": c.get("phones") or None}


def normalizar(e: dict) -> dict:
    """Un evento crudo de la API a la forma que devuelven las herramientas."""
    estado = e.get("status")
    return {
        "event_id": (e.get("id") or "").split("/")[-1] or None,
        "fecha": e.get("day"),
        "hora": e.get("time"),
        "duracion_min": e.get("duration"),
        "estado": ESTADOS.get(estado, estado),
        "estado_crudo": estado,
        "vigente": estado not in NO_VIGENTES,
        "profesional": (e.get("resource") or {}).get("label"),
        "servicio": (e.get("service") or {}).get("label"),
        "remoto": bool(e.get("remote")),
        "paciente": _paciente(e),
    }


def _orden(t: dict):
    return (t.get("fecha") or "", t.get("hora") or "")


def _filtrar(crudos, profesional=None, incluir_cancelados=False,
             incluir_bloqueos=False, desde=None, hasta=None) -> list[dict]:
    turnos = []
    for e in crudos:
        if e.get("deleted"):
            continue
        if e.get("type") != "appointment":
            if not incluir_bloqueos:
                continue
        t = normalizar(e)
        # El recorte por fecha es nuestro, no del servidor. 'day' ya viene en
        # la zona de la clinica y se compara como texto: '2026-09-15'.
        dia = t["fecha"]
        if desde and (not dia or dia < desde):
            continue
        if hasta and (not dia or dia > hasta):
            continue
        if not incluir_cancelados and not t["vigente"]:
            continue
        if profesional and norm(profesional) not in norm(t["profesional"]):
            continue
        turnos.append(t)
    return sorted(turnos, key=_orden)


def consultar(desde: str, hasta: str, profesional: str | None = None,
              incluir_cancelados: bool = False,
              incluir_bloqueos: bool = False) -> dict:
    """Turnos del equipo entre dos fechas, ambas inclusive."""
    crudos = api.consultar_eventos(_ms(desde, dias=-1),
                                   _ms(hasta, fin_del_dia=True, dias=1))
    turnos = _filtrar(crudos, profesional, incluir_cancelados,
                      incluir_bloqueos, desde, hasta)
    fuera = sum(1 for e in crudos
                if (e.get("day") or "") and not (desde <= e["day"] <= hasta))
    por_dia: dict[str, int] = {}
    for t in turnos:
        if t["fecha"]:
            por_dia[t["fecha"]] = por_dia.get(t["fecha"], 0) + 1
    return {"desde": desde, "hasta": hasta, "total": len(turnos),
            "por_dia": dict(sorted(por_dia.items())),
            "descartados_no_turno": sum(1 for e in crudos
                                        if e.get("type") != "appointment"),
            "descartados_fuera_de_rango": fuera,
            "turnos": turnos}


def de_paciente(consumer_id: str, incluir_cancelados: bool = False) -> dict:
    """Turnos de un paciente, separados en futuros y pasados por la API."""
    d = api.eventos_de(consumer_id) or {}
    fut = _filtrar(d.get("next") or [], incluir_cancelados=incluir_cancelados)
    pas = _filtrar(d.get("past") or [], incluir_cancelados=incluir_cancelados)
    return {"proximo": fut[0] if fut else None,
            "futuros": fut,
            "ultimo": pas[-1] if pas else None,
            "pasados": pas}
