# `config.md` — Parámetros del proyecto

Este archivo es la **única fuente de verdad** de la configuración del pipeline. No es
documentación decorativa: `src/config.py` lo lee y parsea los bloques ` ```toml ` que
contiene, de modo que cambiar un departamento, un umbral o una URL aquí cambia el
comportamiento del pipeline **sin tocar una sola línea de código**.

```python
from src.config import load_config
cfg = load_config()          # lee este mismo archivo
cfg.departamentos            # ['LAMBAYEQUE', 'AYACUCHO', 'LORETO']
```

---

## 1. Ámbito geográfico

Tres departamentos, uno por región natural, según exige el enunciado. Los nombres deben
escribirse **exactamente** como aparecen en RENIPRESS y en el shapefile del IGN
(mayúsculas, sin tildes en los casos en que la fuente no las trae).

```toml
[ambito]
departamentos = ["LAMBAYEQUE", "AYACUCHO", "LORETO"]

# Etiqueta de región natural para cada departamento. Se usa en los gráficos y en el
# informe para explicar el contraste costa / sierra / selva.
[ambito.region_natural]
LAMBAYEQUE = "Costa"
AYACUCHO   = "Sierra"
LORETO     = "Selva"
```

> **Por qué estos tres.** Lambayeque es costero, compacto y con red vial densa.
> Ayacucho es andino, con topografía que alarga los tiempos reales muy por encima de la
> distancia euclidiana. Loreto es amazónico y su conectividad es fluvial, no vial: es el
> caso donde el supuesto "existe una carretera" se rompe, y por eso es el más informativo.

---

## 2. Definición de establecimiento resolutivo

Un establecimiento es **resolutivo** si y solo si está activo **y** su categoría
pertenece al whitelist. Ambas condiciones se evalúan sobre los campos ya normalizados.

```toml
[resolutivo]
# Categorías con capacidad resolutiva (pueden operar / hacer cesáreas).
categorias = ["II-1", "II-2", "II-E", "III-1", "III-2", "III-E"]

# Valores del campo ESTADO que cuentan como "en operación".
estados_activos = ["ACTIVO"]

# Categorías que existen en el registro pero NO son resolutivas. Se conservan en el
# dataset (el enunciado lo exige) y alimentan el simulador de escenarios de la Fase 4.
categorias_no_resolutivas = ["I-1", "I-2", "I-3", "I-4"]

# Categorías candidatas a "ascenso" en el simulador de escenarios (Fase 4).
categorias_ascendibles = ["I-3", "I-4"]
```

---

## 3. Reglas de validación

Umbrales de las seis reglas obligatorias de la Fase 1.

```toml
[validacion]
# Bounding box del territorio peruano continental (grados decimales).
lon_min = -81.4
lon_max = -68.6
lat_min = -18.4
lat_max = -0.04

# Tolerancia al verificar que un punto cae dentro del polígono del distrito que declara.
# Absorbe el error de digitalización del límite distrital (~200 m a esta latitud).
tolerancia_distrito_grados = 0.002

# Encoding real de los CSV de RENIPRESS. El archivo viene en UTF-8 CON BOM: leerlo como
# latin-1 corrompe la primera columna del header y mete mojibake en los nombres.
encoding_renipress = "utf-8-sig"
encoding_fallback  = "latin-1"
separador_renipress = ";"

# Si un registro puede recuperarse (coordenadas invertidas, mojibake reparable), se
# corrige y se documenta. Si no, se marca y se excluye del cálculo, nunca se borra en
# silencio.
corregir_coordenadas_invertidas = true
reparar_mojibake = true
```

---

## 4. Demanda: población por centro poblado

El shapefile oficial de centros poblados (IGN) **no trae población**, y la Fase 3 exige
que toda agregación sea ponderada por población. La población se imputa asignando cada
celda del ráster WorldPop al centro poblado más cercano *dentro de su mismo distrito*,
de modo que el total distrital se conserva exactamente.

```toml
[demanda]
# Método de imputación de población. "worldpop_vecino_cercano" reparte el ráster entre
# los centros poblados del distrito; "uniforme" reparte la población distrital en partes
# iguales (solo como respaldo si el ráster no está disponible).
metodo_poblacion = "worldpop_vecino_cercano"

