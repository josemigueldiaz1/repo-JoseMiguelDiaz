"""
Fase 1 — Adquisicion de datos.

Descarga las fuentes declaradas en `config.md` hacia `data/raw/` y deja constancia de
cada descarga en un manifiesto (`data/raw/_manifest.json`) con URL efectiva, fecha,
tamano y SHA-256.

Decisiones de diseno que responden al enunciado:

* **Re-ejecutable sin costo.** Si el archivo ya esta y coincide con el tamano que anuncia
  el servidor, no se vuelve a descargar. Volver a correr el pipeline no re-descarga 250 MB.
* **Cadena de respaldo.** Cada fuente declara una lista de URLs; se intenta en orden y se
  registra cual funciono. Cubre el escenario, explicitamente previsto por el enunciado, de
  portales de datos peruanos caidos o sin URL directa.
* **Escritura atomica.** Se baja a `<archivo>.part` y se renombra al terminar. Una descarga
  interrumpida (Ctrl-C, caida de red) nunca deja un archivo truncado que la siguiente
  corrida daria por bueno.
* **User-Agent de navegador.** `datosabiertos.gob.pe` responde **HTTP 418** a clientes sin
  User-Agent reconocible; con el header por defecto de `urllib`/`requests` la descarga falla.
* **Trazabilidad.** El SHA-256 y la fecha de descarga permiten citar en el informe la
  version exacta de los datos usados, requisito del enunciado ("access dates").
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

from .config import Config, Fuente

log = logging.getLogger(__name__)

MANIFIESTO = "_manifest.json"


# --------------------------------------------------------------------------- utilidades
def sha256(path: Path, chunk: int = 1 << 20) -> str:
    """SHA-256 del archivo, leido por bloques para no cargarlo entero en memoria."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for bloque in iter(lambda: fh.read(chunk), b""):
            h.update(bloque)
    return h.hexdigest()


def _tamano_remoto(url: str, headers: dict, timeout: int) -> int | None:
    """Content-Length de la URL, o None si el servidor no lo declara."""
    try:
        r = requests.head(url, headers=headers, timeout=min(timeout, 60), allow_redirects=True)
        if r.ok and "Content-Length" in r.headers:
            return int(r.headers["Content-Length"])
    except requests.RequestException:
        pass
    return None


