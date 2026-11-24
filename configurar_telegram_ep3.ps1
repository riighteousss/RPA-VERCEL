$ErrorActionPreference = 'Stop'
$tokenSeguro = Read-Host 'Pega el token de BotFather' -AsSecureString
$token = [System.Net.NetworkCredential]::new('', $tokenSeguro).Password.Trim()
try {
    if ($token -notmatch '^[0-9]+:[A-Za-z0-9_-]+$') {
        throw 'El formato del token no es válido.'
    }
    $api = "https://api.telegram.org/bot$token"
    try {
        $bot = Invoke-RestMethod -Method Post -TimeoutSec 15 -Uri "$api/getMe"
    } catch {
        $respuesta = $_.Exception.Response
        if ($respuesta) {
            $codigo = [int]$respuesta.StatusCode
            if ($codigo -in 401,404) {
                throw "Telegram rechazó el token (HTTP $codigo). En @BotFather usa /mybots, selecciona tu bot y copia su API Token completo."
            }
            throw "Telegram no pudo identificar el bot (HTTP $codigo)."
        }
        throw "PowerShell no pudo conectarse a Telegram ($($_.Exception.GetType().Name))."
    }
    if (!$bot.ok -or !$bot.result.username) { throw 'Telegram no reconoció el bot.' }
    $usuarioBot = $bot.result.username
    Write-Host "Bot identificado: https://t.me/$usuarioBot"
    [void](Read-Host 'Abre ese bot, envía un mensaje privado como hola y pulsa Enter aquí')
    try {
        $consulta = Invoke-RestMethod -Method Post -TimeoutSec 15 -Uri "$api/getUpdates" -ContentType 'application/json' -Body '{"allowed_updates":["message"]}'
    } catch {
        throw 'No se pudieron leer los mensajes. Si otro servicio administra este bot, usa un bot nuevo para EP3.'
    }
    $chats = @($consulta.result | ForEach-Object {
        if ($_.message.chat.type -eq 'private') { $_.message.chat }
    } | Sort-Object -Property id -Unique)
    if ($chats.Count -eq 0) {
        throw "Telegram no devolvió mensajes privados para @$usuarioBot. Envía un mensaje nuevo al bot indicado y vuelve a ejecutar."
    }
    $chat = $chats[0]
    if ($chats.Count -gt 1) {
        for ($i = 0; $i -lt $chats.Count; $i++) {
            $opcion = $chats[$i]
            Write-Host "$($i+1). $($opcion.first_name) $($opcion.last_name) (ID $($opcion.id))"
        }
        $seleccion = 0
        if (![int]::TryParse((Read-Host 'Número del chat'), [ref]$seleccion) -or $seleccion -lt 1 -or $seleccion -gt $chats.Count) {
            throw 'Selección inválida. No se guardó ningún cambio.'
        }
        $chat = $chats[$seleccion-1]
    }
    $confirmacion = Read-Host "Chat encontrado: $($chat.first_name) $($chat.last_name) (ID $($chat.id)). Escribe SI para guardarlo"
    if ($confirmacion -ne 'SI') { return }
    [Environment]::SetEnvironmentVariable('EP3_TELEGRAM_TOKEN', $token, 'User')
    [Environment]::SetEnvironmentVariable('EP3_TELEGRAM_CHAT_ID', [string]$chat.id, 'User')
    Write-Host 'Telegram quedó configurado. Abre una nueva consola para ejecutar el robot.'
} finally {
    Remove-Variable token, tokenSeguro, api -ErrorAction SilentlyContinue
}
