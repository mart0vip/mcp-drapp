# mcp-drapp

Servidor MCP de **solo lectura** sobre la historia clínica electrónica (HCE) del
equipo `48b19010` de [drapp.la](https://drapp.la). Deja consultar pacientes,
evoluciones, diagnósticos, tratamientos y laboratorios desde Claude (u otro
cliente MCP) sin pasar por la web de drapp.

El corpus local vive en `data/hce/` (un JSON por paciente, fuente de verdad) y
se indexa en `data/index.db`, un SQLite con FTS5 que se puede borrar y
regenerar en cualquier momento sin perder nada. Las consultas leen ese índice
local: son instantáneas, no gastan token y funcionan sin internet. Las
herramientas que tocan la red son `login`, `refresh` y `agenda` — esta última
porque los turnos son dato vivo y no tendría sentido indexarlos. `get_patient`
le suma los turnos del paciente y por eso también sale a la red, pero si no
hay sesión o no hay internet devuelve la ficha igual y avisa qué faltó.

Corpus actual: 1575 pacientes, 4189 registros, de los cuales 3957 son
evoluciones en texto libre y 175 son adjuntos (laboratorios en PDF, ecografías
y fotos de laboratorios en papel). El texto de los adjuntos también se indexa:
ver "Adjuntos" más abajo.

## Instalación

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Para armar el corpus desde cero, después de iniciar sesión:

```bash
.venv/bin/python scripts/fetch_hce.py            # historias (15-25 min)
.venv/bin/python scripts/bajar_adjuntos.py       # adjuntos (~155 MB)
.venv/bin/python scripts/extraer_texto_adjuntos.py
```

El padrón se le pide a drapp, así que no hace falta exportar ningún CSV.
`scripts/importar_csv.py` queda como respaldo para instalar sin sesión, a
partir del export de Reportes → Pacientes.

Guía paso a paso para alguien que no programa: [INSTALL.md](INSTALL.md).

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

## Las 9 herramientas

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
  "n_patients": 1575,
  "n_records": 4189,
  "last_refresh": "2026-08-24T04:11:49.814516+00:00",
  "dias_desde_refresh": 1,
  "schema_version": "1",
  "advertencia": null,
  "sesion": {
    "sesion": "activa",
    "vence_en_seg": 86340
  }
}
```

### `refresh(mode="nuevos", consumer_id=None)`
Re-baja la HCE desde drapp y reindexa. Devuelve el diff (`pacientes_nuevos`,
`registros_nuevos`, `registros_modificados`), `padron_al_dia`, `errores` y los
conteos del reindexado.

`mode="nuevos"` (default) consulta el contador de cada paciente —un request
barato— y sólo baja las 8 secciones de los que cambiaron. Ese contador refleja
**evoluciones**: un cambio que toque sólo diagnósticos o tratamientos puede no
detectarse. `mode="todos"` es el exhaustivo. Unos 5 minutos sobre el padrón
completo.

El padrón se le pide a drapp en cada corrida, así que los pacientes dados de
alta desde la última vez **aparecen solos**. Si la red falla se usa la copia
local y se avisa con `padron_al_dia: false`, en vez de aparentar estar al día.

El índice se reconstruye siempre al final, aun si alguna descarga falló, para
que no quede desincronizado del corpus. Reindexar solo tarda unos 3 segundos
(1575 pacientes / 4189 registros / 8440 labs).

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

### `get_patient(consumer_id=None, dni=None, sections=None, desde=None, hasta=None, limit=50, incluir_turnos=True)`
Historia clínica completa (o filtrada por sección/fecha), en orden
cronológico, más los turnos del paciente para preparar la consulta: `proximo`,
`ultimo`, y las listas completas `futuros` y `pasados`.

Los turnos son la única parte que sale a la red. Si no hay sesión o no hay
internet, la ficha se devuelve igual y `turnos` trae un `no_disponible` que
explica por qué. Con `incluir_turnos=False` no se consulta nada y la
herramienta vuelve a funcionar 100% offline.
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
  "corpus": {"last_refresh": "2026-08-18T18:39:18...", "dias_desde_refresh": 0, "advertencia": null},
  "turnos": {
    "proximo": {"fecha": "2026-09-15", "hora": "10:20", "estado": "reservado",
                "profesional": "Acosta, Veronica", "...": "..."},
    "ultimo":  {"fecha": "2026-08-28", "hora": "17:00", "estado": "activo",
                "profesional": "Anselmi, MARIA EUGENIA", "...": "..."},
    "futuros": ["..."], "pasados": ["..."]
  }
}
```

### `agenda(desde=None, hasta=None, profesional=None, incluir_cancelados=False, incluir_bloqueos=False)`
Turnos del equipo entre dos fechas (`YYYY-MM-DD`), ambas inclusive. Sin
argumentos, los de hoy; con `desde` solo, ese día. **Consulta drapp en vivo:
necesita sesión e internet.**

Por defecto muestra solo turnos vigentes. Quedan afuera tres cosas distintas:
los cancelados, los ausentes (`noshow`) y los **bloqueos de agenda** — horas
que la profesional cerró, que la API devuelve mezcladas con los turnos bajo
`type: "lock"` y que no tienen paciente ni servicio. El campo
`descartados_no_turno` dice cuántos bloqueos había en la ventana.

