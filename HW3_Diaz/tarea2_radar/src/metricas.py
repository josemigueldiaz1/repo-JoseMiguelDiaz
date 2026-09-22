"""
Fase 5 — Indicador de riesgo: adjudicaciones con un solo postor.

**Que mide y que NO mide.** La proporcion de procesos adjudicados que recibieron
exactamente un postor. Es una senal de la literatura internacional sobre integridad en
compras publicas (Open Contracting Partnership, *Red Flags in Public Procurement*, 2024;
Ojo Publico, *Funes*). Un valor alto indica competencia baja, y la competencia baja es
una condicion que **facilita** la captura de una compra.

No indica delito. Un postor unico puede deberse a un mercado genuinamente concentrado
(hay un solo fabricante del repuesto), a una especializacion tecnica legitima, a una
urgencia declarada o a que el objeto es poco atractivo comercialmente. El enunciado exige
decirlo explicitamente en el dashboard y en el video, y este modulo lo lleva incorporado
como texto en `config.yaml` para que la advertencia no pueda perderse por olvido.

**Por que hace falta un minimo de procesos por comprador.** Sin minimo, el ranking lo
copan entidades con dos o tres procesos: una con 2 procesos y 1 postor unico da 50%, que
no distingue un patron de una coincidencia. El minimo se declara en configuracion y se
justifica: con 15 procesos, un 50% ya son 8 casos, y eso si es un patron.

Se publican nombres de **entidades publicas**, nunca de personas naturales.
"""

from __future__ import annotations

import logging

import pandas as pd

from .config import Config
from .territorio import NO_LOCALIZADO

log = logging.getLogger("hw3.t2.metricas")


def _base_adjudicados(df: pd.DataFrame) -> pd.DataFrame:
    """
    Los procesos sobre los que el indicador tiene sentido.

    El enunciado dice "among awarded processes": un proceso aun en convocatoria todavia
    puede recibir mas ofertas, asi que contarlo como "un solo postor" seria un error de
    interpretacion, no un hallazgo.
    """
    d = df[df["adjudicado"] & df["n_licitantes"].notna()].copy()
    d["n_licitantes"] = pd.to_numeric(d["n_licitantes"], errors="coerce")
    d = d[d["n_licitantes"] >= 1]
    d["postor_unico"] = d["n_licitantes"] == 1
    return d


def indicador_global(cfg: Config, df: pd.DataFrame) -> dict:
    base = _base_adjudicados(df)
    if base.empty:
        return {"procesos_adjudicados": 0, "con_postor_unico": 0, "pct_postor_unico": 0.0}
    return {
        "procesos_adjudicados": len(base),
        "con_postor_unico": int(base["postor_unico"].sum()),
        "pct_postor_unico": round(100 * base["postor_unico"].mean(), 2),
        "mediana_licitantes": float(base["n_licitantes"].median()),
    }


def por_departamento(cfg: Config, df: pd.DataFrame) -> pd.DataFrame:
    base = _base_adjudicados(df)
    base = base[base["departamento"].ne(NO_LOCALIZADO)]
    if base.empty:
        return pd.DataFrame()
    g = base.groupby("departamento")
    out = pd.DataFrame({
        "procesos_adjudicados": g.size(),
        "con_postor_unico": g["postor_unico"].sum(),
        "pct_postor_unico": (100 * g["postor_unico"].mean()).round(2),
        "monto_total": g["monto"].sum().round(0),
        "mediana_licitantes": g["n_licitantes"].median(),
    }).reset_index().sort_values("pct_postor_unico", ascending=False)
    return out


def por_comprador(cfg: Config, df: pd.DataFrame) -> pd.DataFrame:
    """
    Ranking de compradores, respetando el minimo de procesos declarado.

    Se devuelven TODOS los compradores que superan el minimo, con la columna
    `supera_minimo`, para que el dashboard pueda mostrar tambien los excluidos y el
    usuario vea que el filtro existe en vez de sospechar que faltan datos.
    """
    r = cfg.riesgo
    minimo = int(r["min_procesos_por_comprador"])
    base = _base_adjudicados(df)
    if base.empty:
        return pd.DataFrame()

    g = base.groupby(["comprador", "departamento"], dropna=False)
    out = pd.DataFrame({
        "procesos_adjudicados": g.size(),
        "con_postor_unico": g["postor_unico"].sum(),
        "pct_postor_unico": (100 * g["postor_unico"].mean()).round(2),
        "monto_total": g["monto"].sum().round(0),
    }).reset_index()

    out["supera_minimo"] = out["procesos_adjudicados"] >= minimo
    out = out.sort_values(["supera_minimo", "pct_postor_unico", "procesos_adjudicados"],
                          ascending=[False, False, False])
    log.info("  compradores con >= %d procesos adjudicados: %d de %d",
             minimo, int(out["supera_minimo"].sum()), len(out))
    return out


def top_compradores(cfg: Config, df: pd.DataFrame) -> pd.DataFrame:
    r = cfg.riesgo
    out = por_comprador(cfg, df)
    if out.empty:
        return out
    return out[out["supera_minimo"]].head(int(r["top_compradores"]))


