"""
Utilidades de escritura de resultados.

Centraliza el guardado para que el formato de salida sea un parametro de `config.md`
(`[salida].formato`) y no una decision repetida en cada modulo.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .config import Config

log = logging.getLogger(__name__)


def guardar_geo(gdf: gpd.GeoDataFrame, carpeta: Path, nombre: str, cfg: Config) -> Path:
    """
    Guarda un GeoDataFrame en el formato principal (GeoParquet por defecto) y,
    opcionalmente, una copia en GeoPackage para poder abrirlo en QGIS.
    """
    formato = cfg.salida.get("formato", "parquet").lower()
    carpeta.mkdir(parents=True, exist_ok=True)

    if formato == "parquet":
        destino = carpeta / f"{nombre}.parquet"
        gdf.to_parquet(destino, index=False)
    elif formato == "gpkg":
        destino = carpeta / f"{nombre}.gpkg"
        gdf.to_file(destino, driver="GPKG", layer=nombre)
    else:
        raise ValueError(f"[salida].formato no soportado: {formato!r} (usa 'parquet' o 'gpkg')")

    log.info("  guardado  %-28s %6d filas  %.1f MB",
             destino.name, len(gdf), destino.stat().st_size / 1e6)

    if formato == "parquet" and cfg.salida.get("exportar_gpkg_tambien", False):
        gpkg = carpeta / f"{nombre}.gpkg"
        try:
            # GeoPackage no admite los dtypes extendidos de pandas (boolean/Int64 nullable,
            # object mixto); se normalizan a tipos que el driver acepta.
            copia = gdf.copy()
            for c in copia.columns:
                if c == copia.geometry.name:
                    continue
                s = copia[c]
                if pd.api.types.is_bool_dtype(s):
                    # El dtype nullable "boolean" admite pd.NA, que no cabe en un entero.
                    # Se mapea a 1/0 y los ausentes a -1, valor imposible para un booleano.
                    copia[c] = s.astype("object").map(
                        {True: 1, False: 0}).fillna(-1).astype("int8")
                elif isinstance(s.dtype, pd.api.extensions.ExtensionDtype) \
                        and pd.api.types.is_numeric_dtype(s):
                    copia[c] = pd.to_numeric(s, errors="coerce").astype("float64")
                elif not pd.api.types.is_numeric_dtype(s):
                    copia[c] = s.astype("string").astype(object)
            copia.to_file(gpkg, driver="GPKG", layer=nombre)
            log.info("  guardado  %-28s (copia para QGIS)", gpkg.name)
        except Exception as e:  # noqa: BLE001 — la copia es un extra, no debe tumbar el pipeline
            log.warning("  no se pudo escribir el GeoPackage de %s: %s", nombre, e)

    return destino


def guardar_tabla(df: pd.DataFrame, carpeta: Path, nombre: str) -> Path:
    """Guarda una tabla de resultados como CSV UTF-8."""
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"{nombre}.csv"
    df.to_csv(destino, index=False, encoding="utf-8")
    log.info("  guardado  %-28s %6d filas", destino.name, len(df))
    return destino
