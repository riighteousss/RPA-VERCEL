"""
Modulo HTTP del robot (EP2).
Hace los requests (GET, POST, PUT, PATCH, DELETE), revisa el codigo de estado
y guarda cada request/response como evidencia para el informe.
"""

import json
import time
import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# CONFIGURACION
# ---------------------------------------------------------
HTTPBIN_URL = "https://httpbin.org"            # servicio de prueba, devuelve lo que le mandamos
RANDOMUSER_URL = "https://randomuser.me/api/"  # genera personas de mentira
TESTFIRE_API_URL = "https://demo.testfire.net/api"

TIMEOUT = 10             # segundos esperando respuesta
MAX_REINTENTOS = 3       # solo se reintenta si el servidor da 5xx o no responde
PAUSA_REINTENTO = 1

EVIDENCIA = []           # aca queda cada request/response (se guarda en un json al final)

# por si randomuser no responde el dia de la demo
PERSONAS_RESPALDO = [
    {"nombre": "Camila Rojas", "email": "camila.rojas@example.com", "pais": "Chile"},
    {"nombre": "Diego Fuentes", "email": "diego.fuentes@example.com", "pais": "Chile"},
    {"nombre": "Laura Perez", "email": "laura.perez@example.com", "pais": "Spain"},
    {"nombre": "John Miller", "email": "john.miller@example.com", "pais": "United States"},
    {"nombre": "Ana Torres", "email": "ana.torres@example.com", "pais": "Mexico"},
]


# ---------------------------------------------------------
# FUNCIONES BASE
# ---------------------------------------------------------
def clasificar_estado(codigo):
    if 200 <= codigo < 300:
        return "OK"
    elif 400 <= codigo < 500:
        return "ERROR DEL CLIENTE"
    elif codigo >= 500:
        return "ERROR DEL SERVIDOR"
    else:
        return "OTRO"


def _ocultar(datos):
    """Tapa claves/tokens (tambien dentro de JSON anidado) para que no queden en la evidencia."""
    if isinstance(datos, list):
        return [_ocultar(d) for d in datos]
    if not isinstance(datos, dict):
        return datos
    copia = {}
    for clave, valor in datos.items():
        if clave.lower() in ("password", "passw", "clave"):
            copia[clave] = "****"
        elif clave.lower() in ("authorization", "token"):
            copia[clave] = str(valor)[:8] + "..."
        else:
            copia[clave] = _ocultar(valor)
    return copia


def _texto_respuesta(respuesta):
    """Cuerpo de la respuesta para la evidencia (con tokens tapados)."""
    try:
        return json.dumps(_ocultar(respuesta.json()), ensure_ascii=False)[:800]
    except ValueError:
        return respuesta.text[:800]


def _registrar(metodo, url, json_body, headers, respuesta, ms):
    EVIDENCIA.append({
        "hora": datetime.now().strftime("%H:%M:%S"),
        "metodo": metodo,
        "url": url,
        "headers_enviados": _ocultar(headers or {}),
        "json_enviado": _ocultar(json_body),
        "status": respuesta.status_code,
        "clasificacion": clasificar_estado(respuesta.status_code),
        "respuesta": _texto_respuesta(respuesta),
        "ms": ms,
    })


def llamar(metodo, url, json_body=None, headers=None, params=None):
    """Hace el request, revisa el estado y guarda evidencia. Devuelve la respuesta o None."""
    respuesta = None
    intento = 0

    while intento < MAX_REINTENTOS:
        intento += 1
        inicio = time.time()
        try:
            respuesta = requests.request(metodo, url, json=json_body, headers=headers,
                                         params=params, timeout=TIMEOUT)
        except requests.exceptions.RequestException as e:
            logger.warning(f"{metodo} {url} fallo ({e.__class__.__name__}), intento {intento}/{MAX_REINTENTOS}")
            respuesta = None
            time.sleep(PAUSA_REINTENTO)
            continue

        ms = round((time.time() - inicio) * 1000)
        _registrar(metodo, url, json_body, headers, respuesta, ms)
        logger.info(f"{metodo} {url} -> {respuesta.status_code} ({clasificar_estado(respuesta.status_code)}) {ms} ms")

        if respuesta.status_code >= 500:
            logger.warning(f"Error del servidor, intento {intento}/{MAX_REINTENTOS}")
            time.sleep(PAUSA_REINTENTO)
            continue  # 5xx se reintenta
        break         # 2xx y 4xx no se reintentan

    return respuesta


def guardar_evidencia(ruta):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(EVIDENCIA, f, indent=2, ensure_ascii=False)
    logger.info(f"Evidencia HTTP guardada en {ruta} ({len(EVIDENCIA)} requests)")


def resumen_evidencia():
    """Version corta de la evidencia (para la hoja HTTP del Excel)."""
    return [
        {"hora": e["hora"], "metodo": e["metodo"], "url": e["url"],
         "status": e["status"], "clasificacion": e["clasificacion"], "ms": e["ms"]}
        for e in EVIDENCIA
    ]


