"""
Integracion con Excel (EP2).
Lee el maestro de cuentas, lo valida, lo cruza con los movimientos sacados
de la web y arma los reportes en Excel.
"""

import os
import logging

import pandas as pd
from openpyxl.styles import Font

logger = logging.getLogger(__name__)

COLUMNAS_MAESTRO = ["cuenta_id", "titular", "tipo", "limite_monto", "estado"]


def crear_maestro_ejemplo(ruta):
    datos = pd.DataFrame([
        {"cuenta_id": "800002", "titular": "John Smith", "tipo": "Savings", "limite_monto": 10000, "estado": "Activa"},
        {"cuenta_id": "800003", "titular": "John Smith", "tipo": "Checking", "limite_monto": 5000, "estado": "Activa"},
    ])
    datos.to_excel(ruta, index=False)


def leer_maestro(ruta, limite_por_defecto=5000):
    """Lee el maestro de cuentas y revisa que venga bien armado."""
    if not os.path.exists(ruta):
        logger.warning(f"No existe el maestro {ruta}, se crea uno de ejemplo")
        crear_maestro_ejemplo(ruta)

    maestro = pd.read_excel(ruta, dtype={"cuenta_id": str})

    faltan = [c for c in COLUMNAS_MAESTRO if c not in maestro.columns]
    if faltan:
        raise ValueError(f"Al maestro le faltan columnas: {faltan}")

    maestro = maestro.dropna(subset=["cuenta_id"]).copy()
    maestro["cuenta_id"] = maestro["cuenta_id"].str.strip()

    maestro["limite_monto"] = pd.to_numeric(maestro["limite_monto"], errors="coerce")
    sin_limite = maestro["limite_monto"].isna().sum()
    if sin_limite > 0:
        logger.warning(f"{sin_limite} cuenta(s) sin limite valido, se usa {limite_por_defecto}")
        maestro["limite_monto"] = maestro["limite_monto"].fillna(limite_por_defecto)

    repetidas = maestro["cuenta_id"].duplicated().sum()
    if repetidas > 0:
        logger.warning(f"{repetidas} cuenta(s) repetidas en el maestro, se deja la primera")
        maestro = maestro.drop_duplicates(subset="cuenta_id", keep="first")

    logger.info(f"Maestro leido: {len(maestro)} cuentas")
    return maestro


def enriquecer_con_maestro(df, maestro):
    """Agrega titular, tipo, limite y estado de la cuenta a cada movimiento."""
    maestro = maestro.rename(columns={"tipo": "tipo_cuenta", "estado": "estado_cuenta"})
    resultado = df.merge(maestro, how="left", on="cuenta_id")
    resultado["en_maestro"] = resultado["titular"].notna()

    no_estan = resultado.loc[~resultado["en_maestro"], "cuenta_id"].nunique()
    logger.info(f"Cruce con maestro: {no_estan} cuenta(s) de la web no estan en el maestro")
    return resultado


def guardar_excel(hojas, ruta):
    """hojas = {"nombre de la hoja": DataFrame}"""
    with pd.ExcelWriter(ruta, engine="openpyxl") as writer:
        for nombre, tabla in hojas.items():
            tabla.to_excel(writer, sheet_name=nombre[:31], index=False)

        for hoja in writer.book.worksheets:
            hoja.freeze_panes = "A2"
            hoja.auto_filter.ref = hoja.dimensions
            for celda in hoja[1]:
                celda.font = Font(bold=True)
            for col in hoja.columns:
                for celda in col[1:]:
                    if celda.data_type == "f":
                        celda.data_type = "s"
                ancho = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                hoja.column_dimensions[col[0].column_letter].width = min(ancho + 2, 60)
                if str(col[0].value).startswith("monto"):
                    for celda in col[1:]:
                        celda.number_format = "#,##0.00"

    logger.info(f"Excel guardado: {ruta}")
    return ruta
