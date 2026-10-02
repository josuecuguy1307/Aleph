# Belt OFICINA — OpenWork + OfficeCLI + gws

## Manos locales

`third_party/officecli/bin/officecli-macos-arm64` se registra en el runtime
de OpenWork como MCP **stdio** con `args: ["mcp"]`. El proceso recibe siempre
`OFFICECLI_SKIP_UPDATE=1` y `OFFICECLI_NO_AUTO_INSTALL=1`: no consulta
releases, no se copia al PATH y no registra MCPs ni skills en otros clientes.
La muestra lista de configuración es
`third_party/openwork/config/aleph-oficina.runtime.example.json`.

## Manos Google, por usuario

`third_party/gws/bin/gws-macos-arm64` se usa sólo tras resolver
`keys:google_workspace` con `credential_broker.make_user_resolver(user_id)`.
El broker inyecta un access token efímero en `GOOGLE_WORKSPACE_CLI_TOKEN` al
subproceso del usuario; no se usa el almacén de gws ni credenciales de la
máquina. Las skills admitidas son exactamente Gmail, Calendar, Docs y Sheets.

Scopes mínimos por función: Gmail lectura/borrador (`gmail.readonly`,
`gmail.compose`); Calendar lectura (`calendar.events.readonly`) o creación
(`calendar.events`); Docs (`documents`); Sheets (`spreadsheets`). Solicitar
sólo el grupo que el usuario conecta. Envío de correo, borrado y creación o
modificación de eventos se mantienen HELD hasta confirmación explícita según
Ó11 / SEND-GATE-FIRST; no se incluyen como acciones autoejecutables.

## Orden de arranque del cerebro

1. Arrancar el motor OpenCode.
2. `PATCH /runtime-config/providers` con el bloque `aleph` de la muestra.
3. Esperar el reload y seleccionar `aleph/aleph-brain`.

El orden es intencional: el PATCH persiste el provider, pero si el motor no
está arriba el reload devuelve `opencode_unconfigured`; no se debe confundir
esa falla posterior con una escritura perdida.
