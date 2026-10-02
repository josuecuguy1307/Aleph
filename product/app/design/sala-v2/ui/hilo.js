// EL HILO — la superficie de assistant-ui con la piel de Aleph.
//
// Se escribe con `h()` (React.createElement) y NO con JSX a propósito: Aleph no tiene
// bundler en runtime, y el precedente del repo es exactamente éste — `support.js:180-183`
// monta React así desde hace nueve pantallas. La consecuencia práctica es que ESTE archivo
// se edita y se recarga; no hay build entre lo que se escribe y lo que corre. El único
// artefacto construido es `vendor/assistant-ui.bundle.js`, y sólo cambia si se sube de
// versión a un tercero.
//
// Ley 2 (se hereda la superficie, jamás su agente): de assistant-ui se usan las primitivas
// —hilo, composer, partes del mensaje— y su runtime de hilo. El cerebro entra por
// `AlephAgent`, que es Aleph. Nada de acá habla con un proveedor de modelo.

import {
  React,
  ThreadPrimitive,
  ComposerPrimitive,
  MessagePrimitive,
  useAuiState,
} from "../vendor/assistant-ui.bundle.js";
import { GateCard } from "./gate-card.js?v=sala-te";
import { TarjetaObra } from "./tarjeta-obra.js?v=sala-te";
// EL VOCABULARIO DE CAUSAS, COMPARTIDO. No se escribe copy nueva acá: `causas-catalogo.js`
// es el archivo sin dueño que ya usan la sección de conectores y el HUD del Cuarto, y
// existe justamente porque tener dos textos para el mismo hecho los desincroniza. Su regla
// sellada gobierna: ninguna causa llega a una superficie sin copy, y si el backend manda
// una que la tabla no conoce, se deriva una frase honesta marcada como provisional en vez
// de escupir el nombre técnico crudo.
import { causaDe } from "../../conectores/causas-catalogo.js?v=sala-te";

const h = React.createElement;

const tr = (clave, fallback) => {
  const s = typeof window !== "undefined" && window.t ? window.t(clave) : null;
  return s && s !== clave ? s : fallback;
};

// ── partes del mensaje ────────────────────────────────────────────────────────────────

/**
 * Texto del modelo, RENDERIZADO.
 *
 * EL DEFECTO, visto en pantalla: el markdown llegaba crudo al hilo. Se leía
 * `tocá **Pesos (ARS)**, **Dólares (USD)**` con los asteriscos a la vista, mientras la
 * MISMA pantalla, tres centímetros a la derecha, pintaba las obras con negritas y tablas.
 * Dos varas de calidad para el mismo texto según dónde caiga.
 *
 * NO SE AGREGA UN MOTOR: `render/sala-render.js` ya trae `marked` + `DOMPurify`
 * vendorizados y expone `renderMarkdown`, que es el MISMO camino por el que se pintan las
 * obras. Un segundo parser habría sido la clase de duplicación que este repo viene matando.
 *
 * ⚠️ `innerHTML` es seguro ACÁ y sólo acá: `mdToSafeHtml` sanitiza con DOMPurify
 * (`FORBID_TAGS: script, style, iframe, object, embed, form`). El texto del modelo es
 * contenido no confiable —puede traer lo que un documento leído le haya dictado— así que
 * pasa por el mismo filtro que una obra. Sin sanitizador no se pinta HTML.
 *
 * MIENTRAS LLEGA, EL TEXTO PLANO. El render es asíncrono (carga sus libs una vez) y el
 * texto STREAMEA: si esperara, el usuario vería el mensaje aparecer de golpe al final. Se
 * muestra plano y se reemplaza al resolver — nunca vacío. Y si `SalaRender` no está, se
 * queda en plano para siempre, que es exactamente lo que hacía antes: degradar, no romper.
 */
function ParteTexto({ text }) {
  const ref = React.useRef(null);
  const [html, setHtml] = React.useState(null);
  React.useEffect(() => {
    let vivo = true;
    const R = typeof window !== "undefined" ? window.SalaRender : null;
    if (!R || typeof R.renderMarkdown !== "function") { setHtml(null); return; }
    R.renderMarkdown(String(text == null ? "" : text))
      .then((h2) => { if (vivo) setHtml(h2); })
      .catch(() => { if (vivo) setHtml(null); });   // fallo ⇒ plano, jamás en blanco
    return () => { vivo = false; };
  }, [text]);
  // Post-markdown: ```chart / spec JSON válido → SVG. Lo hace SalaRender.renderInlineFigures
  // (el mismo camino que las obras y el chat clásico). Sin este paso, marked deja el JSON
  // como <pre><code> y el usuario ve el spec en vez del gráfico.
  React.useEffect(() => {
    const node = ref.current;
    if (!node || html == null) return;
    const R = typeof window !== "undefined" ? window.SalaRender : null;
    try { if (R && R.renderInlineFigures) R.renderInlineFigures(node); } catch (e) {}
    try { if (R && R.highlightIn) R.highlightIn(node); } catch (e) {}
    // [Educación] Y EL MATH, por el mismo camino que las obras. `runKatex` estaba escrito
    // y probado en `sala-render.js` desde siempre —las obras lo llaman— y esta burbuja,
    // que pinta el MISMO texto del MISMO modelo, no lo llamaba: el mecanismo estaba y le
    // faltaba el llamador. Medido en `aleph.db`: 38 bloques `$$…$$` en las 24 respuestas
    // del hilo de Educación, todos crudos en pantalla.
    try { if (R && R.runKatex) R.runKatex(node); } catch (e) {}
  }, [html]);
  return html == null
    ? h("div", { className: "sv-burbuja" }, text)
    : h("div", { className: "sv-burbuja sv-md", ref, dangerouslySetInnerHTML: { __html: html } });
}

