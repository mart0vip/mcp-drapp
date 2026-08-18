"""Servidor MCP de solo lectura sobre la HCE de drapp.

Traduce entre el protocolo MCP y los modulos; no contiene logica de negocio.
"""
import pathlib

from mcp.server.mcpserver import MCPServer as FastMCP

from . import auth, index
from .api import secciones_de
from .corpus import cargar, diff

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "index.db"
CORPUS = ROOT / "data" / "hce"

mcp = FastMCP("drapp")


def _db() -> pathlib.Path:
    if not DB.exists():
        index.reconstruir(DB, CORPUS)
    return DB


@mcp.tool()
def login() -> dict:
    """Inicia sesion en drapp abriendo el navegador. No recibe contrasenas."""
    return auth.login()


@mcp.tool()
def status() -> dict:
    """Frescura del corpus, conteos y estado de la sesion."""
    return {**index.estado(_db()), "sesion": auth.estado_token()}


@mcp.tool()
def refresh(mode: str = "nuevos", consumer_id: str | None = None) -> dict:
    """Re-baja la HCE desde drapp y reindexa. Informa que cambio.

    mode: 'nuevos' compara contra el corpus; 'todos' vuelve a bajar todo.
    """
    import json
    viejo = cargar(CORPUS)
    objetivo = ([p for p in viejo if p.consumer_id == consumer_id] if consumer_id
                else viejo)
    for p in objetivo:
        datos = secciones_de(p.consumer_id)
        (CORPUS / f"{p.consumer_id}.json").write_text(
            json.dumps({"patient": p.patient, "sections": datos},
                       ensure_ascii=False, indent=1), encoding="utf-8")
    nuevo = cargar(CORPUS)
    d = diff(viejo, nuevo)
    d.update(index.construir(DB, nuevo))
    return d


@mcp.tool()
def find_patient(query: str, limit: int = 20) -> list[dict]:
    """Busca un paciente por nombre, DNI, email o telefono."""
    return index.find_patient(_db(), query, limit)


@mcp.tool()
def get_patient(consumer_id: str | None = None, dni: str | None = None,
                sections: list[str] | None = None, desde: str | None = None,
                hasta: str | None = None, limit: int = 50) -> dict:
    """Historia clinica de un paciente, en orden cronologico."""
    return index.get_patient(_db(), consumer_id, dni, sections, desde, hasta, limit)


@mcp.tool()
def search_records(query: str, section: str = "evoluciones", desde: str | None = None,
                   hasta: str | None = None, author: str | None = None,
                   limit: int = 30) -> list[dict]:
    """Busqueda de texto completo en las evoluciones. Sintaxis FTS5:
    AND, OR, "frase exacta", prefijo*. Por defecto busca solo en evoluciones,
    donde esta el 95% del contenido clinico.
    """
    return index.search_records(_db(), query, section, desde, hasta, author, limit)


@mcp.tool()
def cohort(contiene: str | None = None, sin_visitas_desde: str | None = None,
           diagnostico: str | None = None, droga: str | None = None,
           limit: int = 100) -> list[dict]:
    """Lista pacientes que cumplen criterios combinados con AND."""
    return index.cohort(_db(), contiene, sin_visitas_desde, diagnostico, droga, limit)


@mcp.tool()
def lab_series(consumer_id: str | None = None, dni: str | None = None,
               analitos: list[str] | None = None, desde: str | None = None,
               hasta: str | None = None) -> dict:
    """Serie temporal de labs y peso de un paciente.

    Cada punto incluye el fragmento original ('snippet') y su origen
    ('source': tabla o texto). Los valores de 'texto' salen de notas escritas
    a mano: verificalos contra el snippet antes de usarlos clinicamente.
    """
    return index.lab_series(_db(), consumer_id, dni, analitos, desde, hasta)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
