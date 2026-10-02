/* opciones.js — OPCIONES POR TURNO · el contrato transversal (FIX-P7).
 *
 * QUÉ ES: cada vez que la próxima entrada del humano es PREDECIBLE Y ENUMERABLE, el mensaje
 * del agente trae las opciones tocables — nacidas del contenido de ESE turno. Tipear queda
 * SIEMPRE abierto: el composer jamás se bloquea; las opciones ahorran tipeo, no lo reemplazan.
 *
 * LA ARQUITECTURA (el patrón Anthropic, copiado en lo copiable):
 *   No es la UI adivinando. Es EL MODELO emitiendo una llamada ESTRUCTURADA y un cliente TONTO
 *   que sólo renderiza el schema. La mesura no vive en el renderer: está ESCRITA como doctrina
 *   en la descripción de cada tool (con ejemplos positivos Y NEGATIVOS) y con TOPES DUROS en el
 *   schema. La separación respuesta/acción es de CONTRATO, no de estilo.
 *
 * LO QUE NO SE PUEDE COPIAR (y queda dicho): los modelos de Anthropic están ENTRENADOS sobre
 * sus tools. Eso no se replica. Lo replicable es enorme: modelo frontier + doctrina bien
 * escrita en el system + schemas con topes duros ≈ casi todo el comportamiento. La calidad
 * escala por MODELO y por WRAPPER — esto es construir wrapper.
 *
 * ── LAS DOS SUPERFICIES, UN SOLO CONTRATO ────────────────────────────────────────────
 * Los MISMOS 5 schemas viajan por dos transportes distintos, porque los dos motores son
 * distintos y ninguno se toca:
 *
 *   · EL GUÍA  — loop de tool-calling en el BROWSER (cuarto.guide.js). Las 5 entran como
 *     tools OpenAI-function de verdad: el modelo las llama, el despacho las renderiza.
 *   · LA SALA  — el loop de tools corre SERVER-SIDE (assembler) y el cliente no puede
 *     agregarle tools sin tocar el motor (fuera de alcance por mandato). Ahí el modelo emite
 *     el MISMO objeto {tool,args} dentro de un bloque cercado ```aleph:opciones, la doctrina
 *     viaja por `recipe.framing.inline` (que el backend ya concatena al system), y el cliente
 *     lo parsea con EL MISMO validador. Mismo contrato, mismo validador, mismo render.
 *     La deuda —y el endpoint exacto que la cierra— está declarada en el informe.
 *
 * ── LO QUE ESTE MÓDULO NO HACE ───────────────────────────────────────────────────────
 * No decide CUÁNDO hay opciones (eso es del modelo), no sabe qué hace cada botón (eso lo
 * cablea la superficie en `destinos`), y no inventa un botón cuyo destino no existe: una
 * opción sin handler cableado NO SE PINTA — se dice honesto. Es la regla de `caminoDe`
 * ("destino inexistente → texto honesto, JAMÁS botón falso") aplicada a las 5 familias.
 */

import { CONEXION_INLINE_TOOLS, TOOL_NAMES as CONEXION_INLINE_TOOL_NAMES } from "./conexion-inline.js";

/* ══ i18n · ES/EN en lockstep · UN solo lugar para las DOS superficies ═════════════════
 * El modelo elige QUÉ acción ofrecer; el PRODUCTO elige CÓMO se llama. Por eso los labels
 * de T2/T3/T4/T5 son nuestros (canónicos, bilingües) y sólo T1 —la respuesta a una pregunta
 * suya— lleva labels que el modelo escribe con las palabras de ESE turno. */
export const STRINGS = {
  es: {
    "acc.enviar": "Enviar",
    "acc.editar": "Editar",
    "acc.descargar": "Descargar",
    "acc.abrir_en_sala": "Abrir en la Sala",
    "acc.aplicar": "Aplicarlo",
    "acc.ver_diff": "Ver el diff",
    "apr.ok": "Aprobar",
    "apr.ver": "Ver qué va a hacer",
    "apr.no": "No",
    "ir.cuarto": "Ir al Cuarto",
    "ir.pieza": "Abrir la pieza",
    "ir.sala": "Ir a la Sala",
    "ir.conexiones": "Abrir el Centro",
    "ir.cerebro": "Elegir modelo",
    "multi.ok": "Listo",
    "lat.enviando": "enviando…",
    "lat.descargando": "preparando la descarga…",
    "lat.abriendo": "abriendo…",
    "lat.aplicando": "aplicando…",
    "lat.aprobando": "ejecutando…",
    "lat.yendo": "llevándote…",
    "des.cancelado": "No lo hice. Nada corrió.",
    "des.sin_camino": "No tengo a dónde llevarte para eso todavía.",
    "des.plan": "Esto es lo que haría",
    "err.contrato": "no pude ofrecerte opciones para esto",
  },
  en: {
    "acc.enviar": "Send",
    "acc.editar": "Edit",
    "acc.descargar": "Download",
    "acc.abrir_en_sala": "Open in the Room of use",
    "acc.aplicar": "Apply it",
    "acc.ver_diff": "See the diff",
    "apr.ok": "Approve",
    "apr.ver": "See what it will do",
    "apr.no": "No",
    "ir.cuarto": "Go to the Room",
    "ir.pieza": "Open the piece",
    "ir.sala": "Go to the Room of use",
    "ir.conexiones": "Open the Hub",
    "ir.cerebro": "Pick a model",
    "multi.ok": "Done",
    "lat.enviando": "sending…",
    "lat.descargando": "preparing the download…",
    "lat.abriendo": "opening…",
    "lat.aplicando": "applying…",
    "lat.aprobando": "running…",
    "lat.yendo": "taking you there…",
    "des.cancelado": "I didn't do it. Nothing ran.",
    "des.sin_camino": "I don't have anywhere to take you for that yet.",
    "des.plan": "This is what I would do",
    "err.contrato": "I couldn't offer you options for this",
  },
};

const T = (lang, k) => (STRINGS[lang === "en" ? "en" : "es"][k] != null
  ? STRINGS[lang === "en" ? "en" : "es"][k]
  : (STRINGS.es[k] != null ? STRINGS.es[k] : k));

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ══ TOPES DUROS · el schema, no el buen gusto del modelo ═════════════════════════════ */
export const TOPES = {
  preguntas_max: 3,        // 1 por turno es la NORMA; 3 es techo duro, no meta
  opciones_min: 2,         // menos de 2 no es una elección
  opciones_max: 4,
  palabras_label: 3,       // labels ≤ 3 palabras
  acciones_max: 4,
  plan_max: 6,
  mensaje_max: 400,
};

/* Qué botón nativo puede llevar cada tipo de producto. El modelo elige la ACCIÓN; no puede
 * ponerle [Enviar] a un informe ni [Descargar] a un correo. Como en Claude: el correo trae
 * su botón de correo, no un botón genérico. */
export const ACCIONES_POR_TIPO = {
  correo:  ["enviar", "editar"],
  mensaje: ["enviar", "editar"],
  archivo: ["descargar", "abrir_en_sala"],
  informe: ["descargar", "abrir_en_sala"],
  receta:  ["aplicar", "ver_diff"],
};
export const TIPOS_PRODUCTO = Object.keys(ACCIONES_POR_TIPO);
export const ACCIONES_PRODUCTO = ["enviar", "editar", "descargar", "abrir_en_sala", "aplicar", "ver_diff"];
export const DESTINOS_REDIRIGIR = ["cuarto", "pieza", "sala", "conexiones", "cerebro"];
export const CONSECUENCIAS = ["cuenta", "dinero", "mundo", "datos"];

/* Las causas que `camino_de_falta` puede nombrar: son EXACTAMENTE las de cuarto.semaforo.js
 * (CAUSAS). Duplicarlas acá sería una segunda tabla; se listan como enum del schema porque el
 * schema viaja al modelo, pero el BOTÓN sale siempre de caminoDe() en runtime. */
export const CAUSAS_FALTA = [
  "falta_key", "key_invalida", "sin_sesion", "sin_red", "timeout", "error_upstream",
  "cli_no_instalado", "cli_version_vieja", "cli_interactivo_colgado", "cli_sin_permisos",
  "plan_insuficiente", "sin_credito", "rate_limit", "modelo_no_disponible",
  "sin_vision", "sin_memoria", "premium", "no_configurado", "detectado",
  // [FIX-P8] las dos que faltaban del mismo grupo: ahora que las piezas declaran su tier
  // mínimo (capability gating), «este modelo no alcanza para esto» es una falta con
  // nombre y con lugar exacto a dónde ir — no un «no puedo» sin salida.
  "sin_codigo", "sin_razonamiento",
];

