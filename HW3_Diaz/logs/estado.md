# Estado del trabajo

Última actualización: **2026-09-20**

---

## Resumen

El proyecto está **completo y verificado de punta a punta**. `python run_all.py` corre
las dos tareas sin fallos en **3.8 minutos** por unos **$0.002 USD por corrida**, y las
dos aplicaciones Streamlit arrancan y responden.

> `logs/costos.csv` **acumula** todas las corridas, no se reinicia. Ahora mismo lleva
> $0.004915 de las pruebas de desarrollo. Si quieres enseñar en el video el costo de una
> sola corrida limpia, borra ese archivo antes y vuelve a ejecutar; si prefieres enseñar
> el gasto total del proyecto, déjalo como está — las dos lecturas son defendibles
> mientras digas cuál estás mostrando.

Lo que queda es tuyo: **grabar el video** y **subir el repositorio**.

---

## Qué está hecho

### Tarea 1 — RAG Normativo (6.0 puntos)

| Fase | Estado | Evidencia |
|---|---|---|
| 1 · Fuentes, extracción, limpieza | Hecho | `data/processed/source_check.csv`, `extraccion_calidad.csv`, `limpieza_antes_despues.md` |
| 2 · Chunking, embeddings, índice | Hecho | 511 fragmentos · `fragmentos_resumen.csv` · barrido de 3 configuraciones |
| 3 · Motor, umbral, versiones, alcance | Hecho | Dos filtros verificados con llamadas reales |
| 4 · Evaluación y comparación | Hecho | 25 preguntas · barrido de 8 umbrales · BM25 |
| 5 · Interfaz Streamlit | Hecho | Arranca y responde HTTP 200 |

### Tarea 2 — Radar (6.0 puntos)

| Fase | Estado | Evidencia |
|---|---|---|
| 1 · Adquisición | Hecho | 3 meses · 20,422 procesos · 5 peticiones · sha verificado |
| 2 · Validación y territorio | Hecho | 7 reglas · cascada de 4 pasos · 100% localizados |
| 3 · RAG híbrido | Hecho | Recall@1 0.9167 · Recall@3 1.00 |
| 4 · Dashboard | Hecho | Las 6 vistas obligatorias · mapa con 25/25 polígonos casando |
| 5 · Indicador de riesgo | Hecho | 13.11% postor único · top 10 compradores |

### Innovaciones

| # | Innovación | Estado |
|---|---|---|
| 1 | BM25 frente a embeddings | Hecho y medido |
| 2 | Enlace entre las dos tareas | Hecho (botón en el dashboard) |
| 3 | Segunda señal de alerta (plazo corto) | Hecho · 5.88% vs 1.27% |
| 4 | GitHub Actions con umbral de Recall@3 | Escrito, **sin probar en GitHub** |

---

## Qué falta

### Obligatorio

1. **Grabar el video** (máximo 12 minutos). El guion está en
   `guion_video_HW3_Diaz.docx`, en la raíz.
   - **Regla crítica:** los pipelines de las dos tareas se explican **antes** de mostrar
     una sola línea de código. Si el primer contenido técnico es código, ese criterio
     vale **cero** y son 2.0 de 8.0 puntos.
   - Los diagramas para compartir pantalla están en `docs/pipeline.md`.

2. **Crear el repositorio público en GitHub** y registrarlo en la hoja de cálculo que
   indica el enunciado.

3. **Enlazar el video en el README**, en la sección que corresponda.

### Recomendado

4. **Commits distribuidos en el tiempo.** El enunciado avisa: *"A repository with all its
   history on the last day will be reviewed with that in mind."* Conviene repartir en
   varios commits temáticos (fuentes → limpieza → índice → evaluación → tarea 2 →
   dashboard → documentación) en vez de uno solo.

5. **Probar el workflow de GitHub Actions** con un push, para comprobar que pasa en
   ubuntu-latest. Localmente no se puede verificar del todo.

6. **Rellenar la fila API de la comparación de embeddings.** Requiere `OPENAI_API_KEY`
   en `.env`. Sin ella el pipeline corre igual y marca esa fila como no ejecutada. El
   coste sería de fracciones de centavo.

---

## Cómo retomar

```powershell
# Activar el entorno
& "$env:USERPROFILE\.venvs\hw3-rag\Scripts\Activate.ps1"
cd C:\Users\josem\OneDrive\Documentos\GitHub\personal\HW3_Diaz

# Comprobar que todo sigue bien (es reanudable: tarda segundos la segunda vez)
python run_all.py

# Ver las aplicaciones
cd tarea1_rag_normativo ; streamlit run app.py
cd tarea2_radar         ; streamlit run app.py
```

El entorno virtual está en `C:\Users\josem\.venvs\hw3-rag`, **fuera de OneDrive** a
propósito: dentro chocaría con el límite de 260 caracteres de Windows y haría que OneDrive
sincronizara miles de archivos.

---

## Riesgos conocidos antes de grabar

| Riesgo | Mitigación |
|---|---|
| La clave de DeepSeek es del profesor y la comparte todo el salón | Puede agotarse el saldo o toparse con límites justo al grabar. El sistema maneja el error de API como error explícito, así que se puede enseñar incluso caído — pero conviene probar una consulta antes de empezar |
| El modelo de embeddings se descarga de HuggingFace | Ya está en caché local (`~/.cache/huggingface`). No hará falta red para eso |
| Los polígonos del mapa se descargan al abrir la pestaña | Ya están en `tarea2_radar/data/raw/departamentos.geojson`. Verificado: 25/25 departamentos casan |
| El portal de OECE podría caerse | Los tres ZIP ya están en `data/raw/`. El pipeline no vuelve a descargarlos |

---

## Números que conviene tener a mano en cámara

| | |
|---|---:|
| Fragmentos normativos indexados | 511 |
| Procesos de contratación indexados | 20,422 |
| Peticiones HTTP para bajar 20,422 procesos | 5 |
| Recall@3 Tarea 1 / Tarea 2 | 0.85 / 1.00 |
| Abstenciones incorrectas | 0 |
| Similitud del ceviche | 0.7934 |
| Similitud de la pregunta de Reglamento | 0.8869 |
| Media de las preguntas válidas | 0.8809 |
| Departamento en texto vs como filtro | 50% vs 100% |
| Postor único | 13.11% |
| Plazo corto vs normal (postor único) | 5.88% vs 1.27% |
| Costo de una consulta | ~$0.00034 |
| Costo de la corrida completa | $0.001938 |
