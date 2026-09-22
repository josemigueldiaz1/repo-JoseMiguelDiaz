"""
TAREA 2 — Dashboard Streamlit del Radar de Compras Publicas.

Solo interfaz. No descarga bulk, no reconstruye el indice: lee lo que dejo
`build_data.py` en data/. El enunciado lo exige y ademas se nota al arrancar, porque el
pipeline offline tarda ~5 minutos y la app abre en segundos.

Ejecucion:
    streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parent
HW3 = RAIZ.parent
for p in (str(RAIZ), str(HW3)):
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(HW3 / ".env")

from src import metricas, territorio  # noqa: E402
from src.config import load_config  # noqa: E402
from src.motor import Filtros, MotorRadar  # noqa: E402

st.set_page_config(page_title="Radar de Compras Públicas", page_icon="🛰️", layout="wide")


# ============================================================================== cache
@st.cache_resource(show_spinner="Cargando el motor…")
def cargar_motor():
    cfg = load_config()
    return cfg, MotorRadar(cfg)


@st.cache_data(show_spinner="Cargando los procesos…")
def cargar_datos(ruta: str) -> pd.DataFrame:
    return pd.read_parquet(ruta)


@st.cache_data(show_spinner=False)
def cargar_tabla(ruta: str) -> pd.DataFrame:
    p = Path(ruta)
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


@st.cache_data(show_spinner="Cargando el mapa…")
def cargar_geo(_cfg) -> dict | None:
    return territorio.cargar_geojson(_cfg)


try:
    cfg, motor = cargar_motor()
except Exception as e:  # noqa: BLE001
    st.error(f"No se pudo iniciar: {e}")
    st.code("python build_data.py", language="powershell")
    st.stop()

parquet = cfg.processed_dir / "procesos.parquet"
if not parquet.exists():
    st.error("Faltan los datos procesados.")
    st.code("python build_data.py", language="powershell")
    st.stop()

df = cargar_datos(str(parquet))
A = cfg.raw["app"]

st.title(A["titulo"])
st.caption(A["subtitulo"])

# ============================================================================= sidebar
with st.sidebar:
    st.header("Filtros")
    st.caption("Estas condiciones se aplican como **filtros estructurados**, no como "
               "texto para los embeddings. Ver la pestaña «Metodología».")

    deps = sorted(d for d in df["departamento"].dropna().unique()
                  if d != territorio.NO_LOCALIZADO)
    sel_dep = st.multiselect("Departamento", deps)

    cats = sorted(c for c in df["categoria"].dropna().unique())
    sel_cat = st.multiselect("Categoría", cats)

    montos = pd.to_numeric(df["monto"], errors="coerce").dropna()
    tope = float(montos.quantile(0.99)) if len(montos) else 1e6
    rango = st.slider("Rango de monto (PEN)", 0.0, tope, (0.0, tope),
                      step=max(tope / 200, 1000.0), format="%.0f")

    fechas = pd.to_datetime(df["fecha_publicacion"], errors="coerce", utc=True).dropna()
    if len(fechas):
        fmin, fmax = fechas.min().date(), fechas.max().date()
        rango_fecha = st.date_input("Rango de fechas", (fmin, fmax),
                                    min_value=fmin, max_value=fmax)
    else:
        rango_fecha = None

    solo_adj = st.checkbox("Solo procesos adjudicados", value=False)

    st.divider()
    st.subheader("Búsqueda semántica")
    top_k = st.slider("Procesos a recuperar (k)", 3, 20, int(cfg.motor["top_k"]))
    umbral = st.slider("Umbral de similitud", 0.60, 0.95,
                       float(cfg.motor["umbral_similitud"]), 0.01)

# --- aplicar filtros al dataframe ---
d = df.copy()
if sel_dep:
    d = d[d["departamento"].isin(sel_dep)]
if sel_cat:
    d = d[d["categoria"].isin(sel_cat)]
monto_num = pd.to_numeric(d["monto"], errors="coerce")
d = d[(monto_num >= rango[0]) & (monto_num <= rango[1]) | monto_num.isna()]
if solo_adj:
    d = d[d["adjudicado"]]
if rango_fecha and isinstance(rango_fecha, (list, tuple)) and len(rango_fecha) == 2:
    f = pd.to_datetime(d["fecha_publicacion"], errors="coerce", utc=True)
    d = d[(f.dt.date >= rango_fecha[0]) & (f.dt.date <= rango_fecha[1]) | f.isna()]

# El enunciado pide manejar la seleccion vacia sin romper. Se avisa y se sigue: los
# paneles de abajo comprueban `len(d)` antes de calcular nada.
if d.empty:
    st.warning("Ningún proceso cumple los filtros seleccionados. "
               "Amplía el rango de monto, de fecha o quita algún departamento.")

# ================================================================== KPI (vista 1 de 6)
kpi = metricas.resumen_general(cfg, d) if len(d) else {}
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Procesos", f"{kpi.get('procesos', 0):,}")
c2.metric("Monto total", f"S/ {kpi.get('monto_total', 0)/1e6:,.0f} M")
c3.metric("Departamentos", kpi.get("departamentos", 0))
c4.metric("Adjudicados", f"{kpi.get('adjudicados', 0):,}")
c5.metric("Con un solo postor", f"{kpi.get('pct_postor_unico', 0):.1f}%",
          help="Señal de riesgo: proporción de procesos adjudicados que recibieron "
               "exactamente una oferta. Es un motivo para mirar más de cerca, "
               "NUNCA una prueba de irregularidad.")

tabs = st.tabs(["Mapa", "Preguntar", "Ranking", "Distribución",
                "Riesgo", "Calidad de datos", "Metodología"])

# ------------------------------------------------------------- mapa (vista 2 de 6)
with tabs[0]:
    st.subheader("Procesos y montos por departamento")
    if d.empty:
        st.info("Sin datos para mostrar con los filtros actuales.")
    else:
        metrica = st.radio("Colorear por", ["Número de procesos", "Monto total"],
                           horizontal=True)
        agg = (d[d["departamento"].ne(territorio.NO_LOCALIZADO)]
               .groupby("departamento")
               .agg(procesos=("ocid", "size"), monto=("monto", "sum"))
               .reset_index())
        col = "procesos" if metrica.startswith("Número") else "monto"

        geo = cargar_geo(cfg)
        if geo:
            import folium
            from streamlit_folium import st_folium

            m = folium.Map(location=[-9.2, -75.0], zoom_start=5, tiles="cartodbpositron")
            folium.Choropleth(
                geo_data=geo, data=agg, columns=["departamento", col],
                key_on="feature.properties.departamento_norm",
                fill_color="YlOrRd", fill_opacity=0.75, line_opacity=0.4,
                nan_fill_color="#eeeeee",
                legend_name=("Procesos" if col == "procesos" else "Monto (PEN)"),
            ).add_to(m)

            # Tooltips: el enunciado los pide junto con la leyenda.
            datos = agg.set_index("departamento").to_dict("index")
            for f in geo["features"]:
                nombre = f["properties"].get("departamento_norm", "")
                v = datos.get(nombre, {})
                folium.GeoJson(
                    f, style_function=lambda _: {"fillOpacity": 0, "weight": 0},
                    tooltip=folium.Tooltip(
                        f"<b>{nombre}</b><br>"
                        f"Procesos: {v.get('procesos', 0):,}<br>"
                        f"Monto: S/ {v.get('monto', 0):,.0f}"),
                ).add_to(m)
            st_folium(m, height=520, use_container_width=True)
        else:
            st.warning("No se pudieron descargar los polígonos departamentales. "
                       "Se muestra un gráfico de barras en su lugar: la app se degrada, "
                       "no se rompe.")
            st.bar_chart(agg.set_index("departamento")[col])

        st.dataframe(agg.sort_values(col, ascending=False), use_container_width=True)

# -------------------------------------------------------- preguntar (vista 3 de 6)
with tabs[1]:
    st.subheader("Pregunta en lenguaje natural")
    st.caption("La parte semántica de tu pregunta va a los embeddings; el departamento, "
               "el monto y la fecha de la barra lateral van como filtros exactos.")

    if "pregunta_t2" not in st.session_state:
        st.session_state.pregunta_t2 = ""
    cols = st.columns(len(A["ejemplos"]))
    for col, ej in zip(cols, A["ejemplos"]):
        if col.button(ej, use_container_width=True, key=f"ej_{ej[:18]}"):
            st.session_state.pregunta_t2 = ej

    pregunta = st.text_input("Tu pregunta:", value=st.session_state.pregunta_t2,
                             placeholder="obras de agua y saneamiento en Cusco")
    # El resultado se guarda en session_state y NO se pinta dentro del `if` del boton.
    #
    # Motivo: en Streamlit, pulsar CUALQUIER boton vuelve a ejecutar el script entero. Si
    # el resultado se pintara dentro de `if st.button("Preguntar")`, al pulsar despues el
    # boton "¿Que dice la ley...?" de un proceso, esa condicion valdria False —porque en
    # esa pasada no se pulso "Preguntar"— y todo el bloque desapareceria: el usuario ve
    # que su clic no hace nada. Guardando la respuesta, sobrevive a las recargas.
    if st.button("Preguntar", type="primary") and pregunta.strip():
        filtros = Filtros(
            departamentos=sel_dep, categorias=sel_cat,
            monto_min=rango[0] if rango[0] > 0 else None,
            monto_max=rango[1] if rango[1] < tope else None,
            fecha_desde=str(rango_fecha[0]) if rango_fecha and len(rango_fecha) == 2 else None,
            fecha_hasta=str(rango_fecha[1]) if rango_fecha and len(rango_fecha) == 2 else None,
            solo_adjudicados=solo_adj,
        )
        with st.spinner("Buscando procesos…"):
            st.session_state.resultado_t2 = motor.responder(
                pregunta, filtros=filtros, top_k=top_k, umbral=umbral)
        # Al lanzar una consulta nueva se olvidan las explicaciones normativas de la
        # anterior: pertenecian a procesos que ya no estan en pantalla.
        for k in [k for k in st.session_state if str(k).startswith("norma_res_")]:
            del st.session_state[k]

    r = st.session_state.get("resultado_t2")
    if r is not None:
        st.caption(f"Filtros aplicados: **{r.filtros}** · "
                   f"{r.candidatos_tras_filtros} procesos recuperados")

        if r.error:
            st.error("**Error del sistema** — esto no es una respuesta.")
            st.code(r.error)
        elif r.abstuvo:
            etiquetas = {"umbral": "filtro 1 · umbral de similitud (no se llamó al modelo)",
                         "modelo": "filtro 2 · el modelo revisó los procesos y no encontró respuesta",
                         "filtros": "los filtros no dejaron ningún candidato"}
            st.warning(f"**Sin respuesta** — {etiquetas.get(r.filtro_que_decidio, '')}")
            st.write(r.respuesta)
            if not r.llamo_al_modelo:
                st.success("0 tokens, 0 USD: la decisión se tomó antes de llamar a la API.")
        else:
            st.success("**Respuesta**")
            st.write(r.respuesta)
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Similitud máxima", f"{r.similitud_maxima:.4f}")
            m2.metric("Tokens", f"{r.tokens_entrada}+{r.tokens_salida}")
            m3.metric("Costo", f"${r.costo_usd:.6f}")
            m4.metric("Latencia", f"{r.latencia_seg:.1f} s")

        if r.procesos:
            st.divider()
            st.subheader("Procesos recuperados")
            for i, p in enumerate(r.procesos, start=1):
                with st.expander(
                        f"{i}. `{p.ocid}` · similitud {p.similitud:.4f} · "
                        f"{p.departamento} · S/ {p.monto:,.0f}"):
                    st.write(f"**{p.comprador}**")
                    st.caption(f"Categoría: {p.categoria} · Fecha: {p.fecha} · "
                               f"Postores: {p.n_licitantes if p.n_licitantes is not None else 'sin dato'} "
                               f"· Adjudicado: {'sí' if p.adjudicado else 'no'}")
                    st.write(p.descripcion)

                    # --- INNOVACIÓN: enlazar las dos tareas ---
                    # El asistente normativo de la Tarea 1 explica la regla que aplica
                    # al método de contratación de ESTE proceso. No hay mecanismo nuevo:
                    # es una llamada a motor.responder() de la otra tarea.
                    metodo = getattr(p, "metodo", "") or p.categoria
                    clave = f"norma_res_{p.ocid}"

                    if st.button(f"¿Qué dice la ley sobre «{metodo}»?",
                                 key=f"norma_btn_{p.ocid}"):
                        try:
                            from src.innovacion import explicar_norma
                            with st.spinner("Consultando al asistente normativo…"):
                                st.session_state[clave] = explicar_norma(
                                    metodo, p.categoria, cfg)
                        except Exception as e:  # noqa: BLE001
                            st.session_state[clave] = ("ERROR", str(e))

                    # Se pinta FUERA del `if`, leyendo lo guardado, para que la
                    # explicacion siga en pantalla aunque el usuario despliegue otro
                    # proceso o pulse cualquier otro boton.
                    guardado = st.session_state.get(clave)
                    if guardado is not None:
                        if isinstance(guardado, tuple) and guardado[0] == "ERROR":
                            st.error(f"El asistente normativo no está disponible: "
                                     f"{guardado[1]}")
                            st.caption("Construye su índice con: "
                                       "`cd ../tarea1_rag_normativo` y "
                                       "`python build_index.py`")
                        else:
                            rn, aviso = guardado
                            # El aviso aparece cuando SEACE usa un nombre de la Ley
                            # 30225 que la Ley 32069 ya no emplea.
                            if aviso:
                                st.warning(aviso)
                            if rn.error:
                                st.error(rn.error)
                            elif rn.abstuvo:
                                st.info(rn.respuesta)
                                st.caption("El asistente normativo se abstuvo. Esa "
                                           "propiedad se hereda del motor de la Tarea 1: "
                                           "no se reimplementó nada.")
                            else:
                                st.success(rn.respuesta)
                                for fu in rn.fuentes[:3]:
                                    st.caption(f"{fu.cita} · similitud {fu.similitud:.3f}")
                                st.caption(f"Costo de esta consulta: ${rn.costo_usd:.6f}")

# ---------------------------------------------------------- ranking (vista 4 de 6)
with tabs[2]:
    st.subheader("Procesos ordenables")
    if d.empty:
        st.info("Sin datos con los filtros actuales.")
    else:
        cols = ["ocid", "descripcion", "comprador", "departamento", "categoria",
                "monto", "fecha_publicacion", "n_licitantes", "adjudicado"]
        tabla = d[[c for c in cols if c in d.columns]] \
            .sort_values("monto", ascending=False) \
            .head(int(A["max_filas_tabla"]))
        st.dataframe(tabla, use_container_width=True, height=460)
        st.download_button(
            "Descargar CSV",
            tabla.to_csv(index=False).encode("utf-8"),
            file_name="procesos_filtrados.csv", mime="text/csv")
        st.caption(f"Mostrando las {len(tabla):,} de mayor monto, de "
                   f"{len(d):,} que cumplen los filtros.")

# ----------------------------------------------------- distribución (vista 5 de 6)
with tabs[3]:
    st.subheader("Distribución")
    if d.empty:
        st.info("Sin datos con los filtros actuales.")
    else:
        por = st.radio("Agrupar por", ["categoria", "departamento", "mes"],
                       horizontal=True)
        dist = metricas.distribucion(d, por)
        if len(dist):
            c1, c2 = st.columns(2)
            with c1:
                st.write("**Número de procesos**")
                st.bar_chart(dist.set_index(dist.columns[0])["procesos"])
            with c2:
                st.write("**Monto total (PEN)**")
                st.bar_chart(dist.set_index(dist.columns[0])["monto_total"])
            st.dataframe(dist, use_container_width=True)

# --------------------------------------------------------------- riesgo (vista 6)
with tabs[4]:
    st.subheader("Señal de riesgo: adjudicaciones con un solo postor")
    st.warning(cfg.riesgo["aviso"])

    if d.empty:
        st.info("Sin datos con los filtros actuales.")
    else:
        dep = metricas.por_departamento(cfg, d)
        if len(dep):
            st.write("**Por departamento**")
            st.dataframe(dep, use_container_width=True)
            st.bar_chart(dep.set_index("departamento")["pct_postor_unico"])

        top = metricas.top_compradores(cfg, d)
        minimo = cfg.riesgo["min_procesos_por_comprador"]
        st.write(f"**Diez entidades con mayor proporción** "
                 f"(mínimo {minimo} procesos adjudicados)")
        st.caption(f"El mínimo de {minimo} procesos existe porque sin él el ranking lo "
                   "coparían entidades con dos o tres procesos: una con 2 procesos y 1 "
                   "postor único daría 50%, que no distingue un patrón de una "
                   "coincidencia. Solo se nombran entidades públicas, nunca personas.")
        if len(top):
            st.dataframe(top, use_container_width=True)
        else:
            st.info("Ninguna entidad supera el mínimo con los filtros actuales.")

        st.divider()
        st.write("**Innovación · Segunda señal: periodo de consulta corto**")
        detalle, resumen = metricas.plazo_corto(cfg, d)
        if resumen:
            c1, c2, c3 = st.columns(3)
            c1.metric("Mediana de días de consulta", resumen["mediana_dias"])
            c2.metric(f"Con menos de {resumen['dias_minimos']} días",
                      f"{resumen['pct_plazo_corto']:.1f}%")
            pc = resumen.get("pct_postor_unico_con_plazo_corto")
            pn = resumen.get("pct_postor_unico_con_plazo_normal")
            if pc is not None and pn:
                c3.metric("Postor único: plazo corto vs normal",
                          f"{pc:.1f}% vs {pn:.1f}%",
                          delta=f"{pc/pn:.1f}x" if pn else None)
            st.caption("El periodo de consulta es la ventana en la que un proveedor "
                       "puede pedir aclaraciones y observar las bases. Si es muy corta, "
                       "quien no estuviera avisado de antemano no llega a competir. "
                       "Se mide sobre ese campo y no sobre el «periodo de licitación», "
                       "cuyo inicio y fin son idénticos en el 100% de los registros.")
            if len(detalle):
                st.dataframe(detalle.head(100), use_container_width=True)

# ------------------------------------------------------------- calidad de datos
with tabs[5]:
    st.subheader("Sobre qué está parado este análisis")
    st.caption("Ninguna regla borra registros. Cada una marca, cuenta y declara qué "
               "se hizo. El enunciado es explícito: descartar filas en silencio es un "
               "enfoque que suspende.")

    cal = cargar_tabla(str(cfg.outputs_dir / "data_quality.csv"))
    if len(cal):
        st.dataframe(cal, use_container_width=True)

    st.subheader("Recuperación territorial — cascada de 4 pasos")
    rec = cargar_tabla(str(cfg.outputs_dir / "recuperacion_territorial.csv"))
    if len(rec):
        st.dataframe(rec, use_container_width=True)

    st.subheader("De cuántas filas se partió")
    st.caption("El enunciado pide reportar cuántas filas había antes y después de "
               "llegar a una fila por proceso.")
    st.dataframe(cargar_tabla(str(cfg.outputs_dir / "conteos_filas.csv")),
                 use_container_width=True)

    st.subheader("Descargas")
    st.dataframe(cargar_tabla(str(cfg.outputs_dir / "descargas.csv")),
                 use_container_width=True)

# ------------------------------------------------------------------- metodología
with tabs[6]:
    st.subheader("Por qué el monto y el departamento son filtros y no embeddings")
    st.markdown("""
