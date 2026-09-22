"""
INNOVACION — Enlazar las dos tareas.

El enunciado la propone asi: "when a process is retrieved in Task 2, the assistant from
Task 1 explains the rule that applies to its procurement method".

Es la innovacion que mejor demuestra que la arquitectura es correcta, porque **no anade
ni un solo mecanismo nuevo**. Todo lo que hace es llamar a `MotorRAG.responder()` de la
Tarea 1 con una pregunta construida a partir de los metadatos del proceso. Si el motor no
estuviera separado de su interfaz, esto seria imposible sin duplicar codigo; como lo
esta, son veinte lineas.

El valor para el usuario final —la MYPE del enunciado— es directo: el radar le dice
*"hay una licitacion de saneamiento en Cusco por 2 millones, por Adjudicacion
Simplificada"*, y el asistente normativo le dice, en la misma pantalla, *"esto es lo que
la Ley 32069 exige para ese procedimiento"*. Las dos preguntas del proyecto —"¿que compra
el Estado?" y "¿que dice la ley?"— se responden juntas.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

HW3 = Path(__file__).resolve().parent.parent.parent
if str(HW3) not in sys.path:
    sys.path.insert(0, str(HW3))

from tarea1_rag_normativo.src.config import load_config as cargar_config_t1  # noqa: E402
from tarea1_rag_normativo.src.motor import MotorRAG, Respuesta  # noqa: E402

log = logging.getLogger("hw3.t2.innovacion")

_MOTOR_T1: MotorRAG | None = None


def motor_normativo() -> MotorRAG:
    """
    Instancia (una sola vez) el motor de la Tarea 1.

    Se carga de forma perezosa porque el dashboard del radar es perfectamente util sin
    esta funcion: si el indice normativo no esta construido, el resto de la app sigue
    funcionando y solo falla esta pestana.
    """
    global _MOTOR_T1
    if _MOTOR_T1 is None:
        cfg = cargar_config_t1(HW3 / "tarea1_rag_normativo" / "config.yaml")
        _MOTOR_T1 = MotorRAG(cfg, tarea="tarea2_enlace")
    return _MOTOR_T1


def pregunta_para(metodo: str, categoria: str = "", cfg=None) -> tuple[str, str]:
    """
    Traduce el metodo de contratacion al lenguaje de la Ley y arma la pregunta.

    Devuelve (pregunta, aviso), donde `aviso` esta vacio salvo que el metodo sea un
    nombre que la ley vigente ya no usa.

    **Aqui hay dos correcciones que salieron de probar, no de suponer:**

    1. *La pregunta debe apuntar a lo que regula la LEY, no el Reglamento.* La primera
       version preguntaba por "requisitos y plazos" y el asistente se abstenia siempre,
       con razon: esos detalles son materia del Reglamento, que esta fuera del corpus a
       proposito. La Ley regula otra cosa: que procedimientos existen y en que supuestos
       procede cada uno.

    2. *Los datos y la ley no hablan el mismo idioma.* SEACE publica los nombres de
       procedimiento de la Ley 30225 ("Adjudicacion Simplificada", "Licitacion Publica
       Abreviada") mientras que la Ley 32069 reorganizo la taxonomia en competitivos
       (articulo 54) y no competitivo (articulo 55). Buscar "Adjudicacion Simplificada"
       en la Ley devuelve cero paginas. El mapeo de `config.yaml` traduce el nombre
       operativo al concepto legal; sin el, esta innovacion se abstendria siempre.

    Preguntar bien es parte del trabajo: una pregunta dirigida al corpus equivocado
    produce una abstencion correcta pero inutil, y el usuario se queda igual.
    """
    inn = (cfg.raw.get("innovacion", {}) if cfg is not None else {})
    mapeo = inn.get("mapeo_metodos", {})
    sin_equiv = set(inn.get("metodos_sin_equivalente", []))

    concepto = mapeo.get(metodo, metodo)
    aviso = ""
    if metodo in sin_equiv:
        aviso = inn.get("aviso_desfase", "").replace("{metodo}", metodo)
        # Estos nombres no existen en la Ley 32069; se pregunta por la categoria
        # general de procedimientos de seleccion, que si esta regulada.
        concepto = "procedimientos de seleccion competitivos y no competitivos"

    tipo = {"goods": "bienes", "works": "obras",
            "services": "servicios"}.get(str(categoria).lower(), "")
    objeto = f" de {tipo}" if tipo else ""

    pregunta = (f"¿Que dice la Ley sobre {concepto}? "
                f"¿En que supuestos procede una contratacion{objeto} por esa via?")
    return pregunta, aviso


def explicar_norma(metodo: str, categoria: str = "", cfg=None) -> tuple[Respuesta, str]:
    """
    Pregunta al asistente normativo por la regla aplicable a un metodo de contratacion.

    Devuelve `(respuesta, aviso)`. La respuesta es la misma `Respuesta` estructurada de
    la Tarea 1, **abstencion incluida**: si la Ley no cubre el concepto, lo dira en vez
    de improvisar. Esa propiedad se hereda gratis por reutilizar el motor, y es la mejor
    prueba de que la reutilizacion es real y no una copia disfrazada.

    `aviso` avisa del desfase de nomenclatura entre SEACE y la Ley 32069, si aplica.
    """
    if cfg is None:
        from .config import load_config
        cfg = load_config()
    pregunta, aviso = pregunta_para(metodo, categoria, cfg)
    return motor_normativo().responder(pregunta), aviso
