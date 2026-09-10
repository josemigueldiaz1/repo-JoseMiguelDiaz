"""
Figuras y mapas para el informe y para el control visual del pipeline.

En la Fase 1 el objetivo de estos productos no es "quedar bonito": son el control de
calidad visual de la validacion. Un mapa donde los puntos marcados aparecen en su sitio
detecta en dos segundos un error de asignacion de coordenadas que una tabla de conteos
puede esconder.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")  # backend sin ventana: el pipeline corre sin display
import matplotlib.pyplot as plt  # noqa: E402

from .config import Config  # noqa: E402

log = logging.getLogger(__name__)

COLOR_REGION = {"Costa": "#0E7C7B", "Sierra": "#C1666B", "Selva": "#4C6E5D"}


def guardar_figura(fig, destino: Path, dpi: int = 200) -> Path:
    """
    Guarda la figura en PNG y ademas en **PDF vectorial**.

    El enunciado pide que las figuras del informe sean "vector PDF o PNG de alta
    resolucion". El PDF es preferible: LaTeX lo incrusta sin perdida y se puede ampliar sin
    pixelarse. El PNG se conserva porque es lo que se puede pegar en una presentacion o
    mirar rapido desde el explorador de archivos.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destino, dpi=dpi, bbox_inches="tight")
    fig.savefig(destino.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    log.info("  figura    %-24s (+ %s)", destino.name, destino.with_suffix(".pdf").name)
    return destino


# ------------------------------------------------------------------ figuras estaticas
def figura_ambito(
    distritos: gpd.GeoDataFrame,
    oferta: gpd.GeoDataFrame,
    demanda: gpd.GeoDataFrame,
    cfg: Config,
    destino: Path,
) -> Path:
    """Mapa general del ambito: distritos, centros poblados y oferta resolutiva."""
    fig, axes = plt.subplots(1, len(cfg.departamentos),
                             figsize=(6 * len(cfg.departamentos), 7))
    axes = np.atleast_1d(axes)

    for ax, dep in zip(axes, cfg.departamentos):
        d = distritos[distritos["DEPARTAMEN"].str.upper() == dep]
        dem = demanda[demanda["departamento"].str.upper() == dep]
        of = oferta[(oferta["departamento"].str.upper() == dep) & oferta["coord_valida"]]
        res = of[of["es_resolutiva"]]

        d.plot(ax=ax, facecolor="#f4f4f2", edgecolor="#b9b9b4", linewidth=0.4)
        if len(dem):
            dem.plot(ax=ax, color="#7a7a7a", markersize=np.clip(dem["poblacion"] / 400, 0.6, 60),
                     alpha=0.45, linewidth=0)
        if len(of):
            of[~of["es_resolutiva"]].plot(ax=ax, color="#9ecae1", markersize=5,
                                          alpha=0.7, linewidth=0)
        if len(res):
            res.plot(ax=ax, color="#d62728", markersize=48, marker="*",
                     edgecolor="black", linewidth=0.4, zorder=5)

        # Los ejes se fijan al poligono del departamento. Sin esto, los establecimientos
        # que R2/R4 marcaron por caer fuera de su departamento declarado estiran la extension
        # y dejan el mapa util reducido a un punto. Siguen dibujados, pero fuera de cuadro.
        x0, y0, x1, y1 = d.total_bounds
        mx, my = (x1 - x0) * 0.04, (y1 - y0) * 0.04
        ax.set_xlim(x0 - mx, x1 + mx)
        ax.set_ylim(y0 - my, y1 + my)

        region = cfg.region_natural.get(dep, "")
        fuera = int((~of.geometry.within(d.union_all())).sum()) if len(of) else 0
        ax.set_title(f"{dep.title()} · {region}\n"
                     f"{len(dem):,} centros poblados · {len(res)} resolutivos"
                     + (f"\n({fuera} IPRESS fuera del departamento declarado)" if fuera else ""),
                     fontsize=11)
        ax.set_axis_off()

    handles = [
        plt.Line2D([], [], marker="o", color="none", markerfacecolor="#7a7a7a",
                   markersize=6, label="Centro poblado (tamano ~ poblacion)"),
        plt.Line2D([], [], marker="o", color="none", markerfacecolor="#9ecae1",
                   markersize=6, label="IPRESS no resolutiva"),
        plt.Line2D([], [], marker="*", color="none", markerfacecolor="#d62728",
                   markeredgecolor="black", markersize=13, label="IPRESS resolutiva (II-1+)"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False, fontsize=10)
    fig.suptitle("Ambito del estudio — oferta resolutiva frente a demanda poblacional",
                 fontsize=13, y=0.98)
    fig.tight_layout(rect=(0, 0.05, 1, 0.96))
    return guardar_figura(fig, destino)


def figura_calidad(reporte_df: pd.DataFrame, destino: Path) -> Path:
    """Barras horizontales con los hallazgos de cada regla de validacion."""
    df = reporte_df.copy()
    fig, ax = plt.subplots(figsize=(9, 4.2))
    y = np.arange(len(df))
    ax.barh(y, df["registros_marcados"], color="#c44e52", label="marcados")
    ax.barh(y, df["recuperados"], color="#55a868", label="recuperados")
    ax.set_yticks(y)
    ax.set_yticklabels([f"{r}  {n[:38]}" for r, n in zip(df["regla"], df["nombre"])],
                       fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("registros")
    ax.set_title("Fase 1 — hallazgos por regla de validacion")
    for i, (m, rec) in enumerate(zip(df["registros_marcados"], df["recuperados"])):
        if m:
            ax.text(m, i, f"  {m:,}", va="center", fontsize=8)
    ax.legend(frameon=False, loc="lower right")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    return guardar_figura(fig, destino)


# ------------------------------------------------------------------- figuras Fase 2
def figura_acceso(acceso: pd.DataFrame, cfg: Config, destino: Path) -> Path:
    """
    Tiempo al establecimiento resolutivo mas cercano: mapa y distribucion por departamento.

    Se distinguen tres estados, y esa distincion es el punto de la figura: puntos servidos
    por la red, puntos que enganchan demasiado lejos como para que el tiempo signifique algo
    (`fuera_de_red`), y puntos que no alcanzan ningun resolutivo por carretera.
    """
    deps = cfg.departamentos
    fig, axes = plt.subplots(2, len(deps), figsize=(5.6 * len(deps), 9.5),
                             gridspec_kw={"height_ratios": [1.6, 1]})
    axes = np.atleast_2d(axes)

    for j, dep in enumerate(deps):
        g = acceso[acceso["departamento"].str.upper() == dep]
        alc = g["alc_car"].fillna(False)
        fuera = g["fuera_de_red"].fillna(False)
        ok = alc & ~fuera

        # --- mapa ---
        ax = axes[0, j]
        if ok.any():
            s = ax.scatter(g.loc[ok, "lon"], g.loc[ok, "lat"], c=g.loc[ok, "t_car"],
                           cmap="RdYlGn_r", s=9, vmin=0, vmax=180, linewidth=0)
            plt.colorbar(s, ax=ax, fraction=0.04, label="minutos al resolutivo")
        if fuera.any():
            ax.scatter(g.loc[fuera, "lon"], g.loc[fuera, "lat"], facecolors="none",
                       edgecolors="#7b3294", s=14, linewidth=0.5, label="fuera de red")
        if (~alc).any():
            ax.scatter(g.loc[~alc, "lon"], g.loc[~alc, "lat"], marker="x", c="black",
                       s=16, linewidth=0.7, label="inalcanzable")
        ax.set_title(f"{dep.title()} · {cfg.region_natural.get(dep, '')}", fontsize=11)
        ax.set_axis_off()
        if fuera.any() or (~alc).any():
            ax.legend(loc="lower left", fontsize=8, frameon=False)

        # --- distribucion ---
        ax = axes[1, j]
        if ok.any():
            ax.hist(g.loc[ok, "t_car"].clip(upper=300), bins=40, color="#2b7bba",
                    edgecolor="white", linewidth=0.4)
            med = float(g.loc[ok, "t_car"].median())
            ax.axvline(med, color="#c44e52", linestyle="--", linewidth=1.6)
            ax.text(med, ax.get_ylim()[1] * 0.92, f"  mediana {med:.0f} min",
                    color="#c44e52", fontsize=9)
        for banda in cfg.metricas.get("bandas_minutos", [30, 60, 120]):
            ax.axvline(banda, color="#999999", linewidth=0.7, linestyle=":")
        ax.set_xlabel("minutos al resolutivo mas cercano (recortado a 300)")
        ax.set_ylabel("puntos de demanda")
        ax.spines[["top", "right"]].set_visible(False)
        n_f, n_i = int(fuera.sum()), int((~alc).sum())
        ax.set_title(f"{int(ok.sum())} en red · {n_f} fuera de red · {n_i} inalcanzables",
                     fontsize=9)

    fig.suptitle("Fase 2 — Tiempo por carretera al establecimiento resolutivo mas cercano",
                 fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    return guardar_figura(fig, destino)


def figura_snapping(acceso: pd.DataFrame, sens: pd.DataFrame, cfg: Config,
                    destino: Path) -> Path:
    """
    El hallazgo central de la Fase 2 en una figura: a que distancia de la red vial vive la
    gente, y por que la conclusion no depende del umbral elegido.
    """
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 5))
    umbral = float(cfg.ruteo.get("snap_umbral_m", 2000))

    # --- izquierda: distribucion acumulada de la distancia de enganche ---
    for dep in cfg.departamentos:
        g = acceso[acceso["departamento"].str.upper() == dep]
        d = g["snap_m"].dropna().sort_values()
        if d.empty:
            continue
        y = np.arange(1, len(d) + 1) / len(d) * 100
        ax1.plot(d.to_numpy(), y, linewidth=2,
                 label=f"{dep.title()} ({cfg.region_natural.get(dep, '')})",
                 color=COLOR_REGION.get(cfg.region_natural.get(dep, ""), None))
    ax1.axvline(umbral, color="#c44e52", linestyle="--", linewidth=1.5)
    ax1.text(umbral * 1.15, 52, f"umbral\n{umbral:.0f} m", color="#c44e52", fontsize=9,
             va="center")
    ax1.set_xscale("log")
    ax1.set_xlabel("distancia a la via mas cercana (m, escala log)")
    ax1.set_ylabel("% de puntos de demanda")
    ax1.set_title("Que tan lejos de la red vial vive la gente")
    ax1.legend(frameon=False, fontsize=9, loc="lower right")
    ax1.grid(alpha=0.25, linewidth=0.5)
    ax1.spines[["top", "right"]].set_visible(False)

    # --- derecha: sensibilidad al umbral ---
    cols = [c for c in sens.columns if c.startswith("pct_pob_")]
    for c in cols:
        etiqueta = c.replace("pct_pob_", "").upper()
        ax2.plot(sens["umbral_m"], sens[c], marker="o", linewidth=2, label=etiqueta)
    ax2.axvline(umbral, color="#c44e52", linestyle="--", linewidth=1.5)
    ax2.set_xscale("log")
    ax2.set_xlabel("umbral de enganche (m, escala log)")
    ax2.set_ylabel("% de poblacion fuera de red")
    ax2.set_title("La conclusion no depende del umbral")
    ax2.legend(frameon=False, fontsize=9)
    ax2.grid(alpha=0.25, linewidth=0.5)
    ax2.spines[["top", "right"]].set_visible(False)

    fig.suptitle("Fase 2 — Cobertura real de la red vial", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return guardar_figura(fig, destino)


def figura_modos(acceso: pd.DataFrame, perfiles: list[str], cfg: Config,
                 destino: Path) -> Path:
    """Comparacion del tiempo de acceso entre auto, pie y bicicleta."""
    otros = [p for p in perfiles if p != "car"]
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5))

    # --- izquierda: mediana por modo y departamento ---
    ax = axes[0]
    deps = [d for d in cfg.departamentos]
    x = np.arange(len(deps))
    ancho = 0.8 / max(len(perfiles), 1)
    for i, p in enumerate(perfiles):
        vals = []
        for dep in deps:
            g = acceso[(acceso["departamento"].str.upper() == dep)
                       & acceso[f"alc_{p}"].fillna(False)
                       & (~acceso["fuera_de_red"].fillna(False))]
            vals.append(float(g[f"t_{p}"].median()) if len(g) else np.nan)
        ax.bar(x + i * ancho, vals, ancho, label=p)
    ax.set_xticks(x + ancho * (len(perfiles) - 1) / 2)
    ax.set_xticklabels([d.title() for d in deps])
    ax.set_ylabel("mediana de minutos al resolutivo")
    ax.set_title("Tiempo mediano por modo (solo puntos servidos por la red)")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)

    # --- derecha: razon respecto al auto ---
    ax = axes[1]
    datos, etiquetas = [], []
    for p in otros:
        for dep in deps:
            col = f"razon_{p}_car"
            if col not in acceso.columns:
                continue
            g = acceso[(acceso["departamento"].str.upper() == dep)
                       & (~acceso["fuera_de_red"].fillna(False))]
            r = g[col].replace([np.inf, -np.inf], np.nan).dropna()
            if len(r):
                datos.append(r.clip(upper=r.quantile(0.98)).to_numpy())
                etiquetas.append(f"{p}\n{dep[:4].title()}")
    if datos:
        # matplotlib >=3.9 renombro `labels` a `tick_labels` en boxplot; en 3.11 el nombre
        # antiguo ya no existe.
        bp = ax.boxplot(datos, tick_labels=etiquetas, showfliers=False, patch_artist=True)
        for caja in bp["boxes"]:
            caja.set_facecolor("#9ecae1")
        ax.axhline(1, color="#c44e52", linestyle="--", linewidth=1.2)
    ax.set_ylabel("razon de tiempo frente al auto")
    ax.set_title("Cuantas veces mas lento que en auto\n(la razon NO es constante)")
    ax.spines[["top", "right"]].set_visible(False)

    fig.suptitle("Fase 2 — Comparacion entre modos de transporte", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return guardar_figura(fig, destino)


# ------------------------------------------------------------------- figuras Fase 3
COLOR_BANDA = {"<=30 min": "#1a7f37", "30-60 min": "#7bb662", "60-120 min": "#f0c419",
               ">120 min": "#e8743b", "sin acceso vial": "#7b3294"}


def figura_bandas(bandas: pd.DataFrame, cfg: Config, destino: Path) -> Path:
    """Barras apiladas: que porcentaje de la poblacion cae en cada banda de tiempo."""
    b = bandas.set_index("grupo")
    orden = [g for g in cfg.departamentos if g in b.index] + \
            [g for g in b.index if g not in cfg.departamentos]
    b = b.loc[orden]

    series = {"<=30 min": "pct_0_30min", "30-60 min": "pct_30_60min",
              "60-120 min": "pct_60_120min", ">120 min": "pct_mas_120min",
              "sin acceso vial": "pct_sin_acceso_vial"}
    fig, ax = plt.subplots(figsize=(10, 5.2))
    abajo = np.zeros(len(b))
    y = np.arange(len(b))
    for etiqueta, col in series.items():
        if col not in b.columns:
            continue
        v = b[col].to_numpy(dtype=float)
        ax.barh(y, v, left=abajo, color=COLOR_BANDA[etiqueta], label=etiqueta,
                edgecolor="white", linewidth=0.6)
        for i, (val, iz) in enumerate(zip(v, abajo)):
            if val >= 4:
                ax.text(iz + val / 2, i, f"{val:.0f}%", ha="center", va="center",
                        fontsize=9, color="white", fontweight="bold")
        abajo += v

    ax.set_yticks(y)
    ax.set_yticklabels([f"{g.title()}\n{cfg.region_natural.get(g, '')}" for g in b.index])
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("% de la poblacion")
    ax.set_title("Fase 3 — Cobertura: tiempo por carretera al establecimiento resolutivo")
    ax.legend(ncol=5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    ax.spines[["top", "right", "left"]].set_visible(False)
    fig.tight_layout()
    return guardar_figura(fig, destino)


def figura_lorenz(curvas: pd.DataFrame, gini: pd.DataFrame, cfg: Config,
                  destino: Path) -> Path:
    """
    Curvas de Lorenz del tiempo de acceso.

    Se lee al reves que una de ingresos: aqui la curva mide como se reparte el TIEMPO de
    viaje. Cuanto mas se aleja de la diagonal, mas concentrado esta el tiempo total en una
    minoria de la poblacion, es decir, mas desigual es el acceso.
    """
    fig, ax = plt.subplots(figsize=(7.2, 6.6))
    ax.plot([0, 100], [0, 100], color="#999999", linestyle="--", linewidth=1.2,
            label="igualdad perfecta")
    g_map = gini.set_index("ambito")["gini_tiempo_acceso"].to_dict()
    for ambito, c in curvas.groupby("ambito"):
        es_total = ambito == "TOTAL"
        ax.plot(c["pct_poblacion"], c["pct_tiempo"],
                linewidth=3 if es_total else 2,
                color="black" if es_total else COLOR_REGION.get(
                    cfg.region_natural.get(ambito, ""), None),
                linestyle="-" if not es_total else ":",
                label=f"{ambito.title()} (Gini {g_map.get(ambito, float('nan')):.3f})")
    ax.set_xlabel("% acumulado de poblacion, de menor a mayor tiempo de viaje")
    ax.set_ylabel("% acumulado del tiempo de viaje total")
    ax.set_title("Fase 3 — Curva de Lorenz del tiempo de acceso\n"
                 "cuanto mas lejos de la diagonal, mas desigual", fontsize=12)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    ax.grid(alpha=0.25, linewidth=0.5)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    return guardar_figura(fig, destino)


def figura_pobreza(cruce: pd.DataFrame, resumen: pd.DataFrame, cfg: Config,
                   destino: Path) -> Path:
    """Dispersion acceso x pobreza, con los cuadrantes de priorizacion."""
    d = cruce.dropna(subset=["tasa_pobreza", "t_medio_pond_min"])
    fig, ax = plt.subplots(figsize=(9.5, 7))

    med_t = d["t_medio_pond_min"].median()
    med_p = d["tasa_pobreza"].median()
    ax.axvline(med_p, color="#999999", linestyle="--", linewidth=1)
    ax.axhline(med_t, color="#999999", linestyle="--", linewidth=1)

    for dep, g in d.groupby("departamento"):
        ax.scatter(g["tasa_pobreza"], g["t_medio_pond_min"],
                   s=np.clip(g["poblacion"] / 900, 12, 420), alpha=0.65,
                   color=COLOR_REGION.get(cfg.region_natural.get(dep, ""), None),
                   edgecolor="white", linewidth=0.6,
                   label=f"{dep.title()} ({cfg.region_natural.get(dep, '')})")

    # Etiquetar los peores del cuadrante de doble carga.
    dc = d[(d["t_medio_pond_min"] > med_t) & (d["tasa_pobreza"] > med_p)]
    for _, f in dc.nlargest(6, "t_medio_pond_min").iterrows():
        ax.annotate(str(f["distrito"]).title(),
                    (f["tasa_pobreza"], f["t_medio_pond_min"]),
                    fontsize=7.5, xytext=(4, 4), textcoords="offset points", alpha=0.85)

    ax.text(0.985, 0.975, f"DOBLE CARGA\nlejos y pobre\n{len(dc)} distritos",
            transform=ax.transAxes, ha="right", va="top", fontsize=9.5,
            color="#8b0000", fontweight="bold",
            bbox=dict(boxstyle="round", facecolor="#ffecec", edgecolor="#d99", alpha=0.9))

    # Escala logaritmica en Y: los distritos amazonicos llegan a 5 000 min y en escala lineal
    # aplastan al 95% de los datos en una franja pegada al eje. La mediana y los cuadrantes
    # se mantienen porque son cortes sobre los datos, no sobre la escala.
    ax.set_yscale("log")
    for banda in cfg.metricas.get("bandas_minutos", [30, 60, 120]):
        ax.axhline(banda, color="#cccccc", linewidth=0.7, linestyle=":", zorder=0)
        ax.text(ax.get_xlim()[0], banda, f" {banda} min ", fontsize=7.5, color="#888888",
                va="bottom", ha="left")

    r = resumen[resumen["ambito"] == "TOTAL"]
    sub = ""
    if len(r):
        f = r.iloc[0]
        p = "< 0.001" if f["spearman_p"] < 0.001 else f"= {f['spearman_p']:.3f}"
        sub = (f"Spearman rho = {f['spearman_rho']:+.3f} (p {p}), "
               f"n = {int(f['n_distritos'])} distritos\n"
               "relacion CORRELACIONAL, no causal: la lejania es un confusor comun")
    ax.set_xlabel("tasa de pobreza monetaria distrital (%)")
    ax.set_ylabel("tiempo medio ponderado al resolutivo mas cercano (min, escala log)")
    ax.set_title("Fase 3 — Acceso frente a pobreza\n" + sub, fontsize=11.5)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    ax.grid(alpha=0.2, linewidth=0.5)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    return guardar_figura(fig, destino)


# ------------------------------------------------------------------- mapa interactivo
def mapa_validacion(
    oferta: gpd.GeoDataFrame,
    demanda: gpd.GeoDataFrame,
    distritos: gpd.GeoDataFrame,
    cfg: Config,
    destino: Path,
) -> Path | None:
    """
    Mapa Folium de control de la Fase 1.

    Capas conmutables: limites distritales, oferta resolutiva, oferta no resolutiva,
    registros con coordenada marcada y mapa de calor de la demanda. Sirve para verificar a
    ojo que la validacion hizo lo que dice el reporte antes de gastar horas en el ruteo.
    """
    try:
        import folium
        from folium.plugins import MarkerCluster, HeatMap
    except ImportError:
        log.warning("  folium no esta instalado; se omite el mapa interactivo")
        return None

    centro = [float(demanda["lat"].mean()), float(demanda["lon"].mean())]
    # OpenStreetMap y no CartoDB: desde 2024 los tiles de CartoDB exigen API key y folium
    # emite un UserWarning con un mapa base que no carga para quien abra el HTML.
    m = folium.Map(location=centro, zoom_start=6, tiles="OpenStreetMap", control_scale=True)

    folium.GeoJson(
        distritos[["UBIGEO", "DISTRITO", "PROVINCIA", "DEPARTAMEN", "geometry"]],
        name="Limites distritales",
        style_function=lambda _: {"fillColor": "#00000000", "color": "#8f8f8f",
                                  "weight": 0.6, "fillOpacity": 0},
        tooltip=folium.GeoJsonTooltip(fields=["DISTRITO", "PROVINCIA", "DEPARTAMEN"],
                                      aliases=["Distrito", "Provincia", "Departamento"]),
    ).add_to(m)

    # --- demanda: mapa de calor ponderado por poblacion ---
    dem = demanda[demanda["poblacion"] > 0]
    if len(dem):
        peso_max = float(dem["poblacion"].quantile(0.99)) or 1.0
        HeatMap(
            [[r.lat, r.lon, min(float(r.poblacion) / peso_max, 1.0)]
             for r in dem.itertuples()],
            name="Demanda (calor por poblacion)", radius=11, blur=15, min_opacity=0.25,
            show=False,
        ).add_to(m)

    # --- oferta resolutiva ---
    res = oferta[oferta["es_resolutiva"] & oferta["coord_valida"]]
    capa_res = folium.FeatureGroup(name=f"IPRESS resolutivas ({len(res)})", show=True)
    for r in res.itertuples():
        folium.CircleMarker(
            [r.lat, r.lon], radius=7, color="#7f0000", weight=1.5,
            fill=True, fill_color="#d62728", fill_opacity=0.9,
            tooltip=f"{r.nombre} — {r.categoria}",
            popup=folium.Popup(
                f"<b>{r.nombre}</b><br>Categoria: {r.categoria}<br>"
                f"Institucion: {r.institucion}<br>Distrito: {r.distrito}<br>"
                f"Estado: {r.estado}", max_width=320),
        ).add_to(capa_res)
    capa_res.add_to(m)

    # --- oferta no resolutiva (agrupada: son miles) ---
    nores = oferta[(~oferta["es_resolutiva"]) & oferta["coord_valida"]]
    cluster = MarkerCluster(name=f"IPRESS no resolutivas ({len(nores)})", show=False)
    for r in nores.itertuples():
        folium.CircleMarker(
            [r.lat, r.lon], radius=3, color="#2b7bba", weight=0.6,
            fill=True, fill_color="#9ecae1", fill_opacity=0.7,
            tooltip=f"{r.nombre} — {r.categoria}",
        ).add_to(cluster)
    cluster.add_to(m)

    # --- registros con problemas de coordenada dentro del ambito ---
    malos = oferta[~oferta["coord_valida"]]
    if len(malos):
        folium.FeatureGroup(
            name=f"Sin coordenada utilizable ({len(malos)}) — no mapeables", show=False
        ).add_to(m)

    conflicto = oferta[oferta["distrito_estado"].isin(["CONFLICTO", "FUERA_DE_TODO_DISTRITO"])]
    if len(conflicto):
        capa_c = folium.FeatureGroup(name=f"Conflicto punto/UBIGEO ({len(conflicto)})", show=False)
        for r in conflicto.itertuples():
            folium.CircleMarker(
                [r.lat, r.lon], radius=6, color="#ff7f0e", weight=2,
                fill=True, fill_color="#ffbb78", fill_opacity=0.85,
                tooltip=f"{r.nombre}: declara {r.ubigeo}, cae en {r.ubigeo_real}",
            ).add_to(capa_c)
        capa_c.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    titulo = (
        '<div style="position:fixed;top:10px;left:60px;z-index:9999;background:white;'
        'padding:8px 14px;border:1px solid #999;border-radius:4px;font-family:sans-serif;'
        'box-shadow:0 1px 4px rgba(0,0,0,.25)">'
        '<b>HW2 · Fase 1 — control de validacion</b><br>'
        f'<span style="font-size:12px">{", ".join(d.title() for d in cfg.departamentos)} · '
        f'{len(demanda):,} centros poblados · {len(res)} IPRESS resolutivas</span></div>'
    )
    m.get_root().html.add_child(folium.Element(titulo))

    destino.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(destino))
    log.info("  mapa      %s", destino.name)
    return destino