/* ══ LAS 5 TOOLS · schema estricto + DOCTRINA en la descripción ═══════════════════════
 * La calibración se ESCRIBE, no se espera del modelo: cada descripción trae cuándo SÍ,
 * cuándo NO, y ejemplos ✓/✗ concretos. Bilingüe: el belt se construye en el idioma de la
 * sesión para que la doctrina se lea en el mismo idioma en que el modelo va a contestar. */

const fn = (name, description, properties, required) => ({
  type: "function",
  function: {
    name, description,
    parameters: { type: "object", properties: properties || {}, required: required || [], additionalProperties: false },
  },
});

const DOC = {
  es: {
    t1: [
      "Ofrece al humano las opciones TOCABLES de la pregunta, nacidas del contenido de ESTE turno. Tocar una convierte su label en el MENSAJE del humano: para el modelo, simplemente contestó. Tipear sigue abierto — las opciones ahorran tipeo, no lo reemplazan.",
      "CUÁNDO SÍ (las 4 familias): (a) RESPUESTA A PREGUNTA — «¿Para uso propio o para un cliente?» → [Para mí] [Para un cliente]. (b) DESAMBIGUACIÓN — «¿cuál de los dos?» → [Cad] [Freecad] [Ver diferencias]. (c) DELEGACIÓN (patrón padrino) — «¿lo armo yo o lo guío paso a paso?» → [Que lo arme el guía] [Guiar paso a paso]. (d) CONTINUACIÓN — se terminó una parte → [Seguir] [Cambiar algo] [Parar aquí].",
      "CUÁNDO NO — no van si: el humano pregunta «¿A o B?» (quiere el análisis del modelo, no sus botones de vuelta: hay que contestar cuál y por qué) · está conversando o desahogándose (escuchar, no dar un menú) · la pregunta es factual (responder el dato) · los constraints ya están dados (no re-preguntar: avanzar y declarar el supuesto).",
      "REGLA DE ORO: antes de preguntar, releer la conversación. Si la respuesta ya está o se infiere, se usa — preguntar lo ya contestado es peor que no preguntar.",
      "REGLA DE TURNO: emitidas las opciones, el turno TERMINÓ. No se sigue escribiendo debajo de la propia pregunta ni se contesta solo. Se espera al humano.",
      "EJEMPLOS ✗ (no llamar esta tool): humano «¿conviene Postgres o SQLite?» → responder con criterio, sin botones · humano «uf, llevo tres horas con esto» → escuchar · humano «lo necesito para mi cliente, en inglés, para el viernes» → los constraints ya están: avanzar.",
      "TOPES: 1 pregunta por turno como NORMA (3 es techo duro, no meta) · 2 a 4 opciones · labels de hasta 3 palabras · opciones MUTUAMENTE EXCLUYENTES · `tipo:\"multi\"` sólo si de verdad se pueden elegir varias · el `mensaje` conversacional breve va SIEMPRE — jamás opciones mudas.",
    ].join("\n"),
    t2: [
      "El turno produjo algo y la siguiente entrada del humano es qué HACER con ese producto. El producto se emite con sus botones NATIVOS: un correo trae su botón de correo, un archivo el suyo — nunca un botón genérico.",
      "Mapa fijo por tipo: correo/mensaje → [Enviar] [Editar] · archivo/informe → [Descargar] [Abrir en la Sala] · receta → [Aplicarlo] [Ver el diff]. No se mezclan: pedir [Enviar] sobre un informe es un error de contrato y se rechaza.",
      "PROHIBICIÓN DE CONTRATO: JAMÁS afirmar que la acción ocurrió antes del tap. El botón ES el consentimiento. Se escribe «queda listo para enviar», nunca «ya lo envié». Si es consecuente, el tap además pasa por su gate.",
      "EJEMPLOS ✓ se redactó un correo → mensaje «Queda redactado» + producto correo + [Enviar] [Editar] · se generó un informe → [Descargar] [Abrir en la Sala].",
      "EJEMPLOS ✗ no va para un texto que no es un entregable (una explicación no se descarga) · no va para volver a preguntar (eso es preguntar_opciones) · nunca «listo, ya está enviado» antes del tap.",
      "REGLA DE TURNO: emitido el producto con sus botones, el turno TERMINÓ. Nada corre hasta que el humano toque.",
    ].join("\n"),
    t3: [
      "Al agente le FALTA una pieza y hay UN camino real que la consigue. La falta se emite con su causa exacta: el botón sale del diccionario único del producto (caminoDe), no se escribe a mano.",
      "CUÁNDO SÍ: sin modelo de visión y el pedido era mirar una imagen (causa `sin_vision`) · la memoria no está conectada (`sin_memoria`) · una pieza es premium (`premium`) · una key falta o no sirve (`falta_key` / `key_invalida`) · el CLI no está instalado (`cli_no_instalado`).",
      "CUÁNDO NO: si el trabajo se puede hacer, se hace — no se ofrece conectar algo que no hace falta · si la causa no se sabe con certeza, se dice honesto en prosa en vez de nombrar una causa al azar (una causa inventada manda al humano a un lugar equivocado).",
      "EJEMPLO ✓ «Para MIRAR la imagen hace falta un modelo con visión — no adivino sobre algo que no vi» + causa `sin_vision`.",
      "EJEMPLO ✗ decir «no puedo» y quedarse callado: dejar a alguien sin camino es la mitad que falta de la honestidad.",
      "REGLA DE TURNO: emitido el camino, el turno TERMINÓ.",
    ].join("\n"),
    t4: [
      "La acción que sigue es CONSECUENTE (toca la cuenta del humano, su plata, sus datos o el mundo). El OK se pide ANTES de correr nada: [Aprobar] [Ver qué va a hacer] [No].",
      "Esto es la PIEL de la doctrina de gates que ya existe — no un gate paralelo. El tap ES el consentimiento: nada corre antes. [Ver qué va a hacer] despliega el PLAN REAL, paso por paso — no un resumen decorativo, no una promesa.",
      "CUÁNDO SÍ: mandar algo a una cuenta de terceros · mover plata · borrar o sobrescribir datos del humano · cualquier escritura al mundo que no se pueda deshacer.",
      "CUÁNDO NO: para leer, calcular, buscar o redactar (eso se corre y ya) · para pedir una preferencia (eso es preguntar_opciones) · nunca para que el humano apruebe algo que YA se hizo.",
      "PROHIBICIÓN DE CONTRATO: JAMÁS afirmar que la acción ocurrió antes del tap. Y si el humano toca [No], no se reintenta ni se negocia: no corrió, y punto.",
      "REGLA DE TURNO: pedida la aprobación, el turno TERMINÓ.",
    ].join("\n"),
    t5: [
      "Lo que el humano quiere se ajusta en OTRA superficie. Se dice y se lleva: la opción navega de verdad y lo deja PARADO en el lugar correcto (la pieza enfocada, no la pantalla genérica).",
      "CUÁNDO SÍ: «eso se equipa/ajusta en el Cuarto» → destino `cuarto` (con `pieza_id` si se sabe cuál) · «se prueba en la Sala» → `sala` · «las conexiones viven en el Centro» → `conexiones` · «cambiar el modelo» → `cerebro`.",
      "CUÁNDO NO: si se puede resolver aquí mismo, se resuelve — mandar a otra pantalla lo que se podía hacer aquí es hacerle perder el viaje.",
      "Si no se sabe a qué pieza exacta llevarlo, no se inventa un `pieza_id`: se manda al destino general.",
      "REGLA DE TURNO: emitida la redirección, el turno TERMINÓ.",
    ].join("\n"),
  },
  en: {
    t1: [
      "Offer the human the TAPPABLE options for your question, born from the content of THIS turn. Tapping one turns its label into the human's MESSAGE: to you, they simply answered. Typing stays open — options save typing, they don't replace it.",
      "WHEN YES (the 4 families): (a) ANSWER TO A QUESTION — “For you or for a client?” → [For me] [For a client]. (b) DISAMBIGUATION — “which one?” → [Cad] [Freecad] [See differences]. (c) DELEGATION (godfather pattern) — “should I do it or walk you through it?” → [You do it] [Walk me through]. (d) CONTINUATION — you finished a part → [Keep going] [Change something] [Stop here].",
      "WHEN NO — don't use them if: the human asks YOU “A or B?” (they want YOUR analysis, not their buttons back: answer which and why) · they're venting or just talking (listen, don't hand them a menu) · the question is factual (answer it) · they already gave you the constraints (don't re-ask: move ahead and state the assumption).",
      "GOLDEN RULE: before asking, re-read the conversation. If the answer is already there or can be inferred, USE IT — asking what was already answered is worse than not asking.",
      "TURN RULE: you emitted options → your turn is OVER. Don't keep writing under your own question and don't answer yourself. Wait for the human.",
      "EXAMPLES ✗ (do not call this tool): human asks “Postgres or SQLite?” → answer with your judgment, no buttons · human says “ugh, three hours on this” → listen · human says “do it for my client, in English, by Friday” → you have the constraints: proceed.",
      "CAPS: 1 question per turn as the NORM (3 is a hard ceiling, not a target) · 2 to 4 options · labels up to 3 words · options MUTUALLY EXCLUSIVE · `tipo:\"multi\"` only if several really can be picked · the brief conversational `mensaje` ALWAYS goes first — never mute options.",
    ].join("\n"),
    t2: [
      "The turn produced something and the human's next input is what to DO with that product. Emit the product with its NATIVE buttons: an email carries its email button, a file its own — never a generic button.",
      "Fixed map by type: correo/mensaje → [Send] [Edit] · archivo/informe → [Download] [Open in the Room of use] · receta → [Apply it] [See the diff]. Don't mix: asking for [Send] on a report is a contract error and gets rejected.",
      "CONTRACT PROHIBITION: NEVER claim the action happened before the tap. The button IS the consent. Write “I've left it ready to send”, never “I sent it”. If it's consequential, the tap also goes through its gate.",
      "EXAMPLES ✓ you drafted an email → message “I've drafted it for you” + producto correo + [Send] [Edit] · you generated a report → [Download] [Open in the Room of use].",
      "EXAMPLES ✗ don't use it for text that isn't a deliverable (an explanation isn't downloaded) · don't use it to ask again (that's preguntar_opciones) · never “done, it's sent” before the tap.",
      "TURN RULE: you emitted the product with its buttons → your turn is OVER. Nothing runs until the human taps.",
    ].join("\n"),
    t3: [
      "The agent is MISSING a piece and there is ONE real path that gets it. Emit the gap with its exact cause: the button comes from the product's single dictionary (caminoDe) — you don't write it.",
      "WHEN YES: no vision model and you were asked to look at an image (cause `sin_vision`) · memory isn't connected (`sin_memoria`) · a piece is premium (`premium`) · a key is missing or invalid (`falta_key` / `key_invalida`) · the CLI isn't installed (`cli_no_instalado`).",
      "WHEN NO: if you can do the work, do it — don't offer to connect something that isn't needed · if you don't know the cause for certain, say so honestly in prose instead of naming a random cause (an invented cause sends the human to the wrong place).",
      "EXAMPLE ✓ “To LOOK at the image I need a brain with vision — I don't guess about something I didn't see” + cause `sin_vision`.",
      "EXAMPLE ✗ saying “I can't” and going quiet: leaving someone without a path is the missing half of honesty.",
      "TURN RULE: you emitted the path → your turn is OVER.",
    ].join("\n"),
    t4: [
      "The next action is CONSEQUENTIAL (it touches the human's account, their money, their data or the world). Ask for the OK BEFORE running anything: [Approve] [See what it will do] [No].",
      "This is the SKIN of the gate doctrine that already exists — not a parallel gate. The tap IS the consent: nothing runs before. [See what it will do] unfolds the REAL plan, step by step — not a decorative summary, not a promise.",
      "WHEN YES: sending something to a third-party account · moving money · deleting or overwriting the human's data · any write to the world that can't be undone.",
      "WHEN NO: for reading, computing, searching or drafting (just do it) · to ask for a preference (that's preguntar_opciones) · never to have the human approve something you ALREADY did.",
      "CONTRACT PROHIBITION: NEVER claim the action happened before the tap. And if the human taps [No], don't retry it or negotiate: it didn't run, full stop.",
      "TURN RULE: you asked for approval → your turn is OVER.",
    ].join("\n"),
    t5: [
      "What the human wants is adjusted on ANOTHER surface. Say it and take them: the option navigates for real and leaves them STANDING in the right place (the focused piece, not the generic screen).",
      "WHEN YES: “that's equipped/adjusted in the Room” → destino `cuarto` (with `pieza_id` if you know which) · “try it in the Room of use” → `sala` · “your connections live in the Hub” → `conexiones` · “change the model” → `cerebro`.",
      "WHEN NO: if you can solve it right here, solve it — sending someone to another screen for something you could have done wastes their trip.",
      "If you don't know the exact piece, don't invent a `pieza_id`: send them to the general destination.",
      "TURN RULE: you emitted the redirect → your turn is OVER.",
    ].join("\n"),
  },
};

