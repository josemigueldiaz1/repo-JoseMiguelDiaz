"""
Configuracion de la Tarea 2.

Es una **subclase** del `Config` de la Tarea 1, no una copia. Esa decision es la que
hace posible que `IndiceVectorial`, `EmbedderLocal` y `RegistroCostos` —escritos para la
Tarea 1— funcionen aqui sin tocar una linea: reciben un objeto que ya sabe responder a
`index_dir`, `embeddings()`, `costos` y `tarifa_vigente()`.

Lo unico que anade esta subclase son las rutas y secciones propias del radar.
"""

from __future__ import annotations

import sys
from pathlib import Path

HW3 = Path(__file__).resolve().parent.parent.parent
if str(HW3) not in sys.path:
    sys.path.insert(0, str(HW3))

from tarea1_rag_normativo.src.config import (  # noqa: E402
    Config as ConfigBase,
    ConfigError,
    load_config as _load_config_base,
)

ROOT = Path(__file__).resolve().parent.parent
CONFIG_YAML = ROOT / "config.yaml"

SECCIONES_OBLIGATORIAS = (
    "rutas", "adquisicion", "columnas", "validacion", "riesgo",
    "territorio", "embeddings", "indice", "motor", "costos", "evaluacion",
)


class Config(ConfigBase):
    """Config de la Tarea 2. Hereda rutas, credenciales y tarifas horarias."""

    # ------------------------------------------------------------------ rutas
    @property
    def outputs_dir(self) -> Path:
        return self.ruta("outputs")

    # --------------------------------------------------------- accesos propios
    @property
    def adquisicion(self) -> dict:
        return self.raw["adquisicion"]

    @property
    def validacion(self) -> dict:
        return self.raw["validacion"]

    @property
    def riesgo(self) -> dict:
        return self.raw["riesgo"]

    @property
    def territorio(self) -> dict:
        return self.raw["territorio"]

    def columnas(self, tabla: str) -> dict[str, str]:
        """Mapeo de cabeceras largas de OECE a nombres cortos, por tabla."""
        c = self.raw["columnas"]
        if tabla not in c:
            raise ConfigError(f"No hay mapeo de columnas para la tabla '{tabla}'")
        return dict(c[tabla])

    @property
    def departamentos(self) -> list[str]:
        return list(self.validacion["departamentos"])

    def meses(self) -> list[tuple[int, str]]:
        """Los meses a descargar, como (anio, 'MM')."""
        return [(int(m["anio"]), str(m["mes"]).zfill(2))
                for m in self.adquisicion["meses"]]


def load_config(path: Path | str | None = None) -> Config:
    """Lee el config.yaml de la Tarea 2 reutilizando el lector de la Tarea 1."""
    return _load_config_base(path or CONFIG_YAML,
                             secciones=SECCIONES_OBLIGATORIAS,
                             cls=Config)


if __name__ == "__main__":  # python -m src.config
    c = load_config()
    print("meses         :", c.meses())
    print("departamentos :", len(c.departamentos))
    print("umbral T2     :", c.motor["umbral_similitud"],
          "(T1 era", c.motor["umbral_tarea1"], ")")
    print("api           :", c.adquisicion["api_base"])
    franja, precios = c.tarifa_vigente()
    print("tarifa ahora  :", franja, precios)
