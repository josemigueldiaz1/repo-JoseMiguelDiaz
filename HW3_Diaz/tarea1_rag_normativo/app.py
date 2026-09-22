"""
TAREA 1 — Interfaz Streamlit. Proceso ONLINE.

Esta app es **solo interfaz**: no extrae PDFs, no trocea, no calcula embeddings de
documentos y no construye el indice. Todo eso ocurrio en `build_index.py`. Aqui solo se
abre el indice ya construido y se llama a `motor.responder()`, que es la unica funcion
del sistema que responde preguntas.

La frontera importa por una razon practica que se ve en el arranque: si la app
reconstruyera el indice al cargar, cada `streamlit run` tardaria minuto y medio y cada
usuario pagaria ese tiempo. Asi arranca en segundos.

Ejecucion:
    streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(RAIZ.parent / ".env")

from src import embeddings  # noqa: E402
from src.config import load_config  # noqa: E402
from src.costos import tabla_precios  # noqa: E402
from src.indice import IndiceVectorial  # noqa: E402
from src.motor import MotorRAG  # noqa: E402

st.set_page_config(page_title="Asistente Normativo — Contrataciones Públicas",
                   page_icon="⚖️", layout="wide")


# ============================================================================== cache
# `cache_resource` para objetos vivos y costosos (el modelo de embeddings pesa y tarda
# ~5s en cargar); `cache_data` para tablas, que se serializan sin problema. Usar
# cache_data con el motor lo intentaria serializar y fallaria.
@st.cache_resource(show_spinner="Cargando el motor RAG…")
def cargar_motor():
    cfg = load_config()
    return cfg, MotorRAG(cfg)


@st.cache_data(show_spinner=False)
def cargar_tabla(ruta: str) -> pd.DataFrame:
    p = Path(ruta)
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


try:
    cfg, motor = cargar_motor()
except Exception as e:  # noqa: BLE001
    st.error(f"No se pudo iniciar el motor: {e}")
    st.info("¿Construiste el índice?  `python build_index.py`")
    st.stop()

if len(motor.indice) == 0:
    st.error("El índice está vacío.")
    st.code("python build_index.py", language="powershell")
    st.stop()

A = cfg.raw["app"]

# ============================================================================ cabecera
st.title(A["titulo"])
st.caption(A["subtitulo"])

c1, c2, c3, c4 = st.columns(4)
c1.metric("Fragmentos indexados", f"{len(motor.indice):,}")
c2.metric("Documentos", len(cfg.fuentes_indexables()))
c3.metric("Umbral de abstención", f"{cfg.motor['umbral_similitud']:.2f}")
c4.metric("Gasto acumulado", f"${motor.costos.total_usd():.4f}")

# ============================================================================= sidebar
with st.sidebar:
    st.header("Parámetros")
    st.caption("Todos vienen de `config.yaml`. Aquí se pueden mover para experimentar "
               "sin tocar el archivo.")
    top_k = st.slider("Fragmentos a recuperar (k)", 1, 10,
                      int(cfg.motor["top_k"]))
    umbral = st.slider("Umbral de similitud", 0.60, 0.95,
                       float(cfg.motor["umbral_similitud"]), 0.01,
                       help="Por debajo de este valor el sistema se abstiene SIN llamar "
                            "al modelo. Calibrado con el barrido de eval/.")
    st.divider()
    st.subheader("Corpus indexado")
    for f in cfg.fuentes_indexables():
        st.markdown(f"- **{f.clave}** · v{f.version}"
                    f"{' · modificatoria' if f.es_modificatoria else ''}")
    fuera = [f for f in cfg.fuentes.values() if not f.indexar]
    if fuera:
        st.subheader("Fuera del corpus (a propósito)")
        for f in fuera:
            st.markdown(f"- {f.clave}")
        st.caption("Muchas preguntas reales solo las responde el Reglamento. El "
                   "asistente debe decirlo, no improvisar.")

# =============================================================================== tabs
tab_preg, tab_calidad, tab_eval, tab_costos = st.tabs(
    ["Preguntar", "Calidad de extracción", "Evaluación", "Costos"])

# ------------------------------------------------------------------------ preguntar
with tab_preg:
    if "pregunta" not in st.session_state:
        st.session_state.pregunta = ""

    st.write("**Ejemplos** (el último está fuera de dominio a propósito):")
    cols = st.columns(len(A["ejemplos"]))
    for col, ej in zip(cols, A["ejemplos"]):
        if col.button(ej, use_container_width=True):
            st.session_state.pregunta = ej

    pregunta = st.text_input("Tu pregunta:", value=st.session_state.pregunta,
                             placeholder="¿Qué garantías me pueden exigir?")
    lanzar = st.button("Preguntar", type="primary")

    # La respuesta se guarda en session_state y se pinta FUERA del `if`.
    #
    # Motivo: en Streamlit, pulsar cualquier boton vuelve a ejecutar el script entero, y
    # en esa pasada `lanzar` vale False. Si la respuesta se pintara dentro del `if`, al
    # pulsar despues un boton de ejemplo —o cualquier otro— desapareceria de pantalla.
    if lanzar and pregunta.strip():
        with st.spinner("Buscando en las normas…"):
            st.session_state.resultado_t1 = motor.responder(
                pregunta, top_k=top_k, umbral=umbral)

    r = st.session_state.get("resultado_t1")
    if r is not None:
        # --- un error es un error, nunca una respuesta ---
        if r.error:
            st.error("**Error del sistema** — esto no es una respuesta.")
            st.code(r.error)
            st.caption(cfg.motor["mensajes"]["error_api"])

        elif r.abstuvo:
            etiqueta = {"umbral": "filtro 1 · umbral de similitud (no se llamó al modelo)",
                        "modelo": "filtro 2 · el modelo revisó el contexto y no encontró la respuesta"}
            st.warning(f"**El asistente se abstuvo** — {etiqueta.get(r.filtro_que_decidio, '')}")
            st.write(r.respuesta)
            m1, m2, m3 = st.columns(3)
            m1.metric("Similitud máxima", f"{r.similitud_maxima:.4f}")
            m2.metric("Umbral", f"{r.umbral:.2f}")
            m3.metric("Costo de esta consulta", f"${r.costo_usd:.6f}")
            if not r.llamo_al_modelo:
                st.success("Abstención gratuita: 0 tokens, 0 USD. La decisión se tomó "
                           "antes de llamar a la API.")

        else:
            st.success("**Respuesta**")
            st.write(r.respuesta)
            if r.nota_version:
                st.info(f"⚠️ {r.nota_version}")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Similitud máxima", f"{r.similitud_maxima:.4f}")
            m2.metric("Tokens", f"{r.tokens_entrada}+{r.tokens_salida}")
            m3.metric("Costo", f"${r.costo_usd:.6f}")
            m4.metric("Latencia", f"{r.latencia_seg:.1f} s")
            st.caption(f"Tarifa aplicada: franja **{r.franja_tarifa}** "
                       f"(precios verificados el {cfg.costos['verificado_el']})")

        # --- fuentes, siempre ---
        if r.fuentes:
            st.divider()
            st.subheader("Fragmentos recuperados")
            for i, f in enumerate(r.fuentes, start=1):
                marca = " · NORMA MODIFICATORIA" if f.es_modificatoria else ""
                with st.expander(
                        f"{i}. {f.cita} · similitud {f.similitud:.4f}{marca}"):
                    st.caption(f"{f.documento_desc} · versión {f.version}")
                    st.write(f.texto)

# --------------------------------------------------------------- calidad extracción
with tab_calidad:
    st.subheader("Comprobación de fuentes (Fase 1)")
    st.caption("Se ejecuta ANTES de construir nada: una fuente que no se puede leer "
               "cambia el plan entero del proyecto.")
    sc = cargar_tabla(str(cfg.processed_dir / "source_check.csv"))
    if len(sc):
        st.dataframe(sc[["archivo", "paginas", "caracteres_por_pagina",
                         "pct_paginas_sin_texto", "orden_correcto", "usable",
                         "indexado", "fecha_descarga"]], use_container_width=True)

    st.subheader("Calidad de extracción por documento")
    st.dataframe(cargar_tabla(str(cfg.processed_dir / "extraccion_calidad.csv")),
                 use_container_width=True)

    st.subheader("Reglas de limpieza y cuántas veces acertó cada una")
    st.caption("Contar los aciertos no es decorativo: es lo que delata una regla que "
               "no hace nada. Una regla rota no da error, solo deja el texto sucio.")
    reglas = cargar_tabla(str(cfg.processed_dir / "limpieza_reglas.csv"))
    if len(reglas):
        st.dataframe(reglas, use_container_width=True)

    ad = cfg.processed_dir / "limpieza_antes_despues.md"
    if ad.exists():
        with st.expander("Ejemplo real de antes y después de la limpieza"):
            st.markdown(ad.read_text(encoding="utf-8"))

    st.subheader("Fragmentos por documento")
    st.dataframe(cargar_tabla(str(cfg.processed_dir / "fragmentos_resumen.csv")),
                 use_container_width=True)

# ------------------------------------------------------------------------ evaluación
with tab_eval:
    res = cfg.eval_dir / "resultados"
    st.subheader("Barrido del umbral — la evidencia para elegirlo")
    st.caption("Recall@k no cambia con el umbral, y eso es correcto: mide al buscador, "
               "que devuelve siempre lo mismo. El umbral solo decide si se usa.")
    bar = cargar_tabla(str(res / "barrido_umbral.csv"))
    if len(bar):
        st.dataframe(bar, use_container_width=True)
        st.bar_chart(bar.set_index("umbral")[["aciertos_totales"]])
    else:
        st.info("Corre `python eval/evaluar.py` para generar estos resultados.")

    st.subheader("Detalle por pregunta")
    det = cargar_tabla(str(res / "detalle_preguntas.csv"))
    if len(det):
        st.dataframe(det, use_container_width=True)
        st.caption("Fíjate en las preguntas out_domain 'cercanas': puntúan MÁS ALTO que "
                   "muchas válidas. Ningún umbral puede separarlas; por eso hay un "
                   "segundo filtro.")

    st.subheader("Innovación · BM25 léxico frente a embeddings semánticos")
    bm = cargar_tabla(str(res / "bm25_vs_embeddings.csv"))
    if len(bm):
        resumen = bm.groupby("estilo")[["bm25_acierta_top3", "embeddings_acierta_top3"]] \
                    .mean().round(3) * 100
        st.dataframe(resumen, use_container_width=True)
        st.caption("La brecha se multiplica en las preguntas coloquiales: el empresario "
                   "dice 'carta fianza' y la Ley dice 'garantía de fiel cumplimiento'. "
                   "Cero palabras en común, así que BM25 no puede encontrarlo.")

    st.subheader("Experimento descartado · el índice de control")
    ctrl = cargar_tabla(str(res / "control_discriminacion.csv"))
    if len(ctrl):
        st.dataframe(ctrl, use_container_width=True)
        st.caption("Hipótesis: una pregunta de Reglamento se parecería más a la colección "
                   "de control. Resultado medido: no discrimina. Se descartó con datos.")

# --------------------------------------------------------------------------- costos
with tab_costos:
    st.subheader("Precios aplicados")
    st.caption(f"Verificados el {cfg.costos['verificado_el']} en {cfg.costos['fuente']}. "
               "DeepSeek cobra la mitad fuera de sus franjas pico, así que el precio "
               "depende de la hora de cada llamada.")
    st.dataframe(tabla_precios(cfg), use_container_width=True)

    franja, precios = cfg.tarifa_vigente()
    st.info(f"En este momento aplica la franja **{franja}**: "
            f"entrada {precios['entrada_cache_miss']} y salida {precios['salida']} "
            f"USD por millón de tokens.")

    st.subheader("Llamadas registradas")
    resumen = motor.costos.resumen()
    if len(resumen):
        st.dataframe(resumen, use_container_width=True)
        st.metric("Total gastado", f"${motor.costos.total_usd():.6f}")
    else:
        st.info("Todavía no se ha registrado ninguna llamada.")

    st.subheader("Log completo")
    log = cargar_tabla(str(motor.costos.ruta))
    if len(log):
        st.dataframe(log.tail(50), use_container_width=True)
        st.caption("Se registran también las llamadas fallidas: una tabla de costos que "
                   "solo cuenta los éxitos miente sobre lo que costó llegar al resultado.")
