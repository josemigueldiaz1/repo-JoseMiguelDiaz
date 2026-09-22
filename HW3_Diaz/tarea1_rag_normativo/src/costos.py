"""
Fase 3, punto 8 — Costo observable, con el precio de la franja horaria correcta.

El enunciado pide dos cosas poco habituales y las dos estan aqui:

1. **"Every call to the generation model is logged"**: fecha, modelo, tokens de entrada y
   salida, latencia, costo en USD y si fue exito o error. Tambien se registran las
   llamadas fallidas: una tabla de costos que solo cuenta los exitos miente sobre lo que
   costo de verdad llegar al resultado.

2. **"Many providers charge different prices at different hours"**: DeepSeek cobra la
   mitad fuera de sus franjas pico. El precio no es una constante del modelo, es una
   funcion del instante de la llamada. Por eso `registrar()` recibe el momento y consulta
   la tarifa vigente en vez de multiplicar por un numero fijo.

Un matiz que conviene saber explicar: DeepSeek distingue entre tokens de entrada que
acertaron en su cache y los que no, y la diferencia de precio es de 50x (0.006 frente a
0.30 USD por millon en hora pico). Cuando la API informa del reparto se usa tal cual;
cuando no, se asume el caso caro, de modo que el costo reportado nunca quede por debajo
del real.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import Config

log = logging.getLogger("hw3.t1.costos")

COLUMNAS = [
    "timestamp_utc", "timestamp_local", "tarea", "modelo", "franja",
    "tokens_entrada", "tokens_entrada_cache_hit", "tokens_salida", "tokens_total",
    "latencia_seg", "costo_usd", "exito", "error", "pregunta",
]


@dataclass
class Llamada:
    """Una llamada al modelo generativo, exitosa o no."""

    timestamp_utc: str
    timestamp_local: str
    tarea: str
    modelo: str
    franja: str
    tokens_entrada: int
    tokens_entrada_cache_hit: int
    tokens_salida: int
    tokens_total: int
    latencia_seg: float
    costo_usd: float
    exito: bool
    error: str = ""
    pregunta: str = ""


class RegistroCostos:
    """Escribe el log de costos en CSV, una fila por llamada."""

    def __init__(self, cfg: Config, tarea: str = "tarea1"):
        self.cfg = cfg
        self.tarea = tarea
        self.ruta: Path = cfg.root / cfg.costos.get("archivo_log", "logs/costos.csv")
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        if not self.ruta.exists():
            with open(self.ruta, "w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow(COLUMNAS)

    def calcular(self, entrada: int, cache_hit: int, salida: int,
                 momento: datetime | None = None) -> tuple[str, float]:
        """
        Devuelve (franja, costo_usd) aplicando la tarifa del momento indicado.

        `cache_hit` son tokens de entrada que DeepSeek sirvio desde su cache y cobra 50
        veces mas barato. Si la API no informa, llega como 0 y todo se cobra como cache
        miss, que es el supuesto conservador.
        """
        momento = momento or datetime.now(timezone.utc)
        franja, p = self.cfg.tarifa_vigente(momento)
        miss = max(entrada - cache_hit, 0)
        costo = (cache_hit / 1e6 * p["entrada_cache_hit"]
                 + miss / 1e6 * p["entrada_cache_miss"]
                 + salida / 1e6 * p["salida"])
        return franja, costo

    def registrar(self, *, modelo: str, entrada: int, salida: int, latencia: float,
                  cache_hit: int = 0, exito: bool = True, error: str = "",
                  pregunta: str = "", momento: datetime | None = None) -> Llamada:
        momento = momento or datetime.now(timezone.utc)
        franja, costo = self.calcular(entrada, cache_hit, salida, momento)

        ll = Llamada(
            timestamp_utc=momento.astimezone(timezone.utc).isoformat(timespec="seconds"),
            timestamp_local=momento.astimezone().isoformat(timespec="seconds"),
            tarea=self.tarea,
            modelo=modelo,
            franja=franja,
            tokens_entrada=entrada,
            tokens_entrada_cache_hit=cache_hit,
            tokens_salida=salida,
            tokens_total=entrada + salida,
            latencia_seg=round(latencia, 3),
            costo_usd=round(costo, 8),
            exito=exito,
            error=error[:200],
            pregunta=pregunta[:160].replace("\n", " "),
        )
        with open(self.ruta, "a", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow([asdict(ll)[c] for c in COLUMNAS])
        return ll

    # ------------------------------------------------------------------ resumen
    def resumen(self) -> pd.DataFrame:
        """Tabla agregada para el README y el video."""
        if not self.ruta.exists():
            return pd.DataFrame()
        df = pd.read_csv(self.ruta)
        if df.empty:
            return df
        g = df.groupby(["tarea", "modelo", "franja"])
        return pd.DataFrame({
            "llamadas": g.size(),
            "exitosas": g["exito"].sum(),
            "tokens_entrada": g["tokens_entrada"].sum(),
            "tokens_salida": g["tokens_salida"].sum(),
            "latencia_mediana_seg": g["latencia_seg"].median().round(2),
            "costo_usd": g["costo_usd"].sum().round(6),
        }).reset_index()

    def total_usd(self) -> float:
        if not self.ruta.exists():
            return 0.0
        df = pd.read_csv(self.ruta)
        return float(df["costo_usd"].sum()) if len(df) else 0.0


def tabla_precios(cfg: Config) -> pd.DataFrame:
    """
    Los precios vigentes con su fecha de verificacion.

    El enunciado exige que la tabla de costos declare "the prices and the date you
    verified them": un costo sin la tarifa que lo produjo no es verificable.
    """
    c = cfg.costos
    filas = []
    for franja, precios in c["precios_por_millon"].items():
        for concepto, valor in precios.items():
            filas.append({
                "franja": franja,
                "concepto": concepto,
                "usd_por_millon_tokens": valor,
                "verificado_el": c["verificado_el"],
                "fuente": c["fuente"],
            })
    return pd.DataFrame(filas)
