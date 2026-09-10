# HW2 — La hora dorada: accesibilidad por carretera a establecimientos de salud resolutivos en el Perú

Autor: José Miguel Díaz

> **Pregunta de investigación.** ¿Cuánto tiempo tarda *realmente*, por carretera, la
> población de una región en llegar a un establecimiento de salud con capacidad resolutiva,
> y dónde están las peores brechas?

En el Perú los puestos de salud I-1 pueden estabilizar a un paciente, pero no operar ni
hacer una cesárea. Solo los establecimientos de categoría **II-1 en adelante** tienen
capacidad resolutiva. Este proyecto mide la distancia real —por red vial, no en línea
recta— entre dónde vive la gente y dónde puede efectivamente ser atendida.

## Ámbito

Tres departamentos, uno por región natural, para que el contraste geográfico sea el eje
del análisis:

| Departamento | Región | Por qué |
|---|---|---|
| **Lambayeque** | Costa | Compacto, red vial densa, alta densidad poblacional |
| **Ayacucho** | Sierra | Topografía andina: el tiempo real se despega de la distancia euclidiana |
| **Loreto** | Selva | Conectividad fluvial, no vial: es donde se rompe el supuesto "existe una carretera" |

Los departamentos se declaran en [`config.md`](config.md) y **se pueden cambiar sin tocar
código**.

---

## Estado del proyecto

| Fase | Descripción | Puntos | Estado |
|---|---|---:|---|
| 1 | Adquisición y validación de datos | 3.0 | ✅ Completa · 41/41 verificaciones |
| 2 | Ruteo y cálculo de tiempos de viaje | 3.0 | ✅ Completa · 26/26 verificaciones |
| 3 | Construcción de métricas | 2.0 | ✅ Completa · 51/51 verificaciones |
| 4 | Dashboard Streamlit | 2.5 | ✅ Completa · 25/25 verificaciones |
| 5 | Informe LaTeX | 1.5 | ✅ Completa · 36/36 verificaciones · 12 páginas |

### Resultado principal

Porcentaje de población según cuánto tarda por carretera en llegar a un establecimiento con
capacidad resolutiva:

| Departamento | ≤30 min | 30-60 | 60-120 | >120 min | **Sin acceso vial** |
|---|---:|---:|---:|---:|---:|
| Lambayeque (costa) | **82 %** | 10 % | 5 % | 2 % | 0.8 % |
| Ayacucho (sierra) | 58 % | 15 % | 16 % | 7 % | 4.3 % |
| Loreto (selva) | 35 % | 5 % | 2 % | 20 % | **38 %** |
| **Total ámbito** | 62.3 % | 9.9 % | 6.8 % | 8.8 % | **12.2 %** |

**El 72.2 % de la población llega en menos de una hora a un establecimiento que puede
operarla. El 12.2 % no llega por carretera en absoluto.** En Loreto, sumando los que tardan
más de dos horas y los que no tienen acceso vial, el **58 % está mal servido**.

Otros tres resultados que el informe desarrolla:

- **La red vial no sirve a Loreto.** El centro poblado mediano está a 8.9 km de la carretera
  más cercana (frente a 107 m en Lambayeque), y el 78 % de ellos queda fuera de la red. La
  conclusión resiste cualquier umbral: incluso con 10 km, Ayacucho cae a 0.0 % y Loreto sigue
  en 24 %.
- **La población rural de Loreto tarda 23 horas de media** y casi tres de cada cuatro
  personas no tienen acceso por carretera.
- **La pobreza predice el acceso solo donde la geografía no manda ya**: correlación fortísima
  en Lambayeque (*r* = 0.80), inexistente en Loreto (*p* = 0.28).

El detalle de cada hallazgo, con sus números y sus salvedades, está en
[`logs/material_video.md`](logs/material_video.md).

---

## Instalación

### Requisitos previos

| Requisito | Por qué |
|---|---|
| **Python 3.11 o superior** | El pipeline lee `config.md` con `tomllib`, que entró a la biblioteca estándar en 3.11 |
| **Docker Desktop** | **Obligatorio.** La Fase 2 rutea contra tres servidores OSRM que corren en contenedores. Sin Docker, el pipeline no se puede ejecutar completo |
| **Windows** | `scripts/osrm.ps1`, que compila y levanta los grafos de OSRM, es un script de PowerShell |

