"""
TAREA 1 — Proceso OFFLINE: convierte los PDF en un indice consultable.

El enunciado exige separar dos procesos: este, que se ejecuta una vez (o cuando cambian
los documentos), y el proceso ONLINE de `app.py`, que responde preguntas y **nunca vuelve
a leer los PDF**. La frontera entre ambos es la carpeta `data/`: aqui se escribe, alli
solo se lee.

Uso:
    python build_index.py                 # todas las fases, sin rehacer lo ya hecho
    python build_index.py --fase 1        # solo fuentes, extraccion y limpieza
    python build_index.py --reconstruir   # borra el indice y lo rehace desde cero
    python build_index.py --barrido       # compara configuraciones de chunking
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import pandas as pd  # noqa: E402

from src import chunking, embeddings, fuentes, limpieza  # noqa: E402
from src.config import load_config  # noqa: E402
from src.indice import IndiceVectorial  # noqa: E402

log = logging.getLogger("hw3.t1.build")


def configurar_logging(logs_dir: Path, verboso: bool = False) -> Path:
    """
    Log simultaneo a archivo y consola.

    El archivo queda como evidencia de ejecucion, que es un entregable del enunciado.
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    archivo = logs_dir / f"build_index_{datetime.now():%Y%m%d_%H%M%S}.log"

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


def banner(texto: str) -> None:
    log.info("")
    log.info("=" * 74)
    log.info(texto)
    log.info("=" * 74)


# ============================================================================== FASE 1
def fase_1(args, cfg) -> dict:
    """
    Fase 1 — Fuentes, extraccion y limpieza.

    Produce:
        data/raw/*.pdf                            originales, nunca modificados
        data/processed/source_check.csv           comprobacion de fuentes
        data/processed/paginas.jsonl              texto limpio CON su numero de pagina
        data/processed/extraccion_calidad.csv     reporte de calidad por documento
        data/processed/limpieza_reglas.csv        cuantas veces acerto cada regla
        data/processed/limpieza_antes_despues.md  ejemplo real antes/despues
    """
    banner("FASE 1 — Fuentes, extraccion y limpieza")

    log.info("Comprobacion de fuentes (antes de construir nada):")
    reporte_fuentes, textos = fuentes.comprobar_todas(cfg, forzar_descarga=args.force_download)
    log.info("\n%s", reporte_fuentes[
        ["archivo", "paginas", "caracteres_por_pagina", "pct_paginas_sin_texto",
         "orden_correcto", "usable", "indexado"]].to_string(index=False))

    log.info("")
    log.info("Limpieza:")
    paginas, reporte, reglas = limpieza.procesar(cfg, textos)
    limpieza.guardar(cfg, paginas, reporte, reglas)
    log.info("\n%s", reglas[reglas["coincidencias_eliminadas"] > 0].to_string(index=False))

    return {"paginas": len([p for p in paginas if p.util]),
            "documentos": len(cfg.fuentes)}


# ============================================================================== FASE 2
def fase_2(args, cfg) -> dict:
    """
    Fase 2 — Chunking, embeddings e indice.

    Produce:
        data/processed/fragmentos.jsonl         fragmentos con metadatos e ID estable
        data/processed/fragmentos_resumen.csv   cuantos y de que tamano, por documento
        data/index/                             ChromaDB persistente
    """
    banner("FASE 2 — Chunking, embeddings e indice")

    paginas = limpieza.cargar_paginas(cfg)
    c = cfg.chunking
    log.info("Troceando: tamano=%d, solapamiento=%d", c["tamano"], c["solapamiento"])

    frags = chunking.trocear(cfg, paginas)
    chunking.guardar(cfg, frags)
    log.info("\n%s", chunking.resumen(frags).to_string(index=False))

    # --- relacion entre el tamano de fragmento y el limite del modelo ---
    emb_cfg = cfg.embeddings("local")
    mayor = max(f.caracteres for f in frags)
    # ~3.7 caracteres por token en espanol; regla practica, suficiente para este control.
    tokens_aprox = mayor / 3.7
    log.info("")
    log.info("Limite del modelo de embeddings:")
    log.info("  modelo        : %s (max %d tokens)", emb_cfg["modelo"], emb_cfg["max_tokens"])
    log.info("  fragmento mayor: %d caracteres ~ %.0f tokens", mayor, tokens_aprox)
    if tokens_aprox > emb_cfg["max_tokens"] * 0.9:
        log.warning("  AVISO: cerca del limite; el modelo truncaria en silencio")
    else:
        log.info("  holgura       : %.0f%% del limite", 100 * tokens_aprox / emb_cfg["max_tokens"])
    log.info("  prefijos      : consulta=%r  pasaje=%r",
             emb_cfg["prefijo_consulta"], emb_cfg["prefijo_pasaje"])

    # --- indexacion ---
    log.info("")
    emb = embeddings.crear(cfg, "local")
    idx = IndiceVectorial(cfg, emb)
    if args.reconstruir:
        idx.vaciar()
    stats = idx.indexar(frags)
    log.info("  indice '%s': %d fragmentos (%d insertados en %.1fs)",
             idx.nombre, len(idx), stats["insertados"], stats["segundos"])

    # --- indice de control con el Reglamento ---
    # No responde nunca; solo permite distinguir "no lo se" de "eso no esta en mi corpus".
    nombre_ctrl = cfg.indice.get("coleccion_control")
    ctrl_n = 0
    if nombre_ctrl:
        log.info("")
        log.info("Indice de CONTROL (Reglamento, fuera del corpus de respuesta):")
        no_indexables = [f.clave for f in cfg.fuentes.values() if not f.indexar]
        pags_ctrl = [p for p in paginas if p["documento"] in no_indexables]
        if pags_ctrl:
            frags_ctrl = chunking.trocear(cfg, pags_ctrl, solo_indexables=False)
            ctrl = IndiceVectorial(cfg, emb, coleccion=nombre_ctrl)
            if args.reconstruir:
                ctrl.vaciar()
            ctrl.indexar(frags_ctrl)
            ctrl_n = len(ctrl)
            log.info("  '%s': %d fragmentos de %s", nombre_ctrl, ctrl_n,
                     ", ".join(no_indexables))

    return {"fragmentos": len(frags), "indexados": len(idx), "control": ctrl_n,
            "segundos_indexado": round(stats["segundos"], 1)}


