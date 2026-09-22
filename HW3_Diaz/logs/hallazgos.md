# Hallazgos — resultados sustantivos, con sus números

Resultados medidos durante el desarrollo. Cubre el punto de *findings* del video y las
secciones de resultados y discusión. ⭐ marca los que mejor funcionan contados en cámara.

---

## ⭐ H-01 · Ningún umbral de similitud separa las preguntas cercanas

**Fase:** Tarea 1, Fase 3 y 4 · **Evidencia:** `tarea1_rag_normativo/eval/resultados/`

El enunciado avisa de que las puntuaciones de similitud no son intuitivas: una pregunta
fuera de dominio ("¿cómo preparo ceviche?") alcanzó 0.79 frente a un umbral de 0.78
elegido a ojo. **Mi medición reproduce ese número casi exactamente: 0.7934.**

Pero el hallazgo de verdad es peor que eso, y es el que hay que contar:

| Pregunta | Tipo | Similitud máxima |
|---|---|---|
| "¿Cómo preparo un ceviche de pescado?" | fuera de dominio | 0.7934 |
| "¿Cuál es la capital de Francia?" | fuera de dominio | 0.7626 |
| **"¿Qué plazo tiene el comité para absolver consultas?"** | **fuera de corpus (Reglamento)** | **0.8869** |
| "¿Qué anexos debe contener la declaración jurada?" | fuera de corpus (Reglamento) | 0.8625 |
| "¿Cuánto cuesta la tasa de inscripción en el RNP?" | fuera de corpus (Reglamento) | 0.8587 |
| *Media de las 20 preguntas VÁLIDAS* | in-domain | *0.8809* |

La tercera fila es la clave: **una pregunta que el sistema no puede responder puntúa 0.8869,
por encima de la media de las preguntas que sí puede responder, y por encima de 13 de las
20 individualmente.** No existe ningún corte horizontal que deje arriba lo bueno y abajo lo
malo, porque las preguntas de Reglamento son del mismo dominio, con el mismo vocabulario
jurídico. El modelo de embeddings tiene razón al decir que se parecen: se parecen.

**Consecuencia de diseño.** Un único umbral es estructuralmente insuficiente. De ahí salen
los dos filtros de la arquitectura (ver H-03).

### Barrido completo del umbral

| Umbral | Recall@1 | Recall@3 | Recall@5 | Abst. correctas | Abst. incorrectas | Aciertos | % |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.70 | 0.70 | 0.85 | 0.90 | 0 | 0 | 20 | 80.0 |
| 0.74 | 0.70 | 0.85 | 0.90 | 0 | 0 | 20 | 80.0 |
| 0.78 | 0.70 | 0.85 | 0.90 | 1 | 0 | 21 | 84.0 |
| **0.80** | 0.70 | 0.85 | 0.90 | 2 | 0 | 22 | **88.0** |
| **0.82** | 0.70 | 0.85 | 0.90 | 2 | 0 | 22 | **88.0** |
| **0.84** | 0.70 | 0.85 | 0.90 | 2 | 0 | 22 | **88.0** |
| 0.86 | 0.70 | 0.85 | 0.90 | 3 | 3 | 20 | 80.0 |
| 0.90 | 0.70 | 0.85 | 0.90 | 5 | 15 | 10 | 40.0 |

**Se eligió 0.82, no 0.80.** El óptimo no es un punto sino una **meseta** entre 0.80 y 0.84,
y las tres dan el mismo resultado. Tomar el centro de la meseta en lugar del primer valor
que empata deja el máximo margen antes de caer por cualquiera de los dos lados. Es una
elección más robusta ante un corpus ligeramente distinto.

Obsérvese también que Recall@k **no cambia** en todo el barrido: es correcto y conviene
saber explicarlo. Recall mide al buscador, que devuelve siempre los mismos fragmentos
ordenados igual; el umbral no cambia qué se recupera, solo si se decide usarlo. Son dos
etapas distintas del pipeline y por eso hacen falta dos métricas.

---

## ⭐ H-02 · El índice de control NO sirve para detectar preguntas de Reglamento (resultado negativo)

**Fase:** Tarea 1, Fase 3 · **Evidencia:** `eval/resultados/control_discriminacion.csv`

