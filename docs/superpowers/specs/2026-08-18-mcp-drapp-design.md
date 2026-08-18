# MCP drapp — diseño

**Fecha:** 2026-08-18
**Estado:** aprobado para planificar
**Ámbito:** servidor MCP de solo lectura sobre la historia clínica de drapp.la (equipo `48b19010`, Centro Anselmi)

---

## 1. Objetivo

Consultar la historia clínica de drapp desde Claude sin abrir la app ni re-descargar datos a mano.

Hoy el corpus existe (1569 pacientes, 4166 registros) pero solo como archivos sueltos: para responder "¿quién está con Wegovy?" hay que leer 3957 evoluciones en texto libre. El MCP convierte ese corpus en algo consultable y lo mantiene actualizado.

### Casos de uso

1. **Ficha previa a consulta** — "¿qué venía haciendo Fulano?"
2. **Búsqueda de texto completo** — "¿quiénes tienen hipotiroidismo?"
3. **Cohortes y seguimiento** — "¿quién no viene hace más de 6 meses?"
4. **Series de labs y peso** — evolución de HbA1c, TSH o peso de un paciente

### Fuera de alcance

- Escribir en drapp (crear o editar evoluciones, diagnósticos, tratamientos, recetas)
- Descargar los adjuntos binarios de la sección Archivos (se indexa la metadata y el link)
- Turnos y agenda
- Multi-equipo: el diseño asume el equipo `48b19010`

---

## 2. Arquitectura

```
data/hce/*.json  ──►  data/index.db (SQLite + FTS5)  ──►  servidor MCP
   corpus crudo          índice derivado                  8 herramientas
        ▲                                                  (solo lectura)
        └── refresh ──► api.drapp.la (solo GET)
```

**El corpus JSON es la fuente de verdad.** El índice es derivado: se puede borrar y regenerar sin pérdida. Esto permite cambiar el esquema o el parser de labs sin volver a bajar 1569 pacientes.

**Modelo híbrido.** Las consultas leen el índice local (instantáneo, sin token, offline). Solo `refresh` toca la red.

### Módulos

| Módulo | Responsabilidad | Depende de |
|---|---|---|
| `auth.py` | PKCE, Llavero, renovación de tokens | — |
| `api.py` | Cliente HTTP de drapp, **solo GET** | `auth` |
| `corpus.py` | Leer/escribir `data/hce/*.json`, diffs | `api` |
| `html2text.py` | HTML del editor → texto plano y tablas Markdown | — |
| `labs.py` | Extracción de analitos del texto | `html2text` |
| `index.py` | Esquema SQLite, construcción, consultas | `corpus`, `labs` |
| `server.py` | Definición de herramientas MCP | todos |

Cada módulo se testea aislado. `server.py` solo traduce entre el protocolo MCP y los módulos; no contiene lógica de negocio.

---

## 3. Autenticación

### Hallazgos de la prueba de factibilidad (2026-08-18)

| Mecanismo | Resultado |
|---|---|
| `device_code` | Rechazado: `Grant type not allowed for the client` |
| PKCE con `localhost:8765` | Rechazado: `Callback URL mismatch` |
| **PKCE con `localhost:3000`** | **Aceptado** |

El tenant declara `offline_access` entre los scopes soportados.

### Flujo

1. `login` genera `code_verifier` y `code_challenge` (S256).
2. Levanta un servidor HTTP efímero en `127.0.0.1:3000`.
3. Abre el navegador en `https://auth.drapp.la/authorize` con:
   - `client_id=UfXGb5B0ezKHRGm6fkac6PTfcwmqtlXk`
   - `audience=https://api.drapp.la`
   - `scope=openid profile email offline_access`
   - `redirect_uri=http://localhost:3000`
4. El usuario se autentica **en la pantalla de Auth0 de drapp**. La contraseña nunca pasa por el MCP.
5. Auth0 redirige con `code`; el MCP lo canjea en `/oauth/token` y apaga el servidor.
6. Los tokens se guardan en el **Llavero de macOS** (servicio `drapp-mcp`), nunca en el repo.