/** OPCIONES_TOOLS(lang) → las 5 tools con su doctrina en el idioma de la sesión. */
export function OPCIONES_TOOLS(lang) {
  const L = lang === "en" ? "en" : "es";
  const d = DOC[L];
  return [
    fn("preguntar_opciones", d.t1, {
      mensaje: { type: "string", description: L === "en"
        ? "Brief conversational line that ALWAYS precedes the options. Never mute options."
        : "Línea conversacional breve que SIEMPRE precede a las opciones. Jamás opciones mudas." },
      preguntas: {
        type: "array", minItems: 1, maxItems: TOPES.preguntas_max,
        description: L === "en" ? "1 as the norm; 3 is a hard ceiling, not a target."
                                : "1 como norma; 3 es techo duro, no meta.",
        items: {
          type: "object", additionalProperties: false, required: ["pregunta", "opciones"],
          properties: {
            pregunta: { type: "string" },
            tipo: { type: "string", enum: ["single", "multi"], description: L === "en"
              ? "single by default; multi ONLY if several really apply." : "single por default; multi SÓLO si de verdad aplican varias." },
            opciones: {
              type: "array", minItems: TOPES.opciones_min, maxItems: TOPES.opciones_max,
              items: {
                type: "object", additionalProperties: false, required: ["label"],
                properties: {
                  label: { type: "string", description: L === "en" ? "Up to 3 words." : "Hasta 3 palabras." },
                  valor: { type: "string", description: L === "en"
                    ? "Optional: the full text that enters the transcript as the human's message. Defaults to the label."
                    : "Opcional: el texto completo que entra al transcript como mensaje del humano. Por default, el label." },
                },
              },
            },
          },
        },
      },
    }, ["mensaje", "preguntas"]),

    fn("accion_de_producto", d.t2, {
      mensaje: { type: "string" },
      producto: {
        type: "object", additionalProperties: false, required: ["tipo", "titulo"],
        properties: {
          tipo: { type: "string", enum: TIPOS_PRODUCTO },
          titulo: { type: "string" },
          ref: { type: "string", description: L === "en" ? "Optional id of the artifact/output produced this turn." : "Opcional: id del artifact/output producido en este turno." },
          instruccion: { type: "string", description: L === "en"
            ? "Optional: the exact instruction to run when the human taps (e.g. the send order). It runs ONLY after the tap."
            : "Opcional: la instrucción exacta a correr cuando el humano toque (ej. la orden de envío). Corre SÓLO tras el tap." },
        },
      },
      acciones: {
        type: "array", minItems: 1, maxItems: TOPES.acciones_max,
        items: { type: "string", enum: ACCIONES_PRODUCTO },
      },
    }, ["mensaje", "producto", "acciones"]),

    fn("camino_de_falta", d.t3, {
      mensaje: { type: "string" },
      causa: { type: "string", enum: CAUSAS_FALTA },
      pieza: { type: "string", description: L === "en" ? "Optional: which piece is missing it." : "Opcional: de qué pieza es la falta." },
    }, ["mensaje", "causa"]),

    fn("aprobar", d.t4, {
      mensaje: { type: "string" },
      resumen: { type: "string", description: L === "en" ? "One line: what is about to happen." : "Una línea: qué está por hacerse." },
      plan: {
        type: "array", minItems: 1, maxItems: TOPES.plan_max,
        description: L === "en" ? "The REAL steps behind [See what it will do]." : "Los pasos REALES detrás de [Ver qué va a hacer].",
        items: { type: "string" },
      },
      consecuencia: { type: "string", enum: CONSECUENCIAS },
      instruccion: { type: "string", description: L === "en"
        ? "Optional: the exact instruction to run on [Approve]. Nothing runs before the tap."
        : "Opcional: la instrucción exacta a correr con [Aprobar]. Nada corre antes del tap." },
    }, ["mensaje", "resumen", "plan", "consecuencia"]),

    fn("redirigir", d.t5, {
      mensaje: { type: "string" },
      destino: { type: "string", enum: DESTINOS_REDIRIGIR },
      pieza_id: { type: "string", description: L === "en" ? "Optional: the piece to focus on arrival." : "Opcional: la pieza a enfocar al llegar." },
    }, ["mensaje", "destino"]),
  ];
}