# Umbral INEI: un centro poblado con 2 000 o más habitantes se considera urbano.
umbral_urbano_habitantes = 2000

# Categorías de CAT_POBLAD que se consideran urbanas con independencia del umbral.
categorias_urbanas = ["CIUDAD", "VILLA", "PUEBLO", "PP.JJ.AA.HH.", "BARRIO O CUARTEL"]

# Umbral para descartar centros poblados por población imputada. Se deja en 0 a propósito.
# El ráster "constrained" solo asigna población donde detecta edificaciones, así que muchos
# caseríos reales reciben 0 habitantes. Descartarlos borraría del mapa asentamientos que sí
# existen, y justo en las zonas rurales donde el estudio busca las brechas. Como toda
# agregación es ponderada por población, un punto con peso 0 no distorsiona ninguna métrica:
# conservarlo no cuesta nada y perderlo sí.
poblacion_minima = 0.0
```

---

## 5. Fuentes de datos

Cada fuente declara una **cadena de respaldo**: si la URL primaria falla, el módulo de
adquisición intenta la siguiente y registra en el log cuál se usó realmente. Esto cubre
el caso previsto en el enunciado de portales peruanos caídos o sin URL directa.

```toml
[fuentes.renipress]
descripcion = "Registro Nacional de IPRESS (RENIPRESS / SUSALUD)"
archivo     = "RENIPRESS_31-08-2026.csv"
urls = [
  "https://www.datosabiertos.gob.pe/sites/default/files/RENIPRESS_31-08-2026.csv",
]
licencia = "Datos Abiertos Gobierno del Perú"
cita     = "SUSALUD (2026). Registro Nacional de Entidades Prestadoras de Servicios de Salud."

[fuentes.renipress_anterior]
descripcion = "RENIPRESS de abril 2026 — se usa solo para la comparación temporal (innovación)"
archivo     = "RENIPRESS_30-04-2026.csv"
opcional    = true
urls = [
  "https://www.datosabiertos.gob.pe/sites/default/files/RENIPRESS_30-04-2026.csv",
]
licencia = "Datos Abiertos Gobierno del Perú"
cita     = "SUSALUD (2026). RENIPRESS, corte 30-04-2026."

[fuentes.centros_poblados]
descripcion = "Centros poblados a nivel nacional (shapefile)"
archivo     = "CCPP_0.zip"
urls = [
  "https://www.datosabiertos.gob.pe/sites/default/files/CCPP_0.zip",
]
licencia = "Datos Abiertos Gobierno del Perú"
cita     = "Instituto Geográfico Nacional (IGN). Centros Poblados, escala 1:100 000."
nota     = """El portal SIGMED del MINEDU que indica el enunciado es una aplicación
interactiva sin URL de descarga directa, por lo que no es automatizable. Se sustituye por
el shapefile de centros poblados del IGN publicado en Datos Abiertos, que cubre la misma
necesidad (puntos de demanda georreferenciados) y sí es descargable de forma reproducible.
La sustitución queda documentada en el informe."""

[fuentes.distritos]
descripcion = "Límites distritales oficiales"
archivo     = "DISTRITOS_LIMITES.zip"
urls = [
  "https://www.datosabiertos.gob.pe/sites/default/files/DISTRITOS_LIMITES.zip",
]
licencia = "Datos Abiertos Gobierno del Perú"
cita     = "Instituto Geográfico Nacional (IGN). Límites distritales."

[fuentes.poblacion_raster]
descripcion = "WorldPop 2020, 100 m, constrained, ajustado a proyecciones ONU"
archivo     = "per_ppp_2020_UNadj_constrained.tif"
urls = [
  "https://data.worldpop.org/GIS/Population/Global_2000_2020_Constrained/2020/BSGM/PER/per_ppp_2020_UNadj_constrained.tif",
]
licencia = "Creative Commons Attribution 4.0"
cita     = "WorldPop (2020). Global High Resolution Population Denominators Project. University of Southampton."
nota     = """Se usa el producto *constrained*, que solo asigna población a celdas donde
detecta edificación. Pesa 6 MB y reproduce bien los totales de Lambayeque y Ayacucho, pero
subestima Loreto (~24%) porque muchos asentamientos amazónicos dispersos no tienen
edificación detectable desde satélite. Es una limitación conocida y declarada en el informe.
Para corregirla existe la fuente opcional `poblacion_raster_alta_res`."""

