# mcp-drapp

Servidor MCP de **solo lectura** sobre la historia clínica electrónica (HCE) del
equipo `48b19010` de [drapp.la](https://drapp.la). Deja consultar pacientes,
evoluciones, diagnósticos, tratamientos y laboratorios desde Claude (u otro
cliente MCP) sin pasar por la web de drapp.

El corpus local vive en `data/hce/` (un JSON por paciente, fuente de verdad) y
se indexa en `data/index.db`, un SQLite con FTS5 que se puede borrar y
regenerar en cualquier momento sin perder nada. Las consultas leen ese índice
local: son instantáneas, no gastan token y funcionan sin internet. Las únicas
dos herramientas que tocan la red son `login` y `refresh`.

Corpus actual: 1569 pacientes, 4166 registros, de los cuales 3957 son
evoluciones en texto libre.

## Instalación

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Iniciar sesión

```bash
.venv/bin/python -c "from mcp_drapp import server; server.login()"
```

o, desde un cliente MCP, invocando la herramienta `login`. Abre el navegador
contra Auth0, esperá a que completes el login ahí (nunca se te pide ni se
maneja una contraseña acá) y guarda el refresh token en el Llavero de macOS.

**El puerto 3000 tiene que estar libre.** drapp sólo acepta
`http://localhost:3000` como callback de OAuth — se probó empíricamente y no
hay forma de cambiarlo. Si el login falla por puerto ocupado:

```bash
lsof -ti:3000        # ver qué lo está usando
kill $(lsof -ti:3000) # liberarlo
```

Con refresh token guardado, el resto de las herramientas renueva la sesión
sola cuando hace falta (`refresh` y, si drapp lo exige, cualquier llamada que
dispare `access_token()`). Si no hay sesión utilizable, la herramienta que la
necesite corta con `NecesitaLogin` pidiendo correr `login` de nuevo — se
comprobó corriendo `refresh` sin sesión:

```
$ .venv/bin/python -c "
from mcp_drapp import server
try:
    server.refresh(consumer_id='96b77748')
except Exception as e:
    print(f'{type(e).__name__}: {e}')
"
NecesitaLogin: No hay sesion. Corre la herramienta 'login'.
```

## Las 8 herramientas

En todos los ejemplos de abajo se reemplazaron nombre, DNI y fecha de
nacimiento reales por placeholders — son corridas reales contra el corpus de
la clínica, no inventadas, pero esa identidad no se pega en un README
versionado (ver la nota de privacidad al final).

### `login()`
Abre el navegador y guarda la sesión. No se corrió acá porque requiere que
vos completes el login interactivamente en el navegador (no es algo para
disparar sin que lo pidas en el momento). Devuelve algo con esta forma
(según `auth.login`):
```python
{"expires_in": 86400, "refresh_token": True,
 "nota": "Renovacion automatica activa."}
```

### `status()`
Frescura del corpus + estado de la sesión.
```
$ .venv/bin/python -c "from mcp_drapp import server; import json; print(json.dumps(server.status(), ensure_ascii=False, indent=2))"
{
  "n_patients": 1569,
  "n_records": 4166,
  "last_refresh": "2026-08-18T18:39:18.618643+00:00",
  "dias_desde_refresh": 0,
  "schema_version": "1",
  "advertencia": null,
  "sesion": {"sesion": "ausente", "detalle": "No hay sesion. Corre la herramienta 'login'."}
}
```

### `refresh(mode="nuevos", consumer_id=None)`
Re-baja la HCE desde drapp (todo el corpus, o un paciente puntual con
`consumer_id`) y reindexa. Devuelve el diff (`pacientes_nuevos`,
`registros_nuevos`, `registros_modificados`) más los conteos del reindexado.
Sin sesión activa corta con `NecesitaLogin` (ver ejemplo arriba). Reindexar
solo, sin bajar nada, es lo que hace `_db()` automáticamente si borrás
`data/index.db` — tarda unos 3 segundos sobre el corpus completo (medido en
esta máquina: 1569 pacientes / 4166 registros / 8755 labs).

### `find_patient(query, limit=20)`
Busca por nombre, DNI, email o teléfono.
```
$ .venv/bin/python -c "from mcp_drapp import server; import json; print(json.dumps(server.find_patient('perez', limit=3), ensure_ascii=False, indent=2))"
[
  {
    "consumer_id": "96b77748",
    "full_name": "Apellido, Nombre",
    "dni": "XXXXXXXX",
    "dob": "AAAA-MM-DD",
    "n_records": 12,
    "last_visit": "2026-07-13"
  },
  {
    "consumer_id": "049190db",
    "full_name": "Apellido, Nombre",
    "dni": "XXXXXXXX",
    "dob": "AAAA-MM-DD",
    "n_records": 5,
    "last_visit": "2025-11-10"
  }
]
```

### `get_patient(consumer_id=None, dni=None, sections=None, desde=None, hasta=None, limit=50)`
Historia clínica completa (o filtrada por sección/fecha), en orden
cronológico.
```
$ .venv/bin/python -c "from mcp_drapp import server; import json; print(json.dumps(server.get_patient(consumer_id='96b77748', sections=['evoluciones'], limit=1), ensure_ascii=False, indent=2))"
{
  "patient": {"consumer_id": "96b77748", "full_name": "Apellido, Nombre",
              "dni": "XXXXXXXX", "n_records": 12,
              "first_visit": "2024-04-08", "last_visit": "2026-07-13", "..." : "..."},
  "records": [
    {"record_id": "records/311d1d38", "section": "evoluciones", "date": null,
     "author": "Anselmi, María Eugenia", "text": "(texto clínico real, omitido acá)"}
  ],
  "corpus": {"last_refresh": "2026-08-18T18:39:18...", "dias_desde_refresh": 0, "advertencia": null}
}
```

### `search_records(query, section="evoluciones", desde=None, hasta=None, author=None, limit=30)`
Full-text FTS5 sobre evoluciones (donde está el 95% del contenido clínico).
Sintaxis: `AND`, `OR`, `"frase exacta"`, `prefijo*`.
```
$ .venv/bin/python -c "from mcp_drapp import server; print(len(server.search_records('hipotiroidismo')))"
30
```
Cada resultado trae `record_id`, `consumer_id`, `date`, `author`, `section` y
un `snippet` resaltado del fragmento que matcheó. Anduvo entre 2 y 50 ms en
las corridas de prueba, según la query.

### `cohort(contiene=None, sin_visitas_desde=None, diagnostico=None, droga=None, limit=100)`
Pacientes que cumplen criterios combinados con AND (mención de texto libre,
inactividad, diagnóstico, droga en tratamiento).
```
$ .venv/bin/python -c "from mcp_drapp import server; print(len(server.cohort(sin_visitas_desde='2025-06-01', limit=2000)))"
980
```
980 pacientes sin visitas desde junio de 2025. Ojo con el `limit` default
(100): para cohortes grandes como esta hay que subirlo explícitamente.

### `lab_series(consumer_id=None, dni=None, analitos=None, desde=None, hasta=None)`
Serie temporal de laboratorio (y peso) de un paciente, con cobertura de la
extracción.
```
$ .venv/bin/python -c "from mcp_drapp import server; import json; print(json.dumps(server.lab_series(consumer_id='96b77748', analitos=['peso']), ensure_ascii=False, indent=2))"
{
  "series": {
    "peso": [
      {"analyte": "peso", "value": 99.0, "unit": "kg", "date": "2025-11-03",
       "source": "texto", "snippet": "pa 99!!!\n\nlleva"}
    ]
  },
  "cobertura": {"evoluciones_totales": 13, "con_labs": 4,
                "nota": "La ausencia de un valor no significa valor normal."},
  "corpus": {"last_refresh": "...", "dias_desde_refresh": 0, "advertencia": null}
}
```
Este ejemplo de paso muestra la regla `PA` = peso actual en acción: el
snippet original queda pegado al valor para que se pueda verificar (ver
advertencias abajo).

## Advertencias importantes

**El servidor es de solo lectura por diseño, no por configuración.**
`mcp_drapp/api.py` sólo implementa `get()`; no existe ninguna función que
escriba en drapp (ni `post`, `put`, `patch` ni `delete`). No es un flag que
se pueda prender: la capacidad de escritura no está implementada en el
código. `tests/test_api.py` lo verifica inspeccionando el módulo y buscando
esos verbos en el código fuente.

**`PA` significa "peso actual" en kg**, en la notación de esta clínica — no
presión arterial. La única excepción es el contexto de MAPA (monitoreo
ambulatorio de presión de 24 h): si el fragmento tiene `mmHg`, "MAPA", "24 h"
o forma sístole/diástole (ej. `119/73`), no se extrae ningún peso y el
fragmento va al bucket `revisar` en vez de inventar un valor. Ver
`mcp_drapp/labs.py`.

**Los labs con `source: "texto"` salen de notas escritas a mano**, no de una
tabla de laboratorio estructurada. Cada valor trae su `snippet` original en
la respuesta de `lab_series`: hay que confirmarlo contra ese fragmento antes
de usarlo clínicamente, la extracción por regex puede errar. La cobertura
medida contra el corpus real es de alrededor del 43% de las evoluciones (1708
de 3957 tienen al menos un valor extraído) — y `lab_series` devuelve su
propia cobertura (`evoluciones_totales` / `con_labs`) junto con la serie,
justamente porque la ausencia de un valor en la serie **no** significa que el
valor haya sido normal: puede ser que nunca se haya escrito, o que se haya
escrito de una forma que el extractor no reconoce.

## Privacidad

`data/` (el corpus JSON y el índice SQLite) nunca se versiona — son datos
clínicos identificables — y está en `.gitignore`. Los datos no salen de esta
máquina: el único tráfico de red de todo el proyecto es el `GET` a la API de
drapp que hacen `login` y `refresh`. Todo lo demás (`status`, `find_patient`,
`get_patient`, `search_records`, `cohort`, `lab_series`) lee el SQLite local.
