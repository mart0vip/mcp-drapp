# Instalar el MCP de drapp

Guía paso a paso para dejar el servidor funcionando en otra computadora. Son **7 pasos** y toma unos 30 minutos, de los cuales 20 son esperar una descarga.

Al terminar vas a poder preguntarle a Claude cosas como *"¿quién está con Mounjaro?"* o *"¿qué venía haciendo tal paciente?"* sin abrir drapp.

---

## Antes de empezar

Necesitás tres cosas:

| | |
|---|---|
| **Una Mac** | El servidor guarda la sesión en el Llavero de macOS |
| **Python 3.11 o superior** | Verificá con `python3 --version`. Si falta: `brew install python3` |
| **Tu cuenta de drapp** | La misma con la que entrás a `app.drapp.la`, con acceso al equipo |

No necesitás saber programar. Todos los comandos se copian y pegan.

---

## Paso 1 — Copiar el código

Pedile a quien te pasa el proyecto una copia de la carpeta `drapp`. Ponela en tu carpeta de Documentos.

> ⚠️ **Importante para quien entrega la copia:** entregá el código **sin el historial de git**. La forma segura es:
>
> ```bash
> cd ~/Documents/drapp && git archive --format=tar HEAD | (mkdir -p /tmp/drapp-limpio && tar -x -C /tmp/drapp-limpio)
> ```
>
> y comprimir `/tmp/drapp-limpio`. El historial de git contiene datos de un paciente real de versiones viejas; el código actual no.

Todos los comandos de acá en adelante se corren parado en esa carpeta:

```bash
cd ~/Documents/drapp
```

---

## Paso 2 — Instalar

Un solo comando. Crea un entorno aislado e instala las dependencias:

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

Verificá que quedó bien:

```bash
.venv/bin/pytest -q
```

Tenés que ver algo como `88 passed`. Si ves errores, algo falló en la instalación.

---

## Paso 3 — Iniciar sesión en drapp

```bash
.venv/bin/python -c "from mcp_drapp import auth; print(auth.login())"
```

Se abre el navegador en la pantalla de login de drapp. **Entrás con tu usuario y contraseña de siempre.** Si ya tenías sesión abierta, te reconoce solo y te dice que podés cerrar la ventana.

La contraseña la escribís en el sitio de drapp; el servidor nunca la ve ni la guarda. Lo único que queda en tu Llavero es un token, que se renueva solo.

> **Si falla con "el puerto 3000 está ocupado":** drapp solo acepta ese puerto. Liberalo con `lsof -ti:3000 | xargs kill` y reintentá.

---

## Paso 4 — Exportar la lista de pacientes

drapp no ofrece forma de listar los pacientes por API, así que hay que exportarla una vez:

1. Entrá a `app.drapp.la`
2. Menú **Reportes** → **Pacientes**
3. Se descarga un archivo `consumers-XXXXXXXX.csv`

Convertilo al formato que necesita el servidor:

```bash
.venv/bin/python scripts/importar_csv.py ~/Downloads/consumers-48b19010.csv
```

Deberías ver `LISTO  1569 pacientes`.

---

## Paso 5 — Descargar las historias clínicas

Este es el paso largo: **entre 15 y 25 minutos** para 1569 pacientes.

```bash
.venv/bin/python scripts/fetch_hce.py
```

Va mostrando el avance. Si se corta (se cae internet, se cierra la notebook), **volvé a correr el mismo comando**: retoma donde quedó, no empieza de cero.

Al terminar decís algo como `LISTO  ok=1569  fallidos=0`.

---

## Paso 6 — Registrar el MCP en Claude

Ya está todo listo. El archivo `.mcp.json` viene incluido, así que solo hay que reiniciar Claude Code estando parado en la carpeta del proyecto.

Comprobá que el servidor arranca:

```bash
.venv/bin/python -c "import asyncio; from mcp_drapp.server import mcp; print(sorted(t.name for t in asyncio.run(mcp.list_tools())))"
```

