# EV2: robot local y alertas en Vercel

El robot Selenium sigue ejecutandose en el PC del usuario. Desplegar esta carpeta
en Vercel publica una pagina web (`/`) para probar la API y la funcion
`POST /api/alerta`: recibe movimientos que el robot ya analizo, devuelve un CSV
descargable y envia un correo con ese reporte unicamente cuando existe al menos
una fila con estado `REVISAR`.

## Desplegar la API

1. Importa el repositorio en Vercel y selecciona `OneDrive/Escritorio/ev2`
   como **Root Directory**. La funcion Python se detecta desde `api/alerta.py`.
2. En **Settings > Environment Variables**, agrega:
   - `ALERT_API_SECRET`: secreto aleatorio compartido con el robot.
   - `RESEND_API_KEY`: clave de API de Resend.
   - `ALERT_EMAIL_FROM`: remitente validado en Resend, por ejemplo
     `Alertas EV2 <alertas@tu-dominio.com>`.
   - `ALERT_EMAIL_TO`: direccion que recibira las alertas.
3. Genera un valor largo y aleatorio para `ALERT_API_SECRET` (por ejemplo,
   `py -c "import secrets; print(secrets.token_urlsafe(32))"`), guardalo como
   variable de entorno en Vercel y vuelve a desplegar. La API exige un secreto
   de al menos 32 caracteres. No lo escribas en el
   codigo ni lo compartas en archivos versionados.
4. Copia la URL desplegada. Abre `https://tu-proyecto.vercel.app/` para usar la
   pagina de prueba o `https://tu-proyecto.vercel.app/api/alerta` para la API.

Resend solo acepta remitentes de dominios que hayas verificado en su cuenta.
La funcion usa sus variables de entorno; las credenciales no se envian desde
el robot.

## Ejecutar el robot local

Instala en el entorno de Python las dependencias del robot que ya utilizas
(Selenium, Chrome, pandas, matplotlib, openpyxl y requests). En PowerShell,
configura la URL y el mismo secreto antes de ejecutar:

```powershell
$env:VERCEL_ALERT_URL = "https://tu-proyecto.vercel.app/api/alerta"
$env:VERCEL_ALERT_SECRET = "el-mismo-secreto-configurado-en-vercel"
py robot_ep2.py
```

El robot conserva sus reportes Excel y, si Vercel esta configurado, guarda
ademas `output/Reporte_Alerta_Vercel_<fecha>.csv`. Sin esas dos variables el
flujo continua solo en local y no intenta conectarse a Vercel. Si la API o el
correo fallan, se registra el error y se conservan los informes locales.

## Contrato de la API

La solicitud requiere `Authorization: Bearer <ALERT_API_SECRET>` y un JSON con
`movimientos`, lista de filas que incluya `estado` (`OK` o `REVISAR`). La
respuesta exitosa es `text/csv`; `X-Alert-Email` indica `enviado` o
`no_requerido`. Se aceptan hasta 5000 filas por llamada. No se envia correo si
ninguna fila esta marcada `REVISAR`.

La pagina de prueba permite pegar el secreto y enviar filas JSON manualmente.
No persiste el secreto; cualquier persona autorizada para usar el formulario
debe conocerlo. Para el flujo habitual, el robot local llama directamente a la
API con sus variables de entorno.

## Panel de resumen y seguimiento

Usa **Analizar datos aqui** para mostrar en el navegador un resumen de los
movimientos, montos netos, cuentas involucradas, graficos de estados y motivos,
una tabla filtrable y una lista de hallazgos. El analisis es local: no requiere
el secreto ni transmite los datos. Considera los errores informados por el
robot y replica comprobaciones visibles de las reglas de negocio (por ejemplo,
duplicados, cuentas no registradas, montos fuera de limite y signos
incompatibles).
Estos hallazgos solo se muestran en el panel y no reescriben los valores
recibidos. El endpoint de correo automatico decide si alerta segun el campo
`estado` enviado (`REVISAR`).

En **Valores para revisar**, puedes indicar uno o varios correos de socios y
una solicitud de seguimiento. **Preparar correo a socios** intenta abrir un
borrador `mailto` en la aplicacion de correo configurada en el dispositivo. El
usuario debe revisar y enviar ese mensaje; el panel no lo envia directamente y
no confirma que se haya abierto una aplicacion.

Esta opcion de borrador es distinta de las alertas automaticas del endpoint:
esas alertas solo se envian por Resend al unico `ALERT_EMAIL_TO` configurado en
Vercel cuando hay movimientos `REVISAR`. La entrega automatica a distintos
socios requiere una integracion de correo en el servidor; el borrador local no
la sustituye.

Para validar cambios sin Selenium ni enviar correos reales, ejecuta:

```powershell
py test_logica_offline.py
```
