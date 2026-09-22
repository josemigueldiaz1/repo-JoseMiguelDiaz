"""
TAREA 2 — Proceso OFFLINE: descarga, valida, normaliza e indexa los procesos.

Misma frontera que en la Tarea 1: aqui se escribe en `data/`, el dashboard solo lee. El
enunciado lo exige explicitamente: "The dashboard reads precomputed files. It must not
download bulk files or rebuild the index at load time."

Uso:
    python build_data.py                # todo, sin rehacer lo ya hecho
    python build_data.py --fase 1       # solo descarga y dataset
    python build_data.py --reconstruir  # vacia el indice y lo rehace
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
HW3 = RAIZ.parent
for p in (str(RAIZ), str(HW3)):
    if p not in sys.path:
        sys.path.insert(0, p)

import pandas as pd  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(HW3 / ".env")

from src import adquisicion, metricas, territorio, validacion  # noqa: E402
from src.config import load_config  # noqa: E402
from src.motor import MotorRadar  # noqa: E402

log = logging.getLogger("hw3.t2.build")


def configurar_logging(logs_dir: Path, verboso: bool = False) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    archivo = logs_dir / f"build_data_{datetime.now():%Y%m%d_%H%M%S}.log"
    raiz = logging.getLogger()
    raiz.setLevel(logging.DEBUG if verboso else logging.INFO)
    raiz.handlers.clear()

    fh = logging.FileHandler(archivo, encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
    raiz.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-7s] %(message)s", "%H:%M:%S"))
    raiz.addHandler(sh)

    for ruidoso in ("urllib3", "httpx", "chromadb", "sentence_transformers",
                    "transformers", "httpcore"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
    return archivo


def banner(t: str) -> None:
    log.info("")
    log.info("=" * 74)
    log.info(t)
    log.info("=" * 74)


# ============================================================================== FASE 1
def fase_1(args, cfg) -> dict:
    """Descarga los bulk mensuales y construye una fila por proceso."""
    banner("FASE 1 — Adquisicion (OECE / OCDS)")

    cliente = adquisicion.ClienteOECE(cfg)
    _, rep_desc = adquisicion.descargar_meses(cfg, cliente, forzar=args.force_download)
    log.info("\n%s", rep_desc[["mes", "archivo", "mb", "segundos", "desde_cache",
                               "sha_verificado"]].to_string(index=False))

    log.info("")
    log.info("Construyendo el dataset (una fila por proceso):")
    df, conteos = adquisicion.construir_dataset(cfg)
    log.info("\n%s", conteos.to_string(index=False))
    conteos.to_csv(cfg.outputs_dir / "conteos_filas.csv", index=False, encoding="utf-8")

    return {"procesos_crudos": len(df), "_df": df, "_peticiones": cliente.n_peticiones}


# ============================================================================== FASE 2
def fase_2(args, cfg, df) -> dict:
    """Validacion, normalizacion territorial y reporte de calidad."""
    banner("FASE 2 — Validacion y normalizacion territorial")

    log.info("Normalizacion territorial (cascada de 4 pasos):")
    norm = territorio.Normalizador(cfg)
    df = norm.aplicar(df)
    rep_terr = norm.reporte(len(df))
    rep_terr.to_csv(cfg.outputs_dir / "recuperacion_territorial.csv",
                    index=False, encoding="utf-8")

    log.info("")
    log.info("Reglas de calidad de datos:")
    df, rep = validacion.validar(cfg, df)
    rep.exportar(cfg)

    # --- persistencia ---
    destino = cfg.processed_dir / "procesos.parquet"
    df.to_parquet(destino, index=False)
    log.info("  dataset -> %s (%.1f MB)", destino.name, destino.stat().st_size / 1e6)

    # Una copia en CSV para poder abrirla sin Python; el enunciado valora que los datos
    # procesados sean inspeccionables.
    cols = ["ocid", "titulo", "descripcion", "comprador", "departamento",
            "origen_departamento", "categoria", "metodo", "monto", "fecha_publicacion",
            "n_licitantes", "adjudicado"]
    df[[c for c in cols if c in df.columns]].to_csv(
        cfg.processed_dir / "procesos.csv", index=False, encoding="utf-8")

    localizados = int(df["departamento"].ne(territorio.NO_LOCALIZADO).sum())
    return {"procesos": len(df), "localizados": localizados,
            "pct_localizados": round(100 * localizados / len(df), 2),
            "aptos_indice": int(df["apto_para_indice"].sum()), "_df": df}


# ============================================================================== FASE 3
def fase_3(args, cfg, df) -> dict:
    """Indexa las descripciones con el mismo modelo local de la Tarea 1."""
    banner("FASE 3 — Indice semantico de descripciones")

    motor = MotorRadar(cfg)
    stats = motor.indexar(df, reconstruir=args.reconstruir)
    log.info("  indice '%s': %d procesos (%d insertados en %.1fs)",
             motor.indice.nombre, stats["total"], stats["insertados"], stats["segundos"])
    return {"indexados": stats["total"], "segundos_indexado": stats["segundos"]}


# ============================================================================== FASE 5
def fase_5(args, cfg, df) -> dict:
    """Indicador de riesgo y senales de alerta adicionales."""
    banner("FASE 5 — Indicador de riesgo: postor unico")

    glob = metricas.indicador_global(cfg, df)
    log.info("  procesos adjudicados     : %d", glob["procesos_adjudicados"])
    log.info("  con un solo postor       : %d (%.2f%%)",
             glob["con_postor_unico"], glob["pct_postor_unico"])

    dep = metricas.por_departamento(cfg, df)
    dep.to_csv(cfg.outputs_dir / "riesgo_por_departamento.csv", index=False, encoding="utf-8")
    if len(dep):
        log.info("\n  Departamentos con mayor proporcion de postor unico:")
        log.info("\n%s", dep.head(8).to_string(index=False))

    comp = metricas.por_comprador(cfg, df)
    comp.to_csv(cfg.outputs_dir / "riesgo_por_comprador.csv", index=False, encoding="utf-8")
    top = metricas.top_compradores(cfg, df)
    if len(top):
        top.to_csv(cfg.outputs_dir / "riesgo_top_compradores.csv",
                   index=False, encoding="utf-8")
        log.info("\n  Top %d compradores (minimo %d procesos adjudicados):",
                 len(top), cfg.riesgo["min_procesos_por_comprador"])
        log.info("\n%s", top[["comprador", "departamento", "procesos_adjudicados",
                              "pct_postor_unico"]].to_string(index=False))

    # --- innovacion: plazo corto ---
    detalle, resumen = metricas.plazo_corto(cfg, df)
    if resumen:
        banner("FASE 5b — INNOVACION: segunda senal (plazo de licitacion corto)")
        for k, v in resumen.items():
            log.info("  %-34s %s", k, v)
        if len(detalle):
            detalle.to_csv(cfg.outputs_dir / "riesgo_plazo_corto.csv",
                           index=False, encoding="utf-8")
        pd.DataFrame([resumen]).to_csv(cfg.outputs_dir / "riesgo_plazo_corto_resumen.csv",
                                       index=False, encoding="utf-8")

    # --- distribuciones para el dashboard ---
    for por in ("categoria", "departamento", "mes"):
        d = metricas.distribucion(df, por)
        if len(d):
            d.to_csv(cfg.outputs_dir / f"distribucion_{por}.csv",
                     index=False, encoding="utf-8")

    log.info("")
    log.info("  AVISO OBLIGATORIO: %s", cfg.riesgo["aviso"].strip()[:150])
    return {"pct_postor_unico": glob["pct_postor_unico"],
            "top_compradores": len(top) if len(top) else 0}


# ================================================================================ main
def parse_args():
    p = argparse.ArgumentParser(
        description="Tarea 2 — construccion offline del radar de compras publicas",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--fase", default="all", choices=["1", "2", "3", "5", "all"])
    p.add_argument("--reconstruir", action="store_true")
    p.add_argument("--force-download", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config()
    archivo = configurar_logging(cfg.logs_dir, args.verbose)
    t0 = time.perf_counter()

    log.info("TAREA 2 — Radar de compras publicas")
    log.info("Log de esta corrida: %s", archivo)
    log.info("Meses del corpus: %s", ", ".join(f"{a}-{m}" for a, m in cfg.meses()))

    try:
        resumen: dict = {}
        df = None

        if args.fase in ("1", "all"):
            r = fase_1(args, cfg)
            df = r.pop("_df")
            resumen |= r

        if args.fase in ("2", "3", "5", "all") and df is None:
            # Permite correr una fase suelta releyendo lo que dejo la anterior.
            p = cfg.processed_dir / "procesos.parquet"
            if p.exists() and args.fase != "2":
                df = pd.read_parquet(p)
                log.info("Releido %s (%d procesos)", p.name, len(df))
            else:
                r = fase_1(args, cfg)
                df = r.pop("_df")
                resumen |= r

        if args.fase in ("2", "all"):
            r = fase_2(args, cfg, df)
            df = r.pop("_df")
            resumen |= r

        if args.fase in ("3", "all"):
            resumen |= fase_3(args, cfg, df)

        if args.fase in ("5", "all"):
            resumen |= fase_5(args, cfg, df)

        banner(f"COMPLETADO en {time.perf_counter() - t0:.1f}s")
        for k, v in resumen.items():
            log.info("  %-22s %s", k, v)
        log.info("")
        log.info("Siguiente paso:  streamlit run app.py")
        return 0
    except KeyboardInterrupt:
        log.warning("Interrumpido. Las descargas ya completadas se conservan.")
        return 130
    except Exception:
        log.exception("El pipeline fallo:")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
