"""
Reglas de negocio del robot (EP2).
Se aplican a movimientos que ya pasaron la validacion de formato y que ya
fueron cruzados con el maestro de cuentas.
"""

import logging
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

# cada regla trae su sugerencia de correccion (va al Excel de discrepancias)
SUGERENCIAS = {
    "cuenta no registrada en el maestro": "Revisar de quien es la cuenta y agregarla al maestro, o bloquear el movimiento",
    "cuenta inactiva en el maestro": "Confirmar con el area de cuentas si la cuenta se puede seguir usando",
    "monto sobre el limite": "Confirmar con un supervisor, puede ser error de digitacion",
    "monto en cero": "Descartar el movimiento, un monto en 0 no tiene efecto contable",
    "signo no coincide con la accion": "Revisar el signo: un deposito debe ser positivo y un retiro negativo",
    "fecha futura": "Corregir la fecha de la transaccion",
    "id de transaccion duplicado": "Eliminar el registro repetido",
    "posible movimiento duplicado": "Revisar si es un doble registro (misma fecha, cuenta, accion y monto)",
}


def aplicar_reglas(df, monto_max=5000, monto_min=0.01):
    """
    Necesita estas columnas: id_transaccion, fecha (texto), cuenta_id, accion,
    monto_num, en_maestro, limite_monto, estado_cuenta.
    Devuelve (df con errores_negocio / sugerencia / estado, conteo por regla).
    """
    df = df.copy()
    hoy = datetime.now().date()
    fechas = pd.to_datetime(df["fecha"], errors="coerce")
    ids_repetidos = df["id_transaccion"].duplicated(keep=False)

    clave = (df["fecha"].astype(str) + "|" + df["cuenta_id"].astype(str) + "|"
             + df["accion"].astype(str) + "|" + df["monto_num"].astype(str))
    veces = clave.map(clave.value_counts())

    errores, sugerencias = [], []
    conteo = {}

    for i in range(len(df)):
        fila = df.iloc[i]
        monto = fila["monto_num"]
        accion = str(fila["accion"]).strip().lower()
        problemas = []

        if not fila["en_maestro"]:
            problemas.append("cuenta no registrada en el maestro")
        elif str(fila["estado_cuenta"]).strip().lower() != "activa":
            problemas.append("cuenta inactiva en el maestro")

        limite = fila["limite_monto"] if pd.notnull(fila["limite_monto"]) else monto_max
        if abs(monto) > limite:
            problemas.append("monto sobre el limite")
        elif abs(monto) < monto_min:
            problemas.append("monto en cero")

        if accion == "deposit" and monto < 0:
            problemas.append("signo no coincide con la accion")
        if accion == "withdrawal" and monto > 0:
            problemas.append("signo no coincide con la accion")

        if pd.notnull(fechas.iloc[i]) and fechas.iloc[i].date() > hoy:
            problemas.append("fecha futura")

        if ids_repetidos.iloc[i]:
            problemas.append("id de transaccion duplicado")
        if veces.iloc[i] > 1:
            problemas.append("posible movimiento duplicado")

        for p in problemas:
            conteo[p] = conteo.get(p, 0) + 1

        errores.append("; ".join(problemas))
        sugerencias.append(" | ".join(SUGERENCIAS[p] for p in problemas))

    df["errores_negocio"] = errores
    df["sugerencia"] = sugerencias
    df["estado"] = ["REVISAR" if e else "OK" for e in errores]

    n_revisar = (df["estado"] == "REVISAR").sum()
    logger.info(f"Reglas de negocio: {n_revisar} de {len(df)} movimientos para revisar")
    for regla, n in sorted(conteo.items(), key=lambda x: -x[1]):
        logger.info(f"   {regla}: {n}")

    return df, conteo
