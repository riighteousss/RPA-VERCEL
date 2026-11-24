"""Evaluación 3. Ejecutar con --demo para probar sin acceder a TestFire ni enviar."""
import argparse
from contextlib import closing
import base64
from datetime import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import socket
import sqlite3
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

import pandas as pd
from openpyxl import load_workbook

from api.alerta import generar_csv
from integracion_excel import enriquecer_con_maestro, guardar_excel, leer_maestro
from reglas_negocio import aplicar_reglas

BASE = Path(__file__).resolve().parent
OUT = BASE / "output"
API = "https://randomuser.me/api/1.4/?results=3&seed=rpa-ep3&inc=nat,location"
PANEL_URL = "https://ev2-vercel-alertas.vercel.app/"
LOG = logging.getLogger("ep3")
REVIEW_COLUMNS = ["id_transaccion", "fecha", "accion", "monto_num", "errores_negocio", "estado"]


def leer_testfire(ruta):
    from robot_ep2 import extraer_tabla, filas_a_movimientos
    from testfire_robot import iniciar_driver, login

    driver = iniciar_driver()
    try:
        if not login(driver):
            raise RuntimeError("Sesión TestFire no confirmada")
        LOG.info("LOGIN confirmado")
        driver.save_screenshot(str(ruta / "login.png"))
        tabla = extraer_tabla(driver)
        driver.save_screenshot(str(ruta / "movimientos.png"))
        return filas_a_movimientos(tabla["filas"])
    finally:
        driver.quit()


def referencia_publica(ruta):
    with urlopen(API, timeout=10) as respuesta:
        codigo = respuesta.status
        cuerpo = json.loads(respuesta.read(250_000))
    filas = cuerpo.get("results") if isinstance(cuerpo, dict) else None
    if not isinstance(filas, list) or len(filas) != 3:
        raise ValueError("RandomUser no devolvió las tres referencias esperadas")

    referencias = []
    for fila in filas:
        if not isinstance(fila, dict) or not isinstance(fila.get("location"), dict):
            raise ValueError("Formato de referencia inesperado")
        pais, codigo_pais = fila["location"].get("country"), fila.get("nat")
        if not isinstance(pais, str) or not pais.strip() or not isinstance(codigo_pais, str):
            raise ValueError("Referencia sin país o nacionalidad")
        codigo_pais = codigo_pais.strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", codigo_pais):
            raise ValueError("Código de nacionalidad inválido")
        referencias.append({"pais": pais.strip(), "nacionalidad": codigo_pais, "fuente": "RandomUser 1.4"})
    # La evidencia conserva únicamente los campos que utiliza el robot.
    evidencia = {"results": [
        {"nat": fila["nat"], "location": {"country": fila["location"]["country"]}}
        for fila in filas
    ]}
    (ruta / "referencia_api.json").write_text(json.dumps(evidencia, indent=2, ensure_ascii=False), encoding="utf-8")
    LOG.info("API HTTP %s | referencias=%s", codigo, len(referencias))
    return referencias


