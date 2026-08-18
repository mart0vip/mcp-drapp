"""Autenticacion contra Auth0 de drapp por authorization code + PKCE.

El usuario se autentica en la pantalla de Auth0. Este modulo NUNCA recibe,
pide ni almacena una contrasena. El refresh token va al Llavero de macOS.

Hallazgos de la prueba del 2026-08-18:
  - device_code: rechazado para este client_id
  - callback: solo http://localhost:3000 esta permitido
"""
import base64
import hashlib
import http.server
import json
import secrets
import socket
import threading
import time
import urllib.parse
import urllib.request
import webbrowser

import keyring

ISSUER = "https://auth.drapp.la"
CLIENT_ID = "UfXGb5B0ezKHRGm6fkac6PTfcwmqtlXk"
AUDIENCE = "https://api.drapp.la"
REDIRECT_URI = "http://localhost:3000"   # impuesto por drapp; no cambiar
SCOPE = "openid profile email offline_access"
SERVICIO = "drapp-mcp"
_TOKEN_MEM: dict | None = None


class NecesitaLogin(RuntimeError):
    """No hay credenciales utilizables; hay que correr login()."""


def challenge_de(verifier: str) -> str:
    d = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(d).rstrip(b"=").decode("ascii")


def pkce_par() -> tuple[str, str]:
    v = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode("ascii")
    return v, challenge_de(v)


def _leer_llavero() -> str | None:
    return keyring.get_password(SERVICIO, "refresh_token")


def _guardar_llavero(rt: str) -> None:
    keyring.set_password(SERVICIO, "refresh_token", rt)


def _post(path: str, datos: dict) -> dict:
    req = urllib.request.Request(
        f"{ISSUER}{path}", data=urllib.parse.urlencode(datos).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _puerto_libre(p: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", p)) != 0


def login(timeout: int = 300) -> dict:
    """Abre el navegador, espera el callback y guarda el refresh token."""
    if not _puerto_libre(3000):
        raise RuntimeError(
            "El puerto 3000 esta ocupado y drapp solo permite ese callback. "
            "Liberalo (lsof -ti:3000) y volve a intentar.")
    verifier, challenge = pkce_par()
    estado = secrets.token_urlsafe(16)
    recibido: dict = {}
    listo = threading.Event()

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            recibido.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            ok = "code" in recibido and recibido.get("state") == estado
            self.wfile.write(("<h2>%s</h2><p>Podes cerrar esta pestana.</p>" %
                              ("Listo, sesion iniciada." if ok else "Fallo el login."))
                             .encode())
            listo.set()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 3000), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"{ISSUER}/authorize?" + urllib.parse.urlencode({
        "client_id": CLIENT_ID, "response_type": "code", "redirect_uri": REDIRECT_URI,
        "scope": SCOPE, "audience": AUDIENCE, "state": estado,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    webbrowser.open(url)
    try:
        if not listo.wait(timeout):
            raise TimeoutError("No se completo el login a tiempo.")
    finally:
        srv.shutdown()

    if recibido.get("state") != estado or "code" not in recibido:
        raise RuntimeError(f"Callback invalido: {recibido.get('error', 'sin code')}")

    tok = _post("/oauth/token", {
        "grant_type": "authorization_code", "client_id": CLIENT_ID,
        "code": recibido["code"], "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier})
    _recordar(tok)
    if tok.get("refresh_token"):
        _guardar_llavero(tok["refresh_token"])
    return {"expires_in": tok.get("expires_in"),
            "refresh_token": bool(tok.get("refresh_token")),
            "nota": ("Renovacion automatica activa." if tok.get("refresh_token")
                     else "Sin refresh token: habra que correr login cada 24h.")}


def _recordar(tok: dict) -> None:
    global _TOKEN_MEM
    _TOKEN_MEM = {"access_token": tok["access_token"],
                  "vence": time.time() + int(tok.get("expires_in", 3600)) - 60}


def access_token() -> str:
    """Token vigente. Renueva con el refresh token si hace falta."""
    global _TOKEN_MEM
    if _TOKEN_MEM and time.time() < _TOKEN_MEM["vence"]:
        return _TOKEN_MEM["access_token"]
    rt = _leer_llavero()
    if not rt:
        raise NecesitaLogin("No hay sesion. Corre la herramienta 'login'.")
    try:
        tok = _post("/oauth/token", {"grant_type": "refresh_token",
                                     "client_id": CLIENT_ID, "refresh_token": rt})
    except Exception as e:
        raise NecesitaLogin(f"No se pudo renovar la sesion ({e}). Corre 'login'.")
    _recordar(tok)
    if tok.get("refresh_token"):
        _guardar_llavero(tok["refresh_token"])
    return _TOKEN_MEM["access_token"]


def estado_token() -> dict:
    try:
        access_token()
        return {"sesion": "activa", "vence_en_seg": int(_TOKEN_MEM["vence"] - time.time())}
    except NecesitaLogin as e:
        return {"sesion": "ausente", "detalle": str(e)}
