"""Servidor MCP de solo lectura sobre la HCE de drapp.

Traduce entre el protocolo MCP y los modulos; no contiene logica de negocio.
"""
import pathlib

from mcp.server.mcpserver import MCPServer as FastMCP

from . import auth, index
from .api import get, listar_consumers, secciones_de
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

    mode:
      'nuevos' (por defecto) consulta el contador de cada paciente (1 request
      barato) y solo baja las 8 secciones de los que cambiaron, mas los que
      todavia no estan en el corpus. Ojo: ese contador refleja evoluciones,
      que son el 95% del contenido; un cambio que toque SOLO diagnosticos,
      tratamientos o archivos puede no detectarse.
      'todos' vuelve a bajar todo, sin excepcion. Es el modo exhaustivo.

    consumer_id: limita la operacion a un unico paciente, ignorando `mode`.

    El padron se pide a drapp en cada corrida, asi que los pacientes dados de
    alta desde la ultima vez aparecen solos: no hay que exportar el CSV a
    mano. Si la red falla se usa la copia local y se avisa en `padron_al_dia`. El indice se reconstruye SIEMPRE al final,
    incluso si alguna descarga fallo, para que no quede desincronizado del
    corpus; las fallas se informan en la clave `errores`.
    """
    import json

    viejo = cargar(CORPUS)
    por_id = {p.consumer_id: p for p in viejo}

    # El padron se pide a drapp: asi las altas nuevas se descubren solas y no
    # hay que exportar el CSV a mano. Si la red falla se cae a la lista local,
    # que puede estar vieja pero permite refrescar lo que ya se tiene.
    lista_path = ROOT / "data" / "patients.json"
    padron_al_dia = True
    try:
        lista = listar_consumers()
        lista_path.parent.mkdir(parents=True, exist_ok=True)
        lista_path.write_text(json.dumps(lista, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    except Exception:
        padron_al_dia = False
        if lista_path.exists():
            lista = json.loads(lista_path.read_text(encoding="utf-8"))
        else:
            lista = [{"consumerId": p.consumer_id, **p.patient} for p in viejo]

    if consumer_id:
        objetivo = [x for x in lista if x.get("consumerId") == consumer_id]
    elif mode == "todos":
        objetivo = lista
    else:
        objetivo = []
        for x in lista:
            cid = x.get("consumerId")
            local = por_id.get(cid)
            if local is None:
                objetivo.append(x)          # paciente nuevo
                continue
            try:
                st = get(f"consumers/{cid}/stats")
            except Exception:
                objetivo.append(x)          # ante la duda, bajar
                continue
            if st.get("records") != len(local.sections.get("evoluciones") or []):
                objetivo.append(x)

    errores = []
    for x in objetivo:
        cid = x.get("consumerId")
        try:
            datos = secciones_de(cid)
        except Exception as e:
            errores.append({"consumer_id": cid, "error": f"{type(e).__name__}: {e}"})
            continue
        ficha = dict(por_id[cid].patient) if cid in por_id else {}
        ficha.update({k: v for k, v in x.items() if v})
        (CORPUS / f"{cid}.json").write_text(
            json.dumps({"patient": ficha, "sections": datos},
                       ensure_ascii=False, indent=1), encoding="utf-8")

    nuevo = cargar(CORPUS)
    d = diff(viejo, nuevo)
    d["revisados"] = len(objetivo)
    d["padron_al_dia"] = padron_al_dia
    d["errores"] = errores
    d.update(index.construir(DB, nuevo))    # siempre, aun con errores
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
           alta_entre: list[str] | None = None, limit: int = 100) -> list[dict]:
    """Lista pacientes que cumplen criterios combinados con AND.

    alta_entre: [desde, hasta] en formato YYYY-MM-DD, sobre la fecha en que
    el paciente fue dado de alta en drapp.
    """
    return index.cohort(_db(), contiene, sin_visitas_desde, diagnostico, droga,
                        alta_entre, limit)


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
