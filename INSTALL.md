# Instalar el MCP de drapp

Guía paso a paso para dejar el servidor funcionando en otra computadora. Son **6 pasos** y toma unos 40 minutos, de los cuales casi todos son esperar descargas.

Al terminar vas a poder preguntarle a Claude cosas como *"¿quién está con Mounjaro?"* o *"¿qué venía haciendo tal paciente?"* sin abrir drapp.

---

## Antes de empezar

| | |
|---|---|
| **Una Mac** | La sesión se guarda en el Llavero y el OCR usa el motor de macOS |
| **Python 3.11 o superior** | Verificá con `python3 --version`. Si falta: `brew install python3` |
| **Tu cuenta de drapp** | La misma con la que entrás a `app.drapp.la`, con acceso al equipo |

No necesitás saber programar. Todos los comandos se copian y pegan.

---

## Paso 1 — Clonar el repositorio

El proyecto vive en un repositorio privado. Pedí que te inviten como colaborador; te llega un mail de GitHub para aceptar. Después:

```bash
cd ~/Documents && git clone https://github.com/mart0vip/mcp-drapp.git drapp
```

Todos los comandos de acá en adelante se corren parado en esa carpeta:

```bash
cd ~/Documents/drapp
```

> **El repositorio no contiene ninguna historia clínica.** Solo el código. Los datos de pacientes los descargás vos con tu propia sesión, y quedan únicamente en tu máquina.

---

## Paso 2 — Instalar

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

Comprobá que quedó bien:

```bash
.venv/bin/pytest -q
```

Tenés que ver `108 passed`. Si ves errores, algo falló en la instalación.

---

## Paso 3 — Iniciar sesión en drapp

```bash
.venv/bin/python -c "from mcp_drapp import auth; print(auth.login())"
```

Se abre el navegador en la pantalla de drapp. **Entrás con tu usuario y contraseña de siempre.** Si ya tenías sesión abierta, te reconoce solo y te avisa que podés cerrar la ventana.

La contraseña la escribís en el sitio de drapp; el servidor nunca la ve ni la guarda. En tu Llavero queda un token que se renueva solo — **este paso se hace una sola vez.**

> **Si dice que el puerto 3000 está ocupado:** drapp solo acepta ese puerto. Liberalo con `lsof -ti:3000 | xargs kill` y reintentá.

---

## Paso 4 — Descargar las historias clínicas

```bash
.venv/bin/python scripts/fetch_hce.py
```

**Entre 15 y 25 minutos** para unos 1575 pacientes. No hace falta exportar ningún CSV: el padrón se lo pide a drapp directamente.

Si se corta —se cae internet, se cierra la notebook— **volvé a correr el mismo comando**: retoma donde quedó.

Al terminar vas a ver algo como `LISTO  ok=1575  fallidos=0`.

---

## Paso 5 — Los adjuntos *(opcional, pero vale la pena)*

Las historias tienen archivos adjuntos: laboratorios en PDF, ecografías, y fotos de laboratorios en papel sacadas con el celular. Sin este paso, su contenido es invisible para la búsqueda.

```bash
.venv/bin/python scripts/bajar_adjuntos.py
.venv/bin/python scripts/extraer_texto_adjuntos.py
```

El primero baja los archivos (unos 155 MB, 5 minutos). El segundo les extrae el texto: usa la capa de texto del PDF cuando existe y **OCR cuando no**, para las fotos y los escaneos. Tarda un minuto.

> **El OCR corre entero en tu máquina**, con el motor de reconocimiento de macOS. Ningún documento clínico sale a un servicio externo.

---

## Paso 6 — Registrar el MCP en Claude

El archivo `.mcp.json` ya viene incluido. Solo hay que **reiniciar Claude Code** estando parado en la carpeta del proyecto.

Comprobá que el servidor arranca:

```bash
.venv/bin/python -c "import asyncio; from mcp_drapp.server import mcp; print(sorted(t.name for t in asyncio.run(mcp.list_tools())))"
```

Tenés que ver las 8 herramientas:

```
['cohort', 'find_patient', 'get_patient', 'lab_series', 'login', 'refresh', 'search_records', 'status']
```

---

## Usarlo

Abrí Claude Code en la carpeta y preguntale en castellano. No hace falta nombrar las herramientas: Claude elige la que corresponde.

### Antes de una consulta

