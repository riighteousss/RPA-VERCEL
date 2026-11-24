"""Chequeo del flujo EP3 sin credenciales ni correo real."""
import base64
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openpyxl import load_workbook

from api import outlook
import robot_ep3 as ep3


class Acuse:
    status = 202

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b'{"estado":"aceptado","request_id":"prueba-local"}'


with TemporaryDirectory() as destino:
    ruta = Path(destino)
    revisar, adjunto, reporte = ep3.preparar_excel(ep3.datos_demo(), [], ruta)
    assert list(revisar["id_transaccion"]) == ["102", "103"]
    with closing(load_workbook(reporte, read_only=True)) as libro:
        assert libro.sheetnames == ["Antes", "Despues", "Referencia_API", "Excepciones", "Rechazados"]
        assert libro["Rechazados"].max_row == 2
    print("Excel de demostración: 4 de entrada, 3 válidos, 2 excepciones, 1 rechazado")

    with (
        patch.object(ep3, "OUT", ruta),
        patch.dict(os.environ, {"VERCEL_OUTLOOK_URL": "https://example.com/api/outlook", "VERCEL_ALERT_SECRET": "a" * 32}),
        patch.object(ep3, "urlopen", return_value=Acuse()) as enviar,
    ):
        ep3.notificar(revisar.iloc[:0], adjunto)
        ep3.notificar(revisar, adjunto)
        ep3.notificar(revisar.iloc[::-1], adjunto)
        assert enviar.call_count == 1
        solicitud = enviar.call_args.args[0]
        payload = json.loads(solicitud.data)
        assert payload["cantidad"] == 2
        assert base64.b64decode(payload["xlsx"]) == adjunto.read_bytes()
        with closing(sqlite3.connect(ruta / "alertas_ep3.sqlite")) as db:
            assert db.execute("SELECT estado FROM alertas").fetchall() == [("aceptado",)]
    print("Correo simulado: 0 casos omitidos, HTTP 202 simulado, segundo envío bloqueado")

    entorno_graph = {
        "GRAPH_TENANT_ID": "01234567-89ab-cdef-0123-456789abcdef",
        "GRAPH_CLIENT_ID": "prueba",
        "GRAPH_CLIENT_SECRET": "prueba",
        "GRAPH_MAILBOX": "robot@example.com",
        "GRAPH_REVIEW_TO": "revision@example.com",
    }
    with (
        patch.dict(os.environ, entorno_graph),
        patch.object(outlook, "urlopen") as servicio,
    ):
        token = servicio.return_value.__enter__.return_value
        token.read.return_value = b'{"access_token":"token-de-prueba"}'
        token.status = 202
        token.headers = {"request-id": "graph-simulado"}
        assert outlook.enviar_graph(payload["xlsx"], 2) == "graph-simulado"
        autenticacion, correo = [llamada.args[0] for llamada in servicio.call_args_list]
        assert autenticacion.full_url.startswith("https://login.microsoftonline.com/")
        assert correo.full_url == "https://graph.microsoft.com/v1.0/users/robot%40example.com/sendMail"
        mensaje = json.loads(correo.data)["message"]
        assert mensaje["toRecipients"] == [{"emailAddress": {"address": "revision@example.com"}}]
        assert mensaje["attachments"][0]["contentBytes"] == payload["xlsx"]
    print("Graph simulado: OAuth, destinatario fijo y adjunto XLSX comprobados")

    with (
        patch.dict(os.environ, {"GMAIL_REVIEW_TO": "revision@example.com", "GMAIL_APP_PASSWORD": "abcd efgh ijkl mnop"}),
        patch.object(outlook.smtplib, "SMTP_SSL") as smtp_ssl,
    ):
        outlook.enviar_gmail(adjunto.read_bytes(), 2, "robot@gmail.com")
        smtp = smtp_ssl.return_value.__enter__.return_value
        assert smtp_ssl.call_args.args == ("smtp.gmail.com", 465)
        smtp.login.assert_called_once_with("robot@gmail.com", "abcdefghijklmnop")
        smtp.send_message.assert_called_once()
        mensaje = smtp.send_message.call_args.args[0]
        assert smtp.send_message.call_args.kwargs["to_addrs"] == ["revision@example.com"]
        archivo, = mensaje.iter_attachments()
        assert archivo.get_filename() == "Revision_EP3.xlsx"
        assert archivo.get_payload(decode=True) == adjunto.read_bytes()
    print("Gmail simulado: autenticación, destinatario y adjunto XLSX comprobados")


with (
    patch.object(ep3, "capturar_movimientos_testfire") as capturar,
    patch.object(ep3, "sleep") as pausa,
):
    error_red = ep3.WebDriverException("net::ERR_CONNECTION_REFUSED")
    capturar.side_effect = [error_red, error_red, ep3.datos_demo()]
    assert ep3.leer_testfire(Path(".")) == ep3.datos_demo()
    assert capturar.call_count == 3
    assert [llamada.args[0] for llamada in pausa.call_args_list] == [2, 5]

    capturar.reset_mock()
    capturar.side_effect = error_red
    try:
        ep3.leer_testfire(Path("."))
    except RuntimeError as error:
        assert "3 intentos" in str(error)
    else:
        raise AssertionError("La caída persistente debe detener el flujo")
    assert capturar.call_count == 3

    capturar.reset_mock()
    capturar.side_effect = ep3.WebDriverException("invalid session id")
    try:
        ep3.leer_testfire(Path("."))
    except ep3.WebDriverException:
        pass
    else:
        raise AssertionError("Los errores ajenos a la red deben propagarse")
    assert capturar.call_count == 1
print("TestFire simulado: recuperación, caída persistente y error ajeno a la red comprobados")


with (
    patch.dict(os.environ, {"EP3_TELEGRAM_TOKEN": "123:token-prueba", "EP3_TELEGRAM_CHAT_ID": "456"}),
    patch.object(ep3, "urlopen", return_value=Acuse()) as telegram,
):
    telegram.return_value.read = lambda: b'{"ok":true}'
    ep3.avisar_telegram("ejecucion-prueba", "TestFire no respondió")
    solicitud = telegram.call_args.args[0]
    assert solicitud.full_url == "https://api.telegram.org/bot123:token-prueba/sendMessage"
    assert json.loads(solicitud.data) == {
        "chat_id": "456", "text": "TestFire no respondió\nEjecución ejecucion-prueba",
    }
    telegram.side_effect = OSError("fallo simulado")
    with patch.object(ep3.LOG, "warning") as warning:
        ep3.avisar_telegram("ejecucion-prueba", "Aviso")
        assert "OSError" in warning.call_args.args
print("Telegram simulado: formato, destinatario y manejo de fallos comprobados")