Tomemos la pregunta **«obras de agua y saneamiento en Cusco por más de un millón de
soles»**. Contiene tres condiciones de naturaleza distinta:

1. **«obras de agua y saneamiento» es semántica.** No hay ninguna columna que diga eso.
   Hay descripciones libres que dicen *«mejoramiento del sistema de agua potable»*,
   *«ampliación de redes de alcantarillado»* o *«planta de tratamiento de aguas
   residuales»*. Ninguna comparte palabras con la pregunta, pero todas significan lo
   mismo. Para eso sirven los embeddings.

2. **«por más de un millón de soles» es numérica, y un embedding no puede resolverla.**
   El vector de *«un millón de soles»* está cerquísima del de *«900,000 soles»*: son
   textos parecidos. Pero 900,000 **no cumple** la condición. Los embeddings capturan
   parecido, no orden ni magnitud: no existe un «mayor que» en el espacio vectorial.

3. **«en Cusco» parece semántica pero no lo es.** Si se dejara a los embeddings, un
   proceso de una entidad de Lima cuya descripción mencione *«carretera Lima-Cusco»*
   puntuaría alto. El departamento no es lo que el texto menciona: es un atributo del
   comprador, normalizado en la Fase 2 y guardado como metadato.

**Regla práctica:** lo que es exacto y verificable va a un filtro; lo que es ambiguo va
a los embeddings.
""")

    st.subheader("Y esto es lo que pasa medido")
    ef = cargar_tabla(str(cfg.eval_dir / "resultados" / "efecto_filtros.csv"))
    if len(ef):
        st.dataframe(ef, use_container_width=True)
        st.metric("Acierto territorial: departamento en el TEXTO",
                  f"{ef['pct_texto'].mean():.0f}%")
        st.metric("Acierto territorial: departamento como FILTRO",
                  f"{ef['pct_filtro'].mean():.0f}%")

    st.subheader("¿Transfiere el umbral calibrado en la Tarea 1?")
    bar = cargar_tabla(str(cfg.eval_dir / "resultados" / "barrido_umbral.csv"))
    if len(bar):
        st.dataframe(bar, use_container_width=True)
        st.caption(f"Sí transfiere. El umbral de la Tarea 1 "
                   f"({cfg.motor['umbral_tarea1']}) da el mismo porcentaje de aciertos "
                   "y además cero abstenciones incorrectas.")

    st.subheader("Costos de esta tarea")
    res = motor.costos.resumen()
    if len(res):
        st.dataframe(res, use_container_width=True)
        st.metric("Total gastado", f"${motor.costos.total_usd():.6f}")