```
$ .venv/bin/python -c "from mcp_drapp import server; import json; print(json.dumps(server.agenda(desde='2026-08-31', hasta='2026-09-05'), ensure_ascii=False, indent=2))"
{
  "desde": "2026-08-31", "hasta": "2026-09-05",
  "total": 19,
  "por_dia": {"2026-08-31": 6, "2026-09-03": 11, "2026-09-04": 2},
  "descartados_no_turno": 18,
  "descartados_fuera_de_rango": 14,
  "turnos": [
    {"event_id": "6a9195794d6f93a9", "fecha": "2026-08-31", "hora": "09:00",
     "duracion_min": 30, "estado": "reservado", "estado_crudo": "booked",
     "vigente": true, "profesional": "Anselmi, MARIA EUGENIA",
     "servicio": "Endocrinología Adultos / Consulta", "remoto": false,
     "paciente": {"consumer_id": "c1...", "nombre": "Apellido, Nombre",
                  "dni": "XXXXXXXX", "telefono": "+54 9 ..."}}
  ]
}
```

**El rango se recorta acá, no en drapp.** La ventana `startsAt`/`endsAt` del
endpoint filtra por fecha **UTC**, así que desde Argentina (UTC−3) el fin del
día local cae en el día siguiente en UTC y el servidor devuelve turnos de más:
pedir el 30/8 devolvía los 12 eventos del 31/8, y la herramienta habría dicho
"tenés 6 turnos hoy" cuando el 30/8 era domingo y no había ninguno. Por eso se
pide un día de margen a cada lado y el recorte fino se hace contra el campo
`day`, que ya viene en la fecha local de la clínica.
`descartados_fuera_de_rango` cuenta lo que entró de más y se tiró.

`estado` traduce el vocabulario de drapp (`booked` → reservado, `fulfilled` →
atendido, `cancelled` → cancelado, `noshow` → ausente, `arrived` → en sala,
`pending`, `active`). Un estado que no esté en esa lista se devuelve tal cual
vino, sin inventarle significado; `estado_crudo` siempre trae el original.

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

### `cohort(contiene=None, sin_visitas_desde=None, diagnostico=None, droga=None, alta_entre=None, limit=100)`
Pacientes que cumplen criterios combinados con AND (mención de texto libre,
inactividad, diagnóstico, droga en tratamiento, fecha de alta). `alta_entre`
toma `[desde, hasta]` en formato `YYYY-MM-DD` sobre la fecha en que el paciente
fue dado de alta en drapp.
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

**El servidor no puede modificar nada en drapp.** `mcp_drapp/api.py` resuelve
casi todo con `get()`. Las excepciones pasan por `buscar()`, que hace `POST`
porque drapp no expone esos listados por `GET`: se piden con un body. Esa
función valida la ruta contra `POST_PERMITIDOS` y rechaza cualquier otra. **No
existe código capaz de hacer `PUT`, `PATCH` ni `DELETE`.** `tests/test_api.py`
lo verifica en tres frentes: que la lista blanca sea exactamente la declarada,
que no haya otros verbos en el código fuente, y que un `POST` fuera de la lista
levante excepción.

La lista tiene hoy **dos** entradas, y las dos son consultas:

| Ruta | Por qué | Autorizada |
|---|---|---|
| `search/consumers` | El padrón de pacientes; no hay GET equivalente | Diseño inicial |
| `events/query` | La agenda de turnos. Es la misma llamada que hace la app web al abrir el calendario | 2026-08-30 |

Cada entrada nueva debilita un poco la garantía, que pasó de "es imposible
hacer POST" a "los únicos POST posibles son estas dos consultas, y está
verificado". Por eso agregar una es una decisión explícita del usuario, no un
detalle de implementación: el test que fija la lista existe para que ampliarla
sin querer sea imposible.

**El contador `events` de `stats` no sirve para contar turnos.** Está en el
corpus y es engañoso: dice `2` para un paciente que tiene 1 turno futuro y 3
pasados, y da 0 para 1447 de los 1575 pacientes. Los turnos de verdad salen de
`agenda` y de `get_patient`, no de ahí.

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
medida contra el corpus real es de alrededor del 46% de las evoluciones (1688
de 3697 tienen al menos un valor extraído) — y `lab_series` devuelve su
propia cobertura (`evoluciones_totales` / `con_labs`) junto con la serie,
justamente porque la ausencia de un valor en la serie **no** significa que el
valor haya sido normal: puede ser que nunca se haya escrito, o que se haya
escrito de una forma que el extractor no reconoce.

## Adjuntos

Las historias traen 175 archivos adjuntos: 140 PDFs (la mitad, laboratorios),
31 fotos de WhatsApp que son laboratorios en papel, y algunas imágenes más.
`scripts/bajar_adjuntos.py` los baja a `data/adjuntos/` y
`scripts/extraer_texto_adjuntos.py` les extrae el texto a
`data/adjuntos_texto/`, usando la capa de texto del PDF cuando existe (122
archivos) y **OCR cuando no** (48). El OCR usa el framework Vision de Apple y
**corre entero en la máquina**: ningún documento clínico sale a un servicio
externo.

Ese texto se indexa junto al nombre del archivo en la sección `archivos`, así
que `search_records(..., section="archivos")` o `section=None` lo alcanzan.
Buscar "tirotrofina" pasa de 3 resultados a 64: casi nunca se escribe en una
evolución, pero está en 61 laboratorios adjuntos.

Un dato sobre drapp, no sobre esta herramienta: **los adjuntos viven en un CDN
público**. Se descargan sin token; cualquiera con el link accede al laboratorio
del paciente. Las URLs son difíciles de adivinar, pero eso es oscuridad, no
control de acceso.

## Privacidad

`data/` (el corpus JSON y el índice SQLite) nunca se versiona — son datos
clínicos identificables — y está en `.gitignore`. Los datos no salen de esta
máquina: el único tráfico de red de todo el proyecto es el `GET` a la API de
drapp que hacen `login` y `refresh`. Todo lo demás (`status`, `find_patient`,
`get_patient`, `search_records`, `cohort`, `lab_series`) lee el SQLite local.
