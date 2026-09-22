"""
Fase 1 — Adquisicion de los datos abiertos de contrataciones (OCDS / OECE).

**Como se encontro la fuente.** El portal https://contratacionesabiertas.oece.gob.pe es
una aplicacion Angular: las tres rutas del enunciado devuelven exactamente el mismo
HTML de 2,837 bytes, sin un solo enlace de descarga, porque el contenido lo construye
JavaScript en el navegador. En vez de automatizar un navegador, se localizo la API que
consume la propia aplicacion inspeccionando su bundle `main.*.js`. Detalle completo en
logs/incidencias.md (I-01).

**Que es un release, que es un record y que es un ocid** (el enunciado pide saber
explicarlo):

- El **ocid** (Open Contracting ID) identifica **un proceso de contratacion completo**,
  desde que se planifica hasta que se liquida. Es el hilo que cose todo. Ejemplo real:
  `ocds-dgv273-seacev3-1251159`.
- Un **release** es *una novedad* sobre ese proceso: se convoco, se adjudico, se firmo
  el contrato. Un mismo proceso genera muchos releases a lo largo de su vida.
- Un **record** (o *compiled release*) es la **foto actual** del proceso: el resultado
  de aplicar todos sus releases en orden. Es lo que interesa para un radar de
  oportunidades, porque responde "¿en que estado esta hoy?" en vez de "¿que paso el
  martes?".

Los bulk mensuales de OECE (`Registros.csv`) contienen compiled releases, es decir
records. Por eso la unidad de analisis de este proyecto es **una fila por ocid**.

**Por que bulk y no API para el corpus.** El enunciado pide justificarlo. La API pagina
de 10 en 10 registros: reunir 20,000 procesos exigiria ~2,000 peticiones. El bulk
mensual son 8.7 MB en UNA peticion. La API se usa para lo que si es buena —consultar
novedades recientes y un proceso concreto por su ocid— y el bulk para el volumen.
"""

from __future__ import annotations

import io
import logging
import time
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path

import pandas as pd
import requests

from .config import Config

log = logging.getLogger("hw3.t2.adquisicion")


@dataclass
class DescargaMes:
    """Registro de la descarga de un mes. El enunciado pide log de tiempo, peticiones y tamanos."""

    mes: str
    url: str
    archivo: str
    mb: float
    segundos: float
    peticiones: int
    desde_cache: bool
    sha_verificado: bool


class ClienteOECE:
    """Cliente HTTP con throttling y reintentos sobre la API de contrataciones abiertas."""

    def __init__(self, cfg: Config):
        a = cfg.adquisicion
        self.base = a["api_base"].rstrip("/")
        self.espera = float(a.get("segundos_entre_peticiones", 1.0))
        self.timeout = int(a.get("timeout_seg", 600))
        self.reintentos = int(a.get("reintentos", 3))
        self.ses = requests.Session()
        self.ses.headers.update({"User-Agent": a["user_agent"],
                                 "Accept": "application/json"})
        self.n_peticiones = 0
        self.segundos_red = 0.0
        self._ultima = 0.0

    def _throttle(self) -> None:
        """
        Espera lo que falte para respetar el intervalo declarado.

        Es una cortesia con un servicio publico gratuito, y ademas evita que una rafaga
        de peticiones acabe en un bloqueo temporal que costaria mas tiempo del que se
        ahorro.
        """
        dt = time.perf_counter() - self._ultima
        if dt < self.espera:
            time.sleep(self.espera - dt)
        self._ultima = time.perf_counter()

    def get(self, ruta: str, params: dict | None = None, stream: bool = False,
            url_absoluta: str | None = None) -> requests.Response:
        url = url_absoluta or f"{self.base}{ruta}"
        ultimo: Exception | None = None
        for intento in range(1, self.reintentos + 1):
            self._throttle()
            t0 = time.perf_counter()
            try:
                r = self.ses.get(url, params=params, timeout=self.timeout, stream=stream)
                self.n_peticiones += 1
                self.segundos_red += time.perf_counter() - t0
                r.raise_for_status()
                return r
            except Exception as e:  # noqa: BLE001
                ultimo = e
                log.warning("  peticion fallida (%d/%d): %s", intento, self.reintentos,
                            str(e)[:110])
                time.sleep(2 * intento)
        raise RuntimeError(f"No se pudo obtener {url} tras {self.reintentos} intentos: {ultimo}")

    def catalogo(self, paginar_por: int = 50) -> pd.DataFrame:
        """Meses disponibles, con sus URLs de descarga en cada formato."""
        d = self.get("/files", params={"page": 1, "paginateBy": paginar_por}).json()
        filas = []
        for r in d.get("results", []):
            filas.append({"id": r["id"], "fuente": r["source"], "anio": r["year"],
                          "mes": r["month"], "mes_nombre": r.get("monthName", ""),
                          "actualizado": r.get("timestamp", ""), **r["files"]})
        return pd.DataFrame(filas)