**Hipótesis.** Si indexo el Reglamento en una colección aparte —que nunca responde— podría
distinguir "no lo sé" de "eso lo responde el Reglamento, que no está en mi corpus". Bastaría
con comparar: si la pregunta se parece más al Reglamento que al corpus, es de Reglamento.

**Resultado: la hipótesis es falsa.** Medido sobre las 25 preguntas:

| Margen exigido | Preguntas fuera de corpus detectadas | Falsos positivos (preguntas válidas marcadas) |
|---:|---:|---:|
| 0.000 | 2 / 5 | 11 / 20 |
| 0.005 | 1 / 5 | 6 / 20 |
| 0.010 | **0 / 5** | 4 / 20 |
| 0.030 | 0 / 5 | 0 / 20 |

No hay ningún margen que funcione: o no detecta nada, o marca como sospechosas la mitad de
las preguntas legítimas. La diferencia media de similitud entre ambas colecciones es de
−0.0033 para las preguntas válidas y +0.0008 para las de fuera: **ruido**.

**Por qué falla.** La Ley y su Reglamento son el mismo dominio, el mismo registro y casi el
mismo vocabulario. Un embedding captura de qué habla un texto, no qué documento tiene
competencia normativa para regularlo. Esa segunda pregunta es jurídica, no semántica.

**Qué se hizo con el resultado.** La colección se conserva (la usa la innovación que enlaza
ambas tareas) pero **queda fuera de la decisión de abstenerse**, con la bandera
`indice.usar_control_para_abstener: false` y el motivo documentado en el propio
`config.yaml`. El código del experimento se mantiene para poder reproducir la medición.

> Vale la pena contarlo en el video: un experimento que falla, medido y descartado con
> datos, demuestra más criterio que tres que funcionan por casualidad. Y evitó meter en
> producción un mecanismo que habría marcado como dudosa 1 de cada 5 respuestas correctas.

---

## ⭐ H-03 · Dos filtros de abstención, con costos distintos — y cada uno atrapa lo suyo

**Fase:** Tarea 1, Fase 3 · **Evidencia:** corrida real del motor, `logs/costos.csv`

De H-01 y H-02 sale la arquitectura final. No hay un mecanismo de abstención, hay dos, y
están ordenados del más barato al más caro:

| | Filtro 1 — umbral | Filtro 2 — el modelo |
|---|---|---|
| **Cuándo actúa** | Antes de llamar a la API | Después de llamar |
| **Costo** | **0 tokens, 0 USD** | Una llamada (~0.0003 USD) |
| **Qué atrapa** | Preguntas ajenas al dominio | Preguntas del dominio sin respuesta en el corpus |
| **Cómo decide** | `similitud_maxima < 0.82` | Campo JSON `puede_responder: false` |

Comportamiento verificado con llamadas reales:

```
"¿Cómo preparo un ceviche de pescado?"
   sim 0.7934 < 0.82  ->  abstuvo=True  filtro='umbral'   0 tokens   $0.000000

"¿Qué plazo exacto tiene el comité para absolver consultas?"
   sim 0.8869 > 0.82  ->  llamó al modelo
                      ->  abstuvo=True  filtro='modelo'   1639+134   $0.000307
```

La respuesta del segundo caso es el mejor material del video, porque el sistema **explica
qué sí tiene y qué no**:

> "El corpus indexado no cubre esa materia. Los fragmentos disponibles tratan sobre la
> reducción del plazo de convocatoria, la elevación del pliego de absolución de consultas
> al OECE, el contenido de las ofertas... Ninguno señala el plazo exacto que tiene el
> comité de selección para absolver consultas y observaciones."

**La abstención es un campo, no una cadena.** El modelo devuelve JSON y `puede_responder`
es un booleano que el motor copia a `Respuesta.abstuvo`. No se interpreta prosa en ningún
momento, que es lo que el enunciado exige explícitamente.

---

## ⭐ H-04 · BM25 se hunde justo donde el usuario real pregunta

**Fase:** Tarea 1, innovación · **Evidencia:** `eval/resultados/bm25_vs_embeddings.csv`

