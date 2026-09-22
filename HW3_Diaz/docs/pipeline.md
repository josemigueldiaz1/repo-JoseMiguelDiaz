# Diagramas para el video

Estos son los diagramas que se muestran en pantalla durante los primeros 4:30 del video,
**antes de enseñar una sola línea de código**. El enunciado es tajante: si el primer
contenido técnico del video es código, el criterio *"Pipeline explained before code"*
se califica con cero, y son 2.0 de los 8.0 puntos de la presentación.

Los diagramas de aquí están pensados para verse a pantalla completa. GitHub renderiza
Mermaid directamente, así que basta con abrir este archivo y compartir pantalla.

---

## 1. El problema, en un diagrama

```mermaid
flowchart LR
    M["MYPE peruana<br/>quiere venderle<br/>al Estado"] --> P1["No entiende<br/>las reglas"]
    M --> P2["No ve las<br/>oportunidades"]
    P1 --> S1["TAREA 1<br/>¿Qué dice la ley?"]
    P2 --> S2["TAREA 2<br/>¿Qué compra el Estado<br/>y dónde?"]
    S1 --> R["Un mismo motor RAG<br/>responde las dos"]
    S2 --> R
```

**Lo que hay que decir aquí:** son dos problemas distintos del mismo usuario. Contratar
un abogado para cada duda cuesta más que muchos de los contratos a los que podría
postular; y se publican miles de procesos al mes que nadie lee enteros.

---

## 2. Tarea 1 — Lo que pasa UNA VEZ (proceso offline)

```mermaid
flowchart TD
    A1["Ley 32069<br/>63 páginas · gob.pe"] --> B
    A2["DS 001-2026-EF<br/>16 páginas · El Peruano"] --> B
    B["COMPROBACIÓN DE FUENTES<br/>¿cuántas páginas?<br/>¿cuántos caracteres por página?<br/>¿hay páginas sin texto?<br/>¿el orden de lectura es correcto?"]
    B -->|alguna NO es usable| STOP(["Se detiene.<br/>Se declara en el README."])
    B -->|las dos son usables| C

    C["EXTRACCIÓN PÁGINA A PÁGINA<br/>cada trozo de texto nace<br/>con su número de página pegado"]
    C --> D["LIMPIEZA<br/>quitar cabeceras de El Peruano<br/>unir palabras partidas por guion"]
    D --> E["TROCEADO POR PÁGINA<br/>900 caracteres · solape 150<br/>ID = documento + página + hash"]
    E --> F["EMBEDDINGS LOCALES<br/>multilingual-e5-small en CPU<br/>prefijo passage:"]
    F --> G[("ChromaDB<br/>511 fragmentos<br/>persistido en disco")]
```

**Los tres puntos que el enunciado pide decir aquí:**

1. **Dónde vive el número de página, y por qué es metadato y no texto.** El troceado se
   hace *página por página*, nunca sobre el documento entero. Si se concatenara todo y se
   partiera después, cada fragmento quedaría sin saber de dónde salió, y recuperarlo
   después obliga a buscar el fragmento dentro del PDF — que falla justo en el caso más
   común de un texto legal: párrafos casi idénticos que se repiten.

2. **La comprobación de fuentes va primero, antes de construir nada.** Una fuente
   ilegible cambia el plan entero del proyecto, y descubrirlo el último día es fatal.

3. **El precio de trocear por página** es que un artículo a caballo entre dos páginas
   queda partido. Se compensa con el solape, y es el intercambio correcto: mejor un
   fragmento algo más corto que una cita equivocada.

---

## 3. Tarea 1 — Lo que pasa en CADA PREGUNTA (proceso online)

