# EP3 · Robot de revisión de movimientos

El robot ejecuta Selenium en Windows para leer movimientos del sitio de demostración TestFire. Consulta RandomUser como referencia externa, cruza los movimientos con el maestro de cuentas y abre o valida el reporte Excel. Con el envío habilitado, Vercel envía por Gmail un Excel que contiene solo las excepciones. El panel de Vercel analiza el CSV en el navegador.

## Ejecutar

Con Python 3.12 o superior y Chrome instalados, desde PowerShell:

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements-robot.txt
& .\.venv\Scripts\python.exe .\robot_ep3.py --demo --sin-api --sin-panel
& .\.venv\Scripts\python.exe .\test_ep3.py
& .\.venv\Scripts\python.exe .\robot_ep3.py --abrir-excel
```

- `--demo` usa cuatro movimientos sintéticos y consulta RandomUser. Añade `--sin-api` para una prueba sin red.
- La ejecución normal inicia sesión en la cuenta pública de demostración de TestFire. Usa únicamente datos del caso de laboratorio. ChromeDriver se administra con Selenium Manager.
- Cada ejecución crea una carpeta en `output/` con log, Excel, CSV para el panel, referencia JSON cuando está disponible y capturas de TestFire cuando se ejecuta el login. El contenido de `output/` es local y está excluido de Git.
- El Excel completo contiene `Antes`, `Despues`, `Referencia_API`, `Excepciones` y `Rechazados`. `Revision_EP3.xlsx` solo contiene las columnas necesarias para decidir qué revisar. Carga `panel_EP3.csv` en el panel para ver las excepciones y motivos.

## Cuando TestFire no responde

EP3 reintenta dos veces ante errores de conexión de Chrome, con pausas de 2 y 5 segundos. Si la fuente sigue sin responder, el robot registra el código de red, termina con un código de error y conserva los reportes de ejecuciones previas. En esa ejecución no genera reportes nuevos ni solicita correo. El log queda en `output/<ejecución>/ejecucion.log`.

Puedes consultar un reporte histórico con `--solo-panel` o practicar con `--demo --sin-api --sin-panel`. La demo usa movimientos sintéticos y no permite enviar correos.

## Avisos de ejecución por Telegram

Crea un bot con [@BotFather](https://t.me/BotFather), abre el chat del bot y pulsa Iniciar. Desde PowerShell, ejecuta `& .\configurar_telegram_ep3.ps1` y pega el token cuando lo pida. El asistente obtiene el identificador del chat y guarda `EP3_TELEGRAM_TOKEN` y `EP3_TELEGRAM_CHAT_ID` para tu usuario de Windows. Abre una nueva consola antes de ejecutar EP3.

El robot envía un aviso de estado al terminar una ejecución normal, incluidas las caídas persistentes de TestFire. El mensaje incluye el identificador de ejecución y el total para revisar cuando el proceso termina correctamente. Telegram no recibe el Excel ni los datos de los movimientos. Si el aviso falla, el log lo indica y el código de salida de EP3 se conserva. La demo no envía avisos.

## Revisar en Vercel y elegir destinatarios

Al ejecutar `python robot_ep3.py`, el robot genera los reportes, abre el panel de Vercel en Chrome y carga `panel_EP3.csv`. El panel calcula los indicadores, gráficos y excepciones. El CSV reúne todos los movimientos válidos, por lo que alcanza para alimentar tanto el resumen como la lista de revisión.

Revisa los datos en la ventana que abre el robot. En la sección de seguimiento escribe los destinatarios y pulsa **Abrir borrador de correo**. La aplicación de correo predeterminada abre el borrador para que confirmes el envío. Si necesitas adjuntar el Excel, elige `Revision_EP3.xlsx` de esa ejecución. Usa el flujo normal sin `--enviar` para elegir los destinatarios después de revisar.

El panel conserva el último CSV en el perfil de Chrome del robot. Puedes recargar la página en esa ventana o borrar el informe mediante el botón del panel. Para reabrirlo con un CSV existente, ejecuta `python robot_ep3.py --solo-panel "output/<ejecución>/panel_EP3.csv"`. El informe permanece en ese perfil de este equipo. `--sin-panel` permite generar los archivos sin abrir Vercel.

## Habilitar Gmail desde Vercel

En Settings → Environment Variables, configura `GMAIL_FROM` con el correo Gmail emisor, `GMAIL_REVIEW_TO` con el destinatario y `GMAIL_APP_PASSWORD` con una contraseña de aplicación de Google. El emisor requiere [verificación en dos pasos y una contraseña de aplicación](https://support.google.com/accounts/answer/185833?hl=es). Guarda la contraseña como variable sensible y vuelve a desplegar el proyecto.

Mantén `ALERT_API_SECRET` en Vercel y usa el mismo valor como `VERCEL_ALERT_SECRET` en Windows. `VERCEL_OUTLOOK_URL` sigue apuntando a `/api/outlook`. Ejecuta el robot con `--enviar` para enviar `Revision_EP3.xlsx` si hay excepciones. Revisa el correo en Gmail para confirmar la entrega.

La primera ejecución con excepciones reserva una huella en `output/alertas_ep3.sqlite`. Si el servicio acepta el envío, se guarda `aceptado`. Si falla o hay incertidumbre, queda `pendiente` y el robot bloquea el envío repetido. Para recuperar una ejecución pendiente, verifica primero la carpeta Enviados de Gmail o la recepción del mensaje. Si compruebas que el correo no se aceptó, corrige la causa y libera únicamente el registro pendiente con `DELETE FROM alertas WHERE huella = ? AND estado = 'pendiente'`, usando la huella que muestra el robot. Conserva esta base entre ejecuciones.

- [RandomUser](https://randomuser.me/documentation)

## Evaluación

El informe, la presentación y las evidencias compartibles están en [entrega](entrega). El flujo anterior de EV2 por Resend sigue disponible en `/api/alerta` y conserva su configuración.


# EV2: robot local y alertas en Vercel

El robot Selenium sigue ejecutandose en el PC del usuario. Desplegar esta carpeta
en Vercel publica una pagina web (`/`) para probar la API y la funcion
`POST /api/alerta`: recibe movimientos que el robot ya analizo, devuelve un CSV
descargable y envia un correo con ese reporte unicamente cuando existe al menos
una fila con estado `REVISAR`.

## Desplegar la API

1. Importa el repositorio en Vercel y deja **Root Directory** en la raiz del
   repositorio (`./`), donde estan `index.html` y `api/alerta.py`. La funcion
   Python se detecta desde `api/alerta.py`.
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

## Preparar y ejecutar el robot local

El robot automatiza el sitio de demostración `https://demo.testfire.net/`.
Selenium abre Chrome en tu PC, inicia sesión con la cuenta de demostración,
lee la tabla de transacciones y genera reportes Excel. No se ejecuta en Vercel.

