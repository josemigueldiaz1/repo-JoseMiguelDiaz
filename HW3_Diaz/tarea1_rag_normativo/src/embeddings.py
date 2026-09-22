"""
Fases 2 y 4 — Embeddings: una interfaz, dos implementaciones.

El enunciado lo pide literalmente: "Your embeddings code must expose one common
interface with two implementations, so that switching models is a configuration change".
Aqui esa interfaz es la clase `Embedder`, y cambiar de modelo es cambiar
`embeddings.activo` en config.yaml. Ningun otro modulo sabe si detras hay un modelo
local o una API.

Dos detalles que el enunciado pide reportar explicitamente y que estan resueltos aqui:

1. **Prefijos distintos para consulta y pasaje.** La familia E5 (el modelo local
   elegido) exige anteponer "query: " a las preguntas y "passage: " a los fragmentos.
   Omitirlo no da ningun error: simplemente recupera peor, de forma silenciosa. Por eso
   la interfaz tiene DOS metodos (`codificar_pasajes` y `codificar_consultas`) en vez de
   uno solo: obliga a decir cual es cual en cada llamada.

2. **Limite de entrada del modelo.** multilingual-e5-small admite 512 tokens; los
   fragmentos de 900 caracteres caben con holgura (~250-300 tokens en espanol). Si se
   subiera el tamano de fragmento por encima de ~1800 caracteres, el modelo truncaria en
   silencio y la segunda mitad del fragmento dejaria de influir en el vector.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

import numpy as np

from .config import Config

log = logging.getLogger("hw3.t1.embeddings")


class Embedder(ABC):
    """Interfaz comun. El resto del sistema solo conoce estos metodos."""

    nombre: str
    modelo: str
    dimension: int
    max_tokens: int

    @abstractmethod
    def codificar_pasajes(self, textos: list[str]) -> np.ndarray:
        """Vectoriza fragmentos del corpus (lo que se indexa)."""

    @abstractmethod
    def codificar_consultas(self, textos: list[str]) -> np.ndarray:
        """Vectoriza preguntas del usuario (lo que se busca)."""

    # Coste y tiempo: la Fase 4 los compara entre modelos.
    tokens_consumidos: int = 0
    segundos: float = 0.0

    def costo_usd(self) -> float:
        return 0.0


# =============================================================================== local
class EmbedderLocal(Embedder):
    """
    Modelo local de sentence-transformers. Corre en CPU.

    Es el modelo principal, como exige el enunciado: "your main model must run locally".
    Se carga una sola vez y se reutiliza; en Streamlit eso lo garantiza
    `@st.cache_resource`.
    """

    def __init__(self, cfg: Config):
        c = cfg.embeddings("local")
        self.nombre = "local"
        self.modelo = c["modelo"]
        self.dimension = int(c["dimension"])
        self.max_tokens = int(c["max_tokens"])
        self._pref_consulta = c.get("prefijo_consulta", "")
        self._pref_pasaje = c.get("prefijo_pasaje", "")
        self._normalizar = bool(c.get("normalizar", True))
        self._lote = int(c.get("lote", 32))

        from sentence_transformers import SentenceTransformer  # import perezoso: es lento

        t0 = time.perf_counter()
        log.info("  cargando modelo local %s (la primera vez lo descarga)...", self.modelo)
        self._m = SentenceTransformer(self.modelo, device="cpu")
        log.info("  modelo listo en %.1fs · dimension %d · max %d tokens",
                 time.perf_counter() - t0, self.dimension, self.max_tokens)

    def _codificar(self, textos: list[str], prefijo: str) -> np.ndarray:
        t0 = time.perf_counter()
        v = self._m.encode(
            [prefijo + t for t in textos],
            batch_size=self._lote,
            normalize_embeddings=self._normalizar,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        self.segundos += time.perf_counter() - t0
        return v.astype(np.float32)

    def codificar_pasajes(self, textos: list[str]) -> np.ndarray:
        return self._codificar(textos, self._pref_pasaje)

    def codificar_consultas(self, textos: list[str]) -> np.ndarray:
        return self._codificar(textos, self._pref_consulta)


# ================================================================================= API
class EmbedderAPI(Embedder):
    """
    text-embedding-3-small de OpenAI. Solo se usa para la comparacion de la Fase 4.

    Se cobra por token, asi que lleva la cuenta de lo consumido para poder rellenar la
    columna de costo de la tabla comparativa con un numero real y no con una estimacion.
    """

    def __init__(self, cfg: Config):
        c = cfg.embeddings("api")
        self.nombre = "api"
        self.modelo = c["modelo"]
        self.dimension = int(c["dimension"])
        self.max_tokens = int(c["max_tokens"])
        self._lote = int(c.get("lote", 64))
        self._usd_millon = float(c.get("usd_por_millon_tokens", 0.02))
        self._normalizar = bool(c.get("normalizar", True))

        from openai import OpenAI

        self._cli = OpenAI(api_key=Config.credencial("OPENAI_API_KEY"))

    def _codificar(self, textos: list[str], _prefijo: str = "") -> np.ndarray:
        salida: list[list[float]] = []
        t0 = time.perf_counter()
        for i in range(0, len(textos), self._lote):
            lote = textos[i:i + self._lote]
            r = self._cli.embeddings.create(model=self.modelo, input=lote)
            salida.extend(d.embedding for d in r.data)
            self.tokens_consumidos += r.usage.total_tokens
        self.segundos += time.perf_counter() - t0

        v = np.asarray(salida, dtype=np.float32)
        if self._normalizar:
            # OpenAI ya devuelve vectores normalizados, pero no se da por supuesto: si
            # cambiara, el umbral calibrado sobre coseno dejaria de significar lo mismo.
            v /= np.linalg.norm(v, axis=1, keepdims=True).clip(min=1e-12)
        return v

    def codificar_pasajes(self, textos: list[str]) -> np.ndarray:
        return self._codificar(textos)

    def codificar_consultas(self, textos: list[str]) -> np.ndarray:
        return self._codificar(textos)

    def costo_usd(self) -> float:
        return self.tokens_consumidos / 1e6 * self._usd_millon


# ============================================================================== fabrica
def crear(cfg: Config, cual: str | None = None) -> Embedder:
    """
    Devuelve el embedder pedido, o el declarado como activo en config.yaml.

    Este es el unico sitio del proyecto donde se decide que implementacion se usa.
    """
    c = cfg.embeddings(cual)
    if c["_nombre"] == "local":
        return EmbedderLocal(cfg)
    return EmbedderAPI(cfg)
