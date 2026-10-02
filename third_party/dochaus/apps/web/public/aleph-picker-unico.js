// aleph-picker-unico.js — EL CHIP DE MODELO DE ALEPH, EN EL COMPOSER DE ESTE STACK.
//
// [convergencia · un solo picker en las siete · decisión del dueño 2026-08-22]
//
// LA DECISIÓN: el cerebro se elige UNA vez, con UN widget, y ese widget es el chip compacto
// del composer de la Sala. Acá adentro se monta ESE MISMO componente —
// `product/app/design/ui/model-chip.core.js`, servido por la casa— encima del lugar donde
// este stack tenía el suyo. No es uno que se le parece: es el archivo.
//
// POR QUÉ EL DEL STACK NO PUEDE QUEDARSE. Listaba SU catálogo (modelos que no son nuestros)
// y su «Connect more providers» abre un alta de proveedor que guarda la llave ADENTRO del
// stack: fuera del vault y fuera del ledger de gasto. Es la misma violación que la fase 5
// de Ajustes cerró para las puertas de credencial, ahora en el picker.
//
// ⚠️ LEY 0 — ESTE ARCHIVO NO HACE NADA FUERA DE ALEPH. Primera línea del IIFE:
// `window.parent === window` ⇒ return. Corrido suelto —que es como un dev corre este árbol,
// y como lo correría cualquiera que lo use sin Aleph— openwork conserva su picker entero,
// su catálogo y su alta de proveedores, intactos. Aleph aporta; jamás domina.
//
// POR QUÉ NO SE EDITA EL COMPONENTE. Es de upstream. Este archivo es de Aleph y vive al lado
// del suyo —igual que `aleph-credencial-redirige.js` en Legal—, así que un merge de upstream
// no lo pisa ni hay que reaplicar un parche.
//
// ⚠️ ESTE ARCHIVO ES EL MISMO EN TODOS LOS STACKS. Se copia tal cual al lado de los assets
// de cada uno, y la vara exige que las copias sean idénticas byte a byte: un archivo por
// stack sería la misma partición que esta obra vino a cerrar, multiplicada por seis. Lo
// único que cambia entre stacks es la tabla `CASOS` de más abajo — y está acá adentro.
//
// EL CHIP VA EN LOS SIETE, TENGA EL STACK PICKER O NO. Que no haya nada que reemplazar lo
// hace más fácil, no innecesario: se ancla al composer y no se toca una línea suya.
//
// ⚠️ Y NO TOCA EL PICKER DE AGENTE. Medido: `[aria-label*="agent"]` da 0 — el control
// «Default agent» no lleva aria-label, así que esta regla no puede alcanzarlo ni por
// accidente. Elegir el agente es del stack y sigue siéndolo; Aleph se lleva el CEREBRO.
(function () {
  "use strict";

  // ── LEY 0 ───────────────────────────────────────────────────────────────────────────
  if (window.parent === window) return;

  /* ══ DÓNDE VA EL CHIP EN CADA STACK ═══════════════════════════════════════════════
   * UN archivo para los siete: la vara exige que las copias sean idénticas byte a byte, y
   * lo único que cambia entre stacks es ESTA tabla. Un archivo por stack sería la partición
   * que esta obra vino a cerrar, multiplicada por seis.
   *
   * Se toma el PRIMER caso cuyo selector matchee en el documento. Tres modos:
   *
   *   "picker"  el stack TIENE un picker de modelo. Se le bloquean los dos caminos (puntero
   *             y su atajo), se esconde, y el chip ocupa su lugar exacto.
   *   "rotulo"  el stack muestra el modelo pero NO deja elegirlo (un `<span>` sin click). No
   *             hay nada que bloquear: se esconde y el chip ocupa su lugar.
   *   "allado"  el stack no muestra nada de modelo. No se toca NADA suyo: el chip se cuelga
   *             al final del ancla. Que no haya qué reemplazar lo hace más fácil, no
   *             innecesario — el chip tiene que estar en las siete.
   *
   * ⚠️ POR QUÉ NO SE ENGANCHA POR EL COPY. «Cerebro de Aleph» lo escribimos nosotros
   * (`cerebro_label`) y cambia con el idioma; el `aria-label` es semántico y además atrapa
   * el próximo picker que agreguen sin acordarse de esta decisión. Donde el stack no expone
   * un atributo semántico (Finanzas) se usa su ESTRUCTURA, que es lo siguiente más estable —
   * y la vara exige que ese selector matchee EXACTAMENTE UNA VEZ en su dist, así que si
   * upstream la cambia, se entera la vara y no el usuario.
   */
  var CASOS = [
    // Oficina · openwork — medido: 1 en el documento, y su `aria-keyshortcuts` es el único.
    { sel: '[aria-label="Change model"]', modo: "picker" },
    // Educación · deeptutor — medido: 1 en el documento. No declara atajo.
    { sel: '[aria-label="Select model"]', modo: "picker" },
    /* Finanzas · vibetrading — SU CHIP DEL COMPOSER, Y VA PRIMERO.
     *
     * 🔧 [integración] EL ANCLA DE ABAJO NO ALCANZABA, Y SE VIO EN PANTALLA. Apuntaba al
     * rótulo de `ModelRuntimeBar`, que es una barra APARTE del composer — y en la pantalla
     * de bienvenida esa barra NO SE RENDERIZA (no hay punto verde ni cápsula de «Reasoning
     * strength»). Sin ancla, el chip se esconde (y hace bien: un componente anclado a algo
     * que no está tiene que desaparecer con ello). Lo que quedaba a la vista era el chip
     * PROPIO de Finanzas, `.aleph-chip-modelo`, que es un `<span>` MUERTO: muestra
     * `visibleRuntimeIdentity.model` —el rótulo del CEREBRO, «Cerebro de Aleph», no el
     * modelo— y lleva una flechita que promete un menú que no existe. Los otros tres
     * mostraban `✳ Claude Code ⌄`, que es el picker de verdad. Un control que dibuja una
     * flecha y no abre nada es peor que no estar: miente.
     *
     * Se ancla acá y NO se borra el de abajo: `resolverCaso()` toma el PRIMERO que exista,
     * así que cuando el composer está en pantalla gana éste, y cuando no, cae al rótulo de
     * la barra como hasta ahora. Dos anclas para el mismo stack no es duplicar: es que el
     * stack muestra el modelo en dos lugares según la pantalla, y el chip tiene que estar
     * en la que se ve. */
    { sel: ".aleph-chip-modelo", modo: "rotulo" },
    // Finanzas · vibetrading — `ModelRuntimeBar.tsx:45`: un `<span title={model}>` que MUESTRA
    // el modelo y no deja elegirlo. No expone atributo semántico; se ancla por estructura.
    // Queda como RESPALDO, para la pantalla donde esa barra sí está.
    { sel: ".shrink-0.border-b span.truncate.font-medium.text-foreground[title]", modo: "rotulo" },
    // Ciencia · openscience — `model-settings-popover.tsx:300`: SU picker, el de «QUICK
    // MODELS» con catálogo propio. Se engancha por `data-model-settings-trigger-style`,
    // que es un atributo SUYO y estructural; su `aria-label` es `Model: <lo que sea>`, o
    // sea copy, y por eso no se usa.
    { sel: "[data-model-settings-trigger-style]", modo: "picker" },
    // Diseño · codesign — `Sidebar.tsx:250`: un `<span>` que muestra el cerebro y no deja
    // elegirlo. Es el ÚNICO stack donde el enganche es un atributo NUESTRO
    // (`data-aleph-modelo`): su árbol es un fork que esta casa ya mantiene, y engancharlo
    // por sus clases de Tailwind se rompería con cualquier retoque de estilo.
    { sel: '[data-aleph-modelo="rotulo"]', modo: "rotulo" },
    // Legal · dochaus — `ChatPanel.tsx:993`: la fila de herramientas del composer. Su
    // `ModelSelector` elige AGENTE, no modelo, así que NO SE TOCA: el chip va al lado.
    { sel: ".composer-tools", modo: "allado" },
  ];

  var caso = null, ancla = null;

  /** El primer caso que exista en este documento. Se re-evalúa: los composers se montan
   *  tarde y el ancla puede aparecer después que este script. */
  function resolverCaso() {
    for (var i = 0; i < CASOS.length; i++) {
      var n = document.querySelector(CASOS[i].sel);
      if (n) { caso = CASOS[i]; ancla = n; return true; }
    }
    ancla = null;
    return false;
  }

  /* Sólo los "picker" se bloquean: es donde hay un menú ajeno que no debe abrirse. Un
   * `<span>` sin click no necesita bloqueo, y una fila de herramientas ajena MENOS todavía —
   * bloquearla le rompería al stack sus propios controles. */
  var SEL_BLOQUEO = CASOS.filter(function (c) { return c.modo === "picker"; })
                         .map(function (c) { return c.sel; }).join(",");
  /* El atajo de teclado que un control declara en su `aria-keyshortcuts`. Sólo openwork tiene
   * uno (`Meta+Alt+/`, medido: el único de su documento); los demás no declaran ninguno.
   * Bloquearlo igual no cuesta nada y cubre al que lo agregue mañana. */
  var ATAJO = { key: "/", meta: true, alt: true };

  /* ── DE DÓNDE SE BAJA EL COMPONENTE: DE ESTE MISMO ORIGEN ────────────────────────────
   * ⚠️ Y NO DEL SIDECAR, QUE ES LO QUE SE INTENTÓ PRIMERO. Finanzas responde con
   * `Content-Security-Policy: script-src 'self'` y bloqueó el `<script>` apuntado a la casa
   * («violates the following Content Security Policy directive», medido en consola). Su CSP
   * es SUYO: aflojarlo para poder meterle nuestra cara sería bajarle una defensa real a un
   * workspace que tiene que seguir funcionando igual afuera de Aleph — lo contrario de la
   * LEY 0. Así que el núcleo y su hoja viajan al lado de este archivo, en cada stack, y se
   * cargan de su propio origen. Cuesta 12 KB por stack y la vara exige que las copias sean
   * idénticas byte a byte.
   *
   * Ya no hace falta resolver el origen de la casa para CARGAR nada. */
  /* ── ¿ESTAMOS ADENTRO DE ALEPH? LA GUARDA ES QUE LA CASA NOS CONTESTE ───────────────
   * La versión anterior exigía que `document.referrer` fuera loopback. **Falla en Diseño**:
   * su lienzo lo sirve un Electron propio y el iframe llega SIN referrer, así que el script
   * se iba en esa línea y no hacía absolutamente nada — un no-op silencioso, que es la peor
   * forma de fallar. Y la guarda tampoco era la correcta: probaba de dónde venía la página,
   * no si Aleph está del otro lado.
   *
   * La guarda buena es más fuerte y no depende de ningún dato del navegador: **no se toca
   * NADA de este stack hasta que la casa nos mandó su catálogo**. Si esto corre suelto, o
   * embebido en una página que no es Aleph, nadie contesta el saludo: el control del stack
   * no se esconde, el chip no se monta, y el workspace queda exactamente como estaba.
   * LEY 0 por construcción, no por adivinar el origen. */
  var catalogoOk = false;

  var NUCLEO_JS  = "/aleph-model-chip.core.js";
  var NUCLEO_CSS = "/aleph-model-chip.core.css";

  var chip = null;         // el mando que devuelve `montarChip`
  var contenedor = null;   // nuestro host, colgado del <body>
  var ultimo = { choices: [], selectedRef: null };
  var pintado = null;      //: firma de lo último pintado, para no repintar de gusto
  var reloj = null;

  function firma() {
    // Repaint when the existing UI locale resolves or changes; no new language store.
    return String(window.AlephI18n?.lang?.() || document.documentElement.lang || "es") + "|" + ultimo.selectedRef + "|" +
           ultimo.choices.map(function (c) { return c.selection_ref; }).join(",");
  }

  /** El tema para el chip. Primero LO QUE LA CASA DIJO —`?aleph_scheme=`, la palabra única
   *  con la que el tema ya cruza el borde en esta casa— y si no está (una navegación del
   *  stack se puede llevar la query), por LUMINANCIA de su fondo. Nunca adivinando su
   *  convención de clases: deeptutor usa `html.dark` de Tailwind, openwork `data-theme`, y
   *  el próximo usará otra. */
  function temaDelStack() {
    try {
      var q = new URLSearchParams(location.search).get("aleph_scheme");
      if (q === "light" || q === "dark") return q;
    } catch (e) {}
    var f = window.AlephModelChip && window.AlephModelChip.temaPorLuminancia;
    return f ? f(document.body) : null;
  }

  /* ⚠️ SE VUELVE A PEDIR HASTA QUE LLEGUE, y no es paranoia: es una carrera que no
   * controlamos. El saludo depende de si este script enganchó antes o después de que la
   * anfitriona tuviera su catálogo listo, y eso cambia con el stack, con el disco y con si
   * el pack estaba caliente. Medido en Finanzas: el chip quedó en «Elegir modelo» —montado,
   * vivo y sin una sola opción— hasta que se forzó la bajada a mano. Un saludo que se manda
   * UNA vez y se pierde en silencio es la peor forma de fallar. */
  var ultimoPedido = 0;
  function pedirCatalogo() {
    ultimoPedido = Date.now();
    try { window.parent.postMessage({ aleph: "modelo?" }, "*"); } catch (e) {}
  }
  function reintentarSiVacio() {
    if (ultimo.choices.length) return;
    if (Date.now() - ultimoPedido < 2000) return;
    pedirCatalogo();
  }

  /* ── POR QUÉ NUESTRO CHIP NO VIVE ADENTRO DEL ÁRBOL DEL STACK ────────────────────────
   * Primero se insertó como hermano del control del stack, adentro de su composer. NO
   * FUNCIONA, y el modo de fallo fue feo: React no MUTA ese contenedor, lo REEMPLAZA entero
   * en cada re-render. Nuestro `<span>` se iba con él; al reponerlo React volvía a
   * reemplazar, y el stack se quedó en los esqueletos de carga sin terminar de pintar nunca.
   * Pelearse con la reconciliación de React es una pelea que se pierde siempre.
   *
   * LA FORMA QUE SÍ: el chip cuelga de `document.body`, FUERA del árbol que React maneja
   * —no lo va a tocar— y se posiciona ENCIMA del hueco que el control del stack ocupa.
   *
   * Y por eso el control se apaga con `visibility: hidden` y no con `display: none`:
   * `hidden` **conserva la caja**, así que sigue reservando su lugar en el composer y nos da
   * el `getBoundingClientRect()` donde pararnos. Con `display:none` el layout se corría y no
   * había rect al que anclarse. `pointer-events:none` y `tabindex=-1` lo sacan del mouse y
   * del teclado; el bloqueo en CAPTURA de más abajo es el que protege de verdad. */
  /* Apaga lo del stack SÓLO cuando hay algo que reemplazar. En modo "allado" no se le toca
   * ni un atributo: el ancla es de ellos y sigue siéndolo. */
  function apagarElDelStack() {
    if (!ancla || caso.modo === "allado") return ancla;
    if (rendido) return ancla;   // ver el limitador: dejamos de pelear por el `style`
    if (ancla.style.visibility !== "hidden") {
      ancla.style.visibility = "hidden";
      ancla.style.pointerEvents = "none";
      ancla.setAttribute("tabindex", "-1");
      ancla.setAttribute("aria-hidden", "true");
      /* El hueco se mide con el borde adentro: si el control del stack tiene padding o
       * borde, sin esto la reserva de `reservarElHueco()` quedaría corta por esos px. */
      ancla.style.boxSizing = "border-box";
      /* 🔧 Y TIENE QUE PODER TOMAR UN ANCHO. En Diseño el ancla es un `<span>` pelado
       * (`Sidebar.tsx:152`), o sea `display:inline` — y en un elemento inline el `width` que
       * `reservarElHueco()` le pone SE IGNORA. Resultado: el hueco no se reservaba nunca, el
       * chip no empujaba a enviar y se le montaba encima. Se vio en pantalla y no lo habría
       * visto ningún grep: la línea que reserva existía y corría, sólo que sobre un elemento
       * que no la obedece.
       * `inline-block` es el cambio mínimo que hace aplicable el ancho sin sacarlo del
       * renglón; donde el ancla ya era un bloque o un flex item, no cambia nada. */
      if (getComputedStyle(ancla).display === "inline") ancla.style.display = "inline-block";
    }
    return ancla;
  }

  /* ── EL HUECO TIENE QUE SER DEL TAMAÑO DEL CHIP, NO DEL CONTROL QUE TAPA ──────────────
   * ⚠️ ESTO ES LO QUE DEJABA A EDUCACIÓN SIN PODER MANDAR UN TURNO, y estaba medido:
   *
   *     Select model   x=132  w=32   (el ancla)
   *     Record voice   x=170  w=32
   *     Send           x=212  w=32   ← el chip le caía ENCIMA
   *
   * `visibility:hidden` conserva la caja, pero conserva LA DE ELLOS: 32 px. El chip dice
   * «Claude Code ⌄» y mide ~4× eso, así que al pararlo en `r.left` se derramaba sobre los
   * dos botones siguientes. El click en el ↑ abría NUESTRO menú en vez de mandar, `Enter`
   * tampoco manda en ese composer, y la superficie quedaba inusable con el puntero.
   * No se arreglaba ensanchando la ventana: probado a 800 y a 1600 px, el derrame es
   * relativo al ancla, no al viewport.
   *
   * LA FORMA: al hueco escondido se le da EL ANCHO DEL CHIP. Como el control sigue en el
   * flujo (por eso `hidden` y no `display:none`), el flex del stack se reacomoda solo y
   * los botones que vienen después se corren a la derecha. El chip deja de pisar a nadie
   * sin que haya que tocar el árbol de React — que es la restricción que manda acá.
   *
   * SÓLO CRECE, NUNCA ACHICA. Si el chip fuera más angosto que el control, encogerle la
   * caja al stack podría romperle un layout que no es nuestro. Reservar de más es
   * invisible; reservar de menos es este bug.
   *
   * Se escribe con el mismo criterio que `left`/`top`: sólo cuando cambió. Y va en el
   * mismo `style` inline que ya defiende el limitador, así que si React lo repone se
   * repone junto con `visibility` y no hace falta otra pulseada. */
  function reservarElHueco() {
    if (!ancla || !contenedor || caso.modo === "allado" || rendido) return;
    if (ancla.style.visibility !== "hidden") return;   // todavía no lo escondimos
    var chip = contenedor.offsetWidth;
    if (!chip) return;                                  // aún sin pintar: no se adivina
    var propio = ancla.getAttribute("data-aleph-w0");
    if (propio === null) {
      // el ancho NATURAL del control, medido UNA vez y guardado: después de reservar, su
      // `offsetWidth` ya es el nuestro y volver a leerlo sería medirnos a nosotros mismos.
      propio = String(ancla.offsetWidth || 0);
      ancla.setAttribute("data-aleph-w0", propio);
    }
    var w = Math.max(parseInt(propio, 10) || 0, chip);
    var px = w + "px";
    if (ancla.style.width !== px) ancla.style.width = px;
  }

  function asegurarContenedor() {
    if (contenedor && contenedor.isConnected) return contenedor;
    contenedor = document.createElement("span");
    contenedor.className = "sv-model-chip-host";
    contenedor.setAttribute("data-aleph-chip", "1");
    // Acá el host ES el posicionado, así que necesita ser una caja (en la Sala, en cambio,
    // es `display:contents` para no alterar el flex de su composer).
    contenedor.style.cssText = "position:fixed;z-index:2147483000;display:block";
    document.body.appendChild(contenedor);
    return contenedor;
  }

  /** Pega el chip al hueco del control del stack. Barato: lee un rect y escribe dos números,
   *  y sólo cuando cambiaron. */
  function ubicar() {
    if (!contenedor || !contenedor.isConnected) return;
    reservarElHueco();
    var b = ancla && ancla.isConnected ? ancla : null;
    /* ⚠️ SIN ANCLA, EL CHIP SE ESCONDE. Visto en pantalla: el stack entra en su estado de
     * carga (esqueletos) y su control de modelo desaparece del DOM; como el nuestro cuelga
     * del `<body>` y no de su árbol, se quedaba flotando en el medio de la pantalla sobre
     * los esqueletos. Un componente anclado a algo que no está tiene que desaparecer con
     * ello — no quedarse afirmando un lugar que ya no existe. */
    if (!b) { contenedor.style.display = "none"; return; }
    var r = b.getBoundingClientRect();
    if (!r.width && !r.height) { contenedor.style.display = "none"; return; }
    contenedor.style.display = "block";
    /* "picker"/"rotulo": el chip OCUPA el lugar de lo que escondimos. "allado": va pegado al
     * final del ancla, que sigue viva y visible — y si no hay lugar a la derecha, adentro
     * por la derecha, que es mejor que salirse de la pantalla. */
    var izq = r.left, arr = r.top;
    /* 🔧 CENTRADO VERTICAL SIEMPRE, NO SÓLO EN «al lado».
     * Antes el chip se alineaba por ARRIBA con el ancla, y eso sólo se ve bien cuando los dos
     * miden parecido. En Diseño el ancla es un `<span>` de 10,5px (`Sidebar.tsx:152`) y el chip
     * es la cápsula del estándar, de ~30: top-aligned, colgaba por debajo del renglón y se veía
     * enorme y fuera de lugar. El lugar estaba bien —el artboard lo pone adentro de la barrita,
     * pegado a enviar—; lo que estaba mal era el eje.
     * Donde ancla y chip miden parecido (Oficina, Finanzas) esto da ~0 y no mueve nada: la
     * corrección se nota justo donde hacía falta. */
    arr = r.top + (r.height - (contenedor.offsetHeight || 28)) / 2;
    if (caso && caso.modo === "allado") {
      /* ⚠️ ADENTRO DEL EXTREMO LIBRE DE LA FILA, no pegado por fuera. Medido en Legal: su
       * `.composer-tools` es un flex de ANCHO COMPLETO con sus controles alineados a la
       * izquierda, así que `r.right + 8` caía fuera de la pantalla y el chip no se veía. El
       * lado derecho de esa fila es espacio vacío del propio composer: ahí entra, alineado
       * con sus controles, y parece parte de la fila en vez de un pegote. */
      var ancho = contenedor.offsetWidth || 120;
      izq = Math.max(r.left, r.right - ancho - 8);
      // el alto ya lo centró la línea de arriba, que ahora vale para los tres modos
    }
    var x = Math.round(izq) + "px", y = Math.round(arr) + "px";
    if (contenedor.style.left !== x) contenedor.style.left = x;
    if (contenedor.style.top !== y) contenedor.style.top = y;
  }

  /* ⚠️ EL OBSERVER NO PUEDE LLAMAR A `pintar()` A SECAS, Y ESTO COLGÓ EL RENDERER.
   * Medido: `pintar()` toca el DOM, cada cambio despierta al observer, que vuelve a pintar
   * — bucle infinito, pestaña congelada, ni un error en consola. El síntoma fue que la
   * pantalla dejó de responder, no una excepción.
   *
   * La regla: el observer sólo REPARA. Mira si falta algo y recién ahí pinta. Y mientras
   * `pintar()` corre, queda mudo. */
  var pintando = false;

  function faltaAlgo() {
    if (!contenedor || !contenedor.isConnected) return true;  // alguien nos sacó del body
    if (!ancla || !ancla.isConnected) return true;            // el composer se remontó
    if (rendido || caso.modo === "allado") return false;
    if (ancla.style.visibility !== "hidden") return true;     // React repuso su control
    return false;
  }

  /* ⚠️ EL LIMITADOR, Y SIN ÉL SE CUELGA LA PESTAÑA. Medido dos veces, en dos stacks.
   *
   * El `pintando` de arriba corta el bucle DENTRO de un tick, pero no el otro bucle: React
   * vuelve a renderizar el control y le RESETEA el `style` que le pusimos; el observer ve la
   * mutación, `faltaAlgo()` dice que sí, reparamos, React repone, y así para siempre. En
   * Educación eso dejó el renderer sin responder — otra vez sin una sola excepción.
   *
   * Dos frenos. Uno de ritmo: como mucho una reparación cada `MIN_MS`. Y uno de fondo: si en
   * `VENTANA_MS` hubo más de `TOPE` reparaciones, es que el stack nos está ganando la pulseada
   * y **se deja de esconder su control**. Degradar es feo —quedan los dos pickers a la vista—
   * pero es MUCHÍSIMO mejor que una pestaña muerta, y el nuestro sigue siendo el que funciona.
   * El bloqueo en captura no se afloja: el suyo se ve pero no abre. */
  var MIN_MS = 200, VENTANA_MS = 4000, TOPE = 25;
  var ultimaRep = 0, reparaciones = [], rendido = false;

  function pintar() {
    if (pintando) return;
    var ahora = Date.now();
    if (ahora - ultimaRep < MIN_MS) return;
    ultimaRep = ahora;
    reparaciones.push(ahora);
    while (reparaciones.length && ahora - reparaciones[0] > VENTANA_MS) reparaciones.shift();
    if (reparaciones.length > TOPE && !rendido) {
      rendido = true;
      // Al rendirse se saca el tapón: el control del stack tiene que volver a verse, porque
      // el camino de rendición no lo muestra —sólo deja de esconderlo— y sin esto el
      // workspace quedaría sin ningún picker. Ver el bloque del tapón.
      destaparElDelStack();
    }
    pintando = true;
    try { _pintar(); } finally {
      // Se libera en el próximo tick: las mutaciones que acabamos de hacer le llegan al
      // observer de forma asíncrona, así que soltar la traba en el mismo turno la deja
      // inútil.
      setTimeout(function () { pintando = false; }, 0);
    }
  }

  function _pintar() {
    // Ver la guarda de arriba: sin catálogo no se toca un solo nodo del stack.
    if (!catalogoOk) return;
    if (!ancla || !ancla.isConnected) {
      var selAntes = caso && caso.sel;
      resolverCaso();
      // El ancla puede cambiar de caso (Finanzas tiene dos, según la pantalla). El tapón
      // apunta a UN selector, así que si el caso cambió hay que rehacerlo o taparíamos el
      // control equivocado.
      if (!caso || caso.sel !== selAntes) { destaparElDelStack(); taparElDelStack(); }
    }
    if (!ancla) { if (contenedor) contenedor.style.display = "none"; return; }
    apagarElDelStack();
    var host = asegurarContenedor();
    if (!host || !window.AlephModelChip) return;
    if (!chip) {
      chip = window.AlephModelChip.montarChip(host, {
        choices: ultimo.choices,
        selectedRef: ultimo.selectedRef,
        tema: temaDelStack(),
        // El «＋ Añadir otro modelo» navega a Conectores por su cuenta, y desde adentro de un
        // iframe eso dejaría a Conectores metido en el lienzo del stack. Acá se le da su
        // propia salida: se lo pide a la casa, que ya sabe abrirlo en su lugar.
        onAdd: function () {
          try { window.parent.postMessage({ aleph: "conectores" }, "*"); } catch (e) {}
        },
        onSelect: function (ref) {
          // OPTIMISTA A PROPÓSITO: el chip marca lo elegido en el acto y la casa confirma
          // con el catálogo de vuelta. Esperar el ida y vuelta dejaría el chip diciendo el
          // modelo viejo por medio segundo, que es la pantalla mintiendo.
          ultimo.selectedRef = ref;
          pintado = firma();
          chip.actualizar({ selectedRef: ref });
          try { window.parent.postMessage({ aleph: "modelo-elegir", ref: ref }, "*"); } catch (e) {}
        },
      });
    } else if (pintado !== firma()) {
      // Sólo cuando el DATO cambió. Repintar en cada reparación del DOM es otra forma del
      // mismo bucle, y además le cerraría el menú al usuario mientras elige.
      chip.actualizar({ choices: ultimo.choices, selectedRef: ultimo.selectedRef });
    }
    pintado = firma();
    ubicar();
  }

  // ── LA PROTECCIÓN: el control del stack no abre su menú por ningún camino ─────────────
  ["pointerdown", "mousedown", "click", "keydown"].forEach(function (tipo) {
    document.addEventListener(tipo, function (ev) {
      if (tipo === "keydown") {
        // El atajo que el propio control declara. Sin esto su picker sigue alcanzable con el
        // teclado y el bloqueo sería sólo para el mouse.
        if (!(ev.metaKey === ATAJO.meta && ev.altKey === ATAJO.alt && ev.key === ATAJO.key)) return;
      } else {
        var t = ev.target;
        if (!SEL_BLOQUEO || !t || !t.closest || !t.closest(SEL_BLOQUEO)) return;
      }
      ev.preventDefault();
      ev.stopPropagation();
      // `stopImmediatePropagation` además: base-ui engancha SU handler en el mismo nodo, y
      // sin esto corre igual aunque el evento no siga subiendo.
      if (ev.stopImmediatePropagation) ev.stopImmediatePropagation();
    }, true);   // ← CAPTURA: corre antes que cualquier handler de React / base-ui
  });

  // ── LO QUE BAJA DE LA CASA ───────────────────────────────────────────────────────────
  // Mismo candado que la casa aplica a lo que sube: sólo de `window.parent`. Y lo único que
  // puede traer son FILAS DE VITRINA para pintar — sin proveedor ejecutable, sin URL, sin
  // secretos. Nada de esto ejecuta nada.
  window.addEventListener("message", function (ev) {
    if (ev.source !== window.parent) return;
    var d = ev.data;
    if (!d || d.aleph !== "modelo-catalogo") return;
    ultimo = {
      choices: Array.isArray(d.choices) ? d.choices : [],
      selectedRef: d.selectedRef == null ? null : String(d.selectedRef),
    };
    catalogoOk = true;
    pintar();
  });

  /* ⚠️ EL LATIDO ES EL QUE REPARA — el observer sólo lo ADELANTA.
   *
   * La versión anterior colgaba toda la reparación del `MutationObserver`, y en Legal eso
   * no alcanzó: medido, `_pintar` corrió TRES veces en veinte segundos de una app React
   * viva, y el composer que aparece al abrir un asunto nunca disparó una reparación. No
   * importa por qué su árbol no produce las mutaciones que esperábamos: colgar la única
   * garantía de una señal que depende de cómo el stack ajeno construye su DOM es apostar a
   * algo que no controlamos.
   *
   * Así que el que garantiza es un latido propio de 250 ms —el mismo que ya reubicaba el
   * chip— y el observer queda como atajo para que se vea en el acto en vez de en el próximo
   * tick. El limitador de más arriba es el que hace que esto no cueste nada: si no falta
   * nada, `faltaAlgo()` es un `querySelector` y dos comparaciones. */
  function latido() {
    /* 🔧 EL TAPÓN SE REINTENTA, PORQUE UNA SOLA VEZ AL ARRANCAR NO ALCANZA.
     * Medido en pantalla: en Ciencia, a los 2 s, se veía SU picker con «Cerebro de Aleph» y
     * recién después aparecía el nuestro. La causa no era el tapón sino CUÁNDO se ponía: se
     * inyectaba una vez en `arrancar()`, y estos stacks montan el composer DESPUÉS de que este
     * script corre —Solid y Electron, no React del primer pintado—. Sin ancla, `taparElDelStack()`
     * devolvía temprano y no se volvía a intentar nunca; el control del stack aparecía después,
     * a la vista, hasta que llegaba el catálogo. Un arreglo que depende de llegar primero no es
     * un arreglo: es una carrera que a veces se gana.
     *
     * Acá se reintenta hasta colocarlo, y cuesta un `querySelector` sólo mientras falte —el
     * mismo precio que `faltaAlgo()`, que ya corre en cada latido—. Y NO depende de
     * `catalogoOk`: el tapón es una hoja inerte fuera de Aleph (ver su bloque), así que puede
     * ponerse antes de que la casa conteste sin tocar la guarda. */
    if (!tapon) {
      if (!ancla || !ancla.isConnected) resolverCaso();
      taparElDelStack();
    }
    if (faltaAlgo() || (catalogoOk && pintado !== firma())) pintar();
    ubicar();
    reintentarSiVacio();
  }
  var obs = new MutationObserver(latido);

  /* ── EL TAPÓN · POR QUÉ EL CONTROL DEL STACK NACE ESCONDIDO ────────────────────────
   * Medido en pantalla capturando la carga de Finanzas cuadro a cuadro: al segundo 1 el chip
   * decía «✳ Cerebro de Aleph ⌄» y al segundo 2 «✳ Claude Code ⌄», y encima se CORRÍA unos px
   * porque el texto viejo era más largo y `reservarElHueco()` reajustaba. Eso es lo que se ve
   * como que algo se solapa y desaparece. Le pasa a los SEIS: cada stack pinta su propio
   * control hasta que el nuestro lo tapa.
   *
   * La causa no es un descuido: la guarda de más arriba —no tocar un solo nodo del stack hasta
   * que la casa contestó con su catálogo— es LEY 0 por construcción y NO se afloja. Lo que se
   * agrega es una hoja nuestra que no necesita esa respuesta para ser SEGURA:
   *
   *   :root[data-aleph-piel="v2"] <su selector> { visibility: hidden }
   *
   * `data-aleph-piel="v2"` lo pone el frame, que a su vez ya se gatea por `window.parent !==
   * window` y por el parámetro de la casa. Fuera de Aleph ese atributo NO EXISTE y la regla no
   * matchea nada: la LEY 0 se cumple sin pedirle permiso al catálogo.
   *
   * ⚠️ EL SELECTOR SALE DE `CASOS`, NO SE ESCRIBE DE NUEVO. Meter los seis en un CSS sería la
   * partición que esa tabla vino a cerrar. Y es el del caso RESUELTO, uno solo: Finanzas tiene
   * dos anclas y tapar las dos le dejaría un hueco en la barra de runtime.
   *
   * ⚠️ NUNCA EN MODO «al lado». Ahí el ancla es de ellos y sigue viva: en Legal es su fila de
   * herramientas entera.
   *
   * ⚠️ Y SE DESTAPA, QUE ES LA MITAD DEL ARREGLO. Si el stack nos gana la pulseada el script
   * se RINDE —deja de esconder, y quien repone es React—; una hoja sin escape lo seguiría
   * tapando y el workspace quedaría SIN NINGÚN picker. Lo mismo si el catálogo no llega nunca.
   * Una degradación que rompe más que el problema no es una degradación. */
  var tapon = null;

  function taparElDelStack() {
    if (tapon || !caso || !ancla || caso.modo === "allado") return;
    try {
      tapon = document.createElement("style");
      tapon.setAttribute("data-aleph-tapon", "1");
      tapon.textContent = ':root[data-aleph-piel="v2"] ' + caso.sel + " { visibility: hidden; }";
      document.head.appendChild(tapon);
    } catch (e) { tapon = null; }
  }

  function destaparElDelStack() {
    if (!tapon) return;
    try { tapon.remove(); } catch (e) {}
    tapon = null;
  }

  /* Si el catálogo no llegó, el control del stack vuelve. Es el mismo criterio que la
   * rendición: preferimos el picker de ellos —que al menos abre— antes que un hueco mudo. */
  var ESPERA_CATALOGO_MS = 6000;

  function arrancar() {
    resolverCaso();
    taparElDelStack();
    setTimeout(function () { if (!catalogoOk) destaparElDelStack(); }, ESPERA_CATALOGO_MS);
    window.AlephModelChip.instalarCss(NUCLEO_CSS);
    obs.observe(document.documentElement, { childList: true, subtree: true });
    pintar();
    /* El composer se mueve por razones que NO son mutaciones del DOM: el textarea crece, la
     * ventana cambia, el panel lateral se abre. Un rAF continuo sería un incendio de CPU; un
     * intervalo corto alcanza. 250 ms: el ojo no ve el salto y son cuatro lecturas de rect
     * por segundo. */
    if (!reloj) reloj = setInterval(latido, 250);
    window.addEventListener("resize", ubicar);
    window.addEventListener("scroll", ubicar, true);
    pedirCatalogo();
  }

  // El núcleo primero; sin él no hay chip que montar. FALLO VISIBLE, JAMÁS MUDO: si no
  // carga, no se apaga nada — el usuario conserva el picker del stack en vez de quedarse
  // sin ninguno.
  var s = document.createElement("script");
  s.src = NUCLEO_JS;
  s.onload = arrancar;
  s.onerror = function () {};
  document.head.appendChild(s);
})();
