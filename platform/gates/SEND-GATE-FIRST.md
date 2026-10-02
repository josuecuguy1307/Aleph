# SEND-GATE-FIRST — ley de cableado de conectores de envío

> Squad **Security** · Fase 4 / Bloque B · misión `f4-b5-send-gate-first` · 2026-06-16
> Firma: Security. Construido sobre `recipe_enforcer.py` + `approval_gate.py` (INVARIANTE §3.5).

## La regla (no negociable)

**Ningún conector de envío se cablea sin su send-gate EN EL PATH del run.**
El send-gate debe EXISTIR y estar PROBADO ANTES de exponer cualquier tool que mande afuera:
Email (`gmail.send_email`), Slack-post (`slack.post_message`), WhatsApp y cualquier futuro
canal saliente. El orden es **gate primero, conector después** — nunca al revés.

- **WhatsApp WABA espera DETRÁS del send-gate.** No se cabla el conector WhatsApp (ni
  ningún `send_*`/`dispatch_*`/`post_*`) hasta que su envío pase por el gate y se verifique
  con evidencia ejecutada (run real, marcador de breach ausente).
- El belt **DECLARA** la intención (`gates.send`, `tool_filters` que excluyen send). Security
  **HACE CUMPLIR**: `recipe_enforcer` fuerza `send` a `confirma-siempre` por CLASIFICACIÓN de
  la tool (verbo de envío), **aunque la receta omita `gates` o los ponga en `off`**. La receta
  no puede apagar el candado; solo subir el piso.
- Default **FAIL-CLOSED**: una tool desconocida que parece escribir/enviar cae a
  `confirma-siempre`. La duda nunca ejecuta sola.

## Por qué GATE-FIRST y no "cablear y después gatear"

Si el conector se cabla antes que el gate, existe una ventana donde un envío real
(correo a un tercero, post público, mensaje WhatsApp) puede salir sin OK del humano. Eso es
exactamente la clase de acción de alta consecuencia que el contrato del org manda gatear
("el agente propone, el humano aprueba"). El gate-first elimina la ventana: si no hay gate
probado en el path, el conector send **no existe** en el `tool_filters` de producción.

## Cómo se hace cumplir en el path

`recipe_assembler.assemble_and_run` construye el gate con
`recipe_enforcer.build_enforced_gate(recipe)` ANTES del loop. Si la matriz derivada no trae
los mandatorios, `build_enforced_gate` LANZA → el run devuelve `gate fail-closed` y **no se
levanta el puppet** (mejor no correr que correr sin candado). Dentro del loop, CADA tool-call
pasa por `gate.evaluate(server, tool, args)` ANTES de `registry.call`. Un verbo de envío
SIEMPRE cae a `needs_ok`; la tool corre solo si el gate dice `execute` (con OK del humano).

## Contrato de UX del send-gate (lenguaje plano)

Cuando un send cae a `needs_ok`, el `payload` trae, sin jerga:
- **qué** va a hacer (`que_va_a_hacer`: "mandar algo afuera (correo, mensaje o difusión)")
- **dónde / a quién** afecta (`donde_afecta`: "el destinatario que figura en el mensaje")
- **vista previa** del mensaje real (`vista_previa`: "Le va a mandar a «dest»: <cuerpo>")
- **OK explícito** (`requiere_ok=True`, `boton_ok`, `boton_cancelar`, `leyenda` del nivel).

## Cobertura de nombres de envío (lección del bypass por nombre evasivo)

El gate clasifica por VERBO, no por sustantivo. Caen a `needs_ok` no solo `send_*` sino los
evasivos: `dispatch_*`, `notify_*`, `post_*`, `forward_*`, `reply_all`, `broadcast`,
`publish`, `deliver`, `transmit`, `tweet`, `whatsapp`, `sms`, `outbound`, `email_send`,
`mail_send`, y los español `enviar/mandar/difundir/publicar/reenviar`, incluyendo camelCase.
Las LECTURAS de mensajería (`search_messages`, `get_message`, `read_inbox`, `list_chats`)
auto-ejecutan: "seguro pero no paralizado".

## Evidencia ejecutada (re-corrible)

```
# Run real por el PATH de prod con la tool de envío del gated_server:
python3 platform/assembler/test_gate_in_path.py        # 11 PASS — gate antes de registry.call
python3 platform/gates/test_gate_evasive_names.py      # 64 PASS — batería de send evasivo
python3 platform/gates/tests_recipe_enforcer.py        # 21 PASS — invariante §3.5
```

Run real de send (gated_server, receta con `gates.send="off"`, peor caso):
`send_message` → `gate_decision = {action: needs_ok, level: confirma-siempre}`, la tool NO se
ejecutó, y el marcador de breach `MESSAGE_SENT` **NUNCA apareció** en el resultado del run.

## DEUDA conocida (fricción de UX, NO breach)

Nombres de LECTURA cuyo string contiene la raíz de canal de correo (`mail`/`email`) —
`fetch_emails`, `list_emails`, `get_emails` — caen a `needs_ok` por conservadurismo del
clasificador (`approval_gate._WRITE_EFFECT_HINTS` matchea `mail`/`email` por substring). Es
el lado SEGURO (pide OK, nunca manda solo), pero agrega fricción a una lectura. No se relaja
el clasificador porque relajar `mail`/`email` reabriría el riesgo de que `email_send`/
`mail_send` se cuele. Cura futura: clasificar lectura-de-correo por token + ausencia de verbo
de envío. Escala a Threat Modeler (J) si se quiere priorizar.
