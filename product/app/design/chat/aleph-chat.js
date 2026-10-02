/* aleph-chat.js — LA CAPA DE CHAT COMPARTIDA (una sola implementación, i18n en un solo lugar).
 *
 * Envuelve `deep-chat` 2.5.0 (MIT, vendorizado en ../vendor/deepChat.bundle.js) y le pone
 * ENCIMA el contrato de Aleph: signos vitales, cards de acción, logos reales de marca,
 * errores con camino y ofertas contextuales. La misma pieza monta en DOS superficies:
 *
 *   · EL GUÍA  (panel flotante del Cuarto)  — surface:"guia"
 *   · LA SALA  (composer + franja de mensajes) — surface:"sala"
 *
 * POR QUÉ deep-chat (ver spikes/deep-chat/VEREDICTO.md — probado en WebKit real):
 *   · CONTAINER-RELATIVE por Shadow DOM: a 300px de contenedor el input conserva ~240px
 *     usables. Ése era el bug de raíz de La Sala (composer a 31px porque la media-query
 *     miraba el VIEWPORT y los controles se acumulaban sin presupuesto).
 *   · streaming SSE incremental, adjuntos por botón/drag/paste, y cards HTML con handlers.
 *
 * ── DOS LEYES QUE NO SE NEGOCIAN ────────────────────────────────────────────────────
 *
 * 1) LOCAL-FIRST. deep-chat, por default, inyecta un <link> a fonts.googleapis.com. Está
 *    GUARDADO: `attemptAppendStyleSheetToHead` sólo inyecta si el fontFamily es el stack
 *    Inter por default. Seteando `font-family` inline en el <deep-chat> la inyección NO
 *    ocurre (spike: 0 requests externos al cargar Y durante el streaming). Acá eso NO se
 *    deja a la memoria de nadie: `FONT_STACK` se aplica siempre en `mount()` y `assertLocalFirst()`
 *    lo verifica en runtime. Si alguien lo saca, se rompe RUIDOSO (regla §4h: fallo visible,
 *    jamás mudo), no en silencio con un request a Google.
 *
 * 2) TODO LO VISIBLE VIVE EN `STRINGS`. ES/EN en lockstep, un solo lugar, las dos superficies.
 *    Los strings SECUNDARIOS de deep-chat que sí son configurables (tooltips de enviar /
 *    adjuntar / micrófono / cámara) se pisan por props acá mismo. Los que el componente deja
 *    hardcodeados en inglés y NO exponen prop están declarados en `README.md` de esta carpeta.
 *
 * ── DÓNDE VIVE EL DOM ────────────────────────────────────────────────────────────────
 * deep-chat renderiza dentro de su Shadow DOM. El CSS de la página NO entra: todo el estilo
 * de nuestras cards viaja por `auxiliaryStyle` (string CSS que deep-chat inyecta en el shadow
 * root) y los handlers por `htmlClassUtilities`. Por eso las cards conservan EXACTAMENTE los
 * mismos nombres de clase que tenían en light DOM (.errcard, .acts, .gate…): la vara sólo
 * cambia por dónde resuelve el nodo, no qué afirma.
 */

/* [FIX-P7] OPCIONES POR TURNO — el contrato vive en opciones.js; acá sólo entra su CSS.
 * Tiene que entrar por ESTA vía y no por el `auxiliaryStyle` de cada superficie: re-asignar
 * auxiliaryStyle después del montaje REINICIA el render de deep-chat (y con él se van los
 * mensajes ya pintados), así que el estilo de las opciones no se puede inyectar tarde. Acá
 * viaja con el resto, una vez, para las DOS superficies — y ninguna se puede olvidar. */
import { CSS as OPCIONES_CSS } from "./opciones.js";
import { CSS as CONEXION_INLINE_CSS } from "./conexion-inline.js";

/* [FIX-P9] LA LÍNEA DE RAZONAMIENTO + LOG — el hilo colapsable del turno. Su CSS entra por
 * la MISMA vía que el de opciones y por el mismo motivo: re-asignar `auxiliaryStyle` después
 * del montaje REINICIA el render de deep-chat (y con él se van los mensajes ya pintados). */
import * as LI from "./linea.js";

const BUNDLE = new URL("../vendor/deepChat.bundle.js", import.meta.url).href;

/* La tipografía de Aleph. Inline en el host ⇒ apaga la inyección de Google Fonts. */
const FONT_STACK = "'Hanken Grotesk', system-ui, -apple-system, sans-serif";

/* ── i18n · ES/EN en lockstep. UN solo lugar para las DOS superficies. ────────────── */
const STRINGS = {
  es: {
    "ph.sala": "Una tarea para el agente — ej: «un informe del cierre de mayo»",
    "ph.guia": "¿Qué hay que armar?…",
    "name.sala": "Agente",
    "name.guia": "Guía",
    "name.user": "Yo",
    "tip.send": "Enviar",
    "tip.attach": "Adjuntar un archivo",
    "tip.mic": "Dictar (voz → texto)",
    "tip.camera": "Tomar una foto",
    "vitals.thinking": "pensando…",
    "vitals.tool": "usando",
    "vitals.reading": "leyendo",
    "vitals.writing": "escribiendo",
    "err.title": "No pude completar eso",
    "err.retry": "Reintentar",
    "err.retrying": "Reintentando…",
    "err.auto": "Reintenté solo una vez y volvió a fallar.",
    "act.done": "listo",
    "act.doing": "en curso",
    "act.fail": "no salió",
    "act.cut": "quedó cortada",
    "act.cut.why": "el turno terminó antes de que devolviera resultado",
    // [GATE 3 · obra 5] LOS DOS DESENLACES QUE FALTABAN. «no salió» y «no corrió» no son lo
    // mismo, y una acción RETENIDA no es ninguno de los dos: el gate hizo su trabajo.
    "act.held": "esperando tu OK",
    "act.held.why": "no la hice todavía — el gate la frenó para preguntarte",
    "act.ask": "¿La hago, o la dejo?",
    "act.skip": "no corrió",
    "offer.title": "Falta una pieza",
    "sug.title": "Para arrancar",
    "attach.ingesting": "leyendo el archivo…",
    "attach.ok": "listo — ya está en el contexto",
    "attach.fail": "no pude leer ese archivo",
  },
  en: {
    "ph.sala": "A task for the agent — e.g. “a report on the May close”",
    "ph.guia": "What needs building?…",
    "name.sala": "Agent",
    "name.guia": "Guide",
    "name.user": "Me",
    "tip.send": "Send",
    "tip.attach": "Attach a file",
    "tip.mic": "Dictate (voice → text)",
    "tip.camera": "Take a photo",
    "vitals.thinking": "thinking…",
    "vitals.tool": "using",
    "vitals.reading": "reading",
    "vitals.writing": "writing",
    "err.title": "I couldn't finish that",
    "err.retry": "Retry",
    "err.retrying": "Retrying…",
    "err.auto": "I retried once on my own and it failed again.",
    "act.done": "done",
    "act.doing": "running",
    "act.fail": "didn't work",
    "act.cut": "cut short",
    "act.cut.why": "the turn ended before it returned a result",
    "act.held": "waiting for your OK",
    "act.held.why": "I haven't done it yet — the gate stopped it to ask you",
    "act.ask": "Go ahead, or leave it?",
    "act.skip": "didn't run",
    "offer.title": "A piece is missing",
    "sug.title": "To get started",
    "attach.ingesting": "reading the file…",
    "attach.ok": "done — it's in the context now",
    "attach.fail": "I couldn't read that file",
  },
};

/* [FIX-P9] Los strings de LA LÍNEA viven en `linea.js` (con su HTML y su CSS) y se FUNDEN acá:
 * ley 2 de este archivo — un solo `tr()` para las dos superficies, y la vara del barrido neutro
 * los ve por el mismo diccionario que todo lo demás. */
Object.assign(STRINGS.es, LI.STRINGS.es);
Object.assign(STRINGS.en, LI.STRINGS.en);

function currentLang() {
  try {
    if (window.AlephI18n && window.AlephI18n.lang) return window.AlephI18n.lang() === "en" ? "en" : "es";
  } catch (e) {}
  return String(document.documentElement.lang || "es").toLowerCase().indexOf("en") === 0 ? "en" : "es";
}