export const OPCIONES_TOOL_NAMES = ["preguntar_opciones", "accion_de_producto", "camino_de_falta", "aprobar", "redirigir"];

/* La familia de tools DEL CLIENTE creció sin cambiar el contrato de las 5 opciones:
 * `conectar_inline` tiene componente/validador propios, pero viaja por el mismo canal P7/P9.
 * Mantener ambos exports evita que el renderer de opciones tenga que saber de credenciales. */
export const CLIENT_TOOL_NAMES = OPCIONES_TOOL_NAMES.concat(CONEXION_INLINE_TOOL_NAMES);
export function CLIENT_TOOLS(lang) {
  return OPCIONES_TOOLS(lang).concat(CONEXION_INLINE_TOOLS(lang));
}

/* ══ LA DOCTRINA PARA EL SYSTEM ═══════════════════════════════════════════════════════
 * Los schemas se auto-describen, pero la parte que el modelo tiene que tener SIEMPRE
 * presente —cuándo NO, la regla de oro y la regla de turno— va también en el system.
 * `transporte:"bloque"` agrega el protocolo de La Sala (donde no hay canal de tools). */
export function doctrinaSistema(lang, opts) {
  const L = lang === "en" ? "en" : "es";
  const o = opts || {};
  const bloque = o.transporte === "bloque";
  const nombres = OPCIONES_TOOL_NAMES.join(" · ");
  if (L === "en") {
    const lines = [
      "## OPTIONS PER TURN",
      "Whenever the human's next input is PREDICTABLE AND ENUMERABLE, your message carries the tappable options — born from the content of THIS turn. Typing always stays open: options save typing, they never replace it. Five families: " + nombres + ".",
      "WHEN NOT TO: the human asks YOU “A or B?” (they want your analysis, not their buttons back) · they're just talking or venting (listen) · the question is factual (answer it) · they already gave you the constraints (don't re-ask: proceed and state the assumption).",
      "GOLDEN RULE: before asking, re-read the conversation — if the answer is already there or can be inferred, USE IT.",
      "TURN RULE: you emitted options → your turn is OVER. Don't keep writing under your own question, and never answer yourself.",
      "SEPARATION OF CONCERNS: answering is not acting. Never claim an action happened before the human taps its button — the button is the consent.",
    ];
    if (o.superficie === "guia") lines.push(
      "ON THIS SURFACE (the Room) you don't produce deliverables: `accion_de_producto` belongs to the Room of use. Here you use preguntar_opciones, camino_de_falta, aprobar and redirigir.",
      "EXAMPLES IN THIS DOMAIN (the Room):",
      "· YES · a search returned 6 MCPs and some must be picked → preguntar_opciones, ONE question, `multi:true`, one `label` per MCP (put its badge in the label if it helps decide). NEVER list them in prose asking the human to name them back: that's typing what's already on screen.",
      "· YES · a brain has to be chosen among the available ones → preguntar_opciones with the ones that EXIST (you read them), not the ones you recall.",
      "· YES · the piece is equipped but missing its key → camino_de_falta (that's its shape), not a question.",
      "· YES · you're about to equip/remove something the human didn't explicitly ask for → aprobar, with the plan in one line.",
      "· NO · “what do you want to build?” / “tell me what it's for” → OPEN question: the answer isn't enumerable. Prose, and listen.",
      "· NO · “want me to explain how this works?” when they already asked you to explain → they gave you the constraint: explain.",
      "· NO · two options that are the same (“Yes” / “Go ahead”) → if there's only one path, take it and say you took it.");
    if (bloque) {
      lines.push(
        "HOW TO EMIT (this surface has no tool channel): write a fenced block, on its own line, after the prose:",
        "```aleph:opciones",
        '{"tool":"preguntar_opciones","args":{"mensaje":"…","preguntas":[{"pregunta":"…","opciones":[{"label":"…"},{"label":"…"}]}]}}',
        "```",
        "One JSON object per block, at most 3 blocks per turn. The schemas are exactly the ones described above; anything that breaks them is discarded (and the human sees only your prose).",
        "THE 5 SCHEMAS:", ...OPCIONES_TOOLS(L).map(esquemaEnTexto));
    }
    return lines.join("\n");
  }
  const lines = [
    "## OPCIONES POR TURNO",
    "Cada vez que la próxima entrada del humano es PREDECIBLE Y ENUMERABLE, el mensaje trae las opciones tocables — nacidas del contenido de ESTE turno. Tipear queda siempre abierto: las opciones ahorran tipeo, jamás lo reemplazan. Cinco familias: " + nombres + ".",
    "CUÁNDO NO: el humano pregunta «¿A o B?» (quiere el análisis, no sus botones de vuelta) · está conversando o desahogándose (escuchar) · la pregunta es factual (responder) · los constraints ya están dados (no re-preguntar: avanzar y declarar el supuesto).",
    "REGLA DE ORO: antes de preguntar, releer la conversación — si la respuesta ya está o se infiere, se usa.",
    "REGLA DE TURNO: emitidas las opciones, el turno TERMINÓ. No se sigue escribiendo debajo de la propia pregunta ni se contesta solo.",
    "SEPARACIÓN DE CONTRATO: responder no es actuar. Jamás afirmar que una acción ocurrió antes de que el humano toque su botón — el botón ES el consentimiento.",
  ];
  if (o.superficie === "guia") lines.push(
    "EN ESTA SUPERFICIE (el Cuarto) no se producen entregables: `accion_de_producto` es de La Sala. Aquí van preguntar_opciones, camino_de_falta, aprobar y redirigir.",
    // [FIX-P10 §5] La doctrina abstracta no alcanzó: en la caminata del 27-jul el Guía
    // listó 6 MCPs y preguntó «¿cuáles dos abro?» EN PROSA — la forma exacta que estas
    // tools existen para cubrir. Los ejemplos van en SU dominio, con el positivo y el
    // negativo pegados, que es como se aprende un límite.
    "EJEMPLOS EN ESTE DOMINIO (el Cuarto):",
    "· SÍ · una búsqueda volvió con 6 MCPs y hay que elegir cuáles equipar → preguntar_opciones con UNA pregunta, `multi:true`, un `label` por MCP (con su badge en el label si ayuda a decidir). JAMÁS enumerarlos en prosa pidiendo que los nombre de vuelta: eso es tipear lo que ya está en pantalla.",
    "· SÍ · hay que elegir modelo entre los disponibles → preguntar_opciones con los que EXISTEN (los que se leyeron), no con los que suenan de memoria.",
    "· SÍ · la pieza está equipada pero le falta la llave → camino_de_falta (esa es su forma), no una pregunta.",
    "· SÍ · está por equiparse o quitarse algo que el usuario no pidió explícito → aprobar, con el plan en una línea.",
    "· NO · «¿qué hay que armar?» / «¿para qué se va a usar?» → pregunta ABIERTA: su respuesta no es enumerable. Prosa, y escuchar.",
    "· NO · «¿explico cómo funciona esto?» cuando el pedido ya era una explicación → el constraint ya está: explicar.",
    "· NO · dos opciones que son la misma («Sí» / «Dale») → si sólo hay un camino, se toma y se cuenta que se tomó.");
  if (bloque) {
    lines.push(
      "CÓMO SE EMITE (esta superficie no tiene canal de tools): va un bloque cercado, en su propia línea, después de la prosa:",
      "```aleph:opciones",
      '{"tool":"preguntar_opciones","args":{"mensaje":"…","preguntas":[{"pregunta":"…","opciones":[{"label":"…"},{"label":"…"}]}]}}',
      "```",
      "Un objeto JSON por bloque, máximo 3 bloques por turno. Los schemas son exactamente los de abajo; lo que no los cumpla se descarta (y el humano ve sólo la prosa).",
      "LOS 5 SCHEMAS:", ...OPCIONES_TOOLS(L).map(esquemaEnTexto));
  }
  return lines.join("\n");
}

/** Un schema OpenAI-function renderizado como texto para el system (transporte bloque). */
function esquemaEnTexto(t) {
  const f = t.function;
  return "· " + f.name + " — " + f.description + "\n  args: " + JSON.stringify(f.parameters);
}

