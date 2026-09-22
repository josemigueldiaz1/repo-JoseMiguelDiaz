# Incidencias — qué se rompió y cómo se resolvió

Bitácora de obstáculos reales encontrados durante el desarrollo de la HW3. Cubre el punto
de "obstáculos" del video. Las entradas marcadas con ⭐ son las que mejor funcionan
contadas en cámara.

---

## ⭐ I-01 · El portal de OECE no se puede scrapear: es una SPA de Angular

**Fecha:** 2026-09-19 · **Fase:** Tarea 2, Fase 1 (adquisición)

**Síntoma.** El primer sondeo a las tres URLs del portal devolvió algo sospechoso:

```
200  text/html  2,837 B  https://contratacionesabiertas.oece.gob.pe/
200  text/html  2,837 B  https://contratacionesabiertas.oece.gob.pe/descargas
200  text/html  2,837 B  https://contratacionesabiertas.oece.gob.pe/api
```

**Exactamente el mismo tamaño en las tres rutas.** Eso no es casualidad: significa que el
servidor devuelve siempre el mismo esqueleto HTML y que el contenido real lo construye
JavaScript en el navegador. Un `BeautifulSoup` sobre esa página no encuentra ni un solo
enlace de descarga, porque en el HTML no existen.

**Diagnóstico.** Al inspeccionar el HTML se ve que es una aplicación Angular: tiene
`<base href="/">`, una `CSP-NONCE` y tres bundles JavaScript (`runtime`, `polyfills`,
`main`). La página no *tiene* datos; los *pide*.

**Alternativas evaluadas.**

1. **Selenium o Playwright** para renderizar el JavaScript. Funciona, pero obliga a
   instalar y automatizar un navegador entero (~300 MB), es lento, y es frágil: cualquier
   cambio de maquetación lo rompe.
2. **Buscar la API que consume la propia página.** Si el navegador obtiene los datos de
   algún sitio, ese sitio es alcanzable directamente con `requests`.

**Solución adoptada (opción 2).** Descargué el bundle principal
(`main.eb02d59670b1851d.js`, 3.2 millones de caracteres) y busqué dentro rutas de API con
una expresión regular. Aparecieron los endpoints que la aplicación usa:

```
/api/v1/files                                 catálogo de archivos mensuales
/api/v1/file/{source}/{type}/{year}/{month}   un archivo concreto
/api/v1/releases                              entregas OCDS
/api/v1/records                               registros OCDS
/api/v1/record/{ocid}                         un proceso por su ocid
```

Probados con `requests`, devuelven JSON limpio. El catálogo lista **40 meses** disponibles
(desde 2023-06 hasta 2026-09) y, para cada mes, URLs directas en seis formatos: `csv`,
`csv_es`, `xlsx`, `xlsx_es`, `json` y `sha`.

**Por qué importa.** Se evitó por completo la dependencia de un navegador automatizado. La
descarga es una petición HTTP normal, cacheable y reproducible. Además apareció el endpoint
`sha`, que permite verificar la integridad de cada descarga — algo que no habría encontrado
scrapeando la interfaz.

**Lección.** Cuando un portal no devuelve nada útil al scraper, la pregunta correcta no es
"¿cómo simulo un navegador?" sino "¿de dónde saca sus datos el navegador?".

---

## ⭐ I-02 · Leí mal la cobertura del departamento: 14.3% era el dato equivocado

**Fecha:** 2026-09-19 · **Fase:** Tarea 2, Fase 2 (validación territorial)

**Síntoma.** Al inspeccionar `Ent_PartesInvolucradas.csv` sobre una muestra de 2,500 filas,
la columna `Dirección:Departamento` aparecía rellena solo en el **14.3%** de los casos.
Con ese número, la Fase 2 parecía condenada: sin departamento no hay mapa coroplético, y
perder el 86% de los procesos habría hecho inútil el dashboard.

**Diagnóstico.** El error era mío, no de los datos. `Ent_PartesInvolucradas.csv` contiene
**una fila por cada parte involucrada en cada proceso**: la entidad compradora, la entidad
contratante, los postores y los proveedores adjudicados. En agosto de 2026 son 46,126 filas
para 6,552 procesos, es decir unas 7 partes por proceso. Los postores y proveedores son
empresas privadas que **no declaran dirección** en este dataset; solo la entidad pública
compradora la declara.

Calcular el porcentaje sobre todas las filas mezcla dos poblaciones distintas y da un
número que no significa nada.

**Solución.** Filtrar por el rol antes de medir. La columna
`Partes involucradas:Roles de las partes` contiene valores como `buyer;procuringEntity`.
Filtrando las filas que contienen `buyer`:

| Medida | Antes (todas las filas) | Después (solo `buyer`) |
|---|---|---|
| Filas consideradas | 46,126 | 6,552 |
| Con `Departamento` | 14.3% | **100.0%** |
| Procesos localizables | — | 6,552 / 6,552 |

**Por qué importa.** El indicador pasó de "problema grave" a "sin problema" por cambiar la
unidad de análisis, no por arreglar ningún dato. Sigue habiendo trabajo de normalización
(la columna `Localidad` sí mezcla provincias y distritos, con 168 valores distintos), pero
el departamento del comprador está completo.

