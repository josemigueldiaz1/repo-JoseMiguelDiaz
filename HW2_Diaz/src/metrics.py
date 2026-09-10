"""
Fase 3 — Construccion de metricas.

Convierte tiempos de viaje en indicadores con los que se pueda decidir algo.

Dos reglas que atraviesan todo el modulo, ambas exigidas por el enunciado:

* **Toda agregacion es ponderada por poblacion.** Un promedio simple entre distritos trata
  igual a un caserio de 12 personas y a un pueblo de 12 000. Aqui el peso es `peso_muestral`,
  que expande cada punto de la muestra a la poblacion que representa (ver `routing.py`).
* **Cada metrica es una funcion que recibe un DataFrame y devuelve un DataFrame.** No hay
  logica de metricas escondida en el dashboard ni en el script de orquestacion: la Fase 4
  importa de aqui.

Una decision de fondo sobre los puntos sin acceso vial. El enunciado pide bandas de
cobertura (30/60/120 min), pero una parte de la poblacion no cae en NINGUNA banda: o no
alcanza ningun resolutivo por carretera, o vive tan lejos de la red que su tiempo ruteado no
significa nada (`fuera_de_red`, ver Fase 2). Meterlos en la banda de ">120 min" los daria por
atendidos-pero-lejos, cuando el problema es cualitativamente distinto. Por eso tienen su
propia categoria, **"sin acceso vial"**, y toda tabla la reporta explicitamente.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from .config import Config

log = logging.getLogger(__name__)

SIN_ACCESO = "sin acceso vial"


# ============================================================== utilidades ponderadas
def _media_ponderada(valores: pd.Series, pesos: pd.Series) -> float:
    v, w = pd.to_numeric(valores, errors="coerce"), pd.to_numeric(pesos, errors="coerce")
    m = v.notna() & w.notna() & (w > 0)
    return float(np.average(v[m], weights=w[m])) if m.any() and w[m].sum() > 0 else np.nan


def _percentil_ponderado(valores: pd.Series, pesos: pd.Series, q: float) -> float:
    """
    Percentil ponderado por poblacion.

    No es lo mismo que el percentil de los puntos: responde "el habitante que esta en el
    percentil q, cuanto tarda", que es la pregunta que importa cuando cada punto representa
    a un numero distinto de personas.
    """
    v, w = pd.to_numeric(valores, errors="coerce"), pd.to_numeric(pesos, errors="coerce")
    m = v.notna() & w.notna() & (w > 0)
    if not m.any():
        return np.nan
    v, w = v[m].to_numpy(), w[m].to_numpy()
    orden = np.argsort(v)
    v, w = v[orden], w[orden]
    acum = np.cumsum(w) - 0.5 * w
    return float(np.interp(q * w.sum(), acum, v))


def _validos(acceso: pd.DataFrame) -> pd.Series:
    """Puntos cuyo tiempo de viaje es interpretable: alcanzables y servidos por la red."""
    return (acceso["alc_car"].fillna(False)
            & ~acceso["fuera_de_red"].fillna(False)
            & acceso["t_car"].notna())


# ================================================================ 1. bandas de cobertura
def bandas_cobertura(acceso: pd.DataFrame, cfg: Config,
                     por: str | None = "departamento") -> pd.DataFrame:
    """
    Proporcion de poblacion dentro de cada banda de tiempo al resolutivo mas cercano.

    Devuelve una fila por grupo (o una sola si `por=None`), con la poblacion y el porcentaje
    en cada banda, mas la categoria explicita de los que no tienen acceso vial.
    """
    bandas = list(cfg.metricas.get("bandas_minutos", [30, 60, 120]))
    ok = _validos(acceso)

    def _fila(g: pd.DataFrame, etiqueta) -> dict:
        w = g["peso_muestral"]
        total = float(w.sum())
        gv = g[ok.reindex(g.index, fill_value=False)]
        f = {"grupo": etiqueta, "poblacion_total": round(total)}
        anterior = 0
        for b in bandas:
            sel = (gv["t_car"] > anterior) & (gv["t_car"] <= b) if anterior else (gv["t_car"] <= b)
            pob = float(gv.loc[sel, "peso_muestral"].sum())
            f[f"pob_{anterior}_{b}min"] = round(pob)
            f[f"pct_{anterior}_{b}min"] = round(100 * pob / total, 2) if total else 0.0
            anterior = b
        pob_mas = float(gv.loc[gv["t_car"] > bandas[-1], "peso_muestral"].sum())
        f[f"pob_mas_{bandas[-1]}min"] = round(pob_mas)
        f[f"pct_mas_{bandas[-1]}min"] = round(100 * pob_mas / total, 2) if total else 0.0
        pob_sin = total - float(gv["peso_muestral"].sum())
        f["pob_sin_acceso_vial"] = round(pob_sin)
        f["pct_sin_acceso_vial"] = round(100 * pob_sin / total, 2) if total else 0.0
        # Acumulado: el indicador que se suele citar ("X% a menos de una hora").
        for b in bandas:
            acum = float(gv.loc[gv["t_car"] <= b, "peso_muestral"].sum())
            f[f"pct_acum_{b}min"] = round(100 * acum / total, 2) if total else 0.0
        return f

    filas = ([_fila(g, k) for k, g in acceso.groupby(por)] if por
             else [_fila(acceso, "TOTAL")])
    out = pd.DataFrame(filas)
    log.info("  bandas de cobertura por %s:", por or "total")
    for _, f in out.iterrows():
        log.info("    %-12s <=30min %5.1f%% · <=60min %5.1f%% · <=120min %5.1f%% · "
                 "sin acceso vial %5.1f%%", f["grupo"], f["pct_acum_30min"],
                 f["pct_acum_60min"], f["pct_acum_120min"], f["pct_sin_acceso_vial"])
    return out


# ==================================================== 2. agregacion ponderada por nivel
def agregar_por_nivel(acceso: pd.DataFrame, nivel: str) -> pd.DataFrame:
    """
    Media y percentiles del tiempo de acceso, ponderados por poblacion, al nivel pedido.

    `nivel` es "distrito", "provincia" o "departamento". Devuelve una fila por unidad, con
    la poblacion que representa y cuanta de ella queda sin acceso vial.
    """
    claves = {"distrito": ["departamento", "provincia", "distrito", "ubigeo"],
              "provincia": ["departamento", "provincia"],
              "departamento": ["departamento"]}[nivel]
    ok = _validos(acceso)
    filas = []
    for valores, g in acceso.groupby(claves, dropna=False):
        valores = valores if isinstance(valores, tuple) else (valores,)
        gv = g[ok.reindex(g.index, fill_value=False)]
        total = float(g["peso_muestral"].sum())
        pob_ok = float(gv["peso_muestral"].sum())
        f = dict(zip(claves, valores))
        f.update({
            "nivel": nivel,
            "puntos": len(g),
            "poblacion": round(total),
            "poblacion_con_acceso_vial": round(pob_ok),
            "pct_sin_acceso_vial": round(100 * (total - pob_ok) / total, 2) if total else 0.0,
            "t_medio_pond_min": round(_media_ponderada(gv["t_car"], gv["peso_muestral"]), 1),
            "t_p50_pond_min": round(_percentil_ponderado(gv["t_car"], gv["peso_muestral"], .50), 1),
            "t_p90_pond_min": round(_percentil_ponderado(gv["t_car"], gv["peso_muestral"], .90), 1),
        })
        filas.append(f)
    out = pd.DataFrame(filas).sort_values("t_medio_pond_min", ascending=False,
                                          na_position="first")
    log.info("  agregado a nivel %-12s %d unidades", nivel, len(out))
    return out.reset_index(drop=True)


# ================================================================ 3. brechas criticas
def brechas_criticas(por_distrito: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """
    Distritos con peor acceso, ordenados.

    El criterio de orden combina las dos formas de estar mal: tardar mucho, y directamente no
    tener acceso vial. Se ordena primero por poblacion sin acceso vial y despues por tiempo
    medio, porque no tener camino es peor que tener uno largo.
    """
    n = int(cfg.metricas.get("top_brechas", 20))
    d = por_distrito.copy()
    d["poblacion_sin_acceso"] = (d["poblacion"] * d["pct_sin_acceso_vial"] / 100).round()
    d = d.sort_values(["pct_sin_acceso_vial", "t_medio_pond_min"],
                      ascending=[False, False], na_position="first")
    d["ranking"] = range(1, len(d) + 1)
    cols = ["ranking", "departamento", "provincia", "distrito", "ubigeo", "poblacion",
            "pct_sin_acceso_vial", "poblacion_sin_acceso", "t_medio_pond_min",
            "t_p90_pond_min"]
    out = d[[c for c in cols if c in d.columns]].head(n).reset_index(drop=True)
    log.info("  brechas criticas: top %d distritos", len(out))
    for _, f in out.head(5).iterrows():
        log.info("    %2d. %-28s %-11s pob=%7d · sin acceso %5.1f%% · t medio %s min",
                 f["ranking"], f["distrito"], f["departamento"], f["poblacion"],
                 f["pct_sin_acceso_vial"], f["t_medio_pond_min"])
    return out


# =================================================================== 4. desigualdad
def gini_ponderado(valores: pd.Series, pesos: pd.Series) -> float:
    """
    Coeficiente de Gini ponderado por poblacion.

    Advertencia de interpretacion que el informe debe recoger: el Gini se usa normalmente
    sobre ingresos, donde MAS es mejor. Aqui se aplica al **tiempo de viaje**, donde mas es
    peor. Un Gini de 0 significa que todo el mundo tarda lo mismo, **no** que todo el mundo
    este bien atendido: un territorio donde todos tardan tres horas tiene Gini 0 y acceso
    pesimo. Por eso el Gini nunca se reporta solo, sino junto a la media y a las bandas.
    """
    v, w = pd.to_numeric(valores, errors="coerce"), pd.to_numeric(pesos, errors="coerce")
    m = v.notna() & w.notna() & (w > 0) & (v >= 0)
    if m.sum() < 2:
        return np.nan
    v, w = v[m].to_numpy(dtype=float), w[m].to_numpy(dtype=float)
    orden = np.argsort(v)
    v, w = v[orden], w[orden]
    wv = w * v
    acum_w = np.cumsum(w)
    acum_wv = np.cumsum(wv)
    if acum_wv[-1] <= 0:
        return np.nan
    # Formula de Brown sobre la curva de Lorenz ponderada.
    x = np.insert(acum_w / acum_w[-1], 0, 0.0)
    y = np.insert(acum_wv / acum_wv[-1], 0, 0.0)
    return float(1 - np.sum((x[1:] - x[:-1]) * (y[1:] + y[:-1])))


def curva_lorenz(valores: pd.Series, pesos: pd.Series,
                 puntos: int = 101) -> pd.DataFrame:
    """Puntos (x, y) de la curva de Lorenz ponderada, para graficar."""
    v, w = pd.to_numeric(valores, errors="coerce"), pd.to_numeric(pesos, errors="coerce")
    m = v.notna() & w.notna() & (w > 0) & (v >= 0)
    if m.sum() < 2:
        return pd.DataFrame({"pct_poblacion": [], "pct_tiempo": []})
    v, w = v[m].to_numpy(dtype=float), w[m].to_numpy(dtype=float)
    orden = np.argsort(v)
    v, w = v[orden], w[orden]
    x = np.insert(np.cumsum(w) / w.sum(), 0, 0.0)
    y = np.insert(np.cumsum(w * v) / (w * v).sum(), 0, 0.0)
    rejilla = np.linspace(0, 1, puntos)
    return pd.DataFrame({"pct_poblacion": 100 * rejilla,
                         "pct_tiempo": 100 * np.interp(rejilla, x, y)})


def desigualdad(acceso: pd.DataFrame, cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Gini por departamento y para el ambito completo, mas los puntos de la curva."""
    ok = _validos(acceso)
    filas, curvas = [], []
    for dep, g in list(acceso.groupby("departamento")) + [("TOTAL", acceso)]:
        gv = g[ok.reindex(g.index, fill_value=False)]
        filas.append({
            "ambito": dep,
            "n_puntos": len(gv),
            "poblacion": round(float(gv["peso_muestral"].sum())),
            "gini_tiempo_acceso": round(gini_ponderado(gv["t_car"], gv["peso_muestral"]), 4),
            "t_medio_pond_min": round(_media_ponderada(gv["t_car"], gv["peso_muestral"]), 1),
        })
        c = curva_lorenz(gv["t_car"], gv["peso_muestral"])
        c["ambito"] = dep
        curvas.append(c)
    out = pd.DataFrame(filas)
    log.info("  desigualdad del tiempo de acceso (Gini ponderado):")
    for _, f in out.iterrows():
        log.info("    %-12s Gini=%.4f  (media ponderada %s min)",
                 f["ambito"], f["gini_tiempo_acceso"], f["t_medio_pond_min"])
    return out, pd.concat(curvas, ignore_index=True)