> *"Traeme la historia de Fulano de Tal, DNI 12345678"*
>
> *"¿Qué le indicamos la última vez que vino?"*

### Buscar en todas las evoluciones

> *"¿Qué pacientes tienen hipotiroidismo?"*
>
> *"¿Quiénes están con Ozempic?"*
>
> *"Buscá menciones de insulinorresistencia en 2025"*

### Buscar dentro de los adjuntos

Por defecto la búsqueda mira solo las evoluciones, para que los resultados no se mezclen. Para alcanzar los laboratorios adjuntos, pedilo:

> *"Buscá tirotrofina en los adjuntos"*
>
> *"Buscá hemograma en todo, evoluciones y archivos"*

### Cohortes y gestión

> *"¿Cuántos pacientes no vienen desde enero de 2025?"*
>
> *"Listame los pacientes que mencionan Mounjaro"*
>
> *"¿Cuántos pacientes nuevos entraron este año?"*

### Seguimiento de laboratorio

> *"Mostrame la evolución de HbA1c y peso de esta paciente"*
>
> *"¿Cómo viene la TSH en los últimos dos años?"*

### Mantenimiento

> *"¿Está actualizado el corpus?"*
>
> *"Actualizá los datos"* — trae evoluciones nuevas y descubre pacientes dados de alta desde la última vez. Tarda unos 5 minutos.

---

## Tres cosas importantes

### 1. El servidor casi no puede escribir en drapp

El cliente HTTP solo hace `GET`, con una única excepción: un `POST` a la ruta de búsqueda del padrón, porque drapp no ofrece otra forma de listar los pacientes. Esa ruta está en una lista blanca de un solo elemento y **no existe código capaz de hacer `PUT`, `PATCH` ni `DELETE`**. Hay tests que lo verifican. Es imposible que Claude te modifique una historia clínica.

### 2. `PA` significa peso actual, no presión arterial

Es la notación de esta clínica y el sistema la respeta. La única excepción reconocida es el contexto de MAPA (`mmHg`, `24 h`, formato `119/73`), donde no se interpreta como peso.

### 3. Los valores de laboratorio hay que verificarlos contra el texto original

Las evoluciones están escritas a mano, con abreviaturas y erratas. El extractor:

- Reconoce **36 analitos** y cubre alrededor del **46 %** de las evoluciones.
- Devuelve **cada valor junto al fragmento original** de donde salió. Miralo antes de usar el número.
- **Nunca adivina.** Lo que no reconoce, lo ambiguo y lo fuera de rango van a una lista aparte en vez de convertirse en un dato.
- Informa su propia cobertura: si una serie dice *"13 evoluciones, 4 con labs"*, **la ausencia de un valor no significa que sea normal.**

Ejemplo de lo que evita: una tabla que compara dos fechas en columnas distintas no se parsea, porque no hay forma de saber cuál corresponde a la visita actual. Es preferible no dar el dato a darlo mal.

---

## Privacidad

- Los datos **nunca salen de tu máquina.** El único tráfico de red es la descarga desde drapp. El OCR es local.
- La carpeta `data/` **no se versiona nunca** — está en `.gitignore`.
- Cada instalación descarga su propia copia con su propia sesión.

> **Un dato sobre drapp, no sobre esta herramienta:** los adjuntos viven en un CDN público. Cualquiera con el link accede al laboratorio del paciente, sin credenciales. Las URLs son difíciles de adivinar, pero eso es oscuridad, no control de acceso.

---

## Si algo falla

| Síntoma | Solución |
|---|---|
| `NecesitaLogin` o error 401 | Repetí el paso 3. |
| "El refresh token ya no sirve" | Pasa si quedó un servidor MCP viejo corriendo. Reiniciá Claude Code y repetí el paso 3. |
| "puerto 3000 ocupado" | `lsof -ti:3000 \| xargs kill` y reintentá |
| Las consultas no encuentran nada | Faltó el paso 4. Verificá con `ls data/hce \| wc -l` |
| La búsqueda no ve los adjuntos | Faltó el paso 5. |
| Los datos están viejos | Pedile a Claude que actualice el corpus. |
| Empezar de cero | Borrá `data/index.db`: se reconstruye solo en la próxima consulta. |

Las consultas funcionan **sin conexión y sin sesión**: leen la copia local. Solo `login` y `refresh` necesitan internet.
