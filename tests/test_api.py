import inspect
import re
from mcp_drapp import api


def test_solo_existe_get():
    """Restriccion estructural: no debe haber ninguna operacion de escritura."""
    publicas = {n for n, _ in inspect.getmembers(api, inspect.isfunction)
                if not n.startswith("_")}
    assert "get" in publicas
    for prohibido in ("post", "put", "patch", "delete", "crear", "borrar", "actualizar"):
        assert prohibido not in publicas


def test_el_codigo_no_menciona_verbos_de_escritura():
    fuente = inspect.getsource(api)
    for verbo in ("POST", "PUT", "PATCH", "DELETE"):
        assert not re.search(rf'["\']{verbo}["\']', fuente), f"{verbo} presente en api.py"


def test_secciones_cubre_las_siete_mas_stats():
    assert set(api.SECCIONES) == {
        "evoluciones", "diagnosticos", "tratamientos", "signos_vitales",
        "archivos", "recetas", "laboratorios", "stats"}


def test_base_apunta_al_equipo_correcto():
    assert api.BASE == "https://api.drapp.la/teams/48b19010"
