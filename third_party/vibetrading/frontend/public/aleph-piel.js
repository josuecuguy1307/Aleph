// aleph-piel.js — EL INTERRUPTOR DE LA PIEL DE ALEPH EN ESTE STACK.
// [rediseño · fase 1 · cable de seguridad (b)]
//
// QUÉ RESUELVE. El rediseño le va a cambiar la piel a seis stacks ajenos. Cada uno de esos
// cambios viaja adentro de un `dist` que hay que hornear, así que **volver atrás costaría
// un build por stack** — y un build de esta casa no es barato (el árbol de Legal solo pesa
// 1,6 GB adentro de la `.app`). Este archivo separa las dos cosas que estaban pegadas:
//
//     la hoja de piel VIAJA siempre  ·  la hoja de piel se APLICA sólo con el flag
//
// Apagar el rediseño entero pasa a ser cambiar una palabra en la casa, sin recompilar nada.
//
// ⚠️ LEY 0 — ESTE ARCHIVO NO HACE NADA FUERA DE ALEPH. Primera línea del IIFE:
// `window.parent === window` ⇒ return. Corrido suelto —que es como un dev corre este árbol,
// y como lo correría cualquiera que lo use sin Aleph— el stack queda exactamente como su
// upstream lo dejó. Mismo contrato que `aleph-picker-unico.js`, que ya vive al lado.
//
// ⚠️ ESTE ARCHIVO ES EL MISMO EN TODOS LOS STACKS, byte a byte, y la vara lo exige. Un
// archivo por stack sería seis lugares donde arreglar el mismo bug. Lo que cambia entre
// stacks es la HOJA (`aleph-piel.css`), no el interruptor.
//
// POR QUÉ VIVE EN `public/` Y NO ADENTRO DE `src/`. Porque `public/` se sirve tal cual y no
// obliga a tocar un componente de upstream: la única cirugía es UNA línea en su `index.html`.
// Es la misma costura que la casa ya usa y que la Ley 6 de `third_party/README.md` permite.
// ⚠️ Y es justo la carpeta que el build NO vigilaba en tres de los seis stacks: eso se
// cerró en el commit anterior a éste (`esta_fresco` + `public`). Sin ese arreglo, este
// archivo podría quedar viejo adentro del `dist` para siempre.
//
// EN LA FASE 1 LA HOJA ESTÁ VACÍA A PROPÓSITO. `aleph-piel.css` no trae un solo estilo:
// trae un TESTIGO (`--aleph-piel: v2`) para que la vara pueda probar los dos brazos del
// interruptor sin que la cara de ningún stack cambie todavía. La piel de verdad la escribe
// la fase 3, un stack por vez.
(function () {
  "use strict";

  // ── LEY 0 ───────────────────────────────────────────────────────────────────────────
  if (window.parent === window) return;
  try { window.__alephPielCorrio = true; } catch (e) {}

  // La casa manda la versión en la URL del `<iframe>`, al lado de `aleph_ws`,
  // `aleph_label`, `aleph_scheme` y `aleph_chat`. Sin parámetro no hay piel: el default es
  // el stack como está hoy, que es lo único seguro.
  /* ══ LOS PARÁMETROS SOBREVIVEN A UN REDIRECT ═════════════════════════════════════════
   * La casa los manda en la URL del `<iframe>`. Eso alcanza en un SPA que no navega… y no
   * alcanza en el resto. MEDIDO en Educación (Next): el middleware redirige `/` → `/home` y
   * **se lleva la query puesta**. La sonda lo dijo con todas las letras — `corrio: true`,
   * `url: .../home`, `piel: ""` — o sea que el script CORRÍA y se iba por el `return` de la
   * versión, porque para cuando leyó el `search` ya no había search.
   *
   * Perseguí dos hipótesis equivocadas antes de medir esto: que Next difería el script (está
   * en el `<head>`, plano, corre al parsear) y que la hidratación de React pisaba los
   * atributos (los sostuve con un observer y siguió igual). **La sonda lo resolvió en una
   * corrida; las dos hipótesis costaron tres.**
   *
   * Se guardan en `sessionStorage` la PRIMERA vez que se ven y se leen de ahí cuando no
   * están. Es por pestaña y por origen: no filtra entre stacks ni sobrevive a cerrar la
   * pestaña, que es exactamente la vida útil que tiene que tener. Y resuelve de paso lo que
   * el `aleph.ts` de cada stack venía avisando desde agosto y no podía arreglar: que en
   * cuanto el router navega, los parámetros se pierden. */
  var CLAVE = "aleph-piel-params";
  function param(nombre) {
    var v = "";
    try { v = new URLSearchParams(location.search).get(nombre) || ""; } catch (e) {}
    if (v) {
      try {
        var g = JSON.parse(sessionStorage.getItem(CLAVE) || "{}");
        g[nombre] = v; sessionStorage.setItem(CLAVE, JSON.stringify(g));
      } catch (e) {}
      return v;
    }
    try { return (JSON.parse(sessionStorage.getItem(CLAVE) || "{}"))[nombre] || ""; }
    catch (e) { return ""; }
  }

  var VERSION = param("aleph_piel");
  if (VERSION !== "v2") return;
  var IDIOMA = param("aleph_lang");
  function copy(es, en) {
    return /^en(?:-|$)/i.test(IDIOMA || document.documentElement.lang || "es") ? en : es;
  }

  var ESQUEMA = param("aleph_scheme");
  if (ESQUEMA !== "dark" && ESQUEMA !== "light") ESQUEMA = "";

  // ⚠️ SE MARCA EL DOCUMENTO ANTES DE PEDIR LA HOJA. El atributo es lo que hace que el
  // interruptor sea MEDIBLE: una hoja que no carga (404, red caída, orden de scripts) haría
  // indistinguible «apagado» de «roto», y esta casa ya pagó esa confusión varias veces.
  /* ⚠️ Y SE VUELVE A PONER SI ALGUIEN LO PISA. Medido en Educación (Next, App Router): el
   * script corre en el `<head>`, pone el atributo… y la HIDRATACIÓN de React lo BORRA. React
   * es dueño del `<html>` en el App Router y al hidratar reconcilia sus atributos contra lo
   * que el servidor mandó — donde no estaba el nuestro. El síntoma era total y mudo: la hoja
   * cargaba con 200, el script corría, y `data-aleph-piel` salía vacío.
   * Es la misma lección que la fase 2 aprendió con `espacios.js`: no alcanza con hacerlo una
   * vez, hay que sostenerlo. Un observer sobre los atributos de la raíz, con ventana acotada:
   * si a los 15 s nadie los pisó, no los va a pisar. */
  function marcar() {
    try {
      var h = document.documentElement;
      if (h.getAttribute("data-aleph-piel") !== VERSION) h.setAttribute("data-aleph-piel", VERSION);
      if (ESQUEMA && h.getAttribute("data-aleph-scheme") !== ESQUEMA) h.setAttribute("data-aleph-scheme", ESQUEMA);
      /* [fase 5 · 5.2] Y EL WORKSPACE. La hoja lo necesita para acotar el mapeo de un stack
       * sin pisarle el de los otros: Finanzas usa el shadcn viejo (triplete HSL) y Oficina y
       * Educación el nuevo (color) con LOS MISMOS NOMBRES de variable. Sin esta marca, un
       * solo `:root` servía a dos y rompía al tercero en silencio. */
      var WS_M = param("aleph_ws");
      if (WS_M && h.getAttribute("data-aleph-ws") !== WS_M) h.setAttribute("data-aleph-ws", WS_M);
    } catch (e) {}
  }
  marcar();
  try {
    var t0m = Date.now();
    var obsAttr = new MutationObserver(function () {
      marcar();
      if (Date.now() - t0m > 15000) obsAttr.disconnect();
    });
    obsAttr.observe(document.documentElement, { attributes: true, attributeFilter: ["data-aleph-piel", "data-aleph-scheme", "class"] });
  } catch (e) {}

  /* ── EL TEMA, UNO SOLO PARA LOS SEIS ────────────────────────────────────────────────
   * [fase 3] Cada stack señala «oscuro» a su manera. Medido, uno por uno:
   *     Oficina    [data-theme="dark"]          Finanzas   .dark
   *     Educación  .dark                        Diseño     .dark
   *     Legal      prefers-color-scheme         Ciencia    prefers-color-scheme
   *                                                        + html[data-color-scheme]
   * Adivinar cuál aplica en cada uno sería seis reglas frágiles. En vez de eso se escribe
   * NUESTRO atributo con el valor que la casa YA manda en la URL desde la fase 1
   * (`aleph_scheme`), y la hoja lo lee primero. Los selectores propios de cada stack quedan
   * en la hoja como respaldo, para el caso de que la casa no lo mande. */
  try {
    // Y si la casa lo cambia con la pantalla abierta, ya manda un `postMessage` (fase 1):
    // se escucha el mismo mensaje en vez de inventar otro canal.
    window.addEventListener("message", function (ev) {
      var d = ev && ev.data;
      if (!d || d.type !== "aleph-theme") return;
      if (d.scheme === "dark" || d.scheme === "light") { ESQUEMA = d.scheme; marcar(); }
    });
  } catch (e) {}

  // ⚠️ LA HOJA SE PONE DOS VECES, Y NO ES UN DESCUIDO. Este script corre mientras el
  // `<head>` todavía se está parseando, así que el `appendChild` la deja ANTES de las hojas
  // del stack que vienen más abajo en el documento — y con igual especificidad, la última
  // gana. Se agrega ya (para que empiece a descargar y no haya destello) y se MUEVE al
  // final del `<head>` cuando el documento terminó de parsearse, que es donde tiene que
  // estar para ganar sin subir especificidad ni repartir `!important`. Mover un nodo ya
  // cargado no lo vuelve a pedir.
  try {
    var l = document.createElement("link");
    l.rel = "stylesheet";
    l.id = "aleph-piel";
    l.href = "/aleph-piel.css?v=" + encodeURIComponent(VERSION);
    (document.head || document.documentElement).appendChild(l);
    document.addEventListener("DOMContentLoaded", function () {
      try { if (document.head && l.parentNode === document.head) document.head.appendChild(l); } catch (e) {}
    });
  } catch (e) {
    // Jamás tumbar la pantalla del stack por la piel. Sin hoja, el atributo queda igual y
    // la vara puede decir «el interruptor prendió y la hoja no llegó», que es un diagnóstico
    // y no un misterio.
  }

  /* ══ EL BLOQUE DE LA CASA, ARRIBA DEL SIDEBAR DEL STACK ═══════════════════════════════
   * [fase 3 · opción A · la única cirugía de esta fase]
   *
   * EL MOLDE ES EL DEL PICKER, no uno nuevo: una tabla de ANCLAS por stack, se toma la
   * primera que matchee, y se inserta lo nuestro en su lugar exacto sin tocar una línea de
   * su código. `aleph-picker-unico.js` hace esto desde agosto para el chip de modelo.
   *
   * ⚠️ LAS ANCLAS SON ATRIBUTOS, NO CLASES. `data-sidebar="header"` es de la primitiva de
   * shadcn y sobrevive un rebuild; una clase de Tailwind cambia con el hash del build. Donde
   * el stack no expone un atributo estable, el ancla queda `null` y esta parte NO CORRE: es
   * preferible un stack sin cabecera de Aleph a una cabecera colgada de un selector que se
   * rompe solo. Los que faltan se agregan cuando se mide su marcado, no antes.
   *
   * ⚠️ Y NO SE REEMPLAZA NADA SUYO. Su sidebar sigue entero debajo: sus secciones, su lista
   * de sesiones, sus botones. Lo nuestro se PREPENDE. Restilar es de la hoja; reemplazar
   * sería inventar, y lo que hay adentro no lo podemos llenar desde acá. */
  var ANCLAS = [
    // Oficina · openwork — primitiva shadcn, atributo estable, medido en components/ui/sidebar.tsx
    { ws: "oficina",  sel: '[data-sidebar="header"]' },
    // Educación · deeptutor — la misma primitiva
    { ws: "educacion", sel: '[data-sidebar="header"]' },
    // Los otros cuatro todavía no tienen ancla medida: su cabecera entra cuando se mire su
    // marcado. Hasta entonces reciben color y letra, que es lo que la hoja ya les da.
  ];

  /* ⚠️ LOS PARÁMETROS SE LEEN UNA SOLA VEZ, AL CARGAR, Y ESTO ES LOAD-BEARING.
   * El `aleph.ts` de cada stack ya lo dejó escrito en agosto: «la casa los pasa en la URL
   * del `<iframe>`, y en cuanto el router de esta app navega, el `search` se pierde. Leerlos
   * tarde daría "no estoy adentro de Aleph" justo después del primer click».
   * Caí en esa trampa igual: `cabecera()` corre desde un MutationObserver —o sea TARDE, cuando
   * el sidebar del stack ya se montó— y para entonces `location.search` podía estar vacío. El
   * síntoma fue chico y silencioso: la cabecera salía con «Aleph» y SIN el nombre del espacio.
   * Se lee al cargar y se guarda. */
  var WS_CARGA = param("aleph_ws");
  var LABEL_CARGA = param("aleph_label");

  /* ⚠️ LA INYECCIÓN SE APAGA DONDE HAY FRAME NATIVO. Desde la fase 6 el frame se escribe en
   * el componente del stack; si ADEMÁS se inyectara, habría dos caminos dibujando la misma
   * cabecera y uno de los dos terminaría mintiendo —el clásico de esta casa—. El componente
   * marca la raíz con `data-aleph-frame-nativo` cuando de verdad se montó, así que el
   * apagado depende de un HECHO, no de una lista de stacks que hay que acordarse de tocar. */
  function frameNativo() {
    try { return document.documentElement.hasAttribute("data-aleph-frame-nativo"); } catch (e) { return false; }
  }

  function cabecera() {
    if (frameNativo()) return true;   /* nada que hacer: su componente ya lo dibujó */
    var ws = WS_CARGA;
    var nombre = LABEL_CARGA;

    var caso = null;
    for (var i = 0; i < ANCLAS.length; i++) {
      if (ANCLAS[i].ws && ws && ANCLAS[i].ws !== ws) continue;
      if (document.querySelector(ANCLAS[i].sel)) { caso = ANCLAS[i]; break; }
    }
    if (!caso) return false;
    var host = document.querySelector(caso.sel);
    if (!host || document.querySelector(".aleph-piel-cabecera")) return false;

    var caja = document.createElement("div");
    caja.className = "aleph-piel-cabecera";
    var img = document.createElement("img");
    img.src = "/aleph-mascot-v2.png"; img.alt = ""; img.width = 20; img.height = 20;
    var marca = document.createElement("span");
    marca.className = "aleph-piel-marca"; marca.textContent = "Aleph";
    var esp = document.createElement("span");
    esp.className = "aleph-piel-espacio"; esp.textContent = nombre;
    caja.appendChild(img); caja.appendChild(marca); if (nombre) caja.appendChild(esp);

    /* ⚠️ `‹ Inicio` NO PUEDE SER UN LINK. Estamos adentro de un `<iframe>` en OTRO ORIGEN:
     * `location` del padre es inalcanzable y un `<a target="_top">` sería bloqueado. El
     * camino es pedirle el destino a la cáscara por `postMessage`, que es EXACTAMENTE lo que
     * `oficina.html:276` ya hace para `aleph-open-settings`. Se reusa ese contrato con otro
     * tipo; la cáscara, que sí conoce su ruta, resuelve. */
    var volver = document.createElement("button");
    volver.type = "button";
    volver.className = "aleph-piel-inicio";
    volver.textContent = copy("‹ Inicio", "‹ Home");
    volver.addEventListener("click", function () {
      try { window.parent.postMessage({ type: "aleph-go-home" }, "*"); } catch (e) {}
    });

    var sep = document.createElement("div");
    sep.className = "aleph-piel-sep";

    host.insertBefore(sep, host.firstChild);
    host.insertBefore(volver, host.firstChild);
    host.insertBefore(caja, host.firstChild);
    return true;
  }


  /* ══ EL PIE DE LA CASA, ADENTRO DE LA BARRA DEL STACK ═════════════════════════════════
   * [rediseño · fase 6 · el frame · Ley 6 tercera cirugía]
   *
   * EL PROBLEMA QUE CIERRA. La fase 2 construyó `aside.ws-riel` de 260 px como CÁSCARA para
   * llenar desde adentro del iframe —lo dice su propio comentario— y la fase 3, en vez de
   * llenarla, inyectó la cabecera en la barra del stack. Resultado medido: DOS columnas y
   * DOS cabeceras «Aleph · Oficina». El diseño pide UNA barra, y la única que puede llevar
   * los ítems del stack es la del stack: sus sesiones, su New chat y su Search viven de su
   * estado, y desde este lado del iframe no se pueden llenar.
   *
   * ⚠️ POR QUÉ NO ALCANZA CON BORRAR NUESTRO RIEL. Su pie no está vacío: tres módulos se
   * auto-montan ahí buscando `.ws-bar` —`ajustes.js` (⚙), `destinos-del-espacio.js` («Ir a…»)
   * y `conectores-del-espacio.js` («Conectores»)— y sus paneles se dibujan en el PADRE con
   * `document.body.appendChild`. Esconder el riel dejaría tres botones vivos e inalcanzables:
   * el defecto nº12 de esta casa, un botón movido sin su cable.
   *
   * LA SALIDA: MANDO A DISTANCIA, NO COPIA. Lo que se inyecta acá adentro no reimplementa
   * nada — le pide al padre que apriete SU botón real, que sigue existiendo con su handler,
   * su estado y su panel. Es literalmente el mismo handler, movido de lugar el disparador.
   * El contrato ya estaba escrito: `aleph-go-home` y `aleph-open-settings` viajan así desde
   * agosto; lo único nuevo es el tipo `aleph-pie`. */
  var PIE_BOTONES = [
    /* `sel` es el selector del botón REAL en el padre. Si el padre no lo encuentra, no pasa
     * nada: no se dibuja el nuestro. Un ítem que no puede gobernar no se pinta — es la regla
     * del hueco honesto, y evita el botón lindo que no hace nada. */
    { id: "ajustes",   glifo: "⚙", rotulo: copy("Ajustes", "Settings") },
    { id: "destinos",  glifo: "",  rotulo: null },
    { id: "conectores", glifo: "", rotulo: null },
  ];

  function pie() {
    if (frameNativo()) return true;   /* idem */
    var barra = document.querySelector('[data-sidebar="sidebar"], [data-slot="sidebar-inner"]');
    if (!barra || document.querySelector(".aleph-piel-pie")) return false;

    var caja = document.createElement("div");
    caja.className = "aleph-piel-pie";

    /* Se pregunta ANTES de dibujar. El padre contesta qué botones existen de verdad en su
     * `.ws-bar`; con esa lista se dibuja. Preguntar es barato y evita inventar. */
    var b = document.createElement("button");
    b.type = "button";
    b.className = "aleph-piel-pie-item";
    b.setAttribute("data-aleph-pie", "ajustes");
    var g = document.createElement("span");
    g.className = "aleph-piel-pie-glifo"; g.textContent = "⚙";
    var r = document.createElement("span");
    r.className = "aleph-piel-pie-rotulo"; r.textContent = copy("Ajustes", "Settings");
    b.appendChild(g); b.appendChild(r);
    b.addEventListener("click", function () {
      /* `aleph-open-settings` YA EXISTE en la cáscara y ya resuelve la sección y el espacio.
       * No se inventa un tipo nuevo para algo que la casa sabe hacer desde agosto. */
      try { window.parent.postMessage({ type: "aleph-open-settings", section: "perfil" }, "*"); } catch (e) {}
    });
    caja.appendChild(b);

    /* Los otros dos —«Ir a…» y «Conectores»— son botones del padre con panel propio. Se
     * relocalizan por mando a distancia: el padre aprieta el suyo. Se dibujan sólo si el
     * padre confirma que existen (ver `aleph-pie-censo` más abajo). */
    PIE_BOTONES.forEach(function (it) {
      if (it.id === "ajustes") return;
      var x = document.createElement("button");
      x.type = "button";
      x.className = "aleph-piel-pie-item";
      x.setAttribute("data-aleph-pie", it.id);
      x.hidden = true; /* hasta que el censo del padre lo confirme */
      x.addEventListener("click", function () {
        try { window.parent.postMessage({ type: "aleph-pie", boton: it.id }, "*"); } catch (e) {}
      });
      caja.appendChild(x);
    });

    barra.appendChild(caja);

    /* EL CENSO. El padre contesta con los botones que de verdad tiene y su rótulo TRADUCIDO
     * —«Ir a…» / «Conectores» salen de su i18n, no de una cadena nuestra que se desincroniza. */
    window.addEventListener("message", function (ev) {
      var d = ev.data || {};
      if (d.type !== "aleph-pie-censo" || !d.botones) return;
      d.botones.forEach(function (bo) {
        var n = caja.querySelector('[data-aleph-pie="' + bo.id + '"]');
        if (!n) return;
        n.hidden = false;
        var rr = document.createElement("span");
        rr.className = "aleph-piel-pie-rotulo"; rr.textContent = bo.rotulo || bo.id;
        n.textContent = ""; n.appendChild(rr);
      });
    });
    try { window.parent.postMessage({ type: "aleph-pie-censo?" }, "*"); } catch (e) {}
    return true;
  }

  /* El sidebar del stack se monta con su app, no con el documento. Se intenta al cargar y se
   * VUELVE A INTENTAR mientras no esté: es el mismo problema que la carrera de `espacios.js`
   * que la fase 2 cerró —muestrear una vez y rendirse—, y acá no tenemos su evento. Se corta
   * a los 10 s: si en diez segundos no hay sidebar, no lo va a haber. */
  try {
    pie();
    if (!cabecera()) {
      var t0 = Date.now();
      var obs = new MutationObserver(function () {
        var hechos = cabecera(); pie();
        if (hechos || Date.now() - t0 > 10000) obs.disconnect();
      });
      obs.observe(document.documentElement, { childList: true, subtree: true });
    }
  } catch (e) { /* jamás tumbar la pantalla del stack por la cabecera */ }

  /* ══ EL MENÚ DE FINANZAS — LA DEUDA DE LA FASE 4.4 ═══════════════════════════════════
   * [rediseño · fase 5 · obra 5.0]
   *
   * ⚠️ CORRECCIÓN A LO QUE DIJO LA FASE 4. Escribí entonces que los cuatro ítems del menú
   * «+» del mockup 35b había que DIBUJARLOS. Falso, y lo mide este archivo: el composer de
   * vibetrading ya trae los cinco (`Upload PDF · Research Goal · Agent Swarm · Check
   * connector · Analyze connector portfolio`), anidados en un solo menú y con la separación
   * exacta del mockup. También dije que el composer «sólo sabía cancelar» el goal y el
   * swarm: falso — `onStartGoal()` y `onStartSwarm()` están cableados desde su origen. Lo
   * había concluido de grepear los `onCancel*` sin leer el bloque de arriba.
   *
   * O sea que 5.0 NO es dibujar cuatro ítems: es CAMBIARLE EL EFECTO A DOS. Hoy `Check
   * connector` y `Analyze connector portfolio` llaman a `submitPrompt(...)`, que hace
   * `onSubmit(...)` — MANDAN EL TURNO SOLOS. El dueño decidió (opción 3) que el click
   * escriba la frase en el composer y que el humano apriete enviar: cero poder nuevo para
   * la UI, y el modelo sigue decidiendo si usa la tool.
   *
   * ⚠️ CERO ARCHIVOS DE VIBETRADING TOCADOS. Se intercepta el click en FASE DE CAPTURA sobre
   * `document`: React 18 escucha en su contenedor raíz, que está por DEBAJO, así que cortar
   * acá le saca el evento antes de que su handler exista siquiera. Es la misma técnica con
   * la que `aleph-picker-unico.js` le cierra a un stack sus dos caminos al modelo.
   *
   * ⚠️ EL MENÚ NO EXISTE AL CARGAR: se monta con `showUploadMenu`. Por eso el listener va
   * DELEGADO en `document` y no sobre el menú — colgarlo del nodo daría un cable que nace
   * muerto, que es el defecto nº12 de esta casa. */
  var MENU_FINANZAS = [
    /* Las frases son las CONSTANTES DE ELLOS, copiadas de `Composer.tsx` (`CONNECTOR_CHECK_
     * PROMPT` y `CONNECTOR_PORTFOLIO_PROMPT`): el objetivo es que el turno resultante sea el
     * mismo de hoy MENOS el envío automático. Copiar texto ajeno abre deriva, así que la
     * vara compara estas dos cadenas contra su archivo y se pone roja si se separan.
     *
     * Los rótulos salen de sus CINCO locales (`i18n/locales/*.json`, clave `agent.check
     * Connector` / `agent.analyzePortfolio`). Emparejar por texto es lo único independiente
     * del idioma activo, que desde adentro del iframe no sabemos. El ícono no sirve de ancla:
     * medido, `lucide-landmark` NO sobrevive al build (0 ocurrencias en `dist/assets/*.js`). */
    {
      id: "check",
      pos: 3,
      rotulos: ["Check connector", "检查连接器", "コネクタを確認", "커넥터 확인", "فحص الموصل"],
      frase: "List my trading connector profiles, show which one is selected, then check that selected connector. If it is not ready, tell me exactly what setup step is missing. Do not place or modify orders."
    },
    {
      id: "portfolio",
      pos: 4,
      rotulos: ["Analyze connector portfolio", "分析连接器投资组合", "コネクタポートフォリオを分析", "커넥터 포트폴리오 분석", "تحليل محفظة الموصل"],
      frase: "Use the selected trading connector profile to summarize my account, positions, concentration, cash, and portfolio risk. Do not place or modify orders."
    }
  ];

  /* El composer se busca por ESTRUCTURA, no por clase: se sube desde el menú hasta el primer
   * ancestro que contenga un `<textarea>`. Sus clases son Tailwind y cambian con el hash del
   * build; su `aria-label` está traducido. La estructura —menú y textarea hermanos bajo la
   * fila del composer— es la que su propio marcado garantiza. */
  function composerDe(nodo) {
    var p = nodo;
    while (p && p !== document.body) {
      var ta = p.querySelector("textarea");
      if (ta) return ta;
      p = p.parentElement;
    }
    return null;
  }

  /* ⚠️ NO ALCANZA CON `ta.value = frase`. El textarea es CONTROLADO por React (`value={input}`)
   * y en el próximo render lo pisa con el estado viejo: se vería la frase por un instante y
   * desaparecería. Hay que escribir por el setter nativo del prototipo —el que React parchea
   * para poder detectar cambios— y después despachar un `input` que burbujee, que es el
   * evento con el que React alimenta su `onChange`. Su `onInput` de auto-alto viaja en el
   * mismo evento, así que la caja crece sola como con cualquier tecla. */
  function escribirEnComposer(ta, frase) {
    try {
      var d = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value");
      if (d && d.set) d.set.call(ta, frase); else ta.value = frase;
      ta.dispatchEvent(new Event("input", { bubbles: true }));
      ta.focus();
      try { ta.setSelectionRange(frase.length, frase.length); } catch (e) {}
      return true;
    } catch (e) { return false; }
  }

  function itemDelMenu(menu, boton) {
    var items = menu.querySelectorAll('[role="menuitem"]');
    var idx = -1;
    for (var i = 0; i < items.length; i++) if (items[i] === boton) { idx = i; break; }
    var texto = (boton.textContent || "").replace(/\s+/g, " ").trim();
    for (var j = 0; j < MENU_FINANZAS.length; j++) {
      var it = MENU_FINANZAS[j];
      if (it.rotulos.indexOf(texto) !== -1) return it;
    }
    /* Respaldo por POSICIÓN, para el día que agreguen un idioma o cambien un rótulo: son los
     * dos últimos de cinco, en el orden que dicta su propio marcado. Si ni el texto ni la
     * posición lo identifican, NO SE INTERCEPTA: se lo deja pasar a su handler. Un ítem
     * ajeno interceptado por error escribiría la frase equivocada, y eso es peor que quedarse
     * con el comportamiento de hoy. La vara mide el emparejamiento por texto, así que la
     * deriva sale en rojo y no en silencio. */
    if (items.length === 5) {
      for (var k = 0; k < MENU_FINANZAS.length; k++) if (MENU_FINANZAS[k].pos === idx) return MENU_FINANZAS[k];
    }
    return null;
  }

  function puenteMenuFinanzas() {
    /* Mismo criterio que ANCLAS: si sabemos el ws y no es finanzas, ni se cuelga el listener.
     * El ancla igual es única de vibetrading, así que en los otros cinco esto no dispara. */
    if (WS_CARGA && WS_CARGA !== "finanzas") return;
    document.addEventListener("click", function (ev) {
      try {
        var t = ev.target;
        if (!t || !t.closest) return;
        var boton = t.closest('[role="menuitem"]');
        if (!boton) return;
        var menu = boton.closest("#agent-more-options-menu");
        if (!menu) return;
        var item = itemDelMenu(menu, boton);
        if (!item) return;

        var ta = composerDe(menu);
        if (!ta) return; /* sin composer no hay a dónde escribir: que siga su camino */

        /* El corte va DESPUÉS de tener el textarea: cortar primero y fallar después dejaría
         * un ítem que no hace nada, que es exactamente lo que esta fase vino a no hacer. */
        ev.preventDefault();
        ev.stopPropagation();
        if (ev.stopImmediatePropagation) ev.stopImmediatePropagation();

        escribirEnComposer(ta, item.frase);

        /* CERRAR EL MENÚ CON SU PROPIO MECANISMO. Al cortar el evento, su
         * `setShowUploadMenu(false)` tampoco corrió, así que el menú quedaría abierto. En vez
         * de tocarle el estado, se le hace click al disparador —que es suyo y ya sabe
         * togglear—. Si está deshabilitado (`streaming`), el menú queda abierto y no pasa
         * nada más: preferible a inventarle un cierre. */
        var disp = document.querySelector('[aria-controls="agent-more-options-menu"]');
        if (disp && !disp.disabled) disp.click();
      } catch (e) { /* jamás tumbar el composer del stack por el puente */ }
    }, true);
  }

  try { puenteMenuFinanzas(); } catch (e) {}
})();
