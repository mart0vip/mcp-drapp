"""Lectura del corpus de HCE en data/hce/ y comparacion entre versiones."""
import json
import pathlib
from dataclasses import dataclass, field

SECCIONES = ["evoluciones", "diagnosticos", "tratamientos", "signos_vitales",
             "recetas", "laboratorios", "archivos"]


@dataclass
class PacienteCorpus:
    consumer_id: str
    patient: dict
    sections: dict = field(default_factory=dict)

    def registros(self):
        """Itera (seccion, registro) sobre todas las secciones de lista."""
        for s in SECCIONES:
            for r in self.sections.get(s) or []:
                if isinstance(r, dict):
                    yield s, r


def cargar(directorio: pathlib.Path) -> list[PacienteCorpus]:
    out = []
    for f in sorted(pathlib.Path(directorio).glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        p = d.get("patient") or {}
        cid = p.get("consumerId") or f.stem
        out.append(PacienteCorpus(cid, p, d.get("sections") or {}))
    return out


def _mapa(ps: list[PacienteCorpus]) -> dict[str, dict]:
    return {r["id"]: r for p in ps for _, r in p.registros() if r.get("id")}


def diff(viejo: list[PacienteCorpus], nuevo: list[PacienteCorpus]) -> dict:
    ids_v = {p.consumer_id for p in viejo}
    rv, rn = _mapa(viejo), _mapa(nuevo)
    return {
        "pacientes_nuevos": sorted(p.consumer_id for p in nuevo if p.consumer_id not in ids_v),
        "registros_nuevos": sorted(k for k in rn if k not in rv),
        "registros_modificados": sorted(
            k for k in rn if k in rv and rn[k].get("updatedAt") != rv[k].get("updatedAt")
        ),
    }