# ============================================================================= descarga
def descargar_meses(cfg: Config, cliente: ClienteOECE | None = None,
                    forzar: bool = False) -> tuple[list[DescargaMes], pd.DataFrame]:
    """
    Descarga los meses declarados en config.yaml. Re-ejecutable y con cache.

    El enunciado pide que "the download step is re-runnable and never downloads what
    already exists": si el ZIP ya esta en data/raw, no se vuelve a pedir.
    """
    cliente = cliente or ClienteOECE(cfg)
    a = cfg.adquisicion
    raw = cfg.raw_dir

    log.info("Consultando el catalogo de archivos mensuales...")
    cat = cliente.catalogo()
    log.info("  %d meses disponibles (de %s-%s a %s-%s)", len(cat),
             cat.iloc[-1]["anio"], cat.iloc[-1]["mes"], cat.iloc[0]["anio"], cat.iloc[0]["mes"])

    clave_formato = a["formato"] + ("_es" if a.get("idioma") == "es" else "")
    registros: list[DescargaMes] = []

    for anio, mes in cfg.meses():
        etiqueta = f"{anio}-{mes}"
        fila = cat[(cat["anio"] == str(anio)) & (cat["mes"] == mes)
                   & (cat["fuente"] == a["fuente"])]
        if fila.empty:
            raise RuntimeError(
                f"El mes {etiqueta} no esta en el catalogo de OECE. "
                f"Meses disponibles: {', '.join(cat['id'].head(12))}"
            )
        fila = fila.iloc[0]
        url = fila[clave_formato]
        destino = raw / f"{etiqueta}_{a['fuente']}_{clave_formato}.zip"

        if destino.exists() and not forzar:
            log.info("  %s  ya descargado (%.1f MB)", etiqueta, destino.stat().st_size / 1e6)
            registros.append(DescargaMes(etiqueta, url, destino.name,
                                         round(destino.stat().st_size / 1e6, 2),
                                         0.0, 0, True, False))
            continue

        t0 = time.perf_counter()
        peticiones_antes = cliente.n_peticiones
        log.info("  %s  descargando...", etiqueta)

        r = cliente.get("", url_absoluta=url, stream=True)
        # Se escribe a un temporal y se renombra al final. Si la descarga se corta, no
        # queda un ZIP truncado que la siguiente corrida daria por valido: eso es lo que
        # el enunciado quiere decir con "a failed request must not lose previous work".
        tmp = destino.with_suffix(".parcial")
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)
        tmp.replace(destino)

        # --- verificacion de integridad ---
        sha_ok = False
        if a.get("verificar_sha", True):
            try:
                import hashlib
                esperado = cliente.get("", url_absoluta=fila["sha"]).text.strip().split()[0]
                h = hashlib.sha256()
                with open(destino, "rb") as fh:
                    for bloque in iter(lambda: fh.read(1 << 20), b""):
                        h.update(bloque)
                sha_ok = h.hexdigest().lower() == esperado.lower()
                if not sha_ok:
                    log.warning("  %s  el sha256 NO coincide con el publicado", etiqueta)
            except Exception as e:  # noqa: BLE001
                log.debug("  %s  no se pudo verificar el sha: %s", etiqueta, e)

        dt = time.perf_counter() - t0
        mb = destino.stat().st_size / 1e6
        log.info("  %s  OK  %.1f MB en %.1fs%s", etiqueta, mb, dt,
                 "  (sha verificado)" if sha_ok else "")
        registros.append(DescargaMes(etiqueta, url, destino.name, round(mb, 2),
                                     round(dt, 1), cliente.n_peticiones - peticiones_antes,
                                     False, sha_ok))

    reporte = pd.DataFrame([asdict(d) for d in registros])
    reporte.to_csv(cfg.outputs_dir / "descargas.csv", index=False, encoding="utf-8")
    log.info("  total: %.1f MB · %d peticiones · %.1fs de red",
             reporte["mb"].sum(), cliente.n_peticiones, cliente.segundos_red)
    return registros, reporte