[fuentes.poblacion_raster_alta_res]
descripcion = "WorldPop 2020 unconstrained (asigna población también fuera de zonas edificadas)"
archivo     = "per_ppp_2020_UNadj.tif"
opcional    = true          # ~596 MB: solo se descarga con --hi-res-pop
urls = [
  "https://data.worldpop.org/GIS/Population/Global_2000_2020/2020/PER/per_ppp_2020_UNadj.tif",
]
licencia = "Creative Commons Attribution 4.0"
cita     = "WorldPop (2020). Global High Resolution Population Denominators Project, unconstrained."

[fuentes.osm]
descripcion = "Extracto OpenStreetMap del Perú para el motor de ruteo (Fase 2)"
archivo     = "peru-latest.osm.pbf"
opcional    = true          # ~244 MB: solo se descarga con --with-osm
urls = [
  "https://download.geofabrik.de/south-america/peru-latest.osm.pbf",
]
licencia = "Open Database License (ODbL)"
cita     = "OpenStreetMap contributors / Geofabrik GmbH."
```

---

## 6. Rutas

Todas relativas a la raíz del repositorio. El pipeline las crea si no existen.

```toml
[rutas]
raw       = "data/raw"
processed = "data/processed"
outputs   = "data/outputs"
logs      = "logs"
figuras   = "report/figures"
cache     = "data/cache"
```

---

## 7. Descarga

```toml
[descarga]
# Si el archivo ya existe en data/raw/ con el tamaño esperado, no se vuelve a bajar.
# El enunciado exige que el paso de descarga sea re-ejecutable sin costo.
saltar_si_existe = true
reintentos = 3
espera_entre_reintentos_seg = 5
timeout_seg = 600
# datosabiertos.gob.pe responde HTTP 418 a clientes sin User-Agent de navegador.
user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
```

---

## 8. Ruteo (Fase 2)

Declarado aquí desde ya para que la Fase 1 no tenga que modificarse después.

```toml
[ruteo]
motor = "osrm"                 # osrm | osmnx | openrouteservice

# Un servidor OSRM sirve UN solo perfil: el que se compiló en su grafo. Para comparar
# auto / pie / bicicleta hay que levantar tres contenedores, cada uno en su puerto.
perfiles = ["car", "foot", "bike"]

# Carpeta de trabajo de OSRM. Va FUERA de OneDrive a propósito: los grafos compilados pesan
# varios GB por perfil y OneDrive intentaría sincronizarlos. Tampoco se versionan.
directorio_osrm = "C:/osrm-hw2"

# Tope de coordenadas por petición /table. Debe coincidir con el --max-table-size con el
# que se levanta osrm-routed, y el chunk del cliente queda por debajo (la API de OSRM es
# solo GET: una URL con miles de coordenadas falla por longitud antes de llegar al servidor).
max_table_size = 4000
chunk_origenes = 200
chunk_destinos = 300
timeout_seg = 120

max_puntos_demanda = 5000      # tope que fija el enunciado
metodo_muestreo = "estratificado_distrito_ponderado_poblacion"
semilla = 42

# --- Umbral de enganche a la red vial ---------------------------------------------------
# OSRM engancha ("snap") cada punto a la vía más cercana y rutea desde ahí, ignorando el
# tramo entre el punto real y esa vía. Cuando ese tramo es grande, el tiempo calculado deja
# de medir lo que se quiere medir.
#
# En Loreto el centro poblado mediano engancha a 10.4 km de la carretera más próxima, y
# algunos a 113 km, porque allí la conectividad es fluvial y la red vial sencillamente no
# sirve a la población. Sin este umbral, esos puntos recibirían un tiempo de viaje
# artificialmente bajo y el promedio departamental sería falso.
#
# El valor de 2 000 m no es arbitrario: caminando son unos 24 minutos, o sea que el tramo
# fuera de red consumiría por sí solo casi entera la banda de cobertura más estricta
# (30 min). Más allá de ahí, el punto no está servido por la red vial.
#
# Los puntos que superan el umbral NO se borran ni se rellenan con distancia euclidiana
# (el enunciado lo prohíbe expresamente): se marcan `fuera_de_red` y se reportan aparte.
snap_umbral_m = 2000