/* ══ EL VALIDADOR · los topes son del schema, no del buen gusto ═══════════════════════
 * Devuelve {ok:true, datos} o {ok:false, error}. El error viaja de vuelta al modelo (en el
 * Guía, como resultado de la tool) para que corrija — nunca se traga en silencio. */
const palabras = (s) => String(s || "").trim().split(/\s+/).filter(Boolean).length;
const norm = (s) => String(s || "").trim().toLowerCase().replace(/\s+/g, " ");

export function validar(name, args, opts) {
  const o = opts || {};
  const a = args && typeof args === "object" ? args : {};
  const err = (m) => ({ ok: false, error: m });
  if (OPCIONES_TOOL_NAMES.indexOf(name) < 0) return err(`«${name}» no es una familia de opciones`);

  const mensaje = String(a.mensaje == null ? "" : a.mensaje).trim();
  if (!mensaje) return err("falta `mensaje`: jamás opciones mudas — una línea conversacional va SIEMPRE antes");
  if (mensaje.length > TOPES.mensaje_max) return err(`\`mensaje\` demasiado largo (${mensaje.length} > ${TOPES.mensaje_max})`);

  if (name === "preguntar_opciones") {
    const qs = Array.isArray(a.preguntas) ? a.preguntas : null;
    if (!qs || !qs.length) return err("falta `preguntas`");
    if (qs.length > TOPES.preguntas_max) return err(`${qs.length} preguntas: el techo duro es ${TOPES.preguntas_max} (la norma es 1)`);
    const limpias = [];
    for (let i = 0; i < qs.length; i++) {
      const q = qs[i] || {};
      const preg = String(q.pregunta || "").trim();
      if (!preg) return err(`la pregunta ${i + 1} no tiene texto`);
      const tipo = q.tipo === "multi" ? "multi" : "single";
      const ops = Array.isArray(q.opciones) ? q.opciones : [];
      if (ops.length < TOPES.opciones_min) return err(`«${preg}» tiene ${ops.length} opción(es): el mínimo es ${TOPES.opciones_min} (menos de 2 no es una elección)`);
      if (ops.length > TOPES.opciones_max) return err(`«${preg}» tiene ${ops.length} opciones: el máximo es ${TOPES.opciones_max}`);
      const vistos = new Set(); const lim = [];
      for (let j = 0; j < ops.length; j++) {
        // SE ADAPTA LA FORMA, JAMÁS EL DATO (la regla de `platform/artifacts/bridge.py`).
        // MEDIDO contra la .app instalada: el modelo emite `opciones: ["Barras","Líneas"]`
        // —strings— y el schema pide `[{label}]`. La validación rechazaba, el render no
        // pasaba, y el humano leía «tocá Barras o Líneas» sin nada que tocar: una promesa
        // sin entrega, y el motivo sólo en la consola.
        //
        // Un string ES un label: envolverlo no agrega ni quita información, que es
        // exactamente la frontera que la regla permite. Lo que sigue prohibido es rellenar
        // lo que falta — una opción sin texto sigue siendo un error, no un `"opción 1"`.
        const cruda = ops[j];
        const op = (typeof cruda === "string" || typeof cruda === "number")
          ? { label: String(cruda) }
          : (cruda || {});
        const label = String(op.label || "").trim();
        if (!label) return err(`una opción de «${preg}» no tiene label`);
        if (palabras(label) > TOPES.palabras_label) return err(`«${label}» tiene ${palabras(label)} palabras: el máximo es ${TOPES.palabras_label}`);
        const k = norm(label);
        // MUTUAMENTE EXCLUYENTES: dos opciones que dicen lo mismo no son una elección.
        if (vistos.has(k)) return err(`«${label}» está repetida en «${preg}»: las opciones deben ser mutuamente excluyentes`);
        vistos.add(k);
        lim.push({ label, valor: String(op.valor || "").trim() || label });
      }
      limpias.push({ pregunta: preg, tipo, opciones: lim });
    }
    return { ok: true, datos: { familia: name, mensaje, preguntas: limpias } };
  }

  if (name === "accion_de_producto") {
    const p = a.producto && typeof a.producto === "object" ? a.producto : null;
    if (!p) return err("falta `producto`");
    const tipo = String(p.tipo || "").trim();
    if (TIPOS_PRODUCTO.indexOf(tipo) < 0) return err(`tipo de producto «${tipo || "?"}» desconocido (válidos: ${TIPOS_PRODUCTO.join(", ")})`);
    const titulo = String(p.titulo || "").trim();
    if (!titulo) return err("el producto no tiene `titulo`");
    const acc = Array.isArray(a.acciones) ? a.acciones.map((x) => String(x || "").trim()) : [];
    if (!acc.length) return err("falta `acciones`");
    if (acc.length > TOPES.acciones_max) return err(`${acc.length} acciones: el máximo es ${TOPES.acciones_max}`);
    const permitidas = ACCIONES_POR_TIPO[tipo];
    const fuera = acc.filter((x) => permitidas.indexOf(x) < 0);
    // EL BOTÓN NATIVO DEPENDE DEL TIPO: un correo trae su botón de correo, no uno genérico.
    if (fuera.length) return err(`un ${tipo} no lleva [${fuera.join("] [")}] — sus botones son: ${permitidas.join(", ")}`);
    const unicas = acc.filter((x, i) => acc.indexOf(x) === i);
    return { ok: true, datos: { familia: name, mensaje,
      producto: { tipo, titulo, ref: String(p.ref || "").trim() || null, instruccion: String(p.instruccion || "").trim() || null },
      acciones: unicas } };
  }

  if (name === "camino_de_falta") {
    const causa = String(a.causa || "").trim();
    if (!causa) return err("falta `causa`");
    if (CAUSAS_FALTA.indexOf(causa) < 0) return err(`causa «${causa}» desconocida — mejor decirlo en prosa que mandar al humano a un lugar equivocado`);
    return { ok: true, datos: { familia: name, mensaje, causa, pieza: String(a.pieza || "").trim() || null } };
  }

  if (name === "aprobar") {
    const resumen = String(a.resumen || "").trim();
    if (!resumen) return err("falta `resumen`: una línea con qué está por hacerse");
    const plan = Array.isArray(a.plan) ? a.plan.map((x) => String(x || "").trim()).filter(Boolean) : [];
    if (!plan.length) return err("falta `plan`: [Ver qué va a hacer] despliega el plan REAL, no un resumen decorativo");
    if (plan.length > TOPES.plan_max) return err(`el plan tiene ${plan.length} pasos: el máximo es ${TOPES.plan_max}`);
    const cons = String(a.consecuencia || "").trim();
    if (CONSECUENCIAS.indexOf(cons) < 0) return err(`consecuencia «${cons || "?"}» desconocida (válidas: ${CONSECUENCIAS.join(", ")})`);
    return { ok: true, datos: { familia: name, mensaje, resumen, plan, consecuencia: cons,
      instruccion: String(a.instruccion || "").trim() || null } };
  }

  // redirigir
  const destino = String(a.destino || "").trim();
  if (DESTINOS_REDIRIGIR.indexOf(destino) < 0) return err(`destino «${destino || "?"}» desconocido (válidos: ${DESTINOS_REDIRIGIR.join(", ")})`);
  const pieza = String(a.pieza_id || "").trim() || null;
  return { ok: true, datos: { familia: "redirigir", mensaje, destino: (destino === "pieza" && !pieza) ? "cuarto" : destino, pieza_id: pieza } };
}

/* ══ EL TRANSPORTE DE LA SALA · bloques cercados en la prosa del modelo ════════════════
 * `extraer(texto)` → {texto, llamadas[]}. El texto vuelve SIN los bloques (el humano no ve
 * JSON crudo, nunca) y las llamadas salen ya parseadas. Un bloque roto NO se traga: se
 * reporta en `rotos` para que el llamador lo grite (§4h · fallo visible, jamás mudo). */
const RE_BLOQUE = /```[ \t]*aleph:opciones[ \t]*\r?\n([\s\S]*?)```/g;