Con Python 3.12 o posterior y Google Chrome instalado, abre PowerShell en la
carpeta del repositorio y prepara el entorno aislado:

```powershell
py -3.14 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements-robot.txt
```

Si tu Python tiene otra versión compatible, sustituye `-3.14` por la versión
instalada. Selenium Manager administra el controlador de Chrome al iniciar el
navegador; la primera ejecución requiere conexión a internet.
Las dependencias del robot están en `requirements-robot.txt` para que Vercel no
las instale dentro de la función API, que no las necesita.

Para publicar el resultado en Vercel, configura en la misma ventana de
PowerShell la URL `/api/alerta` del proyecto y el mismo secreto que `ALERT_API_SECRET`
en Vercel:

```powershell
$env:VERCEL_ALERT_URL = "https://tu-proyecto.vercel.app/api/alerta"
$env:VERCEL_ALERT_SECRET = "el-mismo-secreto-configurado-en-vercel"
& .\.venv\Scripts\python.exe .\robot_ep2.py
```

El robot conserva sus reportes Excel en `output` y, si Vercel está configurado,
envía directamente los movimientos analizados a la API y guarda el CSV devuelto
como `output/Reporte_Alerta_Vercel_<fecha>.csv`. Después puedes cargar ese CSV
en el panel de Vercel para consultar sus gráficos y hallazgos. Sin ambas
variables el robot sigue funcionando en local, sin conectarse a Vercel. Si el
envío falla, registra el error y conserva los reportes locales.

## Contrato de la API

La solicitud requiere `Authorization: Bearer <ALERT_API_SECRET>` y un JSON con
`movimientos`, lista de filas que incluya `estado` (`OK` o `REVISAR`). La
respuesta exitosa es `text/csv`; `X-Alert-Email` indica `enviado` o
`no_requerido`. Se aceptan hasta 5000 filas por llamada. No se envia correo si
ninguna fila esta marcada `REVISAR`.

El panel acepta el CSV generado por el robot o un archivo JSON, o permite
pegar/editar el JSON. **Analizar informe** presenta los datos en el navegador
sin enviarlos. **Generar CSV en Vercel** es opcional: solicita el secreto en ese
momento, lo usa solo para esa llamada y descarga el CSV de la API. Para el flujo
habitual, el robot local llama directamente a la API con sus variables de
entorno.

## Panel de resumen y seguimiento

Usa **Analizar informe** para mostrar en el navegador un resumen de los
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
& .\.venv\Scripts\python.exe .\test_logica_offline.py
```