**Lección para el video.** Un porcentaje de cobertura solo significa algo si el denominador
es la población correcta. Antes de declarar que unos datos están rotos, hay que comprobar
que se está contando lo que se cree contar. Dejé implementada igualmente la imputación por
entidad (si una entidad declara su departamento en algún proceso, ese valor sirve para el
resto de sus procesos) porque en otros meses la cobertura puede no ser perfecta, y porque
es la diferencia entre "descartar filas" y "recuperarlas", que el enunciado puntúa
explícitamente.

---

## ⭐ I-06 · Mi regla de limpieza acertaba cero veces: la cabecera va al revés

**Fecha:** 2026-09-19 · **Fase:** Tarea 1, Fase 1 (limpieza)

**Síntoma.** Escribí el patrón de limpieza para las cabeceras de El Peruano suponiendo
el formato `El Peruano / jueves 8 de enero de 2026`. El reporte de reglas lo delató:

```
patron                                    coincidencias_eliminadas
El Peruano\s*/\s*[^\n]{0,60}\d{4}                                0
```

**Cero coincidencias**, mientras el texto limpio seguía empezando por
`41 NORMAS LEGALES Jueves 8 de enero de 2026 El Peruano / "Artículo 194...`.

**Diagnóstico.** Al imprimir el texto crudo con `repr()` aparecieron dos cosas que no
había supuesto:

1. El orden es el **contrario** al que asumí: la fecha va **antes** de "El Peruano /",
   no después.
2. Hay **dos variantes** de cabecera, según la página sea par o impar, y la impar viene
   **sin espacios de separación**:

```
par:    '34 NORMAS LEGALES Jueves 8 de enero de 2026  El Peruano /'
impar:  '35NORMAS LEGALESJueves 8 de enero de 2026 El Peruano / '
```

La variante impar explica por qué un patrón ingenuo como `NORMAS\s+LEGALES` (con `\s+`,
que exige al menos un espacio) tampoco las capturaba todas.

**Solución.** Un único patrón que cubre ambas variantes haciendo **opcionales** todos los
espacios (`\s*` en vez de `\s+`) y que consume la cabecera entera de una vez, desde el
número de página hasta la barra final:

```
\d{0,3}\s*NORMAS\s*LEGALES\s*(?:Lunes|Martes|Mi[eé]rcoles|Jueves|Viernes|S[aá]bado|Domingo)
\s*\d{1,2}\s*de\s*[A-Za-zÁÉÍÓÚáéíóú]+\s*de\s*\d{4}\s*El\s*Peruano\s*/
```

Resultado: 16 coincidencias sobre 16 páginas del decreto. Aprovechando el hallazgo añadí
los pies del Reglamento (`Reglamento de la Ley Nº 32069...` y `Página N de 249`), que
acertaron 266 y 249 veces.

| Documento | Texto eliminado antes | Texto eliminado después |
|---|---|---|
| ley_32069 | 2.17% | 2.22% |
| ds_001_2026_ef | 1.63% | **2.54%** |
| reglamento | 2.22% | **4.66%** |

**Por qué importa.** Sin esta corrección, cada fragmento del decreto habría arrastrado la
fecha de publicación y la palabra "NORMAS LEGALES". Eso contamina los embeddings: la
pregunta *"¿qué dice la norma del 8 de enero?"* habría recuperado fragmentos por su
cabecera y no por su contenido, y todos los fragmentos se habrían parecido entre sí por
compartir el mismo encabezado.

**Lección para el video.** Contar cuántas veces acierta cada regla de limpieza no es un
adorno del reporte: es el mecanismo que detecta que una regla no hace nada. Una regla
rota falla en silencio — el texto sale, simplemente sale sucio.

---

## ⭐ I-07 · El indicador de plazo marcó el 100% de los procesos: el campo no era una ventana

**Fecha:** 2026-09-20 · **Fase:** Tarea 2, Fase 5 (innovación: señales de alerta)

**Síntoma.** La primera versión de la señal "periodo de licitación corto" dio un
resultado imposible:

```
mediana_dias        0.0
con_plazo_corto     19085
pct_plazo_corto     100.0
```

Cuando un indicador marca el 100% de los casos, no está detectando nada: está roto.

**Diagnóstico.** Perfilé todos los campos de fecha del dataset y apareció la causa:

```
licitacion_fin - licitacion_inicio   n=6148  min=0.0  mediana=0.0  max=0.0
```

**Mínimo, mediana y máximo valen exactamente cero.** El "periodo de licitación" de OECE
no es un intervalo: trae el mismo instante en el campo de inicio y en el de fin, en el
100% de los registros. Es una marca temporal duplicada en dos columnas.

**Solución.** El mismo perfilado mostró cuál era la ventana real:

| Campo | n | p25 | Mediana | Máx |
|---|---:|---:|---:|---:|
| `licitacion_fin - licitacion_inicio` | 6,148 | 0.0 | **0.0** | 0.0 |
| `consulta_fin - consulta_inicio` | 4,613 | 3.0 | **5.0** | 21.0 |
| `Duración (días)` declarado | 4,583 | 2.0 | **4.0** | 20.0 |

