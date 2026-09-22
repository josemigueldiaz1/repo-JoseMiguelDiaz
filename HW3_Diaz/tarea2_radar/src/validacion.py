"""
Fase 2 — Reglas de calidad de datos y su reporte.

El enunciado enumera cinco defectos que los datos contienen de verdad y exige detectarlos
y registrarlos. El criterio que fija para calificar es claro:

    "Silently dropping bad rows is a failing approach. Dropping them with a logged,
     justified rule is a passing approach. Correcting the recoverable ones and reporting
     the recovery rate is an excellent approach."

Por eso aqui **ninguna regla borra filas**. Cada regla marca una columna booleana
`flag_*`, cuenta cuantos registros afecta y declara que se hizo con ellos. Quien consuma
el dataset decide si excluye o no, y el dashboard muestra los conteos para que el usuario
sepa sobre que esta parado.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from .config import Config
from .territorio import NO_LOCALIZADO

log = logging.getLogger("hw3.t2.validacion")


@dataclass
class Regla:
    """Una regla de calidad y su resultado."""

    codigo: str
    descripcion: str
    marcados: int
    pct: float
    accion: str


class ReporteCalidad:
    """Acumula los resultados de las reglas y los exporta."""

    def __init__(self):
        self.reglas: list[Regla] = []

    def anadir(self, codigo: str, descripcion: str, marcados: int, total: int,
               accion: str) -> None:
        self.reglas.append(Regla(codigo, descripcion, int(marcados),
                                 round(100 * marcados / total, 3) if total else 0.0,
                                 accion))
        log.info("  %-22s %6d (%5.2f%%)  %s", codigo, marcados,
                 100 * marcados / total if total else 0, accion)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([r.__dict__ for r in self.reglas])

    def exportar(self, cfg: Config, nombre: str = "data_quality") -> None:
        df = self.to_frame()
        df.to_csv(cfg.outputs_dir / f"{nombre}.csv", index=False, encoding="utf-8")

        lineas = ["# Reporte de calidad de datos — Tarea 2", "",
                  "Ninguna regla elimina registros. Cada una marca una columna `flag_*`,",
                  "cuenta los afectados y declara que se hizo con ellos.", "",
                  "| Código | Qué detecta | Registros | % | Acción |",
                  "|---|---|---:|---:|---|"]
        for r in self.reglas:
            lineas.append(f"| `{r.codigo}` | {r.descripcion} | {r.marcados:,} | "
                          f"{r.pct:.2f}% | {r.accion} |")
        (cfg.outputs_dir / f"{nombre}.md").write_text("\n".join(lineas), encoding="utf-8")
        log.info("  reporte de calidad -> %s.csv / .md", nombre)


def validar(cfg: Config, df: pd.DataFrame) -> tuple[pd.DataFrame, ReporteCalidad]:
    """Aplica todas las reglas. Devuelve el dataframe con columnas flag_* y el reporte."""
    v = cfg.validacion
    rep = ReporteCalidad()
    df = df.copy()
    n = len(df)

    # --- 1. procesos repetidos ---
    # Tras la deduplicacion de la adquisicion no deberia quedar ninguno. Se comprueba
    # igualmente: una regla que siempre da cero es la que avisa el dia que deja de darlo.
    dup = df["ocid"].duplicated(keep=False)
    df["flag_duplicado"] = dup
    rep.anadir("duplicados", "Mismo ocid en mas de una fila", dup.sum(), n,
               "ya deduplicado en la adquisicion; se conserva la aparicion mas reciente")

    # --- 2. monto ausente o cero ---
    monto = pd.to_numeric(df["monto"], errors="coerce")
    df["monto"] = monto
    sin_monto = monto.isna() | (monto <= float(v.get("monto_minimo", 0)))
    df["flag_sin_monto"] = sin_monto
    rep.anadir("sin_monto", "Monto ausente, cero o negativo", sin_monto.sum(), n,
               "se conserva; queda excluido de las sumas y del mapa por monto")

    # --- 3. sin descripcion ---
    desc = df["descripcion"].fillna("").astype(str).str.strip()
    sin_desc = desc.str.len() < int(v.get("descripcion_minima", 10))
    df["flag_sin_descripcion"] = sin_desc
    rep.anadir("sin_descripcion", "Descripcion vacia o demasiado corta", sin_desc.sum(), n,
               "se conserva; NO entra al indice semantico porque no hay que vectorizar")

    # --- 4. ubicacion que no es un departamento ---
    # Se mide sobre el campo crudo: cuantos valores de `Localidad` NO son uno de los 25
    # departamentos. Es la prueba de lo que advierte el enunciado, que hay provincias y
    # distritos mezclados con departamentos.
    from .territorio import normalizar_texto
    canon = {normalizar_texto(d) for d in v["departamentos"]}
    loc = df["localidad_cruda"].map(normalizar_texto)
    no_es_dep = loc.ne("") & ~loc.isin(canon)
    df["flag_localidad_no_departamento"] = no_es_dep
    rep.anadir("localidad_no_dep", "El campo Localidad no es un departamento "
               "(mezcla provincias y distritos)", no_es_dep.sum(), n,
               "no se usa Localidad como departamento salvo como ultimo recurso difuso")

    # --- 5. inconsistencias de codificacion y tildes ---
    # Cuantos valores crudos cambian al normalizar. Si el numero es cero, el dato venia
    # limpio; si no, esta regla es la que lo esta arreglando.
    crudo = df["departamento_crudo"].fillna("").astype(str)
    normalizado = crudo.map(normalizar_texto)
    diferente = crudo.str.strip().ne(normalizado) & crudo.str.strip().ne("")
    df["flag_codificacion"] = diferente
    rep.anadir("codificacion", "Tildes o mayusculas distintas del canonico "
               "(por ejemplo JUNIN frente a JUNIN con tilde)", diferente.sum(), n,
               "corregido con normalizacion Unicode NFD")

    # --- 6. no localizables ---
    if "departamento" in df.columns:
        sin_dep = df["departamento"].eq(NO_LOCALIZADO)
        df["flag_sin_departamento"] = sin_dep
        rep.anadir("sin_departamento", "No se pudo asignar departamento tras la cascada",
                   sin_dep.sum(), n,
                   "se conserva etiquetado NO_LOCALIZADO; excluido solo del mapa")

    # --- 7. fechas ilegibles ---
    for col in ("fecha_publicacion", "licitacion_inicio", "licitacion_fin"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    sin_fecha = df["fecha_publicacion"].isna()
    df["flag_sin_fecha"] = sin_fecha
    rep.anadir("sin_fecha", "Fecha de publicacion ausente o ilegible", sin_fecha.sum(), n,
               "se conserva; excluido de los filtros y graficos por fecha")

    # --- resumen util ---
    df["apto_para_indice"] = ~df["flag_sin_descripcion"]
    df["apto_para_mapa"] = ~df["flag_sin_departamento"] if "flag_sin_departamento" in df \
        else True
    log.info("  aptos para indice semantico: %d/%d", int(df["apto_para_indice"].sum()), n)

    return df, rep
