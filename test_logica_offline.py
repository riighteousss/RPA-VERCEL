"""
Pruebas automaticas del robot EP2.
No abren el navegador ni necesitan internet: los requests HTTP van a un
servidor local de mentira que se levanta aca mismo.

Ejecutar:  python test_logica_offline.py
"""

import glob
import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, HTTPServer

import pandas as pd
import requests
from selenium.common.exceptions import (
    NoAlertPresentException, TimeoutException, UnexpectedAlertPresentException,
)

import cliente_http
import robot_ep2
import alertas_vercel
from api import alerta as api_alerta
from integracion_excel import leer_maestro, enriquecer_con_maestro, guardar_excel
from reglas_negocio import aplicar_reglas
from testfire_robot import validar_movimientos


# ---------------------------------------------------------
# SERVIDOR HTTP LOCAL (imita httpbin, randomuser y la API de TestFire)
# ---------------------------------------------------------
class ServidorFalso(BaseHTTPRequestHandler):
    visitas = {}          # cuantas veces se llamo cada ruta
    login_con_token = True

    def log_message(self, *args):
        pass  # sin ruido en la consola

    def _responder(self, codigo, cuerpo):
        datos = json.dumps(cuerpo).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def _leer_json(self):
        largo = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(largo)) if largo else None

    def _atender(self):
        ruta = self.path.split("?")[0]
        ServidorFalso.visitas[ruta] = ServidorFalso.visitas.get(ruta, 0) + 1
        cuerpo = self._leer_json()

        if ruta.startswith("/status/"):
            return self._responder(int(ruta.split("/")[-1]), {"status": ruta})

        if ruta == "/ru/":
            return self._responder(200, {"results": [
                {"name": {"first": "Ana", "last": "Lopez"}, "email": "ana@example.com",
                 "location": {"country": "Spain"}},
                {"name": {"first": "Bob", "last": "Stone"}, "email": "bob@example.com",
                 "location": {"country": "United States"}},
            ]})
        if ruta == "/ru_malo/":
            return self._responder(200, {"otra_cosa": 1})

        if ruta == "/api/login":
            if self.command == "POST":
                if ServidorFalso.login_con_token:
                    return self._responder(200, {"Authorization": "token123456789"})
                return self._responder(200, {"mensaje": "sin token"})
            if self.headers.get("Authorization"):
                return self._responder(200, {"ok": True})
            return self._responder(401, {"error": "Unauthorized"})
        if ruta == "/api/account":
            return self._responder(200, {"Accounts": [{"Name": "Savings", "id": "800002"}]})
        if ruta == "/api/account/800002/transactions":
            return self._responder(200, {"last_10_transactions": [{"id": 1}, {"id": 2}, {"id": 3}]})

        return self._responder(200, {"metodo": self.command, "ruta": ruta, "recibido": cuerpo})

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _atender


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------
MAESTRO_PRUEBA = pd.DataFrame([
    {"cuenta_id": "800002", "titular": "John Smith", "tipo": "Savings", "limite_monto": 10000, "estado": "Activa"},
    {"cuenta_id": "800003", "titular": "John Smith", "tipo": "Checking", "limite_monto": 5000, "estado": "Activa"},
    {"cuenta_id": "800009", "titular": "Cuenta Vieja", "tipo": "Savings", "limite_monto": 1000, "estado": "Inactiva"},
])


def armar_df(filas):
    """filas = lista de (id, fecha, cuenta, accion, monto). Devuelve el df listo para aplicar_reglas."""
    df = pd.DataFrame([
        {"id_transaccion": str(f[0]), "fecha": f[1], "cuenta_id": f[2], "accion": f[3], "monto_num": f[4]}
        for f in filas
    ])
    return enriquecer_con_maestro(df, MAESTRO_PRUEBA)


def reglas_de(df_resultado, posicion=0):
    texto = df_resultado.iloc[posicion]["errores_negocio"]
    return texto.split("; ") if texto else []


