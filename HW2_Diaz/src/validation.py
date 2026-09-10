"""
Fase 1 — Capa de validacion y reporte de calidad de datos.

El enunciado enumera seis clases de error documentadas en el registro y exige que, para
cada una, el pipeline informe cuantos registros se marcaron, que accion se tomo y por que.
La regla de calificacion es explicita:

    borrar filas malas en silencio = reprobado
    borrar con reglas registradas y justificadas = aprobado
    corregir lo recuperable documentando la tasa de recuperacion = excelencia

Por eso este modulo nunca hace `dropna()` a secas. Cada reg1a produce un
`ResultadoRegla` con conteos y una accion explicita, y todo registro descartado queda
identificado por codigo en el reporte, de modo que la decision sea auditable.

Las seis reglas obligatorias:

    R1  Coordenadas ausentes, nulas o cero
    R2  Coordenadas fuera del bounding box del Peru
    R3  Latitud y longitud intercambiadas
    R4  Punto fuera del poligono del distrito que el propio registro declara
    R5  Codigos de establecimiento duplicados
    R6  Problemas de codificacion de texto (UTF-8 vs latin-1)
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from .config import Config

log = logging.getLogger(__name__)

# Acciones posibles sobre un grupo de registros marcados.
CORREGIDO = "CORREGIDO"
ELIMINADO = "ELIMINADO"
RETENIDO = "RETENIDO_CON_ADVERTENCIA"
SIN_HALLAZGOS = "SIN_HALLAZGOS"


# ============================================================================ reporte
@dataclass
class ResultadoRegla:
    """Resultado de aplicar una regla de validacion."""

    codigo: str
    nombre: str
    n_evaluados: int
    n_marcados: int
    accion: str
    justificacion: str
    n_recuperados: int = 0
    n_descartados: int = 0
    detalle: dict = field(default_factory=dict)

    @property
    def tasa_recuperacion(self) -> float:
        """Proporcion de registros marcados que se logro corregir en vez de descartar."""
        return self.n_recuperados / self.n_marcados if self.n_marcados else 0.0

    def fila(self) -> dict:
        return {
            "regla": self.codigo,
            "nombre": self.nombre,
            "registros_evaluados": self.n_evaluados,
            "registros_marcados": self.n_marcados,
            "pct_marcados": round(100 * self.n_marcados / self.n_evaluados, 3)
            if self.n_evaluados else 0.0,
            "recuperados": self.n_recuperados,
            "descartados": self.n_descartados,
            "tasa_recuperacion_pct": round(100 * self.tasa_recuperacion, 1),
            "accion": self.accion,
            "justificacion": self.justificacion,
        }


@dataclass
class ReporteCalidad:
    """Acumula los resultados de todas las reglas y los exporta."""

    dataset: str
    resultados: list[ResultadoRegla] = field(default_factory=list)

    def add(self, r: ResultadoRegla) -> ResultadoRegla:
        self.resultados.append(r)
        simbolo = "OK " if r.n_marcados == 0 else "!! "
        log.info("  %s%-4s %-46s marcados=%-6d %s",
                 simbolo, r.codigo, r.nombre[:46], r.n_marcados, r.accion)
        if r.n_marcados and r.n_recuperados:
            log.info("       -> recuperados %d/%d (%.1f%%), descartados %d",
                     r.n_recuperados, r.n_marcados, 100 * r.tasa_recuperacion, r.n_descartados)
        return r

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([r.fila() for r in self.resultados])

    def to_markdown(self) -> str:
        df = self.to_frame()
        lineas = [
            f"### Reporte de calidad — `{self.dataset}`",
            "",
            f"- Registros evaluados: **{df['registros_evaluados'].max():,}**",
            f"- Reglas aplicadas: **{len(df)}**",
            f"- Reglas con hallazgos: **{int((df['registros_marcados'] > 0).sum())}**",
            f"- Total de marcas: **{int(df['registros_marcados'].sum()):,}** "
            f"(un registro puede activar mas de una regla)",
            f"- Recuperados: **{int(df['recuperados'].sum()):,}** · "
            f"Descartados: **{int(df['descartados'].sum()):,}**",
            "",
            "| Regla | Descripcion | Marcados | % | Recup. | Descart. | Accion |",
            "|---|---|---:|---:|---:|---:|---|",
        ]
        for r in self.resultados:
            f = r.fila()
            lineas.append(
                f"| {f['regla']} | {f['nombre']} | {f['registros_marcados']:,} | "
                f"{f['pct_marcados']}% | {f['recuperados']:,} | {f['descartados']:,} | "
                f"{f['accion']} |"
            )
        lineas += ["", "**Justificacion de cada accion**", ""]
        for r in self.resultados:
            lineas.append(f"- **{r.codigo} — {r.nombre}.** {r.justificacion}")
        return "\n".join(lineas)


# ==================================================================== R6: codificacion
# Firmas tipicas de mojibake: texto UTF-8 leido como latin-1/cp1252.
_MOJIBAKE = re.compile(r"Ã[\x80-\xbf]|Â[\x80-\xbf]|â€|ï»¿|�")


def detectar_mojibake(s: pd.Series) -> pd.Series:
    """True donde el texto muestra sintomas de doble decodificacion."""
    return s.astype("string").fillna("").str.contains(_MOJIBAKE, regex=True, na=False)


def reparar_mojibake(texto: str) -> str:
    """
    Revierte el doble decodificado: re-codifica a latin-1 y decodifica como UTF-8.

    Si la operacion no es reversible (el texto no era mojibake), se devuelve intacto.
    """
    if not isinstance(texto, str):
        return texto
    try:
        arreglado = texto.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return texto
    # Solo se acepta la reparacion si de verdad elimino las firmas de mojibake.
    return arreglado if not _MOJIBAKE.search(arreglado) else texto


def limpiar_texto(s: object) -> object:
    """Normaliza espacios y forma Unicode, sin alterar el contenido semantico."""
    if not isinstance(s, str):
        return s
    return unicodedata.normalize("NFC", " ".join(s.split()))


# ============================================================== normalizacion categoria
# RENIPRESS trae la categoria sucia: variantes de espaciado, guiones distintos, ceros y
# vacios. Las reglas de normalizacion tienen que ser visibles en el codigo (lo pide el
# enunciado), no escondidas en un diccionario opaco.
_CAT_CANONICAS = {"I-1", "I-2", "I-3", "I-4",
                  "II-1", "II-2", "II-E",
                  "III-1", "III-2", "III-E"}
SIN_CATEGORIA = "SIN_CATEGORIA"


def normalizar_categoria(valor: object) -> str:
    """
    Lleva la categoria a su forma canonica `<romano>-<nivel>`.

    Pasos, en orden:
      1. nulos, cadena vacia y el literal "0" -> SIN_CATEGORIA (el registro no declara nivel)
      2. mayusculas y colapso de espacios
      3. guiones tipograficos (– —) y espacios/puntos separadores -> guion ASCII
      4. se inserta el guion si falta ("II1" -> "II-1")
      5. si el resultado no esta en el conjunto canonico -> SIN_CATEGORIA
    """
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return SIN_CATEGORIA
    s = str(valor).strip().upper()
    if s in {"", "0", "NAN", "NONE", "SIN CATEGORIA", "S/C", "-"}:
        return SIN_CATEGORIA
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"[\s.]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    if "-" not in s:
        m = re.fullmatch(r"(I{1,3})([12E])", s)
        if m:
            s = f"{m.group(1)}-{m.group(2)}"
    return s if s in _CAT_CANONICAS else SIN_CATEGORIA


def normalizar_estado(valor: object) -> str:
    """Estado en mayusculas y sin espacios redundantes."""
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return "DESCONOCIDO"
    s = " ".join(str(valor).strip().upper().split())
    return s or "DESCONOCIDO"


# ==================================================================== reglas geometricas
def _en_bbox(lon: pd.Series, lat: pd.Series, bbox) -> pd.Series:
    lon_min, lat_min, lon_max, lat_max = bbox
    return lon.between(lon_min, lon_max) & lat.between(lat_min, lat_max)


def validar_coordenadas(
    df: pd.DataFrame,
    col_lat: str,
    col_lon: str,
    cfg: Config,
    reporte: ReporteCalidad,
    etiqueta: str = "registro",
) -> pd.DataFrame:
    """
    Aplica R1, R2 y R3 sobre las columnas de coordenadas.

    Anade al DataFrame:
      `lat`, `lon`      coordenadas finales (corregidas donde correspondia)
      `coord_valida`    bool: la fila puede usarse geometricamente
      `coord_flags`     texto con los codigos de regla que activo la fila
    """
    n = len(df)
    out = df.copy()
    bbox = cfg.bbox_peru
    flags = pd.Series([[] for _ in range(n)], index=out.index, dtype=object)

    lat = pd.to_numeric(out[col_lat], errors="coerce")
    lon = pd.to_numeric(out[col_lon], errors="coerce")

    # ---------- R1: ausentes, nulas o cero ----------
    nulas = lat.isna() | lon.isna()
    ceros = (lat == 0) | (lon == 0)
    r1_mask = nulas | ceros
    for i in out.index[r1_mask]:
        flags[i] = flags[i] + ["R1"]
    reporte.add(ResultadoRegla(
        codigo="R1",
        nombre="Coordenadas ausentes, nulas o cero",
        n_evaluados=n,
        n_marcados=int(r1_mask.sum()),
        accion=RETENIDO if r1_mask.any() else SIN_HALLAZGOS,
        n_descartados=int(r1_mask.sum()),
        justificacion=(
            f"{int(nulas.sum()):,} filas sin coordenada y {int(ceros.sum()):,} con (0,0). "
            "No son recuperables sin geocodificar la direccion, lo que introduciria un "
            f"error de posicion mayor que el que se quiere medir. Se conservan en el dataset "
            "con `coord_valida=False` (siguen contando para estadisticas de cobertura del "
            "registro) pero se excluyen del calculo de establecimiento mas cercano. "
            "Excluirlas del ruteo sesga la oferta a la baja: es una limitacion que el "
            "informe declara explicitamente."
        ),
        detalle={"nulas": int(nulas.sum()), "cero": int(ceros.sum())},
    ))

    # ---------- R3: lat/lon intercambiadas ----------
    # En el Peru los rangos de latitud (-18.4..-0.04) y longitud (-81.4..-68.6) son
    # disjuntos, asi que un intercambio es detectable sin ambiguedad: el par "cabe" solo
    # si se lee al reves. Por eso este error si es 100% recuperable.
    ok_directo = _en_bbox(lon, lat, bbox)
    ok_invertido = _en_bbox(lat, lon, bbox)
    r3_mask = (~ok_directo) & ok_invertido & (~r1_mask)

    lat_fin, lon_fin = lat.copy(), lon.copy()
    if cfg.validacion.get("corregir_coordenadas_invertidas", True) and r3_mask.any():
        lat_fin[r3_mask], lon_fin[r3_mask] = lon[r3_mask], lat[r3_mask]
    for i in out.index[r3_mask]:
        flags[i] = flags[i] + ["R3"]
    reporte.add(ResultadoRegla(
        codigo="R3",
        nombre="Latitud y longitud intercambiadas",
        n_evaluados=n,
        n_marcados=int(r3_mask.sum()),
        n_recuperados=int(r3_mask.sum()),
        accion=CORREGIDO if r3_mask.any() else SIN_HALLAZGOS,
        justificacion=(
            "Los rangos validos de latitud y longitud del Peru no se solapan, de modo que "
            "un par intercambiado solo es interpretable de una forma. La correccion es "
            "deterministica y se aplica con tasa de recuperacion del 100%; no se descarta "
            "ningun registro por esta causa."
            + ("" if r3_mask.any() else
               " En este corte del registro no se hallo ningun caso: la regla queda "
               "implementada y ejercitada, y su conteo cero es en si un resultado.")
        ),
    ))

    # ---------- R2: fuera del bounding box ----------
    dentro = _en_bbox(lon_fin, lat_fin, bbox)
    r2_mask = (~dentro) & (~r1_mask)
    for i in out.index[r2_mask]:
        flags[i] = flags[i] + ["R2"]
    reporte.add(ResultadoRegla(
        codigo="R2",
        nombre="Coordenadas fuera del bounding box del Peru",
        n_evaluados=n,
        n_marcados=int(r2_mask.sum()),
        n_descartados=int(r2_mask.sum()),
        accion=RETENIDO if r2_mask.any() else SIN_HALLAZGOS,
        justificacion=(
            f"Evaluado contra lon [{bbox[0]}, {bbox[2]}] y lat [{bbox[1]}, {bbox[3]}]. "
            "Se aplica despues de R3 para no contar como fuera de rango un punto que solo "
            "estaba invertido. Lo que queda marcado no tiene una lectura alternativa "
            "plausible (signo perdido, unidades UTM sin convertir), asi que se retiene con "
            "`coord_valida=False` en vez de inventarle una posicion."
        ),
    ))

    out["lat"] = lat_fin
    out["lon"] = lon_fin
    out["coord_valida"] = dentro & (~r1_mask)
    out["coord_flags"] = flags.map(lambda x: "|".join(x))
    log.info("       coordenadas utilizables: %d/%d (%.1f%%)",
             int(out["coord_valida"].sum()), n, 100 * out["coord_valida"].mean())
    return out


def validar_duplicados(
    df: pd.DataFrame, col_id: str, reporte: ReporteCalidad
) -> pd.DataFrame:
    """
    R5 — Codigos duplicados.

    Se conserva la primera aparicion y se marca el resto. No se eliminan del dataset:
    se etiquetan con `es_duplicado=True` para que las estadisticas del registro sigan
    siendo fieles, pero no se cuentan dos veces como oferta.
    """
    out = df.copy()
    dup = out[col_id].duplicated(keep="first")
    out["es_duplicado"] = dup
    n_ids = int(out.loc[dup, col_id].nunique())
    reporte.add(ResultadoRegla(
        codigo="R5",
        nombre=f"Codigos duplicados en `{col_id}`",
        n_evaluados=len(out),
        n_marcados=int(dup.sum()),
        n_descartados=int(dup.sum()),
        accion=RETENIDO if dup.any() else SIN_HALLAZGOS,
        justificacion=(
            f"{int(dup.sum()):,} filas repiten un codigo ya visto ({n_ids:,} codigos "
            "afectados). Se marca `es_duplicado=True` en las repeticiones y se conserva la "
            "primera. Contar dos veces un mismo establecimiento inflaria artificialmente la "
            "oferta resolutiva, que es justo la variable que el estudio mide."
            if dup.any() else
            "No se hallaron codigos repetidos: el identificador es unico en este corte."
        ),
    ))
    return out


def validar_encoding(
    df: pd.DataFrame, cols_texto: list[str], cfg: Config, reporte: ReporteCalidad
) -> pd.DataFrame:
    """
    R6 — Problemas de codificacion.

    Hallazgo concreto de este dataset: el CSV de RENIPRESS viene en **UTF-8 con BOM**.
    Leerlo como latin-1 (el reflejo habitual con datos peruanos) corrompe el nombre de la
    primera columna, que pasa de `INSTITUCION` a `ï»¿INSTITUCION`, y llena de mojibake los
    campos con tildes y enies. El pipeline lo lee con `utf-8-sig` y ademas verifica que no
    queden residuos.
    """
    out = df.copy()
    presentes = [c for c in cols_texto if c in out.columns]
    total_marcados = total_reparados = 0
    por_columna: dict[str, int] = {}

    for c in presentes:
        mask = detectar_mojibake(out[c])
        k = int(mask.sum())
        if not k:
            continue
        por_columna[c] = k
        total_marcados += k
        if cfg.validacion.get("reparar_mojibake", True):
            reparado = out.loc[mask, c].map(reparar_mojibake)
            total_reparados += int((reparado != out.loc[mask, c]).sum())
            out.loc[mask, c] = reparado

    # Normalizacion de texto en todas las columnas de texto (espacios, forma Unicode).
    for c in presentes:
        out[c] = out[c].map(limpiar_texto)

    reporte.add(ResultadoRegla(
        codigo="R6",
        # Se informa el numero de REGISTROS evaluados, no de celdas, para que la cifra sea
        # comparable con la del resto de reglas. El total de celdas revisadas va en `detalle`.
        nombre="Problemas de codificacion en campos de texto",
        n_evaluados=len(out),
        n_marcados=total_marcados,
        n_recuperados=total_reparados,
        n_descartados=0,
        accion=CORREGIDO if total_reparados else (RETENIDO if total_marcados else SIN_HALLAZGOS),
        justificacion=(
            "El archivo se lee con `"
            + str(cfg.validacion.get("encoding_renipress", "utf-8-sig"))
            + "`, que es su codificacion real (UTF-8 con BOM). Leerlo como latin-1 renombra "
            "la primera columna a `ï»¿INSTITUCION` y mete mojibake en los campos acentuados; "
            "por eso el encoding es un parametro de `config.md` y no un valor incrustado. "
            "Los residuos que sobreviven se reparan re-codificando a latin-1 y decodificando "
            "como UTF-8, y la reparacion solo se acepta si elimina la firma de mojibake. "
            + (f"Columnas afectadas: {por_columna}." if por_columna else
               "No quedaron residuos tras leer con el encoding correcto.")
        ),
        detalle={"por_columna": por_columna,
                 "celdas_revisadas": len(out) * max(len(presentes), 1),
                 "columnas_revisadas": len(presentes)},
    ))
    return out


def validar_contra_distritos(
    gdf: gpd.GeoDataFrame,
    distritos: gpd.GeoDataFrame,
    col_ubigeo: str,
    cfg: Config,
    reporte: ReporteCalidad,
) -> gpd.GeoDataFrame:
    """
    R4 — El punto cae fuera del poligono del distrito que el propio registro declara.

    Resolucion en tres niveles, de menos a mas grave:
      * dentro del poligono declarado                -> correcto
      * dentro de la tolerancia del borde declarado  -> aceptado (error de digitalizacion)
      * dentro de OTRO distrito                      -> conflicto, se retiene y se reporta
      * fuera de todo distrito                       -> conflicto (mar, frontera), se retiene

    No se corrige el UBIGEO automaticamente: cuando coordenada y codigo se contradicen no
    hay forma de saber cual de los dos esta mal, y sobrescribir uno con el otro fabricaria
    una certeza que el dato no tiene. Se deja constancia de ambos.
    """
    out = gdf.copy()
    tol = float(cfg.validacion.get("tolerancia_distrito_grados", 0.002))
    evaluables = out["coord_valida"].fillna(False)
    n_eval = int(evaluables.sum())

    out["ubigeo_real"] = pd.NA
    out["distrito_coincide"] = pd.NA
    out["distrito_estado"] = "NO_EVALUADO"

    if n_eval:
        sub = out.loc[evaluables, [col_ubigeo, "geometry"]].copy()
        dist = distritos[["UBIGEO", "geometry"]].rename(columns={"UBIGEO": "ubigeo_poligono"})
        unido = gpd.sjoin(sub, dist, how="left", predicate="within")
        # sjoin puede devolver mas de una fila si los poligonos se solapan; nos quedamos
        # con la primera coincidencia por indice.
        unido = unido[~unido.index.duplicated(keep="first")]

        real = unido["ubigeo_poligono"]
        declarado = out.loc[evaluables, col_ubigeo]
        coincide = real.eq(declarado)

        # Segunda pasada: los que no coinciden pueden estar a milimetros del borde.
        sospechosos = evaluables[evaluables].index[~coincide.reindex(
            evaluables[evaluables].index, fill_value=False)]
        rescatados = set()
        if len(sospechosos):
            dmap = distritos.set_index("UBIGEO").geometry
            for i in sospechosos:
                ub = out.at[i, col_ubigeo]
                poly = dmap.get(ub)
                if poly is not None and out.at[i, "geometry"].distance(poly) <= tol:
                    rescatados.add(i)

        out.loc[evaluables, "ubigeo_real"] = real
        out.loc[evaluables, "distrito_coincide"] = coincide
        if rescatados:
            idx = list(rescatados)
            out.loc[idx, "distrito_coincide"] = True

        est = pd.Series("CONFLICTO", index=out.index[evaluables])
        est[out.loc[evaluables, "distrito_coincide"].fillna(False).to_numpy()] = "OK"
        est[real.isna().to_numpy()] = "FUERA_DE_TODO_DISTRITO"
        if rescatados:
            est[est.index.isin(rescatados)] = "OK_TOLERANCIA_BORDE"
        out.loc[evaluables, "distrito_estado"] = est.to_numpy()

    conteo = out["distrito_estado"].value_counts().to_dict()
    n_conflicto = int(conteo.get("CONFLICTO", 0) + conteo.get("FUERA_DE_TODO_DISTRITO", 0))
    n_borde = int(conteo.get("OK_TOLERANCIA_BORDE", 0))

    reporte.add(ResultadoRegla(
        codigo="R4",
        nombre="Punto fuera del distrito que el registro declara",
        n_evaluados=n_eval,
        n_marcados=n_conflicto + n_borde,
        n_recuperados=n_borde,
        n_descartados=0,
        accion=RETENIDO if n_conflicto else (CORREGIDO if n_borde else SIN_HALLAZGOS),
        justificacion=(
            f"Se cruzo cada punto con los limites distritales del IGN. {n_borde:,} caen a "
            f"menos de {tol}deg del borde del distrito declarado y se aceptan como error de "
            f"digitalizacion del limite (~{tol * 111_000:.0f} m a esta latitud). "
            f"{n_conflicto:,} presentan un conflicto real entre coordenada y UBIGEO. "
            "Esos no se corrigen automaticamente: no hay informacion para decidir si el "
            "erroneo es el punto o el codigo, y sobrescribir uno con el otro fabricaria una "
            "precision inexistente. Se retienen con `distrito_estado` explicito para que el "
            "analisis de sensibilidad del informe pueda excluirlos y medir el efecto."
        ),
        detalle=conteo,
    ))
    return out


def exportar_reporte(reporte: ReporteCalidad, outputs_dir: Path, sufijo: str) -> tuple[Path, Path]:
    """Escribe el reporte de calidad como CSV (para el informe) y Markdown (para leer)."""
    csv_p = outputs_dir / f"data_quality_{sufijo}.csv"
    md_p = outputs_dir / f"data_quality_{sufijo}.md"
    reporte.to_frame().to_csv(csv_p, index=False, encoding="utf-8")
    md_p.write_text(reporte.to_markdown(), encoding="utf-8")
    log.info("  reporte de calidad -> %s", csv_p.name)
    log.info("  reporte de calidad -> %s", md_p.name)
    return csv_p, md_p


def a_geodataframe(df: pd.DataFrame, crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    """
    Construye el GeoDataFrame usando `lon` como X y `lat` como Y.

    Nota sobre RENIPRESS: sus columnas se llaman `NORTE` y `ESTE`, pero contienen
    **latitud** y **longitud** en grados decimales respectivamente — es decir, los nombres
    invitan al error opuesto. Se verifico contra los rangos reales del archivo
    (NORTE in [-18.34, 0], ESTE in [-81.31, 0]) antes de fijar la asignacion.
    """
    geom = [Point(xy) if pd.notna(xy[0]) and pd.notna(xy[1]) else None
            for xy in zip(df["lon"], df["lat"])]
    return gpd.GeoDataFrame(df.copy(), geometry=geom, crs=crs)
