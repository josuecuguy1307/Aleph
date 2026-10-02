/* cuarto.guide.belt.js — EL CINTURÓN cuarto-ui (el "flaco"): las 22 tools de SUPERFICIE
 * que el modelo-guía del Cuarto viste cuando opera en el contexto del Cuarto.
 *
 * T5 · EL GUÍA PADRINO (CUARTO HONESTO §6): el belt crece de 16→21 con las tools que le
 * faltaban al padrino — leer_estado + probar_ahora (el semáforo §1 vía Motor de Verdad),
 * equipar_catalogo (el carril LIBRE curado), quitar_pieza y cerrar_inspector. Cada una
 * despacha a un handler que YA existe (cero lógica nueva de dominio).
 *
 * ARQUITECTURA (elegida por persona usuaria): COPILOTO CLIENTE · paridad-mano LITERAL.
 *   El browser corre el loop de tool-calling (cuarto.guide.js) contra el modelo-guía y
 *   EJECUTA cada tool_call llamando el MISMO handler JS que el mouse del usuario
 *   (window.__cuarto.* / los handlers del inspector). Este módulo NO ejecuta nada: sólo
 *   DECLARA el contrato (schemas OpenAI-function) + el framing que hace que el modelo se
 *   auto-limite. La ejecución + los gates viven en cuarto.guide.js (el despacho).
 *
 * LAS 4 REGLAS INVIOLABLES (definición de "flaco"):
 *   1. Paridad-mano: cada tool despacha al handler existente del camino manual — cero
 *      camino privilegiado, cero endpoint nuevo por-tool.
 *   2. Todo visible: cada Mano se anima en el canvas con la coreografía existente.
 *   3. Propuesta ≠ ejecución AL MUNDO (evolución T5): el guía SÍ equipa piezas del catálogo
 *      LIBRE (internas/keyless, curadas) y organiza/mueve/quita — eso NO sale al mundo, es
 *      suyo (auto-resolvible §0). Pero conectar-con-credencial, construir un MCP premium o
 *      cualquier acción de mundo (enviar/pagar/ejecutar) SIEMPRE queda en propuesta o ABRE el
 *      flujo que espera el OK + la llave del humano. El guía JAMÁS completa una conexión con
 *      credencial, una construcción de MCP ni una acción al mundo solo.
 *   4. Cero mundo real: este belt NO CONTIENE tools de mundo real — no las bloquea: no
 *      existen en él. No toca credenciales. Para actuar sobre el mundo está La Sala.
 *
 * Fuente ÚNICA de verdad: estos schemas se mandan al modelo-guía (qué puede pedir) Y son
 * el índice del despacho (qué sabe ejecutar el browser). Si un nombre no está acá, el
 * modelo no lo puede llamar y el despacho no lo puede ejecutar.
 */

// [FIX-P7] OPCIONES POR TURNO — la 5ª familia. NO son tools de superficie: no miran, no
// mueven y no abren nada. Son la FORMA del mensaje cuando la próxima entrada del humano es
// predecible y enumerable. Su contrato (schemas + doctrina + validador + render) vive en la
// capa transversal ../chat/opciones.js, compartida con La Sala: una sola definición.
import { CLIENT_TOOLS, CLIENT_TOOL_NAMES, doctrinaSistema } from "../chat/opciones.js";

// Familias — puro metadato (UI + docs); el orden es el del contrato §2.
export const GUIDE_FAMILIES = {
  ojos: ["ver_cuarto", "inspeccionar_pieza", "estado_conexiones", "leer_estado", "probar_ahora"],
  manos: ["mover_pieza", "organizar_cuarto", "enfocar", "senalar", "quitar_pieza", "cerrar_inspector"],
  puertas: ["buscar_catalogo_local", "buscar_registro", "proponer_pieza", "equipar_catalogo", "conectar_pieza",
            "abrir_construccion_mcp", "elegir_cerebro", "gestionar_agente", "ir_a_sala"],
  guia: ["tour", "explicar"],
  opciones: CLIENT_TOOL_NAMES.slice(),
};

// Las tools que ABREN un flujo sensible (nunca lo completan) — el despacho las trata con
// la semántica "abrir-no-completar" y el harness §4·check2 verifica que ninguna complete sola.
export const PUERTA_TOOLS = new Set([
  "conectar_pieza", "abrir_construccion_mcp", "elegir_cerebro", "gestionar_agente", "ir_a_sala",
]);

