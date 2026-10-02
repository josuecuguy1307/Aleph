/* model-chip.core.js — EL CHIP DE MODELO. UNO SOLO, PARA LAS SIETE SUPERFICIES.
 *
 * [convergencia · un solo picker en las siete · decisión del dueño 2026-08-22]
 *
 * ═══ POR QUÉ ESTE ARCHIVO EXISTE, Y POR QUÉ NO ES UNA SEGUNDA VERSIÓN ═════════════════
 * El chip compacto del composer nació en la Sala (`sala-v2/ui/model-chip.js`) y funciona.
 * El dueño pidió ESE MISMO widget en las siete superficies. Pero el de la Sala no se puede
 * montar afuera, y no es una opinión — está medido: su única línea de acople es
 * `useAuiState((s) => s.thread.isRunning)`, que **exige el runtime de assistant-ui**. Un
 * workspace es un iframe de otro origen, sin React y sin ese runtime: importar el
 * componente ahí revienta en la primera línea.
 *
 * Así que el componente se MUEVE acá, sin framework, y **la Sala pasa a consumir éste**.
 * `sala-v2/ui/model-chip.js` queda como una cáscara de React de ~30 líneas cuyo único
 * trabajo es traducir `isRunning` a un booleano y montar este núcleo. No hay dos
 * implementaciones: hay una, y dos hosts.
 *
 *   ⚠️ Si alguna vez esto se vuelve a partir en dos, el síntoma va a ser el de siempre:
 *   la Sala y un workspace mostrando el mismo modelo de dos formas distintas. La casa ya
 *   pagó 519 líneas y una llave del dueño por escribir la segunda versión de algo que ya
 *   estaba.
 *
 * ═══ CÓMO LLEGA A UN STACK, Y POR QUÉ VIAJA CON ÉL ════════════════════════════════════
 * Este archivo se COPIA al lado de los assets de cada stack y se carga desde SU PROPIO
 * origen. La primera versión lo servía desde el sidecar, cross-origin, y **Finanzas lo
 * bloqueó**: su respuesta trae `Content-Security-Policy: script-src 'self'`.
 *
 * ⚠️ EL CSP DEL STACK ES SUYO Y NO SE TOCA. Aflojarlo para poder inyectarle nuestra cara
 * sería exactamente lo contrario de la LEY 0: le bajaríamos una defensa real a un workspace
 * que tiene que seguir funcionando igual afuera de Aleph. La cara se adapta al stack, no el
 * stack a la cara. Copiar el archivo cuesta 12 KB por stack y la vara exige que las copias
 * sean idénticas byte a byte, así que sigue habiendo UNA implementación.
 *
 * Va como `<script>` CLÁSICO y no como módulo ESM: publica `window.AlephModelChip` y nada
 * más — el mismo archivo, cargado por `<script>` en los siete documentos.
 *
 * ═══ QUÉ NO HACE ══════════════════════════════════════════════════════════════════════
 * No pide datos, no persiste, no sabe qué es un workspace. Recibe `choices` y devuelve un
 * `selection_ref` por `onSelect`. Quién los trae y quién los guarda es del host — que en
 * los siete casos termina en la MISMA fuente (`preferencias-v2.default`), y eso lo garantiza
 * el backend, no este archivo.
 */

/* ⚠️ SCRIPT CLÁSICO, NO MÓDULO ESM — y es una decisión medida, no un descuido de estilo.
 * Este archivo tiene que cargar en DOS documentos: el de la Sala (mismo origen) y el de un
 * stack (otro origen, servido por su propio pack). Un `import` cross-origin exige cabeceras
 * CORS y el sidecar **no las manda** (medido: `curl -D-` sobre `/ui/model-chip.core.js` con
 * `Origin:` de un pack devuelve 200 sin un solo `access-control-*`). Un `<script src>`
 * clásico no las pide. La alternativa era abrirle CORS al sidecar para servir un archivo de
 * UI: más superficie de backend por un problema de carga. Así que el archivo se publica en
 * `window.AlephModelChip`, que además es el idioma que esta casa ya habla —`AlephBrain`,
 * `AlephModelSelector`, `AlephConectoresDelEspacio` son todos globales. */