# ---------------------------------------------------------
# PRUEBAS
# ---------------------------------------------------------
class TestValidacionFormato(unittest.TestCase):
    def test_acepta_fecha_iso_con_hora_y_monto_con_signo(self):
        movs = [{"fecha": "2026-09-08 01:37", "descripcion": "Withdrawal cuenta 800020", "monto": "-$1234.00"}]
        validos = validar_movimientos(movs)
        self.assertEqual(len(validos), 1)
        self.assertEqual(validos[0]["monto_num"], -1234.0)

    def test_descarta_fecha_y_monto_invalidos(self):
        movs = [
            {"fecha": "ABCDE", "descripcion": "x", "monto": "$10.00"},
            {"fecha": "2026-09-08 01:37", "descripcion": "x", "monto": "N/A"},
            {"fecha": "2026-09-08 01:37", "descripcion": "", "monto": "$10.00"},
            {"fecha": "2026-09-08 01:37", "descripcion": "ok", "monto": "$10.00"},
        ]
        self.assertEqual(len(validar_movimientos(movs)), 1)


class TestExtraccionFilas(unittest.TestCase):
    def test_salta_encabezado_y_filas_cortas(self):
        filas = [
            ["Transaction ID", "Transaction Time", "Account ID", "Action", "Amount"],
            ["15835", "2026-09-08 01:40", "800011", "Deposit", "$0.00"],
            [],
            ["15833", "2026-09-08 01:37", "800020", "Deposit", "$1234.00"],
            ["dato", "suelto"],
        ]
        movs = robot_ep2.filas_a_movimientos(filas)
        self.assertEqual(len(movs), 2)
        self.assertEqual(movs[0]["id_transaccion"], "15835")
        self.assertEqual(movs[1]["descripcion"], "Deposit cuenta 800020")


class TestMaestro(unittest.TestCase):
    def test_crea_maestro_si_no_existe(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "maestro.xlsx")
            maestro = leer_maestro(ruta)
            self.assertTrue(os.path.exists(ruta))
            self.assertGreaterEqual(len(maestro), 1)

    def test_error_si_faltan_columnas(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "maestro.xlsx")
            pd.DataFrame([{"cuenta_id": "1", "titular": "x"}]).to_excel(ruta, index=False)
            with self.assertRaises(ValueError):
                leer_maestro(ruta)

    def test_limite_vacio_usa_valor_por_defecto_y_quita_repetidas(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "maestro.xlsx")
            pd.DataFrame([
                {"cuenta_id": "1", "titular": "a", "tipo": "x", "limite_monto": None, "estado": "Activa"},
                {"cuenta_id": "1", "titular": "b", "tipo": "x", "limite_monto": 50, "estado": "Activa"},
            ]).to_excel(ruta, index=False)
            maestro = leer_maestro(ruta, limite_por_defecto=777)
            self.assertEqual(len(maestro), 1)
            self.assertEqual(maestro.iloc[0]["limite_monto"], 777)

    def test_enriquecer_marca_cuentas_fuera_del_maestro(self):
        df = armar_df([(1, "2026-09-08 01:40", "800002", "Deposit", 10.0),
                       (2, "2026-09-08 01:41", "800011", "Deposit", 10.0)])
        self.assertTrue(df.iloc[0]["en_maestro"])
        self.assertFalse(df.iloc[1]["en_maestro"])
        self.assertEqual(df.iloc[0]["titular"], "John Smith")


