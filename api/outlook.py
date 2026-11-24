"""Protected Vercel relay for EP3 review workbooks."""
import base64
import binascii
import json
import os
import re
import secrets
import smtplib
import ssl
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from api.alerta import _json_respuesta

MAX_BODY = 900_000
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CUERPO = ("Revisa el motivo indicado para cada fila del Excel adjunto. "
          "El robot marca excepciones para revisión humana.")


def enviar_graph(adj, cantidad):
    tenant, client, secret, sender, recipient = (
        os.environ.get(key, "").strip() for key in (
            "GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET",
            "GRAPH_MAILBOX", "GRAPH_REVIEW_TO",
        )
    )
    if not all((tenant, client, secret, sender, recipient)):
        raise ValueError("Configuración de Microsoft Graph incompleta")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", tenant):
        raise ValueError("GRAPH_TENANT_ID debe ser el identificador del tenant")
    if not all(re.fullmatch(r"[^\s@,;]+@[^\s@,;]+", address) for address in (sender, recipient)):
        raise ValueError("Configura un buzón y un destinatario válidos")

    token_request = Request(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        urlencode({
            "client_id": client, "client_secret": secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }).encode(),
        {"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urlopen(token_request, timeout=8) as response:
        token = json.load(response)["access_token"]

    message = {"message": {
        "subject": f"[EP3] {cantidad} movimiento(s) requieren revisión",
        "body": {
            "contentType": "Text",
            "content": CUERPO,
        },
        "toRecipients": [{"emailAddress": {"address": recipient}}],
        "attachments": [{
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "Revision_EP3.xlsx", "contentType": XLSX_TYPE, "contentBytes": adj,
        }],
    }}
    request = Request(
        f"https://graph.microsoft.com/v1.0/users/{quote(sender, safe='')}/sendMail",
        json.dumps(message, ensure_ascii=False).encode("utf-8"),
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=8) as response:
        if response.status != 202:
            raise OSError(f"Graph devolvió HTTP {response.status}")
        return response.headers.get("request-id")


def enviar_gmail(adj, cantidad, sender):
    recipient = os.environ.get("GMAIL_REVIEW_TO", "").strip()
    password = "".join(os.environ.get("GMAIL_APP_PASSWORD", "").split())
    if not password or not all(
        re.fullmatch(r"[^\s@,;<>]+@[^\s@,;<>]+", address) for address in (sender, recipient)
    ):
        raise ValueError("Configuración SMTP de Gmail incompleta o inválida")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = f"[EP3] {cantidad} movimiento(s) requieren revisión"
    message.set_content(CUERPO)
    maintype, subtype = XLSX_TYPE.split("/")
    message.add_attachment(adj, maintype=maintype, subtype=subtype, filename="Revision_EP3.xlsx")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=8, context=ssl.create_default_context()) as smtp:
        smtp.login(sender, password)
        smtp.send_message(message, from_addr=sender, to_addrs=[recipient])


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        secret = os.environ.get("ALERT_API_SECRET", "").strip()
        authorization = self.headers.get("Authorization", "")
        if len(secret) < 32:
            _json_respuesta(self, 503, {"error": "Autenticación del servicio sin configurar"})
            return
        if not secrets.compare_digest(authorization.encode(), f"Bearer {secret}".encode()):
            _json_respuesta(self, 401, {"error": "No autorizado"})
            return

        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 1 <= size <= MAX_BODY:
                _json_respuesta(self, 413, {"error": "Tamaño de solicitud fuera del límite"})
                return
            payload = json.loads(self.rfile.read(size))
            count, attachment = payload["cantidad"], payload["xlsx"]
            if type(count) is not int or not 1 <= count <= 5000:
                raise ValueError("Cantidad inválida")
            workbook = base64.b64decode(attachment, validate=True)
            if not workbook.startswith(b"PK\x03\x04"):
                raise ValueError("Adjunto inválido")
        except (ValueError, KeyError, TypeError, binascii.Error):
            _json_respuesta(self, 400, {"error": "Se requiere un Excel y entre 1 y 5000 excepciones"})
            return

        try:
            gmail_sender = os.environ.get("GMAIL_FROM", "").strip()
            if gmail_sender:
                enviar_gmail(workbook, count, gmail_sender)
                request_id = None
            else:
                request_id = enviar_graph(attachment, count)
        except HTTPError as error:
            print(f"[correo] Proveedor HTTP {error.code}", flush=True)
            _json_respuesta(self, 502, {"error": "Microsoft rechazó la solicitud", "http_microsoft": error.code})
            return
        except (OSError, ValueError, KeyError) as error:
            print(f"[correo] Error de proveedor: {type(error).__name__}", flush=True)
            _json_respuesta(self, 502, {"error": "No se pudo confirmar la aceptación por Microsoft"})
            return
        print(f"[correo] HTTP 202 | casos={count} | request_id={request_id}", flush=True)
        _json_respuesta(self, 202, {"estado": "aceptado", "request_id": request_id})