Comparación de búsqueda léxica (BM25) contra búsqueda semántica (embeddings), separando
las preguntas por cómo están redactadas:

| Estilo de pregunta | n | BM25 acierta en top-3 | Embeddings acierta en top-3 |
|---|---:|---:|---:|
| Formal (redactada como la ley) | 14 | 71.4% | **100.0%** |
| **Coloquial (redactada como un empresario)** | 6 | **16.7%** | **50.0%** |

Los embeddings ganan siempre, pero **la brecha se multiplica por cuatro en las preguntas
coloquiales**: de 1.4x a 3.0x. Y esa es justamente la población de usuarios del sistema —
una MYPE que no habla en lenguaje jurídico.

**El ejemplo que lo explica en una frase:** el empresario pregunta *"me piden una carta
fianza"*. La Ley no dice "carta fianza" en ese artículo: dice **"garantía de fiel
cumplimiento"**. Cero palabras en común. BM25 puntúa por coincidencia de términos, así que
estructuralmente no puede encontrarlo. Los embeddings sí, porque operan sobre significado:
lo recuperaron en la **posición 1** con similitud 0.8493.

> Matiz honesto para el video: el 50% de los embeddings en preguntas coloquiales tampoco
> es bueno. Las dos que fallan (P11 sobre ventajas para MYPE y P13 sobre plazos de reclamo)
> fallan porque la respuesta está repartida en varias páginas y mi anotación esperaba unas
> concretas. Es una limitación del conjunto de evaluación tanto como del sistema.

---

## H-05 · Métricas de recuperación con el umbral de producción

**Fase:** Tarea 1, Fase 4

| Métrica | Valor | Qué mide |
|---|---:|---|
| Recall@1 | 0.70 | El fragmento correcto sale el primero en 14 de 20 |
| Recall@3 | 0.85 | Entra en el top-3 en 17 de 20 |
| Recall@5 | 0.90 | Entra en el top-5 en 18 de 20 |
| Abstenciones correctas | 2 / 5 | Fuera de dominio detectado por el umbral |
| Abstenciones incorrectas | **0 / 20** | Ninguna pregunta válida fue rechazada |
| Similitud media in-domain | 0.8809 | |
| Similitud máxima out-domain | 0.8869 | Por encima de la media in-domain (ver H-01) |

Las 3 preguntas fuera de corpus que el umbral no atrapa las resuelve el filtro 2 (H-03),
así que la tasa de abstención correcta efectiva del sistema completo es 5/5.

**Cero abstenciones incorrectas es el número que más importa.** Significa que el sistema
nunca se negó a responder algo que sí estaba en el corpus. El coste de esa elección es que
3 de 5 preguntas fuera de corpus llegan hasta la llamada al modelo, es decir, unos 0.0003
USD desperdiciados cada una. Es el intercambio correcto para este caso de uso: la molestia
de un usuario que no recibe respuesta a algo respondible es peor que un tercio de milésimo
de dólar.

---

## ⭐ H-07 · Poner el departamento en el texto acierta el 50%; como filtro, el 100%

**Fase:** Tarea 2, Fase 3 · **Evidencia:** `tarea2_radar/eval/resultados/efecto_filtros.csv`

El enunciado pide explicar *por qué* las condiciones numéricas y territoriales deben ser
filtros y no embeddings. En vez de argumentarlo solo, lo medí. Para cinco departamentos
hice la **misma** búsqueda de dos maneras y conté qué porcentaje de los 10 procesos
recuperados pertenecía realmente a ese departamento:

| Departamento | Departamento **en el texto** de la pregunta | Departamento **como filtro** |
|---|---:|---:|
| Cusco | 50% | 100% |
| Puno | 40% | 100% |
| Loreto | 70% | 100% |
| **Arequipa** | **0%** | **100%** |
| Piura | 90% | 100% |
| **Media** | **50.0%** | **100.0%** |

**La mitad de los resultados son del departamento equivocado** cuando la condición
territorial se deja a los embeddings. Y el caso de Arequipa es demoledor: *cero* de diez.

