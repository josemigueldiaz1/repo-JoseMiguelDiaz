# Material para el video

Todo lo que se puede comentar en la presentación, en un solo lugar: hallazgos, decisiones
técnicas, obstáculos y explicaciones del proyecto.

- ⭐ marca lo que mejor funciona contado en cámara.
- Se amplía al cerrar cada fase. Estado: **las cinco fases completas**.
- El estado del trabajo y los siguientes pasos van aparte, en `estado.md`.

**Índice:** [1. El problema](#1-el-problema-y-el-ámbito) · [2. Hallazgos](#2-hallazgos) ·
[3. Decisiones técnicas](#3-decisiones-técnicas) · [4. Obstáculos](#4-obstáculos) ·
[5. Cómo funciona el proyecto](#5-cómo-funciona-el-proyecto) ·
[6. Innovación](#6-innovación-puntos-extra) · [7. Limitaciones](#7-limitaciones-declaradas)

---

## 1. El problema y el ámbito

- **La pregunta:** cuánto tarda *realmente* la población peruana, por carretera, en llegar a
  un establecimiento de salud con capacidad resolutiva, y dónde están las peores brechas.
- **Por qué importa:** los puestos I-1 estabilizan pero no operan ni hacen cesáreas. Solo
  desde categoría **II-1** hay capacidad resolutiva. En una emergencia obstétrica o un
  trauma grave, esa diferencia es la vida.
- **La palabra clave del enunciado es "realmente"**: red vial en vez de línea recta, y datos
  auditados en vez de un registro tomado al pie de la letra.
- **Tres departamentos, uno por región natural**, para que el contraste geográfico sea el eje
  del análisis: **Lambayeque** (costa, red densa), **Ayacucho** (sierra, topografía que
  alarga los tiempos), **Loreto** (selva, conectividad fluvial).
- **Escala:** 215 distritos · 15 418 centros poblados · 2 732 389 habitantes · 2 838
  establecimientos de salud.

---

## 2. Hallazgos

### 2.1 En Loreto la red vial no sirve a la población ⭐⭐

*El hallazgo más fuerte del proyecto. No es un problema técnico: es el resultado.*

- **Cómo apareció:** el **factor de rodeo** (km por carretera ÷ km en línea recta) confirmó
  la hipótesis en dos departamentos y la rompió en el tercero.

  | Departamento | Factor | Lectura |
  |---|---:|---|
  | Ayacucho | **2.14** | Las carreteras andinas serpentean: recorres el doble. Esperado |
  | Lambayeque | **1.29** | Malla plana y densa. Esperado |
  | Loreto | **1.06** | Diría que las carreteras amazónicas son rectas. **Implausible** |

- **La causa:** OSRM engancha cada punto a la vía más cercana y rutea **desde ahí**,
  ignorando el tramo intermedio. Se midió esa distancia de enganche sobre 5 000 puntos:

  | Departamento | Mediana | p90 | Máximo |
  |---|---:|---:|---:|
  | Lambayeque | **107 m** | 543 m | 10 km |
  | Ayacucho | **207 m** | 2.3 km | 11 km |
  | **Loreto** | **8 901 m** | **43.8 km** | **134 km** |

- En costa y sierra el centro poblado mediano está a ~100-200 m de una carretera. **En Loreto
  está a casi 9 km**, y uno de cada diez a más de 44 km. El factor de 1.06 era un artefacto:
  el numerador no incluía el tramo que falta.
- **La solución:** se marca `fuera_de_red` todo punto que enganche a más de **2 000 m**. No
  es arbitrario: 2 km caminando son ~24 min, o sea que el tramo fuera de red consumiría por
  sí solo casi entera la banda de cobertura más estricta (30 min).
- Esos puntos **no se borran ni se rellenan** con distancia euclidiana (el enunciado lo
  prohíbe): se reportan aparte. **La diferencia entre la métrica con y sin ellos *es* la
  medida de cuánta población queda fuera del alcance vial.**
- **Resultado con umbral de 2 km:** 1 571 de 5 000 puntos (31.4 %) — **294 234 habitantes,
  10.8 % del ámbito**.

  | Departamento | Puntos fuera | % de su población |
  |---|---:|---:|
  | Lambayeque | 25 / 1 224 | 0.8 % |
  | Ayacucho | 238 / 2 096 | 4.3 % |
  | **Loreto** | **1 308 / 1 680 (78 %)** | **32.5 %** |

- **La conclusión no depende del umbral** — esto blinda el hallazgo frente a la crítica de
  "elegiste 2 km a dedo":

  | Umbral | Ayacucho | Lambayeque | **Loreto** |
  |---:|---:|---:|---:|
  | 500 m | 8.9 % | 3.1 % | 36.8 % |
  | **2 000 m** | **4.3 %** | **0.8 %** | **32.5 %** |
  | 5 000 m | 1.2 % | 0.2 % | 27.7 % |
  | **10 000 m** | **0.0 %** | 0.1 % | **24.0 %** |

- Incluso con el umbral más permisivo imaginable —10 km, media hora larga caminando—
  Ayacucho cae a **cero** y Loreto se mantiene en **24 %**. El contraste no se disuelve
  estirando el umbral: se hace más nítido.
- **La frase de cierre:** *el problema no es que falten carreteras en Loreto; es que medir el
  acceso amazónico con una red vial es la pregunta equivocada.*

> **Guion de 8 pasos ⭐** — encadena método y hallazgo, es el mejor momento narrativo:
> 1. "Elegí costa, sierra y selva esperando que el terreno cambiara los tiempos."
> 2. "El factor de rodeo confirmó la hipótesis en dos: Ayacucho 2.14, Lambayeque 1.29."
> 3. "Pero Loreto dio 1.06, como si sus carreteras fueran rectas. Eso no podía ser."
> 4. "Revisé el snapping: el centro poblado mediano de Loreto está a 9 km de la carretera
>    más cercana. Algunos, a 134 km."
> 5. "OSRM enganchaba esos puntos a una vía lejana y ruteaba desde ahí, regalándoles los
>    primeros 9 km. Por eso el indicador salía bonito."
> 6. "Lo resolví marcándolos como fuera de red, con un umbral de 2 km justificado en que
>    caminarlos consume la banda de cobertura de 30 minutos."
> 7. "Y verifiqué que no depende del umbral: en 10 km, Ayacucho cae a 0.0 % y Loreto sigue
>    en 24 %."
> 8. "El hallazgo no es que falten carreteras. Es que la pregunta estaba mal planteada."

### 2.2 Solo 48 establecimientos resolutivos para 2.7 millones de personas ⭐

- De 2 838 establecimientos en el ámbito, apenas **48 son resolutivos** (II-1 o superior,
  activos), y solo **44** tienen coordenadas utilizables para rutear.

  | Departamento | Población | Resolutivos | Habitantes por resolutivo |
  |---|---:|---:|---:|
  | Lambayeque | 1 238 761 | 22 | 68 820 |
  | Ayacucho | 715 240 | 12 | 59 603 |
  | Loreto | 778 389 | 14 | 55 599 |

- **El ratio es engañosamente parecido entre los tres.** Lo que cambia radicalmente es la
  **distribución en el territorio**.
- En Lambayeque los 18 resolutivos mapeables están prácticamente todos dentro del núcleo
  urbano de Chiclayo, dejando vacío el resto del departamento. Se ve de un vistazo en
  `report/figures/fase1_ambito.png`.
- **Conclusión preliminar:** el problema peruano de acceso resolutivo no es tanto de
  **cantidad** como de **concentración geográfica**.

### 2.3 Un tercio del registro nacional no tiene coordenadas ⭐

- **13 176 de 36 004 registros de RENIPRESS (36.6 %) no tienen coordenadas**, y 2 más las
  tienen en (0, 0).
- **Efecto sobre este estudio:** la oferta está subestimada. Hay establecimientos reales que
  el análisis no ve, así que los tiempos calculados son, si acaso, pesimistas.
- **Recomendación de política:** un registro nacional de prestadores en el que un tercio de
  las entradas carece de georreferencia **no permite planificar cobertura territorial**.
  Antes de decidir dónde poner el próximo hospital, hay que poder ubicar los que ya existen.

### 2.4 La oferta resolutiva cambia mes a mes

- Comparando los cortes de RENIPRESS de abril y agosto de 2026 en el mismo ámbito: **46
  altas, 0 bajas, 17 cambios de categoría, 30 cambios de estado**; 2 establecimientos
  ganaron capacidad resolutiva y 1 la perdió.
- Los resolutivos pasaron de **45 a 48 en cuatro meses**: un neto de +7 % sobre la base.
- **El resultado de este estudio tiene fecha de caducidad.** La fecha del corte (31-08-2026)
  es parte del resultado, no un pie de página.

### 2.5 La paradoja de Loreto: filtrar por red vial lo hace parecer *mejor* ⭐⭐

*El resultado más contraintuitivo del proyecto, y el más importante de explicar bien.*

| Departamento | Mediana con **todos** los puntos | Mediana solo **en red** | p90 en red | Inalcanzables por carretera |
|---|---:|---:|---:|---:|
| Lambayeque | 28.7 min | **28.3 min** | 84.8 min | 0.0 % |
| Ayacucho | 66.1 min | **60.2 min** | 160.6 min | 0.0 % |
| **Loreto** | 126.1 min | **47.3 min** | **2 204.5 min** | **7.8 %** |

- En Lambayeque y Ayacucho, filtrar a los puntos que la red vial sirve de verdad casi no
  cambia nada (−0.4 y −5.9 min): casi toda su población **está** sobre la red.
- **En Loreto la mediana CAE de 126 a 47 minutos.** Filtrar lo hace parecer *mejor que
  Ayacucho*.
- **Eso no es una mejora: es un efecto de selección.** La red vial de Loreto solo llega a los
  lugares que ya están cerca de un hospital — el entorno de Iquitos y los pocos ejes viales.
  Al quedarnos con "los puntos que la carretera sirve", nos quedamos justamente con los
  privilegiados y borramos del cálculo al 32.5 % de la población.
- El p90 lo delata: **2 204 minutos, casi 37 horas**, incluso entre los puntos que sí están
  sobre la red. La distribución no es que sea mala; es que está partida en dos mundos.
- **Cómo decirlo:** *"Si reporto solo los puntos que la carretera alcanza, Loreto sale mejor
  que Ayacucho. Sería el número más engañoso de todo el informe: la carretera solo llega
  donde ya hay hospital."*

### 2.6 Caminar no es "el mismo viaje pero más lento" ⭐

El enunciado advertía que la razón caminar/conducir no es constante y que las discrepancias
son hallazgos, no errores. Se confirma en los tres departamentos:

| Departamento | Auto (mediana) | A pie | Bici | Razón pie/auto | Razón bici/auto |
|---|---:|---:|---:|---:|---:|
| Lambayeque | 28.7 min | 401.9 min | 184.2 min | **12.6×** | 6.0× |
| Ayacucho | 66.1 min | 748.1 min | 301.5 min | **10.5×** | 4.1× |
| Loreto | 126.1 min | 636.4 min | 251.8 min | **6.5×** | 2.6× |

- **La razón varía casi al doble entre departamentos** (6.5× en Loreto contra 12.6× en
  Lambayeque). No existe un "factor de conversión" universal entre modos.
- **Contraintuitivo:** la penalización por caminar es *menor* en Loreto. La explicación es que
  su red vial es tan escasa que el auto tampoco aprovecha gran cosa: no hay autopistas que
  amplifiquen la ventaja del motor.
- **El establecimiento más cercano CAMBIA según el modo** en una fracción enorme de los
  puntos: entre **17 % y 47 %**. El caso extremo es la bicicleta en Lambayeque (**47.3 %**):
  casi la mitad de la población tiene un hospital más cercano en bici que en auto, porque la
  red ciclable y la vial no coinciden.
- **Implicación práctica:** un plan de referencia de emergencias que asuma "el hospital más
  cercano" sin especificar el modo de transporte está mal en uno de cada tres casos.
- A pie, los puntos que no alcanzan **ningún** resolutivo suben de 131 (2.6 % en auto) a
  **443 (8.9 %)**.

### 2.7 Acceso urbano cotidiano: el sistema sí funciona de cerca

Caminando al establecimiento más cercano **de cualquier categoría** (posta, centro de salud),
desde los puntos de demanda urbanos:

| Departamento | n válidos | Mediana | p90 |
|---|---:|---:|---:|
| Ayacucho | 160 | **4.3 min** | 22.5 min |
| Lambayeque | 112 | **7.0 min** | 56.6 min |
| Loreto | 50 | **5.8 min** | 39.4 min |

- **El contraste con el resto del estudio es el punto.** Para la atención cotidiana urbana, el
  sistema peruano responde: una posta a menos de 10 minutos caminando. **El problema no es la
  atención primaria: es la capacidad resolutiva.**
- Esa es la brecha que el estudio mide: 5 minutos hasta una posta que puede estabilizarte,
  frente a 47-126 minutos hasta un establecimiento que puede operarte.

### 2.8 La cobertura, en una sola figura ⭐⭐

`report/figures/fase3_bandas.png` resume el estudio entero. Porcentaje de población según
cuánto tarda en llegar a un establecimiento resolutivo:

| Departamento | ≤30 min | 30-60 | 60-120 | >120 min | **Sin acceso vial** |
|---|---:|---:|---:|---:|---:|
| Lambayeque | **82 %** | 10 % | 5 % | 2 % | **0.8 %** |
| Ayacucho | 58 % | 15 % | 16 % | 7 % | **4.3 %** |
| **Loreto** | 35 % | 5 % | 2 % | 20 % | **38 %** |
| **Total ámbito** | 62.3 % | 9.9 % | 6.8 % | 8.8 % | **12.2 %** |

- **El titular:** en el ámbito estudiado, **el 72.2 % de la población llega en menos de una
  hora** a un establecimiento que puede operarla… y **el 12.2 % no llega por carretera en
  absoluto**.
- En Loreto, sumando los que tardan más de dos horas y los que no tienen acceso vial,
  **el 58 % de la población está mal servida**.
- La barra morada de Loreto es el argumento visual más fuerte del proyecto.

### 2.9 Dos departamentos igual de desiguales, uno el doble de lento ⭐

Gini del tiempo de acceso, ponderado por población:

| Ámbito | Gini | Media ponderada |
|---|---:|---:|
| Lambayeque | **0.633** | 19.3 min |
| Ayacucho | **0.639** | 38.8 min |
| Loreto | 0.864 | 331.9 min |
| Total | 0.864 | 88.1 min |

- **Lambayeque y Ayacucho tienen prácticamente el mismo Gini (0.633 y 0.639) pero Ayacucho
  tarda el doble.** Eso ilustra exactamente qué mide y qué no mide el Gini: **dispersión, no
  nivel**.
- **Advertencia de interpretación que hay que decir en voz alta:** el Gini se usa
  normalmente sobre ingresos, donde *más es mejor*. Aquí se aplica al tiempo de viaje, donde
  *más es peor*. **Un Gini de 0 significaría que todos tardan lo mismo, no que todos estén
  bien atendidos**: un territorio donde todo el mundo tarda tres horas tendría Gini 0 y un
  acceso pésimo. Por eso nunca se reporta solo, sino junto a la media y a las bandas.
- Se reportan **las dos cosas** que el enunciado permite elegir: el Gini como número
  comparable, y la curva de Lorenz como figura, porque el número solo resume y la curva
  enseña de dónde sale la desigualdad.

### 2.10 Lo rural amazónico es otro país ⭐

| Departamento | Ámbito | Población | Tiempo medio | Sin acceso vial |
|---|---|---:|---:|---:|
| Lambayeque | urbano | 939 141 | **11.8 min** | 0.6 % |
| Lambayeque | rural | 299 620 | 43.0 min | 1.5 % |
| Ayacucho | urbano | 469 158 | 30.7 min | 1.6 % |
| Ayacucho | rural | 246 081 | 55.7 min | 9.3 % |
| Loreto | urbano | 577 771 | 196.1 min | 25.6 % |
| **Loreto** | **rural** | **200 617** | **1 394.6 min** | **72.6 %** |

- La brecha urbano/rural es de **1.8× en Lambayeque, 1.8× en Ayacucho… y 7.1× en Loreto**.
- **La población rural de Loreto tarda de media 23 horas**, y **casi tres de cada cuatro
  personas no tienen acceso por carretera**.
- Es la misma brecha que en el resto del país, pero de otro orden de magnitud.

### 2.11 La pobreza predice el acceso solo donde la geografía no manda ⭐⭐

*El hallazgo más sutil del proyecto, y el que mejor demuestra que se entendió el dato.*

Correlación entre la tasa de pobreza distrital y el tiempo medio de acceso:

| Departamento | n | Pearson *r* | *p* | Lectura |
|---|---:|---:|---:|---|
| **Lambayeque** | 38 | **+0.798** | **<0.001** | Fortísima |
| Ayacucho | 104 | +0.229 | 0.019 | Débil pero significativa |
| **Loreto** | 36 | +0.186 | **0.278** | **No significativa** |
| Total | 178 | +0.136 (Spearman +0.470) | <0.001 | Moderada |

- **La correlación más fuerte está en el departamento con MEJOR acceso, y no hay correlación
  en el peor.** Contraintuitivo, y tiene explicación:
- En **Loreto la geografía manda sobre todo lo demás**: seas pobre o no, si vives río arriba
  estás lejos. La pobreza no añade información porque la distancia ya está determinada.
- En **Lambayeque, donde hay carreteras en todas partes**, la variación que queda en el
  acceso sí sigue la línea de la pobreza: los distritos pobres son los peor conectados
  *dentro* de una red que existe.
- **La pobreza predice el acceso solo allí donde la geografía no lo ha decidido ya.**
- **Naturaleza de la relación, que el enunciado obliga a declarar: correlacional, no causal.**
  Hay un confusor común evidente —la lejanía— que mueve ambas variables a la vez: los
  distritos remotos son más pobres *y* están más lejos de un hospital, sin que lo uno cause
  lo otro. Tampoco puede descartarse la causalidad inversa. El dato sirve para **priorizar**,
  no para explicar.
- **Cuadrante de doble carga:** 62 distritos son a la vez más pobres y peor comunicados que
  la mediana. **420 053 habitantes, el 15.4 % del ámbito.** Es la lista de priorización que
  saldría de este estudio.

### 2.12 Treinta y tres distritos sin ningún acceso vial

- En **33 distritos** (16 de Ayacucho y 17 de Loreto) **ningún punto de demanda tiene un
  tiempo de viaje interpretable**: o no alcanzan ningún resolutivo por carretera, o están
  todos fuera de la red vial.
- No es un hueco de datos: es que **la red vial no sirve al distrito entero**.
- Quedan fuera del cruce con pobreza, y esa exclusión se reporta explícitamente separada de
  los 4 distritos que faltan por no tener dato de pobreza.

### 2.13 Media contra mediana: en Loreto no dicen lo mismo

- Loreto tiene una **media ponderada de 331.9 min pero una mediana ponderada de 22.5 min**.
- No es un error: la mediana está dominada por Iquitos, donde vive la mayor parte de la
  población y hay hospitales cerca. La media la arrastra una cola extrema de comunidades
  fluviales.
- **Cuál reportar depende de la pregunta.** "¿Cuánto tarda el peruano típico de Loreto?" →
  la mediana. "¿Cuánta capacidad de traslado necesita el sistema?" → la media. Reportar solo
  una de las dos, sin decir cuál, es la forma más fácil de engañar con datos correctos.

### 2.14 Doce hospitales intercambiables: la Amazonía es una isla vial ⭐⭐

*Descubierto al validar el simulador de escenarios, y es el hallazgo con la implicación de
política más directa de todo el proyecto.*

- Al rankear qué ascenso de un puesto I-3/I-4 ganaría más cobertura, **ocho establecimientos
  distintos daban exactamente la misma cifra: 104 571 habitantes**. Eso olía a bug.
- No lo era. Al comprobarlo: **12 establecimientos, repartidos en 8 distritos de Loreto
  (Balsapuerto, Capelo, Jenaro Herrera, Nauta, Parinari, Puinahua, Requena, Yaquerana), sobre
  un área de 238 × 276 km, alcanzan EXACTAMENTE los mismos 290 centros poblados.** Conjuntos
  idénticos, ni un punto de diferencia.
- La razón: **todos están en el mismo componente aislado de la red vial amazónica.** Esa
  carretera no conecta con el resto del país. Desde el punto de vista de esos 290 centros
  poblados, los 12 establecimientos son perfectamente intercambiables.
- **De esos 290 puntos, 251 (el 87 %) hoy no tienen ningún acceso resolutivo por carretera.**
  Representan **105 856 habitantes**.

**La implicación de política, que es lo que hay que decir:**

> El problema no es *cuál* de esos doce establecimientos ascender: cualquiera rinde lo mismo.
> El problema es que el componente está aislado. Ascender uno resuelve el acceso de 290
> comunidades que hoy no lo tienen — y ascender los doce no resuelve ni una más.

- Eso convierte la pregunta "¿dónde ponemos el próximo hospital resolutivo?" en una pregunta
  distinta: dentro de ese componente **hay doce respuestas igual de buenas**, así que la
  decisión se toma por otros criterios (costo, personal disponible, infraestructura
  existente) y no por accesibilidad.
- **Cómo contarlo:** *"Vi ocho establecimientos con la misma ganancia exacta y pensé que
  tenía un bug. Lo comprobé: no era un bug, era la red vial. Doce hospitales separados por
  cientos de kilómetros sirven exactamente a la misma gente, porque están todos en el mismo
  pedazo de carretera que no lleva a ninguna parte."*

---

## 3. Decisiones técnicas

*El enunciado pide al menos tres puntos de decisión entre alternativas, con su razonamiento.
Hay seis.*

### 3.1 Motor de ruteo: OSRM ⭐⭐

| Opción | Veredicto |
|---|---|
| **OSRM en Docker** | **Elegida.** Sin límite de consultas, matrices en milisegundos, funciona offline |
| OSMnx + NetworkX | Descartada: Loreto tiene 368 000 km²; grafo enorme, lento y pesado en memoria **en cada corrida** |
| OpenRouteService | Descartada: cuota limitada y **no funciona sin internet** — la demo del video dependería de la conexión |

- **El resultado medido: 13 200 pares origen-destino en 0.3 segundos.**
- **El costo:** OSRM solo existe para Linux, así que hubo que instalar WSL2 y Docker. El
  intercambio fue *30 minutos de instalación una vez* contra *horas de cómputo en cada
  corrida, para siempre*.

### 3.2 Qué hacer con los puntos que la red no alcanza ⭐

| Opción | Veredicto |
|---|---|
| Rellenar con distancia euclidiana × factor de rodeo | **Prohibido** por el enunciado sin justificación empírica |
| Descartarlos | Descartada: se perdería justo la población más vulnerable |
| **Marcarlos y reportarlos aparte** | **Elegida.** La diferencia entre ambas métricas es en sí el resultado |

### 3.3 Fuente de los puntos de demanda: sustitución de SIGMED ⭐

- El enunciado señala **SIGMED (MINEDU)**, pero es una aplicación interactiva de ArcGIS sin
  URL de descarga directa: hay que aceptar términos, navegar un visor y generar el archivo a
  mano. **No es automatizable ni reproducible.**
- Alternativas: automatizar el visor con Selenium (frágil), la capa ArcGIS de INEI en
  Geocatmin (sin paginación, tope de 1 000 registros, población del censo de 1999).
- **Elegida:** shapefile de **Centros Poblados del IGN** en Datos Abiertos — 136 587 puntos,
  descarga directa, misma necesidad cubierta.
- El propio enunciado lo anticipa: *"esto es un hallazgo legítimo sobre los datos abiertos
  peruanos, no un fracaso"*.

### 3.4 Imputación de población: WorldPop al vecino más cercano ⭐

- **El problema:** el shapefile del IGN trae coordenadas pero **no población**, y la Fase 3
  exige que toda agregación sea ponderada.

| Opción | Veredicto |
|---|---|
| Censo 2017 vía REDATAM | Descartada: sistema de consulta interactivo, no automatizable |
| Repartir la población distrital en partes iguales | Descartada: iguala un caserío de 12 personas con un pueblo de 12 000 |
| Buffer de radio fijo sobre el ráster | Descartada: deja fuera la población dispersa y duplica los solapes |
| **Cada celda de WorldPop al centro poblado más cercano del mismo distrito** | **Elegida** |

- **Tres propiedades que la justifican:** conserva el total (verificado al 100.0000 %),
  respeta la frontera administrativa, y modela la dispersión rural sin fijar un radio
  arbitrario.

### 3.5 Muestreo: estratificado por distrito y ponderado por población ⭐

- El enunciado topa el análisis en 5 000 puntos de demanda, y hay 15 418.
- **Una muestra aleatoria simple habría dejado distritos enteros sin representar**, y las
  métricas se agregan justamente a nivel distrital.
- **Elegido:** un punto garantizado por distrito + reparto proporcional a población por
  **restos mayores** (Hamilton), que usa el presupuesto completo en vez de perderlo al
  truncar.
- Cada punto lleva un `peso_muestral` que expande la población de su estrato. **Resultado
  verificado: 5 000 puntos, 215/215 distritos representados, población reproducida con
  desvío 0.000000 %** distrito por distrito.
- **Error muestral que hay que declarar:** la varianza *dentro* del distrito no se captura.

### 3.6 Qué segunda dimensión cruzar, y cuál descartar ⭐

El enunciado exige cruzar el acceso con una segunda dimensión. Se evaluaron tres:

| Opción | Veredicto |
|---|---|
| Población menor de 5 años (WorldPop por edad) | Descartada: **590 MB por archivo**, cuatro archivos, 2.4 GB para una sola variable |
| `PBI_PC` e `IDH` de la tabla del curso | **Descartadas por un motivo de fondo**: tienen **un único valor por departamento repetido en cada distrito**. No aportan variación distrital, y cualquier correlación con ellas a nivel distrito sería un artefacto de estar comparando tres departamentos |
| **Tasa de pobreza monetaria distrital** | **Elegida**: varía de verdad distrito a distrito (115 valores distintos entre los 119 de Ayacucho) |

- **Cómo se detectó lo del IDH:** contando valores distintos por departamento antes de
  usarlos. `PBI_PC` e `IDH` daban 1, 1 y 1. Es una comprobación de treinta segundos que evita
  publicar una correlación inventada.
- **Limitación declarada:** la tabla viene del material del curso y **no documenta su año ni
  su fuente exacta**. Cubre 210 de los 215 distritos; los 5 que faltan son de creación
  reciente en Ayacucho.

### 3.7 Cómo hacer viable el simulador: podar la matriz ⭐

El simulador de la Fase 4 necesita el tiempo desde cada punto de demanda **hasta cada
candidato a ascenso** — algo que la matriz de resolutivos no contiene. Son 5 000 × 406 =
**2 030 000 pares**, unos 24 MB que habría que versionar en el repositorio.

| Opción | Veredicto |
|---|---|
| Guardar la matriz completa | 24 MB en git para algo que se usa parcialmente |
| Rutear en vivo al mover el selector | **Prohibido**: el enunciado exige que el dashboard no llame al motor de ruteo |
| Limitar los candidatos a unos pocos | Empobrece el simulador y la elección sería arbitraria |
| **Podar a los pares que podrían mejorar el acceso** | **Elegida** |

- **La poda:** ascender un establecimiento solo beneficia a los puntos para los que quedaría
  **más cerca que su resolutivo actual**. El resto de pares no puede cambiar el resultado, así
  que guardarlos es peso muerto.
- **Resultado: 2 030 000 → 48 803 pares (2.4 %), de 24 MB a 0.5 MB**, sin perder ni un caso:
  el simulador da exactamente los mismos números.
- `verify.py` comprueba la poda explícitamente: *"la poda solo dejó pares que mejoran el
  acceso actual (0 inconsistentes)"*. Si la condición se rompiera, el simulador reportaría
  ganancias inexistentes.

### 3.8 Compilar el informe desde el pipeline ⭐

No había ningún compilador de LaTeX en la máquina, y el enunciado exige **el PDF compilado en
el repositorio**, no solo la fuente.

| Opción | Veredicto |
|---|---|
| MiKTeX o TeX Live | Distribución completa, 200 MB - 1 GB, instalación con privilegios |
| Overleaf | El enunciado lo admite, pero el PDF se generaría fuera del repositorio y a mano |
| **Tectonic** | **Elegida**: un binario de 49 MB que **descarga solo los paquetes que el documento necesita**, sin admin ni cambios al sistema |

- La primera compilación tardó **234 s** porque Tectonic fue trayendo los paquetes; las
  siguientes tardan **6.8 s**.
- **Esto convierte la Fase 5 en una de las innovaciones que el propio enunciado sugiere**:
  *"un paso del pipeline que recompila el PDF de LaTeX con las cifras nuevas cada vez que
  cambian los datos"*. `python run_pipeline.py --phase 5` regenera el informe entero.
- **Ninguna cifra del informe está tecleada a mano.** Las 6 tablas entran con `\input` desde
  `report/tablas/` y las 5 figuras son PDF vectorial exportado por matplotlib. Si cambia un
  departamento en `config.md`, el informe se rehace con los números nuevos y no puede quedar
  desincronizado.
- `verify.py --phase 5` comprueba las 9 secciones obligatorias, que el PDT tenga entre 8 y 12
  páginas, que no queden referencias cruzadas sin resolver (`??`) y que las tablas vengan de
  `report/tablas/` en vez de estar escritas a mano.

### 3.9 Formatos de salida: GeoParquet y GeoPackage

- **GeoParquet** es el formato de trabajo: columnar y comprimido, casi 5× más liviano
  (0.21 MB frente a 0.99 MB en el caso de la oferta).
- **GeoPackage** es el de interoperabilidad: abre en **QGIS** con doble clic, para que un
  evaluador o un funcionario regional inspeccione el dato sin saber Python.
- El enunciado pide uno **u** otro; se generan ambos porque resuelven problemas distintos.

---

## 4. Obstáculos

*Veinte incidencias. Las agrupo por tipo; el orden dentro de cada grupo es cronológico.*

### 4.1 Del entorno

- **geopandas 0.14.3 + fiona ≥1.10 son incompatibles** ⭐ — `AttributeError: module 'fiona'
  has no attribute 'path'`. Las dos se instalan sin conflicto aparente y solo revientan al
  primer uso real, porque `fiona.path` se eliminó en 1.10. *Lección: fijar una versión
  antigua no la aísla; sus dependencias siguen avanzando.* **Solución:** entorno con
  geopandas 1.1.4 y **pyogrio** como motor de I/O.
- **JupyterLab no instalaba** — el venv estaba dentro de OneDrive, en una ruta ya de 109
  caracteres, y con la ruta interna de una extensión se superaban los **260 caracteres** que
  Windows admite por defecto. **Solución:** los entornos virtuales van fuera de OneDrive, en
  `C:\Users\josem\.venvs\`. Esto además evita sincronizar 23 536 archivos de paquetes.
- **Ni Docker ni WSL instalados**, y OSRM los necesita. Ver decisión 3.1.
- **Docker Desktop instalado pero "no encontrado"** — busqué el ejecutable solo en
  `Program Files`; estaba instalado **por usuario**, en `AppData\Local\Programs\DockerDesktop`.
  La pista estaba en la ruta del propio `docker.exe`, que no miré antes de concluir.
  *Lección: preguntarle al sistema dónde está algo (`Get-Command`, el registro de
  desinstalación) en vez de comprobar las rutas que uno espera.*
- **Los tiles de CartoDB ahora exigen API key** — folium emitía un `UserWarning` y el mapa
  interactivo se habría publicado con un fondo que no carga para quien lo abriera.
  **Solución:** mapa base de OpenStreetMap, que no requiere clave.
- **Aclaración útil:** no existe una app llamada "WSL2". WSL es la característica y `2` la
  versión del backend. La prueba está en la columna `VERSION` de `wsl -l -v`. Que la distro
  diga `Stopped` tampoco es problema: WSL arranca bajo demanda.

### 4.2 De acceso a los datos

- **`HTTP Error 418` al descargar de Datos Abiertos** ⭐ — el portal rechaza clientes sin
  `User-Agent` de navegador; el 418 ("I'm a teapot") es una respuesta anti-bot deliberada.
  *Lección: "funciona en el navegador pero no desde Python" casi siempre son cabeceras HTTP.*
  **Solución:** User-Agent como parámetro de `config.md`, no incrustado.
- **SIGMED no es automatizable.** Ver decisión 3.3.

### 4.3 Del contenido de los datos

- **El CSV de RENIPRESS es UTF-8 con BOM** ⭐ — `KeyError: 'INSTITUCION'` pese a que la
  columna se ve en el archivo. Leerlo como latin-1 —el reflejo habitual con datos
  peruanos— renombra la primera columna a `ï»¿INSTITUCION` y llena de mojibake los campos
  acentuados. **Solución:** `utf-8-sig`; el hallazgo se convirtió en la regla de validación
  R6, que además repara residuos (4 hallados, 100 % recuperados). *Lección: el encoding es un
  parámetro de los datos, no una constante del código.*
- **`NORTE` contiene la latitud y `ESTE` la longitud** ⭐ — los nombres invitan al error
  contrario. Verificado contra los rangos reales del archivo antes de fijarlo. **El notebook
  `Geopandas1.ipynb` del material del curso lo tiene al revés**, lo que coloca todos los
  puntos fuera del planeta. *Lección: no confiar en el nombre de una columna; validar contra
  el rango esperado.*
- **8 552 registros con categoría `"0"`** (23.8 %) además de vacíos y variantes de
  espaciado. **Solución:** reglas de normalización explícitas y visibles en el código, como
  exige el enunciado; se conservan `categoria` y `categoria_raw` para poder auditar.
- **WorldPop *constrained* subestima Loreto ~24 %** — solo asigna población donde detecta
  edificación desde satélite, y los asentamientos amazónicos dispersos bajo dosel arbóreo no
  se detectan. Ayacucho (+7 %) y Lambayeque (−5 %) salen bien. **No se "arregla": se
  declara**, y queda el flag `--hi-res-pop` para el producto *unconstrained* de 596 MB.

### 4.4 Errores propios ⭐

*Cuatro bugs míos. **Ninguno lanzó excepción**: el pipeline terminaba con código de salida 0.
Aparecieron al leer el log y mirar las figuras, no al ejecutar. Esa distinción —entre "corrió
sin errores" y "corrió bien"— es en sí un punto para el video.*

- **Se perdía el 85 % de los puntos de demanda** ⭐ — el log decía
  `15418 -> 2272 puntos (0 habitantes descartados)`: dos números que se contradicen. Puse
  `poblacion_minima = 1.0`, que descartaba todo centro poblado sin población en el ráster, y
  el mensaje solo reportaba los habitantes perdidos (correctamente cero), escondiendo que el
  mapa se quedaba sin el 85 % de sus puntos. **Solución:** umbral en 0, bandera
  `tiene_poblacion_raster`, y log que reporta puntos y habitantes por separado. *Lección: un
  filtro que descarta datos debe reportar ambas magnitudes.*
- **Error de unidades: "~0 m"** — usé 111 km/grado y etiqueté el resultado en metros. Lo
  correcto eran 222 m.
- **"432 048 registros evaluados"** cuando RENIPRESS tiene 36 004 — la regla R6 reportaba
  *celdas* (36 004 filas × 12 columnas) donde las demás reportan registros. *Lección: si
  varias filas de una tabla comparten columna, tienen que compartir unidad.*
- **Los mapas salían diminutos** — los establecimientos que R2 y R4 habían marcado por caer
  fuera de su departamento estiraban la extensión de los ejes. **La validación estaba
  funcionando y el gráfico la estaba delatando.** Ahora los ejes se fijan al polígono del
  departamento y el título informa cuántos puntos quedan fuera de cuadro.

### 4.5 De la Fase 2

- **El trayecto de 0 metros que no era un hospital en la puerta** ⭐⭐ — el acceso urbano a pie
  daba en Loreto una mediana de **exactamente 0.0 minutos**. Al mirarlo de cerca: **68 de 390
  puntos urbanos (17.4 %), y 63 de los 113 de Loreto (56 %)**, tenían tiempo 0.0 y distancia
  0.0. No significaba "el establecimiento está en la puerta": **OSRM enganchaba el centro
  poblado y la IPRESS al mismo nodo de la red y no podía distinguirlos.** Es el mismo problema
  de red dispersa del hallazgo 2.1, apareciendo por otra vía y disfrazado de buena noticia.
  **Solución:** bandera `snap_colapsado` para todo trayecto de exactamente 0 m, excluido de
  los estadísticos y reportado aparte. La mediana de Loreto pasó del falso 0.0 a **5.8 min**
  sobre 50 puntos válidos. *Lección: un resultado sospechosamente bueno merece la misma
  desconfianza que uno sospechosamente malo.*
- **`TypeError: Invalid value 'nan' for dtype 'bool'`** — al marcar como "no se sabe" la
  comparación entre modos donde uno de los dos no alcanza nada. En pandas 3.x no se puede
  asignar `pd.NA` a una columna `bool` corriente. **Solución:** usar el dtype nullable
  `boolean`, que sí admite ausentes.
- **`Axes.boxplot() got an unexpected keyword argument 'labels'`** — matplotlib renombró
  `labels` a `tick_labels` en la versión 3.9 y en 3.11 el nombre antiguo ya no existe.
- **El GeoPackage no aceptaba las columnas nullable** — `cannot convert NA to integer`. El
  Parquet principal sí se escribía; fallaba solo la copia para QGIS. **Solución:** mapear los
  booleanos nullable a 1/0 con −1 para los ausentes, valor imposible para un booleano.
- **Los destinos también había que trocearlos** — el análisis a pie compara contra las ~2 100
  IPRESS de cualquier categoría, y los destinos por sí solos ya superaban el
  `--max-table-size` del servidor y la longitud máxima de URL. La API de OSRM es solo GET.
  **Solución:** trocear ambas dimensiones de la matriz, no solo los orígenes.

### 4.6 De la Fase 3

- **"5 distritos sin dato de pobreza" cuando faltaban 37** ⭐ — el cruce usaba 178 de 215
  distritos pero el log solo justificaba 5 ausencias. **Es el mismo error de reporte parcial
  que la incidencia del 85 % de los puntos de demanda**, cometido por segunda vez: los
  distritos salían del cruce por **dos motivos distintos** y solo se contaba uno. Los otros
  32 no tenían **ningún** punto con tiempo interpretable, o sea que la red vial no sirve al
  distrito entero — que no es un hueco de datos sino un hallazgo (ver 2.12). **Solución:**
  desglosar los tres casos (sin pobreza / sin tiempo / ambos) y nombrar el segundo como lo
  que es.
- **`\textbackslash \%` en las tablas LaTeX** — al pasarle a pandas cabeceras ya escritas en
  LaTeX (`(\%)`, `$\rho$`) con `escape=True`, pandas volvía a escapar la barra invertida.
  **Solución:** escapar los **datos** a mano y desactivar el escapado automático, con una
  lista de columnas exentas para las que ya traen sintaxis matemática propia.
- **`p = 0.00`** — `float_format` es único para toda la tabla, así que los p-valores salían
  con la misma precisión que los minutos y un p de 0.00002 se imprimía como cero, que se lee
  como "sin efecto" cuando significa lo contrario. **Solución:** preformatearlos como
  `$<$0.001`, y el mismo truco a la inversa para que el Gini lleve 3 decimales y los minutos
  solo 1.
- **La dispersión acceso × pobreza era ilegible** — los distritos amazónicos llegan a
  5 000 minutos y en escala lineal aplastaban al 95 % de los puntos contra el eje.
  **Solución:** escala logarítmica en el eje Y, con las bandas de 30/60/120 min dibujadas
  como referencia.

### 4.7 De la Fase 4

- **Un `default` que no estaba entre las opciones tumbaba la app entera** ⭐ — el filtro de
  categorías usaba como valor por defecto el whitelist completo de `config.md`
  (`II-1, II-2, II-E, III-1, III-2, III-E`), pero **en Lambayeque, Ayacucho y Loreto no existe
  ningún establecimiento III-2 ni III-E**. Streamlit lanza `StreamlitDefaultNotInOptionsError`
  y la app no llega ni a renderizar. **Solución:** intersectar el default con las categorías
  que existen realmente en el ámbito.
- **Y el modo en que lo encontré importa más que el bug** ⭐⭐ — primero levanté el servidor y
  comprobé que respondía `HTTP 200`. **Eso no probaba nada**: Streamlit solo ejecuta el script
  cuando un navegador conecta por websocket, así que un GET a `/` devuelve el HTML vacío
  aunque el código esté roto. Al usar `streamlit.testing.v1.AppTest`, que **sí** ejecuta el
  script, el fallo apareció de inmediato. *Lección: comprobar que un servicio "responde" no es
  comprobar que funciona.*
- **Siete escenarios de prueba, no uno** — con `AppTest` se ejercitan la carga por defecto, el
  filtrado a un departamento, **la selección vacía** (que el enunciado exige que no rompa), el
  filtro rural, el cambio de umbral, y el simulador con uno y con tres ascensos. Están
  incorporados a `verify.py --phase 4`.
- **El test tenía un hueco que no vi al principio** — buscaba los widgets por índice, y el
  índice que creía del simulador era en realidad el filtro de instituciones: el escenario
  "simulador" nunca llegó a probar el simulador. Se corrigió buscando los widgets **por
  etiqueta**. *Un test que pasa sin ejercitar lo que dice ejercitar es peor que no tenerlo.*
- **`use_container_width` está deprecado** desde el 31-12-2025 en Streamlit; se sustituyó por
  `width="stretch"` en los 6 usos.
- **Calcular centroides sobre un CRS geográfico** para centrar el mapa produce un aviso de
  geopandas en cada llamada. Se sustituyó por el punto medio del *bounding box*, que además
  es exacto.

### 4.8 De la Fase 5

- **`NaN` impreso en el informe** ⭐ — la tabla de brechas críticas mostraba `NaN` en la
  columna de tiempo medio para 16 distritos. **El valor era correcto**: esos distritos tienen
  el 100 % de su población sin acceso vial, así que no hay ningún tiempo que promediar. Pero
  imprimir el nombre interno de pandas en un informe **sugiere un fallo de cálculo cuando en
  realidad es el resultado**. **Solución:** `na_rep="---"` en la exportación LaTeX, más una
  nota en el pie de la tabla explicando qué significa la raya. *Lección: la forma en que se
  presenta un ausente cambia cómo se lee — "NaN" dice "algo se rompió", una raya dice "no
  aplica".*
- **Detectado por el usuario, no por mí.** Yo había verificado que el PDF compilaba sin
  errores, que tenía 12 páginas y que no quedaban referencias sin resolver, pero **no había
  mirado el contenido de las tablas renderizadas**. Se añadieron dos comprobaciones nuevas
  para que no vuelva a pasar: que ninguna tabla imprima `NaN` y que ninguna tenga mojibake.
- **Falso mojibake, por tercera vez** — al revisar la tabla en la terminal aparecía `OCAÃ‘A`
  en vez de `OCAÑA`. No era real: PowerShell 5.1 muestra los archivos UTF-8 sin BOM como si
  fueran ANSI. El `.tex` y el PDF estaban correctos. Es el mismo artefacto de las incidencias
  del manifiesto y del script `.ps1`, y ya van tres veces que despista. **Regla práctica para
  este proyecto: no diagnosticar encoding con `Get-Content`; verificarlo leyendo el archivo
  desde Python.**

### 4.9 De ejecución

- **`ModuleNotFoundError: No module named 'geopandas'`** — el botón ▶ de VS Code usó el
  Python del sistema en vez del entorno. **Dos pistas para el diagnóstico:** no se generó
  ningún log (la falla ocurrió antes de configurar el logging, o sea en los imports), y el
  comando empezaba con la ruta del Python del sistema. *Vale para quien evalúe la tarea: sin
  crear el entorno de `requirements.txt`, el repositorio no corre.*
- **`OSError: [Errno 22]` al sobrescribir una figura** ⭐ — el pipeline abortó en el **último**
  paso tras 30 s de trabajo ya hecho. **La prueba decisiva:** `fase1_ambito.png` se había
  guardado bien *un segundo antes en la misma carpeta*, lo que descartaba permisos y ruta.
  La diferencia: la otra figura estaba abierta en el visor de fotos de Windows, que bloquea
  el archivo. **Solución:** función `intentar()` que protege solo los pasos **prescindibles**
  (figuras y mapa) y deja fallar los esenciales. *Lección: distinguir entre pasos cuyo fallo
  invalida el resultado y pasos cuyo fallo solo cuesta un archivo.*
- **Datos y configuración apuntando a ámbitos distintos** ⭐ — `config.md` decía Loreto pero
  los archivos procesados contenían Ucayali, tras probar el cambio de ámbito y revertir la
  configuración sin regenerar. **Rutear sobre eso habría dado resultados silenciosamente
  equivocados: sin excepción, sin advertencia, con números plausibles.** `verify.py` ya lo
  detectaba, porque cruza los tres datasets contra el ámbito de `config.md`.
- **Un script `.ps1` roto por su propia codificación** ⭐ — cascada de errores de sintaxis
  apuntando a una línea perfectamente válida. El archivo no tenía ningún error: estaba en
  UTF-8 sin BOM con un guion largo `—`, y **PowerShell 5.1 lee los `.ps1` con la página de
  códigos ANSI cuando no llevan BOM**. El error se reportaba en la línea 87 pero la causa
  estaba en la 78. **Solución:** mantener el script en ASCII puro, verificable con
  `([IO.File]::ReadAllBytes($p) | Where-Object { $_ -gt 127 }).Count`. *Es el mismo tipo de
  fallo que el BOM de RENIPRESS, visto desde el otro lado: allí el BOM sobraba, aquí faltaba.*

---

## 5. Cómo funciona el proyecto

### 5.1 Arquitectura: `run_pipeline.py` frente a `src/` ⭐

- La confusión natural es pensar que `src/` duplica lo que hace `run_pipeline.py`. Es **al
  revés**: `run_pipeline.py` casi no tiene lógica propia — son ~1 850 líneas en `src/` contra
  231 de orquestación.
- **La analogía:** `run_pipeline.py` es el índice de un libro; `src/` son los capítulos.
  Dicho de otro modo: `run_pipeline.py` dice **qué pasa y en qué orden**; `src/` dice **cómo
  se hace cada cosa**. Toda la Fase 1 cabe en seis llamadas, y cada una dispara cientos de
  líneas.
- **Por qué separado:** el enunciado lo exige (*"el módulo de ruteo debe ser importable y
  testeable de forma independiente"*); el dashboard de la Fase 4 importará de `src/` sin
  ejecutar el pipeline; y se puede probar por partes, como se hizo con el muestreo.

### 5.2 Un solo botón: el pipeline se ejecuta y se verifica solo ⭐⭐

- **`python run_pipeline.py` sin argumentos hace todo.** En VS Code, abrir el archivo y pulsar
  **▶ Run** basta: no hay que escribir comandos, ni recordar el orden de las fases, ni
  levantar servicios a mano.
- Cuatro cosas ocurren solas:
  1. **Corre todas las fases** en orden (`--phase` vale `all` por defecto).
  2. **Regenera lo que falte** (ver 5.3).
  3. **Arranca los contenedores de OSRM** si están detenidos — no arrancan solos tras
     reiniciar la máquina, y sin ellos la Fase 2 no puede correr.
  4. **Verifica los resultados** al terminar: 41 comprobaciones de la Fase 1 y 26 de la Fase 2.
- **La demostración que vale la pena grabar:** apagar los tres contenedores de OSRM, borrar
  *todas* las salidas, pulsar ▶, y ver esto en **46 segundos**:

  ```
  Modo 'all': se ejecutaran en secuencia las fases 1, 2
  FASE 1 COMPLETA en 0.3 min
    3 perfil(es) de OSRM no responden; intentando arrancarlos...
    OSRM listo: los 3 perfiles responden
  FASE 2 COMPLETA en 0.5 min
  VERIFICACION DE LOS RESULTADOS
    Las 41 verificaciones pasaron
    Las 26 verificaciones pasaron
  TODO CORRECTO: las fases 1, 2 se ejecutaron y verificaron sin errores.
  ```

- **Por qué importa para la nota:** el enunciado exige reproducibilidad y penaliza los
  proyectos que "producen la respuesta correcta mediante scripts ilegibles e
  irreproducibles". Quien evalúe clona el repositorio, pulsa un botón y obtiene todos los
  resultados **más la prueba de que son correctos**.
- **El único requisito de configuración**, y una sola vez: que VS Code use el intérprete del
  entorno. El repositorio trae un `.vscode/settings.json` que ya lo apunta.

> **Guion:** "No hay que saber nada para reproducir esto. Abres el archivo, le das a play, y
> en menos de un minuto tienes todos los resultados y la verificación de que son correctos.
> Si borraste algo, lo reconstruye. Si los servicios estaban apagados, los levanta."

### 5.3 El pipeline se repara solo ⭐

- **Se puede borrar cualquier salida y volver a ejecutar: lo que falte se regenera.** Cada
  fase declara de qué depende y qué archivos produce, y el pipeline resuelve sus insumos como
  un sistema de *build*.
- Demostración: borrar todo `data/processed/` y pedir **solo** la Fase 2 →
  `[WARNING] La Fase 1 se regenera: faltan 3 de sus salidas` → corre la 1, luego la 2, en
  **23.5 segundos**.
- **La regla:** la fase que pides siempre se ejecuta; las de las que depende, solo si sus
  salidas faltan o quedaron desfasadas. Así volver a correr algo ya calculado sigue costando
  segundos y no minutos.
- **Además detecta el ámbito desfasado**, que es un caso que ocurrió de verdad durante el
  desarrollo (obstáculo 4.6): si los datos procesados son de un ámbito distinto al que
  declara `config.md` hoy, la Fase 1 se rehace sola. Sin esa comprobación, rutear sobre datos
  de otro departamento habría dado resultados **silenciosamente equivocados: sin excepción,
  sin advertencia, con números plausibles**.
- **Por qué importa para la nota:** el enunciado valora la reproducibilidad y pide un script
  de regeneración documentado. Quien evalúe clona el repositorio y con `--phase all` obtiene
  todos los resultados, sin tener que saber qué fase producía qué archivo.
- Las fases 4 y 5 nunca entran en `all`, y es deliberado: el dashboard es una app que se queda
  corriendo (`streamlit run app.py`) y el informe es una compilación de LaTeX. No son pasos
  de pipeline.

> **Guion:** "Un pipeline de datos no debería obligarte a recordar el orden. Cada fase declara
> qué necesita y qué produce, así que puedes borrar cualquier resultado, pedir la fase que te
> interese, y el pipeline reconstruye solo lo que falte — en veintitrés segundos."

### 5.4 `config.md` es documentación **y** configuración ejecutable ⭐

- El enunciado exige que todo parámetro viva en `config.md` y que los departamentos se puedan
  cambiar **sin modificar código**.
- El problema: Markdown es para leer, no para ejecutar. La solución típica —un `.md` de
  documentación y un `.yaml` de verdad— crea dos copias que se desincronizan.
- **Lo que se hizo:** `src/config.py` extrae con una expresión regular todos los bloques
  ` ```toml ` del propio Markdown y los parsea con `tomllib` (biblioteca estándar desde
  Python 3.11). **Una sola fuente de verdad: es imposible que la documentación mienta sobre
  la configuración, porque son el mismo archivo.**
- *Frase:* "Cero valores incrustados. Ningún departamento, umbral, categoría ni URL está
  escrito dentro de un `.py`."

### 5.5 Demostración en vivo: cambiar un departamento ⭐

- **Son exactamente dos ediciones** en la sección 1 de `config.md`: el nombre en la lista
  `departamentos`, y su etiqueta en `[ambito.region_natural]` (esta se suele olvidar; sin
  ella el título de la figura muestra `?`).
- Luego `python run_pipeline.py --phase 1` y `python verify.py --phase 1`. **Tarda ~25 s**
  porque las descargas están en caché.
- **Funciona porque los datos crudos son nacionales** — 36 004 establecimientos, 136 587
  centros poblados, 1 891 distritos: el recorte al ámbito ocurre en memoria, después de
  validar.
- **Cuidado:** nombres en MAYÚSCULAS y sin tildes (`SAN MARTIN`, `APURIMAC`); respetar uno de
  costa, uno de sierra, uno de selva; y ensayarlo antes de grabar.

### 5.6 Cómo se lee `fase1_calidad.png` ⭐

- Barras horizontales: **rojo = registros marcados**, **verde = recuperados** (subconjunto,
  dibujado encima desde cero).
- **El orden del eje Y no es numérico: es el orden de ejecución** (R6, R5, R1, R3, R2, R4).
  R6 va primero porque todas las demás leen campos de texto.
- **El punto metodológico que vale oro:** R3 (lat/lon invertidas) va **antes** que R2 (fuera
  del bounding box) a propósito. Un punto invertido cae fuera del bounding box; evaluando R2
  primero se descartaría como inválido cuando era **perfectamente recuperable**.
- **Tres mensajes:** (1) la barra roja gigante —R1 = 13 176— es el hallazgo; (2) que R3 y R5
  den **cero es un resultado, no un hueco**: el registro es consistente en lat/lon y
  `COD_IPRESS` sí es clave única; (3) el verde es la diferencia entre aprobar y destacar,
  porque el enunciado premia corregir lo recuperable documentando la tasa.
- **El cierre: en este gráfico nada se borró.** Ni una fila. Todo lo marcado sigue en el
  dataset con su bandera, solo se excluye del cálculo de más cercano.

### 5.7 Por qué hubo que instalar tanto ⭐⭐

| Capa | Qué es | Peso |
|---|---|---:|
| Entorno Python | 77 paquetes, 23 536 archivos | 842 MB |
| WSL2 + Docker Desktop | Infraestructura para correr Linux | ~2-4 GB |
| Imagen de OSRM | El motor de ruteo | 388 MB |
| Grafo compilado | Red vial del Perú procesada | 2 103 MB |
| Datos | RENIPRESS, CCPP, distritos, WorldPop, OSM | 311 MB |

- **Los 77 paquetes no son exceso:** no se instaló "geopandas", se instalaron **envoltorios
  de Python sobre librerías C/C++ que llevan décadas existiendo**, las mismas en las que se
  apoyan QGIS, ArcGIS y PostGIS — **GEOS** (geometría, vía `shapely`), **PROJ**
  (transformación entre ~10 000 sistemas de coordenadas, vía `pyproj`) y **GDAL/OGR** (lectura
  de ~100 formatos, vía `pyogrio` y `rasterio`). `geopandas` no hace ese trabajo: lo orquesta.
- **La cadena de instalación es una sola decisión, no tres** ⭐:
  `Necesito OSRM → solo existe para Linux → para correr Linux en Windows necesito Docker →
  Docker en Windows necesita WSL2`. Leído al revés, esa es la secuencia de instalación.
  **No existe versión de OSRM para Windows.**
- **Los 2.1 GB del grafo no se instalaron, se generaron:** OSRM procesó los 244 MB del
  extracto de OpenStreetMap —extrayendo vías y aplicando el perfil de automóvil con sus
  velocidades, sentidos y restricciones de giro— hasta una estructura que responde en
  milisegundos. El archivo más pesado, `peru-latest.osrm.geometry` (441 MB), es la geometría
  de **todas las carreteras del Perú**.
- **Compilar los tres grafos costó 7.5 minutos, no una hora.** Medido sobre las marcas de
  tiempo de los archivos en `C:\osrm-hw2\`: `car` 2.2 min, `foot` 2.5 min, `bike` 2.8 min.
  Es la cadena completa `osrm-extract` → `osrm-partition` → `osrm-customize` para los 244 MB
  del extracto del Perú. Si sale la pregunta *"¿cuánto tardó montar esto?"*, ese es el número.
- **Cuidado con la estimación que imprime el script.** `scripts/osrm.ps1` anunciaba
  "la etapa lenta: 10-25 min" — una cifra escrita a mano, copiada de la documentación general
  de OSRM (que piensa en extractos del tamaño de un continente), no medida sobre el Perú.
  Estuvo en el repositorio dando una impresión equivocada hasta que se contrastó contra las
  marcas de tiempo reales. **Punto de método que vale contar:** cualquier número del proyecto
  debe poder rastrearse hasta una medición; los que no, son texto decorativo y engañan igual
  que un dato mal calculado.
- **Nada de esto es específico de esta tarea:** es la infraestructura estándar de cualquier
  análisis serio de accesibilidad geoespacial. Lo propio del proyecto son las ~1 850 líneas
  de `src/`.

### 5.8 Qué son exactamente las 116 verificaciones ⭐⭐

Pregunta que va a salir: *"¿41, 26 y 49 de qué?"*

- Son **aserciones individuales sobre los archivos que quedaron en disco**. Cada línea `PASA`
  cuenta una. Los números no son redondos porque cada comprobación se añadió cuando hizo
  falta, no para llegar a una cifra.

  | | Fase 1 | Fase 2 | Fase 3 |
  |---|---:|---:|---:|
  | Archivos existen y no están vacíos | 9 | 7 | 19 |
  | CRS, ámbito, claves, integridad referencial | 10 | 4 | — |
  | Regla de capacidad resolutiva y flags de validación | 7 | 5 | — |
  | Dataset de demanda y reporte de calidad | 9 | — | — |
  | Trazabilidad de descargas (SHA-256, fechas) | 6 | — | — |
  | Matriz completa, fuera de red, expansión poblacional | — | 10 | — |
  | Bandas, agregación, desigualdad, brechas, cruce | — | — | 24 |
  | Tablas LaTeX bien formadas | — | — | 6 |
  | **TOTAL** | **41** | **26** | **49** |

- **`verify.py` NO es un test del código.** No importa las funciones del pipeline ni las
  ejecuta: **vuelve a abrir los archivos de disco** y exige propiedades que no pueden ser
  falsas si todo salió bien. Hay cuatro clases:

  **Matemáticas** — `el Gini esta en [0,1]` · `las bandas suman 100%` ·
  `la curva de Lorenz es monotona y va de (0,0) a (100,100)` ·
  `la matriz es completa: 220000 filas == 5000 origenes x 44 destinos`

  **Lógicas** — `apto_para_ruteo implica coord_valida` ·
  `ningun punto inalcanzable tiene tiempo inventado` ·
  `fuera_de_red coincide con snap_m > 2000 m`

  **Consistencia entre archivos** — `la poblacion de los distritos suma la del departamento` ·
  `todo ubigeo de demanda existe en la capa de distritos` ·
  `el establecimiento mas cercano siempre es un resolutivo apto`

  **Cumplimiento del enunciado** — verifican el entregable contra la rúbrica, no contra el
  código: `las 6 reglas obligatorias estan reportadas` ·
  `toda regla trae una justificacion escrita` ·
  `cada fila declara la naturaleza de la relacion` ·
  `la muestra respeta el tope del enunciado (5000 <= 5000)`

- **La comprobación más valiosa** es esta, de la Fase 2:
  `el tiempo del consolidado es exactamente el minimo de la matriz`.
  **Recalcula la respuesta por un camino distinto y la compara.** El pipeline obtiene el
  tiempo al más cercano con `groupby().idxmin()`; el verificador lo vuelve a derivar desde
  los 220 000 pares de la matriz por su cuenta y exige que coincidan al cuarto decimal. Si
  hubiera un error en esa lógica, esto lo caza.

> **Guion:** "Verificar no es correr y ver si peta. El pipeline puede terminar con código de
> salida cero y estar mal — de hecho me pasó cuatro veces, y ninguna lanzó excepción. Estas
> 116 comprobaciones re-leen los archivos y exigen propiedades que no pueden ser falsas si el
> cálculo está bien: que las bandas sumen 100%, que el Gini esté entre 0 y 1, que la
> población de los distritos sume la del departamento. Y algunas verifican el entregable
> contra el enunciado, no contra el código."

Conecta directamente con la sección 4.4, la de mis propios errores.

### 5.9 Detalles menores que pueden surgir

- **Los `.gitkeep`** son archivos vacíos que existen solo para que Git preserve una carpeta
  vacía, porque **Git versiona archivos, no directorios**. Combinados con `.gitignore`
  (`data/raw/*` + `!data/raw/.gitkeep`), mantienen la estructura sin subir 311 MB de
  descargas públicas.
- **`data/processed/` tiene seis archivos**: tres datasets (oferta 2 838×24, demanda
  15 418×16, distritos 215×11) duplicados en `.parquet` y `.gpkg`. Ver decisión 3.6.
- **Hay tres Pythons en la máquina** y solo uno sirve: el del sistema (sin librerías
  geoespaciales), `geopandas-class` (los notebooks de clase) y **`hw2-geo`** (este proyecto).
  Causa de la incidencia del intérprete equivocado.
- **Trazabilidad:** `data/raw/_manifest.json` guarda URL efectiva, fecha UTC, tamaño y
  **SHA-256** de cada descarga, para poder citar en el informe la versión exacta de los datos.

---

## 6. Innovación (puntos extra)

*El enunciado ofrece bonificación por mejoras que vayan más allá del mínimo. Estas son las
que el proyecto trae, con la referencia a la sección donde se explican.*

| Innovación | Qué es | Dónde |
|---|---|---|
| **Regeneración automática del informe** ⭐ | Sugerida literalmente por el enunciado. `--phase 5` recompila el PDF con las cifras vigentes; ninguna está tecleada a mano | 3.8 |
| **Comparación temporal del registro** ⭐ | Dos cortes de RENIPRESS (abril y agosto 2026) para medir la rotación real: 46 altas, 17 cambios de categoría, +3 resolutivos netos en 4 meses | 2.4 |
| **Análisis de sensibilidad del umbral** ⭐⭐ | El hallazgo principal se prueba contra cinco umbrales (500 m a 10 km) para demostrar que no depende de un número elegido a dedo | 2.1 |
| **Verificación automática con 179 comprobaciones** ⭐⭐ | Un verificador independiente que re-lee los archivos y exige invariantes matemáticas, lógicas, de consistencia entre archivos y de cumplimiento del enunciado | 5.8 |
| **Pipeline auto-suficiente de un solo botón** ⭐⭐ | Se puede borrar cualquier salida y volver a ejecutar; resuelve dependencias, levanta OSRM y se verifica solo | 5.2, 5.3 |
| **Imputación de población con ráster** ⭐ | WorldPop repartido al vecino más cercano dentro del distrito, conservando el total exacto, en lugar de repartir la población distrital en partes iguales | 3.4 |
| **Detección de trayectos degenerados** ⭐ | Bandera `snap_colapsado` para los pares con 0 m de recorrido, que son artefactos de red dispersa disfrazados de buen resultado | 4.5 |
| **Trazabilidad criptográfica** | Manifiesto con SHA-256 y fecha UTC de cada descarga, para poder citar la versión exacta de los datos | 5.9 |
| **Poda de la matriz del simulador** ⭐ | 2 030 000 → 48 803 pares (de 24 MB a 0.5 MB) sin perder ni un caso | 3.7 |

Pendientes que el enunciado también menciona y que **no** se implementaron: 2SFCA (modelar la
capacidad de cada establecimiento frente a la demanda), optimización formal de localización,
cuantificación de incertidumbre por bootstrap, corrida a escala nacional e isócronas.

---

## 7. Limitaciones declaradas

*Van a la sección de limitaciones del informe, que se califica de forma independiente.*

- **36.6 % del registro nacional no tiene coordenadas** (13 176 de 36 004). Sesga la oferta a
  la baja: hay más establecimientos de los que el análisis puede ver.
- **WorldPop subestima la población de Loreto ~24 %** por el sesgo del producto *constrained*
  en zonas de asentamiento disperso.
- **1 369 conflictos entre coordenada y UBIGEO** sin resolver. No hay información para
  decidir cuál de los dos está mal; se retienen etiquetados en vez de sobrescribir uno con el
  otro y fabricar una precisión inexistente.
- **La población se asigna a los centros poblados por proximidad euclidiana**, no por red
  vial. En valles encajonados y en la selva, la población más cercana en línea recta no
  siempre gravita hacia ese centro poblado.
- **El muestreo no captura la varianza dentro del distrito.** Si un distrito tiene dos
  centros poblados con accesos muy distintos y se muestrea uno, el promedio distrital hereda
  su valor.
- **El registro rota mes a mes**, así que el resultado tiene fecha de caducidad.
- **La red vial de OSM tiene sesgo de cobertura rural**: lo que no está mapeado no existe
  para el ruteo, y eso afecta desproporcionadamente a las zonas que el estudio quiere medir.
