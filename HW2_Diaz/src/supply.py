"""
Fase 1 — Construccion del dataset de oferta (establecimientos de salud, RENIPRESS).

Carga el registro, lo normaliza, le aplica las seis reglas de validacion y marca que
establecimientos tienen capacidad resolutiva segun la definicion de `config.md`.

Dos detalles del archivo real que condicionan el codigo:

* El CSV viene **delimitado por `;` y codificado en UTF-8 con BOM**. Leerlo como latin-1
  renombra la primera columna a `ï»¿INSTITUCION` y llena de mojibake los campos acentuados.
* Las columnas de coordenadas se llaman `NORTE` y `ESTE`, pero contienen **latitud** y
  **longitud** respectivamente. Los nombres invitan al error contrario, asi que la
  asignacion se verifico contra los rangos observados en el propio archivo antes de fijarla.
"""

from __future__ import annotations

import logging

import geopandas as gpd
import pandas as pd

from . import validation as val
from .config import Config

log = logging.getLogger(__name__)

# Columnas de texto sobre las que corre la deteccion de mojibake (R6).
COLS_TEXTO = ["INSTITUCION", "NOMBRE", "CLASIFICACION", "TIPO_ESTABLECIMIENTO",
              "DEPARTAMENTO", "PROVINCIA", "DISTRITO", "DIRECCION",
              "DISA", "RED", "MICRORED", "UNIDAD_EJECUTORA"]

COLS_SALIDA = ["cod_ipress", "nombre", "institucion", "clasificacion", "tipo_establecimiento",
               "categoria", "categoria_raw", "estado", "estado_raw", "es_resolutiva",
               "ubigeo", "departamento", "provincia", "distrito", "direccion",
               "lon", "lat", "coord_valida", "coord_flags", "es_duplicado",
               "ubigeo_real", "distrito_estado", "apto_para_ruteo", "geometry"]


def leer_renipress(path, cfg: Config) -> pd.DataFrame:
    """Lee el CSV con el encoding y separador declarados, con respaldo documentado."""
    v = cfg.validacion
    enc = v.get("encoding_renipress", "utf-8-sig")
    sep = v.get("separador_renipress", ";")
    try:
        df = pd.read_csv(path, sep=sep, dtype=str, encoding=enc, low_memory=False)
    except UnicodeDecodeError:
        fallback = v.get("encoding_fallback", "latin-1")
        log.warning("  no se pudo leer con %s; se reintenta con %s (quedara registrado en R6)",
                    enc, fallback)
        df = pd.read_csv(path, sep=sep, dtype=str, encoding=fallback, low_memory=False)
    log.info("  %s: %d registros x %d columnas (encoding=%s, sep=%r)",
             path.name, len(df), len(df.columns), enc, sep)
    return df


def construir_oferta(
    csv_path, distritos: gpd.GeoDataFrame, cfg: Config
) -> tuple[gpd.GeoDataFrame, val.ReporteCalidad]:
    """
    Devuelve el GeoDataFrame de oferta del ambito y el reporte de calidad asociado.

    Importante: las reglas de validacion se aplican sobre el registro **nacional completo**
    y solo despues se recorta a los tres departamentos. Medir la calidad del registro sobre
    la muestra ya filtrada daria una tasa de error que depende del recorte y no seria
    comparable con lo que reporta cualquier otro estudio sobre RENIPRESS.
    """
    log.info("-" * 70)
    log.info("FASE 1.2 — Oferta: establecimientos de salud (RENIPRESS)")
    log.info("-" * 70)

    df = leer_renipress(csv_path, cfg)
    rep = val.ReporteCalidad(dataset=f"oferta_renipress ({csv_path.name})")

    # ---- R6: codificacion (primero: el resto de reglas lee estos campos) ----
    df = val.validar_encoding(df, COLS_TEXTO, cfg, rep)

    # ---- normalizacion de categoria y estado ----
    df["categoria_raw"] = df["CATEGORIA"]
    df["estado_raw"] = df["ESTADO"]
    df["categoria"] = df["CATEGORIA"].map(val.normalizar_categoria)
    df["estado"] = df["ESTADO"].map(val.normalizar_estado)
    n_sin_cat = int((df["categoria"] == val.SIN_CATEGORIA).sum())
    log.info("  categoria normalizada: %d sin categoria utilizable (%.1f%%)",
             n_sin_cat, 100 * n_sin_cat / len(df))
    log.info("  distribucion: %s",
             df["categoria"].value_counts().head(12).to_dict())

    # ---- R5: duplicados ----
    df = val.validar_duplicados(df, "COD_IPRESS", rep)

    # ---- R1 / R2 / R3: coordenadas ----
    # NORTE contiene latitud y ESTE contiene longitud (verificado contra los rangos reales).
    df = val.validar_coordenadas(df, col_lat="NORTE", col_lon="ESTE", cfg=cfg,
                                 reporte=rep, etiqueta="establecimiento")

    gdf = val.a_geodataframe(df, crs=cfg.salida.get("crs_trabajo", "EPSG:4326"))

    # ---- R4: coherencia punto / distrito declarado ----
    gdf = val.validar_contra_distritos(gdf, distritos, col_ubigeo="UBIGEO", cfg=cfg, reporte=rep)

    # ---- capacidad resolutiva ----
    gdf["es_resolutiva"] = [
        cfg.es_resolutiva(c, e) for c, e in zip(gdf["categoria"], gdf["estado"])
    ]
    # Un establecimiento entra al calculo de "mas cercano" solo si es utilizable: no
    # duplicado y con coordenada valida.
    gdf["apto_para_ruteo"] = gdf["coord_valida"] & (~gdf["es_duplicado"])

    log.info("  nacional: %d activos · %d resolutivos · %d resolutivos aptos para ruteo",
             int((gdf["estado"].isin(cfg.estados_activos)).sum()),
             int(gdf["es_resolutiva"].sum()),
             int((gdf["es_resolutiva"] & gdf["apto_para_ruteo"]).sum()))

    # ---- recorte al ambito ----
    gdf = gdf.rename(columns={
        "COD_IPRESS": "cod_ipress", "NOMBRE": "nombre", "INSTITUCION": "institucion",
        "CLASIFICACION": "clasificacion", "TIPO_ESTABLECIMIENTO": "tipo_establecimiento",
        "UBIGEO": "ubigeo", "DEPARTAMENTO": "departamento", "PROVINCIA": "provincia",
        "DISTRITO": "distrito", "DIRECCION": "direccion",
    })
    ambito = gdf[gdf["departamento"].str.upper().isin(cfg.departamentos)].copy()
    log.info("  ambito (%s): %d establecimientos · %d resolutivos · %d resolutivos aptos",
             ", ".join(cfg.departamentos), len(ambito),
             int(ambito["es_resolutiva"].sum()),
             int((ambito["es_resolutiva"] & ambito["apto_para_ruteo"]).sum()))

    resumen = (ambito.groupby(["departamento", "categoria"]).size()
               .unstack(fill_value=0))
    log.info("  categorias por departamento:\n%s", resumen.to_string())

    cols = [c for c in COLS_SALIDA if c in ambito.columns]
    return ambito[cols].reset_index(drop=True), rep