### Renovación

Si Auth0 devuelve `refresh_token`, las herramientas renuevan el access token de forma transparente al vencer. Si no lo devuelve (la rotación de refresh tokens podría estar deshabilitada para el cliente SPA — **no verificable sin un login real**), el MCP pide `login` de nuevo con un mensaje claro.

En ambos casos no se almacenan contraseñas y no hay que copiar tokens a mano.

### Reglas

- **Nunca** se persiste una contraseña. El MCP no tiene campo ni parámetro para recibirla.
- El access token vive en memoria; el refresh token, en el Llavero.
- Si el puerto 3000 está ocupado, `login` falla con un mensaje explícito indicando qué proceso lo ocupa. No intenta otro puerto: drapp solo permite ese callback.

---

## 4. Modelo de datos

```sql
CREATE TABLE patients (
  consumer_id  TEXT PRIMARY KEY,
  last_name    TEXT,
  first_name   TEXT,
  full_name    TEXT,
  name_norm    TEXT,      -- minúsculas sin acentos, para búsqueda tolerante
  dni          TEXT,
  dob          TEXT,
  phones       TEXT,
  emails       TEXT,
  financiers   TEXT,
  created_at   TEXT,
  n_records    INTEGER,
  first_visit  TEXT,
  last_visit   TEXT
);

CREATE TABLE records (
  record_id    TEXT PRIMARY KEY,
  consumer_id  TEXT NOT NULL REFERENCES patients(consumer_id),
  section      TEXT NOT NULL,   -- evoluciones|diagnosticos|tratamientos|archivos|...
  date         TEXT,            -- YYYY-MM-DD
  author       TEXT,
  author_norm  TEXT,            -- unifica las firmas de una misma persona
  text         TEXT,            -- contenido en texto plano
  html         TEXT,            -- original, para no perder fidelidad
  code         TEXT,            -- diagnósticos: CIE
  label        TEXT,
  status       TEXT,
  drug         TEXT,            -- tratamientos
  link         TEXT,            -- archivos
  created_at   INTEGER,
  updated_at   INTEGER,
  raw          TEXT             -- JSON completo del registro
);

CREATE VIRTUAL TABLE records_fts USING fts5(
  text, patient_name,
  content='records', content_rowid='rowid',
  tokenize="unicode61 remove_diacritics 2"
);

CREATE TABLE labs (
  record_id   TEXT NOT NULL REFERENCES records(record_id),
  consumer_id TEXT NOT NULL,
  date        TEXT,
  analyte     TEXT NOT NULL,   -- clave canónica: hba1c, tsh, peso...
  value       REAL,
  unit        TEXT,
  source      TEXT NOT NULL,   -- 'tabla' | 'texto'
  snippet     TEXT NOT NULL    -- fragmento original, SIEMPRE presente
);

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
-- last_refresh, n_patients, n_records, schema_version
```

Índices sobre `patients(dni)`, `patients(name_norm)`, `patients(last_visit)`, `records(consumer_id)`, `records(date)`, `records(section)`, `labs(consumer_id, analyte, date)`.

### Normalización de autores

Una misma profesional aparece con cuatro firmas distintas, artefacto de cómo drapp fue guardando el campo:

`Anselmi, MARIA EUGENIA` · `Maru anselmi` · `Anselmi, María Eugenia` · `maruanselmi@gmail.com`

`author_norm` las unifica. El mapeo vive en un diccionario explícito y versionado, no en heurística: dos profesionales podrían tener apellidos parecidos y fusionarlos sería un error clínico.

---

## 5. Herramientas MCP

Todas devuelven, junto al resultado, la antigüedad del corpus. Si supera los 7 días, incluyen una advertencia visible.

### `login`
Sin parámetros. Ejecuta el flujo de §3. Devuelve el usuario autenticado y el vencimiento.

