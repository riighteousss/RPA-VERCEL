"""
Robot RPA - Evaluacion 2: Demo TestFire
Amplia el robot de la EP1 (testfire_robot.py) con:
  - comparacion de localizadores (XPath, CSS, id...) y de tecnicas de extraccion (Selenium vs DOM vs API)
  - integracion con un maestro de cuentas en Excel
  - reglas de negocio con reporte de discrepancias y "antes y despues"
  - llamadas HTTP (GET, POST, PUT, PATCH, DELETE) con evidencia
  - datos de prueba autogenerados (RandomUser)

Hay que dejarlo en la misma carpeta que testfire_robot.py.
"""

import os
import json
import time

import matplotlib
matplotlib.use("Agg")  # solo guardamos el grafico en un archivo, no abrimos ventana
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import pandas as pd
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    NoSuchElementException, WebDriverException, TimeoutException,
    UnexpectedAlertPresentException, NoAlertPresentException,
)

try:
    from testfire_robot import (
        iniciar_driver, login, esperar, validar_movimientos,
        logger, OUTPUT_DIR, FECHA, USERNAME, PASSWORD, BASE_URL, MONTO_MAX, MONTO_MIN,
    )
except ImportError as e:
    raise SystemExit(f"Falta testfire_robot.py (el de la EP1) en esta carpeta, o es una version vieja: {e}")

from cliente_http import (
    obtener_beneficiarios, registrar_log_webhook, demo_metodos_http, api_testfire,
    guardar_evidencia, resumen_evidencia,
)
from alertas_vercel import enviar_reporte_vercel
from integracion_excel import leer_maestro, enriquecer_con_maestro, guardar_excel
from reglas_negocio import aplicar_reglas

# ---------------------------------------------------------
# CONFIGURACION
# ---------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAESTRO = os.path.join(BASE_DIR, "maestro_cuentas.xlsx")

CANTIDAD_BENEFICIARIOS = 5
ENVIAR_FEEDBACK = False   # solo se llena el formulario, no se envia (el sitio es compartido)

ALERTAS = []   # alerts de JavaScript que abrio el sitio (se anotan para el informe)

COLUMNAS_ANTES = ["id_transaccion", "fecha", "cuenta_id", "accion", "monto", "descripcion"]

# lee todas las filas de la tabla en una sola llamada usando el DOM
JS_FILAS = "return Array.from(arguments[0].rows).map(f => Array.from(f.cells).map(c => c.innerText.trim()));"

# distintas formas de ubicar la misma tabla (nombre, tipo, localizador, comentario)
LOCALIZADORES = [
    ("ID exacto", By.ID, "_ctl0__ctl0_Content_Main_MyTransactions",
     "el id lo genera el framework, puede cambiar"),
    ("XPath con contains(@id)", By.XPATH, "//table[contains(@id,'MyTransactions')]",
     "aguanta cambios en el prefijo del id"),
    ("XPath por texto de columna", By.XPATH, "//td[normalize-space()='Transaction ID']/ancestor::table[1]",
     "depende del contenido, no del id"),
    ("CSS selector", By.CSS_SELECTOR, "table[id*='MyTransactions']",
     "igual que contains pero mas corto"),
    ("XPath absoluto", By.XPATH, "/html/body/table[2]/tbody/tr/td[2]/div/form/table[2]",
     "se rompe si cambia el layout de la pagina"),
    ("Tag name", By.TAG_NAME, "table",
     "devuelve la primera tabla de la pagina, no la que queremos"),
]


# ---------------------------------------------------------
# ALERTAS DE JAVASCRIPT (el sitio a veces abre un alert y Selenium se cae)
# ---------------------------------------------------------
def anotar_alerta(driver, paso, error):
    """Cierra el alert si sigue abierto y deja anotado lo que decia."""
    texto = getattr(error, "alert_text", None)
    try:
        alerta = driver.switch_to.alert
        texto = texto or alerta.text
        alerta.accept()
    except NoAlertPresentException:
        pass  # el navegador ya lo cerro solo
    ALERTAS.append({"paso": paso, "texto": texto})
    logger.warning(f"[{paso}] El sitio abrio un alert de JavaScript: '{texto}'. Se cerro y se sigue")


