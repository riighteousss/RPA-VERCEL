"""
Robot RPA - Caso 2: Demo TestFire
Login, extracción de movimientos, validación de datos, detección de
errores de negocio y gráfico de dispersión de los montos extraídos.
"""

import os
import re
import time
import logging
from datetime import datetime

import pandas as pd
import matplotlib.pyplot as plt
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, WebDriverException, TimeoutException


# CONFIGURACION

BASE_URL = "https://demo.testfire.net/"
LOGIN_URL = BASE_URL + "login.jsp"   # el login no está en el home, está acá

USERNAME = os.environ.get("TESTFIRE_USER", "jsmith")
PASSWORD = os.environ.get("TESTFIRE_PASS", "demo1234")  # ojo, es con el 4 al final

MAX_LOGIN_ATTEMPTS = 3
WAIT_TIMEOUT = 20        # segundos maximos esperando un elemento
INTERVALO = 0.5          # cada cuanto reintenta buscar el elemento

MONTO_MAX = 5000         # sobre esto se considera raro
MONTO_MIN = 0.01         # un monto en 0 tampoco es normal

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
FECHA = datetime.now().strftime("%Y%m%d_%H%M%S")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(os.path.join(OUTPUT_DIR, f"log_{FECHA}.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)



# FUNCIONES DE APOYO

def esperar(driver, by, valor, timeout=WAIT_TIMEOUT):
    """Busca un elemento reintentando cada 0.5s hasta encontrarlo o cansarse."""
    tiempo = 0
    while tiempo < timeout:
        try:
            return driver.find_element(by, valor)
        except NoSuchElementException:
            time.sleep(INTERVALO)
            tiempo += INTERVALO
    raise TimeoutException(f"No aparecio el elemento {by}={valor}")


def iniciar_driver():
    opciones = webdriver.ChromeOptions()
    opciones.set_capability("acceptInsecureCerts", True)  # el sitio tiene certificado viejo

    # Equivalente a dom.webdriver.enabled = False en Firefox
    opciones.add_argument("--disable-blink-features=AutomationControlled")

    # Opciones clave para que Chrome funcione de forma estable en Linux
    opciones.add_argument("--no-sandbox")
    opciones.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=opciones)
    driver.maximize_window()
    return driver


# ACCION 1: LOGIN (navegar + cargar formulario)

def login(driver):
    intentos = 0
    logueado = False

    while intentos < MAX_LOGIN_ATTEMPTS and not logueado:
        intentos += 1
        logger.info(f"Intento de login #{intentos}")
        driver.get(LOGIN_URL)

        try:
            campo_user = esperar(driver, By.NAME, "uid")
            campo_pass = driver.find_element(By.NAME, "passw")

            campo_user.clear()
            campo_user.send_keys(USERNAME)
            campo_pass.clear()
            campo_pass.send_keys(PASSWORD)
            driver.find_element(By.NAME, "btnSubmit").click()
            time.sleep(2)  # dar tiempo a que la pagina cambie tras enviar el form

            # si el login sirvio, esto aparece en algun lado de la pagina
            if "SIGN OFF" in driver.page_source.upper() or "Account Summary" in driver.page_source:
                logueado = True
                logger.info("Login OK")
            else:
                logger.warning("Login no confirmado, reintentando...")
                time.sleep(2)

        except TimeoutException:
            logger.warning("La pagina no cargo a tiempo, reintentando...")
            time.sleep(2)

    if not logueado:
        logger.error("No se pudo iniciar sesion")
    return logueado


# ACCION 2: EXTRAER MOVIMIENTOS (navegar + extraer)

def extraer_movimientos(driver):
    movimientos = []
    try:
        esperar(driver, By.LINK_TEXT, "View Recent Transactions").click()

        # guardamos el HTML SIEMPRE, para poder revisar la estructura real
        ruta_html = os.path.join(OUTPUT_DIR, f"pagina_transacciones_{FECHA}.html")
        with open(ruta_html, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        logger.info(f"HTML de la pagina de transacciones guardado en {ruta_html}")

        # la tabla real se llama "...MyTransactions" y las columnas son:
        # Transaction ID | Transaction Time | Account ID | Action | Amount
        tabla = esperar(driver, By.XPATH, "//table[contains(@id,'MyTransactions')]")
        filas = tabla.find_elements(By.TAG_NAME, "tr")
        logger.info(f"Filas encontradas en la tabla: {len(filas)}")

        for fila in filas:
            try:
                celdas = fila.find_elements(By.TAG_NAME, "td")
                if len(celdas) < 5:
                    continue  # fila vacia o de paginacion, se salta

                id_transaccion = celdas[0].text.strip()
                if not id_transaccion.isdigit():
                    continue  # es la fila del encabezado (dice "Transaction ID"), se salta

                fecha = celdas[1].text.strip()
                cuenta = celdas[2].text.strip()
                accion = celdas[3].text.strip()
                monto = celdas[4].text.strip()

                movimientos.append({
                    "fecha": fecha,
                    "descripcion": f"{accion} cuenta {cuenta}",
                    "monto": monto,
                })
            except Exception as e:
                logger.warning(f"Fila con problema, se omite: {e}")

    except (TimeoutException, NoSuchElementException) as e:
        logger.error(f"No se pudo extraer la tabla: {e}")
        ruta_html = os.path.join(OUTPUT_DIR, f"error_extraccion_{FECHA}.html")
        with open(ruta_html, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        logger.info(f"HTML de esa pagina guardado en {ruta_html} para revisar")

    logger.info(f"Movimientos extraidos: {len(movimientos)}")
    return movimientos



# ACCION 3: TRANSFER FUNDS (cargar formulario)

def cargar_formulario_transferencia(driver, monto="10"):
    try:
        esperar(driver, By.LINK_TEXT, "Transfer Funds").click()
        campo = esperar(driver, By.NAME, "transferAmount")
        campo.clear()
        campo.send_keys(monto)
        logger.info("Formulario de transferencia completado")
        return True
    except (TimeoutException, NoSuchElementException) as e:
        logger.warning(f"No se pudo llenar el formulario de transferencia: {e}")
        return False



# VALIDACION DE DATOS (antes de seguir con el resto)

def validar_movimientos(movimientos):
    # acepta dd/mm/aaaa o aaaa-mm-dd, con hora opcional al final
    patron_fecha = r"^(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})(\s\d{2}:\d{2})?$"
    validos = []

    for mov in movimientos:
        fecha_ok = bool(re.match(patron_fecha, mov["fecha"]))

        monto_txt = mov["monto"].replace("$", "").replace(",", "").replace("(", "-").replace(")", "")
        try:
            monto_num = float(monto_txt)
            monto_ok = True
        except ValueError:
            monto_num = None
            monto_ok = False

        desc_ok = len(mov["descripcion"]) > 0

        if fecha_ok and monto_ok and desc_ok:
            mov["monto_num"] = monto_num
            validos.append(mov)
        else:
            logger.warning(f"Movimiento con datos invalidos, se descarta: {mov}")

    logger.info(f"Movimientos validos: {len(validos)} de {len(movimientos)}")
    return validos



# ERRORES DE NEGOCIO (sobre datos ya validados)

def detectar_errores_negocio(df):
    hoy = datetime.now().date()
    estados = []

    claves = df["fecha"] + df["descripcion"] + df["monto"]

    for i, fila in df.iterrows():
        problema = None

        if abs(fila["monto_num"]) > MONTO_MAX or abs(fila["monto_num"]) < MONTO_MIN:
            problema = "monto fuera de rango"

        fecha_dt = pd.to_datetime(fila["fecha"], errors="coerce")
        if pd.notnull(fecha_dt) and fecha_dt.date() > hoy:
            problema = "fecha futura"

        clave = fila["fecha"] + fila["descripcion"] + fila["monto"]
        if (claves == clave).sum() > 1:
            problema = "posible duplicado"

        estados.append(problema if problema else "OK")

    df["estado"] = estados
    revisar = (df["estado"] != "OK").sum()
    logger.info(f"Movimientos para revisar (errores de negocio): {revisar}")
    return df



# EXPORTAR EXCEL

def exportar_excel(df):
    ruta = os.path.join(OUTPUT_DIR, f"movimientos_{FECHA}.xlsx")
    df.to_excel(ruta, index=False)
    logger.info(f"Excel guardado en {ruta}")
    return ruta


# GRAFICO DE DISPERSION

def graficar_dispersion(df):
    colores = df["estado"].apply(lambda e: "red" if e != "OK" else "green")

    plt.figure(figsize=(9, 5))
    plt.scatter(range(len(df)), df["monto_num"], c=colores)
    plt.axhline(MONTO_MAX, color="gray", linestyle="--", linewidth=1)
    plt.axhline(-MONTO_MAX, color="gray", linestyle="--", linewidth=1)
    plt.title("Movimientos extraidos (verde = OK, rojo = revisar)")
    plt.xlabel("Movimiento #")
    plt.ylabel("Monto")

    ruta = os.path.join(OUTPUT_DIR, f"grafico_dispersion_{FECHA}.png")
    plt.savefig(ruta)
    plt.close()
    logger.info(f"Grafico guardado en {ruta}")
    return ruta



# MAIN

def main():
    driver = iniciar_driver()
    try:
        if not login(driver):
            return

        movimientos = extraer_movimientos(driver)
        cargar_formulario_transferencia(driver)

        movimientos_validos = validar_movimientos(movimientos)
        if not movimientos_validos:
            logger.warning("No quedaron movimientos validos, se termina aca.")
            return

        df = pd.DataFrame(movimientos_validos)
        df = detectar_errores_negocio(df)

        exportar_excel(df)
        graficar_dispersion(df)

    except Exception as e:
        logger.error(f"Error inesperado: {e}")

    finally:
        driver.quit()
        logger.info("Listo, navegador cerrado")


if __name__ == "__main__":
    main()