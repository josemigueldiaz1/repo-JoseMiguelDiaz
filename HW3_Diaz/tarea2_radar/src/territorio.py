"""
Fase 2 — Normalizacion territorial a los 25 departamentos.

El enunciado pide una **regla explicita y documentada**, y distingue tres calidades de
respuesta: borrar filas malas en silencio (suspenso), borrarlas con una regla registrada
y justificada (aprobado), y **recuperar las recuperables informando la tasa de
recuperacion** (excelente). Este modulo implementa la tercera, con una cascada de cuatro
pasos que se aplican en orden y de la que queda constancia de cual resolvio cada fila.

La cascada, de mas fiable a menos:

  1. **Campo `Departamento` del comprador.** Es el dato declarado por la propia entidad.
  2. **Campo `Region`.** Mismo contenido en la practica; sirve cuando el primero falta.
  3. **Imputacion por entidad.** Una misma entidad compradora aparece en muchos procesos.
     Si declaro su departamento en ALGUNO, ese valor vale para todos los demas. Esto
     recupera filas sin inventar nada: el dato viene de la propia entidad, solo que de
     otra de sus apariciones.
  4. **Emparejamiento difuso de la `Localidad`.** Ultimo recurso, y el mas delicado,
     porque `Localidad` mezcla distritos, provincias y departamentos (168 valores
     distintos en un solo mes). Solo se acepta por encima del umbral configurado.

Cada paso deja su marca en la columna `origen_departamento`, de modo que el reporte de
calidad puede decir exactamente cuantas filas resolvio cada uno. Si todo falla, la fila
se conserva con `departamento = NO_LOCALIZADO`: no se borra, se etiqueta. Un proceso sin
departamento sigue siendo valido para los indicadores que no son territoriales.
"""

from __future__ import annotations

import logging
import unicodedata

import pandas as pd
from rapidfuzz import fuzz, process as fuzzproc

from .config import Config

log = logging.getLogger("hw3.t2.territorio")

NO_LOCALIZADO = "NO_LOCALIZADO"


def normalizar_texto(t) -> str:
    """
    Mayusculas, sin tildes, sin espacios sobrantes.

    Resuelve el caso `JUNÍN` frente a `JUNIN` que el enunciado menciona. Se hace con
    `unicodedata` en vez de con un diccionario de reemplazos porque asi cubre todas las
    tildes y diereses de una vez, incluidas las que no se han visto todavia.
    """
    if not isinstance(t, str):
        return ""
    t = unicodedata.normalize("NFD", t.strip().upper())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(t.split())


