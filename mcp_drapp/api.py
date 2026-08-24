"""Cliente HTTP de drapp. SOLO LECTURA.

La regla del proyecto es que este cliente no puede modificar nada en drapp:
son historias clinicas reales y cualquier escritura quedaria firmada con la
matricula de la profesional.

Casi todo se resuelve con get(). La unica excepcion es buscar(), que hace
POST porque drapp no ofrece otra forma de enumerar el padron de pacientes:
el listado se pide con un body. Para que la excepcion no se convierta en una
puerta abierta, buscar() solo acepta rutas de la lista blanca POST_PERMITIDOS
-- hoy una sola, la de busqueda -- y rechaza cualquier otra. No existe codigo
capaz de hacer PUT, PATCH ni DELETE.

tests/test_api.py verifica las tres cosas: que la lista blanca sea la
declarada, que no haya otros verbos, y que un POST fuera de la lista falle.
"""
import json
import time
from datetime import datetime, timezone
import urllib.error
import urllib.request

from .auth import NecesitaLogin, access_token as _access_token

TEAM = "48b19010"
BASE = f"https://api.drapp.la/teams/{TEAM}"

# Unicas rutas a las que se permite POST. Son consultas: devuelven datos y no
# modifican nada. Agregar una entrada aca es una decision de diseno, no un
# detalle -- cada ruta nueva debilita la garantia de solo lectura.
POST_PERMITIDOS = frozenset({"search/consumers"})

SECCIONES = {
    "evoluciones": "records/_all", "diagnosticos": "diagnostics",
    "tratamientos": "treatments", "signos_vitales": "vitalSigns",
    "archivos": "files", "recetas": "prescriptions",
    "laboratorios": "labs", "stats": "stats",
}


def get(path: str, reintentos: int = 3):
    """Unica operacion de red del proyecto."""
    url = path if path.startswith("http") else f"{BASE}/{path.lstrip('/')}"
    ultimo = None
    for intento in range(1, reintentos + 1):
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {_access_token()}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise NecesitaLogin("La sesion vencio. Corre la herramienta 'login'.")
            if e.code == 429 or e.code >= 500:
                ultimo = f"HTTP {e.code}"; time.sleep(2 * intento); continue
            raise RuntimeError(f"HTTP {e.code} en {url}")
        except Exception as e:
            ultimo = str(e); time.sleep(1.5 * intento)
    raise RuntimeError(f"Fallo tras {reintentos} intentos: {ultimo}")


def secciones_de(consumer_id: str) -> dict:
    """Baja las 7 secciones de la HCE de un paciente, mas stats."""
    return {n: get(f"consumers/{consumer_id}/{ep}") for n, ep in SECCIONES.items()}


def buscar(path: str, body: dict, reintentos: int = 3):
    """Consulta que exige body. SOLO para rutas de POST_PERMITIDOS.

    drapp no expone el padron por GET: hay que pedirlo con un body. Esta
    funcion existe unicamente para eso y valida la ruta contra la lista
    blanca antes de salir a la red.
    """
    ruta = path.strip("/")
    if ruta not in POST_PERMITIDOS:
        raise ValueError(
            f"'{ruta}' no esta en POST_PERMITIDOS. Este cliente es de solo "
            f"lectura: el unico POST permitido es a {sorted(POST_PERMITIDOS)}.")
    url = f"{BASE}/{ruta}"
    ultimo = None
    for intento in range(1, reintentos + 1):
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {_access_token()}",
                     "Content-Type": "application/json",
                     "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise NecesitaLogin("La sesion vencio. Corre la herramienta 'login'.")
            if e.code == 429 or e.code >= 500:
                ultimo = f"HTTP {e.code}"; time.sleep(2 * intento); continue
            raise RuntimeError(f"HTTP {e.code} en {url}")
        except Exception as e:
            ultimo = str(e); time.sleep(1.5 * intento)
    raise RuntimeError(f"Fallo tras {reintentos} intentos: {ultimo}")


def _iso(v) -> str:
    """Fecha de alta a texto ISO.

    El CSV la trae como "2025-12-29T13:41:18.942Z" y la API como epoch en
    milisegundos. Ambas rutas tienen que producir lo mismo.
    """
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000, timezone.utc).isoformat()
    return (v or "").strip()


def listar_consumers() -> list[dict]:
    """Padron completo del equipo, paginado de a 25 por `offset`.

    Devuelve los pacientes en el formato de data/patients.json. Ojo: este
    endpoint NO trae la fecha de nacimiento; se completa despues desde el
    registro individual, que si la tiene.
    """
    acumulado: dict[str, dict] = {}
    offset = 0
    while True:
        pagina = buscar("search/consumers", {"sort": {"key": "label"},
                                             "offset": offset})
        if not isinstance(pagina, list) or not pagina:
            break
        nuevos = {x["id"].split("/")[-1]: x for x in pagina
                  if x.get("id") and not x.get("deleted")}
        if not set(nuevos) - set(acumulado):
            break                      # dejo de avanzar: llegamos al final
        acumulado.update(nuevos)
        offset += len(pagina)
    return [{"consumerId": cid,
             "firstName": (x.get("firstName") or "").strip(),
             "lastName": (x.get("lastName") or "").strip(),
             "dni": (x.get("identification") or "").strip(),
             "createdAt": _iso(x.get("createdAt"))}
            for cid, x in acumulado.items()]