const fn = (name, description, properties = {}, required = []) => ({
  type: "function",
  function: {
    name, description,
    parameters: { type: "object", properties, required, additionalProperties: false },
  },
});

/** GUIDE_TOOLS — 22 tools en 4 familias (Ojos 5 · Manos 6 · Puertas 9 · Guía 2). */
export const GUIDE_TOOLS = [
  // ── OJOS — leer lo que el usuario ve (read-only, cero mutación) ──────────────────
  fn("ver_cuarto",
     "Mira el estado ACTUAL del Cuarto del usuario: qué piezas hay, cómo están conectadas al Núcleo, qué falta y qué modelo tiene el agente. Sólo lee — no cambia nada. Conviene usarla SIEMPRE antes de mover o proponer, para trabajar sobre el estado real."),
  fn("inspeccionar_pieza",
     "Abre el inspector de una pieza (el mismo panel que si el usuario la clickeara) y devuelve su detalle: qué es, sus tools, su estado de conexión.",
     { id: { type: "string", description: "id de la pieza (de ver_cuarto)" } }, ["id"]),
  fn("estado_conexiones",
     "Reporta el estado HONESTO de las conexiones: viva / apagada / 🔒 (con la razón). Lee la detección existente, no la inventa. Sin id → todas.",
     { id: { type: "string", description: "opcional: una pieza específica" } }),
  fn("leer_estado",
     "Lee el estado de VERDAD (semáforo §1) de algo — una pieza, su conexión/MCP, una key o el modelo: uno de los 5 → probado 🟢 / detectado 🟡 (sin probar aún) / roto 🔴 (con la causa exacta) / no_configurado ⚪ / premium 🔒. Es la lectura BARATA cacheada (no dispara pruebas). Sirve para responder honesto «¿esto funciona?» sin inventar un verde. Para el modelo del agente, id='nucleo'.",
     { id: { type: "string", description: "id o nombre de la pieza (de ver_cuarto); 'nucleo' para el modelo del agente" } },
     ["id"]),
  fn("probar_ahora",
     "Dispara [Probar ahora]: corre la prueba REAL contra el Motor de Verdad (ping al modelo / handshake al MCP / validación de la key / auth del CLI) y devuelve el estado VERIFICADO con evidencia + timestamp. No cambia nada del mundo — es una prueba de lectura. Va cuando algo está 🟡 detectado y hace falta confirmar que sirve, o cuando el usuario pregunta si algo ya quedó bien.",
     { id: { type: "string", description: "id o nombre de la pieza a probar; 'nucleo' para el modelo del agente" } },
     ["id"]),

  // ── MANOS — mover la superficie (mismo camino de código que el mouse) ────────────
  fn("mover_pieza",
     "Mueve una pieza a una celda de la grilla — EXACTAMENTE el mismo arrastre que haría el usuario con el mouse (misma animación, mismo estado). Las coordenadas de grilla (gx, gy) salen de ver_cuarto.",
     { id: { type: "string" }, gx: { type: "integer" }, gy: { type: "integer" } },
     ["id", "gx", "gy"]),
  fn("organizar_cuarto",
     "Auto-ordena las piezas sueltas alrededor del Núcleo (el mismo 'ordenar' del layout). Útil cuando el Cuarto está desordenado o tras proponer varias piezas.",
     { criterio: { type: "string", enum: ["auto"], description: "por ahora solo 'auto'" } }),
  fn("enfocar",
     "Mueve la cámara / hace zoom. Con 'id' enfoca esa pieza; 'zoom' ajusta el nivel (in/out/fit/reset); 'entrar' entra al sub-Cuarto de una pieza-agente (zoom semántico). Es lo mismo que los botones de cámara del usuario.",
     { id: { type: "string", description: "opcional: pieza a enfocar" },
       zoom: { type: "string", enum: ["in", "out", "fit", "reset"] },
       entrar: { type: "boolean", description: "entrar al sub-Cuarto de la pieza-agente id" } }),
  fn("senalar",
     "Resalta una pieza con un pulso + una nota corta (tooltip en el HUD) para dirigir la atención del usuario. No cambia el estado; solo apunta.",
     { id: { type: "string" }, nota: { type: "string", description: "tooltip corto (una línea)" } },
     ["id"]),
  fn("quitar_pieza",
     "Quita una pieza del Cuarto — el mismo ✕ que el usuario. GATE intacto: si el agente está corriendo AHORA y la pieza es delicada, ABRE el pedido de confirmación (el usuario da el OK) en vez de sacarla; en cualquier otro caso la saca directo. Nunca corta una tarea en curso sin avisar.",
     { id: { type: "string" } }, ["id"]),
  fn("cerrar_inspector",
     "Cierra el inspector/closet abierto (y el panel de una pieza-agente si estuviera abierto) — el mismo cerrar que el usuario. Útil para despejar la vista después de mostrar o inspeccionar algo.",
     {}),

  // ── PUERTAS — abrir flujos existentes; JAMÁS completarlos ────────────────────────
  fn("buscar_catalogo_local",
     "Busca únicamente en el catálogo LOCAL: lo que ya está disponible en esta instalación, incluido lo que una ingesta anterior limpió y aceptó. No consulta el registro público y no dispara ingesta. Corresponde a pedidos como «las que ya tengo», «mi catálogo» o «lo disponible aquí». Una query vacía lista el catálogo local completo.",
     { query: { type: "string", description: "nombre o tipo a filtrar; vacío = todo el catálogo local" } }),
  fn("buscar_registro",
     "Busca únicamente en el REGISTRO PÚBLICO: lo que se podría traer. Esta tool dispara el proceso completo y visible leyendo → limpiando → clasificando → veredicto; sólo las entradas limpias aceptadas se añaden al catálogo local. Corresponde a pedidos como «qué podría traer» o «busca en el registro». Si el pedido sólo dice «catálogo/conectores» sin aclarar fuente, no se llama ninguna de las dos: se usa preguntar_opciones con exactamente [Mi catálogo] [El registro].",
     { query: { type: "string", description: "servicio, oficio o capacidad a buscar en el registro público" } },
     ["query"]),
  fn("proponer_pieza",
     "Arrastra una pieza FANTASMA como PROPUESTA para un servicio. La fantasma es INERTE: no se equipa, no se conecta, no ejecuta — es solo una sugerencia visible hasta que el usuario dé OK. NUNCA crea una pieza real. (Para colocar una pieza REAL del catálogo libre está equipar_catalogo.)",
     { servicio: { type: "string", description: "nombre del servicio a proponer (ej. 'Crossref', 'Zotero')" },
       nota: { type: "string", description: "por qué se propone (una línea)" } },
     ["servicio"]),
  fn("equipar_catalogo",
     "Equipa una pieza REAL del catálogo LIBRE curado (el carril free, SIN forjar). Comportamiento con el GATE adentro: si es interna/keyless la coloca REAL en el Cuarto; si el conector confiable pide una llave, ABRE su conexión para que el usuario pegue la credencial (el guía no la ve ni la completa); si necesita premium o el registro no lo tiene, se dice honesto y NO se forja nada. Es la herramienta para ARMAR el agente con piezas reales en modo delegar. Para conectar una pieza YA colocada está conectar_pieza; para construir un MCP que no existe (premium), abrir_construccion_mcp.",
     { servicio: { type: "string", description: "nombre del servicio/pieza a equipar (ej. 'Crossref', 'Wikipedia', 'arXiv')" },
       nota: { type: "string", description: "opcional: por qué se equipa (una línea para narrar)" } },
     ["servicio"]),
  fn("conectar_pieza",
     "ABRE el flujo de conexión existente de una pieza (OAuth 1-click / token / keyless). El flujo le pide la credencial AL USUARIO en su propio widget; el guía NUNCA la ve ni la transporta, y NUNCA completa la conexión solo — sólo la abre, y el usuario decide.",
     { id: { type: "string" } }, ["id"]),
  fn("abrir_construccion_mcp",
     "ABRE el panel de Inspeccionar/construir MCP con el objetivo puesto (servicio o URL). El gate y las formas corren igual que siempre; esta tool SÓLO abre — el usuario lo dispara y aprueba. El guía nunca construye ni equipa una pieza solo.",
     { servicio: { type: "string" }, url: { type: "string", description: "opcional: URL del MCP/API a inspeccionar" } }),
  fn("elegir_cerebro",
     "Abre el selector de modelo del agente y PROPONE/resalta la card del provider sugerido. El modelo activo se confirma al correr: aquí se propone, el usuario confirma.",
     { provider: { type: "string", description: "id del provider a proponer (ej. 'opus', 'oss', 'claude_cli')" } },
     ["provider"]),
  fn("gestionar_agente",
     "Guarda o carga el agente del usuario — el mismo save/load que los botones existentes. 'guardar' persiste el agente actual con el nombre dado; 'cargar' rehidrata un agente guardado.",
     { accion: { type: "string", enum: ["guardar", "cargar"] },
       nombre: { type: "string", description: "nombre del agente (guardar) o a cargar" } },
     ["accion"]),
  fn("ir_a_sala",
     "Cruza el puente Cuarto→Sala (el mismo botón existente) para probar el agente. Requiere que el agente esté guardado; si no lo está, avisa al usuario en vez de cruzar."),

  // ── GUÍA — didáctico ─────────────────────────────────────────────────────────────
  fn("tour",
     "Recorre el Cuarto enfocando + señalando las piezas en secuencia, explicando cada una. Para el usuario perdido que pide ver todo lo que tiene.",
     { tema: { type: "string", description: "opcional: 'piezas', 'conexiones', 'nucleo', 'todo'" } }),
  fn("explicar",
     "Explica en dos líneas qué ES una pieza y qué le FALTA (mismo texto que el inspector). Para responder «¿qué es esto?».",
     { id: { type: "string" } }, ["id"]),
];