# Umbrales adicionales para el análisis de sensibilidad, de modo que el resultado no dependa
# de un solo número elegido a dedo.
snap_umbrales_sensibilidad = [500, 1000, 2000, 5000, 10000]

[ruteo.osrm]
# Puerto y perfil Lua de la imagen oficial de OSRM para cada modo.
car  = { url = "http://localhost:5000", lua = "/opt/car.lua",     puerto = 5000 }
foot = { url = "http://localhost:5001", lua = "/opt/foot.lua",    puerto = 5001 }
bike = { url = "http://localhost:5002", lua = "/opt/bicycle.lua", puerto = 5002 }
```

---

## 9. Métricas (Fase 3)

```toml
[metricas]
# Bandas de cobertura en minutos.
bandas_minutos = [30, 60, 120]

# Se reportan las dos: el Gini como número comparable entre departamentos, y la curva de
# Lorenz como figura. La justificación está en el informe — el Gini solo resume, y en una
# variable de "tiempo" (donde más es peor) conviene enseñar la curva para que se vea de
# dónde sale la desigualdad.
medida_desigualdad = "gini_y_lorenz"

niveles_agregacion = ["distrito", "provincia", "departamento"]

# Cuántos distritos entran en la lista de brechas críticas.
top_brechas = 20

# Segunda dimensión para el cruce que exige el enunciado.
# Se usa SOLO la tasa de pobreza: en esta tabla `PBI_PC` e `IDH` traen un único valor por
# departamento repetido en cada distrito, así que no aportan variación distrital real y
# cualquier correlación con ellos sería espuria. `POVERTY_RATE` sí varía distrito a distrito
# (115 valores distintos entre los 119 distritos de Ayacucho).
archivo_pobreza = "data/external/pobreza_distrital.csv"
columna_pobreza = "POVERTY_RATE"
```

**Procedencia de la tabla de pobreza.** Viene del material del curso
(`sessions/06-geoespacial/lab/Data/Poverty.csv`) y se copió al repositorio para que sea
autosuficiente. Trae la tasa de pobreza monetaria distrital, presumiblemente del mapa de
pobreza del INEI, pero **el archivo no documenta su año ni su fuente exacta**, lo cual es en
sí una limitación que el informe declara. Cubre 210 de los 215 distritos del ámbito; los 5
que faltan son distritos de creación reciente en Ayacucho (Putis, Unión Progreso, Río
Magdalena, Ninabamba y Patibamba) que aún no existían cuando se elaboró la tabla.

---

## 10. Informe (Fase 5)

El informe se compila desde el propio pipeline, de modo que el PDF nunca pueda quedar
desincronizado de los datos: cada vez que cambian las cifras, `--phase 5` las vuelve a
incorporar. Las tablas entran con `\input` y las figuras en PDF vectorial.

```toml
[informe]
fuente = "report/main.tex"
salida = "report/main.pdf"

# Compiladores que se intentan, en orden. Tectonic es un binario único que descarga solo
# los paquetes que el documento necesita, sin instalar una distribución completa de LaTeX.
compiladores = [
  "C:/Users/josem/.tectonic/tectonic.exe",
  "tectonic",
  "latexmk",
  "pdflatex",
]
timeout_seg = 600
```

**Si no hay ningún compilador disponible**, la fase avisa con instrucciones y no falla: el
`.tex` queda escrito y se puede compilar en Overleaf, que el enunciado admite expresamente.

---

## 11. Salida

```toml
[salida]
# Formato de los datasets procesados: "parquet" (GeoParquet) o "gpkg" (GeoPackage).
formato = "parquet"
# Además del formato principal, exporta una copia en GeoPackage para abrir en QGIS.
exportar_gpkg_tambien = true
crs_trabajo = "EPSG:4326"      # geográfico, para almacenamiento e intercambio
crs_metrico = "EPSG:24891"     # PSAD56 / Peru central zone, para distancias y áreas
```