const CSS_ID = "aleph-model-chip-core-css";

// Consume the UI locale already resolved by the house or the workspace's own picker.
// No separate preference, selector, or model-language policy is introduced here.
const copy = (es, en) => String(window.AlephI18n?.lang?.() || document.documentElement.lang || "es").startsWith("en") ? en : es;

/* ── las marcas ─────────────────────────────────────────────────────────────────────── */
function normalizarEtiqueta(value) {
  return String(value || "Modelo")
    .replace(/\bgpt[-\s]?(\d+(?:\.\d+)?)\b/gi, (_, v) => `GPT-${v}`)
    .replace(/\bclaude[ _-]?code\b/gi, "Claude Code")
    .replace(/\bclaude\b/gi, "Claude")
    .replace(/\bcodex\b/gi, "Codex")
    .replace(/\bgemini\b/gi, "Gemini");
}

function marcaDe(row) {
  const value = [row?.selection_ref, row?.provider, row?.label].join(" ").toLocaleLowerCase();
  if (value.includes("claude") || value.includes("anthropic")) return { glyph: "✳", name: "Anthropic" };
  if (value.includes("codex")) return { glyph: "⌘", name: "OpenAI Codex" };
  if (value.includes("openai") || value.includes("gpt")) return { glyph: "◎", name: "OpenAI" };
  if (value.includes("gemini") || value.includes("google")) return { glyph: "✦", name: "Google" };
  if (value.includes("mistral")) return { glyph: "M", name: "Mistral" };
  if (value.includes("deepseek")) return { glyph: "D", name: "DeepSeek" };
  if (value.includes("groq")) return { glyph: "G", name: "Groq" };
  if (value.includes("local") || value.includes("ollama")) return { glyph: "⬡", name: "Local" };
  return { glyph: "◆", name: String(row?.provider || "Aleph") };
}

function detalle(row) {
  const partes = [];
  if (row?.provider) partes.push(normalizarEtiqueta(String(row.provider).replaceAll("_", " ")));
  partes.push(row?.context_window ? `${row.context_window} ctx` : copy("ventana no medida", "context window not measured"));
  if (row?.tier) partes.push(row.tier);
  if (row?.cost) {
    const costo = typeof row.cost === "string"
      ? row.cost
      : (row.cost.label || (row.cost.free === true ? copy("gratis", "free") : null));
    partes.push(costo || copy("costo no medido", "cost not measured"));
  } else partes.push(copy("costo no medido", "cost not measured"));
  return partes.join(" · ");
}

function proveedorCorto(row) {
  const marca = marcaDe(row);
  const origen = String(row?.selection_ref || "").includes(":")
    ? String(row.selection_ref).split(":", 1)[0].toUpperCase()
    : (String(row?.selection_ref || "").includes("_cli") ? "CLI" : null);
  return [marca.name, origen].filter(Boolean).join(" · ");
}

/** El motor del cerebro elegido, si NO está listo. `null` = está bien o no se sabe. */
function estadoDelMotor(motores, elegido) {
  if (!motores || !elegido) return null;
  const estados = motores.providers || motores;
  const clave = String(elegido.selection_ref || "");
  const e = estados[clave];
  if (!e || e.state === "ready") return null;
  return { state: e.state, detail: e.detail || null };
}

/** La hoja del chip, inyectada una sola vez por documento.
 *
 * ⚠️ VA POR `<link>` Y NO COPIADA ACÁ. Las reglas viven en `model-chip.core.css`, al lado,
 * porque la Sala ya las tenía en su hoja y duplicarlas en un string de JS sería exactamente
 * la segunda versión que este archivo viene a evitar — pero de los estilos. */