### `status`
Sin parámetros. Devuelve: fecha del último refresh, cantidad de pacientes y registros, validez del token, versión del esquema.

### `refresh`
| Parámetro | Tipo | Default | Descripción |
|---|---|---|---|
| `mode` | `nuevos` \| `todos` | `nuevos` | `nuevos` compara contra el corpus y trae solo lo que cambió |
| `consumer_id` | string | — | Refrescar un solo paciente |

Devuelve el diff: pacientes nuevos, evoluciones nuevas, registros modificados. Reindexa al terminar.

### `find_patient`
| Parámetro | Tipo | Default |
|---|---|---|
| `query` | string (nombre, DNI, email o teléfono) | requerido |
| `limit` | int | 20 |

Búsqueda tolerante a acentos y errores de tipeo. Devuelve `consumer_id`, nombre, DNI, fecha de nacimiento, cantidad de registros y última visita.

### `get_patient`
| Parámetro | Tipo | Default |
|---|---|---|
| `consumer_id` o `dni` | string | uno de los dos |
| `sections` | lista | todas |
| `desde` / `hasta` | fecha | — |
| `limit` | int | 50 |

Devuelve la ficha y los registros en orden cronológico.

### `search_records`
| Parámetro | Tipo | Default |
|---|---|---|
| `query` | string (sintaxis FTS5: `AND`, `OR`, `"frase exacta"`, `term*`) | requerido |
| `desde` / `hasta` | fecha | — |
| `section` | string | `evoluciones` |
| `author` | string | — |
| `limit` | int | 30 |

Devuelve resultados ranqueados por relevancia con fragmento resaltado, paciente, fecha y autor.

### `cohort`
| Parámetro | Tipo | Descripción |
|---|---|---|
| `contiene` | string | término que aparece en alguna evolución |
| `sin_visitas_desde` | fecha | última visita anterior a esa fecha |
| `diagnostico` | string | código CIE o etiqueta |
| `droga` | string | tratamiento registrado |
| `alta_entre` | [fecha, fecha] | rango de alta del paciente |
| `limit` | int | 100 |

Los criterios se combinan con `AND`. Devuelve la lista de pacientes con el motivo de inclusión de cada uno.

### `lab_series`
| Parámetro | Tipo | Default |
|---|---|---|
| `consumer_id` o `dni` | string | uno de los dos |
| `analitos` | lista | todos los detectados |
| `desde` / `hasta` | fecha | — |

Devuelve, por analito, la serie ordenada por fecha. **Cada punto incluye siempre `snippet` y `source`.**

---

## 6. Extracción de labs

El punto más delicado del diseño. Las evoluciones están escritas a mano, con erratas reales (`hba2c` por HbA1c, `Test t 1.82*`) y notación propia de la casa.

### Notación de la casa

| Abreviatura | Significado | Nota |
|---|---|---|
| `PA` | **Peso actual en kg** | **No es presión arterial.** Confirmado por el usuario el 2026-08-18. Un parser genérico produciría una serie de tensión arterial falsa y plausible. |

### Dos orígenes

1. **Tablas estructuradas** (`<table>` en el HTML, típicamente labs pegados desde otra herramienta). Parseo confiable → `source='tabla'`.
2. **Texto libre** (`Lab 9-9-24: HTO 45- HB 15.2 - COL T 153`). Regex sobre un diccionario de analitos → `source='texto'`.

### Diccionario

Cada analito canónico lista sus sinónimos y erratas observadas. Arranca con: `peso` (PA), `hba1c` (hba2c, hemoglobina glicosilada), `glucemia` (gluc), `tsh`, `t4l`, `ldl`, `hdl`, `colesterol_total` (col t), `trigliceridos` (tg), `ferritina`, `insulina`, `homa`, `vitamina_d`, `b12`.

### Reglas duras