```mermaid
flowchart TD
    Q["Pregunta del usuario"] --> R["Embedding de la consulta<br/>prefijo query:"]
    R --> S["Buscar los 5 fragmentos<br/>más parecidos en ChromaDB"]
    S --> T{{"FILTRO 1 — GRATIS<br/>¿la mejor similitud<br/>llega a 0.82?"}}

    T -->|NO| U["SE ABSTIENE<br/>0 tokens · $0.00<br/>nunca se llamó a la API"]
    T -->|SÍ| V["Montar el contexto:<br/>cada fragmento etiquetado<br/>con su documento y página"]

    V --> W["DeepSeek · temperatura 0<br/>respuesta obligada en JSON"]
    W --> X{{"FILTRO 2 — CUESTA<br/>¿el modelo dice<br/>puede_responder = true?"}}

    X -->|false| Y["SE ABSTIENE<br/>explicando qué SÍ cubre<br/>el corpus"]
    X -->|true| Z["RESPUESTA<br/>citando documento y página"]
    Z --> AA{{"¿alguna fuente es<br/>norma modificatoria?"}}
    AA -->|sí| AB["+ nota de versión"]
    AA -->|no| AC["Entregar"]
    AB --> AC
```

**El punto donde el sistema decide no llamar al LLM** es el rombo del FILTRO 1. Hay que
señalarlo explícitamente en el video: el enunciado lo pide por su nombre.

**Por qué hacen falta dos filtros** — esta es la tabla que se enseña justo después:

| Pregunta | Similitud | ¿Quién la atrapa? |
|---|---:|---|
| "¿Cómo preparo un ceviche?" | 0.7934 | Filtro 1, gratis |
| "¿Cuál es la capital de Francia?" | 0.7626 | Filtro 1, gratis |
| **"¿Qué plazo tiene el comité para absolver consultas?"** | **0.8869** | **Filtro 2** |
| *Media de las 20 preguntas válidas* | *0.8809* | — |

La tercera fila es el argumento entero: **una pregunta que el sistema no puede responder
puntúa por encima de la media de las que sí puede.** No hay ningún umbral que las separe,
porque son del mismo dominio y el mismo vocabulario.

---

## 4. Tarea 2 — De un portal sin enlaces a 20,422 procesos

```mermaid
flowchart TD
    A["Portal de contrataciones abiertas<br/>Las 3 URLs devuelven el MISMO<br/>HTML de 2,837 bytes"] --> B{{"¿Por qué?"}}
    B --> C["Es una SPA de Angular:<br/>el contenido lo construye<br/>JavaScript en el navegador"]
    C --> D["Opción A: automatizar un navegador<br/>~300 MB, lento, frágil<br/>DESCARTADA"]
    C --> E["Opción B: buscar la API<br/>que usa la propia página"]
    E --> F["Descargar main.js<br/>3.2 millones de caracteres<br/>y buscar rutas con regex"]
    F --> G["/api/v1/files<br/>/api/v1/file/:fuente/:formato/:año/:mes<br/>/api/v1/releases · /api/v1/record/:ocid"]
    G --> H["3 ZIP mensuales<br/>26.5 MB · 5 peticiones HTTP"]
```

**La frase para el video:** cuando un portal no devuelve nada útil al scraper, la pregunta
correcta no es *"¿cómo simulo un navegador?"* sino *"¿de dónde saca sus datos el
navegador?"*.

**El argumento de bulk contra API:** la API pagina de 10 en 10. Reunir 20,422 procesos
por ahí serían unas 2,000 peticiones; por bulk fueron **5**. La API se usa para lo que sí
es buena: novedades recientes y consultar un proceso concreto por su `ocid`.

---

## 5. Tarea 2 — OCDS: release, record y ocid

```mermaid
flowchart LR
    O["ocid<br/>ocds-dgv273-seacev3-1251159<br/><i>identifica el PROCESO entero</i>"]
    O --> R1["release 1<br/>se convocó"]
    O --> R2["release 2<br/>se adjudicó"]
    O --> R3["release 3<br/>se firmó el contrato"]
    R1 --> C["record / compiled release<br/><b>la foto de HOY</b>"]
    R2 --> C
    R3 --> C
    C --> D["Registros.csv<br/>UNA fila por proceso"]
```

- El **ocid** es el hilo que cose todo el proceso, desde la planificación hasta la
  liquidación.
- Un **release** es *una novedad*: se convocó, se adjudicó, se firmó.
- Un **record** es la **foto actual**: el resultado de aplicar todos los releases en orden.

Para un radar de oportunidades interesa el record, porque responde *"¿en qué estado está
hoy?"* y no *"¿qué pasó el martes?"*. Por eso la unidad de análisis es **una fila por ocid**.

