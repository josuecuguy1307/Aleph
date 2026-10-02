# La capa de chat compartida

`aleph-chat.js` es **la única implementación de chat del producto**. La usan las dos
superficies conversacionales:

| Superficie | Monta en | `surface:` |
|---|---|---|
| **El Guía** (panel flotante del Cuarto) | `#copilot` en `cuarto.pixi.html` | `"guia"` |
| **La Sala** (composer + franja de mensajes) | `.chat` en `sala/sala.html` | `"sala"` |

Debajo corre [`deep-chat`](https://github.com/OvidijusParsiunas/deep-chat) `2.5.0` (MIT),
**vendorizado** en `../vendor/deepChat.bundle.js` (390 KB, un solo archivo, cero CDN).
El veredicto de viabilidad — medido en WebKit real — está en `spikes/deep-chat/VEREDICTO.md`.

    node product/app/design/chat/verify_aleph_chat.mjs     # la vara (WebKit, sin backend)

---

## Las dos leyes

**1 · Local-first.** deep-chat, por default, inyecta un `<link>` a `fonts.googleapis.com`.
Está guardado: sólo inyecta si el `fontFamily` es su stack Inter por default. Seteando
`font-family` inline en el `<deep-chat>` la inyección **no ocurre**. Acá eso no se deja a la
memoria de nadie: `FONT_STACK` se aplica siempre y `assertLocalFirst()` lo verifica en runtime
(deja `window.__alephChatLocalFirst`). Si alguien lo saca, rompe **ruidoso**, no en silencio
con un request a Google.

**2 · Todo lo visible vive en `STRINGS`.** ES/EN en lockstep, un solo lugar, las dos
superficies. Se re-aplica solo con el evento `aleph:langchange`.

---

## El orden que sí funciona (y por qué)

Montar deep-chat tiene **dos** esperas, no una. Saltarse cualquiera falla en silencio:

1. **`customElements.whenDefined("deep-chat")`.** El bundle se importa async. Asignar
   propiedades a un elemento **sin upgradear** crea *own-properties* que después **tapan los
   setters del prototipo**: el componente nunca ve la config y responde con su demo
   (`"Hi there! This is a demo response!"`). Costó una tarde: `connect`,
   `htmlClassUtilities` y `auxiliaryStyle` se ignoraban sin un solo error en consola.
2. **El evento `render`.** `whenDefined` sólo dice que la clase existe. `addMessage` se
   rechaza hasta que el chat-view renderizó (`addMessage failed - please wait for chat view
   to render…`), y encima el componente **difiere el render mientras le sigan llegando
   propiedades** (`waitForPropertiesToBeUpdatedBeforeRender`) — o sea que configurar dispara
   un render nuevo.

Orden correcto: `whenDefined` → escuchar `render` → `configure()` → (render) → recién ahí,
mensajes. Mientras tanto, el controlador **encola**; los callers no se enteran (la API es
sincrónica igual). Si el render no llega en 8 s, se grita por consola en vez de tragarse los
mensajes.

## `slot(node)` — por qué existe

La Sala ya sabe armar cards ricas (gate, recibo, evidencia, obracard, delegación) y las
construye **imperativamente**, con `.onclick` asignado a mano. Serializarlas a HTML
(`addMessage({html})`) **mataría esos handlers**: botones que se ven bien y no hacen nada,
el peor de los fallos mudos.

`slot()` hace que deep-chat renderice un mensaje html **vacío** que sirve de ranura, y después
**mueve el nodo real adentro**. Mover un nodo del light DOM al shadow DOM conserva sus
listeners y propiedades — es el mismo objeto. El orden cronológico de la conversación queda
bien (es un mensaje más de la lista) y el estilo entra por `auxiliaryStyle`.

## El CSS vive en `auxiliaryStyle`

deep-chat renderiza dentro de su **Shadow DOM**: el `<style>` de la página **no entra**. Todo
el estilo de nuestras cards viaja en la constante `AUX_CSS`. Por eso las cards conservan
**exactamente los mismos nombres de clase** que tenían en light DOM (`.errcard`, `.acts`,
`.gate`…): la vara sólo cambia por dónde resuelve el nodo, no qué afirma.

Las *custom properties* **sí** cruzan el shadow boundary, así que el tema claro/oscuro sigue
mandando por `var(--ink)`, `var(--accent)`, etc.

---

## i18n · qué se pisa y qué queda en inglés

**Pisado por props** (en `applyStrings()`): placeholder · nombres AI/usuario · mensaje de
error · tooltip de **enviar** (`submitButtonStyles.tooltip`) · tooltip de **adjuntar**
(`mixedFiles.button.tooltip`). Los tooltips de cámara y micrófono se pisan por la misma vía
si esas entradas se habilitan.

**Declarado — hardcodeado en inglés dentro del bundle, sin prop que lo exponga:**

| String | Dónde aparece | Nos pega hoy |
|---|---|---|
| `"No file was added"` | validación al enviar un adjunto vacío | sólo si el usuario fuerza ese caso |
| `"Please send text with your file(s)"` | validación del camino OpenAI | **no** — no usamos servicios directos |
| `"Invalid API Key"`, `"Failed to connect"`, `"Request settings have not been set up"` | UI de servicios directos / API-key | **no** — usamos `connect.handler` |
| errores de Azure / Gemini / WebLLM | integraciones opt-in | **no** — no se activan |

Cubrir el resto exigiría override por CSS (`::after`) o un parche upstream. **No es
bloqueante** y no se disfraza: se declara acá. Si alguno empieza a aparecer en una superficie
real, el arreglo es un parche al bundle vendorizado, documentado en este mismo archivo.
