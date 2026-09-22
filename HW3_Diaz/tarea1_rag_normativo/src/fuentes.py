"""
Fase 1 — Descarga de las fuentes y comprobacion de que son usables.

El enunciado insiste en que esto se haga ANTES de escribir el resto del pipeline:
"a source that cannot be read changes your whole plan". La comprobacion mide cuatro
cosas por PDF —paginas, caracteres por pagina, paginas sin texto extraible y si el
orden de lectura es correcto— y emite un veredicto explicito de usable o no usable.

No adivina: si un PDF viniera escaneado, la salida lo dice y el pipeline se detiene,
en lugar de construir un indice sobre paginas vacias que luego no recuperaria nada.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from pypdf import PdfReader

from .config import Config, Fuente

log = logging.getLogger("hw3.t1.fuentes")


# ============================================================================ descarga
def descargar(fuente: Fuente, destino_dir: Path, cfg: Config, forzar: bool = False) -> Path:
    """
    Descarga un PDF a data/raw/, saltandolo si ya existe.

    El enunciado pide que el paso sea re-ejecutable y que no vuelva a descargar lo que
    ya esta. Ademas los PDF originales no se modifican nunca: todo el procesamiento
    escribe en data/processed/.
    """
    destino = destino_dir / fuente.archivo
    if destino.exists() and not forzar:
        log.info("  %-22s ya estaba descargado (%.1f MB)",
                 fuente.clave, destino.stat().st_size / 1e6)
        return destino

    d = cfg.raw["descarga"]
    cabeceras = {"User-Agent": d["user_agent"]}
    ultimo_error: Exception | None = None

    for intento in range(1, int(d["reintentos"]) + 1):
        try:
            log.info("  %-22s descargando (intento %d)...", fuente.clave, intento)
            r = requests.get(fuente.url, headers=cabeceras, timeout=int(d["timeout_seg"]),
                             stream=True, allow_redirects=True)
            r.raise_for_status()

            # Escritura a un temporal y renombrado al final: si la descarga se corta,
            # no queda un PDF truncado que la proxima corrida daria por bueno.
            tmp = destino.with_suffix(".parcial")
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
            tmp.replace(destino)

            log.info("  %-22s OK  %.1f MB", fuente.clave, destino.stat().st_size / 1e6)
            return destino
        except Exception as e:  # noqa: BLE001
            ultimo_error = e
            log.warning("  %-22s fallo: %s", fuente.clave, str(e)[:110])
            time.sleep(2 * intento)

    raise RuntimeError(
        f"No se pudo descargar '{fuente.clave}' tras {d['reintentos']} intentos: {ultimo_error}.\n"
        f"URL: {fuente.url}\n"
        f"Si la fuente esta caida, el enunciado admite documentarlo y usar una copia "
        f"cacheada: deja el PDF manualmente en {destino} y vuelve a ejecutar."
    )


# ================================================================ comprobacion de fuente
@dataclass
class ChequeoFuente:
    """Resultado de la comprobacion de un PDF. Es una fila del reporte de la Fase 1."""

    documento: str
    archivo: str
    sha256: str
    mb: float
    paginas: int
    caracteres: int
    caracteres_por_pagina: float
    paginas_sin_texto: int
    pct_paginas_sin_texto: float
    orden_correcto: bool
    usable: bool
    motivo: str
    fecha_descarga: str
    indexado: bool


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for bloque in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _orden_de_lectura_correcto(paginas: list[str]) -> bool:
    """
    Heuristica para detectar texto desordenado (columnas mal reconstruidas).

    No basta con que salga texto: si el PDF trae dos columnas y la libreria las
    entrelaza, el resultado es legible caracter a caracter pero incoherente como
    discurso, y los fragmentos resultantes serian basura.

    La senal que se usa: en un texto bien ordenado, la mayoria de las frases terminan
    en punto y las palabras estan separadas. Si aparecen muchisimas mayusculas en medio
    de palabra, suele indicar columnas mezcladas.
    """
    muestra = "\n".join(paginas[: min(5, len(paginas))])
    if len(muestra) < 200:
        return False
    palabras = muestra.split()
    if not palabras:
        return False
    # palabras "pegadas": minuscula seguida de mayuscula dentro de la misma palabra
    raras = sum(1 for w in palabras
                if len(w) > 6 and any(a.islower() and b.isupper() for a, b in zip(w, w[1:])))
    return (raras / len(palabras)) < 0.15


def comprobar(fuente: Fuente, pdf: Path, cfg: Config) -> tuple[ChequeoFuente, list[str]]:
    """
    Comprueba un PDF y devuelve (resultado, texto_por_pagina).

    Devuelve tambien el texto para no leer el PDF dos veces: la extraccion de la
    siguiente fase reutiliza exactamente lo que aqui se midio, de modo que el reporte
    de calidad describe los mismos datos que entran al indice.
    """
    sc = cfg.raw["source_check"]
    lector = PdfReader(str(pdf))
    paginas: list[str] = []
    for pag in lector.pages:
        try:
            paginas.append(pag.extract_text() or "")
        except Exception as e:  # noqa: BLE001
            log.warning("    pagina ilegible en %s: %s", fuente.clave, str(e)[:80])
            paginas.append("")

    n = len(paginas)
    total = sum(len(t) for t in paginas)
    vacias = sum(1 for t in paginas if len(t.strip()) < int(sc["min_caracteres_por_pagina"]))
    pct_vacias = 100.0 * vacias / n if n else 100.0
    orden = _orden_de_lectura_correcto(paginas)

    motivos = []
    if pct_vacias > float(sc["max_pct_paginas_vacias"]):
        motivos.append(f"{pct_vacias:.1f}% de paginas sin texto extraible "
                       f"(limite {sc['max_pct_paginas_vacias']}%); parece escaneado")
    if not orden:
        motivos.append("el orden de lectura parece incorrecto (posibles columnas mezcladas)")
    if n == 0:
        motivos.append("el PDF no tiene paginas")

    chequeo = ChequeoFuente(
        documento=fuente.descripcion[:70],
        archivo=fuente.archivo,
        sha256=_sha256(pdf)[:16],
        mb=round(pdf.stat().st_size / 1e6, 2),
        paginas=n,
        caracteres=total,
        caracteres_por_pagina=round(total / n, 1) if n else 0.0,
        paginas_sin_texto=vacias,
        pct_paginas_sin_texto=round(pct_vacias, 2),
        orden_correcto=orden,
        usable=not motivos,
        motivo="; ".join(motivos) if motivos else "usable tal cual",
        fecha_descarga=date.today().isoformat(),
        indexado=fuente.indexar,
    )
    return chequeo, paginas


def comprobar_todas(cfg: Config, forzar_descarga: bool = False
                    ) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """
    Descarga y comprueba todas las fuentes declaradas.

    Devuelve el reporte como DataFrame y el texto crudo por documento, que consume la
    fase de extraccion. Escribe ademas el reporte a data/processed/ como entregable.
    """
    raw = cfg.raw_dir
    filas: list[dict] = []
    textos: dict[str, list[str]] = {}

    for clave, fuente in cfg.fuentes.items():
        pdf = descargar(fuente, raw, cfg, forzar=forzar_descarga)
        chequeo, paginas = comprobar(fuente, pdf, cfg)
        filas.append(asdict(chequeo))
        textos[clave] = paginas

        estado = "USABLE" if chequeo.usable else "NO USABLE"
        marca = "indexado" if fuente.indexar else "fuera del indice (control)"
        log.info("  %-22s %-10s %3d pag · %6.0f car/pag · %s",
                 clave, estado, chequeo.paginas, chequeo.caracteres_por_pagina, marca)
        if not chequeo.usable:
            log.error("    motivo: %s", chequeo.motivo)

    reporte = pd.DataFrame(filas)
    salida = cfg.processed_dir / "source_check.csv"
    reporte.to_csv(salida, index=False, encoding="utf-8")
    log.info("  reporte de fuentes -> %s", salida.name)

    # Una fuente que debia indexarse y no es usable detiene el pipeline: seguir
    # construiria un indice con huecos silenciosos.
    malas = reporte[(~reporte["usable"]) & (reporte["indexado"])]
    if len(malas):
        raise RuntimeError(
            "Estas fuentes indexables NO son usables: "
            + ", ".join(malas["archivo"])
            + ". El enunciado pide dejarlas fuera y declararlo en el README."
        )
    return reporte, textos