El **periodo de consulta** sí es un intervalo real, y además es conceptualmente el
correcto: es la ventana en la que un proveedor puede pedir aclaraciones y observar las
bases antes de ofertar. Si es muy corta, quien no estuviera avisado de antemano no llega
a competir, que es exactamente lo que la señal quiere capturar.

Se cambió el indicador a ese campo, prefiriendo el valor `Duración (días)` que la propia
entidad declara y cayendo al cálculo por diferencia de fechas cuando falta. El corte se
fijó en 3 días a partir de la distribución observada (p25 = 2), no por intuición.

**Resultado después del arreglo** — y esta es la parte que vale para el video, porque el
indicador pasó de roto a tener contenido empírico:

| | Postor único |
|---|---:|
| Procesos con periodo de consulta **corto** (< 3 días) | **5.88%** |
| Procesos con periodo de consulta **normal** | **1.27%** |

Un proceso con consultas apuradas termina con un solo postor **4.6 veces más a menudo**.
Las dos señales de alerta, que se calculan de forma independiente, se confirman entre sí.

**Lección para el video.** Un indicador que marca el 100% o el 0% de los casos siempre es
un error de datos, nunca un hallazgo. Y antes de calcular una duración conviene perfilar
el campo: mínimo, mediana y máximo iguales a cero delatan el problema en un vistazo.

---

## I-03 · `Invoke-WebRequest` falla en PowerShell no interactivo

**Fecha:** 2026-09-19 · **Fase:** comprobación de fuentes

**Síntoma.** El primer sondeo de las URLs oficiales falló en las cinco con el mismo mensaje:

```
Windows PowerShell is in NonInteractive mode. Read and Prompt functionality is not available.
```

**Diagnóstico.** No era un problema de red. `Invoke-WebRequest` usa por defecto el motor de
Internet Explorer para analizar el HTML, y ese motor intenta mostrar un diálogo de
configuración la primera vez que se ejecuta. En una sesión no interactiva no hay quién
responda ese diálogo, así que aborta.

**Solución.** Hacer las comprobaciones con `requests` desde Python, que es además la
librería que usa el pipeline. El diagnóstico quedó así alineado con la herramienta real.
(La alternativa en PowerShell habría sido `-UseBasicParsing`.)

**Lección.** Un error de herramienta puede disfrazarse de error de red. Cinco fallos
idénticos en cinco dominios distintos son señal de que el problema está en el cliente.

---

## I-04 · gob.pe redirige: OSCE ya no se llama OSCE

**Fecha:** 2026-09-19 · **Fase:** Tarea 1, Fase 1 (fuentes)

**Síntoma.** La URL del enunciado apunta a `/institucion/osce/colecciones/45029-...` y
responde 200, pero tras seguir la redirección la URL final es:

```
https://www.gob.pe/institucion/oece/colecciones/45029-ley-n-32069-ley-general-de-
contrataciones-publicas-y-su-reglamento
```

Cambian dos cosas: `osce` → `oece` y el slug termina ahora en `-y-su-reglamento`.

**Diagnóstico.** El OSCE (Organismo Supervisor de las Contrataciones del Estado) pasó a
llamarse OECE (Organismo Especializado para las Contrataciones Públicas Eficientes). La
redirección funciona hoy, pero es una dependencia frágil.

**Solución.** Registrar en `config.yaml` la URL final, no la del enunciado, y permitir
`allow_redirects`. Las URLs de los PDF están en el CDN (`cdn.www.gob.pe`), que no cambió.

**Consecuencia inesperada y útil.** La colección publica **dos** documentos, no uno: la Ley
32069 actualizada y el **Reglamento** actualizado. El Reglamento se descarga pero
deliberadamente **no se indexa**: es exactamente el documento que el enunciado usa para
comprobar que el asistente reconoce los límites de su corpus. Tenerlo a mano permite
demostrar que la abstención no es por ignorancia sino por diseño.

---

## I-05 · El PDF de El Peruano no está en un `<a href>`

**Fecha:** 2026-09-19 · **Fase:** Tarea 1, Fase 1 (fuentes)

**Síntoma.** La página del DS 001-2026-EF muestra botones "PDF", "HTML" y "Cuadernillo",
pero al recorrer todos los `<a href>` con BeautifulSoup no aparecía ningún enlace `.pdf`.

**Diagnóstico.** El enlace se construye por JavaScript. Sin embargo, la ruta sí está
presente en el HTML crudo como cadena de texto.

**Solución.** Buscar el patrón con una expresión regular sobre el HTML completo en vez de
sobre el árbol de etiquetas. Apareció:

```
/api/archivo/file/4UFSj6jQKdnBeQxKkvTolN/*/2474920-3.PDF
```

**Lección.** El árbol DOM que construye el parser solo ve lo que está marcado como
etiqueta. Cuando un dato viaja como texto dentro de un script, hay que bajar al HTML
crudo. Es el mismo principio que resolvió I-01, aplicado a menor escala.

---