class TestReglasNegocio(unittest.TestCase):
    def aplicar(self, filas):
        df, conteo = aplicar_reglas(armar_df(filas))
        return df, conteo

    def test_movimiento_normal_queda_ok(self):
        df, _ = self.aplicar([(1, "2026-09-08 01:40", "800002", "Deposit", 100.0)])
        self.assertEqual(df.iloc[0]["estado"], "OK")

    def test_cuenta_fuera_del_maestro_es_observacion_informativa(self):
        df, _ = self.aplicar([(1, "2026-09-08 01:40", "800011", "Deposit", 100.0)])
        self.assertEqual(df.iloc[0]["estado"], "OK")
        self.assertIn("cuenta no registrada en el maestro", df.iloc[0]["observaciones"])
        self.assertEqual(reglas_de(df), [])

    def test_cuenta_inactiva(self):
        df, _ = self.aplicar([(1, "2026-09-08 01:40", "800009", "Deposit", 100.0)])
        self.assertIn("cuenta inactiva en el maestro", reglas_de(df))

    def test_monto_sobre_el_limite_de_la_cuenta(self):
        # 800003 tiene limite 5000; 800002 tiene 10000
        df, _ = self.aplicar([(1, "2026-09-08 01:40", "800003", "Deposit", 6000.0),
                              (2, "2026-09-08 01:41", "800002", "Deposit", 6000.0)])
        self.assertIn("monto sobre el limite", reglas_de(df, 0))
        self.assertNotIn("monto sobre el limite", reglas_de(df, 1))

    def test_monto_en_cero(self):
        df, _ = self.aplicar([(1, "2026-09-08 01:40", "800002", "Deposit", 0.0)])
        self.assertIn("monto en cero", reglas_de(df))

    def test_signo_no_coincide_con_la_accion(self):
        df, _ = self.aplicar([(1, "2026-09-08 01:40", "800002", "Deposit", -1000.0),
                              (2, "2026-09-08 01:41", "800002", "Withdrawal", 1000.0),
                              (3, "2026-09-08 01:42", "800002", "Withdrawal", -1000.0)])
        self.assertIn("signo no coincide con la accion", reglas_de(df, 0))
        self.assertIn("signo no coincide con la accion", reglas_de(df, 1))
        self.assertEqual(reglas_de(df, 2), [])

    def test_fecha_futura(self):
        df, _ = self.aplicar([(1, "2999-01-01 10:00", "800002", "Deposit", 10.0)])
        self.assertIn("fecha futura", reglas_de(df))

    def test_solo_id_duplicado_se_marca_como_duplicado(self):
        df, _ = self.aplicar([(7, "2026-09-08 01:40", "800002", "Deposit", 10.0),
                              (7, "2026-09-08 01:41", "800002", "Deposit", 20.0),
                              (8, "2026-09-08 01:42", "800003", "Deposit", 30.0),
                              (9, "2026-09-08 01:42", "800003", "Deposit", 30.0)])
        self.assertIn("id de transaccion duplicado", reglas_de(df, 0))
        self.assertEqual(reglas_de(df, 2), [])
        self.assertEqual(reglas_de(df, 3), [])

    def test_cada_error_trae_su_sugerencia(self):
        df, _ = self.aplicar([(1, "2026-09-08 01:40", "800002", "Deposit", -5.0)])
        self.assertIn("Revisar el signo", df.iloc[0]["sugerencia"])

    def test_conteo_por_regla(self):
        _, conteo = self.aplicar([(1, "2026-09-08 01:40", "800011", "Deposit", 5.0),
                                  (2, "2026-09-08 01:41", "800011", "Deposit", 6.0)])
        self.assertEqual(conteo, {})

    def test_100_movimientos_con_maestro_incompleto_no_se_marcan_todos(self):
        filas = []
        cuentas = ["800011", "800020", "800021"]
        for indice in range(100):
            filas.append({
                "id_transaccion": str(1000 + indice),
                "fecha": "2026-09-08 01:40",
                "cuenta_id": cuentas[indice % len(cuentas)] if indice < 88 else "800002",
                "accion": "Deposit",
                "monto_num": 6000.0 if indice < 4 else 10.0,
            })
        df = enriquecer_con_maestro(pd.DataFrame(filas), MAESTRO_PRUEBA)

        resultado, conteo = aplicar_reglas(df)

        self.assertEqual(int((resultado["estado"] == "REVISAR").sum()), 4)
        self.assertEqual(int(resultado["observaciones"].str.contains(
            "cuenta no registrada en el maestro"
        ).sum()), 88)
        self.assertEqual(conteo, {"monto sobre el limite": 4})


class TestExcel(unittest.TestCase):
    def test_guarda_todas_las_hojas(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "reporte.xlsx")
            guardar_excel({"Antes": pd.DataFrame({"a": [1]}), "Despues": pd.DataFrame({"monto_num": [1.5]})}, ruta)
            with pd.ExcelFile(ruta) as xls:
                hojas = xls.sheet_names
            self.assertEqual(hojas, ["Antes", "Despues"])


class TestHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidor = HTTPServer(("127.0.0.1", 0), ServidorFalso)
        cls.base = f"http://127.0.0.1:{cls.servidor.server_port}"
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()
        cliente_http.HTTPBIN_URL = cls.base
        cliente_http.RANDOMUSER_URL = cls.base + "/ru/"
        cliente_http.TESTFIRE_API_URL = cls.base + "/api"
        cliente_http.PAUSA_REINTENTO = 0
        cliente_http.TIMEOUT = 3

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()

    def setUp(self):
        cliente_http.EVIDENCIA.clear()
        ServidorFalso.visitas.clear()
        ServidorFalso.login_con_token = True

    def test_los_5_metodos_responden_200(self):
        for metodo in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            r = cliente_http.llamar(metodo, self.base + "/x", json_body={"dato": 1} if metodo != "GET" else None)
            self.assertEqual(r.status_code, 200, metodo)
            self.assertEqual(r.json()["metodo"], metodo)

    def test_json_enviado_llega_al_servidor(self):
        r = cliente_http.llamar("POST", self.base + "/post", json_body={"hola": "mundo"})
        self.assertEqual(r.json()["recibido"], {"hola": "mundo"})

    def test_404_no_se_reintenta(self):
        r = cliente_http.llamar("GET", self.base + "/status/404")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(ServidorFalso.visitas["/status/404"], 1)

    def test_500_se_reintenta_3_veces(self):
        r = cliente_http.llamar("GET", self.base + "/status/500")
        self.assertEqual(r.status_code, 500)
        self.assertEqual(ServidorFalso.visitas["/status/500"], 3)

    def test_servidor_caido_devuelve_none(self):
        r = cliente_http.llamar("GET", "http://127.0.0.1:1/nada")
        self.assertIsNone(r)

    def test_clasificar_estado(self):
        self.assertEqual(cliente_http.clasificar_estado(200), "OK")
        self.assertEqual(cliente_http.clasificar_estado(404), "ERROR DEL CLIENTE")
        self.assertEqual(cliente_http.clasificar_estado(500), "ERROR DEL SERVIDOR")

    def test_evidencia_oculta_password_y_token(self):
        cliente_http.llamar("POST", self.base + "/api/login", json_body={"username": "jsmith", "password": "secreta"})
        cliente_http.llamar("GET", self.base + "/api/account", headers={"Authorization": "token123456789"})
        texto = json.dumps(cliente_http.EVIDENCIA)
        self.assertNotIn("secreta", texto)
        self.assertNotIn("token123456789", texto)
        self.assertEqual(cliente_http.EVIDENCIA[0]["json_enviado"]["password"], "****")

    def test_randomuser_ok_y_respaldo(self):
        personas = cliente_http.obtener_beneficiarios(2)
        self.assertEqual([p["nombre"] for p in personas], ["Ana Lopez", "Bob Stone"])
        self.assertEqual(personas[0]["fuente"], "randomuser.me")

        cliente_http.RANDOMUSER_URL = self.base + "/ru_malo/"
        respaldo = cliente_http.obtener_beneficiarios(3)
        self.assertEqual(len(respaldo), 3)
        self.assertEqual(respaldo[0]["fuente"], "respaldo local")
        cliente_http.RANDOMUSER_URL = self.base + "/ru/"

    def test_demo_metodos_devuelve_los_estados_esperados(self):
        resultados = cliente_http.demo_metodos_http()
        self.assertEqual([r["status"] for r in resultados], [200, 200, 200, 200, 200, 404, 500])
        self.assertEqual(resultados[-1]["clasificacion"], "ERROR DEL SERVIDOR")

    def test_webhook_devuelve_200(self):
        self.assertEqual(cliente_http.registrar_log_webhook({"ok": 1}), 200)

    def test_api_testfire_flujo_completo(self):
        api = cliente_http.api_testfire("jsmith", "demo1234")
        self.assertEqual(api["login_status"], 200)
        self.assertTrue(api["token_ok"])
        self.assertEqual(api["sin_token_status"], 401)
        self.assertEqual(api["cuentas_status"], 200)
        self.assertEqual(api["n_cuentas"], 1)
        self.assertEqual(api["cuenta_usada"], "800002")
        self.assertEqual(api["tx_status"], 200)
        self.assertEqual(api["n_tx_api"], 3)

    def test_api_testfire_sin_token_no_sigue(self):
        ServidorFalso.login_con_token = False
        api = cliente_http.api_testfire("jsmith", "demo1234")
        self.assertFalse(api["token_ok"])
        self.assertNotIn("/api/account", ServidorFalso.visitas)