/**
 * Razonamiento. Va en su propio bloque, nunca mezclado con la respuesta: son dos cosas
 * distintas y el pedido lo exige explícitamente. Sólo aparece si el modelo lo emitió de
 * verdad — Aleph jamás fabrica un `thinking` (router.py:2496-2498 lo declara así).
 */
function ParteRazonamiento({ text }) {
  if (!text) return null;
  return h(
    "div",
    { className: "sv-razon" },
    h("div", { className: "sv-razon-tit" }, tr("salav2.razonando", "Razonando")),
    text,
  );
}

/**
 * Una herramienta en el hilo.
 *
 * El estado sale del sobre tal cual: `ok` / `error` / `gated` son los tres valores que
 * `tool_call_finished.status` puede tomar (§C.1 del censo). Mientras no cerró, no se
 * inventa un veredicto: se dice que está corriendo.
 */
function ParteTool({ toolName, result, status, argsText }) {
  const meta = window.__salaV2?.toolMeta?.(toolName) || null;
  const st = meta?.status || (result !== undefined ? "ok" : null);
  const etiqueta = st
    ? { ok: tr("salav2.tool.ok", "listo"), error: tr("salav2.tool.error", "falló"), gated: tr("salav2.tool.gated", "necesita tu OK") }[st] || st
    : tr("salav2.tool.corriendo", "corriendo…");
  const ms = meta?.latency_ms;
  return h(
    "div",
    { className: "sv-tool", title: argsText || "" },
    h("span", { className: "sv-punto " + (st || "") }),
    h("span", { className: "nom" }, toolName || "herramienta"),
    h("span", { className: "est" }, ms != null ? `${etiqueta} · ${ms} ms` : etiqueta),
  );
}

// ── mensajes ──────────────────────────────────────────────────────────────────────────

const componentesDeParte = {
  Text: ParteTexto,
  Reasoning: ParteRazonamiento,
  tools: { Fallback: ParteTool },
};

function MensajeUsuario() {
  return h(
    MessagePrimitive.Root,
    { className: "sv-msg user", "data-no-tm": "" },
    h(MessagePrimitive.Parts, { components: { Text: ParteTexto } }),
  );
}

function MensajeAgente() {
  return h(
    MessagePrimitive.Root,
    { className: "sv-msg assistant", "data-no-tm": "" },
    h(MessagePrimitive.Parts, { components: componentesDeParte }),
    // Fallo visible, jamás mudo: si el turno murió, el hilo lo dice en el lugar del turno,
    // no en una consola ni en un toast que se va.
    h(MessagePrimitive.Error, { className: "sv-error" }),
  );
}

// ── el estado en vivo (1.4) ───────────────────────────────────────────────────────────

/**
 * Se suscribe a la máquina de estados, que a su vez lee los MISMOS eventos AG-UI que
 * alimentan el hilo. Una sola fuente ⇒ el estado y el hilo no pueden divergir.
 */
/* La línea de razonamiento.
 *
 * ⚠️ `vivo` NO ES UN EXTRA: sin él este componente es MUDO para las capacidades de la Sala,
 * y lo era. `s.thread.isRunning` es el reloj de **assistant-ui**, y ni la búsqueda web ni
 * la investigación a fondo corren por ese runtime —corren por su propio NDJSON—, así que
 * durante toda la obra valía `false` y la guardia de abajo devolvía `null` pasara lo que
 * pasara. La máquina recibía cada etapa, las traducía bien, y no se pintaba ninguna.
 *
 * MEDIDO EN PANTALLA, y sólo ahí: el stream trae los sobres, el artefacto nace, el backend
 * dice 200 y la vara pasa. Lo único que falla es lo único que el usuario ve.
 *
 * Le pasa igual a §6.a.bis —es el mismo componente y el mismo reloj—, así que el arreglo es
 * de los dos: `vivo` lo enciende cualquier capacidad de la Sala mientras su stream está
 * abierto, y el `corriendo` de assistant-ui sigue gobernando el turno del agente.
 */
function EstadoVivo({ maquina, vivo }) {
  const [v, setV] = React.useState(() => ({ estado: "quieto", texto: "" }));
  React.useEffect(() => {
    maquina.onCambio = setV;
    return () => {
      maquina.onCambio = () => {};
    };
  }, [maquina]);

  const corriendo = useAuiState((s) => s.thread.isRunning);
  if (!corriendo && !vivo && v.estado !== "esperando_ok") return null;
  if (!v.texto) return null;

  return h(
    "div",
    { className: "sv-estado", "data-estado": v.estado, role: "status", "aria-live": "polite" },
    h("span", { className: "sv-pulso" }),
    h("span", null, v.texto),
  );
}

// ── el composer ───────────────────────────────────────────────────────────────────────

