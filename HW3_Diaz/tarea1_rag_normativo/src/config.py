"""
Lectura de la configuracion de la Tarea 1.

El enunciado es explicito: "Every path, model name, chunk size, threshold, prompt and
user-facing message lives in a configuration file". Este modulo es el unico punto por
el que el resto del codigo accede a esos valores, de modo que no exista ninguna
constante repetida entre modulos que se pueda desincronizar.

Falla ruidosamente si falta una seccion obligatoria. Es preferible detenerse aqui, con
un mensaje que dice exactamente que falta, a arrastrar un valor por defecto silencioso
hasta el final del pipeline y descubrirlo cuando los numeros ya son incorrectos.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any

import yaml

# Raiz de la tarea = carpeta padre de src/
ROOT = Path(__file__).resolve().parent.parent
CONFIG_YAML = ROOT / "config.yaml"

SECCIONES_OBLIGATORIAS = (
    "rutas", "fuentes", "source_check", "limpieza", "chunking",
    "embeddings", "indice", "motor", "costos", "evaluacion",
)


class ConfigError(RuntimeError):
    """La configuracion no se pudo leer o esta incompleta."""


@dataclass
class Fuente:
    """Un documento normativo declarado en config.yaml."""

    clave: str
    descripcion: str
    tipo: str
    institucion: str
    version: str
    archivo: str
    url: str
    pagina_fuente: str
    indexar: bool
    modifica: str = ""

    @property
    def es_modificatoria(self) -> bool:
        """True si esta norma modifica a otra.

        Lo usa el motor para anadir la nota de version que pide la Fase 3: una
        respuesta construida sobre un decreto modificatorio esta incompleta si se
        presenta como si fuera la regla entera.
        """
        return bool(self.modifica) or self.tipo == "decreto_modificatorio"


@dataclass
class Config:
    """Configuracion completa de la Tarea 1, ya validada."""

    raw: dict[str, Any]
    root: Path
    fuentes: dict[str, Fuente] = field(default_factory=dict)

    # ------------------------------------------------------------------ rutas
    def ruta(self, clave: str) -> Path:
        """Ruta absoluta a partir de su clave en [rutas]. La crea si no existe."""
        rutas = self.raw["rutas"]
        if clave not in rutas:
            raise ConfigError(f"Ruta '{clave}' no declarada en la seccion 'rutas' de config.yaml")
        p = self.root / rutas[clave]
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def raw_dir(self) -> Path:
        return self.ruta("raw")

    @property
    def processed_dir(self) -> Path:
        return self.ruta("processed")

    @property
    def index_dir(self) -> Path:
        return self.ruta("index")

    @property
    def logs_dir(self) -> Path:
        return self.ruta("logs")

    @property
    def eval_dir(self) -> Path:
        return self.ruta("eval")

    # --------------------------------------------------------- accesos comunes
    @property
    def motor(self) -> dict[str, Any]:
        return self.raw["motor"]

    @property
    def chunking(self) -> dict[str, Any]:
        return self.raw["chunking"]

    @property
    def indice(self) -> dict[str, Any]:
        return self.raw["indice"]

    @property
    def costos(self) -> dict[str, Any]:
        return self.raw["costos"]

    def embeddings(self, cual: str | None = None) -> dict[str, Any]:
        """Parametros del modelo de embeddings 'local' o 'api'.

        Sin argumento devuelve el que este activo, que es como lo consume el motor:
        cambiar de modelo debe ser un cambio de configuracion, no de codigo.
        """
        emb = self.raw["embeddings"]
        cual = cual or emb.get("activo", "local")
        if cual not in ("local", "api"):
            raise ConfigError(f"embeddings.{cual} no existe; usa 'local' o 'api'")
        d = dict(emb[cual])
        d["_nombre"] = cual
        return d

    def fuentes_indexables(self) -> list[Fuente]:
        """Solo las fuentes que entran al indice.

        El Reglamento queda fuera a proposito: es el control con el que se demuestra
        que el asistente reconoce los limites de su corpus.
        """
        return [f for f in self.fuentes.values() if f.indexar]

    # ------------------------------------------------------------- credenciales
    @staticmethod
    def credencial(nombre: str, obligatoria: bool = True) -> str:
        """
        Lee una credencial del entorno (que `run_all.py` carga desde .env).

        Se usa `os.environ[...]` deliberadamente en el caso obligatorio: si la variable
        falta, revienta aqui con un mensaje claro, en lugar de mandar `None` a la API y
        recibir un 401 que no dice nada sobre la causa real.
        """
        if obligatoria:
            v = os.environ.get(nombre)
            if not v:
                raise ConfigError(
                    f"Falta la variable {nombre}. Copia .env.example como .env y rellenala."
                )
            return v
        return os.environ.get(nombre, "")

    # ------------------------------------------------------- precios por hora
    def tarifa_vigente(self, momento: datetime | None = None) -> tuple[str, dict[str, float]]:
        """
        Devuelve ('pico'|'valle', precios) segun la hora UTC del momento indicado.

        La Fase 3 pide explicitamente que el calculo de costo aplique el precio que
        corresponde a la hora de cada llamada. DeepSeek cobra la mitad fuera de sus
        franjas pico, y esas franjas se definen en UTC de lunes a viernes: una misma
        consulta puede costar el doble segun cuando se lance.
        """
        c = self.costos
        ahora = (momento or datetime.now(timezone.utc)).astimezone(timezone.utc)

        es_habil = ahora.weekday() < 5
        en_pico = False
        if es_habil or not c.get("solo_dias_habiles", True):
            for franja in c.get("horas_pico_utc", []):
                h1, m1 = (int(x) for x in str(franja["desde"]).split(":"))
                h2, m2 = (int(x) for x in str(franja["hasta"]).split(":"))
                if time(h1, m1) <= ahora.time() < time(h2, m2):
                    en_pico = True
                    break

        franja = "pico" if en_pico else "valle"
        return franja, c["precios_por_millon"][franja]


def load_config(path: Path | str | None = None,
                secciones: tuple[str, ...] | None = None,
                cls: type[Config] = Config) -> Config:
    """
    Lee un config.yaml y devuelve un objeto Config validado.

    `secciones` y `cls` existen para que la Tarea 2 pueda reutilizar este mismo lector
    con su propio esquema y su propia subclase de Config, en vez de escribir un segundo
    cargador casi identico que despues habria que mantener por duplicado.
    """
    ruta = Path(path) if path else CONFIG_YAML
    if not ruta.exists():
        raise ConfigError(f"No se encontro el archivo de configuracion: {ruta}")

    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    if not isinstance(datos, dict):
        raise ConfigError(f"{ruta.name} no contiene un mapeo YAML valido")

    obligatorias = secciones if secciones is not None else SECCIONES_OBLIGATORIAS
    faltan = [s for s in obligatorias if s not in datos]
    if faltan:
        raise ConfigError(f"{ruta.name}: faltan las secciones {faltan}")

    fuentes: dict[str, Fuente] = {}
    for clave, d in (datos.get("fuentes") or {}).items():
        # La Tarea 2 declara sus fuentes de otra forma (endpoints, no PDFs), asi que
        # solo se convierten a `Fuente` las que tengan la forma documental.
        if not isinstance(d, dict) or "archivo" not in d:
            continue
        try:
            fuentes[clave] = Fuente(
                clave=clave,
                descripcion=d["descripcion"],
                tipo=d.get("tipo", ""),
                institucion=d.get("institucion", ""),
                version=str(d.get("version", "")),
                archivo=d["archivo"],
                url=d["url"],
                pagina_fuente=d.get("pagina_fuente", ""),
                indexar=bool(d.get("indexar", True)),
                modifica=d.get("modifica", ""),
            )
        except KeyError as e:
            raise ConfigError(f"La fuente '{clave}' no declara el campo {e}") from e

    cfg = cls(raw=datos, root=ruta.resolve().parent, fuentes=fuentes)

    if fuentes and not cfg.fuentes_indexables():
        raise ConfigError("Ninguna fuente tiene 'indexar: true': el indice quedaria vacio")
    return cfg


if __name__ == "__main__":  # inspeccion rapida: python -m src.config
    c = load_config()
    print("fuentes        :", list(c.fuentes))
    print("  indexables   :", [f.clave for f in c.fuentes_indexables()])
    print("embeddings     :", c.embeddings()["modelo"])
    print("umbral         :", c.motor["umbral_similitud"])
    franja, precios = c.tarifa_vigente()
    print(f"tarifa ahora   : {franja}  {precios}")