class TestAPIAlertaVercel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidor = HTTPServer(("127.0.0.1", 0), api_alerta.handler)
        cls.base = f"http://127.0.0.1:{cls.servidor.server_port}/api/alerta"
        cls.hilo = threading.Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.hilo.start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()

    def setUp(self):
        self.variables = patch.dict(os.environ, {
            "ALERT_API_SECRET": "s" * 43,
        }, clear=True)
        self.variables.start()
        self.addCleanup(self.variables.stop)

    def post(self, movimientos, secreto="s" * 43):
        return requests.post(
            self.base,
            json={"movimientos": movimientos},
            headers={"Authorization": f"Bearer {secreto}"},
            timeout=3,
        )

    def test_sin_autorizacion_no_genera_reporte(self):
        respuesta = self.post([{"estado": "REVISAR"}], secreto="incorrecto")
        self.assertEqual(respuesta.status_code, 401)

    def test_fila_ok_devuelve_csv(self):
        respuesta = self.post([{
            "id_transaccion": "1", "monto_num": 12.5, "estado": "OK",
        }])
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.headers["Content-Type"].startswith("text/csv"))
        self.assertNotIn("X-Alert-Email", respuesta.headers)
        self.assertIn(b"id_transaccion", respuesta.content)
        self.assertIn(b"observaciones", respuesta.content)

    def test_fila_revisar_devuelve_csv_sin_configuracion_de_correo(self):
        respuesta = self.post([{
            "id_transaccion": "2", "estado": "REVISAR",
            "errores_negocio": "cuenta no registrada en el maestro",
        }])
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotIn("X-Alert-Email", respuesta.headers)
        self.assertIn(b"cuenta no registrada en el maestro", respuesta.content)

    def test_estado_invalido_se_rechaza(self):
        respuesta = self.post([{"estado": "OTRO"}])
        self.assertEqual(respuesta.status_code, 400)

    def test_csv_escapa_contenido_que_podria_ser_formula(self):
        contenido = api_alerta.generar_csv([{
            "titular": "=1+1", "estado": "REVISAR",
        }])
        self.assertIn(b"'=1+1", contenido)

