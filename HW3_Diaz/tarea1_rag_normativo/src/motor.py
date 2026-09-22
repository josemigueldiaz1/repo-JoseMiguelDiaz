"""
Fase 3 — El motor RAG. Una funcion, un resultado estructurado.

Este es el modulo que exige el enunciado: "All the RAG logic lives in one module that
exposes one function receiving a question and returning a structured result". Esa
funcion es `responder()`. La app de Streamlit, el bot de Telegram y el dashboard de la
Tarea 2 la llaman igual; ninguno reimplementa nada.

**Este modulo no importa ninguna libreria de interfaz.** Ni streamlit, ni gradio, ni
telegram. Se puede comprobar con el comando que esta en el README. La razon practica:
en cuanto el motor sabe de la interfaz, deja de poder usarse desde otra, y la Tarea 2
depende de poder reutilizarlo.

Las decisiones que hay que saber defender en el video:

1. **Dos filtros de abstencion, con costos distintos.** No hay uno solo, y la razon
   esta medida (ver logs/hallazgos.md, H-02):

   - **Filtro 1, gratis:** si el mejor fragmento no supera el umbral de similitud, se
     abstiene SIN llamar al modelo. Atrapa lo evidentemente ajeno al dominio
     ("¿como preparo un ceviche?", similitud 0.793).

   - **Filtro 2, cuesta una llamada:** para preguntas del mismo dominio pero cuya
     respuesta no esta en el corpus (las que solo responde el Reglamento), NINGUN umbral
     funciona: puntuan 0.86-0.89, por encima de la mayoria de preguntas validas. Esa
     decision solo puede tomarse mirando el contenido de los fragmentos, asi que se
     delega en el modelo, que devuelve un campo `puede_responder` en su JSON.

   Ponerlos en ese orden importa: el filtro caro solo se paga cuando el barato no ha
   podido decidir.

2. **La abstencion es un campo, no una cadena.** `abstuvo` es un booleano del resultado.
   Cuando la decide el modelo, llega como el booleano `puede_responder` de un JSON, no
   como prosa que haya que interpretar. Deducirla comparando el texto de la respuesta
   ("¿empieza por 'no se'?") seria fragil y se rompe en cuanto el modelo reformula.

3. **Un error de la API es un error, nunca una respuesta.** Si la llamada falla,
   `error` se rellena y `respuesta` queda vacia. La interfaz lo pinta como fallo. Si se
   devolviera el mensaje de error como si fuera la respuesta, el usuario leeria un "no
   pude" y concluiria que la norma no dice nada, que es lo contrario de la verdad.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from .config import Config
from .costos import RegistroCostos
from .embeddings import Embedder, crear as crear_embedder
from .indice import IndiceVectorial, Recuperado

log = logging.getLogger("hw3.t1.motor")


# ============================================================================ resultado
@dataclass
class Fuente:
    """Un fragmento citado en la respuesta."""

    documento: str
    documento_desc: str
    pagina: int
    similitud: float
    version: str
    es_modificatoria: bool
    texto: str

    @property
    def cita(self) -> str:
        return f"[{self.documento}, p. {self.pagina}]"


@dataclass
class Respuesta:
    """
    Lo que devuelve el motor. Es el contrato con todas las interfaces.

    El enunciado fija el minimo: respuesta, fuentes con documento/pagina/similitud, si
    se abstuvo, tokens, costo y error si lo hubo. Se anaden `motivo_abstencion` y
    `nota_version` porque sin ellos la interfaz tendria que reconstruirlos leyendo el
    texto, que es justo lo que se quiere evitar.
    """

    pregunta: str
    respuesta: str = ""
    fuentes: list[Fuente] = field(default_factory=list)

    abstuvo: bool = False
    # "" | "baja_similitud" (filtro 1, gratis) | "sin_respuesta_en_contexto" (filtro 2,
    # lo decide el modelo) | "indice_vacio"
    motivo_abstencion: str = ""
    filtro_que_decidio: str = ""         # "umbral" | "modelo" | ""
    similitud_maxima: float = 0.0
    umbral: float = 0.0

    nota_version: str = ""

    modelo: str = ""
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo_usd: float = 0.0
    franja_tarifa: str = ""
    latencia_seg: float = 0.0
    llamo_al_modelo: bool = False

    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    def a_dict(self) -> dict:
        d = asdict(self)
        d["fuentes"] = [asdict(f) for f in self.fuentes]
        return d


# =============================================================================== motor
class MotorRAG:
    """
    Motor de consulta. Se construye una vez y se reutiliza.

    Cargar el modelo de embeddings tarda varios segundos; hacerlo por pregunta haria la
    app inusable. En Streamlit la instancia vive en `@st.cache_resource`.
    """

    def __init__(self, cfg: Config, embedder: Embedder | None = None,
                 tarea: str = "tarea1"):
        self.cfg = cfg
        self.m = cfg.motor
        self.emb = embedder or crear_embedder(cfg)
        self.indice = IndiceVectorial(cfg, self.emb)
        self.costos = RegistroCostos(cfg, tarea=tarea)

        # Indice de control con el Reglamento: NUNCA produce respuestas, solo sirve para
        # explicar una abstencion. Ver `_es_del_reglamento`.
        self._control: IndiceVectorial | None = None
        nombre_control = cfg.indice.get("coleccion_control")
        if nombre_control:
            try:
                ctrl = IndiceVectorial(cfg, self.emb, coleccion=nombre_control)
                self._control = ctrl if len(ctrl) > 0 else None
            except Exception as e:  # noqa: BLE001 — el control es opcional
                log.debug("indice de control no disponible: %s", e)

        self._cliente = None   # perezoso: no se crea si todas las preguntas se abstienen

    # ------------------------------------------------------------------ auxiliares
    def _cliente_llm(self):
        if self._cliente is None:
            from openai import OpenAI
            self._cliente = OpenAI(
                api_key=Config.credencial("DEEPSEEK_API_KEY"),
                base_url=self.m["base_url"],
            )
        return self._cliente

    def _es_del_reglamento(self, pregunta: str, sim_corpus: float) -> bool:
        """
        ¿La pregunta se responderia con el Reglamento, que esta fuera del indice?

        HIPOTESIS DESCARTADA CON DATOS. La idea era que una pregunta de Reglamento se
        pareceria mas a la coleccion de control que al corpus indexado. Se midio sobre
        las 25 preguntas de evaluacion y no funciona: con margen 0.01 atrapa 0 de 5
        preguntas fuera de corpus y marca como sospechosas 4 de 20 preguntas validas.
        La causa es que la Ley y su Reglamento comparten dominio y vocabulario.

        Se conserva desactivada por defecto (`indice.usar_control_para_abstener: false`)
        porque la evidencia del experimento forma parte de los entregables, y porque
        dejar el codigo permite reproducir la medicion. Quien active la bandera vera el
        comportamiento degradado que documenta logs/hallazgos.md (H-02).
        """
        if self._control is None:
            return False
        if not self.cfg.indice.get("usar_control_para_abstener", False):
            return False
        try:
            r = self._control.buscar(pregunta, k=1)
        except Exception:  # noqa: BLE001
            return False
        margen = float(self.cfg.indice.get("margen_control", 0.02))
        return bool(r) and r[0].similitud > sim_corpus + margen

    def _leer_json(self, crudo: str) -> tuple[str, bool, str]:
        """
        Interpreta la respuesta JSON del modelo.

        Devuelve (texto_de_respuesta, se_abstuvo, motivo).

        Si el modelo devolviera algo que no es JSON valido —no deberia, porque se le pide
        con `response_format`, pero conviene no depender de que nunca falle— se trata el
        texto como respuesta normal y NO se marca abstencion. El criterio es
        conservador en la direccion correcta: ante la duda, se muestra lo que el modelo
        dijo junto con sus fuentes, y el usuario decide; inventar una abstencion que el
        modelo no declaro seria anadir un error propio encima de uno ajeno.
        """
        if not self.m.get("formato_json", True):
            return crudo, False, ""
        try:
            d = json.loads(crudo)
        except json.JSONDecodeError:
            log.warning("  el modelo no devolvio JSON valido; se usa el texto tal cual")
            return crudo, False, ""

        if not isinstance(d, dict):
            return crudo, False, ""

        puede = bool(d.get("puede_responder", True))
        texto = str(d.get("respuesta", "") or "").strip()
        motivo = str(d.get("motivo", "") or "").strip()

        # Las citas llegan aparte; se anaden al final del texto para que la respuesta
        # visible las lleve tambien, no solo el panel de fuentes.
        citas = d.get("citas") or []
        if puede and isinstance(citas, list) and citas:
            marca = "  ".join(f"[{str(c).strip()}]" for c in citas if str(c).strip())
            if marca and marca not in texto:
                texto = f"{texto}\n\nFuentes citadas: {marca}"

        return texto, (not puede), motivo

    def _construir_contexto(self, recuperados: list[Recuperado]) -> str:
        """
        Arma el bloque CONTEXTO del prompt.

        Cada fragmento va etiquetado con su documento y pagina para que el modelo pueda
        citar copiando, no recordando. Pedirle que cite sin darle la referencia delante
        es pedirle que la invente.
        """
        partes = []
        for i, r in enumerate(recuperados, start=1):
            marca = " (NORMA MODIFICATORIA)" if r.es_modificatoria else ""
            partes.append(
                f"--- Fragmento {i} · [{r.documento}, p. {r.pagina}]{marca} "
                f"· similitud {r.similitud:.3f} ---\n{r.texto}"
            )
        return "\n\n".join(partes)

    # ================================================================== API publica
    def responder(self, pregunta: str, top_k: int | None = None,
                  umbral: float | None = None) -> Respuesta:
        """
        Responde una pregunta. ESTA es la unica funcion que las interfaces llaman.

        `top_k` y `umbral` se pueden forzar para que la app los exponga como controles y
        para el barrido de calibracion; por defecto salen de config.yaml.
        """
        t0 = time.perf_counter()
        k = int(top_k or self.m["top_k"])
        u = float(umbral if umbral is not None else self.m["umbral_similitud"])
        res = Respuesta(pregunta=pregunta, umbral=u, modelo=self.m["modelo"])

        if not pregunta or not pregunta.strip():
            res.error = "La pregunta esta vacia."
            return res

        # ---------------------------------------------------------- 1. recuperacion
        try:
            recuperados = self.indice.buscar(pregunta, k=k)
        except Exception as e:  # noqa: BLE001
            res.error = f"Fallo la busqueda en el indice: {e}"
            res.latencia_seg = time.perf_counter() - t0
            return res

        if not recuperados:
            res.abstuvo = True
            res.motivo_abstencion = "indice_vacio"
            res.respuesta = self.m["mensajes"]["abstencion_baja_similitud"]
            res.latencia_seg = time.perf_counter() - t0
            return res

        res.similitud_maxima = recuperados[0].similitud
        res.fuentes = [
            Fuente(documento=r.documento, documento_desc=r.documento_desc, pagina=r.pagina,
                   similitud=round(r.similitud, 4), version=r.version,
                   es_modificatoria=r.es_modificatoria, texto=r.texto)
            for r in recuperados
        ]

        # ---------------------------- 2. FILTRO 1 (gratis): ¿se llama al modelo?
        # Este es el punto que el enunciado pide senalar en el video. Si el mejor
        # fragmento no llega al umbral, se retorna aqui: sin llamada, sin tokens, sin
        # costo. Abstenerse es gratis; responder mal, no.
        if res.similitud_maxima < u:
            res.abstuvo = True
            res.filtro_que_decidio = "umbral"
            if self._es_del_reglamento(pregunta, res.similitud_maxima):
                res.motivo_abstencion = "fuera_de_corpus"
                res.respuesta = self.m["mensajes"]["abstencion_fuera_de_corpus"]
            else:
                res.motivo_abstencion = "baja_similitud"
                res.respuesta = self.m["mensajes"]["abstencion_baja_similitud"]
            res.latencia_seg = time.perf_counter() - t0
            log.info("  abstencion (%s) · sim_max %.3f < umbral %.2f · 0 tokens",
                     res.motivo_abstencion, res.similitud_maxima, u)
            return res

        # ------------------------------------------------------------ 3. generacion
        contexto = self._construir_contexto(recuperados)
        p = self.m["prompts"]
        momento = datetime.now(timezone.utc)
        t_api = time.perf_counter()

        extra = {}
        if self.m.get("formato_json", True):
            extra["response_format"] = {"type": "json_object"}

        try:
            r = self._cliente_llm().chat.completions.create(
                model=self.m["modelo"],
                messages=[
                    {"role": "system", "content": p["sistema"]},
                    {"role": "user", "content": p["usuario"].format(
                        contexto=contexto, pregunta=pregunta)},
                ],
                temperature=float(self.m["temperatura"]),
                max_tokens=int(self.m["max_tokens"]),
                timeout=float(self.m["timeout_seg"]),
                **extra,
            )
        except Exception as e:  # noqa: BLE001
            # Un error de API NO es una respuesta. Se registra su latencia en el log de
            # costos porque el tiempo se gasto igual, aunque no hubiera tokens.
            latencia = time.perf_counter() - t_api
            res.error = f"{type(e).__name__}: {str(e)[:220]}"
            res.respuesta = ""
            res.llamo_al_modelo = True
            res.latencia_seg = time.perf_counter() - t0
            self.costos.registrar(modelo=self.m["modelo"], entrada=0, salida=0,
                                  latencia=latencia, exito=False, error=res.error,
                                  pregunta=pregunta, momento=momento)
            log.error("  la API fallo: %s", res.error)
            return res

        latencia_api = time.perf_counter() - t_api
        uso = getattr(r, "usage", None)
        entrada = int(getattr(uso, "prompt_tokens", 0) or 0)
        salida = int(getattr(uso, "completion_tokens", 0) or 0)
        # DeepSeek informa de cuantos tokens de entrada sirvio desde su cache. Si no
        # viene, se asume 0 (todo a precio caro), que es el supuesto conservador.
        detalles = getattr(uso, "prompt_tokens_details", None)
        cache_hit = int(getattr(detalles, "cached_tokens", 0) or 0) if detalles else 0

        crudo = (r.choices[0].message.content or "").strip()
        res.llamo_al_modelo = True
        res.tokens_entrada = entrada
        res.tokens_salida = salida

        # ------------------------------- FILTRO 2 (cuesta la llamada ya hecha)
        # El modelo devuelve JSON con `puede_responder`. Cuando dice que no, la
        # abstencion entra al resultado como un booleano que el modelo puso, no como
        # una cadena que haya que interpretar. Esa es la diferencia que pide el
        # enunciado entre "campo estructurado" y "deducirlo del texto".
        res.respuesta, decidio_no_responder, motivo_modelo = self._leer_json(crudo)
        if decidio_no_responder:
            res.abstuvo = True
            res.filtro_que_decidio = "modelo"
            res.motivo_abstencion = "sin_respuesta_en_contexto"
            if not res.respuesta:
                res.respuesta = motivo_modelo or self.m["mensajes"]["abstencion_fuera_de_corpus"]

        ll = self.costos.registrar(modelo=self.m["modelo"], entrada=entrada, salida=salida,
                                   cache_hit=cache_hit, latencia=latencia_api,
                                   exito=True, pregunta=pregunta, momento=momento)
        res.costo_usd = ll.costo_usd
        res.franja_tarifa = ll.franja

        # ------------------------------------------------- 4. manejo de versiones
        # Si alguna fuente citada es una norma modificatoria, la respuesta lleva un aviso
        # explicito. Una respuesta construida sobre un decreto que modifica otra norma
        # esta incompleta si se presenta como si fuera la regla entera.
        if not res.abstuvo and any(f.es_modificatoria for f in res.fuentes[:3]):
            res.nota_version = self.m["nota_version"]

        res.latencia_seg = time.perf_counter() - t0
        log.info("  respondida · sim %.3f · %d+%d tokens · %s · %.4f USD · %.1fs",
                 res.similitud_maxima, entrada, salida, ll.franja, ll.costo_usd,
                 res.latencia_seg)
        return res


# ------------------------------------------------------------------ funcion de modulo
_MOTOR: MotorRAG | None = None


def responder(pregunta: str, cfg: Config | None = None, **kw) -> Respuesta:
    """
    Atajo de un solo uso que reutiliza un motor global.

    Pensado para scripts e interfaces sencillas (el bot de Telegram). Las aplicaciones
    que gestionan su propio ciclo de vida deberian instanciar `MotorRAG` y quedarselo.
    """
    global _MOTOR
    if _MOTOR is None:
        from .config import load_config
        _MOTOR = MotorRAG(cfg or load_config())
    return _MOTOR.responder(pregunta, **kw)