function T(lang, key) {
  const tbl = STRINGS[lang] || STRINGS.es;
  return tbl[key] != null ? tbl[key] : (STRINGS.es[key] != null ? STRINGS.es[key] : key);
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ── LOGOS REALES (brandface) ──────────────────────────────────────────────────────
 * Un servicio nombrado en el chat aparece con SU logo, no con un cuadradito genérico.
 * AlephBrand ya trae el contrato: slug conocido → <img> de /v1/icons/{slug} (cacheado
 * server-side, cero red externa); desconocido / manifest ausente / 404 → iniciales+color
 * deterministas. Acá sólo se elige el tamaño y se degrada si brandface no cargó. */
function faceHTML(service, size) {
  size = size || 15;
  try {
    if (window.AlephBrand && window.AlephBrand.faceHTML) {
      return window.AlephBrand.faceHTML(service, { size: size, cls: "ac-face" });
    }
  } catch (e) {}
  // brandface ausente: iniciales sin color de marca, pero NUNCA un cuadrado vacío.
  const name = String((service && (service.label || service.connector || service.server || service.slug)) || service || "?");
  const ini = name.replace(/[_\-./]+/g, " ").trim().split(/\s+/).filter(Boolean);
  const txt = (ini.length > 1 ? ini[0][0] + ini[1][0] : name.slice(0, 2)).toUpperCase();
  return '<span class="ac-face ac-face-fallback" style="width:' + size + "px;height:" + size + 'px" aria-hidden="true">' + esc(txt) + "</span>";
}

/* Servicios nombrados en una frase → logo inline. Se apoya en el manifest de brandface
 * (los 47 slugs curados) para no teñir cualquier palabra: sólo marca lo que ES un servicio. */
function knownSlugs() {
  try {
    const k = window.AlephBrand && window.AlephBrand._known && window.AlephBrand._known();
    return k && k.length ? k : null;
  } catch (e) { return null; }
}

/** inlineLogos(html) → el mismo HTML con el logo real pegado a cada servicio mencionado. */
function inlineLogos(html) {
  const slugs = knownSlugs();
  if (!slugs || !slugs.length) return html;
  // más largo primero: "google_drive" antes que "google" (si ambos existen en el manifest).
  const ordered = slugs.slice().sort((a, b) => b.length - a.length);
  let out = html;
  for (let i = 0; i < ordered.length; i++) {
    const slug = ordered[i];
    const human = slug.replace(/[_-]+/g, "[ _-]?");
    // sólo fuera de tags y sólo la PRIMERA mención (no confetear la burbuja de logos).
    const re = new RegExp("(^|[^<\\w])(" + human + ")\\b(?![^<]*>)", "i");
    if (!re.test(out)) continue;
    out = out.replace(re, (m, pre, word) =>
      pre + '<span class="ac-svc">' + faceHTML(slug, 14) + "<span>" + word + "</span></span>");
  }
  return out;
}

/* ── CSS de nuestras cards. Viaja al SHADOW ROOT por auxiliaryStyle ────────────────
 * (el <style> de la página no entra al shadow DOM — ver §"dónde vive el DOM").
 * Se apoya en las vars de tema de Aleph con fallback, porque las custom properties SÍ
 * heredan a través del shadow boundary: el tema claro/oscuro sigue mandando. */
const AUX_CSS = `
  .ac-face{display:inline-flex;align-items:center;justify-content:center;vertical-align:middle;
    border-radius:4px;overflow:hidden;flex:none;box-sizing:border-box}
  .ac-face img{width:100%;height:100%;object-fit:contain;display:block}
  .ac-face-fallback{background:var(--line2,#4A433A);color:#fff;font-weight:500;font-size:8px;line-height:1}
  .ac-svc{display:inline-flex;align-items:center;gap:4px;vertical-align:baseline}
  /* el globo-placeholder que cierra un turno sin streaming: existe para deep-chat, no se ve */
  .ac-noop{display:none}
  .outer-message-container:has(.ac-noop){display:none}

  /* SIGNOS VITALES — jamás silencio entre pregunta y respuesta */
  .ac-vitals{display:flex;align-items:center;gap:8px;font-size:11.5px;color:var(--faint,#897F70);
    padding:2px 0;line-height:1.4}
  .ac-vitals .ac-dot{width:7px;height:7px;border-radius:50%;background:var(--accent,#8B5CF6);
    flex:none;animation:acpulse 1.2s ease-in-out infinite}
  .ac-vitals .ac-what{display:inline-flex;align-items:center;gap:5px}
  @keyframes acpulse{0%,100%{opacity:.35}50%{opacity:1}}

  /* ACCIÓN (tool_call) — card, JAMÁS <function=…> crudo */
  .ac-act{display:flex;align-items:center;gap:8px;border:1px solid var(--line,#3A342D);
    background:var(--paper2,#242120);border-radius:10px;padding:7px 10px;font-size:12px;
    color:var(--muted,#A89C8B);margin:2px 0}
  .ac-act .ac-act-tt{flex:1;min-width:0;color:var(--ink,#F3ECE0);font-weight:500;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .ac-act .ac-act-sub{display:block;font-weight:400;font-size:11px;color:var(--faint,#897F70)}
  .ac-act .ac-act-st{flex:none;font-size:10.5px;border-radius:999px;padding:2px 8px;
    border:1px solid var(--line2,#4A433A)}
  .ac-act.done .ac-act-st{color:var(--green,#34D399);border-color:rgba(52,211,153,.4)}
  .ac-act.doing .ac-act-st{color:var(--accent-deep,#B4B1FF)}
  /* [FIX-P10 §1] TODA CARD CIERRA: ✓ resultado o ✗ causa. El estado "en curso" es
     TRANSITORIO por contrato — una card que se queda ahí es un turno que no terminó. */
  .ac-act.fail{border-color:#6A3A3A}
  .ac-act.fail .ac-act-st{color:#E58A8A;border-color:rgba(229,138,138,.45)}
  .ac-act.fail .ac-act-sub{color:#E0A6A6}
  /* [GATE 3 · obra 5] EL GATE ES PROTECCIÓN, NO FALLO — y una acción que NO CORRIÓ tampoco
     es un fallo. Tres desenlaces, tres caras, y NINGÚN color nuevo:
       · held      ÁMBAR — el MISMO 0xffb454 del aura "held" del Cuarto (cuarto.render.js:2154,
                   «ámbar del gate, mismo del muro-espera»). Ni el verde del éxito ni el rojo
                   del error: el gate hizo su trabajo y está preguntando.
       · nocorrio  GRIS de --faint, el que YA usa .ac-act-sub en esta misma card. Es la
                   familia del «no hay dato»: la acción no llegó a pasar, no hay nada que
                   pintar de rojo. Un fallo se arregla; esto no llegó a intentarse.
     La Sala se alinea al Cuarto (acta de persona usuaria, 2026-08-06) — el Cuarto ya distinguía "held"
     desde F5 y la Sala lo pintaba rojo. */
  .ac-act.held{border-color:#7A5A24;background:rgba(255,180,84,.05)}
  .ac-act.held .ac-act-st{color:#FFB454;border-color:rgba(255,180,84,.45)}
  .ac-act.held .ac-act-sub{color:#FFD9A0}
  .ac-act.held .ac-act-ask{display:block;font-weight:500;font-size:11px;color:#FFB454;margin-top:2px}
  .ac-act.nocorrio{border-color:var(--line2,#4A433A);opacity:.86}
  .ac-act.nocorrio .ac-act-st{color:var(--faint,#897F70)}
  .ac-act.nocorrio .ac-act-sub{color:var(--muted,#A89C8B)}

  /* ERROR con camino: causa humana en 1 línea + reintento */
  .errcard{border:1px solid #6A3A3A;background:rgba(224,106,106,.10);border-radius:13px;
    padding:12px 13px;margin:2px 0}
  .errcard b{color:#E58A8A;font-size:12.5px;display:flex;align-items:center;gap:6px}
  .errcard p{margin:5px 0 0;font-size:12.5px;line-height:1.5;color:var(--ink,#F3ECE0)}
  .errcard .ac-auto{margin:6px 0 0;font-size:11px;color:var(--faint,#897F70)}
  .errcard .acts{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
  .errcard .acts button{border:none;background:var(--accent,#8B5CF6);color:#fff;border-radius:9px;
    padding:7px 14px;font-weight:500;font-size:12.5px;cursor:pointer;font-family:inherit}
  .errcard .acts button.ghost{border:1px solid var(--line2,#4A433A);background:none;
    color:var(--muted,#A89C8B)}
  .errcard .acts button:disabled{opacity:.55;cursor:default}

  /* OFERTA CONTEXTUAL — cuando falta una pieza, el camino está ahí mismo */
  .ac-offer{border:1px solid var(--line2,#4A433A);background:var(--accent-soft,rgba(139,92,246,.15));
    border-radius:13px;padding:12px 13px;margin:2px 0}
  .ac-offer b{color:var(--accent-deep,#B4B1FF);font-size:12.5px;display:flex;align-items:center;gap:7px}
  .ac-offer p{margin:5px 0 0;font-size:12.5px;line-height:1.5;color:var(--ink,#F3ECE0)}
  .ac-offer .acts{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
  .ac-offer .acts button{border:none;background:var(--accent,#8B5CF6);color:#fff;border-radius:9px;
    padding:7px 14px;font-weight:500;font-size:12.5px;cursor:pointer;font-family:inherit}
  .ac-offer .acts button.ghost{border:1px solid var(--line2,#4A433A);background:none;
    color:var(--muted,#A89C8B)}

  /* SUGERENCIAS DE ARRANQUE — el chat nunca es un campo vacío mudo */
  .ac-sugs{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px}
  .ac-sug{border:1px solid var(--line,#3A342D);background:var(--paper2,#242120);
    color:var(--muted,#A89C8B);border-radius:999px;padding:5px 11px;font-size:12px;cursor:pointer;
    font-family:inherit;text-align:left}
  .ac-sug:hover{border-color:var(--accent,#8B5CF6);color:var(--accent-deep,#B4B1FF)}

  /* markdown dentro de la burbuja (el CSS de la página no cruza el shadow boundary) */
  .ac-md p{margin:.35em 0} .ac-md p:first-child{margin-top:0} .ac-md p:last-child{margin-bottom:0}
  .ac-md ul,.ac-md ol{margin:.35em 0;padding-left:18px}
  .ac-md code{background:var(--accent-soft,rgba(139,92,246,.15));padding:1px 4px;border-radius:4px;font-size:12px}
  .ac-md pre{background:var(--paper2,#242120);border:1px solid var(--line,#3A342D);padding:8px 10px;
    border-radius:8px;overflow-x:auto;font-size:12px}
  .ac-md pre code{background:none;padding:0}
  .ac-md table{border-collapse:collapse;font-size:12px;margin:.35em 0;display:block;overflow-x:auto}
  .ac-md td,.ac-md th{border:1px solid var(--line,#3A342D);padding:3px 7px}
  .ac-md blockquote{margin:.35em 0;padding-left:10px;border-left:2px solid var(--line2,#4A433A);
    color:var(--muted,#A89C8B)}
  /* hljs teñido con las vars del tema (mismo criterio que sala.html, cero css externo) */
  pre code.hljs{background:transparent;padding:0}
  .hljs-keyword,.hljs-built_in,.hljs-type,.hljs-tag{color:var(--accent-deep,#B4B1FF)}
  .hljs-string,.hljs-regexp,.hljs-addition{color:var(--green,#34D399)}
  .hljs-number,.hljs-literal,.hljs-symbol{color:var(--amber,#E0A82E)}
  .hljs-comment,.hljs-quote{color:var(--faint,#897F70);font-style:italic}
  .hljs-title,.hljs-section,.hljs-name{color:var(--accent,#8B5CF6);font-weight:500}

  /* SEND APAGADO-PERO-VIVO: el modelo que no puede ejecutar se VE apagado, pero el
     click SIEMPRE entra (un disabled se traga el click y deja al humano sin señal). */
  :host([data-gated="1"]) #submit-icon{opacity:.5;filter:grayscale(1)}
` + OPCIONES_CSS + CONEXION_INLINE_CSS + LI.CSS;

/* ── el módulo del bundle se carga UNA vez por página (las dos superficies lo comparten) ──
 * Se dispara al IMPORTAR este módulo, no al montar: el custom element tiene que estar
 * definido lo antes posible para que el upgrade del <deep-chat> no llegue tarde y deje
 * `addMessage` sin existir en el primer turno. */
let _bundle = null;
function loadBundle() {
  if (!_bundle) _bundle = import(/* @vite-ignore */ BUNDLE);
  return _bundle;
}
loadBundle();

/**
 * mount(host, opts) → controlador del chat.
 *
 * @param host   elemento contenedor (el <deep-chat> se crea adentro y ocupa el 100%).
 * @param opts.surface   "sala" | "guia" — elige placeholder/nombre por default.
 * @param opts.onSubmit  (turn, signals) → void. turn={text, files}. signals={onOpen,onResponse,onClose}
 *                       es el canal de STREAMING de deep-chat (onResponse recibe DELTAS).
 * @param opts.onAttach  (file) → Promise — el camino de ingesta existente (markitdown / visión).
 * @param opts.attachments  bool — habilita botón + drag&drop + paste.
 * @param opts.suggestions  [string] — opciones por default al entrar.
 * @param opts.intro     string|html — saludo (si no, lo arma la superficie).
 */
export function mount(host, opts) {
  opts = opts || {};
  const surface = opts.surface === "guia" ? "guia" : "sala";
  let lang = currentLang();
  const tr = (k) => T(lang, k);

  const el = document.createElement("deep-chat");
  el.id = opts.id || (surface === "guia" ? "guiaChat" : "salaChat");
  // LEY 1 · font-family INLINE ⇒ deep-chat NO inyecta el <link> a Google Fonts.
  el.setAttribute("style",
    "width:100%;height:100%;border:none;background:none;font-family:" + FONT_STACK + ";");

  /* ── EL UPGRADE MANDA ───────────────────────────────────────────────────────────
   * El bundle se importa async: cuando `mount()` corre, `deep-chat` todavía NO es un
   * custom element definido. Asignarle propiedades ACÁ crea own-properties sobre un
   * elemento sin upgradear que después TAPAN los setters del prototipo — el componente
   * nunca ve la config y cae a su respuesta DEMO ("Hi there! This is a demo response!").
   * Lo pagué: connect/htmlClassUtilities/auxiliaryStyle se ignoraban en silencio.
   * Por eso TODO (props y llamadas) se difiere hasta `whenDefined`, y mientras tanto se
   * encola. Los callers no se enteran: la API del controlador es sincrónica igual. */
  let upgraded = false;
  let introChromeNode = null;
  const pending = [];
  function q(fn) {
    if (upgraded) { fn(); return; }
    pending.push(fn);
  }

  /* ── textos: TODO desde STRINGS, incluidos los tooltips que deep-chat deja en inglés ── */
  function applyStrings() {
    el.textInput = {
      placeholder: { text: opts.placeholder || tr("ph." + surface) },
      styles: { text: { fontSize: surface === "guia" ? "12px" : "16px" } },
    };
    el.names = {
      ai: { text: opts.showAiName === false ? "" : (opts.aiName || tr("name." + surface)) },
      user: { text: tr("name.user") },
    };
    el.errorMessages = {
      overrides: { default: tr("err.title") },
      displayServiceErrorMessages: false,
    };
    // strings SECUNDARIOS de deep-chat que SÍ exponen prop (el spike los marcó en inglés):
    el.submitButtonStyles = { alwaysEnabled: true, tooltip: { text: tr("tip.send") } };
    if (opts.attachments) {
      el.mixedFiles = { button: { tooltip: { text: tr("tip.attach") } }, files: { maxNumberOfFiles: 6 } };
    }
  }

  /* ── handlers de nuestras cards (viven en el shadow DOM ⇒ van por htmlClassUtilities) ── */
  const ACTIONS = {};          // id → callback, poblado por card()/errorCard()/offer()
  let _actionSeq = 0;
  // [FIX-P10 §1] cards de ACCIÓN abiertas (estado "en curso"). Se vacía sola cuando cada
  // una cierra; `cerrarActs()` la vacía a la fuerza cuando el turno se muere en el camino.
  const ABIERTAS = new Set();

  /** TODA la config del componente, en un solo lugar y SIEMPRE post-upgrade. */
  function configure() {
    applyStrings();

    const salaComposerCSS = surface === "sala" ? `
      #text-input-container{width:min(92%,900px);min-height:62px;border-radius:18px;
        margin-top:18px;margin-bottom:18px;box-shadow:none}
      #text-input{font-size:16px;line-height:1.55;padding:14px 16px}
      .input-button-svg{width:2.15em;height:2.15em}
      #submit-icon{width:1.65em}
      .outer-message-container{font-size:15.5px;line-height:1.58}
    ` : "";
    el.auxiliaryStyle = AUX_CSS + salaComposerCSS + (opts.auxiliaryStyle || "");
    el.displayLoadingBubble = true;   // vale como red: los signos vitales propios van igual
    el.chatStyle = { backgroundColor: "transparent" };
    el.messageStyles = {
      default: {
        shared: { bubble: { backgroundColor: "transparent", maxWidth: "94%", fontSize: surface === "guia" ? "12px" : "15.5px" } },
        user: { bubble: { backgroundColor: "var(--accent-soft, rgba(139,92,246,.15))", color: "var(--ink, #F3ECE0)" } },
        ai: { bubble: { color: "var(--ink, #F3ECE0)" } },
      },
    };

    if (opts.attachments) {
      el.dragAndDrop = { backgroundColor: "rgba(139,92,246,.16)", border: "2px dashed var(--accent, #8B5CF6)" };
    }

    el.htmlClassUtilities = {
      "ac-action": {
        events: {
          click: (e) => {
            const b = e.target.closest ? e.target.closest("[data-ac-id]") : null;
            const id = b && b.getAttribute("data-ac-id");
            const fn = id && ACTIONS[id];
            if (fn) fn(b);
          },
        },
        styles: { default: { cursor: "pointer" } },
      },
      /* [FIX-P9] LA LÍNEA — UN SOLO handler DELEGADO en la raíz, y eso NO es un detalle:
       * deep-chat cablea `htmlClassUtilities` cuando RENDERIZA el mensaje, y las entradas
       * del log se agregan DESPUÉS (cada tool que dispara muta el nodo ya pintado). Un
       * handler por botón nunca se cablearía para las entradas nuevas: se verían bien y no
       * harían nada — el peor de los fallos mudos. La raíz sí existe al renderizar, así que
       * los clicks de todo lo que crezca adentro burbujean hasta acá.
       *
       * Y por eso mismo el toggle NO usa el registro `ACTIONS` (que vive en el closure de
       * ESTE montaje): es una marca en el DOM. Una línea de hace una hora se despliega
       * igual, sin depender de que nadie haya guardado su callback. */
      "ac-li": {
        events: {
          click: (e) => {
            const t = e.target;
            const btn = t && t.closest ? t.closest("[data-li-act]") : null;
            if (!btn) return;
            const acto = btn.getAttribute("data-li-act");
            if (acto === "head") {
              const box = btn.closest(".ac-linea"); if (!box) return;
              if (box.getAttribute("data-viva") === "1") return;   // viva = latido, no se pliega
              const abierta = box.getAttribute("data-open") === "1";
              box.setAttribute("data-open", abierta ? "0" : "1");
              btn.setAttribute("aria-expanded", abierta ? "false" : "true");
              btn.title = tr(abierta ? "li.ver" : "li.ocultar");
              return;
            }
            if (acto === "det") {
              const box = btn.closest(".ac-linea"); if (!box) return;
              const det = box.querySelector('.ac-li-det[data-det="' + btn.getAttribute("data-e") + '"]');
              if (!det) return;
              det.hidden = !det.hidden;
              btn.textContent = tr(det.hidden ? "li.detalle" : "li.ocultar_detalle");
              return;
            }
            if (acto === "cam") {
              const fn = ACTIONS[btn.getAttribute("data-ac-id")];
              if (fn) fn(btn);
            }
          },
        },
      },
    };

    el.connect = CONNECT;
  }

  /* ── el canal de envío: deep-chat entrega el turno, la SUPERFICIE lo ejecuta ────────
   * `connect.handler` nos deja dueños del request: La Sala mantiene su pipeline entero
   * (classify → route → run/stream, gates, artifacts) y el Guía su loop de tool-calling.
   * Nada del motor cambia — deep-chat sólo aporta composer, burbujas y streaming. */
  /* `stream` es POR SUPERFICIE, y no es cosmético.
   *   · La Sala streamea de verdad (el motor emite tokens) → stream:true.
   *   · El Guía NO: su loop devuelve el turno entero y la respuesta se pinta después con
   *     say(). Con stream:true, cerrar un turno sin haber streameado dispara
   *     `attemptToFinaliseStream`, que TIRA "No valid stream events were sent" y —lo grave—
   *     pinta un globo de error visible al humano en CADA turno. En modo no-streaming el
   *     turno se cierra entregando una respuesta y no hay finalización que fallar. */
  const streaming = opts.stream !== false;
  const CONNECT = {
    stream: streaming,
    handler: (body, signals) => {
      const turn = readTurn(body);
      cerrarLinea();                           // [FIX-P9] turno nuevo ⇒ el hilo anterior se pliega
      vitals(tr("vitals.thinking"));           // §3 · "pensando…" DESDE EL INSTANTE DEL ENVÍO
      let opened = false;
      const wrapped = {
        onOpen: () => {
          if (!opened) {
            opened = true;
            clearVitals();
            try { return signals.onOpen(); } catch (e) {}
          }
        },
        onResponse: (r) => {
          wrapped.onOpen();
          try { return signals.onResponse(r); } catch (e) {}
        },
        onClose: () => {
          clearVitals();
          try { return signals.onClose(); } catch (e) {}
        },
        stopClicked: signals.stopClicked,
      };
      try {
        // El héroe es chrome DE ARRANQUE, no un mensaje que se muda al fondo del hilo.
        if (introChromeNode) { introChromeNode.remove(); introChromeNode = null; }
        opts.onSubmit && opts.onSubmit(turn, wrapped);
      } catch (e) {
        clearVitals();
        try { signals.onResponse({ error: String((e && e.message) || e) }); } catch (e2) {}
        try { signals.onClose(); } catch (e2) {}
      }
    },
  };

  /* deep-chat manda JSON {messages:[…]} o FormData (cuando hay adjuntos). Normalizamos
   * a {text, files} para que la superficie no tenga que saber en qué forma vino. */
  function readTurn(body) {
    const out = { text: "", files: [] };
    try {
      if (body instanceof FormData) {
        for (const [k, v] of body.entries()) {
          if (v instanceof File) out.files.push(v);
          else if (/^message/.test(k)) {
            try { const m = JSON.parse(String(v)); if (m && m.text) out.text = m.text; } catch (e) {}
          }
        }
        return out;
      }
      const msgs = (body && body.messages) || [];
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i] && msgs[i].role !== "ai" && msgs[i].text) { out.text = msgs[i].text; break; }
      }
      if (!out.text && msgs.length) out.text = msgs[msgs.length - 1].text || "";
    } catch (e) {}
    return out;
  }

  /* ── SIGNOS VITALES ────────────────────────────────────────────────────────────────
   * Una sola línea viva en el chat: nace en el envío, cambia cuando el agente usa una
   * herramienta, y muere cuando empieza a llegar la respuesta. Se actualiza EN SITIO
   * (no apila) — por eso se busca el nodo dentro del shadow root en vez de re-emitir. */
  function shadow() { return el.shadowRoot || null; }
  function liveVitals() {
    const sr = shadow();
    return sr ? sr.querySelector('.ac-vitals[data-live="1"]') : null;
  }

  /* LOS SIGNOS VITALES NO SON UN MENSAJE DE deep-chat — y eso es deliberado.
   *
   * Al principio se emitían con addMessage() y se borraban del DOM al llegar la respuesta.
   * Parecía funcionar. No funcionaba: deep-chat SIGUE CONTABILIZANDO los mensajes que creó
   * (messageElementRefs), así que arrancarle un nodo por detrás le deja una referencia
   * colgada. Consecuencias REALES, las dos mudas:
   *   · el globo del stream no se creaba ⇒ al cerrar, "No valid stream events were sent" y
   *     deep-chat pintaba SU globo de error en un turno que salió BIEN;
   *   · y como ese globo no existía, el re-render final escribía la respuesta encima del
   *     ÚLTIMO mensaje ai que sí existía: las opciones de arranque. La respuesta "4"
   *     reemplazaba a los chips de sugerencia.
   *
   * Por eso los vitales se insertan a mano en #messages, SIN pasar por addMessage: deep-chat
   * no los conoce, no los cuenta, y sacarlos no le rompe nada. */
  function vitals(what, service) {
    q(() => {
      const sr = shadow(); if (!sr) return;
      const box = sr.querySelector("#messages"); if (!box) return;
      const inner = '<span class="ac-dot" aria-hidden="true"></span><span class="ac-what">' +
        (service ? faceHTML(service, 14) : "") + "<span>" + esc(what) + "</span></span>";
      let cur = liveVitals();
      if (!cur) {
        cur = document.createElement("div");
        cur.className = "ac-vitals";
        cur.setAttribute("data-live", "1");
        cur.setAttribute("role", "status");
        box.appendChild(cur);
      }
      cur.innerHTML = inner;
      /* [FIX-P9] EL LATIDO VIVE EN LA LÍNEA, si hay línea viva.
       * No se pinta un segundo pulso debajo del primero: es el MISMO nodo (mismo
       * `data-live="1"`, mismo contrato que mide P10) hospedado por la cabecera de la
       * línea mientras el turno corre. Ahí es donde el humano ya está mirando —"Buscando
       * en Hugging Face…" pertenece al hilo del turno, no a una fila suelta al final. */
      const cabeza = lineaCabeza();
      if (cabeza) { if (cur.parentNode !== cabeza) cabeza.insertBefore(cur, cabeza.firstChild); }
      else if (cur.parentNode !== box) box.appendChild(cur);
      box.scrollTop = box.scrollHeight;
    });
  }
  function clearVitals() {
    q(() => {
      const cur = liveVitals();
      if (cur) cur.remove();      // nodo NUESTRO: deep-chat nunca supo de él
    });
  }

  /* ── mensajes ricos ────────────────────────────────────────────────────────────── */
  function addHTML(html) { q(() => el.addMessage({ role: "ai", html: html })); }

  function bindAction(fn) {
    const id = "aca" + (++_actionSeq);
    ACTIONS[id] = fn;
    return id;
  }
  function actionsHTML(actions) {
    return (actions || []).map((a) =>
      '<button type="button" class="ac-action' + (a.ghost ? " ghost" : "") + '" data-ac-id="' +
      bindAction(a.onClick || function () {}) + '">' + esc(a.label) + "</button>").join("");
  }

  /** say(text) — prosa del agente. Markdown por SalaRender si está; si no, el nativo.
   * La prosa ES la respuesta ⇒ mata los signos vitales (una card de ACCIÓN, en cambio, no:
   * el agente sigue trabajando mientras la muestra). */
  function say(text) {
    const t = String(text == null ? "" : text);
    if (!t.trim()) return;
    clearVitals();
    // [FIX-P9] la prosa ES la respuesta ⇒ la línea del turno se pliega a su resumen ANTES,
    // no después: razono → trabajo → contesto, en ese orden y en ese orden se lee.
    cerrarLinea();
    // Sin SalaRender (o si falla) NO se pierde el logo inline: se cae a texto escapado
    // dentro del mismo contenedor .ac-md, así la regla "servicio nombrado ⇒ su logo real"
    // vale en las dos ramas y no depende de que el renderer rico esté cargado.
    const plain = () => addHTML('<div class="ac-md">' + inlineLogos(esc(t).replace(/\n/g, "<br>")) + "</div>");
    if (window.SalaRender && window.SalaRender.renderMarkdown) {
      window.SalaRender.renderMarkdown(t).then((html) => {
        addHTML('<div class="ac-md">' + inlineLogos(html) + "</div>");
        q(enhanceLast);
      }).catch(plain);
      return;
    }
    plain();
  }

  /** Las figuras inline (```chart / ```svg), el highlight y el math, DENTRO del shadow.
   *
   * [Educación] El math entró en esta misma línea de las otras dos: `SalaRender.runKatex`
   * es el que las obras ya usaban, y esta burbuja pinta el mismo texto del mismo modelo.
   * Sin él, un tutor de matemática entrega `$$f'(x) = \lim_{h \to 0}\dots$$` a la vista. */
  function enhanceLast() {
    const sr = shadow(); if (!sr) return;
    const nodes = sr.querySelectorAll(".ac-md");
    const last = nodes[nodes.length - 1]; if (!last) return;
    try { if (window.SalaRender && window.SalaRender.renderInlineFigures) window.SalaRender.renderInlineFigures(last); } catch (e) {}
    try { if (window.SalaRender && window.SalaRender.highlightIn) window.SalaRender.highlightIn(last); } catch (e) {}
    try { if (window.SalaRender && window.SalaRender.runKatex) window.SalaRender.runKatex(last); } catch (e) {}
  }

  /** action(label) — un tool_call SIEMPRE se ve como acción con su card, nunca como texto.
   *
   * [FIX-P10 §1] DEVUELVE UN ASA, y el asa es obligación: `ok()` / `fail(causa)`. Antes
   * la card nacía "en curso" y NADIE la cerraba nunca — el resultado se pintaba como una
   * card APARTE y la primera quedaba girando para siempre. En la caminata del 27-jul eso
   * se vio crudo: tres `buscar_catalogo` "en curso" ETERNAS en el Guía. El estado "en
   * curso" es transitorio POR CONTRATO; quien abre una card se compromete a cerrarla, y
   * `cerrarActs()` es la red de atrás para cuando el turno se muere en el camino. */
  function actHTML(id, label, o) {
    const st = o.done ? "done" : "doing";
    return '<div class="ac-act ' + st + '" data-act-id="' + id + '" data-tool="' + esc(o.tool || label) + '">' +
      faceHTML(o.service || o.tool || label, 16) +
      '<span class="ac-act-tt">' + esc(label) +
      (o.detail ? '<span class="ac-act-sub">' + esc(o.detail) + "</span>" : "") + "</span>" +
      '<span class="ac-act-st">' + esc(o.done ? tr("act.done") : tr("act.doing")) + "</span></div>";
  }

  /* ══ [FIX-P9] LA LÍNEA DE RAZONAMIENTO + LOG ══════════════════════════════════════
   *
   * El hilo del turno: razonamiento (si lo hubo) + una entrada por acción REAL. Vive EN el
   * mensaje, colapsado por default, y se despliega cuando lo piden — hoy o dentro de una hora.
   *
   * ── POR QUÉ SE ABRE SOLA ─────────────────────────────────────────────────────────
   * `action()` es la puerta por la que YA entran los tool_calls de las dos superficies (el
   * loop del Guía la llama en `onTool`; La Sala, por cada `tool_call_finished` del espinazo).
   * Si abrir la línea fuera un paso aparte, cada superficie tendría que acordarse — y la que
   * se olvidara volvería a apilar cards sueltas sin que nadie lo notara. Acá la primera
   * acción del turno ABRE la línea y todo lo que siga cae adentro: el Cuarto no cambia una
   * línea de código y su log queda armado igual.
   *
   * ── DÓNDE SE CIERRA ──────────────────────────────────────────────────────────────
   * La línea es del TURNO, y un turno termina cuando llega su respuesta o cuando se muere:
   *   · `say()` / `stream().finish()` — la prosa ES la respuesta ⇒ la línea se pliega a su
   *     resumen ANTES de que se pinte, que es el orden del ejemplo canónico (razono →
   *     trabajo → contesto). Si el modelo vuelve a trabajar después de hablar, abre OTRA
   *     línea: son dos tramos y así se leen.
   *   · `cerrarActs()` — la red de atrás de P10 (el loop murió, el cerebro se cortó).
   *   · `errorCard()` — el turno terminó mal.
   *
   * ── LA LEY ───────────────────────────────────────────────────────────────────────
   * TELEMETRÍA REAL. `pensar()` es la única puerta del bloque de razonamiento y el bloque no
   * existe en el DOM hasta que la llaman con texto real: un cerebro que no razona deja CERO
   * bloque. `accion()` es la única puerta del log. No hay tercera fuente.
   */
  let LINEA = null;         // la línea VIVA (una por turno), o null
  let _lineaSeq = 0;

  /** La cabecera de la línea viva — el hogar de los signos vitales mientras corre. */
  function lineaCabeza() {
    if (!LINEA) return null;
    const sr = shadow(); if (!sr) return null;
    return sr.querySelector('.ac-linea[data-linea="' + LINEA.id + '"] .ac-li-head');
  }
  function lineaNodo(id) {
    const sr = shadow(); if (!sr) return null;
    return sr.querySelector('.ac-linea[data-linea="' + id + '"]');
  }

  /** abrirLinea() — idempotente: devuelve la del turno en curso o crea una nueva. */
  function abrirLinea() {
    if (LINEA) return LINEA;
    const id = "acli" + (++_lineaSeq);
    const L = { id: id, t0: Date.now(), acciones: 0, razono: false, cerrada: false };
    LINEA = L;
    addHTML(LI.lineaHTML(id, lang));
    return L;
  }

  /** pensar(texto) — RAZONAMIENTO REAL, en deltas o entero. Sin llamada, sin bloque. */
  function pensar(texto) {
    const t = String(texto == null ? "" : texto);
    if (!t) return;                       // un delta vacío no crea el bloque
    const L = abrirLinea();
    L.razono = true;
    q(() => {
      const box = lineaNodo(L.id); if (!box) return;
      const body = box.querySelector(".ac-li-body"); if (!body) return;
      let p = body.querySelector(".ac-li-piensa");
      if (!p) {
        const tmp = document.createElement("div");
        tmp.innerHTML = LI.razonHTML(lang);
        p = tmp.firstChild;
        body.insertBefore(p, body.firstChild);
      }
      const span = p.querySelector("span");
      if (span) { span.textContent += t; p.scrollTop = p.scrollHeight; }
    });
  }

  /** accion(label, o) — UNA entrada del log. Devuelve el asa de siempre (ok / fail). */
  function lineaAccion(label, o) {
    o = o || {};
    const L = abrirLinea();
    const id = "acact" + (++_actionSeq);
    L.acciones++;
    const det = LI.detalleSlotHTML(id, lang);
    q(() => {
      const box = lineaNodo(L.id); if (!box) return;
      const log = box.querySelector(".ac-li-log"); if (!log) return;
      const fila = document.createElement("div");   // buffer de parseo: sus hijos se MUEVEN al log
      fila.innerHTML = actHTML(id, label, o) + det.caja;
      // el botón de detalle sólo existe si HAY detalle que mostrar (jamás un botón vacío)
      if (o.args !== undefined || o.result !== undefined) {
        const card = fila.querySelector(".ac-act");
        if (card) card.insertAdjacentHTML("beforeend", det.boton);
        const caja = fila.querySelector(".ac-li-det");
        if (caja) caja.innerHTML = LI.detalleHTML({ args: o.args, result: o.result }, lang);
      }
      while (fila.firstChild) log.appendChild(fila.firstChild);
      scrollDown();
    });
    if (!o.done) ABIERTAS.add(id);
    return {
      id: id,
      ok: (nota, extra) => cerrarAct(id, "done", nota, extra),
      fail: (causa, extra) => cerrarAct(id, "fail", causa, extra),
      // [GATE 3 · obra 5] los dos desenlaces que faltaban. `cerrar()` es la puerta genérica
      // para quien ya tiene el estado derivado del evento REAL y no quiere volver a decidirlo.
      held: (causa, extra) => cerrarAct(id, "held", causa, extra),
      noCorrio: (causa, extra) => cerrarAct(id, "nocorrio", causa, extra),
      cerrar: (estado, nota, extra) => cerrarAct(id, estado, nota, extra),
    };
  }

  /** cerrarLinea() — el turno terminó: la cabecera pasa a su resumen y queda PLEGADA. */
  function cerrarLinea(o) {
    const L = LINEA; if (!L || L.cerrada) return null;
    o = o || {};
    L.cerrada = true;
    L.ms = Date.now() - L.t0;
    LINEA = null;                    // desde acá, los vitales vuelven a su fila propia
    const texto = LI.resumen({ acciones: L.acciones, razono: L.razono, ms: L.ms }, lang);
    q(() => {
      const box = lineaNodo(L.id); if (!box) return;
      box.setAttribute("data-viva", "0");
      const head = box.querySelector(".ac-li-head");
      // UNA LÍNEA SIN NADA ADENTRO NO SE PINTA. Un turno que no razonó ni usó una sola
      // herramienta no tiene hilo que contar: dejar la cabecera sería inventar un resumen
      // ("0 acciones") de algo que no pasó. Se retira el nodo entero.
      if (!texto) { const w = box.closest(".outer-message-container"); if (w) w.style.display = "none"; box.remove(); return; }
      const res = head && head.querySelector(".ac-li-res");
      if (res) res.textContent = texto;
      if (head) head.title = tr("li.ver");
    });
    return { id: L.id, acciones: L.acciones, razono: L.razono, ms: L.ms, resumen: texto };
  }

  /** action(label) — un tool_call SIEMPRE se ve como acción con su card, nunca como texto.
   *
   * [FIX-P10 §1] DEVUELVE UN ASA, y el asa es obligación: `ok()` / `fail(causa)`. Antes
   * la card nacía "en curso" y NADIE la cerraba nunca — el resultado se pintaba como una
   * card APARTE y la primera quedaba girando para siempre. En la caminata del 27-jul eso
   * se vio crudo: tres `buscar_catalogo` "en curso" ETERNAS en el Guía. El estado "en
   * curso" es transitorio POR CONTRATO; quien abre una card se compromete a cerrarla, y
   * `cerrarActs()` es la red de atrás para cuando el turno se muere en el camino.
   *
   * [FIX-P9] La card ahora nace DENTRO de la línea del turno (misma clase, mismo asa, mismo
   * cierre — cambia dónde vive y cómo se lee, no su contrato). */
  function action(label, o) {
    return lineaAccion(label, o);
  }
  /** LOS CUATRO DESENLACES de una acción. [GATE 3 · obra 5]
   *
   * Hasta obra 5 eran DOS (`done` y todo-lo-demás→`fail`) y eso fundía tres cosas que la
   * persona necesita distinguir: una tool que corrió y falló, una que NUNCA CORRIÓ, y una
   * que el gate RETUVO. `nocorrio` y `held` no son grados de fallo: son otra cosa.
   * `held` es PROTECCIÓN — el gate hizo su trabajo (acta de persona usuaria, 2026-08-06). */
  const ACT_EST = {
    done:     { cls: "done",     copy: "act.done" },
    fail:     { cls: "fail",     copy: "act.fail" },
    held:     { cls: "held",     copy: "act.held" },
    nocorrio: { cls: "nocorrio", copy: "act.skip" },
  };
  /** cerrarAct(id, estado, nota, extra) — el desenlace, idempotente. ✓ resultado o ✗ causa.
   *
   * `estado` ∈ {done, fail, held, nocorrio}. **Un estado desconocido cae en `fail`, jamás en
   * `done`**: pintar ✓ por defecto es exactamente el agujero que obra 5 mata (G-1).
   *
   * [FIX-P9] `extra` es opcional y aditivo (los llamadores viejos no lo mandan y nada cambia):
   *   · extra.camino  {label, onClick} — el CAMINO de una acción fallida. Sale de `caminoDe`
   *     (el diccionario único), jamás se escribe a mano; sin camino real, no hay botón.
   *   · extra.args / extra.result     — el detalle plegable de ESTA entrada.
   *   · extra.pregunta {texto}        — [obra 5] la pregunta del gate: seguir o no. Sólo en
   *     `held`, y sin botón propio: quien responde es la tarjeta del gate que se pinta abajo
   *     (un segundo [Aprobar] sería la misma lección que ya dejó el segundo [Reintentar]).
   */
  function cerrarAct(id, estado, nota, extra) {
    if (!id || !ABIERTAS.has(id)) return false;
    ABIERTAS.delete(id);
    extra = extra || {};
    const E = ACT_EST[estado] || ACT_EST.fail;
    q(() => {
      const sr = shadow(); if (!sr) return;
      const el = sr.querySelector('[data-act-id="' + id + '"]'); if (!el) return;
      const malo = E.cls !== "done";
      el.classList.remove("doing");
      el.classList.add(E.cls);
      const stEl = el.querySelector(".ac-act-st");
      const txt = String(nota == null ? "" : nota).trim();
      /* DÓNDE VA EL DESENLACE, y por qué son dos lugares distintos:
       *   · ✗ CAUSA → al subtítulo. Un fallo necesita la línea ancha, y la llamada cruda
       *     que lo produjo pasa a ser ruido al lado del "por qué". (Contrato de P10 §2b:
       *     la causa se lee en `.ac-act-sub`.)
       *   · ✓ RESULTADO → al estado. La llamada cruda ES la evidencia de qué corrió y se
       *     queda; lo que devolvió es un recuento que entra al lado del tilde. Así el log
       *     se lee como el ejemplo canónico: hub_repo_search "vision GGUF" · listo 15
       *     resultados — antes el "15 resultados" PISABA la llamada y se perdía el qué. */
      if (stEl) stEl.textContent = tr(E.copy) + (!malo && txt ? " " + txt : "");
      if (malo && txt) {
        const tt = el.querySelector(".ac-act-tt");
        if (tt) {
          let sub = tt.querySelector(".ac-act-sub");
          if (!sub) { sub = document.createElement("span"); sub.className = "ac-act-sub"; tt.appendChild(sub); }
          sub.textContent = txt;
        }
      }
      // [obra 5] LA PREGUNTA — una acción retenida se PRESENTA preguntando, no informando.
      // Va sólo en `held`, y el default es la pregunta del acta: seguir o no.
      if (E.cls === "held") {
        const tt = el.querySelector(".ac-act-tt");
        if (tt && !tt.querySelector(".ac-act-ask")) {
          const ask = document.createElement("span");
          ask.className = "ac-act-ask";
          ask.textContent = (extra.pregunta && extra.pregunta.texto) || tr("act.ask");
          tt.appendChild(ask);
        }
      }
      // el DETALLE (con qué · qué devolvió), si el desenlace lo trajo. El botón se crea acá
      // sólo si todavía no existe: una entrada puede haber nacido ya con su detalle.
      const cuerpo = LI.detalleHTML({ args: extra.args, result: extra.result }, lang);
      if (cuerpo) {
        const caja = el.parentNode && el.parentNode.querySelector('.ac-li-det[data-det="' + id + '"]');
        if (caja) {
          caja.innerHTML = cuerpo;
          if (!el.querySelector(".ac-li-more")) el.insertAdjacentHTML("beforeend", LI.detalleSlotHTML(id, lang).boton);
        }
      }
      // EL CAMINO de una acción fallida. Un botón sin destino cableado no se pinta (regla
      // de caminoDe): sin `onClick`, el humano queda con la causa y nada más — que es
      // honesto — pero jamás con un botón que no lleva a ningún lado.
      if (malo && extra.camino && extra.camino.label && typeof extra.camino.onClick === "function"
          && !el.querySelector(".ac-li-cam")) {
        // OJO: `ac-action` NO sirve acá. deep-chat cablea htmlClassUtilities al RENDERIZAR el
        // mensaje, y este botón nace mucho después (cuando la tool falló). Va por el delegado
        // de la raíz de la línea, que sí existía al renderizar.
        el.insertAdjacentHTML("beforeend",
          '<button type="button" class="ac-li-cam" data-li-act="cam" data-ac-id="' +
          bindAction(extra.camino.onClick) + '">' + esc(extra.camino.label) + "</button>");
      }
    });
    return true;
  }
  /** cerrarActs(causa) — LA RED DE ATRÁS: el turno terminó ⇒ nada queda "en curso".
   *  Cubre el modo de fallo que ningún desenlace individual cubre: el loop muere, el
   *  cerebro se corta, la vuelta se agota. Devuelve cuántas cerró. */
  function cerrarActs(causa) {
    const ids = Array.from(ABIERTAS);
    const why = causa == null ? (tr("act.cut.why")) : causa;
    let n = 0;
    ids.forEach((id) => { if (cerrarAct(id, "fail", why)) n++; });
    // [FIX-P9] …y la línea con ellas: si el turno se murió, su hilo no puede seguir latiendo.
    cerrarLinea();
    return n;
  }

  /** errorCard — causa humana en 1 línea + reintento automático 1x + [Reintentar]. */
  function errorCard(cause, o) {
    o = o || {};
    clearVitals();                 // el turno terminó (mal): nada de spinner huérfano
    cerrarLinea();                 // [FIX-P9] …y su hilo se pliega con lo que alcanzó a hacer
    const acts = [];
    if (o.onRetry) acts.push({ label: tr("err.retry"), onClick: (b) => { b.disabled = true; b.textContent = tr("err.retrying"); o.onRetry(); } });
    (o.actions || []).forEach((a) => acts.push({ ghost: true, label: a.label, onClick: a.onClick }));
    addHTML(
      '<div class="errcard"' + (o.causa ? ' data-causa="' + esc(o.causa) + '"' : "") + ">" +
      "<b>" + esc(o.title || tr("err.title")) + "</b>" +
      "<p>" + inlineLogos(esc(cause)) + "</p>" +
      (o.auto ? '<p class="ac-auto">' + esc(tr("err.auto")) + "</p>" : "") +
      (acts.length ? '<div class="acts">' + actionsHTML(acts) + "</div>" : "") +
      "</div>");
  }

  /** offer — la oferta CONTEXTUAL: falta algo y el camino está ahí mismo, no en un menú. */
  function offer(text, actions, o) {
    o = o || {};
    addHTML(
      '<div class="ac-offer"' + (o.kind ? ' data-offer="' + esc(o.kind) + '"' : "") + ">" +
      "<b>" + (o.service ? faceHTML(o.service, 15) : "") + esc(o.title || tr("offer.title")) + "</b>" +
      "<p>" + inlineLogos(esc(text)) + "</p>" +
      '<div class="acts">' + actionsHTML(actions) + "</div></div>");
  }

  /** Los chips de sugerencia como HTML — sirven al intro (pre-render) y a `suggest()`. */
  function sugsHTML(list) {
    if (!list || !list.length) return "";
    return '<div class="ac-sugs">' + list.map((s) => {
      const label = typeof s === "string" ? s : s.label;
      const send = typeof s === "string" ? s : (s.send || s.label);
      return '<button type="button" class="ac-sug ac-action" data-ac-id="' +
        bindAction(() => {
          if (typeof s !== "string" && s.onClick) return s.onClick();
          if (opts.onSuggestion) return opts.onSuggestion(send);
          try { el.submitUserMessage({ text: send }); } catch (e) {}
        }) + '">' + esc(label) + "</button>";
    }).join("") + "</div>";
  }

  /** suggest — opciones por default: el chat nunca arranca como un campo vacío mudo. */
  function suggest(list) {
    const html = sugsHTML(list);
    if (html) addHTML(html);
  }

  /** card — escotilla para HTML propio de la superficie (gates, recibos, evidencia). */
  function card(html, actions) {
    addHTML(html + (actions && actions.length ? '<div class="acts">' + actionsHTML(actions) + "</div>" : ""));
  }

  /** slot(node) — mete un NODO YA CONSTRUIDO, con sus handlers VIVOS, en la conversación.
   *
   * Es la pieza que deja intactas las cards ricas que La Sala ya sabe armar (gate, recibo,
   * evidencia, obracard, delegación…): esas se construyen imperativamente y llevan `.onclick`
   * asignado a mano. Serializarlas a HTML (addMessage({html})) MATARÍA esos handlers —
   * botones que se ven bien y no hacen nada, el peor de los fallos mudos.
   *
   * Truco: deep-chat renderiza un mensaje html VACÍO que sirve de ranura, y después se MUEVE
   * el nodo real adentro. Mover un nodo del light DOM al shadow DOM conserva sus listeners y
   * sus propiedades — el nodo es el mismo objeto. Así el orden cronológico de la conversación
   * queda bien (es un mensaje más de la lista) y el estilo entra por `auxiliaryStyle`.
   */
  function slot(node) {
    if (!node) return null;
    q(() => {
      const id = "acs" + (++_actionSeq);
      el.addMessage({ role: "ai", html: '<div class="ac-slot" data-ac-slot="' + id + '"></div>' });
      const sr = shadow();
      const target = sr && sr.querySelector('[data-ac-slot="' + id + '"]');
      if (!target) {
        // Si la ranura no apareció, el mensaje NO se pierde en silencio (§4h): degrada a texto.
        console.error("[aleph-chat] no pude crear la ranura para una card — degrado a texto");
        el.addMessage({ role: "ai", text: (node.textContent || "").trim() });
        return;
      }
      target.appendChild(node);
      scrollDown();
    });
    return node;
  }

  function scrollDown() {
    const sr = shadow(); if (!sr) return;
    const box = sr.querySelector("#messages");
    if (box) box.scrollTop = box.scrollHeight;
  }

  /** closeTurn(signals) — cerrar el canal SIN haber streameado nada, y sin ruido.
   *
   * El Guía no streamea: su loop devuelve el turno entero y la respuesta se pinta después
   * con say(). Pero cerrar un stream que no emitió un solo evento hace que deep-chat tire
   * "No valid stream events were sent" por consola en CADA turno (y se arriesga a pintar su
   * propio globo de error). Se le entrega un evento válido y VACÍO, marcado como temporal
   * (`deep-chat-temporary-message`): el componente queda conforme y el propio deep-chat lo
   * borra en cuanto llega el mensaje real. */
  function hideNoop() {
    const sr = shadow(); if (!sr) return;
    sr.querySelectorAll(".ac-noop").forEach((noop) => {
      const outer = noop.closest(".outer-message-container");
      if (outer) {
        outer.hidden = true;
        outer.style.display = "none";
        outer.setAttribute("aria-hidden", "true");
      }
    });
  }
  function closeTurn(signals) {
    if (!signals) return Promise.resolve();
    let response;
    try {
      response = signals.onResponse({
        html: '<span class="deep-chat-temporary-message ac-noop"></span>',
      });
    } catch (e) {}
    const finish = () => {
      if (streaming) {
        try { return signals.onClose(); } catch (e) {}
      }
    };
    // onResponse es async en deep-chat. Cerrar antes recreaba el noop DESPUÉS de la
    // card de fallo y dejaba un globo vacío final. Esperamos su procesamiento y además
    // ocultamos el contenedor en JS: cero dependencia de la forma interna o de :has().
    return Promise.resolve(response).then(finish, finish).finally(() => {
      hideNoop();
      setTimeout(hideNoop, 0);
      setTimeout(hideNoop, 40);
    });
  }

  /** El último globo del agente que deep-chat pintó (para re-renderizarlo al cerrar). */
  function lastAIBubble() {
    const sr = shadow(); if (!sr) return null;
    const outs = sr.querySelectorAll(".outer-message-container.deep-chat-outer-container-role-ai");
    for (let i = outs.length - 1; i >= 0; i--) {
      const t = outs[i].querySelector(".ai-message-text, .message-bubble");
      if (t) return t;
    }
    return null;
  }

  /* ── LA BURBUJA VIVA ───────────────────────────────────────────────────────────────
   * `update(acumulado)` — el motor de La Sala entrega el texto COMPLETO en cada tick, y
   * deep-chat espera DELTAS: la diferencia se calcula acá, así el motor no cambia.
   * `finish(textoFinal)` — cierra el stream y RE-RENDERIZA el globo con markdown/figuras.
   * El texto que se streamea es crudo y el final viene limpio (cleanObra), así que el
   * globo se reemplaza en vez de dejar el crudo pintado.
   *
   * Con `signals` (turno nacido en el composer) usa el streaming NATIVO de deep-chat.
   * Sin `signals` (reintento, chip, retoma) pinta su propio globo y lo actualiza en sitio:
   * el mismo contrato para los dos caminos, así ningún caller tiene que preguntar.
   */
  function stream(signals) {
    let sent = "", closed = false, ownId = null;

    if (!signals) ownId = "acl" + (++_actionSeq);
    if (ownId) addHTML('<div class="ac-md" data-ac-live="' + ownId + '"></div>');
    const ownNode = () => { const sr = shadow(); return sr && sr.querySelector('[data-ac-live="' + ownId + '"]'); };

    /* Repintar "el último globo del agente" es una trampa, y cara: `onResponse` de deep-chat
     * es ASÍNCRONO, así que con una respuesta corta (un token y `done` en la misma lectura) el
     * globo del stream TODAVÍA NO EXISTE al cerrar el turno — y "el último" resulta ser el
     * mensaje ANTERIOR. Pasó de verdad: la respuesta se escribía encima de las OPCIONES DE
     * ARRANQUE y los chips desaparecían.
     *
     * Contar globos tampoco sirve: deep-chat abre un globo de LOADING al enviar y lo CONVIERTE
     * en el del stream, así que el total nunca crece. Lo que sí identifica al globo de este
     * turno es la marca que le pone el propio componente: `.streamed-message`. Si no aparece,
     * no se repinta — perder el markdown es barato; pisar otro mensaje, no. */
    const lastStreamed = () => {
      const sr = shadow(); if (!sr) return null;
      const all = sr.querySelectorAll(".streamed-message");
      return all.length ? all[all.length - 1] : null;
    };
    /* La marca `.streamed-message` SÓLO existe MIENTRAS el stream vive: al finalizar, deep-chat
     * se la saca. O sea que el globo hay que agarrarlo ANTES de cerrar el turno, no después. */
    const esperarGlobo = (quedan) => new Promise((res) => {
      const tick = () => {
        const t = lastStreamed();
        if (t || quedan-- <= 0) return res(t);
        setTimeout(tick, 25);
      };
      tick();
    });
    function paintFinal(txt, target) {
      if (ownId) { const n = ownNode(); if (n) put(n, txt); return; }
      if (target) { put(target, txt); return; }
      console.warn("[aleph-chat] el globo del stream nunca apareció — no repinto (no piso otro mensaje)");
    }
    /* Escribir el globo y RE-VERIFICAR que lo escrito sobrevivió.
     *
     * `onClose` dispara `finaliseStreamedMessage`, que vuelve a renderizar el mensaje desde
     * el texto que deep-chat guardó — y se lleva puesto lo que pintemos antes. No es una
     * carrera que se gane con un delay fijo: se escribe, se comprueba, y si el componente lo
     * pisó, se escribe otra vez. Máximo dos veces, para no pelearse para siempre. */
    function put(target, txt, reintento) {
      const write = (html) => {
        target.innerHTML = '<div class="ac-md">' + inlineLogos(html) + "</div>";
        q(enhanceLast); scrollDown();
        if (!reintento) setTimeout(() => {
          if (!target.querySelector(".ac-md")) put(target, txt, 1);   // deep-chat lo repintó
        }, 80);
      };
      if (window.SalaRender && window.SalaRender.renderMarkdown) {
        window.SalaRender.renderMarkdown(txt).then(write).catch(() => write(esc(txt).replace(/\n/g, "<br>")));
      } else write(esc(txt).replace(/\n/g, "<br>"));
    }

    return {
      update(acc) {
        acc = String(acc == null ? "" : acc);
        if (acc.length <= sent.length) return;
        const delta = acc.slice(sent.length);
        sent = acc;
        q(() => {
          if (signals) { clearVitals(); signals.onResponse({ text: delta }); return; }
          const n = ownNode(); if (n) { n.textContent = sent; scrollDown(); }
        });
      },
      finish(txt) {
        if (closed) return; closed = true;
        const fin = String(txt == null ? sent : txt);
        cerrarLinea();     // [FIX-P9] llegó la respuesta ⇒ el hilo del turno se pliega
        q(async () => {
          clearVitals();
          let target = null;
          if (signals) {
            // CERRAR UN STREAM SIN HABER EMITIDO NADA VÁLIDO hace que deep-chat pinte SU
            // globo de error ("No pude completar eso") — en un turno que salió BIEN. Un
            // texto vacío no cuenta como evento válido (upsertContent exige text/html
            // truthy), así que el placeholder invisible es obligatorio, no decorativo.
            if (!sent) {
              try {
                signals.onResponse(fin ? { text: fin }
                  : { html: '<span class="deep-chat-temporary-message ac-noop"></span>' });
              } catch (e) {}
            }
            target = await esperarGlobo(40);   // agarrar el globo ANTES de que pierda su marca
            try { signals.onClose(); } catch (e) {}
          }
          if (fin) paintFinal(fin, target);
        });
      },
      remove() {
        if (closed) return; closed = true;
        cerrarLinea();     // [FIX-P9] el turno se retira ⇒ nada queda latiendo
        q(() => {
          clearVitals();
          // mismo motivo: sin un evento válido, el cierre se ve como fallo aunque no lo sea.
          if (signals) closeTurn(signals);
          // El globo propio se VACÍA, no se arranca: es un mensaje que creó deep-chat y
          // sacarlo del DOM le deja la referencia colgada (ver el comentario de los vitales).
          const n = ownId ? ownNode() : null;
          if (n) {
            n.innerHTML = "";
            const w = n.closest(".outer-message-container");
            if (w) w.style.display = "none";
          }
        });
      },
      get sent() { return sent; },
    };
  }

  /** gated(on) — Send apagado PERO VIVO (el click entra igual y la superficie responde). */
  function gated(on) {
    if (on) el.setAttribute("data-gated", "1"); else el.removeAttribute("data-gated");
  }

  /* OJO: re-aplicar props REINICIA el render de deep-chat, y con él se van los mensajes ya
   * pintados. Por eso setLang es un no-op si el idioma no cambió — el Guía llama a su
   * localizeCop() en CADA apertura del panel, y eso borraba el saludo y las opciones de
   * arranque recién puestas, en silencio y sin un solo error. */
  function setLang(l) {
    const next = l === "en" ? "en" : "es";
    if (next === lang) return;
    lang = next;
    q(() => {
      applyStrings();
      try { el.setPlaceholderText(opts.placeholder || tr("ph." + surface)); } catch (e) {}
    });
  }

  /* ── LEY 1 · verificación en runtime: si alguien saca el font-family, se grita ────── */
  function assertLocalFirst() {
    const bad = [];
    if (!/font-family/.test(el.getAttribute("style") || "")) bad.push("falta font-family inline en <deep-chat>");
    try {
      const links = document.querySelectorAll('link[href*="fonts.googleapis.com"],link[href*="fonts.gstatic.com"]');
      if (links.length) bad.push("deep-chat inyectó " + links.length + " <link> a Google Fonts");
    } catch (e) {}
    if (bad.length) {
      // §4h — fallo VISIBLE, jamás mudo: romper local-first es un defecto de producto.
      console.error("[aleph-chat] LOCAL-FIRST ROTO: " + bad.join(" · "));
      try { window.__alephChatLocalFirst = { ok: false, problemas: bad }; } catch (e) {}
      return false;
    }
    try { window.__alephChatLocalFirst = { ok: true, problemas: [] }; } catch (e) {}
    return true;
  }

  host.appendChild(el);

  /* ── EL UPGRADE NO ALCANZA: HAY QUE ESPERAR EL RENDER ────────────────────────────
   * `whenDefined` sólo dice que la clase existe. deep-chat rechaza `addMessage` hasta que
   * su chat-view renderizó ("addMessage failed - please wait for chat view to render"),
   * y encima difiere el render mientras le sigan llegando propiedades
   * (`waitForPropertiesToBeUpdatedBeforeRender`). Es decir: configurar DISPARA un render
   * nuevo. Orden correcto y único que funciona:
   *   whenDefined → escuchar 'render' → configure() → (render) → recién ahí, mensajes.
   * Si el render no llega, se grita (§4h) en vez de tragarse los mensajes en silencio. */
  /* Esperar "un" render NO alcanza: el componente hace un primer render solo, y `configure()`
   * dispara OTRO (difiere mientras le lleguen props). Si se toma el primero por bueno, los
   * mensajes se insertan y el segundo render los BORRA — así desaparecían el saludo y las
   * opciones de arranque del Guía, sin un solo error. Hay que esperar a que se asiente:
   * `#messages` presente Y el componente sin renders pendientes (`_waitingToRender_`). */
  function whenSettled() {
    return new Promise((resolve) => {
      let done = false;
      const finish = () => { if (done) return; done = true; clearInterval(poll); clearTimeout(bomb); resolve(); };
      const listo = () => {
        const sr = el.shadowRoot;
        return !!(el._hasBeenRendered && !el._waitingToRender_ && sr && sr.querySelector("#messages"));
      };
      const poll = setInterval(() => { if (listo()) finish(); }, 25);
      const bomb = setTimeout(() => {
        if (done) return;
        console.error("[aleph-chat] el chat-view no terminó de renderizar en 8s — sigo igual, pero esto es un defecto");
        finish();
      }, 8000);
      if (listo()) finish();
    });
  }

  const readyP = loadBundle()
    .then(() => customElements.whenDefined("deep-chat"))
    .then(() => {
      try { customElements.upgrade(el); } catch (e) {}
      configure();                       // primero la config: ella misma dispara el render bueno
      return whenSettled();
    })
    .then(() => {
      upgraded = true;
      // El SALUDO + las opciones por default van como PRIMER MENSAJE, no como `introMessage`:
      // deep-chat pinta el intro en su primer render y la config llega después, así que por
      // esa vía el saludo no aparecía nunca. Como mensaje es determinista y verificable.
      const introHTML = (opts.intro || "") + sugsHTML(opts.suggestions);
      if (introHTML && opts.introChrome) {
        const box = shadow() && shadow().querySelector("#messages");
        if (box) {
          const intro = document.createElement("div");
          intro.className = "ac-intro ac-intro-chrome";
          intro.innerHTML = introHTML;
          box.insertBefore(intro, box.firstChild);
          introChromeNode = intro;
          if (typeof opts.onIntroReady === "function") opts.onIntroReady(intro);
        }
      } else if (introHTML) {
        el.addMessage({ role: "ai", html: '<div class="ac-intro">' + introHTML + "</div>" });
      }
      while (pending.length) { const fn = pending.shift(); try { fn(); } catch (e) { console.error("[aleph-chat]", e); } }
      assertLocalFirst();
      return ctl;
    });

  const ctl = {
    el: el, shadow: shadow,
    say: say, user: (t) => q(() => el.addMessage({ role: "user", text: String(t == null ? "" : t) })),
    action: action, card: card, slot: slot, errorCard: errorCard, offer: offer, suggest: suggest,
    // [FIX-P10 §1] el desenlace de las cards de acción (toda card cierra: ✓ o ✗ con causa)
    cerrarAct: cerrarAct, cerrarActs: cerrarActs, actsAbiertas: () => ABIERTAS.size,
    /* [FIX-P9] LA LÍNEA del turno. `action()` la abre sola, así que una superficie que sólo
     * emite acciones no necesita saber que existe. Las tres puertas explícitas son para
     * quien tiene MÁS que contar: razonamiento real, o el cierre de un turno que no pasa
     * por say()/stream(). `linea()` devuelve el estado VIVO — la vara lo compara, uno a
     * uno, contra los tool_calls de la telemetría. */
    pensar: pensar, cerrarLinea: cerrarLinea,
    linea: () => (LINEA
      ? { id: LINEA.id, viva: true, acciones: LINEA.acciones, razono: LINEA.razono, ms: Date.now() - LINEA.t0 }
      : null),
    // [FIX-P7] `bind(fn) → id` — la capa de OPCIONES arma su propio HTML (grupos, marcado,
    // apagado) y necesita colgarle handlers vivos dentro del shadow root. Es el mismo
    // registro que usan las cards de acá: un id por handler, despachado por htmlClassUtilities.
    bind: bindAction,
    stream: stream, closeTurn: closeTurn, scrollDown: scrollDown,
    input: () => { const sr = shadow(); return sr && sr.querySelector("#text-input"); },
    vitals: vitals, clearVitals: clearVitals, gated: gated,
    faceHTML: faceHTML, inlineLogos: inlineLogos, enhanceLast: enhanceLast,
    setLang: setLang, t: tr,
    clear: () => q(() => { try { el.clearMessages(); } catch (e) {} }),
    discardLastUser: (text) => q(() => {
      const sr = shadow(); if (!sr) return;
      const users = sr.querySelectorAll(".deep-chat-outer-container-role-user");
      const last = users[users.length - 1]; if (!last) return;
      const want = String(text || "").replace(/\s+/g, " ").trim();
      const body = last.querySelector(".user-message-text, .message-bubble");
      const got = String((body && body.textContent) || "")
        .replace(/\s+/g, " ").trim();
      if (want && got !== want) return;
      // No arrancar el nodo: DeepChat conserva refs internas y quitar sólo DOM las
      // corrompe. El submit rechazado no es transcript; se oculta sin romper el índice.
      last.hidden = true;
      last.style.display = "none";
      last.setAttribute("aria-hidden", "true");
      last.setAttribute("data-ac-discarded", "1");
    }),
    focus: () => q(() => { try { el.focusInput(); } catch (e) {} }),
    send: (text) => q(() => { try { el.submitUserMessage({ text: String(text || "") }); } catch (e) {} }),
    assertLocalFirst: assertLocalFirst,
    ready: readyP,
  };

  try {
    window.addEventListener("aleph:langchange", (e) => setLang((e && e.detail && e.detail.lang) || currentLang()));
  } catch (e) {}

  return ctl;
}

/* hook de verificación + acceso no-ESM (las superficies clásicas lo usan por window) */
try {
  window.AlephChat = { mount: mount, STRINGS: STRINGS, FONT_STACK: FONT_STACK, load: loadBundle };
} catch (e) {}

export default { mount };