# ---------------------------------------------------------
# GET: datos de prueba con RandomUser
# ---------------------------------------------------------
def obtener_beneficiarios(cantidad=5):
    respuesta = llamar("GET", RANDOMUSER_URL,
                       params={"results": cantidad, "nat": "es,mx,us,gb", "inc": "name,email,location"})
    personas = []

    if respuesta is not None and respuesta.status_code == 200:
        try:
            for r in respuesta.json()["results"]:
                personas.append({
                    "nombre": f"{r['name']['first']} {r['name']['last']}",
                    "email": r["email"],
                    "pais": r["location"]["country"],
                    "fuente": "randomuser.me",
                })
        except (ValueError, KeyError, TypeError) as e:
            logger.warning(f"La respuesta de randomuser vino con otro formato: {e}")
            personas = []

    if not personas:
        logger.warning("No se pudo usar RandomUser, se usan datos de respaldo locales")
        personas = [dict(p, fuente="respaldo local") for p in PERSONAS_RESPALDO[:cantidad]]

    return personas


# ---------------------------------------------------------
# POST: registrar el log de la ejecucion en un webhook de prueba
# ---------------------------------------------------------
def registrar_log_webhook(resumen):
    payload = {"robot": "testfire_ep2", "hora": datetime.now().isoformat(), "resumen": resumen}
    respuesta = llamar("POST", HTTPBIN_URL + "/post", json_body=payload)
    if respuesta is None:
        return None
    return respuesta.status_code


# ---------------------------------------------------------
# Los 5 metodos + codigos de estado, contra httpbin
# ---------------------------------------------------------
def demo_metodos_http():
    cuerpo = {"origen": "robot_ep2", "dato": "prueba"}
    pruebas = [
        ("GET", "/get", None),
        ("POST", "/post", cuerpo),
        ("PUT", "/put", cuerpo),
        ("PATCH", "/patch", {"dato": "corregido"}),
        ("DELETE", "/delete", None),
        ("GET", "/status/404", None),
        ("GET", "/status/500", None),
    ]

    resultados = []
    for metodo, ruta, body in pruebas:
        r = llamar(metodo, HTTPBIN_URL + ruta, json_body=body)
        if r is None:
            status, clase = None, "SIN RESPUESTA"
        else:
            status, clase = r.status_code, clasificar_estado(r.status_code)
        resultados.append({"metodo": metodo, "endpoint": ruta, "status": status, "clasificacion": clase})
    return resultados


# ---------------------------------------------------------
# API REST del propio TestFire (login -> token -> cuentas -> movimientos)
# ---------------------------------------------------------
def _sacar_token(respuesta):
    try:
        data = respuesta.json()
    except ValueError:
        return None
    if isinstance(data, dict):
        for clave in ("Authorization", "authorization", "token", "Token"):
            if clave in data:
                return str(data[clave])
    return None


def _buscar_lista(data, nivel=0):
    """Devuelve la primera lista que encuentre dentro del JSON (la API anida las listas)."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and nivel < 3:
        for valor in data.values():
            encontrada = _buscar_lista(valor, nivel + 1)
            if encontrada is not None:
                return encontrada
    return None


def _sacar_id_cuenta(lista):
    for item in lista or []:
        if isinstance(item, dict):
            for clave in ("id", "Id", "accountId", "account_id"):
                if clave in item:
                    return str(item[clave])
    return None


def api_testfire(usuario, clave, cuenta_por_defecto="800002"):
    resultado = {"login_status": None, "token_ok": False, "sin_token_status": None,
                 "cuentas_status": None, "n_cuentas": None, "cuenta_usada": None,
                 "tx_status": None, "n_tx_api": None}

    r = llamar("POST", f"{TESTFIRE_API_URL}/login", json_body={"username": usuario, "password": clave})
    if r is None:
        return resultado
    resultado["login_status"] = r.status_code
    token = _sacar_token(r)
    resultado["token_ok"] = token is not None

    # mismo GET sin token: tiene que dar 401
    sin_token = llamar("GET", f"{TESTFIRE_API_URL}/login")
    if sin_token is not None:
        resultado["sin_token_status"] = sin_token.status_code

    if token is None:
        logger.warning("La API no devolvio token, no se hacen las otras consultas")
        return resultado

    headers = {"Authorization": token}

    r = llamar("GET", f"{TESTFIRE_API_URL}/account", headers=headers)
    cuenta = cuenta_por_defecto
    if r is not None:
        resultado["cuentas_status"] = r.status_code
        if r.status_code == 200:
            try:
                lista = _buscar_lista(r.json())
            except ValueError:
                lista = None
            if lista is not None:
                resultado["n_cuentas"] = len(lista)
                cuenta = _sacar_id_cuenta(lista) or cuenta_por_defecto

    resultado["cuenta_usada"] = cuenta
    r = llamar("GET", f"{TESTFIRE_API_URL}/account/{cuenta}/transactions", headers=headers)
    if r is not None:
        resultado["tx_status"] = r.status_code
        if r.status_code == 200:
            try:
                lista = _buscar_lista(r.json())
            except ValueError:
                lista = None
            if lista is not None:
                resultado["n_tx_api"] = len(lista)

    return resultado