def esperar_cerrando_alertas(driver, by, valor, paso, timeout=20):
    """Igual que esperar(), pero si aparece un alert lo cierra y sigue buscando."""
    for _ in range(5):
        try:
            return esperar(driver, by, valor, timeout)
        except UnexpectedAlertPresentException as e:
            anotar_alerta(driver, paso, e)
    raise TimeoutException(f"Siguen apareciendo alerts buscando {by}={valor}")


def ir_a(driver, url, paso):
    try:
        driver.get(url)
    except UnexpectedAlertPresentException as e:
        anotar_alerta(driver, paso, e)


def cargar_transferencia(driver, monto="10"):
    """Llena el monto en Transfer Funds (como en la EP1) pero aguantando los alerts del sitio."""
    try:
        enlace = esperar_cerrando_alertas(driver, By.LINK_TEXT, "Transfer Funds", "transfer")
        try:
            enlace.click()
        except UnexpectedAlertPresentException as e:
            anotar_alerta(driver, "transfer (click)", e)

        campo = esperar_cerrando_alertas(driver, By.NAME, "transferAmount", "transfer")
        campo.clear()
        campo.send_keys(monto)
        logger.info("Formulario de transferencia completado")
        return True
    except (TimeoutException, NoSuchElementException, UnexpectedAlertPresentException) as e:
        logger.warning(f"No se pudo llenar el formulario de transferencia: {e}")
        return False


# ---------------------------------------------------------
# PARTE WEB (Selenium)
# ---------------------------------------------------------
def extraer_tabla(driver):
    """Entra a View Recent Transactions y lee la tabla con 2 tecnicas para compararlas."""
    esperar(driver, By.LINK_TEXT, "View Recent Transactions").click()
    tabla = esperar(driver, By.XPATH, "//table[contains(@id,'MyTransactions')]")

    # tecnica 1: Selenium fila por fila (como en la EP1)
    inicio = time.time()
    filas_selenium = []
    for tr in tabla.find_elements(By.TAG_NAME, "tr"):
        filas_selenium.append([td.text.strip() for td in tr.find_elements(By.TAG_NAME, "td")])
    ms_selenium = round((time.time() - inicio) * 1000)

    # tecnica 2: DOM con JavaScript, todo en una sola llamada
    filas_dom, ms_dom = None, None
    try:
        inicio = time.time()
        filas_dom = driver.execute_script(JS_FILAS, tabla)
        ms_dom = round((time.time() - inicio) * 1000)
        filas_dom = [[c.strip() for c in f] for f in filas_dom]
    except WebDriverException as e:
        logger.warning(f"No se pudo leer la tabla con JavaScript, se usa Selenium: {e}")

    coinciden = None
    if filas_dom is not None:
        coinciden = filas_dom == filas_selenium
        logger.info(f"Selenium: {ms_selenium} ms | DOM: {ms_dom} ms | mismos datos: {coinciden}")

    filas = filas_dom if filas_dom is not None else filas_selenium
    return {"filas": filas, "ms_selenium": ms_selenium, "ms_dom": ms_dom, "coinciden": coinciden}


def filas_a_movimientos(filas):
    """Pasa las filas de texto a diccionarios. Salta el encabezado y las filas cortas."""
    movimientos = []
    for celdas in filas:
        if len(celdas) < 5:
            continue
        if not celdas[0].strip().isdigit():
            continue  # es el encabezado (dice "Transaction ID")
        id_tx, fecha, cuenta, accion, monto = [c.strip() for c in celdas[:5]]
        movimientos.append({
            "id_transaccion": id_tx,
            "fecha": fecha,
            "cuenta_id": cuenta,
            "accion": accion,
            "monto": monto,
            "descripcion": f"{accion} cuenta {cuenta}",
        })
    return movimientos


