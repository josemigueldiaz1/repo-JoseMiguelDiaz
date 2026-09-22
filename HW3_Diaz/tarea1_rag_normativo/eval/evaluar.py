"""
Fase 4 — Evaluacion de la recuperacion. NO llama al modelo generativo.

Esa es la propiedad central de este script y el enunciado pide saber explicarla: todas
las metricas que calcula miden la etapa de **recuperacion**, que es anterior a la
generacion. Por eso evaluar es gratis y se puede repetir cuantas veces haga falta, en
cada barrido de chunking y de umbral, sin gastar un centimo. Si la evaluacion costara
dinero, en la practica se haria una vez y se dejaria de hacer, que es como se acaba
ajustando un umbral "a ojo".

Que mide cada metrica:

- **Recall@k** mide el BUSCADOR. Responde: entre los k fragmentos que el indice devuelve,
  ¿esta el que contiene la respuesta? Si Recall@5 es bajo, ningun prompt ni ningun modelo
  generativo puede arreglarlo: la informacion nunca llego al contexto.

- **Tasa de abstencion** mide el UMBRAL, que es la politica de decision. Se separa en
  aciertos (abstenerse ante una pregunta fuera de dominio) y errores (abstenerse ante una
  pregunta que si estaba en el corpus). Son dos errores de distinto coste: no responder
  algo que sabias es una molestia; responder con seguridad algo que no sabias es el fallo
  que el enunciado considera peor que no tener sistema.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from src import embeddings  # noqa: E402
from src.config import Config, load_config  # noqa: E402
from src.indice import IndiceVectorial  # noqa: E402

log = logging.getLogger("hw3.t1.eval")

# Un articulo puede empezar al final de una pagina y continuar en la siguiente, asi que
# el fragmento correcto puede caer en la pagina contigua a la anotada. Se admite esa
# holgura de forma explicita y documentada, en vez de anotar rangos enormes que harian
# la metrica trivialmente facil.
TOLERANCIA_PAGINAS = 1


def cargar_preguntas(cfg: Config) -> pd.DataFrame:
    ruta = cfg.root / cfg.raw["evaluacion"]["archivo_preguntas"]
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el conjunto de evaluacion: {ruta}")
    df = pd.read_csv(ruta)
    df["paginas_esperadas"] = df["paginas_esperadas"].fillna("").astype(str)
    df["documento_esperado"] = df["documento_esperado"].fillna("").astype(str)
    return df


def _paginas(celda: str) -> set[int]:
    if not celda or celda.lower() == "nan":
        return set()
    return {int(x) for x in str(celda).replace(",", ";").split(";") if x.strip().isdigit()}


def _acierta(recuperado, documento: str, paginas: set[int]) -> bool:
    """Un fragmento acierta si es del documento esperado y de una pagina esperada."""
    if recuperado.documento != documento:
        return False
    return any(abs(recuperado.pagina - p) <= TOLERANCIA_PAGINAS for p in paginas)


def evaluar_recuperacion(cfg: Config, indice: IndiceVectorial,
                         preguntas: pd.DataFrame | None = None,
                         umbral: float | None = None) -> dict:
    """
    Calcula Recall@k y tasas de abstencion sobre el conjunto de evaluacion.

    Devuelve un diccionario plano, listo para ser una fila de una tabla comparativa.
    """
    preguntas = cargar_preguntas(cfg) if preguntas is None else preguntas
    ks = list(cfg.raw["evaluacion"]["k_valores"])
    u = float(umbral if umbral is not None else cfg.motor["umbral_similitud"])
    kmax = max(ks)

    aciertos = {k: 0 for k in ks}
    n_in = n_out = 0
    abst_correctas = abst_incorrectas = 0
    sims_in: list[float] = []
    sims_out: list[float] = []
    detalle = []

    for _, fila in preguntas.iterrows():
        rec = indice.buscar(fila["pregunta"], k=kmax)
        sim_max = rec[0].similitud if rec else 0.0
        se_abstiene = sim_max < u
        es_in = fila["tipo"] == "in_domain"

        if es_in:
            n_in += 1
            sims_in.append(sim_max)
            doc = fila["documento_esperado"]
            pags = _paginas(fila["paginas_esperadas"])
            posicion = next((i + 1 for i, r in enumerate(rec) if _acierta(r, doc, pags)), None)
            for k in ks:
                if posicion is not None and posicion <= k:
                    aciertos[k] += 1
            if se_abstiene:
                abst_incorrectas += 1
        else:
            n_out += 1
            sims_out.append(sim_max)
            posicion = None
            if se_abstiene:
                abst_correctas += 1

        detalle.append({
            "id": fila["id"],
            "tipo": fila["tipo"],
            "estilo": fila.get("estilo", ""),
            "pregunta": fila["pregunta"][:70],
            "similitud_maxima": round(sim_max, 4),
            "posicion_acierto": posicion,
            "se_abstiene": se_abstiene,
            "doc_recuperado_1": rec[0].documento if rec else "",
            "pagina_recuperada_1": rec[0].pagina if rec else None,
        })

    met = {
        "umbral": u,
        "n_in_domain": n_in,
        "n_out_domain": n_out,
        "sim_media_in_domain": round(sum(sims_in) / len(sims_in), 4) if sims_in else 0.0,
        "sim_media_out_domain": round(sum(sims_out) / len(sims_out), 4) if sims_out else 0.0,
        "sim_max_out_domain": round(max(sims_out), 4) if sims_out else 0.0,
        "abstenciones_correctas": abst_correctas,
        "abstenciones_incorrectas": abst_incorrectas,
        "tasa_abstencion_correcta": round(abst_correctas / n_out, 4) if n_out else 0.0,
        "tasa_abstencion_incorrecta": round(abst_incorrectas / n_in, 4) if n_in else 0.0,
    }
    for k in ks:
        met[f"recall@{k}"] = round(aciertos[k] / n_in, 4) if n_in else 0.0

    met["_detalle"] = pd.DataFrame(detalle)
    return met


def barrido_umbral(cfg: Config, indice: IndiceVectorial,
                   preguntas: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Recorre los umbrales candidatos y mide el intercambio en cada uno.

    Esta es la evidencia que exige la Fase 3: "Calibrate that threshold with a sweep over
    your evaluation set, and show the evidence". El enunciado avisa de que la intuicion
    falla —una pregunta fuera de dominio alcanzo 0.79 con un umbral intuitivo de 0.78—,
    asi que el umbral tiene que salir de una tabla, no de una corazonada.

    La columna `aciertos_totales` es el criterio de eleccion: cuantas preguntas se
    resuelven bien, contando como acierto tanto responder una in-domain como abstenerse
    ante una out-of-domain.
    """
    preguntas = cargar_preguntas(cfg) if preguntas is None else preguntas
    filas = []
    for u in cfg.motor["barrido_umbral"]:
        m = evaluar_recuperacion(cfg, indice, preguntas, umbral=float(u))
        m.pop("_detalle", None)
        bien_in = m["n_in_domain"] - m["abstenciones_incorrectas"]
        m["aciertos_totales"] = bien_in + m["abstenciones_correctas"]
        m["pct_aciertos"] = round(
            100 * m["aciertos_totales"] / (m["n_in_domain"] + m["n_out_domain"]), 1)
        filas.append(m)
    return pd.DataFrame(filas)


