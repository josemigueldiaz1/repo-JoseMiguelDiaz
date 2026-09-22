"""
Fase 3 — RAG HIBRIDO: filtros estructurados + busqueda semantica.

**Que reutiliza de la Tarea 1** (el enunciado lo pide expresamente):

    embeddings.crear      el mismo modelo local multilingual-e5-small
    IndiceVectorial       el mismo envoltorio sobre ChromaDB
    RegistroCostos        el mismo registro de costos con tarifa horaria
    Config                la clase base de la que hereda el Config de esta tarea

No hay ni una linea duplicada de esos modulos. Si se corrige un fallo alli, se corrige
aqui.

**Por que las condiciones numericas y territoriales son FILTROS y no embeddings.**
El enunciado pide explicarlo y es la decision central de esta fase. Tomemos la pregunta
del propio enunciado:

    "obras de agua y saneamiento en Cusco por mas de un millon de soles"

Contiene tres condiciones de naturaleza distinta:

1. *"obras de agua y saneamiento"* es **semantica**. No hay ninguna columna que diga
   "agua y saneamiento"; hay descripciones libres que pueden decir "mejoramiento del
   sistema de agua potable", "ampliacion de redes de alcantarillado" o "planta de
   tratamiento de aguas residuales". Ninguna comparte palabras con la pregunta, pero
   todas significan lo mismo. Esto es exactamente para lo que sirven los embeddings.

2. *"por mas de un millon de soles"* es **numerico**, y un embedding no puede resolverlo.
   El vector de "un millon de soles" esta cerquisima del de "900,000 soles": son textos
   parecidos. Pero 900,000 **no cumple** la condicion. Los embeddings capturan parecido,
   no orden ni magnitud; no existe un "mayor que" en el espacio vectorial. Una respuesta
   construida por similitud incluiria procesos que incumplen la condicion, y lo haria de
   forma plausible, que es la peor manera de equivocarse.

3. *"en Cusco"* es **territorial**, y parece semantica pero no lo es. Si se dejara a los
   embeddings, un proceso de una entidad de Lima cuya descripcion mencione "carretera
   Lima-Cusco" puntuaria alto. El departamento no es lo que el texto menciona: es un
   atributo del comprador, que ya normalizamos en la Fase 2 y que esta como metadato.

Regla practica: **lo que es exacto y verificable va a un filtro; lo que es ambiguo va a
los embeddings.** Un filtro tiene ademas dos virtudes que la similitud no tiene: es
exacto (no hay falsos positivos) y es explicable al usuario ("se aplico monto >= 1e6").
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
import sys

HW3 = Path(__file__).resolve().parent.parent.parent
if str(HW3) not in sys.path:
    sys.path.insert(0, str(HW3))

import pandas as pd  # noqa: E402

# --- REUTILIZACION DIRECTA DE LA TAREA 1 ---
from tarea1_rag_normativo.src.config import Config as ConfigT1  # noqa: E402
from tarea1_rag_normativo.src.costos import RegistroCostos  # noqa: E402
from tarea1_rag_normativo.src.embeddings import Embedder, crear as crear_embedder  # noqa: E402
from tarea1_rag_normativo.src.indice import IndiceVectorial  # noqa: E402

from .config import Config  # noqa: E402
from .territorio import NO_LOCALIZADO, normalizar_texto  # noqa: E402

log = logging.getLogger("hw3.t2.motor")


# ============================================================================= filtros
@dataclass
class Filtros:
    """
    Condiciones estructuradas de una consulta.

    Se construyen desde la barra lateral del dashboard o desde `desde_texto()`. Viajan
    aparte de la pregunta precisamente porque NO deben pasar por los embeddings.
    """

    departamentos: list[str] = field(default_factory=list)
    categorias: list[str] = field(default_factory=list)
    monto_min: float | None = None
    monto_max: float | None = None
    fecha_desde: str | None = None
    fecha_hasta: str | None = None
    solo_adjudicados: bool = False

    def a_where(self) -> dict | None:
        """
        Traduce los filtros al lenguaje `where` de ChromaDB.

        Solo se traducen aqui los que ChromaDB sabe aplicar sobre metadatos escalares.
        Las fechas se filtran despues sobre el dataframe, porque se guardan como cadena
        ISO y una comparacion lexicografica seria correcta pero fragil ante zonas
        horarias distintas.
        """
        clausulas: list[dict] = []
        if self.departamentos:
            clausulas.append({"departamento": {"$in": list(self.departamentos)}})
        if self.categorias:
            clausulas.append({"categoria": {"$in": list(self.categorias)}})
        if self.monto_min is not None:
            clausulas.append({"monto": {"$gte": float(self.monto_min)}})
        if self.monto_max is not None:
            clausulas.append({"monto": {"$lte": float(self.monto_max)}})
        if self.solo_adjudicados:
            clausulas.append({"adjudicado": True})

        if not clausulas:
            return None
        if len(clausulas) == 1:
            return clausulas[0]
        return {"$and": clausulas}

    def descripcion(self) -> str:
        """Texto legible de los filtros, para mostrarselo al modelo y al usuario."""
        p = []
        if self.departamentos:
            p.append(f"departamento en {', '.join(self.departamentos)}")
        if self.categorias:
            p.append(f"categoria en {', '.join(self.categorias)}")
        if self.monto_min is not None:
            p.append(f"monto >= {self.monto_min:,.0f} PEN")
        if self.monto_max is not None:
            p.append(f"monto <= {self.monto_max:,.0f} PEN")
        if self.fecha_desde:
            p.append(f"desde {self.fecha_desde}")
        if self.fecha_hasta:
            p.append(f"hasta {self.fecha_hasta}")
        if self.solo_adjudicados:
            p.append("solo adjudicados")
        return "; ".join(p) if p else "ninguno"


# ============================================================================ resultado
@dataclass
class ProcesoRecuperado:
    ocid: str
    descripcion: str
    comprador: str
    departamento: str
    categoria: str
    monto: float
    fecha: str
    n_licitantes: float | None
    adjudicado: bool
    similitud: float
    # El metodo de contratacion lo consume la innovacion que enlaza las dos tareas:
    # es la clave con la que se le pregunta al asistente normativo que regla aplica.
    metodo: str = ""


@dataclass
class RespuestaRadar:
    """Mismo contrato que la Respuesta de la Tarea 1, adaptado al dominio."""

    pregunta: str
    respuesta: str = ""
    procesos: list[ProcesoRecuperado] = field(default_factory=list)
    filtros: str = "ninguno"
    candidatos_tras_filtros: int = 0

    abstuvo: bool = False
    motivo_abstencion: str = ""
    filtro_que_decidio: str = ""
    similitud_maxima: float = 0.0
    umbral: float = 0.0

    modelo: str = ""
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo_usd: float = 0.0
    franja_tarifa: str = ""
    latencia_seg: float = 0.0
    llamo_al_modelo: bool = False

    error: str = ""

    def a_dict(self) -> dict:
        d = asdict(self)
        d["procesos"] = [asdict(p) for p in self.procesos]
        return d


# =============================================================================== motor
class MotorRadar:
    """RAG hibrido sobre procesos de contratacion."""

    def __init__(self, cfg: Config, embedder: Embedder | None = None):
        self.cfg = cfg
        self.m = cfg.motor
        self.emb = embedder or crear_embedder(cfg)
        self.indice = IndiceVectorial(cfg, self.emb)
        self.costos = RegistroCostos(cfg, tarea="tarea2")
        self._cliente = None

    def _cliente_llm(self):
        if self._cliente is None:
            from openai import OpenAI
            self._cliente = OpenAI(
                api_key=ConfigT1.credencial("DEEPSEEK_API_KEY"),
                base_url=self.m["base_url"],
            )
        return self._cliente

    # ------------------------------------------------------------------- indexacion
    def indexar(self, df: pd.DataFrame, lote: int = 256, reconstruir: bool = False) -> dict:
        """
        Indexa las descripciones de proceso con los campos estructurados como metadatos.

        Solo entran los procesos `apto_para_indice` (con descripcion util). Vectorizar
        una descripcion vacia produce un vector sin contenido que luego aparece en
        cualquier busqueda como ruido.
        """
        if reconstruir:
            self.indice.vaciar()

        d = df[df["apto_para_indice"]].copy()
        existentes = self.indice.ids_existentes()
        d = d[~d["ocid"].isin(existentes)]
        if d.empty:
            log.info("  el indice ya contiene los %d procesos; no se reindexa",
                     len(self.indice))
            return {"insertados": 0, "total": len(self.indice), "segundos": 0.0}

        log.info("  indexando %d procesos nuevos (%d ya estaban)", len(d), len(existentes))
        t0 = time.perf_counter()

        for i in range(0, len(d), lote):
            g = d.iloc[i:i + lote]
            textos = (g["titulo"].fillna("") + ". " + g["descripcion"].fillna("")).tolist()
            vectores = self.emb.codificar_pasajes(textos)
            metadatos = []
            for _, f in g.iterrows():
                metadatos.append({
                    "ocid": str(f["ocid"]),
                    "comprador": str(f.get("comprador", ""))[:180],
                    "departamento": str(f.get("departamento", NO_LOCALIZADO)),
                    "categoria": str(f.get("categoria", "")),
                    "metodo": str(f.get("metodo", ""))[:120],
                    # ChromaDB solo admite escalares: float, int, str y bool.
                    "monto": float(f["monto"]) if pd.notna(f.get("monto")) else 0.0,
                    "fecha": (str(f["fecha_publicacion"])[:10]
                              if pd.notna(f.get("fecha_publicacion")) else ""),
                    "n_licitantes": float(f["n_licitantes"])
                    if pd.notna(f.get("n_licitantes")) else -1.0,
                    "adjudicado": bool(f.get("adjudicado", False)),
                })
            self.indice._col.add(
                ids=g["ocid"].astype(str).tolist(),
                documents=textos,
                embeddings=[v.tolist() for v in vectores],
                metadatas=metadatos,
            )
            log.info("    %d/%d", min(i + lote, len(d)), len(d))

        dt = time.perf_counter() - t0
        return {"insertados": len(d), "total": len(self.indice), "segundos": round(dt, 1)}

    # ---------------------------------------------------------------------- consulta
    def buscar(self, pregunta: str, filtros: Filtros, k: int) -> list[ProcesoRecuperado]:
        """
        Busqueda semantica RESTRINGIDA por los filtros estructurados.

        El orden importa: primero se acota el universo con condiciones exactas y despues
        se ordena lo que queda por parecido. Hacerlo al reves —recuperar por similitud y
        filtrar despues— produciria menos de k resultados cuando el filtro es selectivo,
        porque los k mejores globales pueden no cumplir ninguno.
        """
        v = self.emb.codificar_consultas([pregunta])[0]
        where = filtros.a_where()
        try:
            r = self.indice._col.query(
                query_embeddings=[v.tolist()],
                n_results=min(k, max(len(self.indice), 1)),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:  # noqa: BLE001
            log.error("  la consulta al indice fallo: %s", e)
            return []

        if not r["ids"] or not r["ids"][0]:
            return []

        salida = []
        for i, _id in enumerate(r["ids"][0]):
            m = r["metadatas"][0][i]
            fecha = m.get("fecha", "")
            # Las fechas se filtran aqui, no en ChromaDB (ver Filtros.a_where).
            if filtros.fecha_desde and fecha and fecha < filtros.fecha_desde:
                continue
            if filtros.fecha_hasta and fecha and fecha > filtros.fecha_hasta:
                continue
            salida.append(ProcesoRecuperado(
                ocid=m.get("ocid", _id),
                descripcion=r["documents"][0][i],
                comprador=m.get("comprador", ""),
                departamento=m.get("departamento", ""),
                categoria=m.get("categoria", ""),
                monto=float(m.get("monto", 0.0)),
                fecha=fecha,
                n_licitantes=(m.get("n_licitantes") if m.get("n_licitantes", -1) >= 0
                              else None),
                adjudicado=bool(m.get("adjudicado", False)),
                similitud=float(1.0 - r["distances"][0][i]),
                metodo=m.get("metodo", ""),
            ))
        return salida

    def _contexto(self, procesos: list[ProcesoRecuperado]) -> str:
        partes = []
        for i, p in enumerate(procesos, start=1):
            partes.append(
                f"--- Proceso {i} · ocid: {p.ocid} · similitud {p.similitud:.3f} ---\n"
                f"Entidad: {p.comprador}\n"
                f"Departamento: {p.departamento} · Categoria: {p.categoria}\n"
                f"Monto: {p.monto:,.0f} PEN · Fecha: {p.fecha}\n"
                f"Postores: {p.n_licitantes if p.n_licitantes is not None else 'sin dato'}"
                f" · Adjudicado: {'si' if p.adjudicado else 'no'}\n"
                f"Descripcion: {p.descripcion[:600]}"
            )
        return "\n\n".join(partes)

    def _leer_json(self, crudo: str) -> tuple[str, bool, str]:
        """Misma logica que la Tarea 1: la abstencion llega como booleano, no como prosa."""
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
        citas = d.get("citas") or []
        if puede and isinstance(citas, list) and citas:
            marca = ", ".join(str(c).strip() for c in citas if str(c).strip())
            if marca and marca not in texto:
                texto = f"{texto}\n\nProcesos citados: {marca}"
        return texto, (not puede), motivo

    # ------------------------------------------------------------------ API publica
    def responder(self, pregunta: str, filtros: Filtros | None = None,
                  top_k: int | None = None, umbral: float | None = None) -> RespuestaRadar:
        """La unica funcion que el dashboard llama."""
        t0 = time.perf_counter()
        filtros = filtros or Filtros()
        k = int(top_k or self.m["top_k"])
        u = float(umbral if umbral is not None else self.m["umbral_similitud"])

        res = RespuestaRadar(pregunta=pregunta, umbral=u, modelo=self.m["modelo"],
                             filtros=filtros.descripcion())

        if not pregunta or not pregunta.strip():
            res.error = "La pregunta esta vacia."
            return res

        procesos = self.buscar(pregunta, filtros, k)
        res.candidatos_tras_filtros = len(procesos)

        if not procesos:
            res.abstuvo = True
            res.filtro_que_decidio = "filtros"
            res.motivo_abstencion = "sin_resultados_filtros"
            res.respuesta = self.m["mensajes"]["sin_resultados_filtros"]
            res.latencia_seg = time.perf_counter() - t0
            return res

        res.procesos = procesos
        res.similitud_maxima = procesos[0].similitud

        # --- filtro 1, gratis ---
        if res.similitud_maxima < u:
            res.abstuvo = True
            res.filtro_que_decidio = "umbral"
            res.motivo_abstencion = "baja_similitud"
            res.respuesta = self.m["mensajes"]["abstencion_baja_similitud"]
            res.latencia_seg = time.perf_counter() - t0
            log.info("  abstencion por umbral · sim %.3f < %.2f · 0 tokens",
                     res.similitud_maxima, u)
            return res

        # --- generacion ---
        p = self.m["prompts"]
        momento = datetime.now(timezone.utc)
        t_api = time.perf_counter()
        extra = {"response_format": {"type": "json_object"}} \
            if self.m.get("formato_json", True) else {}

        try:
            r = self._cliente_llm().chat.completions.create(
                model=self.m["modelo"],
                messages=[
                    {"role": "system", "content": p["sistema"]},
                    {"role": "user", "content": p["usuario"].format(
                        contexto=self._contexto(procesos),
                        filtros=filtros.descripcion(),
                        pregunta=pregunta)},
                ],
                temperature=float(self.m["temperatura"]),
                max_tokens=int(self.m["max_tokens"]),
                timeout=float(self.m["timeout_seg"]),
                **extra,
            )
        except Exception as e:  # noqa: BLE001
            latencia = time.perf_counter() - t_api
            res.error = f"{type(e).__name__}: {str(e)[:220]}"
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
        det = getattr(uso, "prompt_tokens_details", None)
        cache_hit = int(getattr(det, "cached_tokens", 0) or 0) if det else 0

        crudo = (r.choices[0].message.content or "").strip()
        res.llamo_al_modelo = True
        res.tokens_entrada = entrada
        res.tokens_salida = salida

        res.respuesta, no_responde, motivo = self._leer_json(crudo)
        if no_responde:
            res.abstuvo = True
            res.filtro_que_decidio = "modelo"
            res.motivo_abstencion = "sin_respuesta_en_contexto"
            if not res.respuesta:
                res.respuesta = motivo or self.m["mensajes"]["abstencion_fuera_de_corpus"]

        ll = self.costos.registrar(modelo=self.m["modelo"], entrada=entrada, salida=salida,
                                   cache_hit=cache_hit, latencia=latencia_api,
                                   exito=True, pregunta=pregunta, momento=momento)
        res.costo_usd = ll.costo_usd
        res.franja_tarifa = ll.franja
        res.latencia_seg = time.perf_counter() - t0
        log.info("  respondida · %d candidatos · sim %.3f · %d+%d tokens · %.5f USD",
                 res.candidatos_tras_filtros, res.similitud_maxima, entrada, salida,
                 ll.costo_usd)
        return res