# ============================================================================== lectura
def _leer_tabla(zf: zipfile.ZipFile, nombre: str, mapeo: dict[str, str]) -> pd.DataFrame:
    """Lee una tabla del ZIP y renombra sus columnas a los nombres cortos."""
    with zf.open(nombre) as fh:
        df = pd.read_csv(fh, low_memory=False)
    faltan = [c for c in mapeo if c not in df.columns]
    if faltan:
        log.warning("  %s: faltan %d columnas esperadas (%s...)",
                    nombre, len(faltan), faltan[0][:50])
    return df[[c for c in mapeo if c in df.columns]].rename(columns=mapeo)


def construir_dataset(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Une los meses descargados en UNA fila por proceso.

    Devuelve (procesos, conteos), donde `conteos` documenta cuantas filas habia antes y
    despues de cada paso: el enunciado pide reportar "how many rows you had before and
    after" llegar a una fila por proceso.
    """
    a = cfg.adquisicion
    col_reg = cfg.columnas("registros")
    col_par = cfg.columnas("partes")
    col_adj = cfg.columnas("adjudicaciones")

    partes_reg, partes_par, partes_adj = [], [], []
    conteos = []

    for anio, mes in cfg.meses():
        etiqueta = f"{anio}-{mes}"
        clave_formato = a["formato"] + ("_es" if a.get("idioma") == "es" else "")
        z = cfg.raw_dir / f"{etiqueta}_{a['fuente']}_{clave_formato}.zip"
        if not z.exists():
            raise FileNotFoundError(f"Falta {z.name}. Corre antes la descarga.")

        with zipfile.ZipFile(z) as zf:
            reg = _leer_tabla(zf, a["tabla_registros"], col_reg)
            par = _leer_tabla(zf, a["tabla_partes"], col_par)
            adj = _leer_tabla(zf, a["tabla_adjudicaciones"], col_adj)

        reg["mes_archivo"] = etiqueta
        partes_reg.append(reg)
        partes_par.append(par)
        partes_adj.append(adj)
        conteos.append({"paso": f"leido {etiqueta}", "filas": len(reg),
                        "ocid_unicos": reg["ocid"].nunique()})
        log.info("  %s  %6d registros · %6d filas de partes · %5d adjudicaciones",
                 etiqueta, len(reg), len(par), len(adj))

    reg = pd.concat(partes_reg, ignore_index=True)
    par = pd.concat(partes_par, ignore_index=True)
    adj = pd.concat(partes_adj, ignore_index=True)

    conteos.append({"paso": "concatenado de los meses", "filas": len(reg),
                    "ocid_unicos": reg["ocid"].nunique()})

    # --- una fila por proceso ---
    # Un proceso puede aparecer en mas de un mes si su segmentacion cambia. Se conserva
    # la aparicion mas reciente, que es la foto vigente del proceso.
    antes = len(reg)
    reg = (reg.sort_values(["ocid", "mes_archivo"])
              .drop_duplicates(subset="ocid", keep="last")
              .reset_index(drop=True))
    log.info("  deduplicacion por ocid: %d -> %d filas (%d duplicados entre meses)",
             antes, len(reg), antes - len(reg))
    conteos.append({"paso": "una fila por ocid", "filas": len(reg),
                    "ocid_unicos": reg["ocid"].nunique()})

    # --- el comprador y su ubicacion ---
    # Solo las filas con rol 'buyer'. Es la correccion de I-02: medir sobre todas las
    # partes mezcla compradores con proveedores, que no declaran direccion.
    compradores = par[par["roles"].fillna("").str.contains("buyer", case=False)]
    compradores = compradores.drop_duplicates(subset="ocid", keep="first")
    log.info("  partes con rol 'buyer': %d filas para %d procesos",
             len(compradores), compradores["ocid"].nunique())

    reg = reg.merge(
        compradores[["ocid", "entidad_id", "entidad_nombre", "departamento_crudo",
                     "region_cruda", "localidad_cruda"]],
        on="ocid", how="left")

    # --- adjudicaciones ---
    resumen_adj = (adj.groupby("ocid")
                      .agg(adjudicado=("id_adjudicacion", "size"),
                           monto_adjudicado=("monto_adjudicado", "sum"),
                           fecha_adjudicacion=("fecha_adjudicacion", "max"))
                      .reset_index())
    reg = reg.merge(resumen_adj, on="ocid", how="left")
    reg["adjudicado"] = reg["adjudicado"].fillna(0).astype(int) > 0
    log.info("  procesos adjudicados: %d de %d (%.1f%%)",
             int(reg["adjudicado"].sum()), len(reg),
             100 * reg["adjudicado"].mean())

    conteos.append({"paso": "con comprador y adjudicacion", "filas": len(reg),
                    "ocid_unicos": reg["ocid"].nunique()})

    return reg, pd.DataFrame(conteos)