def medir_control(cfg: Config, indice: IndiceVectorial,
                  preguntas: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Mide si el indice de control (Reglamento) sirve para detectar preguntas fuera de
    corpus. La respuesta, medida, es que NO. Ver logs/hallazgos.md (H-02).

    Se conserva como script porque un resultado negativo solo vale si es reproducible:
    cualquiera puede volver a correr esto y comprobar que el mecanismo no discrimina.
    """
    nombre = cfg.indice.get("coleccion_control")
    if not nombre:
        return pd.DataFrame()
    control = IndiceVectorial(cfg, indice.emb, coleccion=nombre)
    if len(control) == 0:
        return pd.DataFrame()

    preguntas = cargar_preguntas(cfg) if preguntas is None else preguntas
    filas = []
    for _, f in preguntas.iterrows():
        a = indice.buscar(f["pregunta"], k=1)
        b = control.buscar(f["pregunta"], k=1)
        sa = a[0].similitud if a else 0.0
        sb = b[0].similitud if b else 0.0
        filas.append({"id": f["id"], "tipo": f["tipo"],
                      "sim_corpus": round(sa, 4), "sim_control": round(sb, 4),
                      "delta": round(sb - sa, 4), "pregunta": f["pregunta"][:60]})
    return pd.DataFrame(filas)


def comparar_bm25(cfg: Config, indice: IndiceVectorial,
                  preguntas: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    INNOVACION — Busqueda lexica (BM25) frente a busqueda semantica (embeddings).

    El enunciado la sugiere expresamente sobre las preguntas coloquiales, y ahi esta la
    gracia: BM25 puntua por coincidencia de palabras. Cuando un empresario pregunta
    "me piden una carta fianza", la Ley no dice "carta fianza" sino "garantia de fiel
    cumplimiento". No comparten ni una palabra clave, asi que BM25 no puede encontrarlo;
    los embeddings si, porque operan sobre significado.

    Separar el resultado por estilo de pregunta (formal frente a coloquial) es lo que
    convierte la comparacion en un argumento y no en un numero suelto.
    """
    from rank_bm25 import BM25Okapi

    preguntas = cargar_preguntas(cfg) if preguntas is None else preguntas
    _, textos, metadatos = indice.vectores_y_textos()
    corpus = [t.lower().split() for t in textos]
    bm25 = BM25Okapi(corpus)
    ks = list(cfg.raw["evaluacion"]["k_valores"])
    kmax = max(ks)

    filas = []
    for _, fila in preguntas[preguntas["tipo"] == "in_domain"].iterrows():
        doc = fila["documento_esperado"]
        pags = _paginas(fila["paginas_esperadas"])

        # --- BM25 ---
        puntajes = bm25.get_scores(fila["pregunta"].lower().split())
        mejores = sorted(range(len(puntajes)), key=lambda i: -puntajes[i])[:kmax]
        pos_bm25 = next(
            (j + 1 for j, i in enumerate(mejores)
             if metadatos[i].get("documento") == doc
             and any(abs(int(metadatos[i].get("pagina", -99)) - p) <= TOLERANCIA_PAGINAS
                     for p in pags)),
            None)

        # --- embeddings ---
        rec = indice.buscar(fila["pregunta"], k=kmax)
        pos_emb = next((i + 1 for i, r in enumerate(rec) if _acierta(r, doc, pags)), None)

        filas.append({
            "id": fila["id"], "estilo": fila.get("estilo", ""),
            "pregunta": fila["pregunta"][:60],
            "posicion_bm25": pos_bm25, "posicion_embeddings": pos_emb,
            "bm25_acierta_top3": bool(pos_bm25 and pos_bm25 <= 3),
            "embeddings_acierta_top3": bool(pos_emb and pos_emb <= 3),
        })
    return pd.DataFrame(filas)


# ================================================================================ main
def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    cfg = load_config()
    salida = cfg.eval_dir / "resultados"
    salida.mkdir(parents=True, exist_ok=True)

    emb = embeddings.crear(cfg, "local")
    idx = IndiceVectorial(cfg, emb)
    if len(idx) == 0:
        log.error("El indice esta vacio. Corre antes: python build_index.py")
        return 1

    preguntas = cargar_preguntas(cfg)
    log.info("Conjunto de evaluacion: %d preguntas (%d in-domain, %d out-of-domain)",
             len(preguntas), (preguntas["tipo"] == "in_domain").sum(),
             (preguntas["tipo"] == "out_domain").sum())
    log.info("Indice: '%s' con %d fragmentos · modelo %s",
             idx.nombre, len(idx), emb.modelo)

    # --- metricas con el umbral de produccion ---
    log.info("\n" + "=" * 74)
    log.info("METRICAS DE RECUPERACION (umbral de produccion)")
    log.info("=" * 74)
    met = evaluar_recuperacion(cfg, idx, preguntas)
    detalle = met.pop("_detalle")
    detalle.to_csv(salida / "detalle_preguntas.csv", index=False, encoding="utf-8")
    for k, v in met.items():
        log.info("  %-28s %s", k, v)

    # --- barrido de umbral ---
    log.info("\n" + "=" * 74)
    log.info("BARRIDO DE UMBRAL — la evidencia para elegirlo")
    log.info("=" * 74)
    bar = barrido_umbral(cfg, idx, preguntas)
    cols = ["umbral", "recall@1", "recall@3", "recall@5", "abstenciones_correctas",
            "abstenciones_incorrectas", "aciertos_totales", "pct_aciertos"]
    bar[cols].to_csv(salida / "barrido_umbral.csv", index=False, encoding="utf-8")
    log.info("\n%s", bar[cols].to_string(index=False))

    mejor = bar.loc[bar["aciertos_totales"].idxmax()]
    log.info("\n  Mejor umbral por aciertos totales: %.2f (%.1f%% de aciertos)",
             mejor["umbral"], mejor["pct_aciertos"])
    log.info("  Similitud media in-domain : %.4f", met["sim_media_in_domain"])
    log.info("  Similitud MAXIMA out-domain: %.4f  <- el umbral debe quedar por encima",
             met["sim_max_out_domain"])

    # --- experimento descartado: el indice de control como discriminador ---
    ctrl = medir_control(cfg, idx, preguntas)
    if len(ctrl):
        log.info("\n" + "=" * 74)
        log.info("EXPERIMENTO DESCARTADO — ¿discrimina el indice de control?")
        log.info("=" * 74)
        ctrl.to_csv(salida / "control_discriminacion.csv", index=False, encoding="utf-8")
        d_in = ctrl[ctrl["tipo"] == "in_domain"]["delta"]
        d_out = ctrl[ctrl["tipo"] == "out_domain"]["delta"]
        log.info("  delta = similitud(control) - similitud(corpus)")
        log.info("  in-domain : media %+.4f", d_in.mean())
        log.info("  out-domain: media %+.4f", d_out.mean())
        for margen in (0.0, 0.005, 0.01, 0.03):
            log.info("  margen %.3f -> detecta %d/%d fuera de corpus, "
                     "%d/%d falsos positivos",
                     margen, int((d_out > margen).sum()), len(d_out),
                     int((d_in > margen).sum()), len(d_in))
        log.info("  CONCLUSION: no discrimina. Ver logs/hallazgos.md (H-02).")

    # --- innovacion: BM25 ---
    if cfg.raw.get("innovacion", {}).get("bm25", {}).get("activo"):
        log.info("\n" + "=" * 74)
        log.info("INNOVACION — BM25 lexico frente a embeddings semanticos")
        log.info("=" * 74)
        cmp = comparar_bm25(cfg, idx, preguntas)
        cmp.to_csv(salida / "bm25_vs_embeddings.csv", index=False, encoding="utf-8")
        for estilo in ("formal", "coloquial"):
            sub = cmp[cmp["estilo"] == estilo]
            if len(sub):
                log.info("  %-10s (n=%2d)  BM25 top3: %4.1f%%   embeddings top3: %4.1f%%",
                         estilo, len(sub),
                         100 * sub["bm25_acierta_top3"].mean(),
                         100 * sub["embeddings_acierta_top3"].mean())

    log.info("\n  Resultados en: %s", salida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