# ============================================================ INNOVACION: mas senales
def plazo_corto(cfg: Config, df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    INNOVACION — Segunda senal de alerta: periodo de consulta inusualmente corto.

    Viene de la misma guia de Open Contracting Partnership. La logica es directa: el
    periodo de consulta es la ventana en la que un proveedor puede pedir aclaraciones y
    observar las bases. Si es muy corta, quien no estuviera avisado de antemano no llega
    a entender el requerimiento ni a corregir una base sesgada. El efecto practico es
    reducir la competencia sin excluir a nadie formalmente.

    **Que campo se usa y por que.** NO el "periodo de licitacion": en los datos de OECE
    ese campo trae inicio y fin identicos en el 100% de los registros, asi que su
    duracion es siempre cero (ver logs/incidencias.md, I-07). Se usa el periodo de
    consulta, que si es una ventana real: mediana 4 dias, maximo 20.

    Se prefiere el campo `consulta_dias` que la propia entidad declara y, si falta, se
    calcula por diferencia de fechas. La preferencia importa porque el valor declarado
    es el que consta oficialmente en el cronograma.

    **Limitaciones que hay que declarar:** el umbral depende del regimen legal y del
    tipo de procedimiento; un contrato menor puede tener plazos legitimamente cortos.
    Ademas el campo solo esta en ~70% de los procesos. Por eso el indicador se cruza con
    el de postor unico: una sola senal es ruido, dos que coinciden ya merecen mirarse.
    """
    r = cfg.riesgo.get("plazo_corto", {})
    if not r.get("activo", False):
        return pd.DataFrame(), {}

    dias_min = int(r.get("dias_minimos", 3))
    d = df.copy()

    declarado = pd.to_numeric(d.get("consulta_dias"), errors="coerce")
    ini = pd.to_datetime(d.get("consulta_inicio"), errors="coerce", utc=True)
    fin = pd.to_datetime(d.get("consulta_fin"), errors="coerce", utc=True)
    calculado = (fin - ini).dt.total_seconds() / 86400
    d["dias_consulta"] = declarado.fillna(calculado)
    d["dias_consulta_origen"] = declarado.notna().map(
        {True: "declarado", False: "calculado"})

    con_plazo = d[d["dias_consulta"].notna() & (d["dias_consulta"] >= 0)].copy()
    con_plazo["flag_plazo_corto"] = con_plazo["dias_consulta"] < dias_min

    base = _base_adjudicados(con_plazo)
    resumen = {
        "procesos_con_plazo": len(con_plazo),
        "pct_con_dato": round(100 * len(con_plazo) / len(df), 2) if len(df) else 0.0,
        "mediana_dias": round(float(con_plazo["dias_consulta"].median()), 1)
        if len(con_plazo) else 0.0,
        "p25_dias": round(float(con_plazo["dias_consulta"].quantile(0.25)), 1)
        if len(con_plazo) else 0.0,
        "con_plazo_corto": int(con_plazo["flag_plazo_corto"].sum()),
        "pct_plazo_corto": round(100 * con_plazo["flag_plazo_corto"].mean(), 2)
        if len(con_plazo) else 0.0,
        "dias_minimos": dias_min,
    }

    # El cruce de las dos senales es lo que aporta: ¿un plazo corto se asocia de hecho a
    # menos postores? Si la respuesta es que si, el indicador tiene contenido empirico.
    if len(base):
        corto = base[base["flag_plazo_corto"]]
        normal = base[~base["flag_plazo_corto"]]
        resumen["pct_postor_unico_con_plazo_corto"] = (
            round(100 * corto["postor_unico"].mean(), 2) if len(corto) else None)
        resumen["pct_postor_unico_con_plazo_normal"] = (
            round(100 * normal["postor_unico"].mean(), 2) if len(normal) else None)
        resumen["n_plazo_corto_adjudicados"] = len(corto)
        resumen["n_plazo_normal_adjudicados"] = len(normal)

    cols = ["ocid", "comprador", "departamento", "categoria", "monto",
            "dias_consulta", "dias_consulta_origen", "n_licitantes", "adjudicado",
            "descripcion"]
    detalle = (con_plazo[con_plazo["flag_plazo_corto"]]
               [[c for c in cols if c in con_plazo.columns]]
               .sort_values("dias_consulta"))
    return detalle, resumen


# =================================================================== otras agregaciones
def resumen_general(cfg: Config, df: pd.DataFrame) -> dict:
    """Los KPI de la cabecera del dashboard."""
    validos = df[~df["flag_sin_monto"]]
    return {
        "procesos": len(df),
        "monto_total": float(validos["monto"].sum()),
        "departamentos": int(df.loc[df["departamento"].ne(NO_LOCALIZADO),
                                    "departamento"].nunique()),
        "compradores": int(df["comprador"].nunique()),
        "adjudicados": int(df["adjudicado"].sum()),
        **indicador_global(cfg, df),
    }


def distribucion(df: pd.DataFrame, por: str) -> pd.DataFrame:
    """Conteo y monto por categoria, departamento o mes. Alimenta la vista de distribucion."""
    d = df.copy()
    if por == "mes":
        d["mes"] = pd.to_datetime(d["fecha_publicacion"], errors="coerce",
                                  utc=True).dt.strftime("%Y-%m")
        clave = "mes"
    else:
        clave = por
    if clave not in d.columns:
        return pd.DataFrame()
    g = d[d[clave].notna()].groupby(clave)
    return pd.DataFrame({
        "procesos": g.size(),
        "monto_total": g["monto"].sum().round(0),
        "monto_mediano": g["monto"].median().round(0),
    }).reset_index().sort_values("procesos", ascending=False)
