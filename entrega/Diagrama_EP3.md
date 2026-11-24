# Flujo del robot EP3

```mermaid
flowchart TD
    A([Inicio]) --> B[Confirmar sesión en TestFire]
    B --> C[Leer tabla de movimientos]
    C --> D[Consultar RandomUser y validar JSON]
    D --> E[Validar formato, cruzar maestro y aplicar reglas]
    E --> F[Guardar y reabrir Excel]
    F --> G{¿Envío habilitado y excepciones?}
    G -- No --> L([Registrar éxito y avisar por Telegram])
    G -- Sí --> H{Reservar huella en SQLite}
    H -- Ya aceptada --> L
    H -- Pendiente --> M([Registrar envío pendiente y avisar por Telegram])
    H -- Nueva --> I[Entregar adjunto HTTPS a Vercel]
    I --> J[Enviar Excel por Gmail]
    J -- Envío aceptado --> K[Marcar aceptado y registrar acuse]
    K --> L
    J -- Error o resultado incierto --> M
    B -. Error de conexión tras tres intentos .-> N([Registrar fallo y avisar por Telegram])
    C -. Error .-> N
    D -. Error .-> N
    F -. Error .-> N
```
