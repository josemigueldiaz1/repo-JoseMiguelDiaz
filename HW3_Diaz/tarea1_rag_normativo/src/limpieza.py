"""
Fase 1 — Limpieza del texto y reporte de calidad de extraccion.

Dos decisiones de diseno que el enunciado pide poder defender:

1. **La pagina viaja con el texto desde el primer paso.** No se concatena el documento
   en una sola cadena para trocearlo despues. Si se hiciera asi, al partir el texto en
   fragmentos ya no habria forma de saber de que pagina salio cada uno, y el requisito
   de citar "documento y pagina" se volveria irrecuperable: habria que reconstruirlo
   buscando el fragmento dentro del PDF, que es fragil y ambiguo cuando el mismo
   parrafo aparece dos veces. Aqui cada unidad de texto nace con su numero de pagina
   pegado y no lo suelta nunca.

2. **La limpieza es declarativa y contable.** Cada patron esta en config.yaml y cada
   aplicacion se cuenta, de modo que el reporte puede decir cuantas cabeceras se
   quitaron y de que tipo, en vez de afirmar genericamente que "se limpio el texto".
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import Config

log = logging.getLogger("hw3.t1.limpieza")


@dataclass
class Pagina:
    """Una pagina de un documento, antes y despues de limpiar."""

    documento: str
    documento_desc: str
    version: str
    tipo: str
    pagina: int
    texto_crudo: str
    texto: str

    @property
    def util(self) -> bool:
        return len(self.texto.strip()) >= 40


class Limpiador:
    """Aplica las reglas de limpieza declaradas en config.yaml, contando cada acierto."""

    def __init__(self, cfg: Config):
        c = cfg.raw["limpieza"]
        self.patrones = [(p, re.compile(p, re.MULTILINE | re.IGNORECASE))
                         for p in c["patrones_cabecera"]]
        self.unir_guion = bool(c.get("unir_guion_fin_de_linea", True))
        self.colapsar = bool(c.get("colapsar_espacios", True))
        self.min_parrafo = int(c.get("min_caracteres_parrafo", 40))
        self.conteo: dict[str, int] = {p: 0 for p, _ in self.patrones}

    def limpiar(self, texto: str) -> str:
        t = texto

        # 1. Cabeceras y pies declarados. El enunciado senala que los PDF de El Peruano
        #    pegan la cabecera (numero de pagina, seccion, fecha) al cuerpo del texto:
        #    si no se quitan, acaban dentro de los fragmentos y contaminan la busqueda.
        for patron, rx in self.patrones:
            t, n = rx.subn(" ", t)
            self.conteo[patron] += n

        # 2. Palabras partidas por guion al final de linea. Los PDF maquetados a dos
        #    columnas parten palabras; sin unirlas, "contrata-\ncion" nunca coincide con
        #    la consulta "contratacion".
        if self.unir_guion:
            t = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", t)

        # 3. Ligaduras tipograficas y caracteres de control que los PDF arrastran.
        t = unicodedata.normalize("NFKC", t)
        t = t.replace("­", "")          # guion suave invisible
        t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", t)

        # 4. Espacios. Se conservan los saltos de parrafo porque los usa el splitter
        #    como frontera natural; se colapsa lo demas.
        if self.colapsar:
            t = re.sub(r"[ \t]+", " ", t)
            t = re.sub(r"\n{3,}", "\n\n", t)
            t = re.sub(r" *\n *", "\n", t)
        return t.strip()

    def resumen(self) -> pd.DataFrame:
        return pd.DataFrame(
            [{"patron": p, "coincidencias_eliminadas": n} for p, n in self.conteo.items()]
        ).sort_values("coincidencias_eliminadas", ascending=False)


def procesar(cfg: Config, textos: dict[str, list[str]]
             ) -> tuple[list[Pagina], pd.DataFrame, pd.DataFrame]:
    """
    Limpia todas las paginas y produce el reporte de calidad de extraccion.

    Devuelve (paginas, reporte_por_documento, reporte_de_reglas).
    """
    limpiador = Limpiador(cfg)
    paginas: list[Pagina] = []
    filas = []

    for clave, fuente in cfg.fuentes.items():
        crudas = textos[clave]
        del_doc: list[Pagina] = []
        for i, crudo in enumerate(crudas, start=1):
            limpio = limpiador.limpiar(crudo)
            del_doc.append(Pagina(
                documento=clave,
                documento_desc=fuente.descripcion,
                version=fuente.version,
                tipo=fuente.tipo,
                pagina=i,                       # 1-indexado, como lo ve un humano en el PDF
                texto_crudo=crudo,
                texto=limpio,
            ))

        utiles = [p for p in del_doc if p.util]
        car_antes = sum(len(p.texto_crudo) for p in del_doc)
        car_despues = sum(len(p.texto) for p in del_doc)

        filas.append({
            "documento": clave,
            "descripcion": fuente.descripcion[:60],
            "version": fuente.version,
            "indexado": fuente.indexar,
            "paginas": len(del_doc),
            "paginas_utiles": len(utiles),
            "paginas_descartadas": len(del_doc) - len(utiles),
            "motivo_descarte": "menos de 40 caracteres tras limpiar (portada, separador o anexo vacio)",
            "caracteres_antes": car_antes,
            "caracteres_despues": car_despues,
            "pct_texto_eliminado": round(100 * (1 - car_despues / car_antes), 2) if car_antes else 0,
            "caracteres_por_pagina": round(car_despues / len(del_doc), 1) if del_doc else 0,
        })
        paginas.extend(del_doc)
        log.info("  %-22s %3d paginas (%d utiles) · %s car -> %s car (%.1f%% eliminado)",
                 clave, len(del_doc), len(utiles), f"{car_antes:,}", f"{car_despues:,}",
                 100 * (1 - car_despues / car_antes) if car_antes else 0)

    reporte = pd.DataFrame(filas)
    reglas = limpiador.resumen()
    return paginas, reporte, reglas


def guardar(cfg: Config, paginas: list[Pagina], reporte: pd.DataFrame,
            reglas: pd.DataFrame) -> None:
    """
    Escribe a data/processed/ el texto limpio y los reportes de la Fase 1.

    El formato es JSONL: una linea por pagina. Se eligio frente a un unico JSON porque
    permite leerlo en streaming y porque un fallo a mitad de escritura deja un archivo
    parcialmente valido en vez de uno corrupto entero.
    """
    d = cfg.processed_dir

    with open(d / "paginas.jsonl", "w", encoding="utf-8") as fh:
        for p in paginas:
            if not p.util:
                continue
            fh.write(json.dumps({
                "documento": p.documento,
                "documento_desc": p.documento_desc,
                "version": p.version,
                "tipo": p.tipo,
                "pagina": p.pagina,
                "texto": p.texto,
            }, ensure_ascii=False) + "\n")

    reporte.to_csv(d / "extraccion_calidad.csv", index=False, encoding="utf-8")
    reglas.to_csv(d / "limpieza_reglas.csv", index=False, encoding="utf-8")
    _guardar_antes_despues(cfg, paginas, d / "limpieza_antes_despues.md")
    log.info("  procesados -> %s", d)


def _guardar_antes_despues(cfg: Config, paginas: list[Pagina], destino: Path) -> None:
    """
    Guarda el ejemplo de antes y despues que el enunciado pide mostrar.

    Se elige la pagina con MAYOR reduccion porcentual de cada documento: es donde la
    limpieza hizo mas trabajo y donde mejor se ve el efecto en camara.
    """
    lineas = ["# Limpieza del texto — antes y despues", "",
              "Ejemplo real por documento. Se muestra la pagina en la que las reglas de",
              "limpieza eliminaron mas texto, que es donde mejor se aprecia su efecto.", ""]

    for clave in cfg.fuentes:
        del_doc = [p for p in paginas if p.documento == clave and len(p.texto_crudo) > 500]
        if not del_doc:
            continue
        peor = max(del_doc, key=lambda p: 1 - len(p.texto) / max(len(p.texto_crudo), 1))
        quitado = 100 * (1 - len(peor.texto) / max(len(peor.texto_crudo), 1))
        lineas += [
            f"## {clave} — pagina {peor.pagina}", "",
            f"Se elimino el **{quitado:.1f}%** de los caracteres "
            f"({len(peor.texto_crudo):,} -> {len(peor.texto):,}).", "",
            "**ANTES (crudo del PDF):**", "", "```",
            peor.texto_crudo[:900].strip(), "```", "",
            "**DESPUES (limpio):**", "", "```",
            peor.texto[:900].strip(), "```", "",
        ]
    destino.write_text("\n".join(lineas), encoding="utf-8")


def cargar_paginas(cfg: Config) -> list[dict]:
    """Relee data/processed/paginas.jsonl. Lo usa el chunking y la re-indexacion."""
    p = cfg.processed_dir / "paginas.jsonl"
    if not p.exists():
        raise FileNotFoundError(
            f"No existe {p}. Corre antes la Fase 1: python build_index.py --fase 1"
        )
    with open(p, encoding="utf-8") as fh:
        return [json.loads(linea) for linea in fh if linea.strip()]