export function extraer(texto) {
  const t = String(texto == null ? "" : texto);
  const llamadas = [], rotos = [];
  let limpio = t.replace(RE_BLOQUE, (m, cuerpo) => {
    if (llamadas.length + rotos.length >= TOPES.preguntas_max) { rotos.push("más de " + TOPES.preguntas_max + " bloques en un turno"); return ""; }
    let obj = null;
    try { obj = JSON.parse(String(cuerpo).trim()); } catch (e) { rotos.push("JSON inválido: " + String((e && e.message) || e)); return ""; }
    const name = obj && (obj.tool || obj.name);
    if (!name) { rotos.push("el bloque no declara `tool`"); return ""; }
    llamadas.push({ name: String(name), args: (obj && (obj.args || obj.arguments)) || {} });
    return "";
  });
  // los bloques dejan líneas vacías donde estaban: se colapsan para no abrir un hueco raro
  limpio = limpio.replace(/\n{3,}/g, "\n\n").trim();
  return { texto: limpio, llamadas, rotos };
}

/* ══ LA PROHIBICIÓN DE CONTRATO, DETECTADA ════════════════════════════════════════════
 * El modelo JAMÁS afirma que la acción ocurrió antes del tap. Esto no se puede impedir —
 * se DETECTA y se grita. `afirmacionPrematura(texto, familia)` mira la prosa del MISMO turno
 * en que se emitió un botón de acción y busca el pretérito de consumación. */
const PRETERITO = {
  es: /\b(ya\s+(lo\s+)?(envi[ée]|mand[ée]|pagu[ée]|transfer[ií]|apliqu[ée]|borr[ée]|ejecut[ée])|lo\s+(envi[ée]|mand[ée]|apliqu[ée])|(envi|mand|pag|transferi|aplic|ejecut|borr)(ado|ada|é)\b|listo[,:]?\s*(ya\s+)?(enviado|mandado|pagado|aplicado|hecho\s+y\s+enviado))/i,
  en: /\b(i\s+(just\s+)?(sent|mailed|paid|transferred|applied|deleted|executed)\b|(it'?s|has\s+been)\s+(sent|paid|applied|deleted|transferred)\b|done[,:]?\s*(it'?s\s+)?(sent|paid|applied))/i,
};
const FAMILIAS_ACCION = new Set(["accion_de_producto", "aprobar"]);

export function afirmacionPrematura(texto, familia) {
  if (!FAMILIAS_ACCION.has(familia)) return false;
  const t = String(texto || "");
  if (!t.trim()) return false;
  return PRETERITO.es.test(t) || PRETERITO.en.test(t);
}

/** El registro de violaciones, visible para la vara y para la consola (§4h). */
function anotarViolacion(detalle) {
  try {
    const reg = window.__alephOpcionesContrato || (window.__alephOpcionesContrato = { ok: true, violaciones: [] });
    reg.ok = false; reg.violaciones.push(detalle);
  } catch (e) {}
  console.error("[opciones] VIOLACIÓN DE CONTRATO — " + detalle);
}
try { window.__alephOpcionesContrato = { ok: true, violaciones: [] }; } catch (e) {}

/* ══ EL CSS · viaja al SHADOW ROOT por auxiliaryStyle (lo inyecta aleph-chat.js) ══════
 * Las opciones son parte del MENSAJE, jamás muebles de pantalla: viven dentro de la burbuja,
 * con los tokens de la casa (las custom properties SÍ cruzan el shadow boundary). */
export const CSS = `
  .ac-opts{margin:2px 0}
  .ac-opts .ac-opts-msg{margin:0 0 8px;font-size:12.5px;line-height:1.5;color:var(--ink,#F3ECE0)}
  .ac-opts .ac-opts-q{margin-top:9px}
  .ac-opts .ac-opts-preg{display:block;font-size:11.5px;color:var(--muted,#A89C8B);margin-bottom:5px}
  .ac-opts .ac-opts-row{display:flex;flex-wrap:wrap;gap:6px}
  .ac-opt{border:1px solid var(--line2,#4A433A);background:var(--paper2,#242120);color:var(--ink,#F3ECE0);
    border-radius:999px;padding:6px 13px;font:500 12px/1.25 inherit;cursor:pointer;text-align:left}
  .ac-opt:hover{border-color:var(--accent,#8B5CF6);color:var(--accent-deep,#B4B1FF)}
  .ac-opt.prim{background:var(--accent,#8B5CF6);border-color:var(--accent,#8B5CF6);color:#fff}
  .ac-opt.prim:hover{color:#fff;opacity:.92}
  .ac-opt.no{color:var(--muted,#A89C8B)}
  /* elegida MARCADA · el resto APAGADO — la conversación conserva lo que se eligió */
  .ac-opts[data-cerrada="1"] .ac-opt,.ac-opts-row[data-cerrada="1"] .ac-opt{cursor:default}
  .ac-opt[data-elegida="1"]{border-color:var(--accent,#8B5CF6);color:var(--accent-deep,#B4B1FF);
    background:var(--accent-soft,rgba(139,92,246,.15))}
  .ac-opt[data-elegida="1"]::before{content:"✓";margin-right:5px;font-weight:500}
  .ac-opt[data-apagada="1"]{opacity:.38;pointer-events:none}
  .ac-opt[data-marcada="1"]{border-color:var(--accent,#8B5CF6);color:var(--accent-deep,#B4B1FF)}
  /* producto: el encabezado del entregable sobre sus botones nativos */
  .ac-opts .ac-prod{display:flex;align-items:center;gap:8px;border:1px solid var(--line,#3A342D);
    background:var(--paper2,#242120);border-radius:10px;padding:8px 11px;margin-bottom:9px;font-size:12px}
  .ac-opts .ac-prod .ac-prod-t{flex:1;min-width:0;color:var(--ink,#F3ECE0);font-weight:500;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .ac-opts .ac-prod .ac-prod-k{flex:none;font-size:10.5px;color:var(--faint,#897F70);
    border:1px solid var(--line2,#4A433A);border-radius:999px;padding:1px 8px}
  /* aprobar: el plan REAL, desplegado por [Ver qué va a hacer] */
  .ac-plan{margin:9px 0 0;padding:9px 11px;border-left:2px solid var(--accent,#8B5CF6);
    background:var(--paper2,#242120);border-radius:0 9px 9px 0}
  .ac-plan b{display:block;font-size:11px;color:var(--muted,#A89C8B);margin-bottom:5px;font-weight:500}
  .ac-plan ol{margin:0;padding-left:17px} .ac-plan li{font-size:12px;line-height:1.5;color:var(--ink,#F3ECE0)}
  /* el DESENLACE — nunca un botón que se toca y no pasa nada */
  .ac-fin{display:flex;align-items:flex-start;gap:7px;margin-top:8px;font-size:12px;line-height:1.45;
    border-radius:9px;padding:7px 10px;border:1px solid var(--line,#3A342D);background:var(--paper2,#242120)}
  .ac-fin .ac-fin-ic{flex:none}
  .ac-fin.ok{border-color:rgba(52,211,153,.42)} .ac-fin.ok .ac-fin-ic{color:var(--green,#34D399)}
  .ac-fin.no{border-color:var(--line2,#4A433A);color:var(--muted,#A89C8B)}
  .ac-fin .ac-fin-ev{display:block;font-size:11px;color:var(--faint,#897F70);margin-top:2px;word-break:break-word}
  /* la honestidad cuando el destino NO existe: texto, jamás un botón falso */
  .ac-opts .ac-sincamino{margin:7px 0 0;font-size:11.5px;color:var(--faint,#897F70);line-height:1.45}
`;

/* ══ EL RENDER ════════════════════════════════════════════════════════════════════════
 * montar(chat, opts) → { emitir(name, args), destinos }
 *
 * @param chat   controlador de aleph-chat (necesita .bind, .card, .user, .say, .vitals…).
 * @param opts.lang       "es" | "en" (se relee en cada emisión si viene como función).
 * @param opts.destinos   el CABLEADO REAL de la superficie. Una acción sin su destino
 *                        cableado NO SE PINTA: se dice honesto (regla de caminoDe).
 * @param opts.onRespuesta (texto) → void — T1: el label elegido entra como MENSAJE del humano.
 */