/* ══════════════════════════════════════════════════════════════════════════════════════
 * LOS DOS MODOS DE LA SALA — Y SON INTERRUPTORES, NO GATILLOS
 * [§6.a.bis · §6.f]
 *
 * ⚠️ ESTO CAMBIÓ, Y EL CAMBIO ES DE COMPORTAMIENTO, NO DE ESTILO.
 *
 * La primera versión de los dos botones MANDABA el turno al apretarlos: un clic y ya
 * estabas buscando. Eso convierte una decisión en un accidente —el usuario no llega a
 * saber en qué modo está antes de mandar— y deja al modo largo, que corre minutos, a un
 * clic de distancia de cualquier resbalón.
 *
 * Ahora son **interruptores que el usuario prende y quedan prendidos hasta que los
 * apague**. Es el mismo trato que Claude le da a estas dos capacidades, y descansa en tres
 * reglas:
 *
 *   1. **NADIE LOS PRENDE MENOS EL USUARIO.** El agente no decide salir a internet ni
 *      arrancar una investigación de minutos. Se cumple más abajo del frente y está
 *      medido: el CLI corre con `web_search="disabled"`
 *      (`platform/assembler/cli_brain/codex_cli.py:201`) y ni `sala_busqueda` ni
 *      `sala_research` se le ofrecen como tool al assembler. Acá arriba, la única forma de
 *      encender un modo es este botón.
 *
 *   2. **SE VEN PRENDIDOS.** `aria-pressed` para quien escucha la pantalla y
 *      `.sv-modo-on` —fondo lleno, no un borde— para quien la mira. Y el placeholder del
 *      composer lo dice con palabras: saber en qué modo estás no puede depender de
 *      distinguir dos tonos de un borde.
 *
 *   3. **JAMÁS LOS DOS A LA VEZ.** No es una validación: es la forma del dato. El modo es
 *      **una sola variable** (`null | "buscar" | "investigar"`), así que prender uno apaga
 *      el otro por construcción y no hay estado en el que los dos estén encendidos.
 *      Deep Research ya busca por dentro —§6.f depende de §6.a.bis a propósito— así que
 *      prender los dos sería buscar dos veces y pagarlo dos veces.
 * ══════════════════════════════════════════════════════════════════════════════════════ */

const MODOS = {
  buscar: {
    icono: "◎",
    etiqueta: () => tr("salav2.buscarweb", "Buscar en la web"),
    title: () => tr("salav2.buscarweb.title", "Buscar en la web y responder con fuentes"),
    ph: () => tr("salav2.buscarweb.ph", "Busca en la web…"),
    clase: "sv-buscar-web",
  },
  investigar: {
    icono: "◈",
    etiqueta: () => tr("salav2.investigar", "Investigar a fondo"),
    title: () => tr("salav2.investigar.title",
                    "Investigación larga: busca, lee y escribe un informe con fuentes. Tarda minutos y se puede parar."),
    ph: () => tr("salav2.investigar.ph", "Qué quieres que investigue a fondo…"),
    clase: "sv-investigar",
  },
};

function BotonModo({ modo, activo, onToggle }) {
  const m = MODOS[modo];
  const corriendo = useAuiState((s) => s.thread.isRunning);
  return h(
    "button",
    {
      type: "button",
      className: m.clase + (activo ? " sv-modo-on" : ""),
      // NO se deshabilita con el composer vacío: prender un modo es una decisión previa a
      // escribir. La primera versión lo ataba al texto —herencia de cuando el botón
      // mandaba el turno— y eso obligaba a escribir antes de poder elegir cómo mandar.
      disabled: corriendo,
      "aria-pressed": activo ? "true" : "false",
      title: m.title(),
      "aria-label": m.etiqueta(),
      onClick: () => onToggle?.(activo ? null : modo),
    },
    m.icono + " ", m.etiqueta(),
  );
}

/* [§6.f] PARAR LA INVESTIGACIÓN — el botón que su hermano no necesita.
 *
 * NO es el «Parar» de assistant-ui: aquél llama al `onCancel` del runtime, que aborta el
 * fetch del turno del agente. Una investigación no corre por ese runtime —corre por el
 * NDJSON de `investigar.js`— así que ese botón no la vería. Y abortar el fetch del lado
 * del navegador dejaría al motor corriendo y cobrando: sería teatro.
 *
 * Éste le pide al MOTOR que pare. Sólo existe mientras hay una obra viva (`obraId`), que es
 * el id que llegó en la primera línea del stream, así que aparece apenas arranca y se va
 * solo cuando termina. Un botón de parar visible sobre algo que ya terminó es una promesa
 * que no se puede cumplir.
 */
function BotonPararObra({ obraId, parando, onParar }) {
  if (!obraId) return null;
  return h(
    "button",
    {
      type: "button",
      className: "sv-parar-obra",
      disabled: !!parando,
      title: tr("salav2.pararobra.title", "Parar esta investigación"),
      "aria-label": tr("salav2.pararobra.aria", "Parar la investigación"),
      onClick: () => onParar?.(),
    },
    parando ? tr("salav2.pararobra.parando", "Parando…")
            : "■ " + tr("salav2.pararobra", "Parar la investigación"),
  );
}