def guardar_evidencia_dom(driver):
    ruta_png = os.path.join(OUTPUT_DIR, f"tabla_transacciones_{FECHA}.png")
    ruta_html = os.path.join(OUTPUT_DIR, f"pagina_transacciones_{FECHA}.html")
    driver.save_screenshot(ruta_png)
    with open(ruta_html, "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    logger.info(f"Evidencia del DOM guardada: {ruta_png} y {ruta_html}")


def comparar_localizadores(driver):
    """Busca la misma tabla con varios tipos de localizador y mide cual la encuentra bien."""
    ref = driver.find_elements(LOCALIZADORES[1][1], LOCALIZADORES[1][2])
    filas_ref = len(ref[0].find_elements(By.TAG_NAME, "tr")) if ref else None

    resultados = []
    for nombre, tipo, localizador, comentario in LOCALIZADORES:
        inicio = time.time()
        try:
            encontrados = driver.find_elements(tipo, localizador)
        except WebDriverException:
            encontrados = []  # localizador mal formado o que no existe
        ms = round((time.time() - inicio) * 1000, 1)

        n_filas = len(encontrados[0].find_elements(By.TAG_NAME, "tr")) if encontrados else 0
        correcto = len(encontrados) == 1 and filas_ref is not None and n_filas == filas_ref

        resultados.append({
            "estrategia": nombre, "tipo": tipo, "localizador": localizador,
            "elementos_encontrados": len(encontrados), "filas_del_primero": n_filas,
            "correcto": correcto, "ms": ms, "comentario": comentario,
        })
        logger.info(f"Localizador '{nombre}': {len(encontrados)} encontrado(s), correcto={correcto}")

    return pd.DataFrame(resultados)


def llenar_feedback(driver, persona):
    """Llena el formulario de feedback con datos generados (no lo envia salvo que se active)."""
    try:
        ir_a(driver, BASE_URL + "feedback.jsp", "feedback")
        esperar_cerrando_alertas(driver, By.NAME, "name", "feedback", timeout=8).send_keys(persona["nombre"])
        esperar_cerrando_alertas(driver, By.NAME, "email_addr", "feedback", timeout=8).send_keys(persona["email"])
        esperar_cerrando_alertas(driver, By.NAME, "subject", "feedback", timeout=8).send_keys("Prueba del robot RPA")
        esperar_cerrando_alertas(driver, By.NAME, "comments", "feedback", timeout=8).send_keys(
            f"Mensaje de prueba generado automaticamente ({persona['pais']})")
        driver.save_screenshot(os.path.join(OUTPUT_DIR, f"feedback_{FECHA}.png"))
        if ENVIAR_FEEDBACK:
            driver.find_element(By.NAME, "submit").click()
        logger.info(f"Formulario de feedback completado con {persona['nombre']}")
        return True
    except (TimeoutException, NoSuchElementException) as e:
        logger.warning(f"No se pudo completar el formulario de feedback: {e}")
        return False


def fase_web(beneficiarios):
    driver = iniciar_driver()
    try:
        if not login(driver):
            return None

        info = extraer_tabla(driver)
        guardar_evidencia_dom(driver)
        localizadores = comparar_localizadores(driver)
        transfer_ok = cargar_transferencia(driver)
        feedback_ok = llenar_feedback(driver, beneficiarios[0])

        return {
            "movimientos": filas_a_movimientos(info["filas"]),
            "tecnicas": info,
            "localizadores": localizadores,
            "transfer_ok": transfer_ok,
            "feedback_ok": feedback_ok,
            "alertas": list(ALERTAS),
        }
    except Exception:
        logger.exception("Error inesperado en la parte web")
        return None
    finally:
        driver.quit()
        logger.info("Navegador cerrado")


# ---------------------------------------------------------
# GRAFICO DE DISPERSION
# ---------------------------------------------------------
def graficar_dispersion(df):
    # ordenamos por fecha: casi todo cae en pocos dias, asi que usamos el orden como eje X
    datos = df.sort_values(["fecha", "id_transaccion"]).reset_index(drop=True)
    colores = ["green" if e == "OK" else "red" for e in datos["estado"]]

    plt.figure(figsize=(10, 5.5))
    plt.scatter(range(len(datos)), datos["monto_num"], c=colores, s=30, alpha=0.8)
    plt.scatter([], [], c="green", label="OK")
    plt.scatter([], [], c="red", label="Revisar")
    plt.yscale("symlog", linthresh=1000)   # hay montos de 1000 y de 1 billon en la misma tabla
    plt.yticks([-1e12, -1e9, -1e6, -1e3, 0, 1e3, 1e6, 1e9, 1e12, 1e15])
    plt.gca().yaxis.set_major_formatter(
        FuncFormatter(lambda v, _: f"{v:,.0f}" if abs(v) < 1e6 else f"{v:.0e}"))
    plt.axhline(MONTO_MAX, color="gray", linestyle="--", linewidth=1)
    plt.axhline(-MONTO_MAX, color="gray", linestyle="--", linewidth=1)
    plt.title("Movimientos ordenados por fecha y su monto (escala symlog)")
    plt.xlabel("Movimiento # (del mas antiguo al mas reciente)")
    plt.ylabel("Monto")
    plt.legend()
    plt.tight_layout()

    ruta = os.path.join(OUTPUT_DIR, f"grafico_dispersion_{FECHA}.png")
    plt.savefig(ruta)
    plt.close()
    logger.info(f"Grafico guardado en {ruta}")
    return ruta


# ---------------------------------------------------------
# PARTE DE DATOS (Excel + reglas + HTTP + reportes)
# ---------------------------------------------------------
def fase_datos(web, beneficiarios, t0):
    movimientos = web["movimientos"]
    df_antes = pd.DataFrame(movimientos, columns=COLUMNAS_ANTES)  # copia cruda, antes de tocar nada

    # 1) validacion de formato (la de la EP1)
    validos = validar_movimientos([dict(m) for m in movimientos])
    if not validos:
        logger.warning("No quedaron movimientos validos, se termina aca")
        return None
    ids_validos = {m["id_transaccion"] for m in validos}
    rechazados = df_antes[~df_antes["id_transaccion"].isin(ids_validos)]

    # 2) cruce con el maestro de cuentas y reglas de negocio
    maestro = leer_maestro(MAESTRO, MONTO_MAX)
    df = enriquecer_con_maestro(pd.DataFrame(validos), maestro)
    df, conteo = aplicar_reglas(df, MONTO_MAX, MONTO_MIN)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")

    df_despues = df[["id_transaccion", "fecha", "cuenta_id", "accion", "monto_num", "titular",
                     "tipo_cuenta", "estado_cuenta", "limite_monto", "en_maestro",
                     "errores_negocio", "sugerencia", "estado"]]
    discrepancias = df_despues[df_despues["estado"] == "REVISAR"]
    cuentas_fuera = (df[~df["en_maestro"]].groupby("cuenta_id").size()
                     .reset_index(name="movimientos"))

    # 3) llamadas HTTP
    api = api_testfire(USERNAME, PASSWORD)
    metodos = demo_metodos_http()

    tec = web["tecnicas"]
    resumen = {
        "movimientos_extraidos": len(df_antes),
        "rechazados_por_formato": len(rechazados),
        "validos": len(df),
        "ok": int((df["estado"] == "OK").sum()),
        "para_revisar": int((df["estado"] == "REVISAR").sum()),
        "cuentas_distintas": int(df["cuenta_id"].nunique()),
        "cuentas_fuera_del_maestro": len(cuentas_fuera),
        "reglas_disparadas": conteo,
        "ms_extraccion_selenium": tec["ms_selenium"],
        "ms_extraccion_dom": tec["ms_dom"],
        "api_login_status": api["login_status"],
        "api_sin_token_status": api["sin_token_status"],
        "api_transacciones_status": api["tx_status"],
        "beneficiarios_generados": len(beneficiarios),
        "fuente_beneficiarios": beneficiarios[0]["fuente"],
        "formulario_transferencia": web["transfer_ok"],
        "formulario_feedback": web["feedback_ok"],
        "alertas_js_detectadas": web["alertas"],
    }
    resumen["webhook_status"] = registrar_log_webhook(resumen)   # POST con el log de la ejecucion
    resumen["duracion_seg"] = round(time.time() - t0, 1)

    # 4) reportes
    df_resumen = pd.DataFrame({
        "indicador": list(resumen.keys()),
        "valor": [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in resumen.values()],
    })
    tecnicas = pd.DataFrame([
        {"tecnica": "Selenium find_elements fila por fila (EP1)", "filas_leidas": len(df_antes),
         "tiempo_ms": tec["ms_selenium"], "observacion": "una llamada al navegador por cada celda"},
        {"tecnica": "DOM con JavaScript (rows/cells)", "filas_leidas": len(df_antes),
         "tiempo_ms": tec["ms_dom"], "observacion": "una sola llamada para toda la tabla"},
        {"tecnica": "API REST de TestFire (HTTP)", "filas_leidas": api["n_tx_api"],
         "tiempo_ms": None, "observacion": "solo trae las ultimas 10 transacciones de una cuenta"},
    ])

    ruta_reporte = guardar_excel({
        "Resumen": df_resumen,
        "Antes": df_antes,
        "Despues": df_despues,
        "Maestro": maestro,
        "Beneficiarios": pd.DataFrame(beneficiarios),
        "Alertas_JS": pd.DataFrame(web["alertas"], columns=["paso", "texto"]),
        "Localizadores": web["localizadores"],
        "Tecnicas": tecnicas,
        "HTTP": pd.DataFrame(resumen_evidencia()),
        "Metodos_HTTP": pd.DataFrame(metodos),
    }, os.path.join(OUTPUT_DIR, f"Reporte_Movimientos_TestFire_{FECHA}.xlsx"))

    ruta_validacion = guardar_excel({
        "Discrepancias": discrepancias,
        "Cuentas_fuera_maestro": cuentas_fuera,
        "Rechazados_formato": rechazados,
    }, os.path.join(OUTPUT_DIR, f"Validacion_Movimientos_{FECHA}.xlsx"))

    ruta_grafico = graficar_dispersion(df)
    ruta_http = os.path.join(OUTPUT_DIR, f"evidencia_http_{FECHA}.json")
    guardar_evidencia(ruta_http)

    ruta_alerta = os.path.join(OUTPUT_DIR, f"Reporte_Alerta_Vercel_{FECHA}.csv")
    try:
        alerta = enviar_reporte_vercel(df_despues, ruta_alerta)
        if alerta["estado"] == "desactivado":
            logger.info("Publicación en Vercel desactivada; se mantienen los reportes locales")
        else:
            logger.info(f"Reporte CSV generado en Vercel y guardado en {alerta['ruta_csv']}")
    except Exception:
        logger.exception("No se pudo generar el CSV en Vercel; los informes locales se conservaron")

    logger.info("=== RESUMEN ===")
    for clave, valor in resumen.items():
        logger.info(f"   {clave}: {valor}")
    logger.info(f"Archivos generados en {OUTPUT_DIR}:")
    for ruta in (ruta_reporte, ruta_validacion, ruta_grafico, ruta_http):
        logger.info(f"   {os.path.basename(ruta)}")
    return resumen


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
def main():
    t0 = time.time()
    logger.info("=== Robot EP2 TestFire ===")

    beneficiarios = obtener_beneficiarios(CANTIDAD_BENEFICIARIOS)   # GET a RandomUser

    web = fase_web(beneficiarios)
    if web is None:
        logger.error("La parte web fallo, no se puede seguir")
        return

    try:
        fase_datos(web, beneficiarios, t0)
    except Exception:
        logger.exception("Error procesando los datos")


if __name__ == "__main__":
    main()
