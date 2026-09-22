# Explicaciones — qué es cada cosa y por qué existe

Material conceptual para poder defender el proyecto sin haberlo memorizado. Si en el
video te preguntan "¿y esto para qué es?", la respuesta está aquí.

---

## Qué hace cada archivo

### Raíz

| Archivo | Qué hace | Por qué existe |
|---|---|---|
| `run_all.py` | Genera todo el proyecto en una corrida | Es la prueba de reproducibilidad: una máquina limpia + `requirements.txt` + este script = el proyecto entero |
| `requirements.txt` | 47 dependencias con versión fija | Sin versiones fijas, quien lo instale en octubre puede recibir otro pandas y ver otro comportamiento |
| `.env.example` | Nombres de variables, **sin valores** | Le dice al evaluador qué credenciales necesita sin filtrar ninguna |
| `.gitignore` | Excluye `.env`, datos crudos e índices | Una clave que entra al historial de git sigue ahí aunque después la borres del archivo |

### Tarea 1

| Módulo | Responsabilidad |
|---|---|
| `src/config.py` | Lee `config.yaml`. Único punto por el que el resto accede a los parámetros |
| `src/fuentes.py` | Descarga los PDF y comprueba que son legibles **antes** de construir nada |
| `src/limpieza.py` | Quita cabeceras y normaliza, conservando el número de página |
| `src/chunking.py` | Trocea **por página**, con IDs estables entre corridas |
| `src/embeddings.py` | Una interfaz, dos implementaciones (local y API) |
| `src/indice.py` | ChromaDB persistente, idempotente y reanudable |
| `src/motor.py` | **El núcleo.** Una función que responde. No importa ninguna interfaz |
| `src/costos.py` | Registra cada llamada con la tarifa de su franja horaria |
| `build_index.py` | Proceso **offline**: PDFs → índice |
| `app.py` | Proceso **online**: solo interfaz, nunca reconstruye el índice |

### Tarea 2

| Módulo | Responsabilidad |
|---|---|
| `src/config.py` | **Subclase** del Config de la Tarea 1 — de ahí sale la reutilización |
| `src/adquisicion.py` | Descarga los bulk de OECE por su API, con throttling y verificación sha |
| `src/validacion.py` | 7 reglas de calidad. Ninguna borra filas |
| `src/territorio.py` | Cascada de 4 pasos para normalizar a 25 departamentos |
| `src/motor.py` | RAG híbrido: filtros exactos + búsqueda semántica |
| `src/metricas.py` | Indicador de postor único y señal de plazo corto |
| `src/innovacion.py` | Enlaza las dos tareas llamando al motor normativo |

---

## Las decisiones de diseño, una por una

### ¿Por qué el troceado es por página y no del documento entero?