**Por qué pasa.** El embedding de "obras de agua y saneamiento en Arequipa" está dominado
por "obras de agua y saneamiento", que es lo que más texto ocupa y más significado
aporta. La palabra "Arequipa" apenas mueve el vector. Además, el departamento **no está
en el texto del proceso**: es un atributo del comprador, que normalizamos en la Fase 2.
Pedirle a los embeddings que lo respeten es pedirles que adivinen un dato que no ven.

Con lo numérico el argumento es todavía más claro: el vector de "un millón de soles" está
cerquísima del de "900,000 soles" —son textos parecidos— pero 900,000 **no cumple** la
condición. Los embeddings capturan parecido, no orden. **No existe un "mayor que" en el
espacio vectorial.**

**Regla que se defiende en el video:** lo que es exacto y verificable va a un filtro; lo
que es ambiguo va a los embeddings. Un filtro además es explicable al usuario ("se aplicó
monto ≥ 1,000,000"), y una similitud no.

---

## ⭐ H-08 · El umbral SÍ transfiere entre corpus (y yo había supuesto que no)

**Fase:** Tarea 2, Fase 3 · **Evidencia:** `tarea2_radar/eval/resultados/barrido_umbral.csv`

El enunciado pide comprobar si el umbral calibrado en la Tarea 1 sirve en el corpus de la
Tarea 2, y recalibrar si no. Yo puse 0.86 en la configuración **antes de medir**, con un
razonamiento que parecía sólido: las descripciones de procesos son textos cortos y
telegráficos ("ADQUISICION DE SOBRE IMPRESO DE POLIETILENO"), muy distintos del lenguaje
articulado de una ley, así que la distribución de similitudes debería desplazarse.

**La medición desmintió la suposición:**

| Umbral | Recall@1 | Recall@3 | Abst. correctas | Abst. incorrectas | % aciertos |
|---:|---:|---:|---:|---:|---:|
| 0.78 | 0.9167 | 1.0 | 1 | 0 | 86.7 |
| **0.80** | 0.9167 | 1.0 | 2 | **0** | **93.3** |
| **0.82** | 0.9167 | 1.0 | 2 | **0** | **93.3** |
| **0.84** | 0.9167 | 1.0 | 2 | **0** | **93.3** |
| 0.86 | 0.9167 | 1.0 | 3 | 1 | 93.3 |
| 0.88 | 0.9167 | 1.0 | 3 | 4 | 73.3 |
| 0.90 | 0.9167 | 1.0 | 3 | 10 | 33.3 |

**La meseta óptima es 0.80–0.84: exactamente la misma que en la Tarea 1.** El 0.86 que yo
había puesto da el mismo porcentaje de aciertos pero rechazando una pregunta válida, así
que es estrictamente peor. Corregí la configuración a 0.82.

**Por qué transfiere.** Porque el umbral no es una propiedad del corpus sino del **modelo
de embeddings**, y es el mismo `multilingual-e5-small` en las dos tareas. La escala de
similitud que produce un modelo es suya, no del texto que le des.

**Por qué conviene contarlo en el video.** Es un caso donde la hipótesis razonable era
falsa y la medición lo demostró en treinta segundos y sin coste. Si hubiera dejado el
0.86 "porque tenía sentido", el sistema rechazaría preguntas legítimas para siempre y
nadie se habría enterado.

### Métricas de la Tarea 2 con el umbral corregido

| Métrica | Valor |
|---|---:|
| Recall@1 | **0.9167** |
| Recall@3 | **1.0000** |
| Recall@5 | **1.0000** |
| Abstenciones correctas | 2 / 3 |
| Abstenciones incorrectas | **0 / 12** |
| Similitud media in-domain | 0.8856 |
| Similitud máxima out-domain | 0.8493 |

Aquí sí hay separación limpia entre in-domain y out-domain (0.8856 frente a 0.8493),
al revés que en la Tarea 1 (H-01). El motivo es que las preguntas fuera de dominio de
este corpus son realmente ajenas (recetas, fútbol), mientras que en la Tarea 1 tres de
las cinco eran del mismo dominio jurídico.

---

## ⭐ H-09 · Qué encontró el radar: 20,422 procesos y una señal que se confirma sola

**Fase:** Tarea 2, Fases 1, 2 y 5

### El corpus

| | |
|---|---:|
| Meses descargados (2026-06, 07, 08) | 3 |
| Peticiones HTTP totales | **5** |
| Datos descargados | 26.5 MB |
| Procesos (una fila por `ocid`) | **20,422** |
| Duplicados entre meses | **0** |
| Procesos localizados en un departamento | **20,422 (100%)** |
| Procesos adjudicados | 13,743 (67.3%) |

Las **5 peticiones para 20,422 procesos** son el argumento de por qué se usó el bulk y no
la API: la API pagina de 10 en 10, así que lo mismo habría costado unas 2,000 peticiones.

### Calidad de los datos

| Regla | Marcados | % |
|---|---:|---:|
| Monto ausente, cero o negativo | 2,476 | 12.12% |
| `Localidad` que **no** es un departamento | 16,281 | **79.72%** |
| Descripción vacía | 0 | 0% |
| Procesos duplicados | 0 | 0% |
| Sin departamento tras la cascada | 0 | 0% |

El 79.72% confirma con números lo que el enunciado advertía: el campo `Localidad` mezcla
distritos y provincias con departamentos. Usarlo directamente como ubicación habría
producido un mapa con cuatro quintas partes de los procesos mal colocados. Por eso la
cascada de normalización lo deja como **último recurso** y prioriza el campo
`Departamento` del comprador.

### Señal de riesgo: postor único

**13.11%** de los 13,742 procesos adjudicados recibieron exactamente una oferta.

| Departamento | Adjudicados | % con un solo postor |
|---|---:|---:|
| Tumbes | 120 | **36.67%** |
| Lima | 3,862 | **30.17%** |
| Amazonas | 218 | 16.06% |
| Arequipa | 545 | 14.68% |
| Piura | 405 | 10.12% |

Lima y Tumbes están muy por encima del resto. En Lima el volumen (3,862 procesos) hace
que no pueda ser casualidad estadística; Tumbes, con 120, es más frágil y conviene decirlo.

Entre las diez entidades con mayor proporción (mínimo 15 procesos adjudicados) aparece,
con un 69.70% sobre 33 procesos, el **Organismo Supervisor de las Contrataciones del
Estado** — es decir, el propio regulador del sistema. Es un dato llamativo para el video y
hay que presentarlo con el mismo cuidado que todos los demás: **es un motivo para mirar,
no una acusación.**

### Las dos señales se confirman entre sí

Calculadas de forma independiente, y este es el hallazgo metodológicamente más sólido de
la Tarea 2:

| Periodo de consulta | Procesos adjudicados | % con un solo postor |
|---|---:|---:|
| **Corto** (< 3 días) | 2,619 | **5.88%** |
| Normal (≥ 3 días) | 6,149 | **1.27%** |

**4.6 veces más.** Un proceso cuya ventana de consultas fue apurada termina con un único
postor mucho más a menudo. No es una definición circular: el plazo sale del cronograma y
el número de postores del resultado del proceso. Que dos señales independientes apunten
en la misma dirección es lo que le da contenido empírico al indicador.

> Limitaciones que hay que declarar: el campo de plazo solo existe en el 69% de los
> procesos; el corte de 3 días es una decisión declarada, no una norma legal; y un
> contrato menor puede tener plazos legítimamente cortos.

---

## ⭐ H-10 · Los datos y la ley no hablan el mismo idioma

**Fase:** Tarea 2, innovación · **Evidencia:** `tarea2_radar/src/innovacion.py`, `config.yaml`

Este salió por accidente, intentando que funcionara la innovación que enlaza las dos
tareas, y es el hallazgo más sustantivo sobre el problema estudiado.

**Síntoma.** Cuando el radar recuperaba un proceso con método *"Adjudicación
Simplificada"* y le preguntaba al asistente normativo qué dice la ley al respecto, el
asistente se abstenía **siempre**. Con una similitud alta, 0.87, pero abstención.

**Diagnóstico.** Busqué los nombres de procedimiento en el texto de la Ley:

| Término | ¿Aparece en la Ley 32069? |
|---|---|
| "adjudicación simplificada" | **0 páginas** |
| "contratación directa" | **0 páginas** |
| "licitación pública" | 3 páginas |
| "concurso público" | 6 páginas |
| "competitivo" / "no competitivo" | 14 / 8 páginas |

**SEACE sigue publicando la nomenclatura de la Ley 30225, la ley anterior.** La Ley 32069
reorganizó los procedimientos por completo:

> **Artículo 54.** Son procedimientos de selección **competitivos**: a) la licitación
> pública para la contratación de bienes y obras; b) el concurso público para la
> contratación de servicios.
>
> **Artículo 55.** Las entidades contratantes se encuentran facultadas para **contratar
> directamente** en los siguientes supuestos: [...]

