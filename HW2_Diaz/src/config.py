"""
Lectura de la configuracion del proyecto.

El enunciado exige que todo parametro (departamentos, rutas, whitelist de categorias,
umbrales) viva en `config.md` y que se pueda cambiar sin tocar codigo. Este modulo hace
literalmente eso: extrae los bloques ```toml de `config.md`, los concatena y los parsea
con `tomllib` (stdlib desde Python 3.11).

De esa forma `config.md` es a la vez documentacion legible para el lector del repositorio
y la unica fuente de verdad para el pipeline: no hay dos copias que se puedan desincronizar.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Raiz del repositorio = carpeta padre de src/
ROOT = Path(__file__).resolve().parent.parent
CONFIG_MD = ROOT / "config.md"

_BLOQUE_TOML = re.compile(r"```toml\s*\n(.*?)```", re.DOTALL)


class ConfigError(RuntimeError):
    """La configuracion no se pudo leer o esta incompleta."""


@dataclass
class Fuente:
    """Una fuente de datos declarada en config.md, con su cadena de respaldo de URLs."""

    clave: str
    descripcion: str
    archivo: str
    urls: list[str]
    licencia: str = ""
    cita: str = ""
    nota: str = ""
    opcional: bool = False


@dataclass
class Config:
    """Configuracion completa del pipeline, ya validada."""

    raw: dict[str, Any]
    root: Path

    # --- ambito ---
    departamentos: list[str] = field(default_factory=list)
    region_natural: dict[str, str] = field(default_factory=dict)

    # --- resolutivo ---
    categorias_resolutivas: list[str] = field(default_factory=list)
    estados_activos: list[str] = field(default_factory=list)
    categorias_no_resolutivas: list[str] = field(default_factory=list)
    categorias_ascendibles: list[str] = field(default_factory=list)

    # --- secciones que se consumen tal cual ---
    validacion: dict[str, Any] = field(default_factory=dict)
    demanda: dict[str, Any] = field(default_factory=dict)
    descarga: dict[str, Any] = field(default_factory=dict)
    ruteo: dict[str, Any] = field(default_factory=dict)
    metricas: dict[str, Any] = field(default_factory=dict)
    salida: dict[str, Any] = field(default_factory=dict)

    fuentes: dict[str, Fuente] = field(default_factory=dict)
    _rutas: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------ rutas
    def ruta(self, clave: str) -> Path:
        """Devuelve una ruta absoluta a partir de su clave en [rutas], creandola."""
        if clave not in self._rutas:
            raise ConfigError(f"Ruta '{clave}' no declarada en la seccion [rutas] de config.md")
        p = self.root / self._rutas[clave]
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def raw_dir(self) -> Path:
        return self.ruta("raw")

    @property
    def processed_dir(self) -> Path:
        return self.ruta("processed")

    @property
    def outputs_dir(self) -> Path:
        return self.ruta("outputs")

    @property
    def logs_dir(self) -> Path:
        return self.ruta("logs")

    @property
    def figuras_dir(self) -> Path:
        return self.ruta("figuras")

    @property
    def cache_dir(self) -> Path:
        return self.ruta("cache")

    # ------------------------------------------------------------- utilidades
    @property
    def bbox_peru(self) -> tuple[float, float, float, float]:
        """(lon_min, lat_min, lon_max, lat_max) del territorio peruano."""
        v = self.validacion
        return (v["lon_min"], v["lat_min"], v["lon_max"], v["lat_max"])

    def es_resolutiva(self, categoria: str, estado: str) -> bool:
        """Regla unica de capacidad resolutiva: activo Y categoria en el whitelist."""
        return estado in self.estados_activos and categoria in self.categorias_resolutivas

    def fuente(self, clave: str) -> Fuente:
        if clave not in self.fuentes:
            raise ConfigError(f"Fuente '{clave}' no declarada en config.md")
        return self.fuentes[clave]


def _extraer_toml(texto: str) -> str:
    bloques = _BLOQUE_TOML.findall(texto)
    if not bloques:
        raise ConfigError("config.md no contiene ningun bloque ```toml")
    return "\n\n".join(b.strip() for b in bloques)


def load_config(path: Path | str | None = None) -> Config:
    """
    Lee `config.md` y devuelve un objeto Config validado.

    Falla ruidosamente si falta una seccion obligatoria: es preferible detenerse aqui
    que arrastrar un valor por defecto silencioso a traves de todo el pipeline.
    """
    md = Path(path) if path else CONFIG_MD
    if not md.exists():
        raise ConfigError(f"No se encontro el archivo de configuracion: {md}")

    datos = tomllib.loads(_extraer_toml(md.read_text(encoding="utf-8")))

    faltantes = [s for s in ("ambito", "resolutivo", "validacion", "rutas", "fuentes")
                 if s not in datos]
    if faltantes:
        raise ConfigError(f"config.md: faltan las secciones {faltantes}")

    fuentes: dict[str, Fuente] = {}
    for clave, d in datos["fuentes"].items():
        if not d.get("urls"):
            raise ConfigError(f"La fuente '{clave}' no declara ninguna URL")
        fuentes[clave] = Fuente(
            clave=clave,
            descripcion=d.get("descripcion", clave),
            archivo=d["archivo"],
            urls=list(d["urls"]),
            licencia=d.get("licencia", ""),
            cita=d.get("cita", ""),
            nota=d.get("nota", ""),
            opcional=bool(d.get("opcional", False)),
        )

    ambito = datos["ambito"]
    res = datos["resolutivo"]
    cfg = Config(
        raw=datos,
        root=md.resolve().parent,
        departamentos=[d.upper() for d in ambito["departamentos"]],
        region_natural={k.upper(): v for k, v in ambito.get("region_natural", {}).items()},
        categorias_resolutivas=res["categorias"],
        estados_activos=res["estados_activos"],
        categorias_no_resolutivas=res.get("categorias_no_resolutivas", []),
        categorias_ascendibles=res.get("categorias_ascendibles", []),
        validacion=datos["validacion"],
        demanda=datos.get("demanda", {}),
        descarga=datos.get("descarga", {}),
        ruteo=datos.get("ruteo", {}),
        metricas=datos.get("metricas", {}),
        salida=datos.get("salida", {}),
        fuentes=fuentes,
        _rutas=datos["rutas"],
    )

    if not cfg.departamentos:
        raise ConfigError("config.md: [ambito].departamentos esta vacio")
    return cfg


if __name__ == "__main__":  # inspeccion rapida: python -m src.config
    c = load_config()
    print("departamentos :", c.departamentos)
    print("resolutivas   :", c.categorias_resolutivas)
    print("bbox Peru     :", c.bbox_peru)
    print("fuentes       :", list(c.fuentes))
    print("raw dir       :", c.raw_dir)