/** Los nombres de SUPERFICIE — el whitelist del despacho (regla 4). Las 5 de OPCIONES NO
 *  entran acá a propósito: no despachan a ningún handler del Cuarto, se resuelven antes en
 *  el loop. Mezclarlas aflojaría justo la lista que existe para no aflojarse. */
export const GUIDE_TOOL_NAMES = GUIDE_TOOLS.map((t) => t.function.name);

/** guideTools(lang) — lo que REALMENTE se le manda al modelo-guía: las 22 de superficie
 *  + las tools DEL CLIENTE en el idioma de la sesión. Es la fuente única: si un nombre no
 *  sale de acá, el modelo no lo puede llamar y el despacho no lo puede ejecutar. */
export function guideTools(lang) {
  return GUIDE_TOOLS.concat(CLIENT_TOOLS(lang === "en" ? "en" : "es"));
}

/** Framing del modelo-guía: le dice su rol Y lo auto-limita (defensa en profundidad — el
 *  despacho lo enforcea estructuralmente, pero el modelo también debe SABER que no puede
 *  cruzar la línea). Bilingüe por `lang`. */
// T5 · LOS 3 MODOS del padrino (§6). Default de la era: DELEGAR. Se inyecta al final del framing.
export const MODE_FRAMING = {
  es: {
    delegar: "MODO ACTIVO · DELEGAR (el default de la era): el trabajo lo arma el guía — equipar del catálogo libre, ordenar, proponer, y narrar en una línea qué se hizo y por qué. Avanzar sin pedir permiso para lo auto-resolvible (keyless, curado); preguntar SOLO antes de lo que necesita al humano (una llave, un login, una decisión) o de lo que sale al mundo. Si hay dos caminos, preguntar natural: «¿lo hago yo o prefiere hacerlo la persona?».",
    guiar: "MODO ACTIVO · PASO A PASO: nada se hace por el usuario — hay que llevarlo de la mano. Abrir el lugar, SEÑALAR la pieza o el botón, decir en una línea qué hay que tocar, y ESPERAR. Una acción por vez; confirmar antes de seguir. Para dirigir están senalar/enfocar/inspeccionar_pieza; no se equipa ni se mueve nada salvo pedido explícito.",
    explicar: "MODO ACTIVO · EXPLICAR: se responde desde la base de conocimiento (poder SABE) y se MUESTRA dónde está en la UI (señalar/navegar/abrir el lugar). El armado no se cambia. Si el usuario prefiere que lo haga el guía, ofrecer el paso a DELEGAR.",
  },
  en: {
    delegar: "ACTIVE MODE · DELEGATE (the era's default): build the work yourself — equip from the free catalog, organize, propose, and NARRATE in one line what you did and why. Move ahead without asking for the auto-resolvable (keyless, curated); ask ONLY before what needs the human (a key, a login, a decision) or reaches the world. When there are two ways, ask naturally: “should I do it or you?”.",
    guiar: "ACTIVE MODE · STEP BY STEP: don't do it for the user — guide their hand. Open the place, POINT at the piece or button, tell them in one line what to touch, and WAIT. One action at a time; confirm before continuing. Use senalar/enfocar/inspeccionar_pieza to direct; don't equip or move yourself unless asked.",
    explicar: "ACTIVE MODE · EXPLAIN: answer from your knowledge base (KNOW power) and SHOW where it is in the UI (point/navigate/open the place). Don't change the build. If the user wants you to do it, offer to switch to DELEGATE.",
  },
};