Los métodos que los datos publican hoy, ordenados por frecuencia:

| Método en los datos de SEACE | Procesos | ¿Existe ese nombre en la Ley 32069? |
|---|---:|---|
| Licitación Pública Abreviada | 6,390 | El concepto sí; el nombre "Abreviada" no |
| Concurso Público Abreviado | 5,202 | Igual |
| Subasta Inversa Electrónica | 2,372 | Sí |
| Comparación de Precios | 1,714 | Sí |
| Contratación Directa | 1,256 | El concepto sí (art. 55), el nombre no |
| **Adjudicación Simplificada** | **37** | **No existe** |
| Adjudicación Selectiva / Abreviada | 170 | No existen |

**Solución.** Un mapeo declarado en `config.yaml` que traduce el nombre operativo al
concepto legal, más una lista de nombres sin equivalente que disparan un aviso explícito
al usuario en vez de fingir que existen.

**Resultado, con llamadas reales:**

```
"Licitación Pública Abreviada" → responde citando [ley_32069, p. 25]
                                 el artículo 54 y sus dos procedimientos competitivos

"Contratación Directa"         → responde citando [ley_32069, p. 26]
                                 el artículo 55 y sus supuestos a), b), c)

"Adjudicación Simplificada"    → AVISA del desfase de nomenclatura
                                 y responde por el marco general
```