class Normalizador:
    """Aplica la cascada y lleva la cuenta de lo que resolvio cada paso."""

    def __init__(self, cfg: Config):
        v = cfg.validacion
        self.canonicos = [normalizar_texto(d) for d in v["departamentos"]]
        self.alias = {normalizar_texto(k): normalizar_texto(val)
                      for k, val in (v.get("alias") or {}).items()}
        self.umbral = int(v.get("umbral_fuzzy", 88))
        self.conteo: dict[str, int] = {}

    def _canonico(self, crudo) -> str | None:
        """Un valor suelto -> departamento canonico, o None si no se reconoce."""
        t = normalizar_texto(crudo)
        if not t:
            return None
        if t in self.canonicos:
            return t
        if t in self.alias:
            return self.alias[t]
        return None

    def _difuso(self, crudo) -> tuple[str | None, float]:
        """Emparejamiento difuso contra los 25 canonicos."""
        t = normalizar_texto(crudo)
        if not t:
            return None, 0.0
        r = fuzzproc.extractOne(t, self.canonicos, scorer=fuzz.WRatio)
        if r and r[1] >= self.umbral:
            return r[0], float(r[1])
        return None, float(r[1]) if r else 0.0

    # --------------------------------------------------------------------- cascada
    def aplicar(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        n = len(df)
        df["departamento"] = None
        df["origen_departamento"] = None
        df["score_departamento"] = 0.0

        # --- paso 1: campo Departamento ---
        d1 = df["departamento_crudo"].map(self._canonico)
        m = d1.notna()
        df.loc[m, "departamento"] = d1[m]
        df.loc[m, "origen_departamento"] = "campo_departamento"
        df.loc[m, "score_departamento"] = 100.0
        self.conteo["1_campo_departamento"] = int(m.sum())

        # --- paso 2: campo Region ---
        pend = df["departamento"].isna()
        d2 = df.loc[pend, "region_cruda"].map(self._canonico)
        m2 = d2.notna()
        idx = d2[m2].index
        df.loc[idx, "departamento"] = d2[m2]
        df.loc[idx, "origen_departamento"] = "campo_region"
        df.loc[idx, "score_departamento"] = 100.0
        self.conteo["2_campo_region"] = int(m2.sum())

        # --- paso 3: imputacion por entidad ---
        # La tabla se construye SOLO con filas ya resueltas, asi que nunca propaga una
        # suposicion: propaga un dato que la propia entidad declaro en otro proceso.
        resueltas = df[df["departamento"].notna()]
        if len(resueltas) and "entidad_id" in df.columns:
            tabla = (resueltas.groupby("entidad_id")["departamento"]
                     .agg(lambda s: s.value_counts().index[0]))
            pend = df["departamento"].isna()
            d3 = df.loc[pend, "entidad_id"].map(tabla)
            m3 = d3.notna()
            idx = d3[m3].index
            df.loc[idx, "departamento"] = d3[m3]
            df.loc[idx, "origen_departamento"] = "imputado_por_entidad"
            df.loc[idx, "score_departamento"] = 90.0
            self.conteo["3_imputado_por_entidad"] = int(m3.sum())
        else:
            self.conteo["3_imputado_por_entidad"] = 0

        # --- paso 4: difuso sobre Localidad ---
        pend = df["departamento"].isna()
        if pend.any():
            res = df.loc[pend, "localidad_cruda"].map(self._difuso)
            d4 = res.map(lambda r: r[0])
            s4 = res.map(lambda r: r[1])
            m4 = d4.notna()
            idx = d4[m4].index
            df.loc[idx, "departamento"] = d4[m4]
            df.loc[idx, "origen_departamento"] = "fuzzy_localidad"
            df.loc[idx, "score_departamento"] = s4[m4]
            self.conteo["4_fuzzy_localidad"] = int(m4.sum())
        else:
            self.conteo["4_fuzzy_localidad"] = 0

        # --- resto: se etiqueta, no se borra ---
        pend = df["departamento"].isna()
        df.loc[pend, "departamento"] = NO_LOCALIZADO
        df.loc[pend, "origen_departamento"] = "no_localizado"
        self.conteo["5_no_localizado"] = int(pend.sum())

        localizados = n - self.conteo["5_no_localizado"]
        log.info("  normalizacion territorial: %d/%d localizados (%.2f%%)",
                 localizados, n, 100 * localizados / n if n else 0)
        for paso, cuantos in self.conteo.items():
            if cuantos:
                log.info("    %-26s %6d (%.2f%%)", paso, cuantos, 100 * cuantos / n)
        return df

    def reporte(self, n_total: int) -> pd.DataFrame:
        """Tabla de recuperacion: cuantas filas resolvio cada paso de la cascada."""
        filas = [{"paso": p, "procesos": c,
                  "pct": round(100 * c / n_total, 2) if n_total else 0.0}
                 for p, c in self.conteo.items()]
        localizados = n_total - self.conteo.get("5_no_localizado", 0)
        filas.append({"paso": "TOTAL_LOCALIZADOS", "procesos": localizados,
                      "pct": round(100 * localizados / n_total, 2) if n_total else 0.0})
        return pd.DataFrame(filas)


def cargar_geojson(cfg: Config):
    """
    Descarga (una vez) el GeoJSON de departamentos y normaliza su campo de nombre.

    Devuelve None si ninguna de las URLs de respaldo responde. El dashboard debe
    degradarse a un grafico de barras en ese caso, no romperse: el enunciado admite
    explicitamente documentar una fuente inalcanzable como hallazgo legitimo sobre el
    estado de los datos abiertos, pero no admite una app que no arranca.
    """
    import json

    import requests

    t = cfg.territorio
    destino = cfg.raw_dir / t["archivo"]

    if not destino.exists():
        for url in t["geojson_urls"]:
            try:
                log.info("  descargando poligonos: %s", url[:80])
                r = requests.get(url, timeout=120,
                                 headers={"User-Agent": cfg.adquisicion["user_agent"]})
                r.raise_for_status()
                destino.write_bytes(r.content)
                break
            except Exception as e:  # noqa: BLE001
                log.warning("  no respondio: %s", str(e)[:90])
        else:
            log.error("  ninguna fuente de poligonos respondio; el mapa se omitira")
            return None

    try:
        geo = json.loads(destino.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.error("  el GeoJSON descargado no se puede leer: %s", e)
        return None

    # El nombre del departamento viene en un campo distinto segun la fuente; se prueba
    # la lista declarada en config.yaml y se anade `departamento_norm` para poder unir
    # con nuestros datos sin depender de tildes ni mayusculas.
    campos = t["campo_nombre"]
    for f in geo.get("features", []):
        props = f.setdefault("properties", {})
        nombre = next((props[c] for c in campos if c in props and props[c]), "")
        props["departamento_norm"] = normalizar_texto(nombre)
    return geo
