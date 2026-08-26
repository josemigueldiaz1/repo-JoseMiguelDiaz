"""
Lichess API - Analisis de partidas (Parte A) y Automatizacion de torneos (Parte B)

Parte A: descarga partidas publicas de un usuario, arma un DataFrame, calcula
estadisticas (resultados, rating, color, modalidad) y genera graficos + CSVs.

Parte B: define un calendario semanal de torneos y los crea via la API de
Lichess. Corre en modo simulacion (dry-run) por defecto: no necesita ninguna
credencial para ejecutarse. Solo intenta crear torneos reales si se pasa
--live Y existe un token valido (variable de entorno LICHESS_TOKEN o archivo
.env junto al script).

Uso:
    python "3. Lichess API - Data Analysis and Automation.py"
    python "3. Lichess API - Data Analysis and Automation.py" --username DrNykterstein --max-games 200
    python "3. Lichess API - Data Analysis and Automation.py" --live
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # backend sin interfaz grafica, necesario para correr sin sesion interactiva
import matplotlib.pyplot as plt
import pandas as pd
import requests

try:
    SCRIPT_DIR = Path(__file__).resolve().parent
except NameError:
    SCRIPT_DIR = Path.cwd()

LICHESS_API_BASE = "https://lichess.org"

# Lichess (o su proxy) rechaza con 404 las peticiones que traen el User-Agent
# por defecto de la libreria requests ("python-requests/x.x"); se fuerza uno
# de navegador real en todas las llamadas para evitar ese bloqueo.
USER_AGENT_BASE = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# ---------------------------------------------------------------------------
# Calendario semanal de torneos (Parte B). Es solo configuracion de datos:
# cambiar dias/horas/modalidades aqui no requiere tocar la logica del script.
# weekday: 0=Lunes ... 6=Domingo
# ---------------------------------------------------------------------------
CALENDARIO_SEMANAL = [
    {"nombre": "Blitz Nocturno", "weekday": 0, "hora": 20, "minuto": 0,
     "clock_time": 5, "clock_increment": 3, "duracion_min": 60,
     "variante": "standard", "rated": True},
    {"nombre": "Rapid de Miercoles", "weekday": 2, "hora": 19, "minuto": 0,
     "clock_time": 10, "clock_increment": 0, "duracion_min": 90,
     "variante": "standard", "rated": True},
    {"nombre": "Bullet Viernes", "weekday": 4, "hora": 21, "minuto": 0,
     "clock_time": 1, "clock_increment": 0, "duracion_min": 45,
     "variante": "standard", "rated": True},
    {"nombre": "Chess960 Sabatino", "weekday": 5, "hora": 15, "minuto": 0,
     "clock_time": 3, "clock_increment": 2, "duracion_min": 60,
     "variante": "chess960", "rated": True},
]


def parse_args():
    parser = argparse.ArgumentParser(description="Lichess API - analisis de partidas y automatizacion de torneos")
    parser.add_argument(
        "--username", default="DrNykterstein",
        help="Usuario de Lichess a analizar en la Parte A (default: DrNykterstein, cuenta publica de ejemplo)"
    )
    parser.add_argument(
        "--max-games", type=int, default=100,
        help="Cantidad de partidas a descargar en la Parte A (default: 100)"
    )
    parser.add_argument(
        "--output-dir", default=str(SCRIPT_DIR / "lichess_output"),
        help="Carpeta donde se guardan los CSV y graficos (default: lichess_output junto al script)"
    )
    parser.add_argument(
        "--log-file", default=str(SCRIPT_DIR / "lichess_bot.log"),
        help="Ruta del archivo de log (default: junto al script)"
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Intenta crear los torneos de verdad en Lichess (requiere LICHESS_TOKEN). "
             "Sin este flag, o si no hay token, la Parte B corre en modo simulacion (dry-run)."
    )
    parser.add_argument(
        "--request-delay", type=float, default=1.0,
        help="Pausa en segundos entre llamadas a la API para respetar el rate limit (default: 1s)"
    )
    return parser.parse_args()


def setup_logging(log_file):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def cargar_token_local():
    """Busca LICHESS_TOKEN en el entorno o en un archivo .env junto al script.
    Nunca se escribe ningun token dentro del codigo fuente."""
    import os

    if os.environ.get("LICHESS_TOKEN"):
        return os.environ["LICHESS_TOKEN"].strip()

    env_path = SCRIPT_DIR / ".env"
    if env_path.exists():
        for linea in env_path.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, _, valor = linea.partition("=")
            if clave.strip() == "LICHESS_TOKEN":
                valor = valor.strip().strip('"').strip("'")
                if valor:
                    return valor
    return None


def _request_con_reintentos(method, url, max_reintentos=3, **kwargs):
    """Wrapper generico para GET/POST que respeta rate limits (HTTP 429)
    leyendo el header Retry-After antes de reintentar."""
    headers = {"User-Agent": USER_AGENT_BASE, **kwargs.pop("headers", {})}

    for intento in range(1, max_reintentos + 1):
        respuesta = requests.request(method, url, timeout=30, headers=headers, **kwargs)
        if respuesta.status_code == 429:
            espera = int(respuesta.headers.get("Retry-After", "60"))
            logging.warning("Rate limit alcanzado (intento %s/%s). Esperando %ss.",
                             intento, max_reintentos, espera)
            time.sleep(espera)
            continue
        return respuesta
    return respuesta


# ===========================================================================
# PARTE A - Analisis de partidas
# ===========================================================================

def descargar_partidas(username, max_games, token=None):
    """Descarga partidas publicas de un usuario en formato NDJSON.
    Si hay un token disponible, se manda autenticado: Lichess otorga un
    limite de peticiones (rate limit) bastante mas alto a consultas
    autenticadas que a anonimas, aunque los datos en si sean publicos."""
    url = f"{LICHESS_API_BASE}/api/games/user/{username}"
    params = {
        "max": max_games,
        "moves": "false",
        "opening": "false",
        "clocks": "false",
        "evals": "false",
    }
    headers = {"Accept": "application/x-ndjson"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    respuesta = _request_con_reintentos("GET", url, params=params, headers=headers)
    respuesta.raise_for_status()

    partidas = []
    for linea in respuesta.text.splitlines():
        linea = linea.strip()
        if linea:
            partidas.append(json.loads(linea))
    return partidas


def construir_dataframe(partidas_raw, username):
    """Convierte la lista de partidas (NDJSON) en un DataFrame con columnas
    ya calculadas: color jugado, rating propio/rival, resultado, modalidad."""
    username_lower = username.lower()
    filas = []

    for partida in partidas_raw:
        jugadores = partida.get("players", {})
        blancas = jugadores.get("white", {})
        negras = jugadores.get("black", {})
        id_blancas = (blancas.get("user") or {}).get("id", "")
        id_negras = (negras.get("user") or {}).get("id", "")

        if id_blancas == username_lower:
            color, rating_propio, rating_rival = "white", blancas.get("rating"), negras.get("rating")
        elif id_negras == username_lower:
            color, rating_propio, rating_rival = "black", negras.get("rating"), blancas.get("rating")
        else:
            # Partida sin el usuario identificado como blancas/negras (cuenta anonima, dato incompleto): se omite.
            continue

        ganador = partida.get("winner")
        if ganador is None:
            resultado = "draw"
        elif ganador == color:
            resultado = "win"
        else:
            resultado = "loss"

        filas.append({
            "id_partida": partida.get("id"),
            "fecha": pd.to_datetime(partida.get("createdAt"), unit="ms", errors="coerce"),
            "modalidad": partida.get("speed"),
            "variante": partida.get("variant"),
            "clasificada": partida.get("rated"),
            "color": color,
            "rating_propio": rating_propio,
            "rating_rival": rating_rival,
            "resultado": resultado,
            "estado_final": partida.get("status"),
        })

    df = pd.DataFrame(filas)
    if not df.empty:
        df = df.sort_values("fecha").reset_index(drop=True)
    return df


def calcular_estadisticas(df):
    """Devuelve un diccionario de DataFrames: resultados, color, modalidad, rating."""
    if df.empty:
        return {}

    resultados = df["resultado"].value_counts().rename_axis("resultado").reset_index(name="cantidad")
    resultados["porcentaje"] = (resultados["cantidad"] / len(df) * 100).round(1)

    por_color = df.groupby("color").agg(
        partidas=("resultado", "count"),
        victorias=("resultado", lambda s: (s == "win").sum()),
    )
    por_color["pct_victorias"] = (por_color["victorias"] / por_color["partidas"] * 100).round(1)
    por_color = por_color.reset_index()

    por_modalidad = df.groupby("modalidad").agg(
        partidas=("resultado", "count"),
        victorias=("resultado", lambda s: (s == "win").sum()),
    )
    por_modalidad["pct_victorias"] = (por_modalidad["victorias"] / por_modalidad["partidas"] * 100).round(1)
    por_modalidad = por_modalidad.reset_index()

    rating_valido = df["rating_propio"].dropna()
    resumen_rating = pd.DataFrame([{
        "rating_inicial": rating_valido.iloc[0] if not rating_valido.empty else None,
        "rating_final": rating_valido.iloc[-1] if not rating_valido.empty else None,
        "rating_minimo": rating_valido.min() if not rating_valido.empty else None,
        "rating_maximo": rating_valido.max() if not rating_valido.empty else None,
        "rating_promedio": round(rating_valido.mean(), 1) if not rating_valido.empty else None,
    }])

    return {
        "resultados": resultados,
        "por_color": por_color,
        "por_modalidad": por_modalidad,
        "resumen_rating": resumen_rating,
    }


def generar_graficos(df, output_dir, username):
    if df.empty:
        logging.warning("No hay partidas para graficar.")
        return

    output_dir = Path(output_dir)

    # Resultados
    fig, ax = plt.subplots()
    df["resultado"].value_counts().plot(kind="bar", ax=ax, color=["#4caf50", "#f44336", "#9e9e9e"])
    ax.set_title(f"Resultados de {username}")
    ax.set_xlabel("Resultado")
    ax.set_ylabel("Cantidad de partidas")
    fig.tight_layout()
    fig.savefig(output_dir / "grafico_resultados.png")
    plt.close(fig)

    # Evolucion del rating
    df_rating = df.dropna(subset=["rating_propio"])
    if not df_rating.empty:
        fig, ax = plt.subplots()
        ax.plot(df_rating["fecha"], df_rating["rating_propio"], marker="o", markersize=3)
        ax.set_title(f"Evolucion de rating de {username}")
        ax.set_xlabel("Fecha")
        ax.set_ylabel("Rating")
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(output_dir / "grafico_rating.png")
        plt.close(fig)

    # Partidas por color
    fig, ax = plt.subplots()
    df["color"].value_counts().plot(kind="bar", ax=ax, color=["#e0e0e0", "#424242"])
    ax.set_title(f"Partidas por color de {username}")
    ax.set_xlabel("Color")
    ax.set_ylabel("Cantidad de partidas")
    fig.tight_layout()
    fig.savefig(output_dir / "grafico_color.png")
    plt.close(fig)

    # Partidas por modalidad
    fig, ax = plt.subplots()
    df["modalidad"].value_counts().plot(kind="bar", ax=ax, color="#1976d2")
    ax.set_title(f"Partidas por modalidad de {username}")
    ax.set_xlabel("Modalidad")
    ax.set_ylabel("Cantidad de partidas")
    fig.tight_layout()
    fig.savefig(output_dir / "grafico_modalidad.png")
    plt.close(fig)


def exportar_parte_a(df, estadisticas, output_dir, username):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df.to_csv(output_dir / f"partidas_{username}.csv", index=False, encoding="utf-8-sig")
    for nombre, tabla in estadisticas.items():
        tabla.to_csv(output_dir / f"estadisticas_{nombre}.csv", index=False, encoding="utf-8-sig")


def ejecutar_parte_a(username, max_games, output_dir, token=None):
    logging.info("===== PARTE A: analisis de partidas de '%s' =====", username)
    try:
        partidas_raw = descargar_partidas(username, max_games, token=token)
    except requests.RequestException as e:
        logging.error("No se pudo descargar partidas de Lichess: %s", e)
        return

    logging.info("Partidas descargadas: %s", len(partidas_raw))
    df = construir_dataframe(partidas_raw, username)

    if df.empty:
        logging.warning("El usuario '%s' no tiene partidas utilizables. Se omite el analisis.", username)
        return

    estadisticas = calcular_estadisticas(df)
    generar_graficos(df, output_dir, username)
    exportar_parte_a(df, estadisticas, output_dir, username)

    logging.info("Resultados: %s", estadisticas["resultados"].to_dict("records"))
    logging.info("Por color: %s", estadisticas["por_color"].to_dict("records"))
    logging.info("Por modalidad: %s", estadisticas["por_modalidad"].to_dict("records"))
    logging.info("Resumen de rating: %s", estadisticas["resumen_rating"].to_dict("records"))
    logging.info("CSVs y graficos guardados en: %s", output_dir)


# ===========================================================================
# PARTE B - Automatizacion de torneos
# ===========================================================================

def calcular_proxima_fecha(entry, ahora):
    """Calcula la fecha/hora de la ocurrencia de ESTA semana para un item del
    calendario (lunes de la semana actual + weekday + hora:minuto)."""
    inicio_semana = ahora - timedelta(days=ahora.weekday())
    inicio_semana = inicio_semana.replace(hour=0, minute=0, second=0, microsecond=0)
    fecha = inicio_semana + timedelta(days=entry["weekday"], hours=entry["hora"], minutes=entry["minuto"])
    return fecha


def crear_torneo(entry, fecha_inicio, token, dry_run):
    """Crea un torneo arena en Lichess (o simula la creacion si dry_run=True)."""
    payload = {
        "name": entry["nombre"],
        "clockTime": entry["clock_time"],
        "clockIncrement": entry["clock_increment"],
        "minutes": entry["duracion_min"],
        "startDate": int(fecha_inicio.timestamp() * 1000),
        "variant": entry["variante"],
        "rated": "true" if entry["rated"] else "false",
    }

    if dry_run:
        logging.info("[DRY-RUN] Se crearia el torneo '%s' el %s con parametros: %s",
                     entry["nombre"], fecha_inicio.strftime("%Y-%m-%d %H:%M"), payload)
        return True

    url = f"{LICHESS_API_BASE}/api/tournament"
    headers = {"Authorization": f"Bearer {token}"}
    respuesta = _request_con_reintentos("POST", url, data=payload, headers=headers)

    if respuesta.status_code >= 400:
        logging.error("Lichess rechazo la creacion de '%s' (HTTP %s): %s",
                       entry["nombre"], respuesta.status_code, respuesta.text[:300])
        return False

    logging.info("Torneo '%s' creado correctamente para el %s.",
                 entry["nombre"], fecha_inicio.strftime("%Y-%m-%d %H:%M"))
    return True


def ejecutar_parte_b(token, live, request_delay):
    logging.info("===== PARTE B: automatizacion de torneos =====")

    dry_run = (not live) or (token is None)
    if live and token is None:
        logging.warning("Se pidio --live pero no se encontro LICHESS_TOKEN. "
                         "Se continua en modo simulacion (dry-run) para no interrumpir la ejecucion.")
    logging.info("Modo de ejecucion: %s", "REAL (crea torneos en Lichess)" if not dry_run else "SIMULACION (dry-run)")

    ahora = datetime.now()
    creados, omitidos_pasado, fallidos = 0, 0, 0

    for i, entry in enumerate(CALENDARIO_SEMANAL):
        fecha_inicio = calcular_proxima_fecha(entry, ahora)

        if fecha_inicio <= ahora:
            logging.info("Se omite '%s': su horario (%s) ya paso esta semana.",
                         entry["nombre"], fecha_inicio.strftime("%Y-%m-%d %H:%M"))
            omitidos_pasado += 1
            continue

        try:
            exito = crear_torneo(entry, fecha_inicio, token, dry_run)
            if exito:
                creados += 1
            else:
                fallidos += 1
        except requests.RequestException as e:
            logging.warning("Error de red/API al crear '%s': %s. Se continua con el siguiente.",
                             entry["nombre"], e)
            fallidos += 1

        if i < len(CALENDARIO_SEMANAL) - 1:
            time.sleep(request_delay)

    logging.info("Resumen Parte B -> creados/simulados: %s, omitidos (horario pasado): %s, fallidos: %s",
                 creados, omitidos_pasado, fallidos)


# ===========================================================================
# Main
# ===========================================================================

def main():
    args = parse_args()
    setup_logging(args.log_file)

    logging.info("Iniciando script de Lichess API")

    token = cargar_token_local()

    ejecutar_parte_a(args.username, args.max_games, args.output_dir, token=token)

    time.sleep(args.request_delay)

    ejecutar_parte_b(token, args.live, args.request_delay)

    logging.info("Proceso finalizado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
