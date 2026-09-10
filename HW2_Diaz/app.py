"""
HW2 — Fase 4. Dashboard interactivo de accesibilidad a establecimientos resolutivos.

    streamlit run app.py

Pensado para que un director regional de salud explore los resultados sin saber Python.

Dos reglas de diseno que impone el enunciado y que atraviesan todo el archivo:

* **Solo lee archivos precomputados.** No hay una sola llamada a OSRM ni reconstruccion de
  grafos: todo sale de `data/processed/` y `data/outputs/`. La app arranca en segundos y
  funciona con el motor de ruteo apagado, que es como se va a demostrar en el video.
* **Cero logica de metricas aqui.** Las funciones de calculo viven en `src/metrics.py` y se
  importan. Si el dashboard recalculara por su cuenta, tendriamos dos implementaciones de la
  misma metrica esperando a divergir.

El simulador de escenarios (seccion 6) es la pieza que justifica haber calculado la matriz
completa en la Fase 2: recalcula la cobertura con establecimientos "ascendidos" leyendo
tiempos ya guardados, sin rutear nada en vivo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_config  # noqa: E402
from src import metrics as mt  # noqa: E402

st.set_page_config(page_title="Acceso a salud resolutiva — Perú",
                   page_icon="🏥", layout="wide")

BANDAS_COLOR = {"≤30 min": "#1a7f37", "30-60 min": "#7bb662", "60-120 min": "#f0c419",
                ">120 min": "#e8743b", "Sin acceso vial": "#7b3294"}


# ============================================================================== carga
@st.cache_data(show_spinner="Cargando datos precomputados...")
def cargar():
    """
    Lee de disco todo lo que la app necesita.

    `@st.cache_data` hace que esto corra una sola vez por sesion: los filtros de la barra
    lateral no vuelven a tocar el disco.
    """
    cfg = load_config()
    ext = "parquet" if cfg.salida.get("formato", "parquet") == "parquet" else "gpkg"
    leer = gpd.read_parquet if ext == "parquet" else gpd.read_file
    P, O = cfg.processed_dir, cfg.outputs_dir

    d = {
        "cfg": cfg,
        "acceso": leer(P / f"acceso_puntos.{ext}"),
        "oferta": leer(P / f"oferta_salud.{ext}"),
        "distritos": leer(P / f"distritos.{ext}"),
        "por_distrito": pd.read_csv(O / "acceso_por_distrito.csv", dtype={"ubigeo": str}),
        "calidad": pd.read_csv(O / "data_quality_oferta.csv"),
    }
    for nombre, archivo in [("matriz_cand", P / "matriz_candidatos.parquet"),
                            ("candidatos", O / "candidatos_ascenso.csv")]:
        d[nombre] = (pd.read_parquet(archivo) if archivo.suffix == ".parquet"
                     else pd.read_csv(archivo, dtype={"cod_ipress": str})) \
            if archivo.exists() else None
    return d


def faltan_datos() -> bool:
    cfg = load_config()
    ext = "parquet" if cfg.salida.get("formato", "parquet") == "parquet" else "gpkg"
    need = [cfg.processed_dir / f"acceso_puntos.{ext}",
            cfg.outputs_dir / "acceso_por_distrito.csv"]
    faltan = [p for p in need if not p.exists()]
    if faltan:
        st.error("Faltan resultados del pipeline. Ejecuta primero:")
        st.code("python run_pipeline.py", language="bash")
        st.caption("Archivos que no se encontraron: " + ", ".join(p.name for p in faltan))
        return True
    return False


def clasificar_banda(t, sin_acceso) -> str:
    if sin_acceso:
        return "Sin acceso vial"
    if pd.isna(t):
        return "Sin acceso vial"
    if t <= 30:
        return "≤30 min"
    if t <= 60:
        return "30-60 min"
    if t <= 120:
        return "60-120 min"
    return ">120 min"


# ================================================================================ app
if faltan_datos():
    st.stop()

D = cargar()
cfg = D["cfg"]
acceso = D["acceso"].copy()
oferta = D["oferta"].copy()

acceso["sin_acceso"] = (~acceso["alc_car"].fillna(False)) | acceso["fuera_de_red"].fillna(False)
acceso["banda"] = [clasificar_banda(t, s)
                   for t, s in zip(acceso["t_car"], acceso["sin_acceso"])]

st.title("🏥 Acceso por carretera a establecimientos de salud resolutivos")
st.caption(
    "La *hora dorada*: solo los establecimientos de categoría **II-1 o superior** pueden "
    "operar o hacer una cesárea. Este panel mide cuánto tarda la población en llegar a uno, "
    "por red vial real. Datos: RENIPRESS 31-08-2026 · IGN · WorldPop 2020 · OpenStreetMap."
)

# ------------------------------------------------------------------ barra lateral
st.sidebar.header("Filtros")
deps = sorted(acceso["departamento"].dropna().unique())
sel_dep = st.sidebar.multiselect("Departamento", deps, default=deps)

provs_disp = sorted(acceso.loc[acceso["departamento"].isin(sel_dep), "provincia"]
                    .dropna().unique()) if sel_dep else []
sel_prov = st.sidebar.multiselect("Provincia", provs_disp, default=[],
                                  help="Vacío = todas las provincias de los departamentos elegidos")

sel_ur = st.sidebar.multiselect("Ámbito", ["urbano", "rural"], default=["urbano", "rural"])
umbral = st.sidebar.slider("Umbral de tiempo (min)", 15, 240, 60, 15,
                           help="Define qué se considera 'cubierto' en los indicadores")

st.sidebar.divider()
st.sidebar.subheader("Capa de establecimientos")
cats = sorted(oferta.loc[oferta["apto_para_ruteo"], "categoria"].dropna().unique())
# El default se intersecta con las categorias que EXISTEN en el ambito. El whitelist de
# config.md incluye III-2 y III-E, pero en Lambayeque, Ayacucho y Loreto no hay ninguno:
# pasarle a Streamlit un default que no esta entre las opciones lanza excepcion y la app
# no llega ni a renderizar.
sel_cat = st.sidebar.multiselect(
    "Categoría", cats, default=[c for c in cfg.categorias_resolutivas if c in cats])
insts = sorted(oferta.loc[oferta["apto_para_ruteo"], "institucion"].dropna().unique())
sel_inst = st.sidebar.multiselect("Institución", insts, default=[],
                                  help="Vacío = todas las instituciones")

st.sidebar.divider()
st.sidebar.caption(
    "Este panel **solo lee archivos precomputados**. No consulta el motor de ruteo, así que "
    "funciona con OSRM apagado y carga en segundos."
)

# ---------------------------------------------------------------------- filtrado
f = acceso[acceso["departamento"].isin(sel_dep)] if sel_dep else acceso.iloc[0:0]
if sel_prov:
    f = f[f["provincia"].isin(sel_prov)]
if sel_ur:
    f = f[f["urbano_rural"].isin(sel_ur)]

if f.empty:
    st.warning("La selección actual no incluye ningún punto de demanda. "
               "Amplía los filtros de la barra lateral.")
    st.stop()

# ============================================================== 1. cabecera de KPIs
pob = float(f["peso_muestral"].sum())
cubierta = float(f.loc[f["t_car"].le(umbral) & ~f["sin_acceso"], "peso_muestral"].sum())
sin_via = float(f.loc[f["sin_acceso"], "peso_muestral"].sum())
mediana = mt._percentil_ponderado(f.loc[~f["sin_acceso"], "t_car"],
                                  f.loc[~f["sin_acceso"], "peso_muestral"], 0.5)

dist_f = D["por_distrito"]
dist_f = dist_f[dist_f["departamento"].isin(sel_dep)]
if sel_prov:
    dist_f = dist_f[dist_f["provincia"].isin(sel_prov)]
peor = (dist_f.sort_values(["pct_sin_acceso_vial", "t_medio_pond_min"], ascending=False)
        .head(1))

c1, c2, c3, c4 = st.columns(4)
c1.metric(f"Población a ≤{umbral} min", f"{cubierta:,.0f}",
          f"{100 * cubierta / pob:.1f}% de {pob:,.0f}")
c2.metric(f"Población a más de {umbral} min", f"{pob - cubierta - sin_via:,.0f}",
          f"{100 * (pob - cubierta - sin_via) / pob:.1f}%", delta_color="inverse")
c3.metric("Sin acceso vial", f"{sin_via:,.0f}",
          f"{100 * sin_via / pob:.1f}%", delta_color="inverse")
c4.metric("Mediana de acceso",
          f"{mediana:.0f} min" if np.isfinite(mediana) else "n/d",
          f"peor distrito: {peor['distrito'].iloc[0].title()}" if len(peor) else "")

st.divider()

# =============================================== 2 y 3. mapa coroplético + oferta
izq, der = st.columns([3, 2])

with izq:
    st.subheader("Tiempo medio al resolutivo más cercano, por distrito")
    geo = D["distritos"].merge(
        dist_f[["ubigeo", "t_medio_pond_min", "poblacion", "pct_sin_acceso_vial",
                "distrito", "provincia", "departamento"]],
        left_on="UBIGEO", right_on="ubigeo", how="inner")
    if geo.empty:
        st.info("No hay distritos en la selección.")
    else:
        # El tope de color se recorta al p95: sin eso, los distritos amazonicos de 5 000
        # minutos aplastan toda la escala y el resto del mapa sale del mismo color.
        tope = float(np.nanpercentile(geo["t_medio_pond_min"].dropna(), 95)) or 120
        fig = px.choropleth_map(
            geo, geojson=geo.geometry.__geo_interface__, locations=geo.index,
            color="t_medio_pond_min", color_continuous_scale="RdYlGn_r",
            range_color=(0, tope), opacity=0.72,
            map_style="carto-positron", zoom=4.6,
            # Centro a partir del bounding box, no del centroide: calcular centroides sobre
            # un CRS geografico es incorrecto y geopandas avisa por cada llamada.
            center={"lat": float((geo.total_bounds[1] + geo.total_bounds[3]) / 2),
                    "lon": float((geo.total_bounds[0] + geo.total_bounds[2]) / 2)},
            hover_name="distrito",
            hover_data={"departamento": True, "provincia": True,
                        "poblacion": ":,.0f", "t_medio_pond_min": ":.1f",
                        "pct_sin_acceso_vial": ":.1f"},
            labels={"t_medio_pond_min": "min al resolutivo",
                    "pct_sin_acceso_vial": "% sin acceso vial",
                    "poblacion": "población"},
            height=560)
        fig.update_layout(margin=dict(l=0, r=0, t=0, b=0),
                          coloraxis_colorbar=dict(title="min"))

        # --- capa de establecimientos ---
        of = oferta[oferta["apto_para_ruteo"] & oferta["departamento"].isin(sel_dep)]
        if sel_cat:
            of = of[of["categoria"].isin(sel_cat)]
        if sel_inst:
            of = of[of["institucion"].isin(sel_inst)]
        if len(of):
            res = of[of["es_resolutiva"]]
            nores = of[~of["es_resolutiva"]]
            if len(nores):
                fig.add_trace(go.Scattermap(
                    lat=nores["lat"], lon=nores["lon"], mode="markers",
                    marker=dict(size=6, color="#2b7bba"),
                    name=f"No resolutivas ({len(nores)})",
                    text=nores["nombre"] + " · " + nores["categoria"],
                    hoverinfo="text"))
            if len(res):
                fig.add_trace(go.Scattermap(
                    lat=res["lat"], lon=res["lon"], mode="markers",
                    marker=dict(size=13, color="#b40426"),
                    name=f"Resolutivas ({len(res)})",
                    text=res["nombre"] + " · " + res["categoria"] + " · " + res["institucion"],
                    hoverinfo="text"))
            fig.update_layout(legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01,
                                          bgcolor="rgba(255,255,255,.75)"))
        st.plotly_chart(fig, width="stretch")
        st.caption("Usa la leyenda para encender y apagar las capas de establecimientos. "
                   "La escala de color se recorta al percentil 95 para que los valores "
                   "extremos de la Amazonía no aplasten el resto.")

with der:
    # ==================================================== 4. vista de distribución
    st.subheader("Distribución del tiempo de acceso")
    modo = st.radio("Partir por", ["Departamento", "Urbano / rural"],
                    horizontal=True, label_visibility="collapsed")
    col = "departamento" if modo == "Departamento" else "urbano_rural"
    dat = f[~f["sin_acceso"] & f["t_car"].notna()]
    if dat.empty:
        st.info("Ningún punto de la selección tiene tiempo interpretable.")
    else:
        fig2 = px.ecdf(dat, x="t_car", color=col, ecdfnorm="percent",
                       labels={"t_car": "minutos al resolutivo más cercano",
                               "percent": "% de puntos"},
                       height=300)
        fig2.add_vline(x=umbral, line_dash="dash", line_color="#c44e52",
                       annotation_text=f"{umbral} min")
        fig2.update_layout(margin=dict(l=0, r=0, t=10, b=0),
                           legend=dict(orientation="h", y=-0.25))
        fig2.update_xaxes(range=[0, min(300, float(dat["t_car"].quantile(0.98)))])
        st.plotly_chart(fig2, width="stretch")

    # bandas de cobertura de la selección
    st.subheader("Cobertura de la selección")
    bandas = (f.groupby("banda")["peso_muestral"].sum() / pob * 100).reindex(
        list(BANDAS_COLOR), fill_value=0.0)
    fig3 = go.Figure()
    for etiqueta, valor in bandas.items():
        fig3.add_bar(y=["población"], x=[valor], name=etiqueta, orientation="h",
                     marker_color=BANDAS_COLOR[etiqueta],
                     text=f"{valor:.0f}%" if valor >= 5 else "", textposition="inside")
    fig3.update_layout(barmode="stack", height=150, showlegend=True,
                       margin=dict(l=0, r=0, t=10, b=0),
                       legend=dict(orientation="h", y=-0.4),
                       xaxis=dict(range=[0, 100], title="% de la población"),
                       yaxis=dict(showticklabels=False))
    st.plotly_chart(fig3, width="stretch")

st.divider()

# ==================================================== 5. tabla de peores distritos
st.subheader("Distritos con peor acceso")
tabla = dist_f.sort_values(["pct_sin_acceso_vial", "t_medio_pond_min"],
                           ascending=[False, False]).copy()
cols = {"departamento": "Departamento", "provincia": "Provincia", "distrito": "Distrito",
        "poblacion": "Población", "pct_sin_acceso_vial": "% sin acceso vial",
        "t_medio_pond_min": "Media (min)", "t_p90_pond_min": "p90 (min)"}
vista = tabla[[c for c in cols if c in tabla.columns]].rename(columns=cols)
st.dataframe(vista, width="stretch", hide_index=True, height=320)
st.download_button("⬇️ Descargar esta tabla en CSV",
                   vista.to_csv(index=False).encode("utf-8"),
                   "distritos_peor_acceso.csv", "text/csv")

st.divider()

# ================================================== 6. simulador de escenarios
st.subheader("🔬 Simulador: ¿qué pasaría si ascendemos un establecimiento?")
st.markdown(
    "Selecciona uno o más establecimientos **I-3 o I-4** para simular que adquieren "
    "capacidad resolutiva. El panel recalcula la cobertura **usando la matriz de tiempos "
    "precomputada en la Fase 2**, sin rutear nada en vivo."
)

if D["matriz_cand"] is None or D["candidatos"] is None:
    st.info("Falta la matriz de candidatos. Ejecuta `python run_pipeline.py --phase 2`.")
else:
    cand = D["candidatos"].copy()
    cand = cand[cand["departamento"].isin(sel_dep)]
    if sel_prov:
        cand = cand[cand["provincia"].isin(sel_prov)]

    if cand.empty:
        st.info("No hay establecimientos I-3/I-4 candidatos en la selección actual.")
    else:
        cand["etiqueta"] = (cand["nombre"] + "  ·  " + cand["categoria"] + "  ·  "
                            + cand["distrito"].str.title() + " ("
                            + cand["departamento"].str.title() + ")")
        elegidos = st.multiselect(
            f"Establecimientos a ascender ({len(cand)} candidatos disponibles)",
            options=cand["etiqueta"].tolist(), default=[],
            help="Cada uno pasaría a contar como resolutivo en el cálculo del más cercano")

        if not elegidos:
            st.caption("Elige al menos uno para ver la ganancia de cobertura.")
        else:
            codigos = cand.loc[cand["etiqueta"].isin(elegidos), "cod_ipress"].astype(str)
            mc = D["matriz_cand"]
            mc = mc[mc["cod_ipress"].astype(str).isin(codigos)]

            # Nuevo tiempo = el mejor entre el actual y el del establecimiento ascendido.
            # La matriz ya viene podada a los pares que mejoran, asi que basta el minimo.
            mejora = (mc.groupby("ccpp_id")["duracion_seg"].min() / 60).rename("t_nuevo")
            sim = f.merge(mejora, on="ccpp_id", how="left")
            sim["t_final"] = np.where(
                sim["t_nuevo"].notna()
                & (sim["sin_acceso"] | (sim["t_nuevo"] < sim["t_car"].fillna(np.inf))),
                sim["t_nuevo"], sim["t_car"])
            sim["sin_acceso_final"] = sim["sin_acceso"] & sim["t_nuevo"].isna()

            cub_antes = float(f.loc[f["t_car"].le(umbral) & ~f["sin_acceso"],
                                    "peso_muestral"].sum())
            cub_desp = float(sim.loc[sim["t_final"].le(umbral) & ~sim["sin_acceso_final"],
                                     "peso_muestral"].sum())
            sinv_desp = float(sim.loc[sim["sin_acceso_final"], "peso_muestral"].sum())
            benef = int((sim["t_final"] < sim["t_car"].fillna(np.inf)).sum())

            k1, k2, k3 = st.columns(3)
            k1.metric(f"Población a ≤{umbral} min", f"{cub_desp:,.0f}",
                      f"+{cub_desp - cub_antes:,.0f}  ({100 * (cub_desp - cub_antes) / pob:+.2f} pp)")
            k2.metric("Sin acceso vial", f"{sinv_desp:,.0f}",
                      f"{sinv_desp - sin_via:+,.0f}", delta_color="inverse")
            med_desp = mt._percentil_ponderado(
                sim.loc[~sim["sin_acceso_final"], "t_final"],
                sim.loc[~sim["sin_acceso_final"], "peso_muestral"], 0.5)
            k3.metric("Mediana de acceso",
                      f"{med_desp:.0f} min" if np.isfinite(med_desp) else "n/d",
                      f"{med_desp - mediana:+.1f} min" if np.isfinite(med_desp)
                      and np.isfinite(mediana) else "", delta_color="inverse")

            st.caption(f"{benef:,} puntos de demanda mejorarían su tiempo de acceso "
                       f"con estos {len(elegidos)} ascenso(s).")

            # Ganancia marginal de cada establecimiento por separado.
            filas = []
            for _, c in cand[cand["etiqueta"].isin(elegidos)].iterrows():
                m1 = D["matriz_cand"]
                m1 = m1[m1["cod_ipress"].astype(str) == str(c["cod_ipress"])]
                mj = (m1.groupby("ccpp_id")["duracion_seg"].min() / 60).rename("t_n")
                s1 = f.merge(mj, on="ccpp_id", how="left")
                tf = np.where(s1["t_n"].notna()
                              & (s1["sin_acceso"] | (s1["t_n"] < s1["t_car"].fillna(np.inf))),
                              s1["t_n"], s1["t_car"])
                sa = s1["sin_acceso"] & s1["t_n"].isna()
                g = float(s1.loc[(tf <= umbral) & ~sa, "peso_muestral"].sum()) - cub_antes
                filas.append({"Establecimiento": c["nombre"], "Categoría": c["categoria"],
                              "Distrito": str(c["distrito"]).title(),
                              f"Ganancia a ≤{umbral} min": round(g)})
            marg = pd.DataFrame(filas).sort_values(f"Ganancia a ≤{umbral} min",
                                                   ascending=False)
            st.markdown("**Ganancia de cada ascenso por separado** "
                        "(la suma no tiene por qué igualar el efecto conjunto: dos "
                        "establecimientos cercanos se solapan)")
            st.dataframe(marg, width="stretch", hide_index=True)

st.divider()

# ================================================== 7. panel de calidad de datos
with st.expander("📋 Calidad de los datos de origen (Fase 1)", expanded=False):
    st.markdown(
        "Las seis reglas de validación aplicadas al registro **nacional** de RENIPRESS "
        "(36 004 establecimientos), antes de recortar al ámbito. **Ninguna fila se borró**: "
        "lo marcado se conserva con su bandera y se excluye del cálculo del más cercano."
    )
    q = D["calidad"]
    cq = {"regla": "Regla", "nombre": "Descripción", "registros_marcados": "Marcados",
          "pct_marcados": "%", "recuperados": "Recuperados", "descartados": "Descartados",
          "accion": "Acción"}
    st.dataframe(q[[c for c in cq if c in q.columns]].rename(columns=cq),
                 width="stretch", hide_index=True)

    a, b = st.columns(2)
    a.metric("Registros sin coordenadas",
             f"{int(q.loc[q['regla'].eq('R1'), 'registros_marcados'].iloc[0]):,}",
             f"{q.loc[q['regla'].eq('R1'), 'pct_marcados'].iloc[0]:.1f}% del registro nacional",
             delta_color="inverse")
    b.metric("Recuperados por corrección",
             f"{int(q['recuperados'].sum()):,}",
             "coordenadas invertidas, mojibake y bordes distritales")
    st.caption("Detalle completo en `data/outputs/data_quality_oferta.md`.")

st.caption(
    "HW2 · José Miguel Díaz · Los datos provienen del pipeline reproducible de este "
    "repositorio (`python run_pipeline.py`). Limitaciones declaradas en "
    "`logs/material_video.md`, sección 6."
)