# ========================================================================== BARRIDO
def barrido_chunking(cfg) -> pd.DataFrame:
    """
    Compara configuraciones de chunking sobre el conjunto de evaluacion.

    El enunciado exige elegir tamano y solapamiento "with evidence (at least two
    configurations compared with your evaluation set)", no por defecto. Se mide Recall@k
    sin llamar nunca al modelo generativo, asi que el barrido es gratis.
    """
    from eval.evaluar import evaluar_recuperacion, cargar_preguntas

    banner("BARRIDO DE CHUNKING — eligiendo tamano con evidencia")
    paginas = limpieza.cargar_paginas(cfg)
    preguntas = cargar_preguntas(cfg)
    emb = embeddings.crear(cfg, "local")

    filas = []
    for conf in cfg.chunking["barrido"]:
        t, s = int(conf["tamano"]), int(conf["solapamiento"])
        log.info("")
        log.info("--- tamano=%d solapamiento=%d ---", t, s)
        frags = chunking.trocear(cfg, paginas, tamano=t, solapamiento=s)

        nombre = f"barrido_{t}_{s}"
        idx = IndiceVectorial(cfg, emb, coleccion=nombre)
        idx.vaciar()
        t0 = time.perf_counter()
        idx.indexar(frags)
        dt = time.perf_counter() - t0

        met = evaluar_recuperacion(cfg, idx, preguntas)
        met.update({"tamano": t, "solapamiento": s, "fragmentos": len(frags),
                    "segundos_indexado": round(dt, 1),
                    "car_medio": round(sum(f.caracteres for f in frags) / len(frags), 1)})
        filas.append(met)
        log.info("  fragmentos=%d  R@1=%.3f  R@3=%.3f  R@5=%.3f",
                 len(frags), met["recall@1"], met["recall@3"], met["recall@5"])

    df = pd.DataFrame(filas)[
        ["tamano", "solapamiento", "fragmentos", "car_medio", "segundos_indexado",
         "recall@1", "recall@3", "recall@5", "sim_media_in_domain", "sim_media_out_domain"]]
    salida = cfg.eval_dir / "resultados"
    salida.mkdir(parents=True, exist_ok=True)
    df.to_csv(salida / "barrido_chunking.csv", index=False, encoding="utf-8")
    log.info("\n%s", df.to_string(index=False))
    log.info("\n  -> %s", salida / "barrido_chunking.csv")
    return df


# ================================================================================ main
def parse_args():
    p = argparse.ArgumentParser(
        description="Tarea 1 — construccion offline del indice normativo",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--fase", default="all", choices=["1", "2", "all"],
                   help="Fase a ejecutar (default: all)")
    p.add_argument("--reconstruir", action="store_true",
                   help="Vacia el indice antes de reindexar")
    p.add_argument("--force-download", action="store_true",
                   help="Vuelve a descargar los PDF aunque existan")
    p.add_argument("--barrido", action="store_true",
                   help="Compara configuraciones de chunking sobre el set de evaluacion")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config()
    archivo = configurar_logging(cfg.logs_dir, args.verbose)

    t0 = time.perf_counter()
    log.info("TAREA 1 — Construccion del indice normativo")
    log.info("Log de esta corrida: %s", archivo)

    try:
        resumen = {}
        if args.fase in ("1", "all"):
            resumen |= fase_1(args, cfg)
        if args.fase in ("2", "all"):
            resumen |= fase_2(args, cfg)
        if args.barrido:
            barrido_chunking(cfg)

        banner(f"COMPLETADO en {time.perf_counter() - t0:.1f}s")
        for k, v in resumen.items():
            log.info("  %-22s %s", k, v)
        log.info("")
        log.info("Siguiente paso:  streamlit run app.py")
        return 0
    except KeyboardInterrupt:
        log.warning("Interrumpido por el usuario. El indice es reanudable: "
                    "vuelve a ejecutar y continuara donde quedo.")
        return 130
    except Exception:
        log.exception("La construccion fallo:")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
