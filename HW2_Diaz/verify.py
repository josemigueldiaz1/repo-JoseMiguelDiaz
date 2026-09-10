"""
Verificacion independiente de los productos de cada fase.

    python verify.py --phase 1

No repite la logica del pipeline: vuelve a leer los archivos que quedaron en disco y
comprueba que cumplan las invariantes que deben cumplir. Si el pipeline se rompe en silencio
(una columna que se pierde, un CRS que cambia, un flag que deja de ser coherente con la
regla que lo genera), esto lo detecta.

Devuelve codigo de salida 0 si todo pasa y 1 si algo falla, para poder encadenarlo.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_config  # noqa: E402

VERDE, ROJO, GRIS, FIN = "\033[92m", "\033[91m", "\033[90m", "\033[0m"


class Verificador:
    def __init__(self, titulo: str):
        print(f"\n{'=' * 72}\n{titulo}\n{'=' * 72}")
        self.fallos: list[str] = []
        self.total = 0

    def seccion(self, nombre: str) -> None:
        print(f"\n{GRIS}-- {nombre}{FIN}")

    def chk(self, condicion: bool, msg: str) -> bool:
        self.total += 1
        ok = bool(condicion)
        print(f"  {VERDE}PASA{FIN}  {msg}" if ok else f"  {ROJO}FALLA{FIN} {msg}")
        if not ok:
            self.fallos.append(msg)
        return ok

    def info(self, msg: str) -> None:
        print(f"  {GRIS}·{FIN}     {msg}")

    def resumen(self) -> int:
        print(f"\n{'=' * 72}")
        if self.fallos:
            print(f"{ROJO}{len(self.fallos)} de {self.total} verificaciones FALLARON{FIN}")
            for f in self.fallos:
                print(f"  - {f}")
            return 1
        print(f"{VERDE}Las {self.total} verificaciones pasaron{FIN}")
        return 0


def verificar_fase_1(cfg) -> int:
    v = Verificador("VERIFICACION — Fase 1: adquisicion y validacion")
    P, O = cfg.processed_dir, cfg.outputs_dir

    # ------------------------------------------------------------------ existencia
    v.seccion("archivos esperados")
    fmt = cfg.salida.get("formato", "parquet")
    ext = "parquet" if fmt == "parquet" else "gpkg"
    esperados = [
        P / f"oferta_salud.{ext}", P / f"demanda_ccpp.{ext}", P / f"distritos.{ext}",
        O / "data_quality_oferta.csv", O / "data_quality_oferta.md",
        O / "resumen_fase1.csv",
        cfg.raw_dir / "_manifest.json",
        cfg.figuras_dir / "fase1_ambito.png", cfg.figuras_dir / "fase1_calidad.png",
    ]
    for p in esperados:
        v.chk(p.exists() and p.stat().st_size > 0, f"existe y no esta vacio: {p.name}")
    if v.fallos:
        return v.resumen()

    leer = gpd.read_parquet if fmt == "parquet" else gpd.read_file
    oferta = leer(P / f"oferta_salud.{ext}")
    demanda = leer(P / f"demanda_ccpp.{ext}")
    distritos = leer(P / f"distritos.{ext}")
    v.info(f"oferta={oferta.shape}  demanda={demanda.shape}  distritos={distritos.shape}")

    # ------------------------------------------------------------------------ CRS
    v.seccion("sistema de referencia")
    crs_esperado = int(cfg.salida.get("crs_trabajo", "EPSG:4326").split(":")[1])
    for nombre, g in (("oferta", oferta), ("demanda", demanda), ("distritos", distritos)):
        v.chk(g.crs is not None and g.crs.to_epsg() == crs_esperado,
              f"{nombre} en EPSG:{crs_esperado}")

    # -------------------------------------------------------------------- ambito
    v.seccion("ambito declarado en config.md")
    deps = set(cfg.departamentos)
    v.chk(set(distritos["DEPARTAMEN"].str.upper()) == deps,
          f"distritos cubren exactamente {sorted(deps)}")
    v.chk(set(oferta["departamento"].str.upper()) <= deps, "oferta no sale del ambito")
    v.chk(set(demanda["departamento"].str.upper()) <= deps, "demanda no sale del ambito")

    # ------------------------------------------------------------- claves e integridad
    v.seccion("claves e integridad referencial")
    v.chk(oferta["cod_ipress"].is_unique, "cod_ipress unico en el ambito")
    v.chk(demanda["ccpp_id"].is_unique, "ccpp_id unico")
    v.chk(distritos["UBIGEO"].is_unique, "UBIGEO unico en distritos")
    v.chk(bool(demanda["ubigeo"].isin(distritos["UBIGEO"]).all()),
          "todo ubigeo de demanda existe en la capa de distritos")

    # --------------------------------------------------- regla de capacidad resolutiva
    v.seccion("definicion de capacidad resolutiva")
    esperado = (oferta["estado"].isin(cfg.estados_activos)
                & oferta["categoria"].isin(cfg.categorias_resolutivas))
    v.chk(bool((oferta["es_resolutiva"] == esperado).all()),
          "es_resolutiva == (estado activo AND categoria en el whitelist de config.md)")
    v.chk(bool(oferta.loc[oferta["es_resolutiva"], "categoria"]
               .isin(cfg.categorias_resolutivas).all()),
          "ninguna resolutiva tiene categoria fuera del whitelist")
    n_res = int(oferta["es_resolutiva"].sum())
    n_apt = int((oferta["es_resolutiva"] & oferta["apto_para_ruteo"]).sum())
    v.info(f"{n_res} resolutivas, {n_apt} aptas para ruteo")
    v.chk(n_apt > 0, "hay al menos una resolutiva apta para ruteo (si no, la Fase 2 no corre)")

    # ------------------------------------------------------------------- validacion
    v.seccion("coherencia de los flags de validacion")
    v.chk(bool(oferta.loc[oferta["apto_para_ruteo"], "coord_valida"].all()),
          "apto_para_ruteo implica coord_valida")
    v.chk(bool((~oferta.loc[oferta["apto_para_ruteo"], "es_duplicado"]).all()),
          "apto_para_ruteo implica no duplicado")
    v.chk(bool(oferta.loc[oferta["coord_valida"], "geometry"].notna().all()),
          "toda fila con coord_valida tiene geometria")
    val = oferta[oferta["coord_valida"]]
    lon_min, lat_min, lon_max, lat_max = cfg.bbox_peru
    v.chk(bool(val["lon"].between(lon_min, lon_max).all()
               and val["lat"].between(lat_min, lat_max).all()),
          "toda coordenada valida cae dentro del bounding box del Peru")
    v.info(f"coordenadas utilizables: {len(val)}/{len(oferta)} "
           f"({100 * len(val) / len(oferta):.1f}%)")

    # --------------------------------------------------------------------- demanda
    v.seccion("dataset de demanda")
    v.chk(bool((demanda["poblacion"] >= 0).all()), "poblacion no negativa")
    v.chk(demanda["poblacion"].sum() > 0, "la poblacion total es positiva")
    if "tiene_poblacion_raster" in demanda.columns:
        v.chk(bool((demanda["tiene_poblacion_raster"] == (demanda["poblacion"] > 0)).all()),
              "tiene_poblacion_raster coherente con poblacion > 0")
    v.chk(bool(demanda["urbano_rural"].isin(["urbano", "rural"]).all()),
          "urbano_rural solo toma los valores urbano/rural")
    v.chk(bool((demanda["es_urbano"] == demanda["urbano_rural"].eq("urbano")).all()),
          "es_urbano coherente con urbano_rural")
    v.info(f"poblacion total imputada: {demanda['poblacion'].sum():,.0f}")
    v.info("por departamento: " + ", ".join(
        f"{k}={vv:,.0f}" for k, vv in
        demanda.groupby("departamento")["poblacion"].sum().items()))

    # ------------------------------------------------------------ reporte de calidad
    v.seccion("reporte de calidad")
    import pandas as pd
    rc = pd.read_csv(O / "data_quality_oferta.csv")
    v.chk(len(rc) == 6, f"las 6 reglas obligatorias estan reportadas (hay {len(rc)})")
    v.chk(set(rc["regla"]) == {"R1", "R2", "R3", "R4", "R5", "R6"},
          "los codigos de regla son R1..R6")
    v.chk(bool(rc["justificacion"].notna().all() and (rc["justificacion"].str.len() > 40).all()),
          "toda regla trae una justificacion escrita")
    v.chk(bool(rc["accion"].notna().all()), "toda regla declara una accion")

    # ------------------------------------------------------------------- manifiesto
    v.seccion("trazabilidad de las descargas")
    import json
    man = json.loads((cfg.raw_dir / "_manifest.json").read_text(encoding="utf-8"))
    obligatorias = [k for k, f in cfg.fuentes.items() if not f.opcional]
    for k in obligatorias:
        v.chk(k in man, f"la fuente obligatoria '{k}' esta en el manifiesto")
    v.chk(all(len(e.get("sha256", "")) == 64 for e in man.values()),
          "toda entrada del manifiesto trae SHA-256")
    v.chk(all(e.get("fecha_descarga_utc") for e in man.values()),
          "toda entrada del manifiesto trae fecha de descarga")

    return v.resumen()


def verificar_fase_2(cfg) -> int:
    import pandas as pd

    v = Verificador("VERIFICACION — Fase 2: ruteo y tiempos de viaje")
    P, O = cfg.processed_dir, cfg.outputs_dir
    fmt = cfg.salida.get("formato", "parquet")
    ext = "parquet" if fmt == "parquet" else "gpkg"

    # ------------------------------------------------------------------ existencia
    v.seccion("archivos esperados")
    esperados = [
        P / f"acceso_puntos.{ext}", P / "matriz_car.parquet",
        O / "resumen_fase2.csv", O / "snapping_diagnostico.csv",
        O / "sensibilidad_umbral_snap.csv",
        cfg.figuras_dir / "fase2_acceso.png", cfg.figuras_dir / "fase2_snapping.png",
    ]
    for p in esperados:
        v.chk(p.exists() and p.stat().st_size > 0, f"existe y no esta vacio: {p.name}")
    if v.fallos:
        return v.resumen()

    leer = gpd.read_parquet if fmt == "parquet" else gpd.read_file
    acceso = leer(P / f"acceso_puntos.{ext}")
    matriz = pd.read_parquet(P / "matriz_car.parquet")
    oferta = leer(P / f"oferta_salud.{ext}")
    resolutivas = oferta[oferta["es_resolutiva"] & oferta["apto_para_ruteo"]]
    v.info(f"acceso={acceso.shape}  matriz={matriz.shape}  resolutivas={len(resolutivas)}")

    # ------------------------------------------------------------------- muestra
    v.seccion("muestra de demanda")
    tope = int(cfg.ruteo.get("max_puntos_demanda", 5000))
    v.chk(len(acceso) <= tope, f"la muestra respeta el tope del enunciado ({len(acceso)} <= {tope})")
    v.chk(acceso["ccpp_id"].is_unique, "ccpp_id unico en el consolidado")
    v.chk(bool(acceso["departamento"].str.upper().isin(cfg.departamentos).all()),
          "la muestra no sale del ambito")
    v.chk(acceso["ubigeo"].nunique() > 0, "los puntos conservan su distrito")
    v.info(f"distritos representados: {acceso['ubigeo'].nunique()}")

    # ------------------------------------------------------------- matriz completa
    v.seccion("matriz completa origen x resolutiva")
    n_o, n_d = acceso["ccpp_id"].nunique(), len(resolutivas)
    v.chk(len(matriz) == n_o * n_d,
          f"la matriz es completa: {len(matriz)} filas == {n_o} origenes x {n_d} destinos")
    v.chk(bool(matriz["cod_ipress"].isin(resolutivas["cod_ipress"]).all()),
          "todos los destinos de la matriz son resolutivos aptos")
    v.chk(bool(matriz["ccpp_id"].isin(acceso["ccpp_id"]).all()),
          "todos los origenes de la matriz estan en la muestra")
    v.chk(bool((matriz["duracion_seg"].dropna() >= 0).all()), "no hay duraciones negativas")
    v.chk(bool((matriz["distancia_m"].dropna() >= 0).all()), "no hay distancias negativas")
    n_nan = int(matriz["duracion_seg"].isna().sum())
    v.info(f"pares inalcanzables: {n_nan:,} ({100 * n_nan / len(matriz):.2f}%)")

    # ------------------------------------------------------------- coherencia
    v.seccion("coherencia del consolidado")
    alc = acceso["alc_car"].fillna(False)
    v.chk(bool(acceso.loc[alc, "t_car"].notna().all()),
          "todo punto alcanzable tiene tiempo calculado")
    v.chk(bool(acceso.loc[~alc, "t_car"].isna().all()),
          "ningun punto inalcanzable tiene tiempo inventado")
    v.chk(bool((acceso.loc[alc, "t_car"] >= 0).all()), "los tiempos no son negativos")
    v.chk(bool(acceso.loc[alc, "id_car"].isin(resolutivas["cod_ipress"]).all()),
          "el establecimiento mas cercano siempre es un resolutivo apto")

    # el tiempo del consolidado coincide con el minimo de la matriz
    minimos = (matriz.dropna(subset=["duracion_seg"])
               .groupby("ccpp_id")["duracion_seg"].min() / 60).round(4)
    comp = acceso.loc[alc, ["ccpp_id", "t_car"]].set_index("ccpp_id")["t_car"].round(4)
    junto = comp.to_frame("consolidado").join(minimos.to_frame("matriz"), how="inner")
    v.chk(len(junto) > 0 and bool((junto["consolidado"] - junto["matriz"]).abs().max() < 0.01),
          "el tiempo del consolidado es exactamente el minimo de la matriz")

    # ------------------------------------------------------------- fuera de red
    v.seccion("clasificacion fuera de red")
    umbral = float(cfg.ruteo.get("snap_umbral_m", 2000))
    v.chk("snap_m" in acceso.columns and "fuera_de_red" in acceso.columns,
          "el consolidado trae snap_m y fuera_de_red")
    esperado = acceso["snap_m"].isna() | (acceso["snap_m"] > umbral)
    v.chk(bool((acceso["fuera_de_red"].fillna(False) == esperado).all()),
          f"fuera_de_red coincide con snap_m > {umbral:.0f} m")
    pob = float(acceso["peso_muestral"].sum())
    pf = float(acceso.loc[acceso["fuera_de_red"].fillna(False), "peso_muestral"].sum())
    v.info(f"fuera de red: {int(acceso['fuera_de_red'].sum())} puntos · "
           f"{100 * pf / pob:.1f}% de la poblacion")

    # ------------------------------------------------------------- peso muestral
    v.seccion("expansion poblacional")
    demanda = leer(P / f"demanda_ccpp.{ext}")
    v.chk(abs(pob - float(demanda["poblacion"].sum())) < 1,
          "los pesos muestrales reproducen la poblacion total del ambito")
    v.info(f"poblacion representada: {pob:,.0f}")

    # ------------------------------------------------------------- sensibilidad
    v.seccion("analisis de sensibilidad")
    sens = pd.read_csv(O / "sensibilidad_umbral_snap.csv")
    v.chk(len(sens) >= 3, f"hay al menos 3 umbrales evaluados (hay {len(sens)})")
    v.chk(bool(sens["pct_poblacion"].is_monotonic_decreasing),
          "el % fuera de red decrece al relajar el umbral (coherencia interna)")

    return v.resumen()


def verificar_fase_3(cfg) -> int:
    import numpy as np
    import pandas as pd

    v = Verificador("VERIFICACION — Fase 3: metricas")
    O, T = cfg.outputs_dir, cfg.root / "report" / "tablas"

    # ------------------------------------------------------------------ existencia
    v.seccion("archivos esperados")
    csvs = ["bandas_cobertura", "acceso_por_distrito", "acceso_por_provincia",
            "acceso_por_departamento", "brechas_criticas", "desigualdad_gini",
            "curva_lorenz", "contraste_urbano_rural", "acceso_x_pobreza",
            "acceso_x_pobreza_correlacion"]
    for n in csvs:
        p = O / f"{n}.csv"
        v.chk(p.exists() and p.stat().st_size > 0, f"existe y no esta vacio: {n}.csv")
    for n in ("bandas_cobertura", "acceso_departamento", "brechas_criticas",
              "desigualdad", "urbano_rural", "acceso_pobreza"):
        p = T / f"{n}.tex"
        v.chk(p.exists() and p.stat().st_size > 0, f"tabla LaTeX: {n}.tex")
    for n in ("fase3_bandas", "fase3_lorenz", "fase3_pobreza"):
        p = cfg.figuras_dir / f"{n}.png"
        v.chk(p.exists() and p.stat().st_size > 0, f"figura: {n}.png")
    if v.fallos:
        return v.resumen()

    bandas = pd.read_csv(O / "bandas_cobertura.csv")
    dist = pd.read_csv(O / "acceso_por_distrito.csv")
    dep = pd.read_csv(O / "acceso_por_departamento.csv")
    gini = pd.read_csv(O / "desigualdad_gini.csv")
    lorenz = pd.read_csv(O / "curva_lorenz.csv")
    brechas = pd.read_csv(O / "brechas_criticas.csv")
    ur = pd.read_csv(O / "contraste_urbano_rural.csv")
    rel = pd.read_csv(O / "acceso_x_pobreza_correlacion.csv")

    # --------------------------------------------------------------------- bandas
    v.seccion("bandas de cobertura")
    partes = ["pct_0_30min", "pct_30_60min", "pct_60_120min", "pct_mas_120min",
              "pct_sin_acceso_vial"]
    v.chk(all(c in bandas.columns for c in partes), "estan las 5 categorias de banda")
    suma = bandas[partes].sum(axis=1)
    v.chk(bool(((suma - 100).abs() < 0.5).all()),
          f"las bandas suman 100% en cada ambito (max desvio {float((suma-100).abs().max()):.2f})")
    v.chk(bool((bandas["pct_acum_30min"] <= bandas["pct_acum_60min"] + 1e-6).all()
               and (bandas["pct_acum_60min"] <= bandas["pct_acum_120min"] + 1e-6).all()),
          "los acumulados son monotonos crecientes")
    v.chk("sin_acceso_vial" in "".join(bandas.columns),
          "los sin acceso vial se reportan como categoria propia, no dentro de >120 min")

    # ---------------------------------------------------------------- agregaciones
    v.seccion("agregacion ponderada por poblacion")
    v.chk(len(dep) == len(cfg.departamentos),
          f"hay una fila por departamento ({len(dep)})")
    v.chk(dist["ubigeo"].is_unique, "un registro por distrito")
    pob_dist = dist.groupby("departamento")["poblacion"].sum()
    pob_dep = dep.set_index("departamento")["poblacion"]
    dif = (pob_dist - pob_dep).abs().max()
    v.chk(bool(dif <= max(3, 0.001 * pob_dep.sum())),
          f"la poblacion de los distritos suma la del departamento (desvio max {dif:.0f})")
    v.chk(bool((dist["t_medio_pond_min"].dropna() >= 0).all()), "no hay tiempos negativos")
    v.chk(bool((dist["pct_sin_acceso_vial"].between(0, 100)).all()),
          "los porcentajes sin acceso vial estan entre 0 y 100")

    # ------------------------------------------------------------------ desigualdad
    v.seccion("desigualdad")
    g = gini["gini_tiempo_acceso"].dropna()
    v.chk(bool(g.between(0, 1).all()), f"el Gini esta en [0,1] (rango {g.min():.3f}-{g.max():.3f})")
    v.chk("TOTAL" in set(gini["ambito"]), "se reporta el Gini del ambito completo")
    for amb, c in lorenz.groupby("ambito"):
        c = c.sort_values("pct_poblacion")
        ok = (bool(np.all(np.diff(c["pct_tiempo"]) >= -1e-6))
              and abs(c["pct_tiempo"].iloc[0]) < 1e-6
              and abs(c["pct_tiempo"].iloc[-1] - 100) < 1e-6)
        v.chk(ok, f"la curva de Lorenz de {amb} es monotona y va de (0,0) a (100,100)")

    # -------------------------------------------------------------- brechas y u/r
    v.seccion("brechas criticas y contraste urbano/rural")
    v.chk(bool((brechas["ranking"].diff().dropna() == 1).all()),
          "el ranking de brechas es consecutivo")
    v.chk(len(brechas) <= int(cfg.metricas.get("top_brechas", 20)),
          "la lista de brechas respeta el tope de config.md")
    v.chk(bool(brechas["ubigeo"].isin(dist["ubigeo"]).all()),
          "los distritos de la lista existen en la agregacion distrital")
    v.chk(set(ur["urbano_rural"].dropna()) <= {"urbano", "rural"},
          "el contraste solo distingue urbano y rural")

    # -------------------------------------------------------------- cruce pobreza
    v.seccion("cruce con la segunda dimension")
    v.chk(len(rel) >= 1, "se reporta al menos un coeficiente de correlacion")
    v.chk("naturaleza" in rel.columns and bool(rel["naturaleza"].notna().all()),
          "cada fila declara la naturaleza de la relacion (el enunciado lo exige)")
    v.chk(bool(rel["naturaleza"].astype(str).str.contains("correlacional").all()),
          "se declara explicitamente que la relacion NO es causal")
    v.chk(bool(rel["spearman_rho"].between(-1, 1).all()), "Spearman esta en [-1,1]")
    v.chk(bool(rel["pearson_r"].between(-1, 1).all()), "Pearson esta en [-1,1]")

    # ------------------------------------------------------------------- LaTeX
    v.seccion("tablas LaTeX")
    for n in ("bandas_cobertura", "acceso_departamento", "brechas_criticas"):
        t = (T / f"{n}.tex").read_text(encoding="utf-8")
        v.chk("\\toprule" in t and "\\bottomrule" in t, f"{n}.tex usa booktabs")
        v.chk("textbackslash" not in t, f"{n}.tex no tiene escapes rotos")
    # Un "NaN" impreso en un informe sugiere un fallo de calculo. Cuando el valor
    # legitimamente no existe —un distrito sin ningun punto con tiempo interpretable— la
    # convencion tipografica es la raya, no el nombre interno de pandas.
    con_nan = [p.name for p in T.glob("*.tex") if "NaN" in p.read_text(encoding="utf-8")]
    v.chk(not con_nan, f"ninguna tabla imprime 'NaN' (afectadas: {con_nan or 'ninguna'})")
    # Mojibake: si alguna tabla se hubiera escrito con el encoding equivocado, las enies y
    # tildes de los nombres de distrito apareceran corrompidas.
    con_moji = [p.name for p in T.glob("*.tex")
                if any(m in p.read_text(encoding="utf-8") for m in ("Ã", "Â", "â€"))]
    v.chk(not con_moji, f"ninguna tabla tiene mojibake (afectadas: {con_moji or 'ninguna'})")

    return v.resumen()


def verificar_fase_4(cfg) -> int:
    import pandas as pd

    v = Verificador("VERIFICACION — Fase 4: dashboard Streamlit")
    P, O = cfg.processed_dir, cfg.outputs_dir
    fmt = cfg.salida.get("formato", "parquet")
    ext = "parquet" if fmt == "parquet" else "gpkg"

    # ------------------------------------------------------------------- la app
    v.seccion("la aplicacion")
    app = cfg.root / "app.py"
    v.chk(app.exists() and app.stat().st_size > 0, "existe app.py")
    if not app.exists():
        return v.resumen()
    codigo = app.read_text(encoding="utf-8")
    v.chk("@st.cache_data" in codigo, "usa @st.cache_data para la carga (lo exige el enunciado)")
    # El enunciado prohibe expresamente rutear en vivo desde el dashboard.
    v.chk("OSRMClient" not in codigo and "localhost:500" not in codigo,
          "no instancia el cliente de OSRM: solo lee archivos precomputados")
    v.chk("st.sidebar" in codigo, "tiene filtros en la barra lateral")
    v.chk("download_button" in codigo, "la tabla se puede descargar en CSV")

    # ------------------------------------------------- insumos que la app lee
    v.seccion("insumos precomputados que la app necesita")
    necesarios = [P / f"acceso_puntos.{ext}", P / f"oferta_salud.{ext}",
                  P / f"distritos.{ext}", P / "matriz_candidatos.parquet",
                  O / "acceso_por_distrito.csv", O / "candidatos_ascenso.csv",
                  O / "data_quality_oferta.csv"]
    for p in necesarios:
        v.chk(p.exists() and p.stat().st_size > 0, f"existe: {p.name}")
    if v.fallos:
        return v.resumen()

    # -------------------------------------------- coherencia del simulador
    v.seccion("matriz del simulador de escenarios")
    leer = gpd.read_parquet if ext == "parquet" else gpd.read_file
    acceso = leer(P / f"acceso_puntos.{ext}")
    oferta = leer(P / f"oferta_salud.{ext}")
    mc = pd.read_parquet(P / "matriz_candidatos.parquet")
    cand = pd.read_csv(O / "candidatos_ascenso.csv", dtype={"cod_ipress": str})

    v.chk(len(mc) > 0, f"la matriz de candidatos no esta vacia ({len(mc):,} pares)")
    v.chk(bool(mc["ccpp_id"].isin(acceso["ccpp_id"]).all()),
          "todos los origenes de la matriz estan en la muestra de demanda")
    v.chk(bool(mc["cod_ipress"].astype(str).isin(cand["cod_ipress"].astype(str)).all()),
          "todos los destinos de la matriz son candidatos declarados")
    v.chk(bool(cand["categoria"].isin(cfg.categorias_ascendibles).all()),
          f"todos los candidatos son de categoria {cfg.categorias_ascendibles}")
    aptos = set(oferta.loc[oferta["apto_para_ruteo"], "cod_ipress"].astype(str))
    v.chk(bool(cand["cod_ipress"].astype(str).isin(aptos).all()),
          "todos los candidatos tienen coordenada valida")
    v.chk(bool((mc["duracion_seg"].dropna() >= 0).all()), "no hay duraciones negativas")

    # La poda debe conservar SOLO pares que mejorarian el acceso actual: esa es su
    # definicion, y si se rompiera el simulador reportaria ganancias inexistentes.
    act = acceso[["ccpp_id", "t_car", "alc_car", "fuera_de_red"]].copy()
    j = mc.merge(act, on="ccpp_id", how="left")
    j["sin_acceso"] = (~j["alc_car"].fillna(False)) | j["fuera_de_red"].fillna(False)
    malos = j[~j["sin_acceso"] & (j["duracion_seg"] / 60 >= j["t_car"])]
    v.chk(len(malos) == 0,
          f"la poda solo dejo pares que mejoran el acceso actual ({len(malos)} inconsistentes)")
    v.info(f"{mc['cod_ipress'].nunique()} candidatos con al menos un punto que mejorarian")

    # --------------------------------------------- la app arranca sin excepcion
    v.seccion("ejecucion de la app")
    try:
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(app), default_timeout=240)
        at.run()
        v.chk(not at.exception,
              "la app se ejecuta sin excepciones"
              + (f" ({at.exception[0].message[:90]})" if at.exception else ""))
        if not at.exception:
            v.chk(len(at.metric) >= 4, f"renderiza la cabecera de KPIs ({len(at.metric)} metricas)")
            v.chk(len(at.dataframe) >= 2, f"renderiza las tablas ({len(at.dataframe)})")
            v.chk(len(at.multiselect) >= 5,
                  f"tiene los filtros y el simulador ({len(at.multiselect)} multiselect)")
            sim = [w for w in at.multiselect if "ascender" in (w.label or "").lower()]
            v.chk(bool(sim) and len(sim[0].options) > 0,
                  f"el simulador ofrece candidatos ({len(sim[0].options) if sim else 0})")
            # Seleccion vacia: el enunciado exige que no reviente.
            dep = [w for w in at.multiselect if (w.label or "") == "Departamento"]
            if dep:
                dep[0].set_value([])
                at.run()
                v.chk(not at.exception and len(at.warning) > 0,
                      "con seleccion vacia avisa y se detiene sin romperse")
    except ImportError:
        v.info("streamlit.testing no disponible; se omite la ejecucion de la app")

    return v.resumen()


def verificar_fase_5(cfg) -> int:
    v = Verificador("VERIFICACION — Fase 5: informe LaTeX")
    inf = cfg.raw.get("informe", {})
    tex = cfg.root / inf.get("fuente", "report/main.tex")
    pdf = cfg.root / inf.get("salida", "report/main.pdf")

    # ------------------------------------------------------------------ entregables
    v.seccion("entregables")
    v.chk(tex.exists() and tex.stat().st_size > 0, "existe la fuente main.tex")
    v.chk(pdf.exists() and pdf.stat().st_size > 0, "existe el PDF compilado main.pdf")
    if not (tex.exists() and pdf.exists()):
        return v.resumen()
    v.info(f"tex {tex.stat().st_size / 1024:.0f} KB · pdf {pdf.stat().st_size / 1e6:.2f} MB")

    fuente = tex.read_text(encoding="utf-8")

    # ------------------------------------------------------- estructura obligatoria
    v.seccion("estructura que exige el enunciado")
    secciones = {
        "Abstract": r"\begin{abstract}",
        "Introduccion y planteamiento": "Introducción y planteamiento",
        "Fuentes de datos": "Fuentes de datos",
        "Metodologia": "Metodología",
        "Resultados": "section{Resultados}",
        "Discusion": "section{Discusión}",
        "Limitaciones": "section{Limitaciones}",
        "Conclusiones y recomendaciones": "Conclusiones y recomendaciones",
        "Referencias": "thebibliography",
    }
    for nombre, marca in secciones.items():
        v.chk(marca in fuente, f"tiene la seccion: {nombre}")

    # ------------------------------------------------------------------- contenido
    v.seccion("figuras y tablas generadas por el pipeline")
    inputs = [l.split("{", 1)[1].split("}", 1)[0]
              for l in fuente.splitlines() if l.strip().startswith("\\input{")]
    graficos = [l.rsplit("{", 1)[1].split("}", 1)[0]
                for l in fuente.splitlines() if "\\includegraphics" in l]
    v.chk(len(inputs) >= 3,
          f"incorpora al menos 3 tablas generadas por el pipeline ({len(inputs)})")
    v.chk(len(graficos) >= 3, f"incorpora al menos 3 figuras ({len(graficos)})")
    for rel in inputs:
        v.chk((tex.parent / rel).exists(), f"la tabla existe en disco: {rel}")
    for rel in graficos:
        v.chk((tex.parent / "figures" / rel).exists(), f"la figura existe en disco: {rel}")
    v.chk(all(g.endswith(".pdf") for g in graficos),
          "todas las figuras del informe son PDF vectorial")

    # El enunciado exige tablas generadas programaticamente, no tecleadas. La marca es que
    # entren con \input desde report/tablas/, que es lo que produce metrics.exportar_latex.
    v.chk(all(r.startswith("tablas/") for r in inputs),
          "las tablas se incorporan desde report/tablas/, no escritas a mano")

    # -------------------------------------------------------------------- el PDF
    v.seccion("el PDF compilado")
    try:
        from pypdf import PdfReader
        r = PdfReader(str(pdf))
        n = len(r.pages)
        v.chk(8 <= n <= 12, f"tiene entre 8 y 12 paginas ({n})")
        texto = "".join((p.extract_text() or "") for p in r.pages)
        v.chk(len(texto) > 10000, f"el PDF contiene texto extraible ({len(texto):,} caracteres)")
        for clave in ("hora dorada", "Limitaciones", "resolutiv"):
            v.chk(clave.lower() in texto.lower(), f"el PDF menciona '{clave}'")
        v.chk("??" not in texto, "no hay referencias cruzadas sin resolver ('??')")
        v.chk("NaN" not in texto, "el PDF no imprime 'NaN' en ninguna tabla")
        v.chk(not any(m in texto for m in ("Ã", "Â", "â€")),
              "el PDF no tiene mojibake en los nombres acentuados")
    except ImportError:
        v.info("pypdf no disponible; se omiten las comprobaciones sobre el PDF")

    # ------------------------------------------------------------ log de compilacion
    v.seccion("log de compilacion")
    logtex = pdf.with_suffix(".log")
    if logtex.exists():
        txt = logtex.read_text(encoding="utf-8", errors="replace")
        v.chk("! LaTeX Error" not in txt and "! Undefined" not in txt,
              "la compilacion no arrojo errores de LaTeX")
        v.chk("LaTeX Warning: Reference" not in txt,
              "no hay referencias sin definir")
    else:
        v.info("no se conservo el log de compilacion")

    return v.resumen()


VERIFICADORES = {1: verificar_fase_1, 2: verificar_fase_2, 3: verificar_fase_3,
                 4: verificar_fase_4, 5: verificar_fase_5}


def main() -> int:
    p = argparse.ArgumentParser(description="Verifica los productos de una fase del pipeline")
    p.add_argument("--phase", type=int, default=1, choices=sorted(VERIFICADORES))
    args = p.parse_args()
    return VERIFICADORES[args.phase](load_config())


if __name__ == "__main__":
    raise SystemExit(main())
