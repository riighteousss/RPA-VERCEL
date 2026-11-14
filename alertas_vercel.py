"""Cliente opcional para publicar los resultados del robot en Vercel."""

import json
import os
from urllib.parse import urlsplit

import requests

from api.alerta import generar_csv


TIMEOUT_VERCEL = 15


def guardar_reporte_csv_local(df_movimientos, ruta_csv):
    """Genera un CSV validado localmente para cargarlo en el panel."""
    movimientos = json.loads(df_movimientos.to_json(
        orient="records", date_format="iso", force_ascii=False
    ))
    contenido = generar_csv(movimientos)
    os.makedirs(os.path.dirname(os.path.abspath(ruta_csv)), exist_ok=True)
    with open(ruta_csv, "wb") as archivo:
        archivo.write(contenido)
    return ruta_csv


def enviar_reporte_vercel(df_movimientos, ruta_csv):
    """Publica filas ya analizadas y guarda localmente el CSV devuelto por la API."""
    url = os.environ.get("VERCEL_ALERT_URL", "").strip()
    secreto = os.environ.get("VERCEL_ALERT_SECRET", "").strip()
    if not url and not secreto:
        return {"estado": "desactivado", "ruta_csv": None}
    if not url or not secreto:
        raise ValueError("Configura VERCEL_ALERT_URL y VERCEL_ALERT_SECRET juntos")

    partes = urlsplit(url)
    if partes.scheme not in ("https", "http") or not partes.netloc:
        raise ValueError("VERCEL_ALERT_URL debe ser una URL HTTP/HTTPS valida")
    if partes.scheme != "https" and partes.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("VERCEL_ALERT_URL debe usar HTTPS fuera de localhost")

    movimientos = json.loads(df_movimientos.to_json(
        orient="records", date_format="iso", force_ascii=False
    ))
    respuesta = requests.post(
        url,
        json={"movimientos": movimientos},
        headers={"Authorization": f"Bearer {secreto}"},
        timeout=TIMEOUT_VERCEL,
    )
    respuesta.raise_for_status()
    if not respuesta.headers.get("Content-Type", "").lower().startswith("text/csv"):
        raise RuntimeError("La API de Vercel no devolvio el reporte CSV esperado")

    os.makedirs(os.path.dirname(os.path.abspath(ruta_csv)), exist_ok=True)
    with open(ruta_csv, "wb") as archivo:
        archivo.write(respuesta.content)
    return {
        "estado": "generado",
        "ruta_csv": ruta_csv,
    }
