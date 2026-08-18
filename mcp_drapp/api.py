"""Cliente HTTP de drapp. SOLO LECTURA.

Este modulo expone unicamente get(). No existe codigo que escriba en drapp:
no es un flag que se pueda invertir, la capacidad no esta implementada.
Ver tests/test_api.py, que lo verifica.
"""
import json
import time
import urllib.error
import urllib.request

from .auth import NecesitaLogin, access_token as _access_token

TEAM = "48b19010"
BASE = f"https://api.drapp.la/teams/{TEAM}"

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
