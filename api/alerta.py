"""Vercel endpoint that validates movement data and returns a CSV report."""

import csv
import io
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit


COLUMNAS = [
    "id_transaccion", "fecha", "cuenta_id", "accion", "monto_num", "titular",
    "tipo_cuenta", "estado_cuenta", "limite_monto", "en_maestro",
    "errores_negocio", "sugerencia", "estado",
]
COLUMNAS_NUMERICAS = {"monto_num", "limite_monto"}
MAX_BODY_BYTES = 1_000_000
MAX_FILAS = 5000
MAX_CARACTERES_CELDA = 10000


class SolicitudInvalida(ValueError):
    """The request body does not match the movement report contract."""


def _valor_csv(columna, valor):
    if valor is None:
        return ""
    if isinstance(valor, (dict, list)):
        raise SolicitudInvalida("Los valores de las filas deben ser escalares")

    texto = str(valor)
    if len(texto) > MAX_CARACTERES_CELDA:
        raise SolicitudInvalida("Una celda supera el largo permitido")

    if columna in COLUMNAS_NUMERICAS:
        if isinstance(valor, bool):
            raise SolicitudInvalida(f"El campo {columna} debe ser numerico")
        try:
            numero = float(texto)
        except (TypeError, ValueError):
            raise SolicitudInvalida(f"El campo {columna} debe ser numerico")
        if numero != numero or numero in (float("inf"), float("-inf")):
            raise SolicitudInvalida(f"El campo {columna} debe ser finito")
        return texto

    if texto.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + texto
    return texto


def generar_csv(movimientos):
    salida = io.StringIO(newline="")
    escritor = csv.DictWriter(salida, fieldnames=COLUMNAS, extrasaction="ignore")
    escritor.writeheader()
    for movimiento in movimientos:
        escritor.writerow({
            columna: _valor_csv(columna, movimiento.get(columna))
            for columna in COLUMNAS
        })
    return salida.getvalue().encode("utf-8")


def _validar_movimientos(datos):
    if not isinstance(datos, dict) or not isinstance(datos.get("movimientos"), list):
        raise SolicitudInvalida("Se requiere una lista 'movimientos'")

    movimientos = datos["movimientos"]
    if len(movimientos) > MAX_FILAS:
        raise SolicitudInvalida(f"Se permiten hasta {MAX_FILAS} movimientos")

    for indice, movimiento in enumerate(movimientos):
        if not isinstance(movimiento, dict):
            raise SolicitudInvalida(f"El movimiento {indice + 1} debe ser un objeto")
        if movimiento.get("estado") not in ("OK", "REVISAR"):
            raise SolicitudInvalida(f"El movimiento {indice + 1} tiene un estado invalido")
        for columna in COLUMNAS:
            if columna in movimiento:
                _valor_csv(columna, movimiento[columna])
    return movimientos


def _json_respuesta(handler, codigo, datos):
    cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
    handler.send_response(codigo)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(cuerpo)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(cuerpo)


def _rechazar_constante_json(valor):
    raise SolicitudInvalida(f"Valor JSON invalido: {valor}")


class handler(BaseHTTPRequestHandler):
    """Vercel Python function handler at POST /api/alerta."""

    def _error(self, codigo, mensaje):
        _json_respuesta(self, codigo, {"error": mensaje})

    def do_GET(self):
        self._error(405, "Usa POST para generar el reporte")

    def do_POST(self):
        if urlsplit(self.path).path.rstrip("/") != "/api/alerta":
            self._error(404, "Ruta no encontrada")
            return

        secreto = os.environ.get("ALERT_API_SECRET", "")
        if not secreto:
            self._error(500, "La API no tiene configurado ALERT_API_SECRET")
            return
        if len(secreto) < 32:
            self._error(500, "ALERT_API_SECRET debe tener al menos 32 caracteres")
            return
        autorizacion = self.headers.get("Authorization", "")
        recibido = autorizacion[7:] if autorizacion.startswith("Bearer ") else ""
        if not secrets.compare_digest(recibido.encode("utf-8"), secreto.encode("utf-8")):
            self._error(401, "No autorizado")
            return

        try:
            longitud = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._error(411, "Se requiere Content-Length valido")
            return
        if longitud < 1:
            self._error(400, "El cuerpo de la solicitud esta vacio")
            return
        if longitud > MAX_BODY_BYTES:
            self._error(413, "El cuerpo supera el tamano permitido")
            return

        try:
            cuerpo = self.rfile.read(longitud)
            if len(cuerpo) != longitud:
                raise SolicitudInvalida("El cuerpo de la solicitud esta incompleto")
            datos = json.loads(
                cuerpo.decode("utf-8"),
                parse_constant=_rechazar_constante_json,
            )
            movimientos = _validar_movimientos(datos)
            csv_bytes = generar_csv(movimientos)
        except (UnicodeDecodeError, json.JSONDecodeError, SolicitudInvalida) as error:
            self._error(400, str(error))
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="reporte_movimientos_ev2.csv"')
        self.send_header("Content-Length", str(len(csv_bytes)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(csv_bytes)

    def log_message(self, formato, *args):
        print("[api/alerta] " + formato % args)