Porque la cita *"documento y página"* es un requisito central, y si se concatena el
documento para partirlo después, esa información se pierde de forma irrecuperable.
Reconstruirla obliga a buscar el fragmento dentro del PDF, que falla justo en el caso más
común de un texto legal: párrafos casi idénticos que se repiten ("de acuerdo con lo
establecido en el reglamento" aparece decenas de veces).

**El precio:** un artículo a caballo entre dos páginas queda partido en dos fragmentos.
Se compensa con el solape de 150 caracteres, y es el intercambio correcto: mejor un
fragmento algo más corto que una cita equivocada, porque en materia normativa una cita
equivocada es exactamente el fallo que el sistema debe evitar.

### ¿Por qué ChromaDB y no FAISS?

FAISS es más rápido en corpus grandes, pero guarda **solo los vectores**: los metadatos
(documento, página, versión) hay que mantenerlos en una estructura paralela y
sincronizarla a mano. Una desincronización entre un vector y su metadato produciría citas
incorrectas **sin dar ningún error**. ChromaDB guarda vector y metadatos juntos.

Con 511 fragmentos la ventaja de velocidad de FAISS es irrelevante; la seguridad de la
cita, no. Con un corpus de millones la decisión se invertiría, y conviene decirlo así.

### ¿Por qué temperatura 0?

El asistente debe **reproducir lo que dice la norma recuperada**, no proponer redacciones
alternativas. Cualquier variabilidad aquí es riesgo de alucinación, no creatividad útil.

**Matiz que conviene saber:** `temperature=0` no garantiza respuestas idénticas al 100%.
Reduce muchísimo la variación, pero las APIs procesan en lotes y hay redondeos de punto
flotante. Di "prácticamente determinista", no "siempre idéntico".

### ¿Por qué el modelo responde en JSON y no en prosa?

Porque el enunciado exige que la abstención sea *"a structured field of the result, not
inferred by comparing the text of the answer"*. Con JSON, `puede_responder` es un booleano
que el modelo rellena y el motor copia. Deducirlo del texto ("¿empieza por 'no sé'?") se
rompe en cuanto el modelo reformula la frase, y se rompe en silencio.

### ¿Por qué los IDs de fragmento llevan un hash del texto?

Para que **cambiar la limpieza cambie el ID**. Si el ID fuera solo `documento+página+n`,
al mejorar una regla de limpieza el índice conservaría silenciosamente la versión vieja
del texto bajo el mismo identificador. Con el hash, un texto distinto es un fragmento
distinto y se reindexa.

El prefijo con el nombre del documento garantiza además que añadir un documento nuevo no
pueda pisar los fragmentos de otro: viven en espacios de nombres separados.

### ¿Por qué los prefijos `query:` y `passage:`?

Porque la familia de modelos E5 los exige. Omitirlos **no da ningún error**: simplemente
recupera peor, de forma silenciosa. Por eso la interfaz `Embedder` tiene dos métodos
(`codificar_pasajes` y `codificar_consultas`) en vez de uno: obliga a decir cuál es cuál
en cada llamada, y el error deja de ser posible.

### ¿Por qué el Reglamento se descarga pero no se indexa?

Es el **control** del experimento. El enunciado pide demostrar que el asistente reconoce
los límites de su corpus: muchas preguntas reales solo las responde el Reglamento. Tenerlo
descargado permite comprobar que la pregunta *sí* tenía respuesta en algún sitio, solo que
no en el corpus indexado. Sin ese control, "no lo sé" y "eso no está en mi corpus" serían
indistinguibles.

### ¿Por qué la evaluación no llama al modelo generativo?

Porque así es **gratis**, y algo gratis se repite. Todas las métricas (Recall@k, tasa de
abstención) miden la etapa de **recuperación**, que es anterior a la generación. Si
evaluar costara dinero, en la práctica se haría una vez y se dejaría de hacer — que es
exactamente como se acaba ajustando un umbral "a ojo". Es también lo que hace viable el
workflow de GitHub Actions que corre en cada push.

### ¿Qué mide cada métrica?

- **Recall@k** mide **el buscador**. Responde: entre los *k* fragmentos que el índice
  devuelve, ¿está el que contiene la respuesta? Si Recall@5 es bajo, ningún prompt ni
  ningún modelo puede arreglarlo: la información nunca llegó al contexto.

- **La tasa de abstención** mide **el umbral**, que es la política de decisión. Se separa
  en aciertos (abstenerse ante algo fuera de dominio) y errores (abstenerse ante algo que
  sí estaba). Son dos errores de coste muy distinto.

Detalle que sorprende y conviene explicar: **Recall@k no cambia en todo el barrido de
umbral**, y es correcto. El buscador devuelve siempre los mismos fragmentos en el mismo
orden; el umbral no cambia *qué* se recupera, solo *si se decide usarlo*. Son dos etapas
distintas y por eso hacen falta dos métricas.

---

## Cómo se lee cada resultado

### La tabla del barrido de umbral

Cada fila es un umbral candidato. La columna que decide es `aciertos_totales`: cuántas de
las 25 preguntas se resuelven bien, contando como acierto tanto responder una in-domain
como abstenerse ante una out-of-domain.

**Lo importante es que el óptimo es una meseta, no un punto.** 0.80, 0.82 y 0.84 empatan.
Se eligió 0.82 —el centro— porque deja el máximo margen antes de caer por cualquiera de
los dos lados. Es más robusto ante un corpus ligeramente distinto que tomar el primer
valor que empata.

### La tabla de BM25 frente a embeddings

Está separada por **estilo de pregunta**, y ahí está la gracia. Los embeddings ganan
siempre, pero la brecha se multiplica por cuatro en las preguntas coloquiales (de 1.4x a
3.0x), que son justamente las que hace el usuario real del sistema.

El ejemplo que lo explica en una frase: el empresario pregunta *"me piden una carta
fianza"*; la Ley dice *"garantía de fiel cumplimiento"*. **Cero palabras en común.** BM25
puntúa por coincidencia de términos, así que estructuralmente no puede encontrarlo.

### El mapa coroplético

El color es el número de procesos o el monto total por departamento. Lo que hay que saber
explicar es **de dónde sale el departamento**: no del texto del proceso, sino del campo
`Dirección:Departamento` de la parte con rol `buyer`, normalizado por la cascada de la
Fase 2. Es un atributo del comprador, no de la descripción.

### La tabla de riesgo

`pct_postor_unico` es la proporción de procesos **adjudicados** que recibieron exactamente
una oferta. Solo adjudicados: un proceso aún en convocatoria todavía puede recibir más
ofertas, y contarlo sería un error de interpretación.

El mínimo de 15 procesos por comprador existe porque sin él el ranking lo coparían
entidades con dos o tres procesos: una con 2 procesos y 1 postor único daría 50%, que no
distingue un patrón de una coincidencia.

---

## Alternativas evaluadas y descartadas

| Alternativa | Por qué se descartó |
|---|---|
| **Selenium/Playwright** para el portal de OECE | Encontré la API en el bundle JS. Evita 300 MB de navegador, es más rápido y no se rompe si cambia la maquetación |
| **La API de OECE para el corpus** | Pagina de 10 en 10: 20,422 procesos serían ~2,000 peticiones frente a 5 por bulk. Se usa solo para novedades y consultas por `ocid` |
| **Índice de control como discriminador** | **Medido y descartado.** Con margen 0.01 detecta 0 de 5 preguntas fuera de corpus y marca 4 de 20 válidas. La Ley y su Reglamento son el mismo dominio |
| **Umbral 0.86 para la Tarea 2** | Lo puse por suposición razonable. La medición dijo que 0.82 da el mismo acierto con cero abstenciones incorrectas |
| **FAISS** | Metadatos por separado = riesgo de citas incorrectas silenciosas |
| **Borrar filas sin departamento** | El enunciado penaliza descartar en silencio. Se etiquetan `NO_LOCALIZADO` y se conservan |
| **`Periodo de licitación` para la señal de plazo** | Inicio y fin idénticos en el 100% de los registros. Se usó el periodo de consulta |
| **XLSX en vez de CSV para los bulk** | 16.4 MB frente a 8.7 MB por mes, mismo contenido |

---

## Guion narrado: cómo contar el hallazgo central de la Tarea 1

> "Empecé con lo que pide el enunciado: un umbral de similitud por debajo del cual el
> sistema se abstiene. Y funciona para lo obvio. Le pregunté cómo se prepara un ceviche y
> puntuó 0.79, por debajo de mi umbral de 0.82, así que se abstuvo **sin llamar al
> modelo**: cero tokens, cero dólares.
>
> Pero entonces le pregunté algo que un empresario preguntaría de verdad: qué plazo tiene
> el comité para absolver consultas. Esa pregunta **no la puede responder mi sistema**,
> porque la responde el Reglamento y el Reglamento no está en mi índice a propósito.
>
> Puntuó **0.8869**. Mi umbral era 0.82. Pasó.
>
> Y aquí está lo que no esperaba: 0.8869 es **más alto que la media de mis veinte
> preguntas válidas**, que es 0.8809. Es más alto que trece de ellas individualmente. O
> sea que no hay ningún umbral que funcione: si lo subo para atrapar esta, empiezo a
> rechazar preguntas legítimas. Lo medí — a 0.86 ya rechazo tres válidas.
>
> El modelo de embeddings no se está equivocando. Tiene razón: esa pregunta *se parece*
> muchísimo a mi corpus. Es de contrataciones públicas, usa el mismo vocabulario jurídico.
> Lo que pasa es que la similitud semántica no puede distinguir *"habla de lo mismo"* de
> *"está respondida aquí"*. Esa segunda pregunta es jurídica, no semántica.
>
> Probé una solución: indexar el Reglamento en una colección aparte y comparar. Si la
> pregunta se parece más al Reglamento que a mi corpus, es de Reglamento. **No funciona**,
> y lo medí antes de meterlo: con margen 0.01 detecta cero de cinco y me marca cuatro de
> veinte preguntas buenas como sospechosas. Es ruido. La causa es de fondo: la Ley y su
> Reglamento son el mismo dominio y casi el mismo vocabulario.
>
> Así que la arquitectura final tiene **dos filtros con costos distintos**. El primero es
> el umbral, gratis, antes de llamar a la API, y atrapa lo evidentemente ajeno. El segundo
> es el propio modelo: le pido la respuesta en JSON con un campo `puede_responder`, y
> cuando ve que los fragmentos no contienen la respuesta, dice que no. Cuesta una llamada
> — tres décimas de milésimo de dólar — pero es la única forma de decidirlo, porque hay
> que **mirar el contenido**, no la similitud.
>
> Y el resultado se ve en la demo: ante esa pregunta el sistema no dice 'no sé'. Dice
> 'el corpus no cubre esa materia; lo que sí tengo trata de la elevación del pliego de
> absolución de consultas al OECE y del contenido de las ofertas, pero ninguno señala el
> plazo exacto'. Te dice qué tiene y qué le falta."