/** Vacía el `<textarea>` del composer avisándole a React. */
function vaciarComposer() {
  const ta = document.querySelector(".sv-composer textarea");
  if (!ta) return;
  // El setter nativo + un `input` sintético: React escucha su propio onChange, así que
  // asignar `.value` a secas no le avisa y el composer se queda con el texto. Es una
  // limitación del bundle de assistant-ui que vendorizamos —no exporta el runtime del
  // composer—, declarada acá para que se vea que es del vendor y no una preferencia.
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype, "value")?.set;
  setter ? setter.call(ta, "") : (ta.value = "");
  ta.dispatchEvent(new Event("input", { bubbles: true }));
}

/* ══ ADJUNTAR · [T2.5] ══════════════════════════════════════════════════════════════════
 * LA BOCA QUE FALTABA. El cable estaba entero de punta a punta y sin nadie que lo llenara:
 * `router.py` acepta `images` (data-URLs) y las manda al modelo multimodal, `aleph-agent.js`
 * arma `attachments` y pide la capacidad `vision`… y la Sala no tenía por dónde. Medido: UN
 * solo hit de «attach» en toda la carpeta, y era consumidor.
 *
 * SÓLO IMÁGENES, y el copy lo dice. El contrato del backend es `images: list[str]` de
 * data-URLs; ofrecer un PDF acá sería un botón que promete algo que ese campo no transporta.
 * Los documentos entran por otro brazo del kit (`markitdown`), que es otra obra.
 *
 * El límite es del transporte, no del gusto: una data-URL viaja DENTRO del JSON del POST, así
 * que un archivo grande no es «lento», es un body que el server rechaza. Se corta acá con
 * causa visible en vez de dejar que falle el turno entero.
 */
//: El mismo tope que declara el store (`inbox_store.MAX_BYTES`). Se repite acá para poder
//: decirlo ANTES de subir 25 MB y que el server los rechace — no para decidirlo: quien
//: manda es el backend, y si difieren gana su 413.
const ADJUNTO_MAX_BYTES = 25 * 1024 * 1024;

/** ¿Es una imagen? Sólo de ésas se hace miniatura y sólo ésas necesitan visión. */
function esImagen(f) {
  return typeof f?.type === "string" && f.type.startsWith("image/");
}

function BotonAdjuntar({ onAdjuntar }) {
  const ref = React.useRef(null);
  const elegir = async (e) => {
    const files = [...(e.target.files || [])];
    e.target.value = "";                       // el mismo archivo dos veces seguidas también cuenta
    for (const f of files) {
      if (f.size > ADJUNTO_MAX_BYTES) {
        onAdjuntar({ error: tr("salav2.adjuntar.grande", "Pesa demasiado."), nombre: f.name });
        continue;
      }
      // La MINIATURA es sólo para imágenes: de un PDF no hay nada que previsualizar acá, y
      // leerlo entero a un data-URL sería cargar 20 MB en memoria para no mostrar nada.
      let dataUrl = "";
      if (esImagen(f)) {
        dataUrl = await new Promise((res) => {
          const r = new FileReader();
          r.onload = () => res(String(r.result || ""));
          r.onerror = () => res("");
          r.readAsDataURL(f);
        });
      }
      onAdjuntar({ nombre: f.name, dataUrl, archivo: f, esImagen: esImagen(f) });
    }
  };
  return h(
    React.Fragment,
    null,
    h("input", {
      // Lo que el kit SABE LEER, medido (`qa/verify_kit_lee_documentos.py`): markitdown
      // hace pdf/docx/xlsx/pptx, filesystem hace el texto plano, y las imágenes van por
      // visión. No se ofrece nada que después no se pueda abrir.
      ref, type: "file", multiple: true,
      accept: "image/*,.pdf,.docx,.xlsx,.pptx,.txt,.md,.csv,.tsv,.json,.xml,.yaml,.yml,.html",
      style: { display: "none" }, onChange: elegir,
      "data-testid": "sv-adjuntar-input",
    }),
    h("button", {
      type: "button", className: "sv-modo-btn", "data-testid": "sv-adjuntar",
      title: tr("salav2.adjuntar.title", "Adjuntar una imagen"),
      "aria-label": tr("salav2.adjuntar.title", "Adjuntar una imagen"),
      onClick: () => ref.current && ref.current.click(),
    }, "📎"),
  );
}

/**
 * Lo adjunto, visible ANTES de enviar: adjuntar a ciegas es adjuntar sin saber qué.
 *
 * ES LA MINIATURA, NO UN CHIP DE TEXTO — y el patrón se tomó de Oficina, que ya lo tenía
 * resuelto (`openwork/.../chat/image-attachment-badge.tsx`): recuadro de 40×40 con la
 * IMAGEN de verdad, la ✕ flotando en la esquina con fondo sólido, y click para ampliar.
 * Un `📎 archivo.png` es el nombre de algo que el usuario ya sabe cómo se llama; lo que no
 * sabe —y por lo que mira— es CUÁL de sus capturas agarró.
 *
 * ⚠️ EL AVISO DE VISIÓN VA ACÁ, ANTES DE ENVIAR. `cli.claude_cli` y `cli.codex_cli`
 * declaran `[text, streaming, tool_calling, reasoning, code]` — SIN `vision` (medido en
 * `centro_modelos._PICKER_HOSTEADO`). Un turno con imagen y ese cerebro falla cerrado con
 * `capability_unavailable` y 409, que es correcto pero LLEGA TARDE: el humano ya escribió
 * el mensaje. Con el cerebro que no ve, se dice acá y se dice antes.
 */
