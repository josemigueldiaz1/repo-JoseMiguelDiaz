"""
RPA - Registro automatico de personal en PeopleSync 

"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

try:
    SCRIPT_DIR = Path(__file__).resolve().parent
except NameError:
    # __file__ no existe al pegar el codigo en una celda de Jupyter;
    # se usa el directorio actual como respaldo solo para pruebas interactivas.
    SCRIPT_DIR = Path.cwd()

# El proyecto separa el script de sus carpetas de datos: input/, logs/ y output/
# viven junto a script/, no dentro de ella.
PROJECT_DIR = SCRIPT_DIR.parent


class RegistroInvalidoError(Exception):
    """El formulario respondio con un toast de error (rechazo por validacion)."""


def parse_args():
    parser = argparse.ArgumentParser(description="RPA de registro de personal en PeopleSync")
    parser.add_argument(
        "--excel", default=str(PROJECT_DIR / "input" / "Ingreso_Personal_Agosto.xlsx"),
        help="Ruta al archivo Excel con los datos a registrar (default: carpeta input/ del proyecto)"
    )
    parser.add_argument(
        "--url", default="https://the-paul2002.github.io/Proyecto-IA-/Homework1/",
        help="URL del formulario a automatizar"
    )
    parser.add_argument(
        "--wait-timeout", type=int, default=10,
        help="Segundos maximos de espera para cada WebDriverWait (default: 10)"
    )
    parser.add_argument(
        "--headless", action="store_true",
        help="Ejecuta Chrome sin interfaz grafica (necesario para Task Scheduler sin sesion interactiva)"
    )
    parser.add_argument(
        "--log-file", default=str(PROJECT_DIR / "logs" / "rpa_registro_personal.log"),
        help="Ruta del archivo de log (default: carpeta logs/ del proyecto)"
    )
    parser.add_argument(
        "--report-omitidos", default=str(PROJECT_DIR / "output" / "registros_omitidos.csv"),
        help="Ruta del CSV donde se guardan las filas que no se pudieron registrar (default: carpeta output/ del proyecto)"
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


def fill_text_field(driver, wait_timeout, field_id, value):
    field = WebDriverWait(driver, wait_timeout).until(
        EC.element_to_be_clickable((By.ID, field_id))
    )
    field.clear()
    field.send_keys(str(value))


def fill_date_field(driver, wait_timeout, field_id, timestamp):
    date_str = timestamp.strftime("%Y-%m-%d")
    field = WebDriverWait(driver, wait_timeout).until(
        EC.presence_of_element_located((By.ID, field_id))
    )
    # Los inputs type="date" son poco confiables con send_keys por el formato/locale,
    # por eso se setea el value directamente via JS (siempre acepta formato ISO YYYY-MM-DD).
    driver.execute_script("arguments[0].value = arguments[1];", field, date_str)
    driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", field)


def select_dropdown(driver, wait_timeout, field_id, visible_text):
    dropdown = WebDriverWait(driver, wait_timeout).until(
        EC.element_to_be_clickable((By.ID, field_id))
    )
    Select(dropdown).select_by_visible_text(visible_text)


def select_modalidad(driver, wait_timeout, value):
    # Los <input type="radio"> estan ocultos con opacity/width/height 0 (estilo "pill"),
    # asi que se hace clic en el <span> visible dentro del mismo <label>.
    option = WebDriverWait(driver, wait_timeout).until(
        EC.element_to_be_clickable(
            (By.XPATH, f"//input[@name='modalidad' and @value='{value}']/following-sibling::span")
        )
    )
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", option)
    try:
        option.click()
    except Exception:
        driver.execute_script("arguments[0].click();", option)


def submit_form(driver, wait_timeout):
    submit_btn = WebDriverWait(driver, wait_timeout).until(
        EC.element_to_be_clickable((By.ID, "btn-registrar"))
    )
    submit_btn.click()

    alert = WebDriverWait(driver, wait_timeout).until(
        EC.presence_of_element_located((By.ID, "alert"))
    )
    # Espera a que el toast aparezca para poder leer si fue de exito o de error.
    WebDriverWait(driver, wait_timeout).until(
        lambda d: "show" in alert.get_attribute("class")
    )
    alert_class = alert.get_attribute("class")
    alert_title = driver.find_element(By.ID, "alert-title").text
    alert_msg = driver.find_element(By.ID, "alert-msg").text

    # Espera a que el toast desaparezca antes de seguir, para no tapar
    # los campos del siguiente registro (evita ElementClickInterceptedException).
    WebDriverWait(driver, wait_timeout).until(
        lambda d: "show" not in d.find_element(By.ID, "alert").get_attribute("class")
    )

    if "alert-error" in alert_class:
        # El formulario rechazo el registro (validacion del lado del cliente):
        # no se agrego a la tabla aunque el click se haya ejecutado sin errores de Selenium.
        raise RegistroInvalidoError(f"{alert_title}: {alert_msg}")

    return alert_title, alert_msg


def procesar_fila(driver, wait_timeout, row):
    fill_text_field(driver, wait_timeout, "nombres", row["apellidos_nombres"])
    fill_text_field(driver, wait_timeout, "dni", str(int(row["dni"])).zfill(8))
    fill_date_field(driver, wait_timeout, "fecha_nacimiento", row["fecha_nacimiento"])
    select_dropdown(driver, wait_timeout, "genero", row["genero"])
    fill_text_field(driver, wait_timeout, "telefono", str(int(row["telefono"])).zfill(9))
    fill_text_field(driver, wait_timeout, "correo", row["correo"])
    select_dropdown(driver, wait_timeout, "area", row["area"])
    select_dropdown(driver, wait_timeout, "puesto", row["puesto"])
    select_dropdown(driver, wait_timeout, "contrato", row["contrato"])
    select_dropdown(driver, wait_timeout, "sede", row["sede"])
    fill_date_field(driver, wait_timeout, "fecha_ingreso", row["fecha_ingreso"])
    select_modalidad(driver, wait_timeout, row["modalidad"])
    # Verificacion real de que el registro se agrego (no solo que se hizo click):
    # submit_form lanza RegistroInvalidoError si el toast fue de error.
    submit_form(driver, wait_timeout)


def main():
    args = parse_args()
    setup_logging(args.log_file)

    logging.info("Iniciando RPA de registro de personal")
    logging.info("Excel: %s", args.excel)
    logging.info("URL: %s", args.url)

    if not Path(args.excel).exists():
        logging.error("No se encontro el archivo Excel: %s", args.excel)
        return 1

    df = pd.read_excel(args.excel)
    omitidos = []
    exitosos = 0

    driver = build_driver(args.headless)
    try:
        # Una sola carga de pagina para todo el proceso; nunca se recarga manualmente.
        driver.get(args.url)

        for index, row in df.iterrows():
            identificador = f"DNI {row.get('dni', 'N/D')} - {row.get('apellidos_nombres', 'N/D')}"
            try:
                procesar_fila(driver, args.wait_timeout, row)
                exitosos += 1
                logging.info("Fila %s (%s): registrado y verificado correctamente.", index, identificador)

            except NoSuchElementException as e:
                motivo = f"Opcion no encontrada en un dropdown: {e}"
                logging.warning("Fila %s (%s): %s", index, identificador, motivo)
                omitidos.append({**row.to_dict(), "fila": index, "identificador": identificador, "motivo": motivo})

            except TimeoutException as e:
                motivo = f"Timeout esperando un elemento: {e}"
                logging.warning("Fila %s (%s): %s", index, identificador, motivo)
                omitidos.append({**row.to_dict(), "fila": index, "identificador": identificador, "motivo": motivo})

            except RegistroInvalidoError as e:
                motivo = f"Rechazado por el formulario: {e}"
                logging.warning("Fila %s (%s): %s", index, identificador, motivo)
                omitidos.append({**row.to_dict(), "fila": index, "identificador": identificador, "motivo": motivo})

            except Exception as e:
                # Cualquier otro error (dato inconsistente, conversion fallida, etc.)
                # no debe detener el proceso: se registra y se sigue con la siguiente fila.
                motivo = f"{type(e).__name__}: {e}"
                logging.warning("Fila %s (%s): error inesperado - %s", index, identificador, motivo)
                omitidos.append({**row.to_dict(), "fila": index, "identificador": identificador, "motivo": motivo})
    finally:
        driver.quit()

    if omitidos:
        pd.DataFrame(omitidos).to_csv(args.report_omitidos, index=False, encoding="utf-8-sig")

    # ---------------- Resumen final ----------------
    logging.info("========== RESUMEN FINAL ==========")
    logging.info("Total de registros procesados: %s", len(df))
    logging.info("Registros cargados exitosamente: %s", exitosos)
    logging.info("Registros no cargados: %s", len(omitidos))
    if omitidos:
        logging.info("Detalle de registros no cargados:")
        for o in omitidos:
            logging.info("  - %s -> %s", o["identificador"], o["motivo"])
        logging.info("Reporte completo guardado en: %s", args.report_omitidos)
    logging.info("====================================")

    return 0


if __name__ == "__main__":
    sys.exit(main())