Tenés que ver las 8 herramientas:

```
['cohort', 'find_patient', 'get_patient', 'lab_series', 'login', 'refresh', 'search_records', 'status']
```

---

## Paso 7 — Usarlo

Abrí Claude Code en la carpeta del proyecto y preguntale en castellano. No hace falta que nombres las herramientas: Claude elige la que corresponde.

### Ejemplos prácticos

**Antes de una consulta**

> *"Traeme la historia de Fulano de Tal, DNI 12345678"*
>
> *"¿Qué le indicamos a Fulano la última vez que vino?"*

**Buscar en todas las evoluciones**

> *"¿Qué pacientes tienen hipotiroidismo?"* → 30 evoluciones
>
> *"¿Quiénes están con Ozempic?"* → 203 evoluciones
>
> *"Buscá menciones de insulinorresistencia en 2025"*

**Cohortes y gestión**

> *"¿Cuántos pacientes no vienen desde enero de 2025?"* → 877
>
> *"Listame los pacientes que mencionan Mounjaro"* → 38
>
> *"¿Quiénes empezaron con GLP-1 y no volvieron en 6 meses?"*

**Seguimiento de laboratorio**

> *"Mostrame la evolución de HbA1c y peso de Fulano"*
>
> *"¿Cómo viene la TSH de esta paciente en los últimos dos años?"*

**Mantenimiento**

> *"¿Está actualizado el corpus?"* → usa `status`
>
> *"Actualizá los datos de Fulano"* → usa `refresh`

---

## Tres cosas importantes

### 1. El servidor **no puede escribir** en drapp

Está diseñado así: el cliente HTTP solo implementa `GET`. No existe código capaz de crear ni modificar una evolución, y hay tests que lo verifican. Es imposible que Claude te ensucie una historia clínica por error.

### 2. `PA` significa **peso actual**, no presión arterial

Es la notación de esta clínica y el sistema la respeta. La única excepción reconocida es el contexto de MAPA (`mmHg`, `24 h`, formato `119/73`), donde no se interpreta como peso.

### 3. Los valores de laboratorio hay que **verificarlos contra el texto original**

Las evoluciones están escritas a mano, con abreviaturas y erratas. El extractor:

- Reconoce **36 analitos** y cubre alrededor del **46%** de las evoluciones.
- Devuelve **cada valor junto al fragmento original** de donde salió. Miralo antes de usar el número.
- **Nunca adivina.** Lo que no reconoce, lo ambiguo y lo fuera de rango van a una lista aparte en vez de convertirse en un dato.
- Informa su propia cobertura: si una serie dice *"13 evoluciones, 4 con labs"*, **la ausencia de un valor no significa que sea normal.**

Ejemplo de lo que evita: una tabla comparativa con columnas de dos fechas distintas no se parsea, porque no hay forma de saber cuál columna corresponde a la visita actual. Es preferible no dar el dato a darlo mal.

---

## Privacidad

- Los datos **nunca salen de tu máquina.** El único tráfico de red es la descarga desde drapp.
- La carpeta `data/` (las historias clínicas) **no se versiona nunca** — está en `.gitignore`.
- Cada instalación descarga su propia copia con su propia sesión. No se comparten archivos de pacientes entre computadoras.

---

## Si algo falla

| Síntoma | Solución |
|---|---|
| `NecesitaLogin` o error 401 | La sesión venció. Repetí el Paso 3. |
| "puerto 3000 ocupado" | `lsof -ti:3000 \| xargs kill` y reintentá |
| Las consultas no encuentran nada | Faltó el Paso 5. Verificá con `ls data/hce \| wc -l` |
| Los datos están viejos | Corré `scripts/fetch_hce.py` de nuevo, o pedile a Claude "actualizá el corpus" |
| Quiero empezar de cero | Borrá `data/index.db`; se reconstruye solo en la próxima consulta |

Las consultas funcionan **sin conexión y sin sesión**: leen la copia local. Solo `login` y `refresh` necesitan internet.