function Adjuntos({ adjuntos, onQuitar, puedeVer }) {
  if (!adjuntos || !adjuntos.length) return null;
  // El aviso de visión sólo aplica a IMÁGENES: un PDF no lo lee el modelo con los ojos,
  // lo lee el kit con markitdown, y decir «tu cerebro no ve» al adjuntar un PDF sería
  // asustar por algo que no pasa.
  const hayImagen = adjuntos.some((a) => !a.error && a.dataUrl);
  return h(
    "div",
    { className: "sv-adjuntos", "data-testid": "sv-adjuntos" },
    adjuntos.map((a, i) => {
      const quitar = h("button", {
        type: "button", className: "sv-adjunto-x",
        "aria-label": tr("salav2.adjuntar.quitar", "Quitar"),
        title: tr("salav2.adjuntar.quitar", "Quitar"),
        onClick: (e) => { e.stopPropagation(); onQuitar(a.id ?? i); },
      }, "×");
      if (a.error) {
        return h("span", { key: a.id ?? i, className: "sv-adjunto sv-adjunto-error", title: a.error },
          `⚠ ${a.nombre}`, quitar);
      }
      if (!a.dataUrl) {
        // DOCUMENTO: no hay miniatura que mostrar, así que se muestra lo que sí importa —
        // el nombre, que es como el usuario va a referirse a él cuando pregunte.
        return h("span", { key: a.id ?? i, className: "sv-adjunto sv-adjunto-doc", title: a.nombre },
          h("span", { className: "sv-adjunto-nombre" }, a.nombre),
          a.subiendo ? h("span", { className: "sv-adjunto-estado" }, "…") : null,
          quitar);
      }
      return h("span", { key: a.id ?? i, className: "sv-adjunto-mini", title: a.nombre },
        // ⚠️ SIN `loading="lazy"`. Oficina lo usa y ahí está bien: sus miniaturas salen de una
        // URL remota en una lista larga. Acá el src es un data-URL que YA está en memoria —
        // diferirlo no ahorra una petición porque no hay petición— y MEDIDO en el navegador
        // dejaba la miniatura en `complete:false`, `naturalWidth:0`: el recuadro se dibujaba
        // vacío. Copiar el patrón incluye saber qué parte del patrón no aplica.
        h("img", { src: a.dataUrl, alt: a.nombre, decoding: "async" }),
        quitar);
    }),
    hayImagen && puedeVer === false
      ? h("span", { className: "sv-adjunto-aviso", "data-testid": "sv-adjunto-sin-vision" },
          tr("salav2.adjuntar.sin_vision",
             "El cerebro que elegiste no puede ver imágenes. Elige otro modelo o saca la imagen."))
      : null,
  );
}