/** El tema de un documento AJENO, por LUMINANCIA de su fondo — no por su hex ni por adivinar
 *  su convención de clases. Es la regla que esta casa ya selló para meter su piel en un
 *  stack: lo que importa es si el fondo es claro u oscuro, no cómo lo escribieron. */
function temaPorLuminancia(el) {
  try {
    var n = el || document.body, bg = "";
    while (n && (!bg || bg === "transparent" || /rgba\(0,\s*0,\s*0,\s*0\)/.test(bg))) {
      bg = getComputedStyle(n).backgroundColor; n = n.parentElement;
    }
    var m = /rgba?\(([^)]+)\)/.exec(bg || "");
    if (!m) return null;
    var p = m[1].split(",").map(function (x) { return parseFloat(x); });
    // Luma perceptual (Rec. 601). 0,5 es el umbral: por encima, fondo claro.
    var l = (0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]) / 255;
    return l > 0.5 ? "light" : "dark";
  } catch (e) { return null; }
}

function instalarCss(href) {
  const doc = document;
  if (doc.getElementById(CSS_ID)) return;
  const link = doc.createElement("link");
  link.id = CSS_ID;
  link.rel = "stylesheet";
  // Un href COMPLETO, que lo arma el host. La Sala no llama a esto —linkea la hoja en su
  // HTML— y un stack la pide de SU PROPIO origen (ver el ⚠️ del CSP abajo).
  link.href = String(href || "/ui/model-chip.core.css");
  doc.head.appendChild(link);
}

/**
 * Monta el chip en `host` y devuelve el mando para actualizarlo.
 *
 * @param {Element} host        dónde vive el chip (el composer del que lo monta)
 * @param {object}  opts
 *   choices          [{selection_ref, label, provider, tier, capabilities, context_window, cost}]
 *   selectedRef      el `selection_ref` elegido
 *   searchThreshold  a partir de cuántas filas aparece el buscador (12, como la Sala)
 *   lockedLabel      si el agente fija el modelo por receta: el chip lo dice y no abre
 *   bloqueado        true mientras corre un turno (la Sala lo saca de `isRunning`)
 *   motores          `/v1/brains/status` para el punto ámbar
 *   tema             "light" | "dark" — lo dice el host; sin esto se sigue la convención
 *                    de la casa, que es la que usa la Sala
 *   onSelect(ref)    lo llama al elegir
 *   onAdd()          lo llama en «＋ Añadir otro modelo»; si falta, va a Conectores
 */