def preparar_excel(movimientos, referencias, ruta):
    if not movimientos:
        raise ValueError("Sin movimientos para procesar")
    antes = pd.DataFrame(movimientos)
    trabajo = antes.copy()
    trabajo["fecha"] = pd.to_datetime(trabajo["fecha"], format="mixed", errors="coerce")
    limpio = trabajo["monto"].astype(str).str.replace(r"[,$]", "", regex=True).str.strip()
    trabajo["monto_num"] = pd.to_numeric(limpio, errors="coerce")
    formato_ok = (
        trabajo["fecha"].notna() & trabajo["monto_num"].abs().lt(float("inf"))
        & trabajo["id_transaccion"].astype(str).str.fullmatch(r"\d+")
    )
    validos = trabajo[formato_ok]
    if validos.empty:
        raise ValueError("No quedaron movimientos con formato válido")
    maestro = leer_maestro(BASE / "maestro_cuentas.xlsx")
    despues, _ = aplicar_reglas(enriquecer_con_maestro(validos, maestro))
    revisar = despues.loc[despues["estado"] == "REVISAR", REVIEW_COLUMNS]
    ref = pd.DataFrame(referencias, columns=["pais", "nacionalidad", "fuente"])
    reporte = ruta / "Movimientos_EP3.xlsx"
    guardar_excel({
        "Antes": antes, "Despues": despues, "Referencia_API": ref,
        "Excepciones": revisar, "Rechazados": antes[~formato_ok],
    }, reporte)
    adjunto = ruta / "Revision_EP3.xlsx"
    guardar_excel({"Excepciones": revisar}, adjunto)
    for archivo, hoja, cantidad in (
        (reporte, "Despues", len(despues)), (adjunto, "Excepciones", len(revisar)),
    ):
        libro = load_workbook(archivo, read_only=True)
        try:
            if libro[hoja].max_row != cantidad + 1:
                raise ValueError(f"Filas de Excel inconsistentes en {hoja}")
        finally:
            libro.close()
    filas = json.loads(despues.to_json(orient="records", date_format="iso", force_ascii=False))
    (ruta / "panel_EP3.csv").write_bytes(generar_csv(filas))
    LOG.info("EXCEL abierto y verificado | antes=%s | válidos=%s | revisar=%s | rechazados=%s",
             len(antes), len(despues), len(revisar), int((~formato_ok).sum()))
    return revisar, adjunto, reporte


def cargar_panel(csv):
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    csv = csv.resolve(strict=True)
    perfil = OUT / "chrome_panel"
    opciones = webdriver.ChromeOptions()
    reutilizar = False
    try:
        puerto = int((perfil / "DevToolsActivePort").read_text().splitlines()[0])
        with socket.create_connection(("127.0.0.1", puerto), timeout=0.5):
            reutilizar = True
        opciones.debugger_address = f"127.0.0.1:{puerto}"
    except (OSError, ValueError, IndexError):
        pass
    if not reutilizar:
        opciones.add_argument(f"--user-data-dir={perfil}")
        opciones.add_experimental_option("detach", True)
    driver = webdriver.Chrome(options=opciones)
    try:
        driver.set_page_load_timeout(30)
        if reutilizar and driver.current_url != PANEL_URL:
            driver.switch_to.new_window("tab")
        driver.get(PANEL_URL)
        espera = WebDriverWait(driver, 20)
        archivo = espera.until(lambda pagina: pagina.find_element(By.ID, "report-file"))
        estado = driver.find_element(By.ID, "file-status")
        archivo.send_keys(str(csv))
        resultado = espera.until(lambda _: estado.get_attribute("data-report-state"))
        if resultado == "error":
            raise RuntimeError(f"El panel rechazó el CSV: {estado.text}")
        if resultado != "guardado" or not driver.find_element(By.ID, "dashboard").is_displayed():
            raise RuntimeError("El panel no confirmó que el informe quedó guardado")
        driver.save_screenshot(str(csv.parent / "panel_vercel.png"))
        LOG.info("PANEL | %s analizado y guardado en Chrome", csv.name)
    except Exception:
        if reutilizar:
            driver.service.stop()
        else:
            driver.quit()
        raise
    else:
        # La ventana queda abierta para la revisión, aunque el robot termine.
        driver.service.stop()