def comparar_cortes_temporales(
    csv_actual, csv_anterior, cfg: Config
) -> pd.DataFrame | None:
    """
    INNOVACION — Comparacion temporal entre dos cortes de RENIPRESS.

    El enunciado propone como innovacion "usar una version anterior de RENIPRESS para
    mostrar cambios de cobertura en el tiempo". Datos Abiertos publica un corte mensual, de
    modo que se puede medir la rotacion real del registro: cuantos establecimientos
    aparecen, desaparecen o cambian de categoria/estado entre dos fechas.

    Esto no es cosmetico: si la oferta resolutiva cambia de un mes a otro, el resultado del
    estudio tiene una fecha de caducidad que el informe debe declarar.
    """
    if csv_anterior is None or not csv_anterior.exists():
        log.info("  comparacion temporal omitida (no hay corte anterior disponible)")
        return None

    log.info("  comparacion temporal: %s vs %s", csv_anterior.name, csv_actual.name)
    cols = ["COD_IPRESS", "CATEGORIA", "ESTADO", "DEPARTAMENTO", "NOMBRE"]

    def _cargar(p):
        d = leer_renipress(p, cfg)[cols].copy()
        d["categoria"] = d["CATEGORIA"].map(val.normalizar_categoria)
        d["estado"] = d["ESTADO"].map(val.normalizar_estado)
        d["es_resolutiva"] = [cfg.es_resolutiva(c, e) for c, e in zip(d["categoria"], d["estado"])]
        return d[d["DEPARTAMENTO"].str.upper().isin(cfg.departamentos)].set_index("COD_IPRESS")

    ant, act = _cargar(csv_anterior), _cargar(csv_actual)
    solo_ant = ant.index.difference(act.index)
    solo_act = act.index.difference(ant.index)
    comunes = ant.index.intersection(act.index)

    cambio_cat = comunes[ant.loc[comunes, "categoria"].ne(act.loc[comunes, "categoria"])]
    cambio_est = comunes[ant.loc[comunes, "estado"].ne(act.loc[comunes, "estado"])]
    gano_res = comunes[(~ant.loc[comunes, "es_resolutiva"]) & act.loc[comunes, "es_resolutiva"]]
    perdio_res = comunes[ant.loc[comunes, "es_resolutiva"] & (~act.loc[comunes, "es_resolutiva"])]

    filas = [
        ("establecimientos_corte_anterior", len(ant)),
        ("establecimientos_corte_actual", len(act)),
        ("altas_nuevas", len(solo_act)),
        ("bajas_desaparecidas", len(solo_ant)),
        ("cambio_de_categoria", len(cambio_cat)),
        ("cambio_de_estado", len(cambio_est)),
        ("resolutivos_corte_anterior", int(ant["es_resolutiva"].sum())),
        ("resolutivos_corte_actual", int(act["es_resolutiva"].sum())),
        ("ganaron_capacidad_resolutiva", len(gano_res)),
        ("perdieron_capacidad_resolutiva", len(perdio_res)),
    ]
    out = pd.DataFrame(filas, columns=["indicador", "valor"])
    log.info("  rotacion del registro entre cortes:\n%s", out.to_string(index=False))
    return out
