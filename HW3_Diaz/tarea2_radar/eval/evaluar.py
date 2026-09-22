"""
Fase 3, punto 5 — Evaluacion del RAG hibrido. NO llama al modelo generativo.

Mide tres cosas:

1. **Recall@k** contra el patron de oro lexico (ver `generar_preguntas.py`).
2. **Si el umbral de la Tarea 1 transfiere a este corpus**, que el enunciado pide
   comprobar expresamente, y recalibracion si no.
3. **El efecto de los filtros**: cuanto cambia la precision al aplicar una condicion
   territorial como filtro estructurado frente a dejarsela a los embeddings. Es la
   evidencia del argumento central de la Fase 3.

Uso:
    python eval/evaluar.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
HW3 = RAIZ.parent
for p in (str(RAIZ), str(HW3)):
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(HW3 / ".env")

from src.config import load_config, Config  # noqa: E402
from src.motor import Filtros, MotorRadar  # noqa: E402

log = logging.getLogger("hw3.t2.eval")


def cargar_preguntas(cfg: Config) -> pd.DataFrame:
    ruta = cfg.root / cfg.raw["evaluacion"]["archivo_preguntas"]
    if not ruta.exists():
        raise FileNotFoundError(
            f"No existe {ruta}. Genera el conjunto: python eval/generar_preguntas.py")
    df = pd.read_csv(ruta)
    df["ocids_relevantes"] = df["ocids_relevantes"].fillna("").astype(str)
    return df


def _relevantes(celda: str) -> set[str]:
    return {x for x in celda.split(";") if x.strip()}


def _es_relevante(proceso, patron: str, rel_ocids: set[str]) -> bool:
    """
    ¿Un proceso recuperado pertenece al patron de oro?

    Se comprueba aplicando la MISMA expresion regular que definio el patron de oro al
    texto del proceso recuperado, en vez de mirar si su ocid esta en una lista guardada.

    El motivo es que algunos temas tienen miles de procesos relevantes y el CSV solo
    guarda una muestra de 60 como referencia. Comprobar contra esa muestra haria que un
    acierto legitimo contara como fallo el 95% de las veces, y el Recall medido no
    significaria nada. La regla es la definicion; la lista es solo una ilustracion.
    """
    if patron:
        import re
        return bool(re.search(patron, proceso.descripcion.lower()))
    return proceso.ocid in rel_ocids


def evaluar(cfg: Config, motor: MotorRadar, preguntas: pd.DataFrame,
            umbral: float | None = None) -> tuple[dict, pd.DataFrame]:
    ks = list(cfg.raw["evaluacion"]["k_valores"])
    u = float(umbral if umbral is not None else cfg.motor["umbral_similitud"])
    kmax = max(ks)

    aciertos = {k: 0 for k in ks}
    n_in = n_out = abst_ok = abst_mal = 0
    sims_in: list[float] = []
    sims_out: list[float] = []
    detalle = []

    for _, f in preguntas.iterrows():
        rec = motor.buscar(f["pregunta"], Filtros(), k=kmax)
        sim = rec[0].similitud if rec else 0.0
        abst = sim < u
        es_in = f["tipo"] == "in_domain"

        pos = None
        if es_in:
            n_in += 1
            sims_in.append(sim)
            rel = _relevantes(f["ocids_relevantes"])
            patron = str(f.get("patron_oro", "") or "")
            pos = next((i + 1 for i, r in enumerate(rec)
                        if _es_relevante(r, patron, rel)), None)
            for k in ks:
                if pos is not None and pos <= k:
                    aciertos[k] += 1
            if abst:
                abst_mal += 1
        else:
            n_out += 1
            sims_out.append(sim)
            if abst:
                abst_ok += 1

        detalle.append({
            "id": f["id"], "tipo": f["tipo"], "pregunta": f["pregunta"][:55],
            "similitud_maxima": round(sim, 4), "posicion_acierto": pos,
            "se_abstiene": abst,
            "ocid_1": rec[0].ocid if rec else "",
            "departamento_1": rec[0].departamento if rec else "",
        })

    met = {
        "umbral": u,
        "n_in_domain": n_in, "n_out_domain": n_out,
        "sim_media_in_domain": round(sum(sims_in) / len(sims_in), 4) if sims_in else 0.0,
        "sim_media_out_domain": round(sum(sims_out) / len(sims_out), 4) if sims_out else 0.0,
        "sim_max_out_domain": round(max(sims_out), 4) if sims_out else 0.0,
        "abstenciones_correctas": abst_ok,
        "abstenciones_incorrectas": abst_mal,
    }
    for k in ks:
        met[f"recall@{k}"] = round(aciertos[k] / n_in, 4) if n_in else 0.0
    met["aciertos_totales"] = (n_in - abst_mal) + abst_ok
    met["pct_aciertos"] = round(100 * met["aciertos_totales"] / (n_in + n_out), 1)
    return met, pd.DataFrame(detalle)


def efecto_filtros(cfg: Config, motor: MotorRadar, df: pd.DataFrame) -> pd.DataFrame:
    """
    Compara aplicar una condicion territorial como FILTRO frente a ponerla en el texto.

    Es la evidencia del argumento de la Fase 3. Para cada departamento se hace la misma
    pregunta de dos maneras y se mide que porcentaje de los procesos recuperados
    pertenece realmente a ese departamento.
    """
    filas = []
    for dep in ["CUSCO", "PUNO", "LORETO", "AREQUIPA", "PIURA"]:
        tema = "obras de agua y saneamiento"

        # (a) el departamento va dentro del texto de la pregunta
        sin_filtro = motor.buscar(f"{tema} en {dep.title()}", Filtros(), k=10)
        ok_a = sum(1 for r in sin_filtro if r.departamento == dep)

        # (b) el departamento va como filtro estructurado
        con_filtro = motor.buscar(tema, Filtros(departamentos=[dep]), k=10)
        ok_b = sum(1 for r in con_filtro if r.departamento == dep)

        filas.append({
            "departamento": dep,
            "recuperados_texto": len(sin_filtro),
            "aciertan_texto": ok_a,
            "pct_texto": round(100 * ok_a / len(sin_filtro), 1) if sin_filtro else 0.0,
            "recuperados_filtro": len(con_filtro),
            "aciertan_filtro": ok_b,
            "pct_filtro": round(100 * ok_b / len(con_filtro), 1) if con_filtro else 0.0,
        })
    return pd.DataFrame(filas)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    for n in ("httpx", "chromadb", "sentence_transformers", "transformers", "httpcore"):
        logging.getLogger(n).setLevel(logging.WARNING)

    cfg = load_config()
    salida = cfg.eval_dir / "resultados"
    salida.mkdir(parents=True, exist_ok=True)

    motor = MotorRadar(cfg)
    if len(motor.indice) == 0:
        log.error("El indice esta vacio. Corre antes: python build_data.py")
        return 1

    preguntas = cargar_preguntas(cfg)
    log.info("Indice: %d procesos · %d preguntas (%d in-domain, %d out-of-domain)",
             len(motor.indice), len(preguntas),
             (preguntas["tipo"] == "in_domain").sum(),
             (preguntas["tipo"] == "out_domain").sum())

    # --- metricas con el umbral de produccion ---
    log.info("\n" + "=" * 74)
    log.info("METRICAS DE RECUPERACION")
    log.info("=" * 74)
    met, detalle = evaluar(cfg, motor, preguntas)
    detalle.to_csv(salida / "detalle_preguntas.csv", index=False, encoding="utf-8")
    for k, v in met.items():
        log.info("  %-28s %s", k, v)

    # --- ¿transfiere el umbral de la Tarea 1? ---
    log.info("\n" + "=" * 74)
    log.info("¿TRANSFIERE EL UMBRAL DE LA TAREA 1?")
    log.info("=" * 74)
    u1 = float(cfg.motor["umbral_tarea1"])
    met_t1, _ = evaluar(cfg, motor, preguntas, umbral=u1)
    log.info("  Umbral de la Tarea 1 (%.2f): %d abstenciones correctas, "
             "%d incorrectas, %.1f%% de aciertos",
             u1, met_t1["abstenciones_correctas"], met_t1["abstenciones_incorrectas"],
             met_t1["pct_aciertos"])
    log.info("  Umbral de la Tarea 2 (%.2f): %d abstenciones correctas, "
             "%d incorrectas, %.1f%% de aciertos",
             met["umbral"], met["abstenciones_correctas"],
             met["abstenciones_incorrectas"], met["pct_aciertos"])

    filas = []
    for u in cfg.motor["barrido_umbral"]:
        m, _ = evaluar(cfg, motor, preguntas, umbral=float(u))
        filas.append(m)
    bar = pd.DataFrame(filas)
    cols = ["umbral", "recall@1", "recall@3", "recall@5", "abstenciones_correctas",
            "abstenciones_incorrectas", "aciertos_totales", "pct_aciertos"]
    bar[cols].to_csv(salida / "barrido_umbral.csv", index=False, encoding="utf-8")
    log.info("\n%s", bar[cols].to_string(index=False))

    # --- efecto de los filtros ---
    log.info("\n" + "=" * 74)
    log.info("FILTRO ESTRUCTURADO FRENTE A CONDICION EN EL TEXTO")
    log.info("=" * 74)
    ef = efecto_filtros(cfg, motor, preguntas)
    ef.to_csv(salida / "efecto_filtros.csv", index=False, encoding="utf-8")
    log.info("\n%s", ef.to_string(index=False))
    log.info("\n  Media: %.1f%% de acierto territorial poniendo el departamento en el "
             "TEXTO, frente a %.1f%% aplicandolo como FILTRO.",
             ef["pct_texto"].mean(), ef["pct_filtro"].mean())

    log.info("\n  Resultados en: %s", salida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
