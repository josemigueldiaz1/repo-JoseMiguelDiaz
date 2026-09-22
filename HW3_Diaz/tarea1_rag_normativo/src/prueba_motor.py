"""
Demostracion reproducible del motor con llamadas reales al modelo.

Es el unico paso de `run_all.py` que gasta dinero, y gasta muy poco: cinco preguntas,
del orden de 0.0015 USD en total. Existe porque las propiedades que mas importa
demostrar —cuando el sistema NO llama al modelo, y cuando lo llama y aun asi se
abstiene— no se pueden comprobar sin hacer la llamada.

Las cinco preguntas estan elegidas para cubrir un caso de cada tipo:

    1. in-domain formal        responde citando la Ley
    2. in-domain coloquial     responde a una pregunta de empresario, no de abogado
    3. norma modificatoria     responde y anade la nota de version
    4. fuera de dominio        se abstiene GRATIS, sin llamar al modelo
    5. fuera de corpus         pasa el umbral, llama al modelo, y el modelo se abstiene

El caso 5 es el interesante: demuestra que un umbral solo no basta.

Uso:
    python -m src.prueba_motor
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

from src.config import load_config  # noqa: E402
from src.motor import MotorRAG  # noqa: E402

log = logging.getLogger("hw3.t1.prueba")

CASOS = [
    ("in-domain formal", "¿Qué tipos de adelantos puede entregar la entidad al contratista?"),
    ("in-domain coloquial", "Me piden una carta fianza, ¿eso qué es y para qué la quieren?"),
    ("norma modificatoria",
     "¿Se puede aprobar una prestación adicional de obra en vía de regularización?"),
    ("fuera de dominio", "¿Cómo preparo un ceviche de pescado?"),
    ("fuera de corpus (Reglamento)",
     "¿Qué plazo exacto tiene el comité de selección para absolver consultas y observaciones?"),
]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    for n in ("httpx", "httpcore", "openai", "chromadb", "sentence_transformers",
              "transformers"):
        logging.getLogger(n).setLevel(logging.WARNING)

    cfg = load_config()
    try:
        cfg.credencial("DEEPSEEK_API_KEY")
    except Exception as e:  # noqa: BLE001
        log.warning("Se omite la prueba del motor: %s", e)
        return 0

    motor = MotorRAG(cfg)
    if len(motor.indice) == 0:
        log.error("El indice esta vacio. Corre antes: python build_index.py")
        return 1

    log.info("Indice: %d fragmentos · umbral %.2f · modelo %s",
             len(motor.indice), cfg.motor["umbral_similitud"], cfg.motor["modelo"])

    filas = []
    for etiqueta, pregunta in CASOS:
        log.info("\n" + "=" * 74)
        log.info("[%s]  %s", etiqueta, pregunta)
        log.info("=" * 74)
        r = motor.responder(pregunta)

        log.info("  abstuvo=%s  motivo=%s  filtro=%s", r.abstuvo, r.motivo_abstencion or "-",
                 r.filtro_que_decidio or "-")
        log.info("  sim_max=%.4f  llamo_al_modelo=%s  tokens=%d+%d  costo=$%.6f",
                 r.similitud_maxima, r.llamo_al_modelo, r.tokens_entrada,
                 r.tokens_salida, r.costo_usd)
        if r.error:
            log.error("  ERROR: %s", r.error)
        log.info("  respuesta: %s", (r.respuesta or "")[:340].replace("\n", " "))
        if r.nota_version:
            log.info("  nota de version aplicada")
        for f in r.fuentes[:2]:
            log.info("    fuente %s  sim=%.4f", f.cita, f.similitud)

        filas.append({
            "caso": etiqueta, "pregunta": pregunta,
            "abstuvo": r.abstuvo, "motivo": r.motivo_abstencion,
            "filtro_que_decidio": r.filtro_que_decidio,
            "similitud_maxima": round(r.similitud_maxima, 4),
            "llamo_al_modelo": r.llamo_al_modelo,
            "tokens_entrada": r.tokens_entrada, "tokens_salida": r.tokens_salida,
            "costo_usd": r.costo_usd, "latencia_seg": round(r.latencia_seg, 2),
            "error": r.error,
            "respuesta": (r.respuesta or "")[:400].replace("\n", " "),
        })

    salida = cfg.eval_dir / "resultados"
    salida.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(filas)
    df.to_csv(salida / "prueba_motor.csv", index=False, encoding="utf-8")

    log.info("\n" + "=" * 74)
    log.info("RESUMEN")
    log.info("=" * 74)
    log.info("\n%s", df[["caso", "abstuvo", "filtro_que_decidio", "similitud_maxima",
                         "llamo_al_modelo", "costo_usd"]].to_string(index=False))
    log.info("\n  gastado en esta prueba: $%.6f USD", df["costo_usd"].sum())
    log.info("  -> %s", salida / "prueba_motor.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
