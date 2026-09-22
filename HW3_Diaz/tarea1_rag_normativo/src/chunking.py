"""
Fase 2 — Troceado del texto en fragmentos indexables.

El punto critico de este modulo es que **se trocea pagina por pagina**, nunca el
documento entero. Es una decision deliberada y el enunciado pregunta por ella
explicitamente:

    "why a design that joins the whole document into one string and splits it later
     tends to lose citations"

Si se concatenara todo el documento y se partiera despues, cada fragmento quedaria sin
saber de que pagina salio. Recuperarlo a posteriori obliga a buscar el fragmento dentro
del PDF, lo que falla justo en el caso mas comun de un texto legal: parrafos casi
identicos que se repiten (por ejemplo, las formulas "de acuerdo con lo establecido en el
reglamento"). Al trocear por pagina, la pagina es un dato que el fragmento ya trae; no
hay nada que reconstruir y la cita no puede equivocarse.

El precio de esta decision es que un articulo que cruza el salto de pagina queda partido
en dos fragmentos. Se compensa con el solapamiento y, sobre todo, es el intercambio
correcto: es preferible un fragmento algo mas corto que una cita incorrecta, porque una
cita incorrecta en materia normativa es exactamente el fallo que el sistema debe evitar.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, asdict
from typing import Iterable

import pandas as pd
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .config import Config

log = logging.getLogger("hw3.t1.chunking")


@dataclass
class Fragmento:
    """Un fragmento listo para indexar, con todo lo que la cita necesita."""

    id: str
    texto: str
    documento: str
    documento_desc: str
    version: str
    tipo: str
    pagina: int
    n_en_pagina: int
    caracteres: int

    def metadatos(self) -> dict:
        """
        Metadatos que se guardan junto al vector.

        ChromaDB solo admite escalares, asi que todo va aplanado. `es_modificatoria` se
        precalcula aqui para que el motor pueda decidir si anade la nota de version sin
        volver a consultar la configuracion en tiempo de consulta.
        """
        return {
            "documento": self.documento,
            "documento_desc": self.documento_desc,
            "version": self.version,
            "tipo": self.tipo,
            "pagina": self.pagina,
            "es_modificatoria": self.tipo == "decreto_modificatorio",
        }


def _id_estable(documento: str, pagina: int, n: int, texto: str) -> str:
    """
    ID unico entre documentos y estable entre corridas.

    Lo exige la Fase 2: el indice debe ser idempotente (correrlo dos veces no duplica) y
    reanudable (si se corta, continua). Ambas propiedades salen de este ID.

    Se incluye un hash del texto ademas de la posicion: si se cambia la regla de limpieza
    y el contenido del fragmento cambia, su ID cambia tambien, de modo que el indice no
    conserva silenciosamente una version vieja del texto bajo el mismo identificador.

    El prefijo lleva el nombre del documento, asi que anadir un documento nuevo jamas
    puede pisar los fragmentos de otro: sus IDs viven en espacios de nombres distintos.
    """
    h = hashlib.sha1(texto.encode("utf-8")).hexdigest()[:10]
    return f"{documento}::p{pagina:04d}::c{n:03d}::{h}"


def trocear(cfg: Config, paginas: Iterable[dict], tamano: int | None = None,
            solapamiento: int | None = None, solo_indexables: bool = True
            ) -> list[Fragmento]:
    """
    Convierte paginas en fragmentos.

    `tamano` y `solapamiento` se pueden forzar para el barrido de la Fase 2; si no se
    pasan, se usan los valores de produccion de config.yaml.
    """
    c = cfg.chunking
    tamano = tamano or int(c["tamano"])
    solapamiento = solapamiento if solapamiento is not None else int(c["solapamiento"])

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=tamano,
        chunk_overlap=solapamiento,
        separators=list(c["separadores"]),
        length_function=len,
    )

    indexables = {f.clave for f in cfg.fuentes_indexables()}
    fragmentos: list[Fragmento] = []

    for pag in paginas:
        if solo_indexables and pag["documento"] not in indexables:
            continue
        for n, trozo in enumerate(splitter.split_text(pag["texto"])):
            trozo = trozo.strip()
            if len(trozo) < 40:          # restos sueltos tras el corte
                continue
            fragmentos.append(Fragmento(
                id=_id_estable(pag["documento"], pag["pagina"], n, trozo),
                texto=trozo,
                documento=pag["documento"],
                documento_desc=pag["documento_desc"],
                version=pag["version"],
                tipo=pag["tipo"],
                pagina=pag["pagina"],
                n_en_pagina=n,
                caracteres=len(trozo),
            ))

    # Un ID repetido significaria dos fragmentos identicos en la misma posicion del mismo
    # documento: no deberia ocurrir, y si ocurre es un error de logica, no un caso borde.
    vistos = {f.id for f in fragmentos}
    if len(vistos) != len(fragmentos):
        raise RuntimeError(f"IDs duplicados: {len(fragmentos) - len(vistos)} colisiones")

    return fragmentos


def resumen(fragmentos: list[Fragmento]) -> pd.DataFrame:
    """Fragmentos por documento y distribucion de longitudes (lo pide la Fase 2, punto 6)."""
    df = pd.DataFrame([asdict(f) for f in fragmentos])
    if df.empty:
        return df
    g = df.groupby("documento")["caracteres"]
    return pd.DataFrame({
        "fragmentos": g.size(),
        "car_min": g.min(),
        "car_p25": g.quantile(0.25).round(0).astype(int),
        "car_mediana": g.median().round(0).astype(int),
        "car_p75": g.quantile(0.75).round(0).astype(int),
        "car_max": g.max(),
        "car_medio": g.mean().round(1),
        "paginas_cubiertas": df.groupby("documento")["pagina"].nunique(),
    }).reset_index()


def guardar(cfg: Config, fragmentos: list[Fragmento]) -> None:
    """Persiste los fragmentos para que la indexacion no dependa de rehacer el troceado."""
    destino = cfg.processed_dir / "fragmentos.jsonl"
    with open(destino, "w", encoding="utf-8") as fh:
        for f in fragmentos:
            fh.write(json.dumps(asdict(f), ensure_ascii=False) + "\n")
    resumen(fragmentos).to_csv(cfg.processed_dir / "fragmentos_resumen.csv",
                               index=False, encoding="utf-8")
    log.info("  %d fragmentos -> %s", len(fragmentos), destino.name)


def cargar(cfg: Config) -> list[Fragmento]:
    """Relee los fragmentos guardados."""
    p = cfg.processed_dir / "fragmentos.jsonl"
    if not p.exists():
        raise FileNotFoundError(f"No existe {p}. Corre antes: python build_index.py --fase 2")
    with open(p, encoding="utf-8") as fh:
        return [Fragmento(**json.loads(linea)) for linea in fh if linea.strip()]
