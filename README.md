# EV2: robot local y panel de informes en Vercel

El robot Selenium sigue ejecutandose en el PC del usuario. Desplegar esta carpeta
en Vercel publica una pagina web (`/`) para analizar y consolidar informes. La
funcion `POST /api/alerta` valida movimientos y devuelve un CSV descargable; no
envia correos ni almacena informes.

## Desplegar la API

1. Importa el repositorio en Vercel y deja **Root Directory** en la raiz del
   repositorio (`./`), donde estan `index.html` y `api/alerta.py`. La funcion
   Python se detecta desde `api/alerta.py`.
2. En **Settings > Environment Variables**, agrega `ALERT_API_SECRET`: secreto
   aleatorio compartido con el robot.
3. Genera un valor largo y aleatorio para `ALERT_API_SECRET` (por ejemplo,
   `py -c "import secrets; print(secrets.token_urlsafe(32))"`), guardalo como
   variable de entorno en Vercel y vuelve a desplegar. La API exige un secreto
   de al menos 32 caracteres. No lo escribas en el
   codigo ni lo compartas en archivos versionados.
4. Copia la URL desplegada. Abre `https://tu-proyecto.vercel.app/` para usar la
   pagina de prueba o `https://tu-proyecto.vercel.app/api/alerta` para la API.

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
publica los movimientos analizados en la API y guarda el CSV devuelto como
`output/Reporte_Alerta_Vercel_<fecha>.csv`. Después puedes cargar ese CSV en el
panel de Vercel para consultar sus gráficos y hallazgos. Sin ambas variables el
robot sigue funcionando en local, sin conectarse a Vercel. Si la publicación
falla, registra el error y conserva los reportes locales.

## Contrato de la API

La solicitud requiere `Authorization: Bearer <ALERT_API_SECRET>` y un JSON con
`movimientos`, lista de filas que incluya `estado` (`OK` o `REVISAR`). La
respuesta exitosa es `text/csv`. Se aceptan hasta 5000 filas por llamada.
El cuerpo de cada solicitud tiene un límite de 1 MB; los lotes grandes pueden
revisarse directamente en el panel, que procesa los archivos en el navegador.

El panel acepta uno o varios CSV del robot o archivos JSON, o permite
pegar/editar el JSON. Los informes seleccionados se consolidan en un resumen
general en el navegador, con su nombre de archivo visible en las tablas.
**Generar CSV en Vercel** es opcional: solicita el secreto en ese momento, lo
usa solo para esa llamada y descarga el CSV de la API. Para el flujo habitual,
el robot local llama directamente a la API con sus variables de entorno.

## Panel general de informes

Al cargar varios archivos, el panel muestra en el navegador un resumen de los
movimientos, montos netos, cuentas involucradas, graficos de estados y motivos,
una tabla filtrable y una lista de hallazgos. El analisis es local: no requiere
el secreto ni transmite los datos. Considera los errores informados por el
robot y replica comprobaciones visibles de las reglas de negocio (por ejemplo,
duplicados, cuentas no registradas, montos fuera de limite y signos
incompatibles).
Estos hallazgos solo se muestran en el panel y no reescriben los valores
recibidos. Los archivos se procesan solo en la sesión actual del navegador; no
se guardan en Vercel ni se comparten entre usuarios o dispositivos porque el
proyecto no cuenta con una base de datos configurada. La API solo valida y
genera CSV; toda la revisión de informes se hace en esta página.

Para validar cambios sin Selenium, ejecuta:

```powershell
& .\.venv\Scripts\python.exe .\test_logica_offline.py
```
