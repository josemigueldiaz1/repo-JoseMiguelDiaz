# HW1 — RPA, Web Scraping y Lichess API

Autor: José Miguel Díaz

Este repositorio contiene los tres proyectos de la tarea (HW1):

1. **RPA con Selenium** — Registro automático de personal en PeopleSync.
2. **Web Scraping** — Tipo de cambio oficial de SUNAT.
3. **Lichess API** — Análisis de partidas y automatización de torneos.
## Video de presentación

Enlace al video (máx. 9 minutos):https://drive.google.com/file/d/1a5v4uMvwJgFoeEg4vd96rQeJYY22dna9/view?usp=sharing

## Estructura del repositorio

```
HW1_Diaz/
├── README.md
├── requirements.txt
├── 1_RPA_PeopleSync/
│   ├── script/        -> script de Python (.py)
│   ├── input/          -> Excel con los datos de entrada
│   ├── output/         -> CSV de registros que no se pudieron cargar
│   ├── logs/           -> log de ejecución
│   └── task_scheduler/ -> evidencia de la tarea programada en Windows
├── 2_WebScraping_SUNAT/
│   ├── script/
│   ├── output/         -> CSV consolidado del tipo de cambio
│   ├── logs/
│   └── task_scheduler/
└── 3_Lichess_API/
    ├── script/
    ├── output/         -> CSVs y gráficos generados por la Parte A
    ├── logs/
    └── .env.example     -> plantilla para configurar el token de Lichess
```

## Requisitos generales

- Python 3.10 o superior
- Google Chrome instalado (para los proyectos 1 y 2, que usan Selenium)
- Instalar dependencias:

```
pip install -r requirements.txt
```

---

## Proyecto 1 — RPA: Registro de Personal en PeopleSync

**Qué hace:** automatiza el llenado y registro de 50 colaboradores (leídos desde un Excel) en un formulario web (PeopleSync), verificando que cada registro se haya guardado correctamente y manejando errores fila por fila sin detener el proceso completo.

**Cómo correrlo:**

```
cd 1_RPA_PeopleSync/script
python "1. RPA Automation — PeopleSync Income Registration.py" --excel "../input/Ingreso_Personal_Agosto.xlsx"
```

> Por defecto el script busca el Excel **junto a sí mismo** (para que funcione solo con copiar el `.py`). En esta estructura del repositorio el Excel vive en `../input/`, así que hay que indicarlo con `--excel` como en el ejemplo. Lo mismo aplica a `--log-file` y `--report-omitidos` si quieres que caigan en `../logs/` y `../output/` en vez de la carpeta del script.

**Parámetros configurables** (todos opcionales, tienen valores por defecto):

| Parámetro | Descripción | Default |
|---|---|---|
| `--excel` | Ruta al Excel de entrada | junto al script |
| `--url` | URL del formulario | la URL de PeopleSync del curso |
| `--wait-timeout` | Segundos de espera para cada `WebDriverWait` | 10 |
| `--headless` | Corre Chrome sin ventana visible (necesario para Task Scheduler sin sesión interactiva) | desactivado |
| `--log-file` | Ruta del log | junto al script |
| `--report-omitidos` | Ruta del CSV de registros no cargados | junto al script |

**Salidas generadas:** `registros_omitidos.csv` (detalle de cada fila que no se pudo registrar y por qué) y un archivo `.log` con el resumen final (total procesados, exitosos, omitidos).

---

## Proyecto 2 — Web Scraping: Tipo de Cambio Oficial SUNAT

**Qué hace:** extrae el tipo de cambio de compra y venta publicado por SUNAT desde junio de 2024 hasta el mes actual, mes por mes, y consolida un registro por cada día calendario (usando la regla oficial de SUNAT de "arrastrar" el último valor publicado en días sin cotización, como fines de semana y feriados).

**Cómo correrlo:**

```
cd 2_WebScraping_SUNAT/script
python "2. Web Scraping — Official SUNAT Exchange Rate.py" --output "../output/tipo_cambio_sunat.csv" --log-file "../logs/tipo_cambio_sunat.log"
```

> Igual que en el Proyecto 1, por defecto el CSV y el log se guardan junto al script; en esta estructura de carpetas conviene indicar `--output` y `--log-file` explícitamente como arriba.

**Parámetros configurables:**

| Parámetro | Descripción | Default |
|---|---|---|
| `--start-year` / `--start-month` | Inicio del rango a extraer | 2024 / 6 (junio) |
| `--end-year` / `--end-month` | Fin del rango a extraer | año y mes actuales |
| `--output` | Ruta del CSV consolidado | junto al script |
| `--wait-timeout` | Segundos de espera por cada `WebDriverWait` | 25 (cubre el reCAPTCHA de la página) |
| `--delay-seconds` | Pausa entre cada consulta mensual (para no saturar el servidor) | 4 |
| `--headless` | Corre Chrome sin ventana visible | desactivado |
| `--log-file` | Ruta del log | junto al script |