export function montar(chat, opts) {
  opts = opts || {};
  const D = opts.destinos || {};
  const lang = () => {
    const l = typeof opts.lang === "function" ? opts.lang() : opts.lang;
    return l === "en" ? "en" : "es";
  };
  const tr = (k) => T(lang(), k);
  let seq = 0;

  /* Un botón sólo se pinta si su destino EXISTE y es una función. Pintado ≠ cableado:
   * la mitad del producto es el botón, la otra mitad es que haga algo. */
  const cableado = (k) => typeof D[k] === "function";

  /* UNA OPCIÓN APAGADA NO SE VUELVE A TOCAR — y no alcanza con el CSS.
   * `pointer-events:none` frena el dedo, pero no frena un `.click()` programático (un script,
   * una extensión, una vara). Si la única defensa es visual, "ya decidí que NO" se puede
   * volver a disparar sin que nadie lo note. La puerta se cierra en el HANDLER: cerrado es
   * cerrado. Se cierra por FILA (una pregunta contestada) o por CAJA (una acción decidida),
   * porque un mensaje con dos preguntas no puede quedar mudo al contestar la primera. */
  function cerrada(btn) {
    if (!btn || !btn.closest) return false;
    const fila = btn.closest(".ac-opts-row"), caja = btn.closest(".ac-opts");
    return (fila && fila.getAttribute("data-cerrada") === "1") ||
           (caja && caja.getAttribute("data-cerrada") === "1");
  }
  function boton(cls, label, onClick) {
    return '<button type="button" class="ac-opt ac-action' + (cls ? " " + cls : "") +
      '" data-ac-id="' + chat.bind((btn) => { if (cerrada(btn)) return; onClick(btn); }) + '">' +
      esc(label) + "</button>";
  }

  /** Marca la elegida y apaga el resto — dentro de su propia pregunta (la FILA). */
  function cerrarGrupo(btn, marcarSolo) {
    const grupo = btn && btn.closest ? btn.closest(".ac-opts-row") : null;
    if (!grupo) return;
    const todos = grupo.querySelectorAll(".ac-opt");
    for (let i = 0; i < todos.length; i++) {
      if (todos[i] === btn) todos[i].setAttribute("data-elegida", "1");
      else if (!marcarSolo) todos[i].setAttribute("data-apagada", "1");
    }
    grupo.setAttribute("data-cerrada", "1");
  }
  /** Apaga TODA la caja (las acciones no vuelven a estar disponibles tras decidir). */
  function cerrarCaja(btn, elegido) {
    const caja = btn && btn.closest ? btn.closest(".ac-opts") : null;
    if (!caja) return null;
    const todos = caja.querySelectorAll(".ac-opt");
    for (let i = 0; i < todos.length; i++) {
      if (todos[i] === btn && elegido !== false) todos[i].setAttribute("data-elegida", "1");
      else todos[i].setAttribute("data-apagada", "1");
    }
    caja.setAttribute("data-cerrada", "1");
    return caja;
  }

  /** El DESENLACE, siempre: hecho con evidencia, o causa + camino. Jamás silencio. */
  function desenlace(caja, res) {
    const d = document.createElement("div");
    const ok = !!(res && res.ok);
    d.className = "ac-fin " + (ok ? "ok" : "no");
    const ic = ok ? "✓" : "·";
    const txt = String((res && (res.texto || res.causa)) || (ok ? "" : tr("des.cancelado")));
    d.innerHTML = '<span class="ac-fin-ic" aria-hidden="true">' + ic + "</span><span>" + esc(txt) +
      (res && res.evidencia ? '<span class="ac-fin-ev">' + esc(String(res.evidencia)) + "</span>" : "") + "</span>";
    if (caja) caja.appendChild(d); else chat.card(d.outerHTML);
    try { chat.scrollDown(); } catch (e) {}
  }

  /** latido visible → handler real → desenlace SIEMPRE (hecho, o causa + camino). */
  function correr(btn, latido, run) {
    const caja = cerrarCaja(btn, true);
    chat.vitals(latido);
    let p;
    try { p = Promise.resolve(run()); }
    catch (e) { p = Promise.reject(e); }
    p.then((res) => {
      chat.clearVitals();
      if (res === false) { desenlace(caja, { ok: false }); return; }
      desenlace(caja, res && typeof res === "object" ? res : { ok: true, texto: res == null ? "" : String(res) });
    }).catch((e) => {
      chat.clearVitals();
      // fallo con CAUSA, y si la superficie sabe el camino, con camino (nunca una pared)
      const causa = String((e && e.message) || e);
      chat.errorCard(causa, { actions: (D.caminoDeError ? D.caminoDeError(e) : []) || [] });
    });
  }

  /* ── T1 · preguntar_opciones ─────────────────────────────────────────────────────── */
  function renderPreguntar(d) {
    const estado = d.preguntas.map((q) => (q.tipo === "multi" ? [] : null));
    const total = d.preguntas.length;
    let enviado = false;

    const entregar = () => {
      if (enviado) return; enviado = true;
      const partes = d.preguntas.map((q, i) => {
        const r = estado[i];
        const val = Array.isArray(r) ? r.join(", ") : r;
        return total > 1 ? q.pregunta + ": " + val : val;
      });
      const texto = partes.join(" · ");
      // EL TRUCO DEL TRANSCRIPT: el label entra como MENSAJE DEL HUMANO, no como tool result.
      // Para el modelo, el humano simplemente contestó — cero lógica especial.
      chat.user(texto);
      if (typeof opts.onRespuesta === "function") opts.onRespuesta(texto);
    };
    const listo = () => estado.every((r) => (Array.isArray(r) ? r.length > 0 : !!r));

    let html = '<div class="ac-opts" data-familia="preguntar_opciones" data-preguntas="' + total + '">' +
      '<p class="ac-opts-msg">' + esc(d.mensaje) + "</p>";
    d.preguntas.forEach((q, i) => {
      html += '<div class="ac-opts-q" data-tipo="' + q.tipo + '">';
      if (total > 1 || q.pregunta !== d.mensaje) html += '<span class="ac-opts-preg">' + esc(q.pregunta) + "</span>";
      html += '<div class="ac-opts-row">';
      q.opciones.forEach((op) => {
        html += boton("", op.label, (btn) => {
          if (enviado) return;
          if (q.tipo === "multi") {
            const on = btn.getAttribute("data-marcada") === "1";
            btn.setAttribute("data-marcada", on ? "0" : "1");
            const set = estado[i];
            const k = op.valor;
            const at = set.indexOf(k);
            if (on) { if (at >= 0) set.splice(at, 1); } else if (at < 0) set.push(k);
            return;
          }
          estado[i] = op.valor;
          cerrarGrupo(btn, false);
          if (listo()) entregar();
        });
      });
      if (q.tipo === "multi") {
        html += boton("prim", tr("multi.ok"), (btn) => {
          if (enviado || !estado[i].length) return;
          const fila = btn.closest(".ac-opts-row");
          if (fila) { const bs = fila.querySelectorAll(".ac-opt");
            for (let k = 0; k < bs.length; k++) {
              if (bs[k].getAttribute("data-marcada") === "1") bs[k].setAttribute("data-elegida", "1");
              else bs[k].setAttribute("data-apagada", "1");
            }
            fila.setAttribute("data-cerrada", "1");   // confirmada: no se re-abre
          }
          if (listo()) entregar();
        });
      }
      html += "</div></div>";
    });
    html += "</div>";
    chat.card(html);
  }

  /* ── T2 · accion_de_producto ─────────────────────────────────────────────────────── */
  const LATIDO_ACC = { enviar: "lat.enviando", editar: "lat.abriendo", descargar: "lat.descargando",
    abrir_en_sala: "lat.abriendo", aplicar: "lat.aplicando", ver_diff: "lat.abriendo" };

  function renderProducto(d) {
    const p = d.producto;
    const pintables = d.acciones.filter((k) => cableado(k));
    let html = '<div class="ac-opts" data-familia="accion_de_producto" data-tipo="' + esc(p.tipo) + '">' +
      '<p class="ac-opts-msg">' + esc(d.mensaje) + "</p>" +
      '<div class="ac-prod"><span class="ac-prod-t">' + esc(p.titulo) + '</span>' +
      '<span class="ac-prod-k">' + esc(p.tipo) + "</span></div>";
    if (pintables.length) {
      html += '<div class="ac-opts-row">';
      pintables.forEach((k, i) => {
        html += boton(i === 0 ? "prim" : "", tr("acc." + k), (btn) => correr(btn, tr(LATIDO_ACC[k] || "lat.abriendo"), () => D[k](p, d)));
      });
      html += "</div>";
    }
    // JAMÁS UN BOTÓN FALSO: lo que no está cableado se dice, no se pinta.
    const sin = d.acciones.filter((k) => !cableado(k));
    if (sin.length) html += '<p class="ac-sincamino">' + esc(tr("des.sin_camino")) + " (" + esc(sin.join(", ")) + ")</p>";
    html += "</div>";
    chat.card(html);
  }

  /* ── T3 · camino_de_falta ────────────────────────────────────────────────────────── */

  /* [FIX-P8] LAS FALTAS DE MODELO TIENEN SU CAMINO CANÓNICO, Y ATERRIZA EN LA CATEGORÍA.
   *
   * «No puedo ver imágenes» ya emitía `sin_vision` y ya ofrecía un botón: el problema era
   * dónde caía. Cada superficie lo cableaba a su manera y todas terminaban en la pantalla
   * genérica de configuración — dejando a la persona a buscar sola qué apretar, que es
   * media honestidad. El Centro de Modelos tiene la categoría exacta, así que el destino
   * de estas cuatro causas lo pone ACÁ, el contrato compartido, para las DOS superficies
   * (el Guía y la Sala) de una sola vez.
   *
   * Gana sobre el cableado de la superficie A PROPÓSITO y sólo para estas cuatro: son
   * faltas de MODELO y ahora existe un lugar exacto al que llevarlas. Todo el resto
   * (`falta_key`, `premium`, `cli_no_instalado`…) sigue saliendo de `D.camino`, intacto.
   */
  const CAT_DE_FALTA = { sin_vision: "vision", sin_memoria: "embeddings",
                         sin_codigo: "codigo", sin_razonamiento: "razonamiento" };
  const LABEL_FALTA = {
    sin_vision: { es: "Conectar un modelo de visión", en: "Connect a vision model" },
    sin_memoria: { es: "Conectar la memoria", en: "Connect memory" },
    sin_codigo: { es: "Conectar un modelo de código", en: "Connect a code model" },
    sin_razonamiento: { es: "Conectar un modelo que razone", en: "Connect a reasoning model" },
  };

  function caminoDeModelo(causa) {
    const cat = CAT_DE_FALTA[String(causa || "")];
    if (!cat) return null;
    const et = LABEL_FALTA[causa];
    return {
      label: lang() === "en" ? et.en : et.es,
      run() {
        let href;
        try {
          // El EMBUDO compartido si está (brain-status.js); si no, la URL directa. Las dos
          // formas llevan al MISMO lugar — el fallback existe para superficies que no
          // cargan el chip, no para inventar un destino alternativo.
          href = (window.AlephBrain && window.AlephBrain.setupHrefPorCausa)
            ? window.AlephBrain.setupHrefPorCausa(causa, { returnTo: location.pathname })
            : null;
        } catch (e) { href = null; }
        if (!href) {
          const sub = /\/(sala|cuarto|metodo|inspeccion|conexiones|chat|modelos)\//.test(location.pathname) ? "../" : "";
          href = sub + "Modelos.dc.html?cat=" + encodeURIComponent(cat) +
                 "&return=" + encodeURIComponent(location.pathname + location.search);
        }
        location.href = href;
        return { ok: true, texto: lang() === "en" ? "Taking you to Models." : "Te llevo a Modelos." };
      },
    };
  }

  function renderFalta(d) {
    // El BOTÓN sale de caminoDe (el diccionario único), no del modelo. Sin camino real →
    // texto honesto, jamás un botón falso.
    const cam = caminoDeModelo(d.causa) || (cableado("camino") ? D.camino(d.causa, d.pieza) : null);
    let html = '<div class="ac-opts" data-familia="camino_de_falta" data-causa="' + esc(d.causa) + '">' +
      '<p class="ac-opts-msg">' + esc(d.mensaje) + "</p>";
    if (cam && cam.label && typeof cam.run === "function") {
      html += '<div class="ac-opts-row">' +
        boton("prim", cam.label, (btn) => correr(btn, tr("lat.yendo"), () => cam.run())) +
        (cam.extra && cam.extra.label && typeof cam.extra.run === "function"
          ? boton("", cam.extra.label, (btn) => correr(btn, tr("lat.abriendo"), () => cam.extra.run())) : "") +
        "</div>";
    } else {
      html += '<p class="ac-sincamino">' + esc(tr("des.sin_camino")) + "</p>";
    }
    html += "</div>";
    chat.card(html);
  }

  /* ── T4 · aprobar ────────────────────────────────────────────────────────────────── */
  function renderAprobar(d) {
    if (!cableado("aprobar")) {
      // sin cableado no hay aprobación posible: se dice, no se finge un gate
      chat.card('<div class="ac-opts" data-familia="aprobar"><p class="ac-opts-msg">' + esc(d.mensaje) +
        '</p><p class="ac-sincamino">' + esc(tr("des.sin_camino")) + "</p></div>");
      return;
    }
    const idPlan = "acp" + (++seq);
    let html = '<div class="ac-opts" data-familia="aprobar" data-consecuencia="' + esc(d.consecuencia) + '">' +
      '<p class="ac-opts-msg">' + esc(d.mensaje) + "</p>" +
      '<div class="ac-prod"><span class="ac-prod-t">' + esc(d.resumen) + '</span>' +
      '<span class="ac-prod-k">' + esc(d.consecuencia) + "</span></div>" +
      '<div class="ac-opts-row">' +
      // EL TAP ES EL CONSENTIMIENTO: nada corre antes.
      boton("prim", tr("apr.ok"), (btn) => correr(btn, tr("lat.aprobando"), () => D.aprobar(d))) +
      // [Ver qué va a hacer] NO cierra la caja: sigue pudiendo aprobar o rechazar después.
      boton("", tr("apr.ver"), (btn) => {
        btn.setAttribute("data-marcada", "1");
        const caja = btn.closest(".ac-opts"); if (!caja || caja.querySelector('[data-plan="' + idPlan + '"]')) return;
        const box = document.createElement("div");
        box.className = "ac-plan"; box.setAttribute("data-plan", idPlan);
        box.innerHTML = "<b>" + esc(tr("des.plan")) + "</b><ol>" +
          d.plan.map((s) => "<li>" + esc(s) + "</li>").join("") + "</ol>";
        caja.appendChild(box);
        try { chat.scrollDown(); } catch (e) {}
        if (cableado("verPlan")) { try { D.verPlan(d); } catch (e) {} }
      }) +
      boton("no", tr("apr.no"), (btn) => {
        cerrarCaja(btn, true);
        const caja = btn.closest(".ac-opts");
        // [No] CANCELA DE VERDAD: nada corrió, y se dice.
        let res = { ok: false, texto: tr("des.cancelado") };
        if (cableado("rechazar")) { try { const r = D.rechazar(d); if (r && typeof r === "object") res = r; } catch (e) {} }
        desenlace(caja, res);
      }) +
      "</div></div>";
    chat.card(html);
  }

  /* ── T5 · redirigir ──────────────────────────────────────────────────────────────── */
  function renderRedirigir(d) {
    const key = d.destino === "pieza" ? "ir.pieza" : "ir." + d.destino;
    let html = '<div class="ac-opts" data-familia="redirigir" data-destino="' + esc(d.destino) + '">' +
      '<p class="ac-opts-msg">' + esc(d.mensaje) + "</p>";
    if (cableado("ir")) {
      html += '<div class="ac-opts-row">' +
        boton("prim", tr(key), (btn) => correr(btn, tr("lat.yendo"), () => D.ir(d.destino, d.pieza_id, d))) +
        "</div>";
    } else {
      html += '<p class="ac-sincamino">' + esc(tr("des.sin_camino")) + "</p>";
    }
    html += "</div>";
    chat.card(html);
  }

  const RENDER = {
    preguntar_opciones: renderPreguntar,
    accion_de_producto: renderProducto,
    camino_de_falta: renderFalta,
    aprobar: renderAprobar,
    redirigir: renderRedirigir,
  };

  /**
   * emitir(name, args, {prosa}) → {ok:true} | {ok:false, error}
   * `prosa` = el texto que el modelo escribió en ESE turno; se usa para detectar la
   * afirmación prematura (§ prohibición de contrato) y gritarla.
   */
  function emitir(name, args, o) {
    o = o || {};
    const v = validar(name, args, { lang: lang() });
    if (!v.ok) {
      // §4h · fallo VISIBLE: el humano no ve opciones rotas, pero el defecto no se traga.
      console.error("[opciones] " + name + " rechazada — " + v.error);
      return v;
    }
    if (o.prosa && afirmacionPrematura(o.prosa, name)) {
      anotarViolacion(name + ": el turno afirma la acción ANTES del tap — el botón es el consentimiento");
    }
    RENDER[v.datos.familia](v.datos);
    return { ok: true, datos: v.datos };
  }

  return { emitir, validar, extraer, cableado, destinos: D };
}

export default {
  OPCIONES_TOOLS, OPCIONES_TOOL_NAMES, CLIENT_TOOLS, CLIENT_TOOL_NAMES,
  doctrinaSistema, validar, extraer, montar, CSS, TOPES,
};
