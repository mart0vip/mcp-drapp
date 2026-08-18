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
    monkeypatch.setattr(auth, "_leer_llavero", lambda: None)
    monkeypatch.setattr(auth, "_TOKEN_MEM", None, raising=False)
    with pytest.raises(auth.NecesitaLogin):
        auth.access_token()
