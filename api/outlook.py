"""Protected Vercel relay for EP3 review workbooks."""
import base64
import binascii
import json
import os
import re
import secrets
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from api.alerta import _json_respuesta

MAX_BODY = 900_000
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
            "content": "Revisa el motivo indicado para cada fila del Excel adjunto. "
                       "El robot marca excepciones para revisión humana.",
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
            if not base64.b64decode(attachment, validate=True).startswith(b"PK\x03\x04"):
                raise ValueError("Adjunto inválido")
        except (ValueError, KeyError, TypeError, binascii.Error):
            _json_respuesta(self, 400, {"error": "Se requiere un Excel y entre 1 y 5000 excepciones"})
            return

        try:
            request_id = enviar_graph(attachment, count)
        except HTTPError as error:
            print(f"[outlook] Proveedor HTTP {error.code}", flush=True)
            _json_respuesta(self, 502, {"error": "Microsoft rechazó la solicitud", "http_microsoft": error.code})
            return
        except (OSError, ValueError, KeyError) as error:
            print(f"[outlook] Error de proveedor: {type(error).__name__}", flush=True)
            _json_respuesta(self, 502, {"error": "No se pudo confirmar la aceptación por Microsoft"})
            return
        print(f"[outlook] HTTP 202 | casos={count} | request_id={request_id}", flush=True)
        _json_respuesta(self, 202, {"estado": "aceptado", "request_id": request_id})
