import pytest
from mcp_drapp import server


@pytest.mark.asyncio
async def test_expone_las_ocho_herramientas():
    nombres = {t.name for t in await server.mcp.list_tools()}
    assert nombres == {"login", "status", "refresh", "find_patient",
                       "get_patient", "search_records", "cohort", "lab_series"}


@pytest.mark.asyncio
async def test_ninguna_herramienta_escribe_en_drapp():
    for t in await server.mcp.list_tools():
        desc = (t.description or "").lower()
        assert not any(v in desc for v in ("crea ", "modifica", "elimina", "escribe en drapp"))


def test_search_records_usa_evoluciones_por_defecto():
    import inspect
    p = inspect.signature(server.search_records).parameters
    assert p["section"].default == "evoluciones"
