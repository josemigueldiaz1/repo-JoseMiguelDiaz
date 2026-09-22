"""
Fase 2 — Indice vectorial persistente sobre ChromaDB.

**Por que ChromaDB y no FAISS.** FAISS es mas rapido en corpus grandes, pero guarda solo
los vectores: los metadatos (documento, pagina, version) hay que mantenerlos en una
estructura paralela y sincronizarla a mano. En este proyecto la cita "documento, pagina"
es un requisito central, y una desincronizacion entre el vector y su metadato produciria
citas incorrectas sin dar ningun error. ChromaDB guarda vector y metadatos juntos, y
ademas persiste solo con indicarle una carpeta. Con corpus de ~500 fragmentos la ventaja
de velocidad de FAISS es irrelevante; la seguridad de la cita, no.

**Idempotencia y reanudacion.** Antes de insertar se consulta que IDs ya existen y se
insertan solo los que faltan. De ahi salen las dos propiedades que pide el enunciado:
correr dos veces no duplica nada, y una corrida interrumpida continua donde quedo. Como
los IDs llevan el nombre del documento como prefijo, anadir un documento nuevo no puede
pisar ni saltarse los fragmentos de otro.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import chromadb
import numpy as np
from chromadb.config import Settings

from .chunking import Fragmento
from .config import Config
from .embeddings import Embedder

log = logging.getLogger("hw3.t1.indice")


@dataclass
class Recuperado:
    """Un fragmento devuelto por una busqueda, con su similitud."""

    id: str
    texto: str
    documento: str
    documento_desc: str
    version: str
    pagina: int
    es_modificatoria: bool
    similitud: float

    @property
    def cita(self) -> str:
        return f"[{self.documento}, p. {self.pagina}]"


class IndiceVectorial:
    """Envoltorio sobre una coleccion de ChromaDB."""

    def __init__(self, cfg: Config, embedder: Embedder, coleccion: str | None = None):
        self.cfg = cfg
        self.emb = embedder
        c = cfg.indice
        nombre = coleccion or (c["coleccion"] if embedder.nombre == "local"
                               else c["coleccion_api"])
        self.nombre = nombre

        self._cli = chromadb.PersistentClient(
            path=str(cfg.index_dir),
            settings=Settings(anonymized_telemetry=False, allow_reset=True),
        )
        self._col = self._cli.get_or_create_collection(
            name=nombre,
            metadata={"hnsw:space": c.get("metrica", "cosine")},
        )

    # ------------------------------------------------------------------ escritura
    def ids_existentes(self) -> set[str]:
        """IDs ya presentes. Es la base de la idempotencia."""
        try:
            return set(self._col.get(include=[])["ids"])
        except Exception:  # noqa: BLE001 — coleccion recien creada
            return set()

    def indexar(self, fragmentos: list[Fragmento], lote: int = 128) -> dict:
        """
        Inserta los fragmentos que falten. Devuelve estadisticas de la operacion.

        No borra nada: si un fragmento desaparece del corpus, su vector queda huerfano.
        Se asume que un cambio de corpus se acompana de `--reconstruir`, que borra la
        coleccion entera. Es preferible a un borrado automatico que podria eliminar
        datos por un fallo transitorio de lectura.
        """
        existentes = self.ids_existentes()
        pendientes = [f for f in fragmentos if f.id not in existentes]

        if not pendientes:
            log.info("  '%s' ya contiene los %d fragmentos; no se reindexa",
                     self.nombre, len(fragmentos))
            return {"insertados": 0, "ya_estaban": len(fragmentos), "segundos": 0.0}

        log.info("  '%s': %d fragmentos nuevos de %d (%d ya estaban)",
                 self.nombre, len(pendientes), len(fragmentos), len(existentes))

        t0 = time.perf_counter()
        for i in range(0, len(pendientes), lote):
            grupo = pendientes[i:i + lote]
            vectores = self.emb.codificar_pasajes([f.texto for f in grupo])
            self._col.add(
                ids=[f.id for f in grupo],
                documents=[f.texto for f in grupo],
                embeddings=[v.tolist() for v in vectores],
                metadatas=[f.metadatos() for f in grupo],
            )
            log.info("    %d/%d", min(i + lote, len(pendientes)), len(pendientes))

        dt = time.perf_counter() - t0
        return {"insertados": len(pendientes), "ya_estaban": len(existentes), "segundos": dt}

    def vaciar(self) -> None:
        """Borra la coleccion. Solo se invoca con --reconstruir explicito."""
        try:
            self._cli.delete_collection(self.nombre)
        except Exception:  # noqa: BLE001
            pass
        self._col = self._cli.get_or_create_collection(
            name=self.nombre,
            metadata={"hnsw:space": self.cfg.indice.get("metrica", "cosine")},
        )
        log.info("  coleccion '%s' vaciada", self.nombre)

    # ------------------------------------------------------------------ lectura
    def __len__(self) -> int:
        return self._col.count()

    def buscar(self, pregunta: str, k: int = 5, filtro: dict | None = None
               ) -> list[Recuperado]:
        """
        Busca los k fragmentos mas parecidos.

        ChromaDB devuelve DISTANCIA coseno; el resto del sistema razona en SIMILITUD.
        La conversion (1 - distancia) se hace aqui y en un solo sitio: tener las dos
        magnitudes circulando por el codigo es la via rapida a comparar un umbral contra
        el numero equivocado, que es un error que no da excepcion, solo resultados malos.
        """
        v = self.emb.codificar_consultas([pregunta])[0]
        r = self._col.query(
            query_embeddings=[v.tolist()],
            n_results=min(k, max(len(self), 1)),
            where=filtro,
            include=["documents", "metadatas", "distances"],
        )
        if not r["ids"] or not r["ids"][0]:
            return []

        salida = []
        for i, fid in enumerate(r["ids"][0]):
            m = r["metadatas"][0][i]
            salida.append(Recuperado(
                id=fid,
                texto=r["documents"][0][i],
                documento=m.get("documento", "?"),
                documento_desc=m.get("documento_desc", ""),
                version=str(m.get("version", "")),
                pagina=int(m.get("pagina", 0)),
                es_modificatoria=bool(m.get("es_modificatoria", False)),
                similitud=float(1.0 - r["distances"][0][i]),
            ))
        return salida

    def vectores_y_textos(self) -> tuple[np.ndarray, list[str], list[dict]]:
        """Vuelca la coleccion. Lo usa la evaluacion para no re-embeder en cada pregunta."""
        d = self._col.get(include=["documents", "metadatas", "embeddings"])
        return (np.asarray(d["embeddings"], dtype=np.float32),
                list(d["documents"]), list(d["metadatas"]))