function Composer({ modeloSelector, modoSala, onModo, onEnviarModo, onPrimeraTecla, adjuntos, onAdjuntar, onQuitarAdjunto, puedeVer,
                   obraViva, parando, onParar }) {
  const texto = useAuiState((s) => s.composer?.text || "");
  const enviarModo = () => {
    const q = (texto || "").trim();
    if (!q || !modoSala) return;
    // El diálogo de proveedor puede terminar en Cancel. Conservar la consulta hasta
    // que el usuario haya confirmado evita perder el borrador por sólo abrirlo.
    onEnviarModo?.(modoSala, q, vaciarComposer);
  };
  return h(
    "div",
    { className: "sv-composer-wrap" },
    h(Adjuntos, { adjuntos, onQuitar: onQuitarAdjunto, puedeVer }),
    h(
      ComposerPrimitive.Root,
      {
        className: "sv-composer" + (modoSala ? " sv-composer-modo" : ""),
        // EL ENTER TAMBIÉN TIENE QUE RESPETAR EL MODO. Sin esto el botón mandaba por el
        // modo y la tecla mandaba un turno normal: dos caminos para el mismo gesto, y el
        // usuario descubriendo cuál tomó recién al ver el resultado. Se intercepta en
        // CAPTURA, antes de que assistant-ui lo vea.
        onKeyDownCapture: (e) => {
          if (!modoSala) return;
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent?.isComposing) {
            e.preventDefault();
            e.stopPropagation();
            enviarModo();
          }
        },
      },
      modeloSelector || null,
      onModo ? h(BotonModo, { modo: "buscar", activo: modoSala === "buscar", onToggle: onModo }) : null,
      onModo ? h(BotonModo, { modo: "investigar", activo: modoSala === "investigar", onToggle: onModo }) : null,
      h(BotonPararObra, { obraId: obraViva, parando, onParar }),
      onAdjuntar ? h(BotonAdjuntar, { onAdjuntar }) : null,
      h(ComposerPrimitive.Input, {
        rows: 1,
        autoFocus: true,
        // ── LA PRIMERA TECLA CREA EL HILO ────────────────────────────────────────────
        // Y con el hilo nace su carpeta, así que el backend puede arrancar sus MCP
        // MIENTRAS la persona termina de escribir. Antes el hilo se creaba al MANDAR
        // (`asegurarHilo` desde el adaptador), o sea con cero ventana: el t1 pagaba los
        // ~2,3 s de arranque enteros.
        //
        // ⚠️ EN LA PRIMERA TECLA Y NO AL ABRIR EL COMPOSER, a propósito. `list_chats` NO
        // filtra hilos vacíos, así que crear al abrir llenaría la lista de «Sin título»
        // cada vez que alguien mira la Sala y no escribe. Con la primera tecla hay
        // intención, y un hilo que se abandonó después de empezar a escribir es un
        // borrador — que es otra cosa que un vacío.
        //
        // `asegurarHilo` ya es idempotente (corta si hay hilo o si hay uno en vuelo), así
        // que dispararlo de más no cuesta nada y esto no necesita su propia guardia.
        onInput: onPrimeraTecla ? (e) => {
          if ((e?.target?.value || "").length > 0) onPrimeraTecla();
        } : undefined,
        // EL PLACEHOLDER DICE EL MODO. Es la mitad de la regla «tienen que verse
        // prendidos»: el color del botón dice cuál, y esto dice qué va a pasar cuando
        // aprete Enter — que es la pregunta que el usuario se está haciendo.
        placeholder: modoSala ? MODOS[modoSala].ph()
                              : tr("salav2.composer.ph", "Escribe lo que necesitas…"),
      }),
      // Enviar y Parar son el mismo lugar, y sólo uno existe por vez: mientras corre, el
      // botón para; mientras no, envía. `Cancel` de assistant-ui llama al `onCancel` del
      // runtime, que en el adaptador aborta el fetch y cierra el stream.
      //
      // ⚠️ CON UN MODO PRENDIDO, EL ENVIAR NO ES EL DE assistant-ui. Su `Send` manda el
      // turno por el runtime del agente, que no sabe nada de estas dos capacidades: dejarlo
      // ahí haría que el botón mandara un turno normal mientras la pantalla dice que está
      // en modo búsqueda. Un botón que hace otra cosa que lo que la pantalla anuncia es
      // peor que no tener modo. Así que con modo prendido se pinta el nuestro, con el mismo
      // aspecto y el mismo lugar, y el del vendor no se monta.
      h(
        ThreadPrimitive.If,
        { running: false },
        modoSala
          ? h("button", {
              type: "button",
              className: "sv-enviar",
              disabled: !(texto || "").trim(),
              "aria-label": MODOS[modoSala].etiqueta(),
              title: MODOS[modoSala].title(),
              onClick: enviarModo,
            }, "↑")
          : h(ComposerPrimitive.Send, { className: "sv-enviar", "aria-label": tr("salav2.enviar", "Enviar") }, "↑"),
      ),
      h(
        ThreadPrimitive.If,
        { running: true },
        h(ComposerPrimitive.Cancel, { className: "sv-parar" }, tr("salav2.parar", "Parar")),
      ),
    ),
  );
}

// ── el hilo entero ────────────────────────────────────────────────────────────────────

/**
 * UNA DELEGACIÓN — el agente le pidió algo a otro agente.
 *
 * Es la única pieza del trabajo del agente que la Sala vieja mostraba y ésta no: la
 * JERARQUÍA. Sin esto, un turno con seis sub-agentes se ve igual que uno con cero — todo
 * plano, sin quién le pidió qué a quién.
 *
 * TRES ESTADOS, Y NINGUNO SE INVENTA:
 *   · abierta        → el sub-agente está trabajando AHORA (llegó el `started`, no el fin)
 *   · cerrada        → ✓ o ✕ según el veredicto que mandó el espinazo
 *   · retenida       → `held > 0`: quedó esperando un OK del humano. No es ✓ ni ✕.
 *
 * Una fila que nunca cierra SE VE ABIERTA. Un sub-agente que no volvió es un hecho del
 * turno; disimularlo con un ✓ sería la fabricación que el anti-grift existe para atrapar.
 */
function Delegacion({ d }) {
  const [abierto, setAbierto] = React.useState(false);
  const marca = !d.cerrada ? "…" : d.retenido ? "⏸" : d.estado === "ok" ? "✓" : "✕";
  const clase = !d.cerrada ? "viva" : d.retenido ? "held" : d.estado === "ok" ? "ok" : "no";
  const hayDetalle = !!d.devolvio;
  return h(
    "div",
    { className: "sv-deleg " + clase },
    h(
      "div",
      { className: "sv-deleg-head" },
      h("span", { className: "d" }, "↳"),
      h(
        "span",
        // El `title` lleva la tarea COMPLETA: la línea se corta para el layout y el dato
        // entero queda a un hover de distancia. Es la misma decisión que la Sala vieja.
        { className: "dt", title: d.tarea || "" },
        tr("salav2.deleg.pedi", "Le pedí a") + " «" + d.nombre + "»",
        d.tarea
          ? h("span", { className: "dq" }, tr("salav2.deleg.que", " que: ") + d.tarea)
          : null,
      ),
      h("span", { className: "dok " + clase }, marca),
      hayDetalle
        ? h(
            "button",
            {
              type: "button",
              className: "sv-deleg-tog",
              "data-testid": "sv-deleg-ver",
              onClick: () => setAbierto((v) => !v),
            },
            abierto ? tr("salav2.deleg.ocultar", "ocultar ▾") : tr("salav2.deleg.ver", "ver ▸"),
          )
        : null,
    ),
    abierto && d.devolvio
      ? h(
          "div",
          { className: "sv-deleg-sub" },
          h("span", { className: "d" }, marca),
          h("span", null, tr("salav2.deleg.devolvio", "devolvió: ") + d.devolvio),
        )
      : null,
  );
}

