"""
Fase 1 — Construccion del dataset de demanda (centros poblados con poblacion).

El shapefile oficial de centros poblados del IGN trae 136 587 puntos con coordenadas,
distrito, provincia y departamento, pero **no trae poblacion**. La Fase 3 exige que toda
agregacion sea ponderada por poblacion ("un caserio de 12 personas no puede pesar lo mismo
que un pueblo de 12 000"), asi que hay que imputarla.

Metodo elegido: **reparto del raster WorldPop al centro poblado mas cercano dentro del
mismo distrito.**

    Para cada distrito:
      1. se recorta el raster WorldPop (100 m, 2020, ajustado a proyecciones ONU) al poligono
      2. cada celda con poblacion > 0 se asigna al centro poblado mas proximo del distrito
      3. la poblacion del centro poblado es la suma de las celdas que se le asignaron

Propiedades del metodo, que son las razones para preferirlo:

* **Conserva el total.** La suma de la poblacion imputada a los centros poblados de un
  distrito es exactamente la poblacion que el raster asigna a ese distrito. No se pierde ni
  se inventa poblacion, cosa que si ocurre con un buffer de radio fijo (deja fuera a la
  poblacion dispersa y cuenta dos veces la de los buffers que se solapan).
* **Respeta la frontera administrativa.** Al restringir el vecino mas cercano al mismo
  distrito, la poblacion de un distrito nunca se le atribuye al centro poblado de otro,
  aunque este mas cerca en linea recta.
* **Modela bien la dispersion rural.** En la Amazonia un centro poblado "representa" un
  area enorme; el metodo se la asigna sin necesidad de fijar un radio arbitrario.

Limitacion que el informe debe declarar: la celda se asigna por proximidad euclidiana, no
por la red vial. En valles encajonados y en la selva la poblacion mas cercana en linea recta
no siempre es la que gravita hacia ese centro poblado.
"""

from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.mask import mask as rio_mask
from scipy.spatial import cKDTree

from .config import Config

log = logging.getLogger(__name__)

# Escalas locales grado -> metro. Dentro de un distrito la distorsion es despreciable y
# evita reproyectar 215 veces.
_M_POR_GRADO_LAT = 110_540.0
_M_POR_GRADO_LON = 111_320.0


def _a_metros_local(lon: np.ndarray, lat: np.ndarray, lat_ref: float) -> np.ndarray:
    """Proyeccion local plana: suficiente para comparar distancias dentro de un distrito."""
    return np.column_stack([
        lon * _M_POR_GRADO_LON * np.cos(np.radians(lat_ref)),
        lat * _M_POR_GRADO_LAT,
    ])