def notificar(revisar, adjunto):
    if revisar.empty:
        LOG.info("CORREO omitido | 0 excepciones")
        return
    url = os.environ.get("VERCEL_OUTLOOK_URL", "").strip()
    secret = os.environ.get("VERCEL_ALERT_SECRET", "").strip()
    destino = urlsplit(url)
    if destino.scheme != "https" or not destino.hostname or destino.path != "/api/outlook" or len(secret) < 32:
        raise ValueError("Configura VERCEL_OUTLOOK_URL y VERCEL_ALERT_SECRET")
    contenido = base64.b64encode(adjunto.read_bytes()).decode("ascii")
    cuerpo = json.dumps({"cantidad": len(revisar), "xlsx": contenido}).encode()
    if len(cuerpo) > 900_000 or len(revisar) > 5000:
        raise ValueError("Adjunto o número de excepciones fuera del límite")
    datos = revisar.astype(str).sort_values(REVIEW_COLUMNS).to_json(orient="records", force_ascii=False)
    huella = hashlib.sha256(f"{url}\n{datos}".encode()).hexdigest()

    with closing(sqlite3.connect(OUT / "alertas_ep3.sqlite")) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS alertas (huella TEXT PRIMARY KEY, estado TEXT NOT NULL)")
        reserva = db.execute("INSERT OR IGNORE INTO alertas VALUES (?, 'pendiente')", (huella,))
        if reserva.rowcount == 0:
            estado, = db.execute("SELECT estado FROM alertas WHERE huella=?", (huella,)).fetchone()
            LOG.info("MEJORA | alerta duplicada omitida | estado anterior=%s", estado)
            if estado == "pendiente":
                raise RuntimeError(f"Estado de envío sin confirmar. Revisar el buzón emisor antes de liberar {huella}")
            return
        db.commit()
        solicitud = Request(url, cuerpo, {
            "Content-Type": "application/json", "Authorization": f"Bearer {secret}",
        })
        with urlopen(solicitud, timeout=25) as respuesta:
            acuse = json.load(respuesta)
            if respuesta.status != 202 or acuse.get("estado") != "aceptado":
                raise RuntimeError("No se confirmó aceptación del correo")
        db.execute("UPDATE alertas SET estado='aceptado' WHERE huella=?", (huella,))
        LOG.info("CORREO aceptado HTTP 202 | request_id=%s", acuse.get("request_id"))


def datos_demo():
    return [
        {"id_transaccion": "101", "fecha": "2025-01-09", "cuenta_id": "800002", "accion": "Deposit", "monto": "$250"},
        {"id_transaccion": "102", "fecha": "2025-01-09", "cuenta_id": "800003", "accion": "Withdrawal", "monto": "-$6,000"},
        {"id_transaccion": "103", "fecha": "2025-01-09", "cuenta_id": "999999", "accion": "Deposit", "monto": "$0"},
        {"id_transaccion": "104", "fecha": "fecha inválida", "cuenta_id": "800003", "accion": "Deposit", "monto": "$25"},
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Usa movimientos sintéticos")
    parser.add_argument("--sin-api", action="store_true", help="Omite la API en una prueba demo sin red")
    parser.add_argument("--sin-panel", action="store_true", help="Genera los informes sin abrir Vercel")
    parser.add_argument("--solo-panel", type=Path, metavar="CSV", help="Abre Vercel con un reporte ya generado")
    parser.add_argument("--enviar", action="store_true", help="Envía correo cuando hay excepciones")
    parser.add_argument("--abrir-excel", action="store_true", help="Abre el reporte en Excel o la aplicación asociada de Windows")
    args = parser.parse_args()
    if args.solo_panel:
        if args.demo or args.sin_api or args.sin_panel or args.enviar or args.abrir_excel:
            parser.error("--solo-panel se usa sin otras opciones")
        logging.basicConfig(level=logging.INFO)
        try:
            cargar_panel(args.solo_panel)
            return 0
        except Exception:
            LOG.exception("No se pudo abrir el informe en Vercel")
            return 1
    if (args.sin_api and not args.demo) or (args.demo and args.enviar):
        parser.error("--sin-api requiere --demo. --demo y --enviar son incompatibles.")
    ruta = OUT / (datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8])
    ruta.mkdir(parents=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(ruta / "ejecucion.log", encoding="utf-8")])
    try:
        if args.demo:
            LOG.info("LOGIN omitido | movimientos sintéticos de demostración")
        movimientos = datos_demo() if args.demo else leer_testfire(ruta)
        if args.sin_api:
            LOG.info("API omitida por opción de prueba sin red")
        referencias = [] if args.sin_api else referencia_publica(ruta)
        revisar, adjunto, reporte = preparar_excel(movimientos, referencias, ruta)
        if not args.sin_panel:
            cargar_panel(ruta / "panel_EP3.csv")
        if args.abrir_excel:
            os.startfile(reporte)
            LOG.info("Se solicitó abrir %s en la aplicación de escritorio", reporte.name)
        if args.enviar:
            notificar(revisar, adjunto)
        else:
            LOG.info("CORREO omitido | ejecución sin envío")
        LOG.info("FIN | %s", ruta)
        return 0
    except Exception:
        LOG.exception("EP3 detenido | evidencias en %s", ruta)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