/* T6 · §9 — JAULA RECORTADA: fuera las reglas redundantes (el belt ya se auto-describe en sus
 * schemas) y el tono enlatado. Quedan SOLO los límites duros: gates jamás auto-aprobados,
 * jamás completar una credencial, jamás un verde inventado. (Frontier-only NO es regla de
 * prompt: lo enforcea el selector — esFrontierGuia — estructuralmente.) Es un modelo frontier:
 * que converse natural, no que llene formularios.
 *
 * [FIX-P10 §4] EL REGISTRO NO SE INSTRUYE — se ESPEJA, y eso el modelo lo hace solo.
 *   Acá NO hay ninguna regla de estilo: ni «neutro», ni una variante del castellano, ni una
 *   lista de palabras prohibidas. Tres razones, y las tres se pagaron:
 *     1. Instruir el registro vuelve al modelo RÍGIDO. Un frontier ya acompaña el registro de
 *        quien le escribe; decirle cómo hablar lo hace hablar como el prompt en vez de como su
 *        interlocutor, que es exactamente el defecto que se quería arreglar.
 *     2. Lo que SÍ importa es cómo está escrito ESTE texto: el modelo copia el registro del
 *        prompt antes que cualquier instrucción. Así que la cura no es una regla — es que el
 *        system y las descripciones de las tools estén escritos en IMPERSONAL, sin interpelar
 *        a nadie. Impersonal el prompt ⇒ prosa sin sesgo de registro, y libre para espejar.
 *     3. Una lista de tokens prohibidos, escrita acá, METE esos tokens en el prompt — y hace
 *        del system el primer rojo de su propia vara. Pasó dos veces (con la muletilla y con
 *        los pronombres) antes de entenderlo.
 *   Queda UNA línea, de categoría y en positivo (acompañar al humano), sin nombrar nada.
 *
 * [FIX-P10 §6] MENOS JAULA, NO MÁS. Es frontier: cada línea que se agregue acá tiene que ser
 *   un LÍMITE que el código no pueda enforcear solo. Todo lo demás —cómo saluda, cuánto
 *   explica, en qué orden, con qué registro— es suyo. */