> ### ⚠️ Docker es obligatorio
>
> **Este proyecto no corre sin Docker Desktop instalado y con el motor arrancado.** La Fase 2
> —el corazón del trabajo— calcula tiempos de viaje reales pidiéndoselos a
> [OSRM](https://project-osrm.org/), que se ejecuta en contenedores. No hay modo alternativo:
> `src/routing.py` lanza `OSRMNoDisponible` y detiene el pipeline si los servidores no
> responden, en lugar de sustituir los tiempos por distancias en línea recta. Es una decisión
> deliberada: un resultado silenciosamente falso es peor que un error.
>
> Antes de correr nada, abre Docker Desktop y espera a que diga **"Engine running"**. Luego
> sigue las instrucciones de [Fase 2: motor de ruteo](#fase-2-motor-de-ruteo): hay que
> descargar el extracto OSM del Perú (~244 MB) y compilar los tres grafos. Medido en la
> máquina de desarrollo, esa compilación tarda **unos 2.5 minutos por perfil (≈ 7.5 min los
> tres)** y deja ~2.1 GB por perfil en `C:\osrm-hw2\`. Es un costo que se paga **una sola
> vez**: después basta con `.\scripts\osrm.ps1 serve all`, que tarda segundos.

### Entorno de Python

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux / macOS
pip install -r requirements.txt
```

> **Nota sobre GeoPandas.** El proyecto exige `geopandas >= 1.0`. Con la combinación
> `geopandas 0.14.x` + `fiona >= 1.10` la lectura de shapefiles falla con
> `module 'fiona' has no attribute 'path'`, porque `fiona.path` se eliminó en 1.10.
> El I/O vectorial va por `pyogrio`, que además es bastante más rápido.

---

## Cómo correrlo

> **Antes de nada: Docker Desktop tiene que estar abierto y con el motor corriendo.** Sin
> eso la Fase 2 se detiene con `OSRMNoDisponible`. Ver [Instalación](#requisitos-previos).

Un único punto de entrada, y **sin argumentos corre todo**:

```bash
python run_pipeline.py
```

Eso es literalmente todo. En VS Code basta con abrir `run_pipeline.py` y pulsar **▶ Run**.
El script, por su cuenta:

1. Ejecuta **todas** las fases implementadas en orden (`--phase` vale `all` por defecto).
2. **Regenera lo que falte**: si borraste salidas, las reconstruye.
3. **Arranca los contenedores de OSRM** si están detenidos (por ejemplo, tras reiniciar).
4. **Verifica los resultados** al terminar y te dice si todo está bien.

Salida esperada:

```
Modo 'all': se ejecutaran en secuencia las fases 1, 2, 3
FASE 1 COMPLETA en 0.3 min
  3 perfil(es) de OSRM no responden; intentando arrancarlos...
  OSRM listo: los 3 perfiles responden
FASE 2 COMPLETA en 0.5 min
FASE 3 COMPLETA en 0.1 min
VERIFICACION DE LOS RESULTADOS
  Las 41 verificaciones pasaron
  Las 26 verificaciones pasaron
  Las 49 verificaciones pasaron
TODO CORRECTO: las fases 1, 2, 3 se ejecutaron y verificaron sin errores.
```

> **Requisito único de configuración, una sola vez:** que VS Code use el intérprete del
> entorno. `Ctrl+Shift+P` → *Python: Select Interpreter* →
> `C:\Users\josem\.venvs\hw2-geo\Scripts\python.exe`. El repositorio trae un
> `.vscode/settings.json` que ya lo apunta; si abres la carpeta `HW2_Diaz` directamente, VS
> Code lo toma solo.

Para ejecutar una fase concreta:

```bash
python run_pipeline.py --phase 1
```

| Opción | Efecto |
|---|---|
| `--phase N` | Fase a ejecutar (`1`..`5`) |
| `--phase all` | Todas las fases implementadas, en secuencia |
| `--with-osm` | Descarga además el extracto OSM del Perú (~244 MB, necesario en la Fase 2) |
| `--hi-res-pop` | Usa el ráster WorldPop *unconstrained* (~596 MB) en vez del de 6 MB |
| `--force-download` | Ignora el caché de `data/raw/` y vuelve a descargar todo |
| `--force-routing` | Ignora el caché de ruteo y recalcula snapping y matrices |
| `--skip-map` | Omite el mapa interactivo Folium (corrida más rápida) |
| `-v`, `--verbose` | Log en nivel DEBUG |

### Fase 4: el dashboard

```bash
streamlit run app.py
```

Se abre en `http://localhost:8501`. **No necesita OSRM ni Docker**: lee únicamente los
archivos que el pipeline dejó en disco, así que arranca en segundos y funciona con todo
apagado. No entra en `--phase all` porque no es un paso de pipeline, sino una app que se
queda corriendo.

Las siete vistas: cabecera de KPIs, mapa coroplético con capa de establecimientos, ECDF del
tiempo de acceso, barras de cobertura, tabla descargable de peores distritos, **simulador de
escenarios** y panel de calidad de datos.

El simulador permite "ascender" cualquiera de los **406 establecimientos I-3/I-4** a
resolutivo y recalcula la cobertura al instante, usando una matriz de tiempos precomputada.

Para comprobar que funciona sin abrir el navegador:

```bash
python verify.py --phase 4
```

Eso **ejecuta la app de verdad** con `streamlit.testing.v1.AppTest` en varios escenarios,
incluida la selección vacía de filtros.

### Fase 5: el informe

```bash
python run_pipeline.py --phase 5
```

Compila `report/main.tex` a `report/main.pdf` (**12 páginas**). **Ninguna cifra del informe
está tecleada a mano**: las 6 tablas entran con `\input` desde `report/tablas/` y las 5
figuras son PDF vectorial exportado por matplotlib. Si cambian los datos, se recompila y el
informe queda al día — no puede desincronizarse.

El compilador es **[Tectonic](https://tectonic-typesetting.github.io/)**, un binario único
que descarga solo los paquetes que el documento necesita, sin instalar una distribución
completa de LaTeX. La ruta se declara en `config.md` §10; si no encuentra ningún compilador,
la fase avisa y deja el `.tex` listo para Overleaf, que el enunciado admite.

> La primera compilación tarda ~4 minutos porque Tectonic va trayendo los paquetes. Las
> siguientes tardan **7 segundos**.

### El pipeline se repara solo

**Se puede borrar cualquier salida y volver a ejecutar: lo que falte se regenera.** Cada fase
declara de qué depende y qué archivos produce, así que el pipeline resuelve sus insumos como
lo haría un sistema de *build*:

```powershell
# Borras todo data/processed y pides solo la Fase 2...
python run_pipeline.py --phase 2
#   [WARNING] La Fase 1 se regenera: faltan 3 de sus salidas
#   FASE 1 COMPLETA en 0.3 min
#   FASE 2 COMPLETA en 0.0 min
```

La regla es la de un *build*: **la fase que pides siempre se ejecuta; las fases de las que
depende se ejecutan solo si sus salidas faltan o quedaron desfasadas.** Volver a correr algo
ya calculado sigue costando segundos.

Además detecta un caso concreto que llegó a ocurrir durante el desarrollo: si los datos
procesados corresponden a un **ámbito distinto** del que declara `config.md` hoy —porque se
cambió la configuración sin regenerar—, la Fase 1 se rehace sola. Rutear sobre datos de otro
ámbito habría producido resultados silenciosamente equivocados: sin excepción, sin
advertencia, con números plausibles.

### Cuánto tarda

Medido con el caché ya construido:

| Comando | Tiempo |
|---|---:|
| `--phase 1` | 19.6 s |
| `--phase 2` | 3.6 s |
| `--phase 3` | 1.5 s |
| `--phase all` (las 3 fases + 116 verificaciones) | **21.9 s** |
| `verify.py --phase N` | 0.7 s cada una |

Con `data/processed/` borrado, `--phase 2` tarda 23.5 s porque regenera la Fase 1 primero.
Cambiar un departamento en `config.md` cuesta ~3 min, porque invalida el caché de ruteo.

La primera corrida descarga ~70 MB y tarda unos minutos. **Las siguientes reutilizan
`data/raw/` y no vuelven a descargar nada**: el paso de adquisición compara el tamaño local
contra el que anuncia el servidor y solo baja lo que falta o cambió.

### Verificar que la fase corrió bien

```bash
python verify.py --phase 1
```

`verify.py` no repite la lógica del pipeline: vuelve a leer los archivos que quedaron en
disco y comprueba las invariantes que deben cumplirse (CRS, unicidad de claves, integridad
referencial entre demanda y distritos, que `es_resolutiva` sea exactamente la regla
declarada en `config.md`, coherencia de los flags de validación, que las 6 reglas estén
reportadas con justificación, y que el manifiesto traiga SHA-256 y fecha). Devuelve código
de salida 0 si todo pasa y 1 si algo falla.

Estado actual: **41/41 · 26/26 · 51/51 · 25/25 · 36/36 = 179 comprobaciones**. Al correr sin argumentos, las tres se verifican solas al terminar.

### Fase 2: motor de ruteo

La Fase 2 necesita **OSRM** corriendo en local, lo que a su vez requiere **Docker Desktop**
con el motor **WSL2**. OSRM está escrito en C++ y solo se distribuye para Linux: no existe
versión nativa de Windows.

```powershell
# 1. Descargar el extracto de OpenStreetMap del Peru (244 MB, una sola vez)
python run_pipeline.py --phase 1 --with-osm

# 2. Compilar los grafos: ~2.5 min por perfil, ~2.1 GB cada uno
.\scripts\osrm.ps1 build all

# 3. Levantar los tres servidores (car:5000, foot:5001, bike:5002)
.\scripts\osrm.ps1 serve all
.\scripts\osrm.ps1 status

# 4. Correr la fase
python run_pipeline.py --phase 2
python verify.py --phase 2
```

> **Los contenedores no arrancan solos tras reiniciar la máquina.** Los grafos quedan
> compilados en `C:\osrm-hw2\`, así que basta con `.\scripts\osrm.ps1 serve all`, que es
> instantáneo. Ese directorio está **fuera de OneDrive** a propósito: son ~6 GB entre los
> tres perfiles.

`scripts/osrm.ps1` acepta `build`, `serve`, `stop` y `status`, y como segundo argumento
`car`, `foot`, `bike` o `all`.

Si algún perfil no responde, la Fase 2 lo omite y sigue con los disponibles, avisando en el
log. Solo `car` es obligatorio.

---

## Estructura

```
HW2_Diaz/
├── config.md                  # ← única fuente de verdad de TODOS los parámetros
├── requirements.txt
├── README.md
├── run_pipeline.py            # ← punto de entrada: python run_pipeline.py --phase 1
├── verify.py                  # ← comprueba los productos: python verify.py --phase 1
├── src/
│   ├── config.py              # parsea los bloques ```toml de config.md
│   ├── acquisition.py         # Fase 1 — descarga reproducible + manifiesto
│   ├── validation.py          # Fase 1 — las 6 reglas de calidad + reporte
│   ├── supply.py              # Fase 1 — dataset de oferta (RENIPRESS)
│   ├── demand.py              # Fase 1 — dataset de demanda (CCPP + población)
│   ├── io_utils.py            # escritura en el formato declarado en config.md
│   └── export.py              # figuras y mapas
├── data/
│   ├── raw/                   # descargas intactas (no versionadas; ver _manifest.json)
│   ├── processed/             # GeoParquet + GeoPackage
│   ├── outputs/               # tablas CSV y reportes
│   └── cache/                 # caché de ruteo (Fase 2)
├── report/
│   └── figures/
└── logs/                      # evidencia de ejecución, un archivo por corrida
```

`config.md` es a la vez documentación legible y configuración ejecutable: `src/config.py`
extrae los bloques ` ```toml ` del propio Markdown y los parsea. No hay dos copias de los
parámetros que se puedan desincronizar.

---

## Fase 1 — Adquisición y validación

### Fuentes de datos

| Fuente | Uso | Formato | Licencia |
|---|---|---|---|
| [RENIPRESS](https://www.datosabiertos.gob.pe/dataset/registro-nacional-de-entidades-prestadoras-de-servicios-de-salud-renipress) (SUSALUD), corte 31-08-2026 | Oferta: establecimientos de salud | CSV | Datos Abiertos Perú |
| RENIPRESS corte 30-04-2026 | Comparación temporal (innovación) | CSV | Datos Abiertos Perú |
| [Centros Poblados](https://www.datosabiertos.gob.pe/dataset/dataset-centros-poblados) (IGN) | Demanda: puntos de población | Shapefile | Datos Abiertos Perú |
| [Límites Distritales](https://www.datosabiertos.gob.pe/dataset/limites-departamentales) (IGN) | Fronteras administrativas | Shapefile | Datos Abiertos Perú |
| [WorldPop 2020](https://www.worldpop.org/) 100 m, *constrained*, ajustado ONU | Población por centro poblado | GeoTIFF | CC BY 4.0 |
| [Geofabrik Perú](https://download.geofabrik.de/south-america/peru-latest.osm.pbf) | Red vial (Fase 2) | OSM PBF | ODbL |

Cada descarga queda registrada en `data/raw/_manifest.json` con URL efectiva, fecha UTC,
tamaño y **SHA-256**, para que el informe pueda citar la versión exacta de los datos.

#### Dos sustituciones documentadas

1. **SIGMED (MINEDU) → Centros Poblados del IGN.** El enunciado señala SIGMED como fuente
   de centros poblados, pero es una aplicación interactiva de ArcGIS sin URL de descarga
   directa: requiere aceptar términos, navegar un visor y generar el archivo a mano, así
   que no es automatizable ni reproducible. Se sustituye por el shapefile de centros
   poblados del IGN publicado en Datos Abiertos, que cubre la misma necesidad y sí es
   descargable de forma programática.

2. **Población imputada con WorldPop.** El shapefile del IGN trae 136 587 centros poblados
   con coordenadas, pero **sin población**, y la Fase 3 exige que toda agregación sea
   ponderada. Ver la sección siguiente.

### Imputación de población

Cada celda del ráster WorldPop (100 m) se asigna al **centro poblado más cercano dentro de
su mismo distrito**; la población de un centro poblado es la suma de las celdas que le
tocaron.

Por qué así y no con un buffer de radio fijo:

- **Conserva el total.** La suma por distrito coincide exactamente con la del ráster. Un
  buffer de radio fijo deja fuera a la población dispersa y cuenta dos veces la de los
  buffers que se solapan.
- **Respeta la frontera administrativa.** La población de un distrito nunca se atribuye al
  centro poblado de otro, aunque esté más cerca en línea recta.
- **Modela la dispersión rural.** En la Amazonía un centro poblado "representa" un área
  enorme; el método se la asigna sin fijar un radio arbitrario.

*Limitación:* la asignación es por proximidad euclidiana, no por red vial.

### Definición de capacidad resolutiva

Un establecimiento es resolutivo **si y solo si** está activo **y** su categoría está en el
whitelist `II-1, II-2, II-E, III-1, III-2, III-E`. Las categorías I-1 a I-4 se conservan en
el dataset (alimentan el simulador de escenarios de la Fase 4) pero se excluyen del cálculo
de establecimiento más cercano.

La categoría llega sucia en el registro, así que se normaliza con reglas explícitas y
visibles en `src/validation.py:normalizar_categoria`: nulos, cadena vacía y el literal
`"0"` pasan a `SIN_CATEGORIA`; se unifican guiones tipográficos y separadores; se inserta
el guion cuando falta (`II1` → `II-1`); lo que no cae en el conjunto canónico se marca como
sin categoría en lugar de adivinarse.

### Las seis reglas de validación

| Regla | Qué detecta | Acción |
|---|---|---|
| **R1** | Coordenadas ausentes, nulas o `(0,0)` | Retenido con `coord_valida=False`, excluido del ruteo |
| **R2** | Coordenadas fuera del *bounding box* del Perú | Retenido con advertencia |
| **R3** | Latitud y longitud intercambiadas | **Corregido** (recuperación determinística) |
| **R4** | Punto fuera del distrito que el propio registro declara | Tolerancia de borde → corregido; conflicto real → retenido |
| **R5** | Códigos `COD_IPRESS` duplicados | Marcado `es_duplicado`, se conserva la primera aparición |
| **R6** | Problemas de codificación UTF-8 / latin-1 | **Corregido** |

Ninguna regla borra filas en silencio. Cada una reporta cuántos registros marcó, qué se
hizo y por qué, en `data/outputs/data_quality_oferta.{csv,md}`.

**R3 es 100 % recuperable en el Perú** porque los rangos de latitud (−18.4 a −0.04) y
longitud (−81.4 a −68.6) son disjuntos: un par intercambiado solo admite una lectura.

**Sobre R6, un hallazgo concreto:** el CSV de RENIPRESS viene en **UTF-8 con BOM**. Leerlo
como latin-1 —el reflejo habitual con datos peruanos— renombra la primera columna de
`INSTITUCION` a `ï»¿INSTITUCION` y llena de mojibake los campos con tildes. Por eso el
encoding es un parámetro de `config.md` y no un valor incrustado en el código.

**Sobre las coordenadas de RENIPRESS:** las columnas se llaman `NORTE` y `ESTE`, pero
contienen **latitud** y **longitud** respectivamente. Los nombres invitan al error
contrario; la asignación se verificó contra los rangos reales del archivo antes de fijarla.

### Salidas de la Fase 1

| Archivo | Contenido |
|---|---|
| `data/processed/oferta_salud.parquet` | IPRESS del ámbito, validadas, con `es_resolutiva` y `apto_para_ruteo` |
| `data/processed/demanda_ccpp.parquet` | Centros poblados con población imputada y clasificación urbano/rural |
| `data/processed/distritos.parquet` | Límites distritales del ámbito |
| `data/outputs/data_quality_oferta.csv` / `.md` | Reporte de calidad, regla por regla |
| `data/outputs/resumen_fase1.csv` | Resumen por departamento |
| `data/outputs/comparacion_temporal_renipress.csv` | Rotación del registro entre cortes (innovación) |
| `data/outputs/mapa_validacion_fase1.html` | Mapa Folium de control visual |
| `report/figures/fase1_ambito.png`, `fase1_calidad.png` | Figuras para el informe |
| `logs/fase1_*.log` | Evidencia de ejecución |

Los datasets se guardan en **GeoParquet** y, además, en **GeoPackage** para poder abrirlos
directamente en QGIS.

---

## Innovación

Elementos implementados por encima del mínimo exigido:

- **Comparación temporal del registro.** Se descargan dos cortes de RENIPRESS (abril y
  agosto 2026) y se mide la rotación real: altas, bajas, cambios de categoría y de estado,
  y cuántos establecimientos ganaron o perdieron capacidad resolutiva entre ambas fechas.
  Si la oferta cambia mes a mes, el resultado del estudio tiene fecha de caducidad, y eso
  el informe debe declararlo.
- **Población imputada con ráster WorldPop** conservando el total distrital, en lugar de
  repartir la población del distrito en partes iguales.
- **Trazabilidad criptográfica.** Manifiesto con SHA-256 y fecha UTC de cada descarga.
- **Mapa interactivo de control de validación** con capas conmutables, que permite
  verificar visualmente que la validación hizo lo que el reporte dice antes de invertir
  horas en el ruteo.
- **Cadenas de respaldo por fuente.** Cada fuente declara varias URLs; el pipeline las
  intenta en orden y registra cuál funcionó, para sobrevivir a caídas de los portales.

Pendientes para fases siguientes: 2SFCA, optimización de localización de nuevos
establecimientos, cuantificación de incertidumbre por bootstrap sobre las tasas de error de
coordenadas halladas en la Fase 1, e isócronas.

---

## Video de presentación

Enlace (máx. 12 minutos): _pendiente_.

---

## Referencias de datos

- SUSALUD (2026). *Registro Nacional de Entidades Prestadoras de Servicios de Salud (RENIPRESS)*, cortes 30-04-2026 y 31-08-2026.
- Instituto Geográfico Nacional (2020). *Centros Poblados del Perú*, escala 1:100 000.
- Instituto Geográfico Nacional. *Límites Distritales del Perú*.
- WorldPop (2020). *Global High Resolution Population Denominators Project*. University of Southampton. https://dx.doi.org/10.5258/SOTON/WP00660
- OpenStreetMap contributors / Geofabrik GmbH. *Peru OSM extract*.