1. **Nunca se devuelve un valor sin su `snippet`.** Un número sin fuente verificable es peor que no tener el dato.
2. **Los tokens ambiguos no se adivinan.** Si un token no está en el diccionario, o podría corresponder a más de un analito, va a un bucket `revisar` que se reporta aparte, sin inventar una asignación. Ejemplo real: `tsdh 3.64` aparece junto a `shbg 17` y no está claro qué es.
3. **La cobertura parcial se declara.** `lab_series` informa cuántas evoluciones del paciente tenían labs detectables y cuántas no, para que la ausencia de un valor no se lea como un valor normal.

---

## 7. Seguridad y privacidad

1. **Solo lectura, estructuralmente.** `api.py` expone una única función `get()`. No existe código que haga `POST`, `PUT`, `PATCH` o `DELETE`. No es un flag: la capacidad no está escrita.
2. **Los datos no salen de la máquina.** Corpus e índice son locales. El único tráfico de red es `GET` a `api.drapp.la`.
3. **Sin credenciales en disco.** Ninguna contraseña, nunca. Refresh token en el Llavero.
4. **El repo no lleva datos de pacientes.** `.gitignore` excluye `data/` y `*.db` desde el primer commit.
5. **Procedencia en toda respuesta.** Paciente, fecha, autor y antigüedad del corpus.

---

## 8. Errores

| Situación | Comportamiento |
|---|---|
| Token vencido y sin refresh | Mensaje pidiendo correr `login`. No se intenta nada más. |
| Puerto 3000 ocupado | Falla indicando qué proceso lo ocupa. |
| Índice ausente o desactualizado | Se reconstruye solo desde el corpus. |
| Corpus vacío | Mensaje indicando correr `refresh`. |
| API caída o 5xx | Reintento con backoff; el corpus local sigue sirviendo consultas. |
| Paciente inexistente | Resultado vacío explícito, nunca un error críptico. |

Principio: **una consulta nunca falla por un problema de red.** El índice local responde siempre; solo `refresh` y `login` dependen de la red.

---

## 9. Testing

TDD, con tests unitarios por módulo:

- `html2text` — tablas, listas, entidades, saltos de línea; casos reales del corpus
- `labs` — extracción sobre fragmentos reales, incluida la regla `PA`=peso; casos ambiguos van a `revisar`
- `index` — construcción, consultas FTS, normalización de autores
- `auth` — generación PKCE (`code_challenge` correcto para un verifier conocido); el flujo de red se mockea
- `api` — verificar que **no existe** ningún método de escritura (test explícito)
- `corpus` — diffing entre corpus viejo y nuevo

Los fixtures usan datos reales del corpus. Al ser información clínica, no se commitean: se generan desde `data/hce/` en tiempo de test.

---

## 10. Riesgos abiertos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| El cliente SPA no emite refresh token | Hay que re-loguear cada 24h | Dos clicks en el navegador; se detecta en el primer `login` real |
| El puerto 3000 es el único callback permitido | Conflicto con dev servers | Detección y mensaje claro |
| Cobertura parcial del parser de labs | Valores no detectados | `source`, `snippet` y reporte de cobertura |
| Cambios en la API de drapp | `refresh` deja de funcionar | El corpus local sigue sirviendo; el error es explícito |
| Notación propia no documentada | Malinterpretar valores | Diccionario explícito; los ambiguos van a `revisar` |

---

## 11. Decisiones tomadas

| Decisión | Alternativa descartada | Motivo |
|---|---|---|
| Python + SQLite FTS5 | Node/TypeScript | Reusa el cliente que ya funciona; evita dos lenguajes |
| Híbrido (local + refresh) | Siempre en vivo | La búsqueda de texto completo en vivo exigiría bajar 1569 pacientes por consulta |
| Solo lectura | Lectura y escritura | Historia clínica real con valor legal; un error quedaría firmado con la matrícula del profesional |
| PKCE + Llavero | Usuario/contraseña | No almacena credenciales, sobrevive a MFA, es revocable |
| Índice derivado | Índice como fuente de verdad | Permite cambiar esquema o parser sin re-descargar |