---

## 6. Tarea 2 — La cascada territorial

```mermaid
flowchart TD
    A["20,422 procesos"] --> B{{"1 · ¿El comprador declara<br/>su Departamento?"}}
    B -->|sí| OK1["✓ campo_departamento"]
    B -->|no| C{{"2 · ¿Declara Región?"}}
    C -->|sí| OK2["✓ campo_region"]
    C -->|no| D{{"3 · ¿Esa MISMA entidad declaró<br/>su departamento en otro proceso?"}}
    D -->|sí| OK3["✓ imputado_por_entidad<br/><i>no se inventa: se propaga<br/>un dato de la propia entidad</i>"]
    D -->|no| E{{"4 · ¿La Localidad se parece<br/>a algún departamento, con score ≥88?"}}
    E -->|sí| OK4["✓ fuzzy_localidad"]
    E -->|no| F["NO_LOCALIZADO<br/><i>se etiqueta, NO se borra</i>"]
```

**El criterio del enunciado**, literal: *"Silently dropping bad rows is a failing
approach. Dropping them with a logged, justified rule is a passing approach. Correcting
the recoverable ones and reporting the recovery rate is an excellent approach."*

Por eso ninguna regla borra filas: cada una marca, cuenta y declara qué se hizo.

**Resultado:** 100% localizados, los 20,422.

---

## 7. Tarea 2 — La consulta híbrida

```mermaid
flowchart TD
    Q["«obras de agua y saneamiento<br/>en Cusco por más de un millón»"] --> SPLIT{{"Tres condiciones<br/>de naturaleza distinta"}}

    SPLIT --> S["SEMÁNTICA<br/>«obras de agua y saneamiento»<br/><i>no hay columna que diga eso;<br/>hay mil formas de decirlo</i>"]
    SPLIT --> N["NUMÉRICA<br/>«más de un millón»<br/><i>900,000 se parece pero NO cumple</i>"]
    SPLIT --> T["TERRITORIAL<br/>«en Cusco»<br/><i>es atributo del comprador,<br/>no del texto</i>"]

    N --> FIL["FILTROS EXACTOS<br/>monto ≥ 1,000,000<br/>departamento = CUSCO"]
    T --> FIL
    FIL --> UNI["Universo acotado"]

    S --> EMB["EMBEDDINGS<br/>ordenar por significado"]
    UNI --> EMB
    EMB --> RES["Top-k procesos<br/>citados por su ocid"]
```

**El orden importa:** primero se acota el universo con condiciones exactas, después se
ordena lo que queda por parecido. Al revés produciría menos de *k* resultados cuando el
filtro es selectivo, porque los *k* mejores globales pueden no cumplir ninguna condición.

**Y esto es lo que pasa medido** (el departamento en el texto frente a como filtro):

| | Cusco | Puno | Loreto | Arequipa | Piura | **Media** |
|---|---:|---:|---:|---:|---:|---:|
| En el texto | 50% | 40% | 70% | **0%** | 90% | **50%** |
| Como filtro | 100% | 100% | 100% | 100% | 100% | **100%** |

---

## 8. Cómo se conectan las dos tareas (innovación)

```mermaid
flowchart LR
    U["La MYPE pregunta al radar:<br/>«obras de saneamiento en Cusco»"] --> T2["TAREA 2<br/>encuentra el proceso<br/>ocid · 2.1M PEN<br/>método: Adjudicación Simplificada"]
    T2 --> BTN["Botón:<br/>«¿Qué dice la ley sobre<br/>Adjudicación Simplificada?»"]
    BTN --> T1["TAREA 1<br/>llama a motor.responder<br/><b>el MISMO motor</b>"]
    T1 --> ANS["Qué dice la Ley,<br/>citando artículo y página"]
```

Son **veinte líneas de código**. No añaden ningún mecanismo: solo llaman a la función del
motor de la otra tarea. Si el motor no estuviera separado de su interfaz, esto sería
imposible sin duplicar código — y esa es exactamente la razón por la que el enunciado
exige que el motor no importe Streamlit.

Las dos preguntas del proyecto quedan respondidas en la misma pantalla.