# ============================================================ 5. contraste urbano/rural
def contraste_urbano_rural(acceso: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """
    Acceso urbano frente a rural, con las reglas de clasificacion declaradas.

    Un centro poblado es urbano si su poblacion imputada alcanza el umbral del INEI
    (2 000 habitantes) **o** si su categoria en el shapefile del IGN es de tipo urbano.
    Las reglas viven en `config.md` y la clasificacion se hizo en la Fase 1.
    """
    ok = _validos(acceso)
    filas = []
    for (dep, ur), g in acceso.groupby(["departamento", "urbano_rural"], dropna=False):
        gv = g[ok.reindex(g.index, fill_value=False)]
        total = float(g["peso_muestral"].sum())
        filas.append({
            "departamento": dep,
            "urbano_rural": ur,
            "puntos": len(g),
            "poblacion": round(total),
            "pct_sin_acceso_vial": round(
                100 * (total - float(gv["peso_muestral"].sum())) / total, 2) if total else 0.0,
            "t_medio_pond_min": round(_media_ponderada(gv["t_car"], gv["peso_muestral"]), 1),
            "t_p90_pond_min": round(_percentil_ponderado(gv["t_car"], gv["peso_muestral"], .9), 1),
        })
    out = pd.DataFrame(filas)
    log.info("  contraste urbano / rural:")
    for _, f in out.iterrows():
        log.info("    %-12s %-7s pob=%8d · t medio %6s min · sin acceso vial %5.1f%%",
                 f["departamento"], f["urbano_rural"], f["poblacion"],
                 f["t_medio_pond_min"], f["pct_sin_acceso_vial"])
    return out


# ============================================== 6. cruce con una segunda dimension
def cargar_pobreza(cfg: Config) -> pd.DataFrame:
    """
    Tasa de pobreza monetaria distrital.

    Solo se conserva `POVERTY_RATE`. La misma tabla trae `PBI_PC` e `IDH`, pero ambos tienen
    **un unico valor por departamento repetido en cada distrito**: no aportan variacion
    distrital, y cualquier correlacion con ellos a nivel distrito seria un artefacto de estar
    comparando tres departamentos.
    """
    ruta = cfg.root / cfg.metricas.get("archivo_pobreza", "data/external/pobreza_distrital.csv")
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontro la tabla de pobreza en {ruta}")
    col = cfg.metricas.get("columna_pobreza", "POVERTY_RATE")
    df = pd.read_csv(ruta, encoding="utf-8-sig")
    # El UBIGEO viene como entero, o sea sin el cero inicial de los departamentos 01-09.
    df["ubigeo"] = df["UBIGEO1"].astype(str).str.zfill(6)
    df[col] = pd.to_numeric(df[col], errors="coerce")  # la tabla trae '#N/D' de Excel
    out = df[["ubigeo", col]].rename(columns={col: "tasa_pobreza"}).dropna()
    log.info("  tabla de pobreza: %d distritos con dato", len(out))
    return out


def cruce_acceso_pobreza(por_distrito: pd.DataFrame, pobreza: pd.DataFrame,
                         cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Cruza el acceso distrital con la tasa de pobreza: el segundo eje que exige el enunciado.

    Devuelve (tabla_por_distrito, resumen_de_la_relacion).

    **Sobre la naturaleza de la relacion**, que el enunciado obliga a declarar: lo que se
    mide aqui es **correlacion, no causalidad**, y ni siquiera una correlacion limpia. Ambas
    variables comparten una causa comun evidente —la lejania— que las mueve a la vez: los
    distritos remotos son mas pobres Y estan mas lejos de un hospital, sin que lo uno cause
    lo otro. Tampoco puede descartarse la causalidad inversa (un distrito con mal acceso a
    servicios se empobrece). El dato es util para **priorizar**, no para explicar.
    """
    d = por_distrito.merge(pobreza, on="ubigeo", how="left")
    con = d[d["tasa_pobreza"].notna() & d["t_medio_pond_min"].notna()]

    # Los distritos quedan fuera del cruce por DOS motivos distintos, y reportar solo uno
    # esconderia el otro. El segundo motivo no es un problema de datos: es un resultado.
    sin_pobreza = d["tasa_pobreza"].isna()
    sin_tiempo = d["t_medio_pond_min"].isna()
    if sin_pobreza.any() or sin_tiempo.any():
        log.warning("  quedan fuera del cruce %d de %d distritos:",
                    len(d) - len(con), len(d))
        log.warning("    %2d sin dato de pobreza (distritos de creacion reciente)",
                    int((sin_pobreza & ~sin_tiempo).sum()))
        log.warning("    %2d sin tiempo de acceso: NINGUN punto del distrito tiene un "
                    "tiempo interpretable, o sea que la red vial no sirve al distrito "
                    "entero. Esto no es un hueco de datos, es un hallazgo.",
                    int((sin_tiempo & ~sin_pobreza).sum()))
        log.warning("    %2d por ambos motivos", int((sin_pobreza & sin_tiempo).sum()))
        por_dep = d[sin_tiempo].groupby("departamento").size().to_dict()
        if por_dep:
            log.warning("    distritos enteros sin acceso vial, por departamento: %s", por_dep)

    from scipy import stats
    filas = []
    for etiqueta, g in list(con.groupby("departamento")) + [("TOTAL", con)]:
        if len(g) < 4:
            continue
        rp, pp = stats.pearsonr(g["tasa_pobreza"], g["t_medio_pond_min"])
        rs, ps = stats.spearmanr(g["tasa_pobreza"], g["t_medio_pond_min"])
        filas.append({
            "ambito": etiqueta, "n_distritos": len(g),
            "pearson_r": round(float(rp), 3), "pearson_p": round(float(pp), 4),
            "spearman_rho": round(float(rs), 3), "spearman_p": round(float(ps), 4),
            "pobreza_media_pct": round(float(g["tasa_pobreza"].mean()), 1),
            "naturaleza": "correlacional, no causal (confusor comun: lejania)",
        })
    resumen = pd.DataFrame(filas)

    # Cuadrantes: cruzar las dos dimensiones por su mediana da una priorizacion legible.
    med_t = con["t_medio_pond_min"].median()
    med_p = con["tasa_pobreza"].median()
    d["cuadrante"] = np.select(
        [(d["t_medio_pond_min"] > med_t) & (d["tasa_pobreza"] > med_p),
         (d["t_medio_pond_min"] > med_t) & (d["tasa_pobreza"] <= med_p),
         (d["t_medio_pond_min"] <= med_t) & (d["tasa_pobreza"] > med_p),
         (d["t_medio_pond_min"] <= med_t) & (d["tasa_pobreza"] <= med_p)],
        ["doble carga: lejos y pobre", "lejos pero menos pobre",
         "cerca pero pobre", "cerca y menos pobre"], default="sin dato")

    log.info("  cruce acceso x pobreza (correlacion, NO causalidad):")
    for _, f in resumen.iterrows():
        log.info("    %-12s n=%3d · Pearson r=%+.3f (p=%.4f) · Spearman rho=%+.3f (p=%.4f)",
                 f["ambito"], f["n_distritos"], f["pearson_r"], f["pearson_p"],
                 f["spearman_rho"], f["spearman_p"])
    conteo = d["cuadrante"].value_counts().to_dict()
    log.info("  distritos por cuadrante: %s", conteo)
    dc = d[d["cuadrante"] == "doble carga: lejos y pobre"]
    if len(dc):
        log.info("  DOBLE CARGA: %d distritos, %.0f habitantes (%.1f%% del ambito)",
                 len(dc), dc["poblacion"].sum(),
                 100 * dc["poblacion"].sum() / d["poblacion"].sum())
    return d, resumen


# =========================================================== exportacion a LaTeX
def exportar_latex(df: pd.DataFrame, destino, caption: str, label: str,
                   columnas: dict[str, str] | None = None, max_filas: int = 25,
                   decimales: str = "%.1f",
                   sin_escapar: tuple[str, ...] = ()) -> None:
    """
    Escribe una tabla LaTeX con `booktabs`, lista para `\\input{}` en el informe.

    El enunciado exige que las tablas del informe se generen programaticamente y no se
    tecleen a mano, precisamente para que no puedan desincronizarse de los datos.
    """
    d = df.head(max_filas).copy()
    # Columnas que ya vienen con sintaxis LaTeX propia (por ejemplo "$<$0.001") y que no
    # deben volver a escaparse: hay que anotarlas ANTES del renombrado.
    exentas = {columnas.get(c, c) if columnas else c for c in sin_escapar}
    if columnas:
        d = d[[c for c in columnas if c in d.columns]].rename(columns=columnas)

    # Se escapan los DATOS a mano y se desactiva el escapado automatico de pandas. Si se
    # dejara `escape=True`, pandas escaparia tambien las cabeceras, y un encabezado
    # legitimo como "$\rho$" o "(\%)" saldria impreso como "\textbackslash \%".
    def _escapar(v):
        if not isinstance(v, str):
            return v
        for a, b in (("\\", r"\textbackslash "), ("&", r"\&"), ("%", r"\%"),
                     ("$", r"\$"), ("#", r"\#"), ("_", r"\_"),
                     ("{", r"\{"), ("}", r"\}")):
            v = v.replace(a, b)
        return v

    for c in d.columns:
        if c in exentas:
            continue
        if d[c].dtype == object or isinstance(d[c].dtype, pd.StringDtype):
            d[c] = d[c].map(_escapar)

    # Los ausentes se imprimen como raya, no como "NaN". No es cosmetica: en la tabla de
    # brechas criticas, un valor ausente en "tiempo medio" significa que el distrito NO TIENE
    # ningun punto con tiempo interpretable —la red vial no lo sirve en absoluto—, y "NaN"
    # sugiere un fallo de calculo cuando en realidad es el resultado. La raya es la
    # convencion tipografica para "no aplica".
    tex = d.to_latex(index=False, escape=False, longtable=False,
                     caption=caption, label=label, position="htbp",
                     column_format="l" + "r" * (len(d.columns) - 1),
                     float_format=decimales, na_rep="---")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(tex, encoding="utf-8")
    log.info("  tabla LaTeX  %-34s %d filas", destino.name, len(d))