export function buildGuideSystem(lang = "es", opts = {}) {
  const L = lang === "en" ? "en" : "es";
  const modeLine = MODE_FRAMING[L][(opts && opts.mode) || "delegar"] || MODE_FRAMING[L].delegar;
  if (lang === "en") {
    return [
      "Role: the Room's guide (Aleph · el Cuarto) — a hands-on copilot that helps the user build and understand their AI agent by moving the room itself: equip, organize, point, test, explain. Real-world actions (send, pay, execute) happen in La Sala, not here. Let the room show the work.",
      "Follow the human's lead: the way they write sets the tone of the conversation.",
      "HARD LIMITS — the only non-negotiables: (1) you never COMPLETE anything gated or world-reaching — connecting with a credential, building a premium MCP, sending/paying/executing: you only OPEN the flow and the user approves; a gate is never auto-approved. (2) You never see, ask for, or carry a credential. (3) You never claim something works without reading or testing it (leer_estado / probar_ahora) — no invented greens.",
      modeLine,
      doctrinaSistema("en", { superficie: "guia" }),
    ].join("\n");
  }
  return [
    "Rol: el guía del Cuarto (Aleph) — un copiloto de manos que ayuda al usuario a armar y entender su agente moviendo la habitación misma: equipar, ordenar, señalar, probar, explicar. Las acciones de mundo real (enviar, pagar, ejecutar) viven en La Sala, no aquí. Que la habitación muestre el trabajo.",
    "El tono lo marca el humano: acompañarlo.",
    "LÍMITES DUROS — lo único innegociable: (1) nada gateado ni que salga al mundo se COMPLETA aquí — conectar con credencial, construir un MCP premium, enviar/pagar/ejecutar: se ABRE el flujo y el usuario aprueba; un gate jamás se auto-aprueba. (2) Una credencial no se ve, no se pide y no se transporta. (3) Nada se declara funcionando sin leerlo o probarlo (leer_estado / probar_ahora) — cero verdes inventados.",
    modeLine,
    doctrinaSistema("es", { superficie: "guia" }),
  ].join("\n");
}