def cargar_centros_poblados(
    shp_path, cfg: Config, distritos: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """
    Lee el shapefile de centros poblados, lo recorta al ambito y le asigna distrito.

    La asignacion de distrito se hace por **cruce espacial**, no por el nombre de distrito
    que trae el propio shapefile: los nombres tienen variantes ortograficas entre fuentes y
    el UBIGEO del poligono es el que se necesita para unir con RENIPRESS y con las metricas.
    """
    log.info("  leyendo centros poblados: %s", shp_path.name)
    ccpp = gpd.read_file(shp_path, engine="pyogrio")
    log.info("    %d centros poblados a nivel nacional", len(ccpp))

    if ccpp.crs is None:
        ccpp = ccpp.set_crs("EPSG:4326")
    elif ccpp.crs.to_epsg() != 4326:
        ccpp = ccpp.to_crs("EPSG:4326")

    # Recorte por nombre de departamento (barato) antes del cruce espacial (caro).
    ccpp = ccpp[ccpp["DEP"].str.upper().isin(cfg.departamentos)].copy()
    log.info("    %d en %s", len(ccpp), ", ".join(cfg.departamentos))

    ccpp = ccpp.rename(columns={
        "NOM_POBLAD": "nombre", "CAT_POBLAD": "categoria_ccpp",
        "DEP": "departamento_src", "PROV": "provincia_src", "DIST": "distrito_src",
    })

    unido = gpd.sjoin(
        ccpp[["nombre", "categoria_ccpp", "departamento_src", "provincia_src",
              "distrito_src", "geometry"]],
        distritos[["UBIGEO", "DEPARTAMEN", "PROVINCIA", "DISTRITO", "geometry"]],
        how="left", predicate="within",
    )
    unido = unido[~unido.index.duplicated(keep="first")]
    sin_distrito = int(unido["UBIGEO"].isna().sum())
    if sin_distrito:
        log.warning("    %d centros poblados no cayeron dentro de ningun distrito "
                    "(borde/costa); se descartan del dataset de demanda", sin_distrito)
        unido = unido[unido["UBIGEO"].notna()]

    unido = unido.rename(columns={
        "UBIGEO": "ubigeo", "DEPARTAMEN": "departamento",
        "PROVINCIA": "provincia", "DISTRITO": "distrito",
    }).drop(columns=[c for c in ("index_right",) if c in unido.columns])

    unido["ccpp_id"] = [f"CP{i:06d}" for i in range(1, len(unido) + 1)]
    unido["lon"] = unido.geometry.x
    unido["lat"] = unido.geometry.y
    log.info("    %d centros poblados con distrito asignado", len(unido))
    return unido.reset_index(drop=True)


def imputar_poblacion(
    ccpp: gpd.GeoDataFrame, distritos: gpd.GeoDataFrame, raster_path, cfg: Config
) -> gpd.GeoDataFrame:
    """
    Asigna poblacion a cada centro poblado repartiendo el raster WorldPop por distrito.

    Devuelve el mismo GeoDataFrame con las columnas `poblacion` y `poblacion_metodo`.
    """
    log.info("  imputando poblacion desde %s", raster_path.name)
    out = ccpp.copy()
    out["poblacion"] = 0.0
    out["poblacion_metodo"] = "worldpop_vecino_cercano"

    ubigeos = sorted(out["ubigeo"].unique())
    dmap = distritos.set_index("UBIGEO")
    total_raster = 0.0
    sin_celdas: list[str] = []

    with rasterio.open(raster_path) as src:
        nodata = src.nodata
        for k, ub in enumerate(ubigeos, 1):
            if ub not in dmap.index:
                continue
            geom = dmap.loc[ub, "geometry"]
            idx_ccpp = out.index[out["ubigeo"] == ub]
            if len(idx_ccpp) == 0:
                continue

            try:
                arr, transform = rio_mask(src, [geom], crop=True, filled=True,
                                          nodata=nodata if nodata is not None else -99999.0)
            except ValueError:
                # El poligono no solapa el raster (islas, error de limite).
                sin_celdas.append(ub)
                continue

            banda = arr[0].astype("float64")
            if nodata is not None:
                banda[banda == nodata] = 0.0
            banda[~np.isfinite(banda)] = 0.0
            banda[banda < 0] = 0.0

            filas, cols = np.nonzero(banda)
            if filas.size == 0:
                sin_celdas.append(ub)
                continue

            valores = banda[filas, cols]
            # Centro de cada celda poblada.
            xs, ys = rasterio.transform.xy(transform, filas, cols, offset="center")
            xs = np.asarray(xs, dtype="float64")
            ys = np.asarray(ys, dtype="float64")
            total_raster += float(valores.sum())

            sub = out.loc[idx_ccpp]
            lat_ref = float(sub["lat"].mean())
            arbol = cKDTree(_a_metros_local(sub["lon"].to_numpy(), sub["lat"].to_numpy(), lat_ref))
            _, vecino = arbol.query(_a_metros_local(xs, ys, lat_ref), k=1)

            sumas = np.bincount(vecino, weights=valores, minlength=len(sub))
            out.loc[idx_ccpp, "poblacion"] = sumas

            if k % 50 == 0 or k == len(ubigeos):
                log.info("    distritos procesados %d/%d", k, len(ubigeos))

    if sin_celdas:
        log.warning("    %d distrito(s) sin celdas pobladas en el raster: %s",
                    len(sin_celdas), ", ".join(sin_celdas[:8]) + ("..." if len(sin_celdas) > 8 else ""))

    # Un centro poblado con 0 habitantes imputados NO es un error del pipeline: significa
    # que el producto "constrained" de WorldPop no detecto edificacion en su entorno. Se
    # marca para poder cuantificar el fenomeno y declararlo como limitacion, en vez de
    # dejarlo pasar como si la poblacion fuera realmente cero.
    out["tiene_poblacion_raster"] = out["poblacion"] > 0

    imputada = float(out["poblacion"].sum())
    n_cero = int((~out["tiene_poblacion_raster"]).sum())
    log.info("    poblacion en el raster (ambito): %.0f", total_raster)
    log.info("    poblacion asignada a centros poblados: %.0f (%.4f%% del raster)",
             imputada, 100 * imputada / total_raster if total_raster else 0)
    log.info("    centros poblados sin poblacion en el raster: %d/%d (%.1f%%)",
             n_cero, len(out), 100 * n_cero / len(out))
    log.info("    poblacion imputada por departamento: %s",
             {k: round(v) for k, v in out.groupby("departamento")["poblacion"].sum().items()})
    if sin_celdas:
        log.warning("    LIMITACION: los distritos sin celdas pobladas y los %d centros "
                    "poblados con cero habitantes reflejan el sesgo conocido del producto "
                    "'constrained' en zonas de asentamiento disperso (Amazonia). Se conservan "
                    "con peso 0 y el informe lo declara.", n_cero)
    return out


def clasificar_urbano_rural(ccpp: gpd.GeoDataFrame, cfg: Config) -> gpd.GeoDataFrame:
    """
    Clasificacion urbano / rural con reglas explicitas (el enunciado exige declararlas).

    Un centro poblado es **urbano** si cumple cualquiera de las dos condiciones:
      a) su poblacion imputada alcanza el umbral del INEI (2 000 habitantes), o
      b) su categoria en el shapefile es de tipo urbano (CIUDAD, VILLA, PUEBLO,
         PP.JJ.AA.HH., BARRIO O CUARTEL).

    La condicion (b) rescata nucleos urbanos pequenos que el umbral poblacional dejaria
    fuera, y la (a) rescata conglomerados que la fuente categorizo mal o dejo en blanco
    (67 409 de los 136 587 registros nacionales no traen categoria).
    """
    d = cfg.demanda
    umbral = float(d.get("umbral_urbano_habitantes", 2000))
    cats = {c.upper() for c in d.get("categorias_urbanas", [])}

    out = ccpp.copy()
    por_poblacion = out["poblacion"] >= umbral
    por_categoria = out["categoria_ccpp"].astype("string").str.upper().isin(cats).fillna(False)
    out["es_urbano"] = por_poblacion | por_categoria
    out["urbano_rural"] = np.where(out["es_urbano"], "urbano", "rural")
    out["urbano_criterio"] = np.select(
        [por_poblacion & por_categoria, por_poblacion, por_categoria],
        ["poblacion_y_categoria", f"poblacion>={umbral:.0f}", "categoria"],
        default="rural",
    )
    log.info("    urbano=%d (%.1f%% de la poblacion) · rural=%d",
             int(out["es_urbano"].sum()),
             100 * out.loc[out["es_urbano"], "poblacion"].sum() / max(out["poblacion"].sum(), 1),
             int((~out["es_urbano"]).sum()))
    return out


def construir_demanda(
    shp_ccpp, raster_path, distritos: gpd.GeoDataFrame, cfg: Config
) -> gpd.GeoDataFrame:
    """Orquesta la construccion completa del dataset de demanda."""
    ccpp = cargar_centros_poblados(shp_ccpp, cfg, distritos)
    ccpp = imputar_poblacion(ccpp, distritos, raster_path, cfg)
    ccpp = clasificar_urbano_rural(ccpp, cfg)

    minima = float(cfg.demanda.get("poblacion_minima", 0))
    if minima > 0:
        antes = len(ccpp)
        descartados = ccpp[ccpp["poblacion"] < minima]
        pob_descartada = float(descartados["poblacion"].sum())
        ccpp = ccpp[ccpp["poblacion"] >= minima].copy()
        # Los dos numeros van separados a proposito: se pueden perder muchos PUNTOS sin
        # perder casi HABITANTES, y reportar solo lo segundo esconde que el mapa quedo vacio.
        log.warning("    filtro poblacion_minima=%.2f: se descartaron %d de %d puntos "
                    "(%.1f%%), equivalentes a %.0f habitantes (%.4f%% de la poblacion). "
                    "Quedan %d puntos de demanda.",
                    minima, antes - len(ccpp), antes, 100 * (antes - len(ccpp)) / antes,
                    pob_descartada,
                    100 * pob_descartada / max(pob_descartada + float(ccpp["poblacion"].sum()), 1),
                    len(ccpp))
    else:
        log.info("    poblacion_minima=0: se conservan los %d puntos de demanda, "
                 "incluidos los de peso 0", len(ccpp))

    cols = ["ccpp_id", "nombre", "categoria_ccpp", "ubigeo", "distrito", "provincia",
            "departamento", "lon", "lat", "poblacion", "poblacion_metodo",
            "tiene_poblacion_raster", "es_urbano", "urbano_rural", "urbano_criterio",
            "geometry"]
    return ccpp[[c for c in cols if c in ccpp.columns]].reset_index(drop=True)