def _descargar_a(url: str, destino: Path, headers: dict, timeout: int) -> None:
    """Descarga con escritura atomica y progreso cada 10 MB."""
    parcial = destino.with_suffix(destino.suffix + ".part")
    parcial.unlink(missing_ok=True)

    with requests.get(url, headers=headers, timeout=timeout, stream=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        bajado = 0
        hito = 10 << 20  # log cada 10 MB para que una descarga larga no parezca colgada
        siguiente = hito
        with parcial.open("wb") as fh:
            for bloque in r.iter_content(chunk_size=1 << 20):
                if not bloque:
                    continue
                fh.write(bloque)
                bajado += len(bloque)
                if bajado >= siguiente:
                    pct = f" ({bajado / total:.0%})" if total else ""
                    log.info("      ... %.1f MB%s", bajado / 1e6, pct)
                    siguiente += hito

    parcial.replace(destino)


# ------------------------------------------------------------------------------ manifiesto
def _leer_manifiesto(raw_dir: Path) -> dict:
    p = raw_dir / MANIFIESTO
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("Manifiesto ilegible, se reconstruye: %s", p)
    return {}


def _escribir_manifiesto(raw_dir: Path, man: dict) -> None:
    (raw_dir / MANIFIESTO).write_text(
        json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# --------------------------------------------------------------------------------- API
def obtener_fuente(cfg: Config, fuente: Fuente, forzar: bool = False) -> Path | None:
    """
    Garantiza que `fuente` este en `data/raw/`. Devuelve la ruta, o None si la fuente es
    opcional y no se pudo obtener.

    Recorre la cadena de URLs en orden hasta que una funcione. Registra en el manifiesto
    cual se uso realmente y cuando.
    """
    d = cfg.descarga
    raw_dir = cfg.raw_dir
    destino = raw_dir / fuente.archivo
    headers = {"User-Agent": d.get("user_agent", "Mozilla/5.0")}
    timeout = int(d.get("timeout_seg", 600))
    reintentos = int(d.get("reintentos", 3))
    espera = float(d.get("espera_entre_reintentos_seg", 5))

    man = _leer_manifiesto(raw_dir)

    # ---- ya lo tenemos? ----
    if destino.exists() and d.get("saltar_si_existe", True) and not forzar:
        esperado = _tamano_remoto(fuente.urls[0], headers, timeout)
        real = destino.stat().st_size
        if esperado is None or esperado == real:
            log.info("  [cache] %-22s ya existe (%.1f MB), no se re-descarga",
                     fuente.clave, real / 1e6)
            # Si falta en el manifiesto (p. ej. archivo copiado a mano), lo registramos.
            if fuente.clave not in man:
                man[fuente.clave] = {
                    "archivo": fuente.archivo,
                    "url_efectiva": "(preexistente en data/raw)",
                    "fecha_descarga_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "bytes": real,
                    "sha256": sha256(destino),
                    "licencia": fuente.licencia,
                    "cita": fuente.cita,
                }
                _escribir_manifiesto(raw_dir, man)
            return destino
        log.warning("  [cache] %s existe pero pesa %.1f MB y el servidor anuncia %.1f MB; "
                    "se vuelve a descargar", fuente.clave, real / 1e6, esperado / 1e6)

    # ---- descargar recorriendo la cadena de respaldo ----
    ultimo_error: Exception | None = None
    for i, url in enumerate(fuente.urls, 1):
        etiqueta = "primaria" if i == 1 else f"respaldo {i - 1}"
        for intento in range(1, reintentos + 1):
            try:
                log.info("  [get]   %-22s %s (intento %d/%d)",
                         fuente.clave, etiqueta, intento, reintentos)
                log.info("          %s", url)
                _descargar_a(url, destino, headers, timeout)
                man[fuente.clave] = {
                    "archivo": fuente.archivo,
                    "url_efectiva": url,
                    "url_es_respaldo": i > 1,
                    "fecha_descarga_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "bytes": destino.stat().st_size,
                    "sha256": sha256(destino),
                    "licencia": fuente.licencia,
                    "cita": fuente.cita,
                }
                _escribir_manifiesto(raw_dir, man)
                log.info("  [ok]    %-22s %.1f MB", fuente.clave, destino.stat().st_size / 1e6)
                return destino
            except Exception as e:  # noqa: BLE001 — se reintenta con cualquier fallo de red
                ultimo_error = e
                log.warning("          fallo: %s", e)
                if intento < reintentos:
                    time.sleep(espera)

    if fuente.opcional:
        log.warning("  [skip]  %s es opcional y no se pudo descargar (%s)",
                    fuente.clave, ultimo_error)
        return None
    raise RuntimeError(
        f"No se pudo obtener la fuente obligatoria '{fuente.clave}' tras agotar "
        f"{len(fuente.urls)} URL(s). Ultimo error: {ultimo_error}"
    )


def descomprimir(zip_path: Path, destino: Path, forzar: bool = False) -> Path:
    """
    Extrae un .zip a `destino/<nombre>/` y devuelve esa carpeta.

    No re-extrae si la carpeta ya tiene contenido: igual que la descarga, el paso debe
    ser barato al re-ejecutarse.
    """
    carpeta = destino / zip_path.stem
    if carpeta.exists() and any(carpeta.iterdir()) and not forzar:
        log.info("  [cache] %s ya descomprimido", zip_path.name)
        return carpeta
    if forzar and carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(carpeta)
    log.info("  [unzip] %s -> %s", zip_path.name, carpeta.name)
    return carpeta


def buscar_shapefile(carpeta: Path) -> Path:
    """Primer .shp dentro de la carpeta (los zips del IGN traen uno solo)."""
    shps = sorted(carpeta.rglob("*.shp"))
    if not shps:
        raise FileNotFoundError(f"No se encontro ningun .shp dentro de {carpeta}")
    if len(shps) > 1:
        log.warning("  %d shapefiles en %s; se usa %s", len(shps), carpeta.name, shps[0].name)
    return shps[0]


def adquirir_todo(
    cfg: Config,
    con_osm: bool = False,
    con_pop_alta_res: bool = False,
    forzar: bool = False,
) -> dict[str, Path]:
    """
    Descarga todas las fuentes no opcionales (y las opcionales que se pidan).

    Devuelve un dict {clave_fuente: ruta}. Las fuentes opcionales que fallaron no aparecen.
    """
    log.info("-" * 70)
    log.info("FASE 1.1 — Adquisicion de datos")
    log.info("-" * 70)

    # Fuentes opcionales y pesadas: solo se bajan si se piden explicitamente.
    omitir_salvo_flag = {
        "osm": (con_osm, "--with-osm", "244 MB del extracto OSM"),
        "poblacion_raster_alta_res": (con_pop_alta_res, "--hi-res-pop",
                                      "596 MB del raster unconstrained"),
    }

    rutas: dict[str, Path] = {}
    for clave, fuente in cfg.fuentes.items():
        if clave in omitir_salvo_flag:
            pedido, flag, peso = omitir_salvo_flag[clave]
            if not pedido:
                log.info("  [skip]  %-22s omitido (usa %s para bajar los %s)",
                         clave, flag, peso)
                continue
        p = obtener_fuente(cfg, fuente, forzar=forzar)
        if p is not None:
            rutas[clave] = p

    # Los shapefiles vienen comprimidos; se dejan listos para leer.
    for clave in ("centros_poblados", "distritos"):
        if clave in rutas and rutas[clave].suffix.lower() == ".zip":
            rutas[f"{clave}_dir"] = descomprimir(rutas[clave], cfg.raw_dir, forzar=forzar)

    log.info("Adquisicion completa: %d archivo(s) disponibles en %s",
             len([k for k in rutas if not k.endswith("_dir")]), cfg.raw_dir)
    return rutas