**Por qué importa, más allá de que la innovación funcione.** Es un hallazgo real sobre el
estado de los datos abiertos peruanos: el sistema operativo que publica las compras y el
marco legal que las rige están desfasados en su vocabulario. Cualquiera que cruce ambas
fuentes se topará con esto, y si no lo detecta concluirá que la ley "no dice nada" sobre
la mitad de los procesos.

**Y la lección de método:** la primera versión de la pregunta apuntaba a *"requisitos y
plazos"*, que son materia del **Reglamento** y no de la Ley. El asistente se abstenía
correctamente, pero de forma inútil. Preguntar bien es parte del trabajo: una pregunta
dirigida al corpus equivocado produce una abstención impecable que no le sirve a nadie.

---

## H-06 · Costo real de una consulta

**Fase:** Tarea 1, Fase 3 · **Evidencia:** `tarea1_rag_normativo/logs/costos.csv`

Precios verificados el **2026-09-20** en `https://api-docs.deepseek.com/quick_start/pricing`.
DeepSeek cobra distinto según la hora: son horas pico 01:00–04:00 y 06:00–10:00 UTC de lunes
a viernes; el resto del tiempo, incluido todo el fin de semana, la tarifa es **la mitad**.

| Concepto | Pico (USD/millón) | Valle (USD/millón) |
|---|---:|---:|
| Entrada con acierto de caché | 0.006 | 0.003 |
| Entrada sin acierto de caché | 0.30 | 0.15 |
| Salida | 1.20 | 0.60 |

Primeras 4 llamadas reales, todas en franja valle:

| Llamadas | Tokens entrada | Tokens salida | Latencia mediana | Costo |
|---:|---:|---:|---:|---:|
| 4 | 6,276 | 781 | 1.8 s | **$0.001354** |

**Una consulta cuesta unos 0.00034 USD en valle**, es decir alrededor de **3 consultas por
milésimo de dólar**. En hora pico costaría exactamente el doble. Con 1 dólar se atienden
unas 3,000 consultas.

Dato relevante para la defensa: el contexto pesa ~1,600 tokens de entrada frente a ~150-340
de salida, pero **la salida es 4 veces más cara por token**, así que ambos lados acaban
pesando parecido en la factura. Recortar el número de fragmentos recuperados abarataría
menos de lo que parece.

---
