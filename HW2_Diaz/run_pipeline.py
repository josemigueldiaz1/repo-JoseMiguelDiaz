

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import acquisition, demand, export, io_utils, supply  # noqa: E402
from src.config import load_config  # noqa: E402

log = logging.getLogger("hw2")


# --------------------------------------------------------------------------- logging
def configurar_logging(logs_dir: Path, fase: int, verboso: bool = False) -> Path:
    """
    Log simultaneo a archivo y a consola.

    El enunciado pide explicitamente que el pipeline muestre progreso: "corridas
    silenciosas de 40 minutos son inaceptables". El archivo queda como evidencia de
    ejecucion, que tambien es un entregable.
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    archivo = logs_dir / f"fase{fase}_{datetime.now():%Y%m%d_%H%M%S}.log"
    fmt = logging.Formatter("%(asctime)s [%(levelname)-7s] %(message)s", "%H:%M:%S")

    raiz = logging.getLogger()
    raiz.setLevel(logging.DEBUG if verboso else logging.INFO)
    raiz.handlers.clear()

    fh = logging.FileHandler(archivo, encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
    raiz.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    raiz.addHandler(sh)

    # Silencia el ruido de las librerias de red.
    for ruidoso in ("urllib3", "fiona", "rasterio", "matplotlib", "pyogrio"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
    return archivo


def banner(texto: str) -> None:
    log.info("")
    log.info("=" * 70)
    log.info(texto)
    log.info("=" * 70)


def asegurar_osrm(cfg) -> None:
    """
    Levanta los contenedores de OSRM si estan detenidos.

    Los contenedores de Docker no arrancan solos tras reiniciar la maquina, y sin ellos la
    Fase 2 no puede correr. Como el objetivo es que pulsar "play" baste, el pipeline los
    arranca por su cuenta en vez de exigir que el usuario recuerde el comando.

    Solo hace `docker start` sobre contenedores que YA existen: no construye grafos ni crea
    nada. Si el propio Docker no responde, no se intenta adivinar: se avisa con el paso
    concreto que falta.
    """
    import subprocess

    import requests

    conf = cfg.ruteo.get("osrm", {})
    if not conf:
        return

    prueba = "-77.0300,-12.0464"  # Lima

    def responde(url: str) -> bool:
        try:
            r = requests.get(f"{url}/nearest/v1/driving/{prueba}", timeout=8)
            return r.ok and r.json().get("code") == "Ok"
        except Exception:  # noqa: BLE001
            return False

    caidos = {p: c for p, c in conf.items() if not responde(c["url"])}
    if not caidos:
        return

    log.info("  %d perfil(es) de OSRM no responden; intentando arrancarlos...", len(caidos))
    try:
        subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                       capture_output=True, timeout=30, check=True)
    except Exception:  # noqa: BLE001
        log.error("  El motor de Docker no responde. Abre Docker Desktop, espera a que diga "
                  "'Engine running' y vuelve a ejecutar.")
        return

    for perfil in caidos:
        try:
            r = subprocess.run(["docker", "start", f"osrm-{perfil}"],
                               capture_output=True, timeout=60, text=True)
            if r.returncode != 0:
                log.warning("  no se pudo arrancar osrm-%s: %s. Compila el grafo con: "
                            ".\\scripts\\osrm.ps1 build %s", perfil,
                            (r.stderr or "").strip()[:120], perfil)
        except Exception as e:  # noqa: BLE001
            log.warning("  fallo al arrancar osrm-%s: %s", perfil, e)

    # Los contenedores tardan unos segundos en cargar el grafo en memoria.
    for intento in range(1, 11):
        time.sleep(3)
        pendientes = [p for p, c in caidos.items() if not responde(c["url"])]
        if not pendientes:
            log.info("  OSRM listo: los %d perfiles responden", len(conf))
            return
        if intento == 10:
            log.warning("  siguen sin responder: %s. La Fase 2 los omitira.",
                        ", ".join(pendientes))


def intentar(descripcion: str, fn, *args, **kwargs):
    """
    Ejecuta un paso accesorio (figura, mapa) sin que su fallo tumbe el pipeline.

    Motivo concreto: si el usuario tiene una figura abierta en el visor de imagenes de
    Windows, el archivo queda bloqueado y matplotlib falla con
    `OSError: [Errno 22] Invalid argument` al intentar sobrescribirla. Antes eso abortaba
    la corrida entera en el ultimo paso, despues de haber hecho ya todo el trabajo pesado.

    Solo se protege lo prescindible: si falla la descarga, la validacion o el guardado de
    los datasets, el pipeline debe detenerse, porque el resultado seria incorrecto.
    """
    try:
        return fn(*args, **kwargs)
    except OSError as e:
        log.error("  NO se pudo generar %s: %s", descripcion, e)
        log.error("  Suele significar que el archivo esta abierto en otro programa "
                  "(visor de imagenes, navegador, QGIS). Cierralo y vuelve a correr.")
        log.error("  El resto de la fase SI se completo; solo falta este archivo.")
        return None


# ============================================================================== FASE 1
def fase_1(args) -> int:
    """
    Fase 1 — Adquisicion y validacion.

    Produce:
        data/processed/oferta_salud.parquet     IPRESS del ambito, validadas y clasificadas
        data/processed/demanda_ccpp.parquet     centros poblados con poblacion imputada
        data/processed/distritos.parquet        limites distritales del ambito
        data/outputs/data_quality_oferta.{csv,md}
        data/outputs/resumen_fase1.csv
        data/outputs/comparacion_temporal_renipress.csv   (innovacion)
        report/figures/fase1_ambito.png, fase1_calidad.png
        data/outputs/mapa_validacion_fase1.html           (control visual)
    """
    t0 = time.perf_counter()
    cfg = load_config()

    banner("HW2 — FASE 1 · Adquisicion y validacion de datos")
    log.info("Departamentos : %s", ", ".join(
        f"{d} ({cfg.region_natural.get(d, '?')})" for d in cfg.departamentos))
    log.info("Resolutivas   : %s", ", ".join(cfg.categorias_resolutivas))
    log.info("Estados activos: %s", ", ".join(cfg.estados_activos))
    log.info("Formato salida: %s", cfg.salida.get("formato", "parquet"))

    # ---------------------------------------------------------------- 1.1 adquisicion
    rutas = acquisition.adquirir_todo(
        cfg, con_osm=args.with_osm, con_pop_alta_res=args.hi_res_pop,
        forzar=args.force_download)

    # ------------------------------------------------------------------- 1.2 distritos
    banner("FASE 1.2 — Limites distritales")
    import geopandas as gpd

    shp_dist = acquisition.buscar_shapefile(rutas["distritos_dir"])
    distritos_nac = gpd.read_file(shp_dist, engine="pyogrio")
    if distritos_nac.crs is None:
        distritos_nac = distritos_nac.set_crs("EPSG:4326")
    elif distritos_nac.crs.to_epsg() != 4326:
        distritos_nac = distritos_nac.to_crs("EPSG:4326")
    log.info("  %d distritos a nivel nacional", len(distritos_nac))

    distritos = distritos_nac[
        distritos_nac["DEPARTAMEN"].str.upper().isin(cfg.departamentos)
    ].copy()
    log.info("  %d distritos en el ambito", len(distritos))
    log.info("  por departamento: %s",
             distritos.groupby("DEPARTAMEN").size().to_dict())

    # ---------------------------------------------------------------------- 1.3 oferta
    oferta, reporte = supply.construir_oferta(rutas["renipress"], distritos_nac, cfg)

    # --------------------------------------------------------------------- 1.4 demanda
    banner("FASE 1.4 — Demanda: centros poblados y poblacion")
    shp_ccpp = acquisition.buscar_shapefile(rutas["centros_poblados_dir"])
    # Si se pidio (y se logro bajar) el raster de alta resolucion, tiene prioridad.
    raster_pop = rutas.get("poblacion_raster_alta_res") or rutas["poblacion_raster"]
    log.info("  raster de poblacion en uso: %s", raster_pop.name)
    demanda_gdf = demand.construir_demanda(shp_ccpp, raster_pop, distritos, cfg)

    # ------------------------------------------------------------------- 1.5 guardado
    banner("FASE 1.5 — Escritura de resultados")
    io_utils.guardar_geo(oferta, cfg.processed_dir, "oferta_salud", cfg)
    io_utils.guardar_geo(demanda_gdf, cfg.processed_dir, "demanda_ccpp", cfg)
    io_utils.guardar_geo(distritos, cfg.processed_dir, "distritos", cfg)

    from src.validation import exportar_reporte
    exportar_reporte(reporte, cfg.outputs_dir, "oferta")

    # ---------------------------------------------------- 1.6 innovacion: temporal
    banner("FASE 1.6 — Innovacion: rotacion temporal del registro")
    comp = supply.comparar_cortes_temporales(
        rutas["renipress"], rutas.get("renipress_anterior"), cfg)
    if comp is not None:
        io_utils.guardar_tabla(comp, cfg.outputs_dir, "comparacion_temporal_renipress")

    # ------------------------------------------------------------------ 1.7 resumen
    banner("FASE 1.7 — Resumen del ambito")
    import pandas as pd

    filas = []
    for dep in cfg.departamentos:
        o = oferta[oferta["departamento"].str.upper() == dep]
        d = demanda_gdf[demanda_gdf["departamento"].str.upper() == dep]
        res_aptas = o[o["es_resolutiva"] & o["apto_para_ruteo"]]
        filas.append({
            "departamento": dep,
            "region_natural": cfg.region_natural.get(dep, ""),
            "distritos": int((distritos["DEPARTAMEN"].str.upper() == dep).sum()),
            "centros_poblados": len(d),
            "centros_sin_poblacion_raster": int((~d["tiene_poblacion_raster"]).sum())
            if "tiene_poblacion_raster" in d.columns else None,
            "poblacion_total": round(float(d["poblacion"].sum())),
            "poblacion_urbana": round(float(d.loc[d["es_urbano"], "poblacion"].sum())),
            "poblacion_rural": round(float(d.loc[~d["es_urbano"], "poblacion"].sum())),
            "ipress_total": len(o),
            "ipress_coord_valida": int(o["coord_valida"].sum()),
            "ipress_resolutivas": int(o["es_resolutiva"].sum()),
            "ipress_resolutivas_aptas": len(res_aptas),
            "habitantes_por_resolutiva": round(
                float(d["poblacion"].sum()) / len(res_aptas)) if len(res_aptas) else None,
        })
    resumen = pd.DataFrame(filas)
    io_utils.guardar_tabla(resumen, cfg.outputs_dir, "resumen_fase1")
    log.info("\n%s", resumen.to_string(index=False))

    # ------------------------------------------------------------------ 1.8 figuras
    banner("FASE 1.8 — Figuras y mapa de control")
    intentar("fase1_ambito.png", export.figura_ambito,
             distritos, oferta, demanda_gdf, cfg, cfg.figuras_dir / "fase1_ambito.png")
    intentar("fase1_calidad.png", export.figura_calidad,
             reporte.to_frame(), cfg.figuras_dir / "fase1_calidad.png")
    if not args.skip_map:
        intentar("mapa_validacion_fase1.html", export.mapa_validacion,
                 oferta, demanda_gdf, distritos, cfg,
                 cfg.outputs_dir / "mapa_validacion_fase1.html")
    else:
        log.info("  mapa interactivo omitido (--skip-map)")

    # -------------------------------------------------------------------- cierre
    dt = time.perf_counter() - t0
    banner(f"FASE 1 COMPLETA en {dt / 60:.1f} min")
    log.info("Oferta            : %d IPRESS (%d resolutivas aptas para ruteo)",
             len(oferta), int((oferta["es_resolutiva"] & oferta["apto_para_ruteo"]).sum()))
    log.info("Demanda           : %d centros poblados · %.0f habitantes",
             len(demanda_gdf), float(demanda_gdf["poblacion"].sum()))
    log.info("Reglas con hallazgos: %d/%d",
             int((reporte.to_frame()["registros_marcados"] > 0).sum()), len(reporte.resultados))
    log.info("Salidas en        : %s", cfg.processed_dir)
    log.info("                    %s", cfg.outputs_dir)

    n_dem = len(demanda_gdf)
    tope = int(cfg.ruteo.get("max_puntos_demanda", 5000))
    if n_dem > tope:
        log.warning("AVISO para la Fase 2: hay %d puntos de demanda y el tope del enunciado "
                    "es %d. Habra que aplicar el muestreo '%s' declarado en config.md.",
                    n_dem, tope, cfg.ruteo.get("metodo_muestreo", "?"))
    return 0


# ============================================================================== FASE 2
def fase_2(args) -> int:
    """
    Fase 2 — Ruteo sobre red vial real y tiempos de viaje.

    Produce:
        data/processed/acceso_puntos.parquet    un registro por punto de demanda, con el
                                                tiempo al resolutivo mas cercano en cada modo
        data/processed/matriz_car.parquet       matriz completa origen x resolutiva (Fase 4)
        data/outputs/resumen_fase2.csv          tiempos por departamento
        data/outputs/comparacion_modos.csv      auto vs pie vs bici
        data/outputs/acceso_urbano_pie.csv      urbanos a pie, cualquier categoria
        data/outputs/snapping_diagnostico.csv   enganche a la red
        data/outputs/sensibilidad_umbral_snap.csv
        report/figures/fase2_*.png
    """
    t0 = time.perf_counter()
    cfg = load_config()

    import geopandas as gpd
    import pandas as pd

    from src import routing as rt

    banner("HW2 — FASE 2 · Ruteo y tiempos de viaje")

    # -------------------------------------------------------------- 2.1 insumos
    banner("FASE 2.1 — Insumos de la Fase 1")
    oferta = gpd.read_parquet(cfg.processed_dir / "oferta_salud.parquet")
    demanda = gpd.read_parquet(cfg.processed_dir / "demanda_ccpp.parquet")
    resolutivas = oferta[oferta["es_resolutiva"] & oferta["apto_para_ruteo"]].copy()
    toda_oferta = oferta[oferta["apto_para_ruteo"]].copy()
    log.info("  demanda      : %d centros poblados", len(demanda))
    log.info("  resolutivas  : %d aptas para ruteo", len(resolutivas))
    log.info("  oferta total : %d aptas para ruteo (cualquier categoria)", len(toda_oferta))
    if resolutivas.empty:
        log.error("No hay establecimientos resolutivos aptos: la Fase 2 no puede correr.")
        return 1

    # --------------------------------------------------- 2.2 perfiles disponibles
    banner("FASE 2.2 — Servidores OSRM disponibles")
    asegurar_osrm(cfg)
    conf_osrm = cfg.ruteo.get("osrm", {})
    clientes: dict[str, rt.OSRMClient] = {}
    for perfil in cfg.ruteo.get("perfiles", ["car"]):
        c = conf_osrm.get(perfil)
        if not c:
            log.warning("  %-5s no esta declarado en [ruteo.osrm] de config.md", perfil)
            continue
        cli = rt.OSRMClient(base_url=c["url"],
                            chunk_origenes=int(cfg.ruteo.get("chunk_origenes", 200)),
                            chunk_destinos=int(cfg.ruteo.get("chunk_destinos", 300)),
                            timeout=int(cfg.ruteo.get("timeout_seg", 120)))
        if cli.disponible():
            clientes[perfil] = cli
            log.info("  %-5s DISPONIBLE en %s", perfil, c["url"])
        else:
            log.warning("  %-5s no responde en %s; se omite este modo "
                        "(levantalo con: .\\scripts\\osrm.ps1 serve %s)", perfil, c["url"], perfil)
    if "car" not in clientes:
        log.error("El perfil 'car' es obligatorio y no responde. "
                  "Levantalo con: .\\scripts\\osrm.ps1 serve car")
        return 1

    # ------------------------------------------------------------- 2.3 muestreo
    banner("FASE 2.3 — Muestreo de la demanda")
    muestra = rt.muestrear_demanda(demanda, cfg).reset_index(drop=True)

    # ------------------------------------------------- 2.4 snapping y fuera de red
    banner("FASE 2.4 — Enganche a la red vial (snapping)")
    diag = []
    snap_car = rt.snap_con_cache(clientes["car"], muestra, "car", "demanda",
                                 cfg.cache_dir, forzar=args.force_routing)
    diag.append(rt.diagnostico_snapping(snap_car, "demanda-car"))
    snap_of = rt.snap_con_cache(clientes["car"], resolutivas, "car", "oferta",
                                cfg.cache_dir, col_id="cod_ipress", forzar=args.force_routing)
    diag.append(rt.diagnostico_snapping(snap_of, "oferta-car"))

    muestra = rt.clasificar_cobertura_red(muestra, snap_car, cfg)
    sens = rt.sensibilidad_umbral(muestra, cfg)
    io_utils.guardar_tabla(sens, cfg.outputs_dir, "sensibilidad_umbral_snap")
    io_utils.guardar_tabla(pd.DataFrame(diag), cfg.outputs_dir, "snapping_diagnostico")

    # ------------------------------------------------- 2.5 matrices y mas cercano
    banner("FASE 2.5 — Matriz completa origen x resolutiva, por modo")
    mejores: dict[str, pd.DataFrame] = {}
    for perfil, cli in clientes.items():
        m = rt.matriz_con_cache(cli, muestra, resolutivas, perfil, cfg.cache_dir,
                                forzar=args.force_routing)
        if perfil == "car":
            # La matriz completa del perfil auto se versiona: el simulador de escenarios de
            # la Fase 4 la necesita, y el enunciado exige que el dashboard corra sin motor
            # de ruteo levantado.
            m.to_parquet(cfg.processed_dir / "matriz_car.parquet", index=False)
            log.info("  matriz completa guardada en data/processed/matriz_car.parquet")
        mejores[perfil] = rt.mas_cercano(m)

    # -------------------------------------------------- 2.6 comparacion de modos
    banner("FASE 2.6 — Comparacion entre modos")
    if len(mejores) > 1:
        acceso, comp = rt.comparar_modos(mejores, muestra)
        io_utils.guardar_tabla(comp, cfg.outputs_dir, "comparacion_modos")
    else:
        log.warning("  solo hay un perfil disponible ('car'); la comparacion entre modos "
                    "queda pendiente de levantar foot y bike")
        acceso, comp = rt.comparar_modos(mejores, muestra)

    # ------------------------------------- 2.7 matriz de candidatos a ascenso
    # La necesita el simulador de escenarios de la Fase 4: para responder "cuanto ganariamos
    # si ascendemos este puesto I-3 a resolutivo" hay que conocer el tiempo desde cada punto
    # de demanda HASTA ese puesto, y eso no esta en la matriz de resolutivos.
    banner("FASE 2.7 — Matriz de candidatos a ascenso (simulador de la Fase 4)")
    candidatos = oferta[oferta["categoria"].isin(cfg.categorias_ascendibles)
                        & oferta["estado"].isin(cfg.estados_activos)
                        & oferta["apto_para_ruteo"]].copy()
    log.info("  %d establecimientos %s activos y mapeables",
             len(candidatos), "/".join(cfg.categorias_ascendibles))
    if len(candidatos):
        m_cand = rt.matriz_con_cache(clientes["car"], muestra, candidatos, "car_candidatos",
                                     cfg.cache_dir, forzar=args.force_routing)
        # --- poda ---
        # Ascender un establecimiento solo mejora a los puntos para los que quedaria MAS
        # CERCA que su resolutivo actual. El resto de pares no puede cambiar el resultado del
        # simulador, asi que guardarlos es peso muerto en el repositorio.
        actual = mejores["car"][["ccpp_id", "t_min_seg", "alcanzable"]].rename(
            columns={"t_min_seg": "t_actual_seg"})
        m_cand = m_cand.merge(actual, on="ccpp_id", how="left")
        antes = len(m_cand)
        util = (m_cand["duracion_seg"].notna()
                & (~m_cand["alcanzable"].fillna(False)
                   | (m_cand["duracion_seg"] < m_cand["t_actual_seg"])))
        m_cand = m_cand.loc[util, ["ccpp_id", "cod_ipress", "duracion_seg",
                                   "distancia_m", "perfil"]]
        m_cand.to_parquet(cfg.processed_dir / "matriz_candidatos.parquet", index=False)
        peso = (cfg.processed_dir / "matriz_candidatos.parquet").stat().st_size / 1e6
        log.info("  poda: %d -> %d pares (%.1f%%); solo los que mejorarian el acceso actual",
                 antes, len(m_cand), 100 * len(m_cand) / antes if antes else 0)
        log.info("  guardado  matriz_candidatos.parquet  %.1f MB", peso)
        io_utils.guardar_tabla(
            candidatos[["cod_ipress", "nombre", "categoria", "institucion", "departamento",
                        "provincia", "distrito", "lon", "lat"]],
            cfg.outputs_dir, "candidatos_ascenso")
    else:
        log.warning("  no hay candidatos a ascenso; el simulador quedara vacio")

    # ------------------------------------------------ 2.8 acceso urbano a pie
    banner("FASE 2.8 — Acceso urbano caminando (cualquier categoria)")
    if "foot" in clientes:
        pie = rt.acceso_urbano_a_pie(clientes["foot"], muestra, toda_oferta, cfg,
                                     forzar=args.force_routing)
        if pie is not None:
            io_utils.guardar_tabla(pie.drop(columns=["geometry"], errors="ignore"),
                                   cfg.outputs_dir, "acceso_urbano_pie")
    else:
        log.warning("  el perfil 'foot' no esta disponible; se omite el analisis a pie")

    # ---------------------------------------------------------- 2.8 consolidado
    banner("FASE 2.9 — Consolidado por punto de demanda")
    acceso = acceso.merge(
        muestra[["ccpp_id", "ubigeo", "distrito", "provincia", "lon", "lat",
                 "snap_m", "fuera_de_red", "es_urbano"]],
        on="ccpp_id", how="left")
    io_utils.guardar_geo(
        gpd.GeoDataFrame(acceso,
                         geometry=gpd.points_from_xy(acceso["lon"], acceso["lat"]),
                         crs=cfg.salida.get("crs_trabajo", "EPSG:4326")),
        cfg.processed_dir, "acceso_puntos", cfg)

    # --------------------------------------------------------- 2.9 resumen
    banner("FASE 2.10 — Resumen del acceso por departamento")
    filas = []
    for dep in cfg.departamentos:
        g = acceso[acceso["departamento"].str.upper() == dep]
        if g.empty:
            continue
        alc = g["alc_car"].fillna(False)
        dentro = alc & (~g["fuera_de_red"].fillna(False))
        pob = float(g["peso_muestral"].sum())
        f = {
            "departamento": dep,
            "region_natural": cfg.region_natural.get(dep, ""),
            "puntos": len(g),
            "poblacion": round(pob),
            "pct_inalcanzable_por_carretera": round(100 * float((~alc).mean()), 1),
            "pct_pob_fuera_de_red": round(
                100 * float(g.loc[g["fuera_de_red"].fillna(False), "peso_muestral"].sum()) / pob, 1)
            if pob else 0.0,
            # Con TODOS los puntos alcanzables (optimista: ignora el tramo fuera de red)
            "t_mediana_todos_min": round(float(g.loc[alc, "t_car"].median()), 1)
            if alc.any() else None,
            # Solo con los que la red vial sirve de verdad
            "t_mediana_en_red_min": round(float(g.loc[dentro, "t_car"].median()), 1)
            if dentro.any() else None,
            "t_p90_en_red_min": round(float(g.loc[dentro, "t_car"].quantile(0.9)), 1)
            if dentro.any() else None,
        }
        filas.append(f)
    resumen = pd.DataFrame(filas)
    io_utils.guardar_tabla(resumen, cfg.outputs_dir, "resumen_fase2")
    log.info("\n%s", resumen.to_string(index=False))

    # ---------------------------------------------------------- 2.10 figuras
    banner("FASE 2.11 — Figuras")
    intentar("fase2_acceso.png", export.figura_acceso,
             acceso, cfg, cfg.figuras_dir / "fase2_acceso.png")
    intentar("fase2_snapping.png", export.figura_snapping,
             acceso, sens, cfg, cfg.figuras_dir / "fase2_snapping.png")
    if len(mejores) > 1:
        intentar("fase2_modos.png", export.figura_modos,
                 acceso, list(mejores), cfg, cfg.figuras_dir / "fase2_modos.png")

    dt = time.perf_counter() - t0
    banner(f"FASE 2 COMPLETA en {dt / 60:.1f} min")
    total_pet = sum(c.n_peticiones for c in clientes.values())
    log.info("Modos calculados  : %s", ", ".join(mejores))
    log.info("Peticiones a OSRM : %d · %.1fs de red",
             total_pet, sum(c.segundos_red for c in clientes.values()))
    log.info("Salidas en        : %s", cfg.processed_dir)
    log.info("                    %s", cfg.outputs_dir)
    return 0


# ============================================================================== FASE 3
def fase_3(args) -> int:
    """
    Fase 3 — Metricas de decision a partir de los tiempos de viaje.

    Produce, en CSV y ademas como tablas LaTeX listas para el informe:
        bandas de cobertura (30/60/120 min y sin acceso vial)
        agregacion ponderada por poblacion a distrito, provincia y departamento
        lista de brechas criticas
        Gini y curva de Lorenz del tiempo de acceso
        contraste urbano / rural
        cruce del acceso con la tasa de pobreza distrital
    """
    t0 = time.perf_counter()
    cfg = load_config()

    import geopandas as gpd
    import pandas as pd

    from src import metrics as mt

    banner("HW2 — FASE 3 · Construccion de metricas")

    ext = "parquet" if cfg.salida.get("formato", "parquet") == "parquet" else "gpkg"
    leer = gpd.read_parquet if ext == "parquet" else gpd.read_file
    acceso = leer(cfg.processed_dir / f"acceso_puntos.{ext}")
    log.info("  puntos de demanda: %d · poblacion representada: %.0f",
             len(acceso), float(acceso["peso_muestral"].sum()))
    val = (acceso["alc_car"].fillna(False) & ~acceso["fuera_de_red"].fillna(False)
           & acceso["t_car"].notna())
    log.info("  con tiempo interpretable: %d (%.1f%%)", int(val.sum()),
             100 * val.mean())

    tex = cfg.root / "report" / "tablas"

    # --------------------------------------------------------- 3.1 bandas
    banner("FASE 3.1 — Bandas de cobertura")
    bandas_dep = mt.bandas_cobertura(acceso, cfg, por="departamento")
    bandas_tot = mt.bandas_cobertura(acceso, cfg, por=None)
    bandas = pd.concat([bandas_dep, bandas_tot], ignore_index=True)
    io_utils.guardar_tabla(bandas, cfg.outputs_dir, "bandas_cobertura")
    mt.exportar_latex(
        bandas, tex / "bandas_cobertura.tex",
        "Cobertura poblacional por banda de tiempo al establecimiento resolutivo mas cercano",
        "tab:bandas",
        {"grupo": "Ambito", "poblacion_total": "Poblacion",
         "pct_acum_30min": r"$\leq$30 min (\%)", "pct_acum_60min": r"$\leq$60 min (\%)",
         "pct_acum_120min": r"$\leq$120 min (\%)",
         "pct_sin_acceso_vial": r"Sin acceso vial (\%)"})

    # ------------------------------------------------- 3.2 agregacion por nivel
    banner("FASE 3.2 — Agregacion ponderada por poblacion")
    niveles = {}
    for nivel in cfg.metricas.get("niveles_agregacion", ["distrito", "provincia", "departamento"]):
        niveles[nivel] = mt.agregar_por_nivel(acceso, nivel)
        io_utils.guardar_tabla(niveles[nivel], cfg.outputs_dir, f"acceso_por_{nivel}")
    mt.exportar_latex(
        niveles["departamento"], tex / "acceso_departamento.tex",
        "Tiempo de acceso ponderado por poblacion, por departamento", "tab:acceso-dep",
        {"departamento": "Departamento", "poblacion": "Poblacion",
         "t_medio_pond_min": "Media (min)", "t_p50_pond_min": "Mediana (min)",
         "t_p90_pond_min": "p90 (min)", "pct_sin_acceso_vial": r"Sin acceso vial (\%)"})

    # ------------------------------------------------------- 3.3 brechas criticas
    banner("FASE 3.3 — Brechas criticas")
    brechas = mt.brechas_criticas(niveles["distrito"], cfg)
    io_utils.guardar_tabla(brechas, cfg.outputs_dir, "brechas_criticas")
    mt.exportar_latex(
        brechas, tex / "brechas_criticas.tex",
        "Distritos con peor acceso a capacidad resolutiva. Una raya en la columna de tiempo "
        "medio indica que el distrito no tiene ningun punto de demanda con tiempo "
        "interpretable: la red vial no lo sirve en absoluto",
        "tab:brechas",
        {"ranking": "\\#", "distrito": "Distrito", "departamento": "Departamento",
         "poblacion": "Poblacion", "pct_sin_acceso_vial": r"Sin acceso vial (\%)",
         "t_medio_pond_min": "Media (min)"})

    # ---------------------------------------------------------- 3.4 desigualdad
    banner("FASE 3.4 — Desigualdad del acceso")
    gini, curvas = mt.desigualdad(acceso, cfg)
    io_utils.guardar_tabla(gini, cfg.outputs_dir, "desigualdad_gini")
    io_utils.guardar_tabla(curvas, cfg.outputs_dir, "curva_lorenz")
    # El Gini pide 3 decimales pero los minutos solo 1, y `float_format` es unico para toda
    # la tabla: se preformatea la columna de minutos como texto.
    gini_tex = gini.copy()
    gini_tex["t_medio_pond_min"] = gini_tex["t_medio_pond_min"].map(lambda v: f"{v:.1f}")
    mt.exportar_latex(
        gini_tex, tex / "desigualdad.tex",
        "Desigualdad del tiempo de acceso (Gini ponderado por poblacion)", "tab:gini",
        {"ambito": "Ambito", "poblacion": "Poblacion",
         "gini_tiempo_acceso": "Gini", "t_medio_pond_min": "Media (min)"},
        decimales="%.3f")

    # ------------------------------------------------------ 3.5 urbano / rural
    banner("FASE 3.5 — Contraste urbano / rural")
    ur = mt.contraste_urbano_rural(acceso, cfg)
    io_utils.guardar_tabla(ur, cfg.outputs_dir, "contraste_urbano_rural")
    mt.exportar_latex(
        ur, tex / "urbano_rural.tex",
        "Acceso urbano frente a rural, ponderado por poblacion", "tab:urbano-rural",
        {"departamento": "Departamento", "urbano_rural": "Ambito", "poblacion": "Poblacion",
         "t_medio_pond_min": "Media (min)", "pct_sin_acceso_vial": r"Sin acceso vial (\%)"})

    # -------------------------------------------------- 3.6 cruce con pobreza
    banner("FASE 3.6 — Cruce con la tasa de pobreza distrital")
    pobreza = mt.cargar_pobreza(cfg)
    cruce, rel = mt.cruce_acceso_pobreza(niveles["distrito"], pobreza, cfg)
    io_utils.guardar_tabla(cruce, cfg.outputs_dir, "acceso_x_pobreza")
    io_utils.guardar_tabla(rel, cfg.outputs_dir, "acceso_x_pobreza_correlacion")
    # Los p-valores se formatean a mano: con dos decimales, un p de 0.00002 saldria
    # impreso como "0.00", que se lee como cero y no como "muy significativo".
    rel_tex = rel.copy()
    for c in ("pearson_p", "spearman_p"):
        rel_tex[c] = rel_tex[c].map(lambda v: "$<$0.001" if v < 0.001 else f"{v:.3f}")
    mt.exportar_latex(
        rel_tex, tex / "acceso_pobreza.tex",
        "Relacion entre acceso y pobreza distrital (correlacional, no causal)",
        "tab:pobreza",
        {"ambito": "Ambito", "n_distritos": "Distritos", "pearson_r": "Pearson $r$",
         "pearson_p": "$p$ (Pearson)", "spearman_rho": r"Spearman $\rho$",
         "spearman_p": "$p$ (Spearman)"},
        decimales="%.3f", sin_escapar=("pearson_p", "spearman_p"))

    # ------------------------------------------------------------- 3.7 figuras
    banner("FASE 3.7 — Figuras")
    intentar("fase3_bandas.png", export.figura_bandas,
             bandas_dep, cfg, cfg.figuras_dir / "fase3_bandas.png")
    intentar("fase3_lorenz.png", export.figura_lorenz,
             curvas, gini, cfg, cfg.figuras_dir / "fase3_lorenz.png")
    intentar("fase3_pobreza.png", export.figura_pobreza,
             cruce, rel, cfg, cfg.figuras_dir / "fase3_pobreza.png")

    dt = time.perf_counter() - t0
    banner(f"FASE 3 COMPLETA en {dt / 60:.1f} min")
    tot = bandas_tot.iloc[0]
    log.info("Poblacion a <=60 min de un resolutivo : %.1f%%", tot["pct_acum_60min"])
    log.info("Poblacion sin acceso vial            : %.1f%%", tot["pct_sin_acceso_vial"])
    log.info("Gini del tiempo de acceso (ambito)   : %.4f",
             float(gini.loc[gini["ambito"] == "TOTAL", "gini_tiempo_acceso"].iloc[0]))
    log.info("Tablas LaTeX en                      : %s", tex)
    return 0


# ============================================================================== FASE 5
def fase_5(args) -> int:
    """
    Fase 5 — Compilacion del informe LaTeX.

    Es tambien una de las innovaciones que sugiere el enunciado: un paso del pipeline que
    recompila el PDF con las cifras vigentes cada vez que cambian los datos. Asi el informe
    no puede quedar desincronizado de los resultados, porque no hay ninguna cifra tecleada a
    mano: las tablas entran con \\input desde report/tablas/ y las figuras en PDF vectorial.
    """
    import shutil
    import subprocess

    t0 = time.perf_counter()
    cfg = load_config()
    inf = cfg.raw.get("informe", {})
    banner("HW2 — FASE 5 · Informe LaTeX")

    tex = cfg.root / inf.get("fuente", "report/main.tex")
    pdf = cfg.root / inf.get("salida", "report/main.pdf")
    if not tex.exists():
        log.error("No se encontro la fuente del informe: %s", tex)
        return 1

    # --- los insumos que el .tex incorpora tienen que existir ---
    faltan = []
    for linea in tex.read_text(encoding="utf-8").splitlines():
        s = linea.strip()
        if s.startswith("\\input{"):
            rel = s.split("{", 1)[1].split("}", 1)[0]
            if not (tex.parent / rel).exists():
                faltan.append(rel)
        elif "\\includegraphics" in s and "{" in s:
            rel = s.rsplit("{", 1)[1].split("}", 1)[0]
            if not (tex.parent / "figures" / rel).exists():
                faltan.append(f"figures/{rel}")
    if faltan:
        log.error("Faltan insumos que el informe incorpora: %s", ", ".join(faltan))
        log.error("Corre primero: python run_pipeline.py")
        return 1
    log.info("  todas las tablas y figuras que el informe incorpora estan presentes")

    # --- buscar compilador ---
    compilador = None
    for c in inf.get("compiladores", ["tectonic", "latexmk", "pdflatex"]):
        p = Path(c)
        if p.is_file():
            compilador = str(p)
            break
        if shutil.which(c):
            compilador = c
            break
    if compilador is None:
        log.warning("No se encontro ningun compilador de LaTeX.")
        log.warning("El archivo %s esta listo: subelo a Overleaf, que el enunciado admite,",
                    tex.name)
        log.warning("o instala Tectonic (un solo binario) desde:")
        log.warning("  https://github.com/tectonic-typesetting/tectonic/releases")
        return 1
    log.info("  compilador: %s", compilador)

    # --- compilar ---
    nombre = Path(compilador).stem.lower()
    if "tectonic" in nombre:
        cmd = [compilador, "-X", "compile", str(tex), "--outdir", str(tex.parent),
               "--keep-logs"]
    elif "latexmk" in nombre:
        cmd = [compilador, "-pdf", "-interaction=nonstopmode",
               f"-outdir={tex.parent}", str(tex)]
    else:
        # pdflatex necesita dos pasadas para resolver las referencias cruzadas.
        cmd = [compilador, "-interaction=nonstopmode", "-halt-on-error",
               f"-output-directory={tex.parent}", str(tex)]

    pasadas = 2 if "pdflatex" in nombre else 1
    for i in range(1, pasadas + 1):
        log.info("  compilando (pasada %d/%d)... la primera vez Tectonic descarga los "
                 "paquetes que el documento necesita", i, pasadas)
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(tex.parent),
                           timeout=int(inf.get("timeout_seg", 600)))
        if r.returncode != 0:
            log.error("  la compilacion fallo (codigo %d)", r.returncode)
            for linea in (r.stderr or r.stdout or "").splitlines()[-25:]:
                log.error("    %s", linea)
            return 1

    if not pdf.exists():
        log.error("  el compilador termino sin error pero no se genero %s", pdf.name)
        return 1

    # --- resumen ---
    # Contar paginas por los marcadores /Type /Page del PDF crudo no funciona: los objetos
    # pueden venir comprimidos en flujos. Se usa pypdf, que si entiende el formato.
    paginas = None
    try:
        from pypdf import PdfReader
        paginas = len(PdfReader(str(pdf)).pages)
    except ImportError:
        log.info("  (instala pypdf si quieres que se verifique el numero de paginas)")
    except Exception as e:  # noqa: BLE001
        log.warning("  no se pudo leer el numero de paginas: %s", e)

    log.info("  PDF generado: %s (%.2f MB%s)", pdf.name, pdf.stat().st_size / 1e6,
             f", {paginas} paginas" if paginas and paginas > 0 else "")
    if paginas and not (8 <= paginas <= 12):
        log.warning("  AVISO: el enunciado pide entre 8 y 12 paginas y el informe tiene %d",
                    paginas)

    banner(f"FASE 5 COMPLETA en {time.perf_counter() - t0:.0f} s")
    log.info("Fuente : %s", tex)
    log.info("PDF    : %s", pdf)
    return 0


# ==================================================== dependencias entre fases
# Cada fase declara de que fase depende y que archivos deja en disco. Con eso el pipeline
# se vuelve **auto-suficiente**: se puede borrar cualquier salida y volver a ejecutar, que
# lo que falte se regenera solo, en orden, sin que el usuario tenga que acordarse de cual
# fase producia cual archivo.
#
# La regla es la de un sistema de build: la fase que se pide SIEMPRE se ejecuta; las fases
# de las que depende se ejecutan **solo si sus salidas faltan o quedaron desfasadas**. Asi
# volver a correr algo ya calculado sigue costando segundos, no minutos.
DEPENDE_DE: dict[int, list[int]] = {1: [], 2: [1], 3: [2], 4: [3], 5: [3]}


def _salidas_fase(n: int, cfg) -> list[Path]:
    """Archivos que deja cada fase. Su ausencia es lo que dispara la regeneracion."""
    ext = "parquet" if cfg.salida.get("formato", "parquet") == "parquet" else "gpkg"
    P = cfg.processed_dir
    O = cfg.outputs_dir
    return {
        1: [P / f"oferta_salud.{ext}", P / f"demanda_ccpp.{ext}", P / f"distritos.{ext}"],
        2: [P / f"acceso_puntos.{ext}", P / "matriz_car.parquet"],
        3: [O / "bandas_cobertura.csv", O / "acceso_por_distrito.csv",
            O / "brechas_criticas.csv", O / "desigualdad_gini.csv",
            O / "acceso_x_pobreza.csv"],
    }.get(n, [])


def _ambito_desfasado(n: int, cfg) -> bool:
    """
    True si las salidas de la fase existen pero corresponden a OTRO ambito que el declarado
    hoy en config.md.

    Esto no es paranoia: ya paso. Se cambio el ambito a Ucayali para probar, se corrio el
    pipeline, y despues se revirtio config.md a Loreto sin regenerar. Los datos quedaron
    huerfanos de su configuracion, y rutear sobre eso habria dado resultados silenciosamente
    equivocados: sin excepcion, sin advertencia, con numeros plausibles.
    """
    if n != 1:
        return False
    import pandas as pd

    p = _salidas_fase(1, cfg)[2]  # distritos
    if not p.exists():
        return False
    try:
        deps = pd.read_parquet(p, columns=["DEPARTAMEN"])["DEPARTAMEN"].str.upper().unique()
    except Exception:  # noqa: BLE001 — si no se puede leer, que lo resuelva regenerando
        return True
    return set(deps) != set(cfg.departamentos)


def asegurar_insumos(n: int, args, cfg, ejecutadas: set[int]) -> None:
    """
    Garantiza recursivamente que las fases de las que depende `n` tengan sus salidas listas.

    Se ejecuta ANTES de la fase pedida. No re-ejecuta lo que ya esta bien: solo lo que falta.
    """
    for previa in DEPENDE_DE.get(n, []):
        if previa in ejecutadas:
            continue
        asegurar_insumos(previa, args, cfg, ejecutadas)

        faltan = [p for p in _salidas_fase(previa, cfg) if not p.exists()]
        desfasado = _ambito_desfasado(previa, cfg)
        if not faltan and not desfasado:
            continue

        if desfasado:
            log.warning("La Fase %d se regenera: sus datos son de un ambito distinto al "
                        "declarado hoy en config.md (%s)", previa, ", ".join(cfg.departamentos))
        else:
            log.warning("La Fase %d se regenera: faltan %d de sus salidas (%s)",
                        previa, len(faltan), ", ".join(p.name for p in faltan[:3]))

        rc = FASES[previa](args)
        if rc != 0:
            raise RuntimeError(f"La Fase {previa}, necesaria para la Fase {n}, fallo "
                               f"con codigo {rc}")
        ejecutadas.add(previa)


# ------------------------------------------------------------------- fases pendientes
def _pendiente(n: int, nombre: str):
    def _f(args):  # noqa: ARG001
        log.error("La fase %d (%s) todavia no esta implementada.", n, nombre)
        log.error("Fases disponibles: 1")
        return 1
    return _f


FASES = {
    1: fase_1,
    2: fase_2,
    3: fase_3,
    4: _pendiente(4, "Dashboard Streamlit"),
    5: fase_5,
}

# Las que `--phase all` recorre. Se amplia al implementar cada fase nueva.
# Las fases 4 (app Streamlit) y 5 (compilar LaTeX) no son pasos de pipeline y nunca entraran
# aqui: se lanzan con `streamlit run app.py` y con el compilador de LaTeX respectivamente.
IMPLEMENTADAS = [1, 2, 3]


def parse_args():
    p = argparse.ArgumentParser(
        description="HW2 — Accesibilidad a establecimientos de salud resolutivos en el Peru",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    # Por defecto se corre TODO. Asi pulsar "play" en el editor —que no puede pasar
    # argumentos— ejecuta el pipeline completo y verifica el resultado, que es el uso normal.
    # Con el cache, 'all' cuesta practicamente lo mismo que una sola fase.
    p.add_argument("--phase", default="all", metavar="{1..5|all}",
                   help="Fase a ejecutar, o 'all' para todas las implementadas en secuencia. "
                        "Las fases de las que dependa se regeneran solas si les faltan "
                        "salidas (default: all)")
    p.add_argument("--no-verify", action="store_true",
                   help="No ejecutar las verificaciones al terminar (por defecto si se hacen)")
    p.add_argument("--with-osm", action="store_true",
                   help="Descarga tambien el extracto OSM del Peru (~244 MB, necesario en Fase 2)")
    p.add_argument("--hi-res-pop", action="store_true",
                   help="Usa el raster WorldPop 'unconstrained' (~596 MB) en vez del "
                        "'constrained' de 6 MB. Corrige la subestimacion de poblacion en la "
                        "Amazonia a costa de una descarga mucho mayor.")
    p.add_argument("--force-download", action="store_true",
                   help="Ignora el cache de data/raw y vuelve a descargar todo")
    p.add_argument("--force-routing", action="store_true",
                   help="Fase 2: ignora el cache de ruteo y recalcula snapping y matrices")
    p.add_argument("--skip-map", action="store_true",
                   help="No genera el mapa interactivo Folium (corrida mas rapida)")
    p.add_argument("-v", "--verbose", action="store_true", help="Log en nivel DEBUG")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config()

    # --- que fases hay que correr ---
    pedido = str(args.phase).strip().lower()
    if pedido == "all":
        objetivo = IMPLEMENTADAS
    else:
        try:
            n = int(pedido)
        except ValueError:
            print(f"--phase: valor invalido {args.phase!r}. Usa 1..5 o 'all'.")
            return 2
        if n not in FASES:
            print(f"--phase: la fase {n} no existe. Usa 1..5 o 'all'.")
            return 2
        objetivo = [n]

    archivo_log = configurar_logging(cfg.logs_dir, objetivo[0], args.verbose)
    log.info("Log de esta corrida: %s", archivo_log)
    if pedido == "all":
        log.info("Modo 'all': se ejecutaran en secuencia las fases %s",
                 ", ".join(map(str, objetivo)))

    ejecutadas: set[int] = set()
    try:
        for n in objetivo:
            if n in ejecutadas:
                log.info("Fase %d ya se ejecuto en esta corrida (como insumo); se omite", n)
                continue
            # Regenera lo que falte aguas arriba antes de correr la fase pedida.
            asegurar_insumos(n, args, cfg, ejecutadas)
            rc = FASES[n](args)
            if rc != 0:
                return rc
            ejecutadas.add(n)

        # --- verificacion automatica ---
        # Correr sin comprobar deja al usuario sin saber si el resultado es bueno. Se
        # verifican las fases que se ejecutaron, en orden.
        if args.no_verify:
            return 0
        import verify

        banner("VERIFICACION DE LOS RESULTADOS")
        problemas = 0
        for n in sorted(ejecutadas):
            if n not in verify.VERIFICADORES:
                continue
            if verify.VERIFICADORES[n](cfg) != 0:
                problemas += 1
        if problemas:
            log.error("%d fase(s) no pasaron la verificacion", problemas)
            return 1
        log.info("")
        log.info("TODO CORRECTO: las fases %s se ejecutaron y verificaron sin errores.",
                 ", ".join(map(str, sorted(ejecutadas))))
        return 0
    except KeyboardInterrupt:
        log.warning("Interrumpido por el usuario.")
        return 130
    except Exception:
        log.exception("El pipeline fallo:")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
