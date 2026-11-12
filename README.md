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

Para validar cambios sin Selenium ni enviar correos reales, ejecuta:

```powershell
py test_logica_offline.py
```
