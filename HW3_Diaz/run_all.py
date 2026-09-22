"""
HW3_Diaz — Genera TODA la tarea en una sola corrida.

Este es el script que hay que ejecutar para reproducir el proyecto entero en una maquina
limpia, despues de instalar `requirements.txt` y de rellenar el `.env`:

    python run_all.py

Hace, en orden:

    TAREA 1   descarga los PDF normativos
              comprueba que son legibles (y se detiene si no lo son)
              limpia el texto conservando el numero de pagina
              trocea, calcula embeddings locales y construye el indice
              evalua la recuperacion y calibra el umbral (sin gastar un token)
              compara BM25 contra embeddings
              prueba el motor con preguntas reales (unicas llamadas de pago)

    TAREA 2   descarga tres meses de datos abiertos de OECE
              construye una fila por proceso de contratacion
              valida, normaliza el territorio e informa de la calidad
              indexa las descripciones con el MISMO modelo local
              evalua y comprueba si el umbral de la Tarea 1 transfiere
              calcula el indicador de postor unico y la senal de plazo corto

    CIERRE    resumen de costos reales y comprobaciones de arquitectura

Opciones utiles:

    python run_all.py --rapido        omite las llamadas de pago al modelo
    python run_all.py --solo 1        solo la Tarea 1
    python run_all.py --reconstruir   rehace los indices desde cero

El script es **reanudable**: lo ya descargado no se vuelve a descargar y lo ya indexado
no se vuelve a indexar, asi que una segunda corrida cuesta segundos en vez de minutos.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
T1 = RAIZ / "tarea1_rag_normativo"
T2 = RAIZ / "tarea2_radar"
for p in (str(RAIZ), str(T1), str(T2)):
    if p not in sys.path:
        sys.path.insert(0, p)

log = logging.getLogger("hw3")
PY = sys.executable


# ============================================================================= utilidades
def configurar_logging(verboso: bool = False) -> Path:
    logs = RAIZ / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    archivo = logs / f"run_all_{datetime.now():%Y%m%d_%H%M%S}.log"

    raiz = logging.getLogger()
    raiz.setLevel(logging.DEBUG if verboso else logging.INFO)
    raiz.handlers.clear()

    fh = logging.FileHandler(archivo, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
                                      "%Y-%m-%d %H:%M:%S"))
    raiz.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-7s] %(message)s", "%H:%M:%S"))
    raiz.addHandler(sh)

    for ruidoso in ("urllib3", "httpx", "httpcore", "chromadb", "openai",
                    "sentence_transformers", "transformers", "huggingface_hub"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
    return archivo


def banner(texto: str, char: str = "=") -> None:
    log.info("")
    log.info(char * 78)
    log.info(texto)
    log.info(char * 78)


def correr(descripcion: str, comando: list[str], cwd: Path) -> int:
    """
    Ejecuta un paso en un subproceso y transmite su salida.

    Se usan subprocesos y no importaciones directas por una razon concreta: cada tarea
    anade su propia carpeta a `sys.path` y ambas tienen un paquete llamado `src`.
    Importarlas en el mismo proceso haria que la segunda viera los modulos de la
    primera. Un subproceso por tarea elimina el problema de raiz.
    """
    log.info("")
    log.info("-> %s", descripcion)
    log.info("   %s  (en %s)", " ".join(Path(c).name if c == PY else c for c in comando),
             cwd.name)
    t0 = time.perf_counter()

    proceso = subprocess.run(comando, cwd=str(cwd), text=True,
                             capture_output=True, encoding="utf-8", errors="replace")
    for linea in (proceso.stdout or "").splitlines():
        if linea.strip():
            log.info("   | %s", linea.rstrip()[:200])
    if proceso.returncode != 0:
        for linea in (proceso.stderr or "").splitlines()[-30:]:
            log.error("   ! %s", linea.rstrip()[:200])

    dt = time.perf_counter() - t0
    estado = "OK" if proceso.returncode == 0 else f"FALLO ({proceso.returncode})"
    log.info("   %s en %.1fs", estado, dt)
    return proceso.returncode


# ======================================================================== comprobaciones
def comprobar_entorno() -> int:
    """
    Comprobaciones previas. Fallar aqui, con un mensaje claro, ahorra descubrir el
    problema veinte minutos despues, a mitad de la indexacion.
    """
    banner("COMPROBACIONES PREVIAS")
    problemas = 0

    log.info("Python: %s", sys.version.split()[0])
    if sys.version_info < (3, 10):
        log.error("  se necesita Python 3.10 o superior")
        problemas += 1

    faltan = []
    for mod in ("yaml", "pandas", "requests", "bs4", "chromadb", "sentence_transformers",
                "openai", "streamlit", "dotenv", "rank_bm25", "rapidfuzz", "pypdf"):
        try:
            __import__(mod)
        except ImportError:
            faltan.append(mod)
    if faltan:
        log.error("  faltan dependencias: %s", ", ".join(faltan))
        log.error("  instalalas con:  pip install -r requirements.txt")
        problemas += 1
    else:
        log.info("Dependencias: todas presentes")

    env = RAIZ / ".env"
    if not env.exists():
        log.warning(".env no existe. Copialo de la plantilla:")
        log.warning("    copy .env.example .env")
        log.warning("Sin el, las fases que llaman al modelo se saltaran.")
    else:
        from dotenv import load_dotenv
        load_dotenv(env)
        import os
        if os.environ.get("DEEPSEEK_API_KEY"):
            log.info(".env: DEEPSEEK_API_KEY presente")
        else:
            log.warning(".env: falta DEEPSEEK_API_KEY; no se podra generar respuestas")

    import torch
    log.info("PyTorch: %s (CUDA disponible: %s)", torch.__version__,
             torch.cuda.is_available())
    return problemas


def verificar_arquitectura() -> int:
    """
    Comprueba que el modulo del motor NO importa ninguna libreria de interfaz.

    El enunciado lo exige y pide incluir el comando en el README: "Your engine module
    must not import Streamlit, Telegram or any UI library. Include in your README the
    command you use to verify it".
    """
    banner("VERIFICACION DE ARQUITECTURA")
    prohibidas = ("streamlit", "gradio", "telegram", "flask", "fastapi", "tkinter", "dash")
    fallos = 0

    for modulo in (T1 / "src" / "motor.py", T2 / "src" / "motor.py"):
        texto = modulo.read_text(encoding="utf-8")
        # Se buscan solo las lineas de import, no cualquier mencion: los comentarios
        # de estos archivos hablan de Streamlit a proposito, y contarlos daria un
        # falso positivo.
        encontradas = [
            linea.strip() for linea in texto.splitlines()
            if (linea.strip().startswith(("import ", "from ")))
            and any(p in linea.lower() for p in prohibidas)
        ]
        rel = modulo.relative_to(RAIZ)
        if encontradas:
            log.error("  %s importa librerias de interfaz:", rel)
            for e in encontradas:
                log.error("      %s", e)
            fallos += 1
        else:
            log.info("  OK  %s no importa ninguna libreria de interfaz", rel)

    log.info("")
    log.info("  Comando equivalente para reproducirlo a mano (PowerShell):")
    log.info('    Select-String -Path tarea*/src/motor.py -Pattern "^\\s*(import|from)\\s" '
             '| Select-String "streamlit|telegram|gradio|flask|fastapi"')
    return fallos


def resumen_costos() -> None:
    """Suma los logs de costos de ambas tareas."""
    banner("COSTO REAL DE ESTA CORRIDA")
    import pandas as pd

    total = 0.0
    for nombre, ruta in (("Tarea 1", T1 / "logs" / "costos.csv"),
                         ("Tarea 2", T2 / "logs" / "costos.csv")):
        if not ruta.exists():
            log.info("  %-8s sin llamadas registradas", nombre)
            continue
        df = pd.read_csv(ruta)
        if df.empty:
            continue
        gasto = float(df["costo_usd"].sum())
        total += gasto
        log.info("  %-8s %3d llamadas · %6d tokens entrada · %5d salida · $%.6f",
                 nombre, len(df), int(df["tokens_entrada"].sum()),
                 int(df["tokens_salida"].sum()), gasto)
        fallidas = int((~df["exito"].astype(bool)).sum())
        if fallidas:
            log.info("           (%d llamadas fallidas, incluidas en el conteo)", fallidas)

    log.info("")
    log.info("  TOTAL ACUMULADO: $%.6f USD", total)
    log.info("  Precios verificados el 2026-09-20 en api-docs.deepseek.com")


# ================================================================================= main
def parse_args():
    p = argparse.ArgumentParser(
        description="HW3_Diaz — genera todo el proyecto en una sola corrida",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--solo", choices=["1", "2"],
                   help="Ejecuta solo una de las dos tareas")
    p.add_argument("--rapido", action="store_true",
                   help="Omite las llamadas de pago al modelo generativo")
    p.add_argument("--reconstruir", action="store_true",
                   help="Vacia los indices y los reconstruye desde cero")
    p.add_argument("--force-download", action="store_true",
                   help="Vuelve a descargar todo aunque ya exista")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    archivo = configurar_logging(args.verbose)
    t0 = time.perf_counter()

    banner("HW3_Diaz — RAG NORMATIVO Y RADAR DE COMPRAS PUBLICAS", "#")
    log.info("Jose Miguel Diaz · Data-Science-Python")
    log.info("Log completo de esta corrida: %s", archivo)

    if comprobar_entorno():
        log.error("")
        log.error("Hay problemas en el entorno. Corrigelos y vuelve a ejecutar.")
        return 1

    extra = []
    if args.reconstruir:
        extra.append("--reconstruir")
    if args.force_download:
        extra.append("--force-download")

    fallos = 0

    # ---------------------------------------------------------------------- TAREA 1
    if args.solo != "2":
        banner("TAREA 1 — RAG NORMATIVO", "#")
        fallos += correr("Construccion del indice (fuentes, limpieza, chunking, embeddings)",
                         [PY, "build_index.py", *extra], T1)
        fallos += correr("Barrido de chunking (elegir tamano con evidencia)",
                         [PY, "build_index.py", "--barrido"], T1)
        fallos += correr("Evaluacion, calibracion del umbral y BM25 (sin coste)",
                         [PY, "eval/evaluar.py"], T1)
        if not args.rapido:
            fallos += correr("Prueba del motor con llamadas reales al modelo",
                             [PY, "-m", "src.prueba_motor"], T1)

    # ---------------------------------------------------------------------- TAREA 2
    if args.solo != "1":
        banner("TAREA 2 — RADAR DE COMPRAS PUBLICAS", "#")
        fallos += correr("Pipeline completo (descarga, validacion, indice, riesgo)",
                         [PY, "build_data.py", *extra], T2)
        fallos += correr("Generacion del conjunto de evaluacion desde los datos reales",
                         [PY, "eval/generar_preguntas.py"], T2)
        fallos += correr("Evaluacion, transferencia del umbral y efecto de los filtros",
                         [PY, "eval/evaluar.py"], T2)

    # ----------------------------------------------------------------------- CIERRE
    fallos += verificar_arquitectura()
    resumen_costos()

    banner(f"{'COMPLETADO' if not fallos else 'COMPLETADO CON FALLOS'} "
           f"en {(time.perf_counter() - t0)/60:.1f} min", "#")

    if fallos:
        log.error("%d paso(s) fallaron. Revisa el log: %s", fallos, archivo)
        return 1

    log.info("Todo listo. Para ver las aplicaciones:")
    log.info("")
    log.info("    cd tarea1_rag_normativo  &&  streamlit run app.py")
    log.info("    cd tarea2_radar          &&  streamlit run app.py")
    log.info("")
    log.info("Material para el video en:  logs/  (incidencias, hallazgos, explicaciones)")
    log.info("Guion del video en:         guion_video_HW3_Diaz.docx")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
