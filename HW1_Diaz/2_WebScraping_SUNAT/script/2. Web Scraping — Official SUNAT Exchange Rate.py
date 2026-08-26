"""
Web Scraping - Tipo de Cambio Oficial SUNAT

"""

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException,
)

try:
    SCRIPT_DIR = Path(__file__).resolve().parent
except NameError:
    # __file__ no existe si se pega el codigo en una celda de Jupyter;
    # se usa el directorio actual como respaldo solo para pruebas interactivas.
    SCRIPT_DIR = Path.cwd()

MESES_ABREV = ["ene.", "feb.", "mar.", "abr.", "may.", "jun.",
               "jul.", "ago.", "sep.", "oct.", "nov.", "dic."]
MESES_LARGO = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
               "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def parse_args():
    hoy = date.today()
    parser = argparse.ArgumentParser(description="Scraper del tipo de cambio oficial SUNAT")
    parser.add_argument(
        "--url", default="https://e-consulta.sunat.gob.pe/cl-at-ittipcam/tcS01Alias",
        help="URL de la consulta de tipo de cambio"
    )
    parser.add_argument(
        "--start-year", type=int, default=2024,
        help="Anio de inicio del rango a extraer (default: 2024)"
    )
    parser.add_argument(
        "--start-month", type=int, default=6,
        help="Mes de inicio del rango, 1=Enero...12=Diciembre (default: 6, Junio)"
    )
    parser.add_argument(
        "--end-year", type=int, default=hoy.year,
        help="Anio final del rango a extraer (default: anio actual)"
    )
    parser.add_argument(
        "--end-month", type=int, default=hoy.month,
        help="Mes final del rango, 1=Enero...12=Diciembre (default: mes actual)"
    )
    parser.add_argument(
        "--output", default=str(SCRIPT_DIR / "tipo_cambio_sunat.csv"),
        help="Ruta del CSV consolidado de salida (default: junto al script)"
    )
    parser.add_argument(
        "--wait-timeout", type=int, default=25,
        help="Segundos maximos de espera por cada WebDriverWait (default: 25, cubre el reCAPTCHA)"
    )
    parser.add_argument(
        "--delay-seconds", type=float, default=4.0,
        help="Pausa entre cada consulta mensual para no saturar el servidor (default: 4s)"
    )
    parser.add_argument(
        "--headless", action="store_true",
        help="Ejecuta Chrome sin interfaz grafica (puede afectar el puntaje del reCAPTCHA v3)"
    )
    parser.add_argument(
        "--log-file", default=str(SCRIPT_DIR / "tipo_cambio_sunat.log"),
        help="Ruta del archivo de log (default: junto al script)"
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


def build_driver(headless):
    options = Options()
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
    driver = webdriver.Chrome(options=options)
    driver.maximize_window()
    return driver


def generar_periodos(start_year, start_month, end_year, end_month):
    """Genera la lista de (año, mes) entre el inicio y el fin, ambos inclusive."""
    periodos = []
    anio, mes = start_year, start_month
    while (anio, mes) <= (end_year, end_month):
        periodos.append((anio, mes))
        mes += 1
        if mes > 12:
            mes = 1
            anio += 1
    return periodos


def esperar_carga_inicial(driver, wait_timeout):
    # La pagina dispara su propia carga automatica del mes actual 2.5s despues
    # de cargar (setTimeout interno); se espera a que termine antes de interactuar.
    WebDriverWait(driver, wait_timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#holder-calendar .calendar-day"))
    )


def consultar_mes(driver, wait_timeout, anio, mes):
    """Selecciona el periodo (año, mes 1-12) en el formulario y espera los resultados."""
    valor_input = f"{MESES_ABREV[mes - 1]} {anio}"
    driver.execute_script(
        "document.getElementById('fecAsistenciaBusq').value = arguments[0];", valor_input
    )

    buscar_btn = WebDriverWait(driver, wait_timeout).until(
        EC.element_to_be_clickable((By.ID, "btnBuscarAsistencias"))
    )
    buscar_btn.click()

    def _calendario_actualizado(d):
        try:
            year_el = d.find_element(By.CSS_SELECTOR, "#holder-calendar button.js-cal-years")
            month_el = d.find_element(By.CSS_SELECTOR, "#holder-calendar button[data-mode='year']")
            return (
                year_el.text.strip() == str(anio)
                and month_el.text.strip() == MESES_LARGO[mes - 1]
            )
        except (NoSuchElementException, StaleElementReferenceException):
            return False

    WebDriverWait(driver, wait_timeout).until(_calendario_actualizado)


def extraer_mes(driver, anio, mes):
    """Lee del DOM las celdas del mes consultado y devuelve una lista de dicts
    {fecha, compra, venta} solo para los dias que SUNAT publico algun valor."""
    registros = {}
    celdas = driver.find_elements(By.CSS_SELECTOR, "#holder-calendar td.calendar-day.current")

    for celda in celdas:
        dia_texto = celda.find_element(By.CSS_SELECTOR, ".date").text.strip()
        if not dia_texto.isdigit():
            continue
        fecha = date(anio, mes, int(dia_texto))

        eventos = celda.find_elements(By.CSS_SELECTOR, ".event")
        compra = None
        venta = None
        for evento in eventos:
            texto = evento.text.strip()
            partes = texto.split()
            if len(partes) != 2:
                continue
            tipo, monto_str = partes
            try:
                monto = float(monto_str.replace(",", "."))
            except ValueError:
                continue
            if tipo.lower().startswith("compra"):
                compra = monto
            elif tipo.lower().startswith("venta"):
                venta = monto

        if compra is not None or venta is not None:
            registros[fecha] = {"fecha": fecha, "compra": compra, "venta": venta}

    return list(registros.values())


def consolidar_con_arrastre(publicados, fecha_inicio, fecha_fin):
    """Genera un registro para CADA dia calendario del rango, usando el valor
    publicado cuando existe, y arrastrando el ultimo valor conocido cuando no
    (regla oficial de SUNAT para dias sin tipo de cambio publicado)."""
    df_publicado = pd.DataFrame(publicados)
    if not df_publicado.empty:
        df_publicado = df_publicado.drop_duplicates(subset="fecha").set_index("fecha")

    todas_las_fechas = pd.date_range(fecha_inicio, fecha_fin, freq="D").date

    filas = []
    ultimo_compra, ultimo_venta, ultima_fecha_origen = None, None, None

    for fecha in todas_las_fechas:
        if not df_publicado.empty and fecha in df_publicado.index:
            fila = df_publicado.loc[fecha]
            compra, venta = fila["compra"], fila["venta"]
            ultimo_compra, ultimo_venta, ultima_fecha_origen = compra, venta, fecha
            origen = "SUNAT (publicado)"
            fecha_origen = fecha
        elif ultima_fecha_origen is not None:
            compra, venta = ultimo_compra, ultimo_venta
            origen = "Arrastrado (dia sin publicacion)"
            fecha_origen = ultima_fecha_origen
        else:
            # No hay ningun valor previo conocido todavia (inicio del rango).
            compra, venta = None, None
            origen = "Sin dato disponible"
            fecha_origen = None

        filas.append({
            "fecha": fecha.strftime("%d/%m/%Y"),
            "compra": compra,
            "venta": venta,
            "origen": origen,
            "fecha_origen_valor": fecha_origen.strftime("%d/%m/%Y") if fecha_origen else "",
        })

    return pd.DataFrame(filas)


def main():
    args = parse_args()
    setup_logging(args.log_file)

    if (args.start_year, args.start_month) > (args.end_year, args.end_month):
        logging.error("El periodo de inicio es posterior al periodo final. Revisa los argumentos.")
        return 1

    periodos = generar_periodos(args.start_year, args.start_month, args.end_year, args.end_month)
    logging.info("Iniciando scraping de tipo de cambio SUNAT")
    logging.info("Periodos a consultar: %s a %s (%s meses)",
                 periodos[0], periodos[-1], len(periodos))

    publicados = []
    meses_con_error = []

    driver = build_driver(args.headless)
    try:
        driver.get(args.url)
        esperar_carga_inicial(driver, args.wait_timeout)

        for i, (anio, mes) in enumerate(periodos):
            try:
                consultar_mes(driver, args.wait_timeout, anio, mes)
                datos_mes = extraer_mes(driver, anio, mes)
                publicados.extend(datos_mes)
                logging.info("Periodo %s-%02d: %s dias con tipo de cambio publicado.",
                             anio, mes, len(datos_mes))
            except TimeoutException as e:
                logging.warning("Periodo %s-%02d: timeout esperando resultados. Se omite. Detalle: %s",
                                 anio, mes, e)
                meses_con_error.append((anio, mes, f"TimeoutException: {e}"))
            except Exception as e:
                logging.warning("Periodo %s-%02d: error inesperado - %s: %s. Se omite y se continua.",
                                 anio, mes, type(e).__name__, e)
                meses_con_error.append((anio, mes, f"{type(e).__name__}: {e}"))

            # No saturar el servidor con consultas consecutivas.
            if i < len(periodos) - 1:
                time.sleep(args.delay_seconds)
    finally:
        driver.quit()

    fecha_inicio = date(args.start_year, args.start_month, 1)
    fecha_fin = date.today() if (args.end_year, args.end_month) >= (date.today().year, date.today().month) \
        else date(args.end_year, args.end_month, 1)
    # Si el mes final es el mes actual, el rango llega solo hasta hoy (no hasta fin de mes futuro).

    df_final = consolidar_con_arrastre(publicados, fecha_inicio, fecha_fin)
    df_final.to_csv(args.output, index=False, encoding="utf-8-sig")

    total_dias = len(df_final)
    publicados_n = (df_final["origen"] == "SUNAT (publicado)").sum()
    arrastrados_n = (df_final["origen"] == "Arrastrado (dia sin publicacion)").sum()
    sin_dato_n = (df_final["origen"] == "Sin dato disponible").sum()

    logging.info("========== RESUMEN FINAL ==========")
    logging.info("Total de dias procesados: %s", total_dias)
    logging.info("Dias con tipo de cambio publicado por SUNAT: %s", publicados_n)
    logging.info("Dias sin publicacion (arrastrados del dia habil anterior): %s", arrastrados_n)
    logging.info("Dias sin ningun dato disponible: %s", sin_dato_n)
    logging.info("Meses con error durante la consulta: %s", len(meses_con_error))
    for anio, mes, motivo in meses_con_error:
        logging.info("  - %s-%02d -> %s", anio, mes, motivo)
    logging.info("Archivo consolidado guardado en: %s", args.output)
    logging.info("====================================")

    return 0


if __name__ == "__main__":
    sys.exit(main())