class TestClienteVercel(unittest.TestCase):
    def test_guarda_csv_local_para_el_panel(self):
        df = pd.DataFrame([{
            "id_transaccion": "1",
            "titular": "=formula",
            "monto_num": 12.5,
            "estado": "REVISAR",
        }])
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "reporte.csv")
            guardado = alertas_vercel.guardar_reporte_csv_local(df, ruta)
            with open(ruta, "rb") as archivo:
                contenido = archivo.read()

        self.assertEqual(guardado, ruta)
        self.assertIn(b"'=formula", contenido)
        self.assertIn(b"REVISAR", contenido)

    def test_main_no_abre_el_panel_ni_carga_el_csv_automaticamente(self):
        with patch.object(robot_ep2, "obtener_beneficiarios", return_value=[]), \
                patch.object(robot_ep2, "fase_web", return_value={"movimientos": []}), \
                patch.object(robot_ep2, "fase_datos") as fase_datos, \
                patch.object(robot_ep2, "iniciar_driver") as iniciar_driver:
            robot_ep2.main()

        fase_datos.assert_called_once()
        iniciar_driver.assert_not_called()

    def test_sin_configuracion_mantiene_el_modo_local(self):
        with patch.dict(os.environ, {}, clear=True), tempfile.TemporaryDirectory() as carpeta:
            resultado = alertas_vercel.enviar_reporte_vercel(
                pd.DataFrame([{"estado": "REVISAR"}]),
                os.path.join(carpeta, "reporte.csv"),
            )
        self.assertEqual(resultado["estado"], "desactivado")
        self.assertIsNone(resultado["ruta_csv"])

    def test_envia_filas_y_guarda_el_csv_de_respuesta(self):
        respuesta = requests.Response()
        respuesta.status_code = 200
        respuesta.headers["Content-Type"] = "text/csv; charset=utf-8"
        respuesta._content = b"id_transaccion,estado\n1,REVISAR\n"
        df = pd.DataFrame([{
            "id_transaccion": "1", "fecha": pd.Timestamp("2026-09-08"),
            "monto_num": -12.5, "estado": "REVISAR",
        }])

        with patch.dict(os.environ, {
            "VERCEL_ALERT_URL": "https://ev2.example/api/alerta",
            "VERCEL_ALERT_SECRET": "secreto-local",
        }), patch("alertas_vercel.requests.post", return_value=respuesta) as post, \
                tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "reporte.csv")
            resultado = alertas_vercel.enviar_reporte_vercel(df, ruta)
            with open(ruta, "rb") as archivo:
                contenido = archivo.read()

        enviado = post.call_args.kwargs
        self.assertEqual(enviado["headers"]["Authorization"], "Bearer secreto-local")
        self.assertEqual(enviado["json"]["movimientos"][0]["estado"], "REVISAR")
        self.assertEqual(enviado["json"]["movimientos"][0]["fecha"], "2026-09-08T00:00:00.000")
        self.assertEqual(resultado["estado"], "generado")
        self.assertEqual(contenido, respuesta.content)

    def test_fase_datos_guarda_csv_local_despues_de_los_reportes(self):
        web = {
            "movimientos": [{
                "id_transaccion": "1", "fecha": "2026-09-08 01:40",
                "cuenta_id": "800011", "accion": "Deposit", "monto": "$10.00",
                "descripcion": "Deposit cuenta 800011",
            }],
            "tecnicas": {"ms_selenium": 1, "ms_dom": 1},
            "localizadores": pd.DataFrame(),
            "transfer_ok": True, "feedback_ok": True, "alertas": [],
        }
        with patch.object(robot_ep2, "leer_maestro", return_value=MAESTRO_PRUEBA), \
                patch.object(robot_ep2, "guardar_excel", side_effect=lambda hojas, ruta: ruta), \
                patch.object(robot_ep2, "graficar_dispersion", return_value="grafico.png"), \
                patch.object(robot_ep2, "guardar_reporte_csv_local") as guardar_csv, \
                patch.object(robot_ep2, "api_testfire", return_value={
                    "login_status": 200, "sin_token_status": 401, "tx_status": 200,
                    "n_tx_api": 1,
                }), \
                patch.object(robot_ep2, "demo_metodos_http", return_value=[]), \
                patch.object(robot_ep2, "registrar_log_webhook", return_value=200), \
                patch.object(robot_ep2, "guardar_evidencia"), \
                patch.object(robot_ep2, "resumen_evidencia", return_value=[]):
            robot_ep2.fase_datos(web, [{"fuente": "respaldo local"}], time.time())

        filas_guardadas = guardar_csv.call_args.args[0]
        self.assertEqual(filas_guardadas.iloc[0]["estado"], "OK")
        self.assertIn("cuenta no registrada en el maestro", filas_guardadas.iloc[0]["observaciones"])
        self.assertTrue(guardar_csv.call_args.args[1].endswith(".csv"))


class TestXPathSobreHTMLGuardado(unittest.TestCase):
    """Prueba los localizadores sobre el HTML real que guardo el robot (no necesita navegador)."""

    def buscar_html(self):
        ruta = os.environ.get("HTML_TRANSACCIONES")
        if ruta:
            return ruta
        archivos = sorted(glob.glob(os.path.join(robot_ep2.OUTPUT_DIR, "pagina_transacciones_*.html")))
        return archivos[-1] if archivos else None

    def test_localizadores_robustos_encuentran_una_sola_tabla(self):
        try:
            from lxml import html
        except ImportError:
            self.skipTest("falta lxml (pip install lxml)")
        ruta = self.buscar_html()
        if ruta is None:
            self.skipTest("todavia no hay un pagina_transacciones_*.html en output/")

        arbol = html.parse(ruta)
        robustos = [robot_ep2.LOCALIZADORES[1][2], robot_ep2.LOCALIZADORES[2][2]]
        for xpath in robustos:
            tablas = arbol.xpath(xpath)
            self.assertEqual(len(tablas), 1, xpath)
            self.assertIn("Transaction ID", tablas[0].text_content())