export function Hilo({ maquina, gates, onGateDecidido, avisos, fallo, modeloSelector,
                       modelIdentity,
                       modoSala, onModo, onEnviarModo, onPrimeraTecla,
                       adjuntos, onAdjuntar, onQuitarAdjunto, puedeVer,
                       obraViva, parandoObra, onPararObra, capacidadViva,
                       delegaciones, tarjetas, destinos, onAbrirObra, onIrAlWorkspace,
                       refOpciones }) {
  return h(
    ThreadPrimitive.Root,
    { className: "sv-main" },
    h(
      "div",
      { className: "sv-head" },
      h("span", { className: "sv-title" }, tr("salav2.titulo", "La Sala")),
      // El modelo tiene un único dueño visual: el chip permanente del composer. Repetirlo
      // acá arriba convertía una elección en dos controles aparentes y alejaba el patrón
      // de chat que siguen las superficies OSS de referencia.
    ),
    h(
      ThreadPrimitive.Viewport,
      { className: "sv-vp", autoScroll: true },
      h(
        "div",
        { className: "sv-thread" },
        h(
          ThreadPrimitive.Empty,
          null,
          h(
            "div",
            { className: "sv-vacio-hilo" },
            tr("salav2.vacio", "Cuéntame qué necesitas y lo hacemos."),
          ),
        ),
        h(ThreadPrimitive.Messages, {
          components: { UserMessage: MensajeUsuario, AssistantMessage: MensajeAgente },
        }),
        // [T2.3] LA ISLA DE LOS WIDGETS DEL TURNO. Va DESPUÉS de los mensajes y ANTES de
        // los sub-agentes: una opción es algo que el agente te acaba de preguntar, así que
        // pertenece al final de lo que dijo. El contenido lo dibuja `opciones.js` por DOM
        // (ver `opciones-host.js`), así que React sólo pone el hueco y no toca lo de adentro
        // — por eso el ref y ningún hijo declarado acá.
        h("div", { className: "sv-opt-host", "data-testid": "sv-opciones", ref: refOpciones }),
        // LOS SUB-AGENTES DE ESTE TURNO, mientras trabajan. Van DESPUÉS de los mensajes y
        // ANTES de los gates: primero lo que el agente dijo, después quién está trabajando
        // para él, y al final lo que espera tu decisión.
        (delegaciones || []).length
          ? h(
              "div",
              { className: "sv-delegs", "data-testid": "sv-delegaciones" },
              (delegaciones || []).map((d) => h(Delegacion, { key: d.clave, d })),
            )
          : null,
        // EL FALLO DEL TURNO, AL NIVEL DEL HILO.
        //
        // `MessagePrimitive.Error` (abajo, dentro de MensajeAgente) sólo pinta si YA hay un
        // mensaje al que colgarse. Un turno que muere ANTES de que el modelo diga una letra
        // no tiene ese mensaje — y la vara sobre la .app instalada midió exactamente eso:
        // `RUN_STARTED → RUN_ERROR` con la pantalla en silencio absoluto. El fallo del RUN
        // es del hilo, no de un mensaje, así que vive acá. Los dos coexisten a propósito:
        // cubren momentos distintos del turno.
        fallo
          ? (() => {
              // El mensaje del backend suele ser un identificador (`auth-rejected`,
              // `sin_red`…). Se traduce por el catálogo compartido; el crudo NO se tira —
              // baja a una línea técnica, que es lo que hace falta para reportar un bug sin
              // obligar al usuario a leerlo como si fuera la explicación.
              // `fallo.causa` es la CLAVE (string). Si alguna vía todavía sube el objeto
              // tipado, se desarma acá en vez de dejarlo caer en un `[object Object]`.
              const clave = fallo.causa && typeof fallo.causa === "object"
                ? fallo.causa.causa ?? null
                : fallo.causa ?? null;
              const c = causaDe(clave || fallo.mensaje, clave);
              const crudo = clave || fallo.mensaje;
              const cooldownLocal = fallo.runtime_state === "local_cooldown_from_previous_limit";
              const limiteProveedor = fallo.provider_rate_limit_event;
              const resetHintAnterior = limiteProveedor?.reset_hint ||
                (Number.isFinite(Number(limiteProveedor?.retry_after_s))
                  ? `${Math.ceil(Number(limiteProveedor.retry_after_s))} s` : "");
              const etiquetaReset = cooldownLocal
                ? tr("salav2.err.cooldown_reset", "Pista de reintento del límite anterior: ")
                : fallo.runtime_state === "provider_rate_limited"
                  ? tr("salav2.err.provider_reset", "Pista indicada por el proveedor: ")
                  : "";
              const diagnosticoTecnico = fallo.diagnostic || (crudo !== fallo.mensaje ? crudo : "");
              // Si el catálogo CONOCE la causa, manda su copy: es el vocabulario compartido
              // y no se le escribe una segunda versión. Si NO la conoce, su frase de
              // respaldo habla de «esta pieza» —está escrita para el viaje de un conector,
              // no para un turno de chat— y usarla acá sería honesta pero del dominio
              // equivocado. En ese caso el respaldo lo pone La Sala, y se marca provisional
              // igual, que es lo que la regla sellada pide: la falta se ve y se arregla.
              // EL DETALLE DEL BACKEND MANDA. «Se agotó tu ventana de uso del CLI» está
              // escrito donde la causa nace y es mejor copy que cualquiera que inventemos
              // acá; el catálogo queda para las causas que llegan sin texto propio.
              const texto = cooldownLocal
                ? tr("salav2.err.cooldown",
                    "Claude Code tuvo un límite temporal anteriormente. Aleph sigue respetando la ventana local de reintento; no puede confirmar la cuota disponible ahora.")
                : fallo.mensaje && fallo.detalle_propio
                  ? fallo.mensaje
                : c && !c.provisional
                  ? c.texto
                  : tr("salav2.err.turno", "No pude completar el turno.");
              return h(
                "div",
                { className: "sv-error", role: "alert" },
                texto,
                // QUÉ CEREBRO FALLÓ. Sin esto el usuario no sabe si se quedó sin cuota
                // Codex o Claude Code, y por lo tanto no sabe qué hacer al respecto.
                fallo.cerebro
                  ? h("div", { className: "sv-error-causa" },
                      tr("salav2.err.cerebro", "Falló") + ": " + fallo.cerebro)
                  : null,
                etiquetaReset && resetHintAnterior
                  ? h("div", { className: "sv-error-causa" },
                      etiquetaReset + resetHintAnterior)
                  : null,
                diagnosticoTecnico
                  ? h("details", { className: "sv-error-detalles" },
                      h("summary", null,
                        tr("salav2.err.detalles_tecnicos", "Detalles técnicos")),
                      h("pre", null, String(diagnosticoTecnico)))
                  : null,
                // UN CLICK EN VEZ DE UN TURNO PERDIDO. La copy sale de
                // `_DEFAULT_CAIDO_CAMINOS` (centro_modelos.py:1997), que ya estaba escrita
                // en dos idiomas y sin enchufar. No se cambia el cerebro solo: se OFRECE —
                // sustituir en silencio es lo que en Gate 3 obligó a anunciar
                // `modelo_sustituido`, y esa deuda no se vuelve a contraer.
                fallo.alternativa
                  ? h("button",
                      { className: "sv-error-accion", type: "button",
                        onClick: () => fallo.onUsarAlternativa?.(fallo.alternativa.selection_ref) },
                      tr("salav2.err.usar_otro", "Usar otro conectado") + ": " + fallo.alternativa.label)
                  : null,
                fallo.setupHref
                  ? h("a", { className: "sv-error-accion", href: fallo.setupHref },
                      tr("salav2.err.conectar_modelo", "Conectar un modelo"))
                  : null,
              );
            })()
          : null,
        // Los avisos que NO son error (modelo sustituido, sesión perdida, espinazo caído):
        // se ven, y se ven como aviso, no como rojo. Obra 6 y obra B de Gate 3 sellaron
        // exactamente esto y acá se respeta.
        (avisos || []).map((a, i) => h("div", { key: "av" + i, className: "sv-aviso" }, a)),
        modelIdentity ? h("details", { className: "sv-aviso", "data-testid": "sv-model-identity" },
          h("summary", null,
            (modelIdentity.actual_model_source === "requested-validated"
              ? "Modelo aceptado por CLI: " : "Modelo observado: ") +
            (modelIdentity.actual_model || "desconocido")),
          h("div", null, "Pedido: " + (modelIdentity.requested_provider || "desconocido") +
            " / " + (modelIdentity.requested_model || "automático")),
          h("div", null, "Resuelto: " + (modelIdentity.resolved_provider || "desconocido") +
            " / " + (modelIdentity.resolved_model || "desconocido")),
          modelIdentity.fallback_used ? h("div", null, "Sustitución: " +
            (modelIdentity.fallback_reason || "falló la ruta principal")) : null,
          modelIdentity.override_used ? h("div", null, "Cambio del operador: " +
            (modelIdentity.override_source || "configuración")) : null,
          modelIdentity.override_blocked ? h("div", null,
            "Se ignoró un cambio del operador para conservar tu elección") : null,
        ) : null,
        // La tarjeta de consentimiento vive EN EL HILO, en el punto del turno donde la
        // acción quedó retenida — no en un modal aparte.
        (gates || []).map((g) => h(GateCard, { key: g.sig, gate: g, onDecidido: onGateDecidido })),
        // [Gate 4 · F4 · O6b · 4.3] LA OBRA DEL TURNO, ANUNCIADA DONDE EL USUARIO MIRA.
        // Va acá abajo, al final del hilo, porque es lo último que pasó — y porque
        // entrar en el flujo del hilo es lo que hace que nada se corra de lugar.
        (tarjetas || []).map((o) =>
          h(TarjetaObra, { key: o.id, obra: o, destino: (destinos || {})[o.type],
                           onAbrir: onAbrirObra, onIrAlWorkspace })),
      ),
    ),
    h(EstadoVivo, { maquina, vivo: capacidadViva }),
    h(Composer, { modeloSelector, modoSala, onModo, onEnviarModo, onPrimeraTecla,
                  adjuntos, onAdjuntar, onQuitarAdjunto, puedeVer,
                  obraViva, parando: parandoObra, onParar: onPararObra }),
  );
}