**Salidas generadas:** `tipo_cambio_sunat.csv` (una fila por día, con columnas `fecha`, `compra`, `venta`, `origen` y `fecha_origen_valor`) y un `.log` con el resumen (días publicados, días arrastrados, meses con error).

---

## Proyecto 3 — Lichess API: Análisis y Automatización de Torneos

**Parte A (análisis):** descarga las partidas públicas de un usuario de Lichess, genera un DataFrame, calcula estadísticas de resultados/rating/color/modalidad, y exporta CSVs y gráficos.

**Parte B (automatización):** define un calendario semanal de torneos y los crea vía la API de Lichess. **Corre en modo simulación (dry-run) por defecto — no requiere ninguna credencial para ejecutarse.**

**Cómo correrlo (modo simulación, sin configurar nada):**

```
cd 3_Lichess_API/script
python "3. Lichess API — Data Analysis and Automation.py"
```

**Cómo correrlo con creación real de torneos (Parte B en vivo):**

1. Copia `3_Lichess_API/.env.example` a `3_Lichess_API/.env` (o a la carpeta donde corras el script).
2. Genera un token personal en `https://lichess.org/account/oauth/token` con el permiso **"Create, update and join tournaments"** (`tournament:write`).
3. Pega el token en el archivo `.env`: `LICHESS_TOKEN=tu_token_aqui`.
4. Corre con el flag `--live`:

```
python "3. Lichess API — Data Analysis and Automation.py" --live
```

> El archivo `.env` nunca se sube al repositorio (está protegido en `.gitignore`). Si falta el token y se usa `--live`, el script degrada automáticamente a modo simulación en vez de fallar.

**Parámetros configurables:**

| Parámetro | Descripción | Default |
|---|---|---|
| `--username` | Usuario de Lichess a analizar (Parte A) | `DrNykterstein` (ejemplo público) |
| `--max-games` | Cantidad de partidas a descargar | 100 |
| `--output-dir` | Carpeta de salida de CSVs y gráficos | `lichess_output` junto al script |
| `--live` | Crea torneos reales (Parte B) | desactivado (dry-run) |
| `--request-delay` | Pausa entre llamadas a la API | 1 segundo |
| `--log-file` | Ruta del log | junto al script |

**Salidas generadas:** `partidas_{usuario}.csv`, `estadisticas_resultados.csv`, `estadisticas_por_color.csv`, `estadisticas_por_modalidad.csv`, `estadisticas_resumen_rating.csv`, 4 gráficos PNG, y un `.log` con el resumen de ambas partes.

---

## Automatización con Windows Task Scheduler (Proyectos 1 y 2)

Ambos scripts están configurados como tareas programadas de Windows:

| Tarea | Programa | Trigger | Argumentos |
|---|---|---|---|
| `RPA_PeopleSync_HW1` | `python.exe` | Diario 3:00 AM (+ ejecución manual de prueba) | `--excel`, `--log-file` y `--report-omitidos` con rutas absolutas a `input/`, `logs/` y `output/` |
| `WebScraping_SUNAT_HW1` | `python.exe` | Diario 3:30 AM (+ ejecución manual de prueba) | `--output` y `--log-file` con rutas absolutas a `output/` y `logs/` |

**Evidencia de que corren automáticamente sin intervención manual** (ver carpetas `task_scheduler/` de cada proyecto):

- `*_task_config.xml`: configuración completa de la tarea exportada directamente desde Task Scheduler (`Export-ScheduledTask`).
- `evidencia_ejecucion.log`: log generado por la ejecución que Windows disparó él solo (lanzada con `Start-ScheduledTask`, el equivalente a click derecho → "Ejecutar" en la interfaz de Task Scheduler).

**Resultado de la prueba real** (`Get-ScheduledTaskInfo` → `LastTaskResult: 0` = éxito en ambas):

- `RPA_PeopleSync_HW1`: procesó las 50 filas del Excel, registrando cada una en el formulario real de PeopleSync sin que nadie tocara el teclado.
- `WebScraping_SUNAT_HW1`: recorrió los 27 meses desde junio 2024 hasta agosto 2026, trayendo 812 días con tipo de cambio publicado y arrastrando 5 días sin publicación, con 0 errores.

**Pasos para reproducir esta configuración en otra máquina** (o para el video de presentación):

1. Abrir **Programador de tareas** de Windows.
2. **Acción → Importar tarea...** y seleccionar el `.xml` correspondiente dentro de `task_scheduler/` (esto recrea la tarea exacta, con las mismas rutas si se clona el repo en la misma ubicación, o editando las rutas si se clona en otra).
3. En la Biblioteca del Programador de tareas, click derecho sobre la tarea → **Ejecutar**.
4. Confirmar en la columna "Último resultado de ejecución" que aparece `0x0` (éxito), y revisar el `.log`/CSV generado en `logs/`/`output/` como prueba de que corrió sola.

> Para el video: se recomienda grabar la pantalla del Programador de tareas haciendo click en "Ejecutar" y mostrar cómo Chrome se abre solo, sin que el presentador escriba ningún comando.