function montarChip(host, opts = {}) {
  let estado = {
    choices: [], selectedRef: null, searchThreshold: 12,
    lockedLabel: null, bloqueado: false, motores: null, tema: null,
    onSelect: null, onAdd: null, ...opts,
  };
  let abierto = false;
  let busqueda = "";

  const raiz = document.createElement("div");
  raiz.className = "sv-model-chip";
  /* ⚠️ EL TEMA NO SE ADIVINA DEL DOCUMENTO AJENO. Cada stack usa su propia convención —la
   * casa marca `[data-theme="light"]`, deeptutor usa la de Tailwind (`html.dark` para
   * oscuro y NADA para claro)— así que ningún selector nuestro puede cubrirlas a todas: en
   * Educación el chip salió oscuro sobre una página clara. El host nos dice cuál es
   * (`opts.tema`) y acá se estampa una marca PROPIA; la hoja lee de esa marca y de nadie
   * más. Sin `tema`, se cae al comportamiento de la casa, que es lo que quiere la Sala. */
  if (opts.tema === "light" || opts.tema === "dark") raiz.dataset.amcTheme = opts.tema;
  host.appendChild(raiz);

  /* El cierre al tocar afuera es del DOCUMENTO, igual que en la Sala (su `useEffect` ponía
   * un `pointerdown` en `document`). Se registra UNA vez y se apaga en `destruir`: un
   * listener por apertura es cómo se llega a veinte oyentes vivos en una sesión larga. */
  function afuera(ev) {
    if (!abierto) return;
    if (!raiz.contains(ev.target)) { abierto = false; busqueda = ""; pintar(); }
  }
  document.addEventListener("pointerdown", afuera);

  function elegido() {
    return (estado.choices || []).find((r) => r.selection_ref === estado.selectedRef) || null;
  }

  function pintar() {
    const el = elegido();
    const marca = marcaDe(el);
    const etiqueta = estado.lockedLabel || normalizarEtiqueta(el?.label || copy("Elegir modelo", "Choose model"));
    const bloqueado = Boolean(estado.lockedLabel) || estado.bloqueado === true;
    const motorFlojo = estadoDelMotor(estado.motores, el);
    const lista = estado.choices || [];
    raiz.textContent = "";

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "sv-model-chip-trigger";
    trigger.disabled = bloqueado || !lista.length;
    trigger.setAttribute("aria-expanded", String(abierto));
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.title = estado.lockedLabel
      ? copy("Este agente conserva el modelo fijado en su receta.", "This agent keeps the model specified in its recipe.")
      : (estado.bloqueado ? copy("El cambio se habilita al terminar este turno.", "You can change the model when this turn finishes.") : copy("Modelo del próximo turno", "Model for the next turn"));
    trigger.onclick = () => { abierto = !abierto; pintar(); };

    const glifo = document.createElement("span");
    glifo.className = "sv-model-brand";
    glifo.setAttribute("aria-hidden", "true");
    glifo.textContent = marca.glyph;
    trigger.appendChild(glifo);

    const rotulo = document.createElement("span");
    rotulo.className = "sv-model-chip-label";
    rotulo.textContent = etiqueta;
    trigger.appendChild(rotulo);

    // El motor no está listo. Un punto, no un cartel: el chip ya dice QUIÉN es, esto agrega
    // CÓMO está, y el aviso del turno ya cubre el DESPUÉS.
    if (motorFlojo) {
      const punto = document.createElement("span");
      punto.className = "sv-model-alerta";
      punto.title = motorFlojo.detail || motorFlojo.state;
      punto.setAttribute("aria-label", motorFlojo.detail || motorFlojo.state);
      punto.textContent = "•";
      trigger.appendChild(punto);
    }

    const caret = document.createElement("span");
    caret.setAttribute("aria-hidden", "true");
    caret.textContent = estado.lockedLabel ? "⌁" : "⌄";
    trigger.appendChild(caret);
    raiz.appendChild(trigger);

    if (!abierto || bloqueado) return;

    const menu = document.createElement("div");
    menu.className = "sv-model-menu";
    menu.setAttribute("role", "listbox");
    menu.setAttribute("aria-label", "Modelos disponibles");

    if (lista.length > (estado.searchThreshold || 12)) {
      const buscador = document.createElement("input");
      buscador.className = "sv-model-search";
      buscador.type = "search";
      buscador.value = busqueda;
      buscador.placeholder = copy("Buscar modelo…", "Search models…");
      buscador.oninput = (ev) => {
        busqueda = ev.target.value;
        pintar();
        const nuevo = raiz.querySelector(".sv-model-search");
        if (nuevo) { nuevo.focus(); nuevo.setSelectionRange(nuevo.value.length, nuevo.value.length); }
      };
      menu.appendChild(buscador);
    }

    const filas = document.createElement("div");
    filas.className = "sv-model-rows";
    const q = busqueda.trim().toLocaleLowerCase();
    const visibles = lista.filter((row) => {
      if (!q) return true;
      return [row.label, row.provider, ...(row.capabilities || [])]
        .some((v) => String(v || "").toLocaleLowerCase().includes(q));
    });

    for (const row of visibles) {
      const m = marcaDe(row);
      const sel = row.selection_ref === estado.selectedRef;
      const b = document.createElement("button");
      b.type = "button";
      b.className = "sv-model-row";
      b.setAttribute("role", "option");
      b.setAttribute("aria-selected", String(sel));
      b.title = [detalle(row), (row.capabilities || []).join(", ")].filter(Boolean).join(" · ");
      b.onclick = () => {
        abierto = false; busqueda = "";
        if (estado.onSelect) estado.onSelect(row.selection_ref);
        pintar();
      };
      const logo = document.createElement("span");
      logo.className = "sv-model-row-logo";
      logo.setAttribute("aria-label", m.name);
      logo.textContent = m.glyph;
      const copy = document.createElement("span");
      copy.className = "sv-model-row-copy";
      const main = document.createElement("span");
      main.className = "sv-model-row-main";
      main.textContent = normalizarEtiqueta(row.label);
      const meta = document.createElement("span");
      meta.className = "sv-model-row-meta";
      meta.textContent = proveedorCorto(row);
      copy.append(main, meta);
      const check = document.createElement("span");
      check.className = "sv-model-row-check";
      check.setAttribute("aria-hidden", "true");
      check.textContent = sel ? "✓" : "";
      b.append(logo, copy, check);
      filas.appendChild(b);
    }

    // ＋ AÑADIR OTRO MODELO · va al VAULT, que es Conectores. El picker es donde se ELIGE;
    // Conectores donde se AÑADE. No hay pantalla nueva.
    const add = document.createElement("button");
    add.type = "button";
    add.className = "sv-model-row sv-model-add";
    add.onclick = () => {
      abierto = false; pintar();
      if (estado.onAdd) { estado.onAdd(); return; }
      const ir = window.AlephBrain?.conectoresHref;
      window.location.href = ir ? ir() : "../Conectores.dc.html";
    };
    const addLogo = document.createElement("span");
    addLogo.className = "sv-model-row-logo";
    addLogo.setAttribute("aria-hidden", "true");
    addLogo.textContent = "＋";
    const addCopy = document.createElement("span");
    addCopy.className = "sv-model-row-copy";
    const addMain = document.createElement("span");
    addMain.className = "sv-model-row-main";
    addMain.textContent = copy("Añadir otro modelo", "Add another model");
    addCopy.appendChild(addMain);
    add.append(addLogo, addCopy);
    filas.appendChild(add);

    menu.appendChild(filas);
    raiz.appendChild(menu);

    /* ⚠️ SI NO HAY LUGAR ARRIBA, ABRE PARA ABAJO. El menú vive `bottom: 100% + 8px`
     * porque en la Sala el composer está al fondo y ésa es la única dirección posible.
     * Adentro de un stack el chip puede quedar ALTO —en Legal el composer está a media
     * pantalla— y ahí el menú se salía por arriba: se veía una tira de dos píxeles. Se mide
     * DESPUÉS de pintarlo, que es cuando ya tiene alto, y se voltea si no entra. */
    const rc = raiz.getBoundingClientRect();
    if (rc.top < menu.offsetHeight + 12) menu.classList.add("sv-model-menu-abajo");
  }

  pintar();

  return {
    /** Parche parcial: sólo lo que llega se pisa. Cerrar el menú al actualizar sería
     *  arrebatárselo al usuario mientras elige, así que `abierto` no se toca acá. */
    actualizar(parciales) { estado = { ...estado, ...(parciales || {}) }; pintar(); },
    cerrar() { if (abierto) { abierto = false; busqueda = ""; pintar(); } },
    estaAbierto() { return abierto; },
    destruir() { document.removeEventListener("pointerdown", afuera); raiz.remove(); },
  };
}

/* LA ÚNICA PUERTA. La Sala lo carga con un `<script>` en su HTML —antes que su bundle, así
 * que está listo cuando el módulo corre— y el stack con otro `<script>` apuntado al origen
 * de la casa. Un archivo, dos documentos, cero copias. */
window.AlephModelChip = { montarChip, instalarCss, normalizarEtiqueta, temaPorLuminancia };