class _SinAlerta:
    @property
    def alert(self):
        raise NoAlertPresentException()


class _AlertaAbierta:
    def __init__(self):
        self.cerrada = False
        self.text = "107"

    def accept(self):
        self.cerrada = True


class _ConAlerta:
    def __init__(self):
        self.alert = _AlertaAbierta()


class NavegadorFalso:
    def __init__(self, switch_to):
        self.switch_to = switch_to


class ElementoFalso:
    def __init__(self):
        self.acciones = []

    def click(self):
        self.acciones.append("click")

    def clear(self):
        self.acciones.append("clear")

    def send_keys(self, texto):
        self.acciones.append(("send_keys", texto))


class TestAlertasJavaScript(unittest.TestCase):
    """El sitio abre un alert (texto 107) al cargar Transfer Funds. El robot tiene que seguir."""

    def setUp(self):
        robot_ep2.ALERTAS.clear()
        self.esperar_original = robot_ep2.esperar

    def tearDown(self):
        robot_ep2.esperar = self.esperar_original

    def test_anotar_alerta_cierra_y_guarda_el_texto(self):
        navegador = NavegadorFalso(_ConAlerta())
        robot_ep2.anotar_alerta(navegador, "transfer", UnexpectedAlertPresentException("x", alert_text="107"))
        self.assertTrue(navegador.switch_to.alert.cerrada)
        self.assertEqual(robot_ep2.ALERTAS, [{"paso": "transfer", "texto": "107"}])

    def test_si_el_navegador_ya_cerro_el_alert_igual_se_anota(self):
        navegador = NavegadorFalso(_SinAlerta())
        robot_ep2.anotar_alerta(navegador, "transfer", UnexpectedAlertPresentException("x", alert_text="107"))
        self.assertEqual(robot_ep2.ALERTAS[0]["texto"], "107")

    def test_esperar_cerrando_alertas_reintenta_y_encuentra(self):
        llamadas = []

        def esperar_falso(driver, by, valor, timeout=20):
            llamadas.append(valor)
            if len(llamadas) == 1:
                raise UnexpectedAlertPresentException("x", alert_text="107")
            return "ELEMENTO"

        robot_ep2.esperar = esperar_falso
        resultado = robot_ep2.esperar_cerrando_alertas(NavegadorFalso(_SinAlerta()), "name", "transferAmount", "transfer")
        self.assertEqual(resultado, "ELEMENTO")
        self.assertEqual(len(llamadas), 2)
        self.assertEqual(len(robot_ep2.ALERTAS), 1)

    def test_si_los_alerts_no_paran_termina_con_timeout(self):
        def esperar_falso(driver, by, valor, timeout=20):
            raise UnexpectedAlertPresentException("x", alert_text="107")

        robot_ep2.esperar = esperar_falso
        with self.assertRaises(TimeoutException):
            robot_ep2.esperar_cerrando_alertas(NavegadorFalso(_SinAlerta()), "name", "x", "transfer")
        self.assertEqual(len(robot_ep2.ALERTAS), 5)

    def test_cargar_transferencia_sobrevive_al_alert(self):
        enlace, campo = ElementoFalso(), ElementoFalso()
        llamadas = []

        def esperar_falso(driver, by, valor, timeout=20):
            llamadas.append(valor)
            if valor == "Transfer Funds":
                return enlace
            if len(llamadas) == 2:   # el alert aparece justo al buscar el campo (igual que en el log real)
                raise UnexpectedAlertPresentException("unexpected alert open", alert_text="107")
            return campo

        robot_ep2.esperar = esperar_falso
        ok = robot_ep2.cargar_transferencia(NavegadorFalso(_SinAlerta()), monto="10")
        self.assertTrue(ok)
        self.assertEqual(enlace.acciones, ["click"])
        self.assertEqual(campo.acciones, ["clear", ("send_keys", "10")])
        self.assertEqual(robot_ep2.ALERTAS[0]["texto"], "107")


if __name__ == "__main__":
    unittest.main(verbosity=2)
