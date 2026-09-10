# Estado del proyecto y siguientes pasos

Instantánea de dónde quedó el trabajo, para retomar sin depender del historial del chat.
**Actualizado: 8 de septiembre de 2026. Las cinco fases completas.**

## Los dos documentos de esta carpeta

- **`material_video.md`** — todo lo que se puede comentar en la presentación, en un solo
  lugar: hallazgos, decisiones técnicas, obstáculos, explicaciones del proyecto y
  limitaciones. Se va escribiendo **mientras** se trabaja, no al final, porque el video se
  califica sobre la capacidad de explicar y defender lo hecho. Las entradas marcadas con ⭐
  son las que mejor funcionan contadas en cámara.
- **`estado.md`** (este archivo) — dónde quedó el trabajo y qué sigue.

También hay un archivo `fase*_.log` por cada corrida del pipeline, como evidencia de
ejecución.

---

## Antes de nada: levantar OSRM

**Los contenedores no arrancan solos tras reiniciar la máquina.** Los grafos ya están
compilados, así que esto es instantáneo:

```powershell
cd "C:\Users\josem\OneDrive\Documentos\GitHub\personal\HW2_Diaz"
.\scripts\osrm.ps1 serve all
.\scripts\osrm.ps1 status     # los tres deben decir: corriendo | SI | compilado
```

---

## Fase 1 — COMPLETA y verificada

- Ámbito: **Lambayeque** (costa), **Ayacucho** (sierra), **Loreto** (selva)
- 2 838 IPRESS · **48 resolutivas** · 44 aptas para ruteo
- 15 418 centros poblados · 2 732 389 habitantes · 215 distritos
- `python verify.py --phase 1` → **41/41 verificaciones en verde**

## Fase 2 — COMPLETA y verificada

- Motor: **OSRM en Docker**, tres perfiles compilados y sirviendo (`car` 5000, `foot` 5001,
  `bike` 5002). Grafos en `C:\osrm-hw2\`, ~2.1 GB por perfil.
- Muestra: **5 000 puntos**, 215/215 distritos, población expandida con desvío 0.000000 %
- **Matriz completa 5 000 × 44 = 220 000 pares por modo**, versionada en
  `data/processed/matriz_car.parquet` para que el dashboard de la Fase 4 corra sin OSRM
- Tiempos medianos en auto (solo puntos servidos por la red): Lambayeque 28.3 min ·
  Ayacucho 60.2 min · Loreto 47.3 min (con p90 de 2 204 min)
- `python verify.py --phase 2` → **26/26 verificaciones en verde**

### Salidas de la Fase 2

| Archivo | Contenido |
|---|---|
| `data/processed/acceso_puntos.parquet` | Un registro por punto de demanda, con tiempo en los 3 modos |
| `data/processed/matriz_car.parquet` | Matriz completa origen × resolutiva |
| `data/outputs/resumen_fase2.csv` | Tiempos por departamento |
| `data/outputs/comparacion_modos.csv` | Auto vs pie vs bici |
| `data/outputs/acceso_urbano_pie.csv` | Urbanos a pie, cualquier categoría |
| `data/outputs/snapping_diagnostico.csv` | Enganche a la red |
| `data/outputs/sensibilidad_umbral_snap.csv` | Robustez del umbral de 2 km |
| `report/figures/fase2_{acceso,snapping,modos}.png` | Tres figuras |

---

## Fase 3 — COMPLETA y verificada

- **Bandas de cobertura**: 72.2 % de la población a ≤60 min de un resolutivo · **12.2 % sin
  acceso vial**
- **Agregación ponderada** a distrito (215), provincia (22) y departamento (3)
- **Brechas críticas**: top 20 distritos, ordenados por población sin acceso y tiempo medio
- **Desigualdad**: Gini ponderado (Lambayeque 0.633 · Ayacucho 0.639 · Loreto 0.864) y curva
  de Lorenz
- **Urbano/rural**: la brecha es 1.8× en costa y sierra, **7.1× en Loreto**
- **Cruce con pobreza distrital**: correlación fortísima en Lambayeque (*r* = 0.80),
  inexistente en Loreto (*p* = 0.28); 62 distritos en el cuadrante de doble carga
- **6 tablas LaTeX** en `report/tablas/`, listas para `\input{}` en el informe
- `python verify.py --phase 3` → **49/49 verificaciones en verde**

### Segunda dimensión: de dónde salió

`data/external/pobreza_distrital.csv`, copiado del material del curso y **versionado en el
repositorio** para que sea autosuficiente. Se usa solo `POVERTY_RATE`: `PBI_PC` e `IDH` traen
un único valor por departamento repetido en cada distrito, así que no aportan variación
distrital real.

---

## Fase 4 — COMPLETA y verificada: dashboard Streamlit

`app.py` en la raíz, lanzado con `streamlit run app.py`. **No entra en `--phase all`**: es una
app que se queda corriendo, no un paso de pipeline.

`python verify.py --phase 4` -> **25/25 verificaciones en verde**, incluida la ejecucion
real de la app con `streamlit.testing.v1.AppTest` en siete escenarios.

Las siete vistas que exige el enunciado, todas implementadas:

1. **Cabecera de KPIs** — población cubierta, población a más de 60 min, peor distrito,
   mediana de acceso. Debe reaccionar a los filtros.
2. **Mapa coroplético** — distritos coloreados por tiempo medio ponderado, con leyenda y
   tooltips.
3. **Capa de establecimientos** — resolutivos y no resolutivos como puntos, conmutables y
   filtrables por categoría e institución (MINSA, EsSalud, privado).
4. **Vista de distribución** — histograma o ECDF del tiempo de acceso, partido por
   departamento o urbano/rural.
5. **Tabla ordenable** de los peores distritos, con descarga en CSV.
6. **Simulador de escenarios** — el usuario "asciende" uno o varios establecimientos I-3/I-4 a
   resolutivos y el dashboard recalcula la cobertura **usando la matriz precomputada**,
   mostrando la ganancia marginal de población.
7. **Panel de calidad de datos** — los conteos de validación de la Fase 1.

Requisitos técnicos: **el dashboard solo lee archivos precomputados**, sin llamadas a OSRM ni
reconstrucción de grafos; `@st.cache_data` para la carga; filtros en la barra lateral por
departamento, provincia, categoría, institución y umbral de tiempo; y no debe romperse con
una selección vacía.

**Todo lo que necesita ya está en disco**: `matriz_car.parquet` (220 000 pares) para el
simulador, `acceso_puntos.parquet`, las agregaciones de la Fase 3 y `oferta_salud.parquet`
con las categorías I-3/I-4 candidatas a ascenso.

## Fase 5 — COMPLETA y verificada: informe LaTeX

`report/main.tex` -> `report/main.pdf`, **12 páginas**, con las 9 secciones obligatorias.
Compilado con **Tectonic** desde el propio pipeline (`--phase 5`), en 7 segundos.

**Ninguna cifra está tecleada a mano**: 6 tablas con `\input` desde `report/tablas/` y 5
figuras en PDF vectorial. `python verify.py --phase 5` -> **34/34 verificaciones en verde**.

---

## Cómo retomar la conversación con Claude

La transcripción está ligada a la carpeta `GitHub`, **no** a `HW2_Diaz`:

```powershell
cd "C:\Users\josem\OneDrive\Documentos\GitHub"
claude --continue
```

---

## Pendiente comprometido

Al terminar todas las fases: **documento guion para el video**, construido a partir del
contenido de `logs/material_video.md`.
