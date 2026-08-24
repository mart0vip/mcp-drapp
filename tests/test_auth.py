import inspect
import pytest
from mcp_drapp import auth


def test_challenge_vector_rfc7636():
    """Vector oficial de la RFC 7636, seccion B."""
    v = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert auth.challenge_de(v) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_pkce_par_es_valido():
    v, ch = auth.pkce_par()
    assert 43 <= len(v) <= 128
    assert auth.challenge_de(v) == ch
    assert "=" not in ch


def test_ninguna_funcion_recibe_password():
    """Restriccion dura: el MCP no maneja contrasenas."""
    prohibidos = {"password", "passwd", "pwd", "contrasena", "secret"}
    for nombre, fn in inspect.getmembers(auth, inspect.isfunction):
        params = set(inspect.signature(fn).parameters)
        assert not (params & prohibidos), f"{nombre} recibe una credencial"


def test_callback_es_localhost_3000():
    """drapp solo permite este callback: no intentar otro puerto."""
    assert auth.REDIRECT_URI == "http://localhost:3000"


def test_sin_token_pide_login(monkeypatch):
    """Sin credenciales guardadas hay que pedir login, no fallar de otro modo.

    Se aisla tambien el access token compartido: desde que se comparte via
    Llavero, un token real de la maquina haria pasar el test por casualidad.
    """
    monkeypatch.setattr(auth, "_leer_llavero", lambda: None)
    monkeypatch.setattr(auth, "_leer_acceso", lambda: None)
    monkeypatch.setattr(auth, "_TOKEN_MEM", None, raising=False)
    with pytest.raises(auth.NecesitaLogin):
        auth.access_token()


# --- Rotacion de refresh tokens: la carrera que revocaba la sesion ---

class _FalsoLlavero:
    """Reemplaza al Llavero de macOS en memoria, compartido entre 'procesos'."""
    def __init__(self, refresh=None):
        self.datos = {"refresh_token": refresh} if refresh else {}
    def get_password(self, serv, clave):
        return self.datos.get(clave)
    def set_password(self, serv, clave, valor):
        self.datos[clave] = valor
    def delete_password(self, serv, clave):
        self.datos.pop(clave, None)


@pytest.fixture
def llavero(monkeypatch):
    kr = _FalsoLlavero(refresh="rt-inicial")
    monkeypatch.setattr(auth, "keyring", kr)
    monkeypatch.setattr(auth, "_TOKEN_MEM", None, raising=False)
    return kr


def test_access_token_compartido_evita_renovar(llavero, monkeypatch):
    """Si otro proceso ya renovo, se reusa su token en vez de renovar de nuevo.
    Renovar de mas es justamente lo que dispara la revocacion de Auth0."""
    import time as _t
    llavero.set_password(None, "access_token",
                         auth.json.dumps({"access_token": "compartido",
                                          "vence": _t.time() + 600}))
    def no_renovar(*a, **k):
        raise AssertionError("no deberia renovar: hay un token compartido vigente")
    monkeypatch.setattr(auth, "_post", no_renovar)
    assert auth.access_token() == "compartido"


def test_renovacion_relee_el_refresh_token_del_llavero(llavero, monkeypatch):
    """El refresh token se relee dentro del lock: si otro proceso lo roto
    mientras esperabamos, usamos el nuevo y no una copia vieja."""
    llavero.set_password(None, "refresh_token", "rt-rotado-por-otro-proceso")
    usados = []
    def falso_post(path, datos):
        usados.append(datos["refresh_token"])
        return {"access_token": "nuevo", "expires_in": 3600,
                "refresh_token": "rt-siguiente"}
    monkeypatch.setattr(auth, "_post", falso_post)
    assert auth.access_token() == "nuevo"
    assert usados == ["rt-rotado-por-otro-proceso"]
    assert llavero.get_password(None, "refresh_token") == "rt-siguiente"


def test_invalid_grant_borra_credenciales_y_pide_login(llavero, monkeypatch):
    """Cuando Auth0 revoca la familia, no sirve reintentar: hay que borrar el
    token muerto y decirlo claro, en vez de fallar de forma criptica."""
    import io
    import urllib.error

    def revocado(path, datos):
        raise urllib.error.HTTPError(
            "https://auth.drapp.la/oauth/token", 403, "Forbidden", {},
            io.BytesIO(b'{"error":"invalid_grant",'
                       b'"error_description":"Unknown or invalid refresh token."}'))
    monkeypatch.setattr(auth, "_post", revocado)

    with pytest.raises(auth.NecesitaLogin) as exc:
        auth.access_token()
    assert "login" in str(exc.value).lower()
    assert llavero.get_password(None, "refresh_token") is None, "credencial muerta borrada"
    assert llavero.get_password(None, "access_token") is None


def test_login_deja_el_access_token_compartido(llavero, monkeypatch):
    """Tras login, otros procesos tienen que poder usar el token sin renovar."""
    monkeypatch.setattr(auth, "_recordar", lambda tok: setattr(
        auth, "_TOKEN_MEM", {"access_token": tok["access_token"],
                             "vence": auth.time.time() + 3600}))
    auth._recordar({"access_token": "post-login"})
    auth._guardar_acceso(auth._TOKEN_MEM)
    assert auth._leer_acceso()["access_token"] == "post-login"
