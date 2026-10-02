/* ajustes.js — EL ⚙ ÚNICO, y el LECTOR de lo guardado.
 * [Convergencia · superficie 3 · fase 3 · corregida]
 *
 * QUÉ HACE HOY: pone el ⚙ en el mismo píxel de las 26 pantallas que cargan `theme.js` —los
 * 6 workspaces incluidos—, y ese ⚙ lleva SIEMPRE al mismo lugar: `Settings.dc.html`. Además
 * adopta al arrancar lo que nadie más adopta (hoy, `tamano_texto`).
 *
 * QUÉ HACÍA ANTES, Y POR QUÉ SE FUE. Dibujaba un overlay de ajustes encima del lienzo. El
 * argumento era bueno —entrar a una pantalla apaga lo que estabas haciendo— pero el
 * resultado era un SEGUNDO Ajustes: el mismo botón abría el overlay en Home y navegaba a la
 * página adentro de un workspace. Dos destinos para un botón es peor que un salto de
 * pantalla. Se eligió la página porque es la que tiene Perfil, API keys, Conexiones y
 * Memoria, que no entran en un panel de esquina.
 *
 * EL COSTO, dicho y no escondido: desde un workspace, tocar el ⚙ descarga el lienzo. El pack
 * NO se muere —el `leave` tiene ventana de gracia (`pack.py:GRACIA_S`)— pero se ve el salto.
 *
 * POR QUÉ SE CARGA DESDE `theme.js` Y NO DESDE `nav.js`. Medido, archivo por archivo:
 *
 *     nav.js    → 15 de 35 pantallas, y NINGUNO de los 6 workspaces
 *     theme.js  → 26 de 35, INCLUIDOS los 6 workspaces
 *
 * Las 9 que no cargan `theme.js` son shims, fixtures y sondas (`_live`, `dispatch`,
 * `resolver`, `canvas-preview`…), no pantallas de producto. O sea: `theme.js` es el único
 * enganche que cumple «el mismo píxel TAMBIÉN adentro del workspace», que es justo el caso
 * que esta fase existe para arreglar. La inyección copia el patrón que `nav.js` ya usa para
 * `aleph-ds.js` — no es un mecanismo nuevo.
 *
 * EL ⚙ REEMPLAZA AL TOGGLE FLOTANTE DE TEMA. Es un cambio visible y deliberado: el plan pide
 * UN solo disparador en el mismo píxel, y dos botones flotantes en la misma esquina son dos.
 * El tema no se pierde: es el primer control del overlay, a un click.
 *
 * DÓNDE SE PONE: si la pantalla tiene `.ws-bar` —la barra de la casa encima del lienzo
 * ajeno— el ⚙ va ahí, al lado de «Conectores». Si no, flota abajo a la derecha. Ver el
 * comentario en `montar()`: colgarlo de `ALEPH_THEME_NOFLOAT` lo dejaba invisible en los
 * seis workspaces, y eso lo destapó mirar la pantalla, no la vara.
 *
 * LOS DOS RÓTULOS SON DE OFICINA: `GENERAL` y el nombre del espacio, a secas —el mismo
 * vocabulario que `espacios.js` usa en Historial y Biblioteca, para que el usuario no lea
 * dos formas de la misma idea en la misma sesión—. Cuestan dos strings y resuelven la
 * pregunta que ningún otro stack contesta: «esto que estoy tocando, ¿me
 * cambia todo o sólo acá?». El ámbito viaja al almacén, que ya lo soporta desde la fase 2
 * con precedencia espacio > casa > default.
 *
 * EL REGISTRO ES DECLARATIVO, y eso es de CIENCIA (`settings/registry.ts`): una tabla de
 * paneles en vez de un `switch`. Es la única de las seis estructuras de ajustes que escala
 * sin reescribir el shell.
 *
 * ⚠️ SÓLO SE DIBUJA LO QUE ALGUIEN LEE. `idioma_salida` y `tema_codigo` existen en el
 * contrato desde la fase 2 y NO están acá: todavía no hay quién los consuma, y un control
 * sin lector es exactamente la perilla pintada que esta misma superficie extirpó en la fase
 * 0. Entran el día que exista su lector, y ese día son cuatro líneas en `PANELES`.
 *
 * `Settings.dc.html` SIGUE VIVA. Hay links viejos apuntando ahí y no se rompen.
 */
(function () {
  "use strict";
  if (window.__alephAjustes) return;
  window.__alephAjustes = true;

  var CASA = "casa";
  var API = "/v1/preferencias";

  /* EL NOMBRE HUMANO DE UN ESPACIO. Acá decía `ws.toUpperCase()` y en pantalla se leía
   * `DISENO` y `EDUCACION` —sin la ñ y sin la tilde—: el id crudo no es un rótulo. La tabla
   * ya existía y ahora vive sola en `espacios-tabla.js`, seis strings sin dependencias, para
   * que este archivo pueda consumirla sin arrastrar el subsistema de conectores a las 26
   * pantallas donde corre. Lo dejó nombrado con archivo:línea `qa/DEUDA-ROTULOS-DE-AMBITO.md`.
   *
   * La carga es dinámica y perezosa porque este archivo se inyecta como script CLÁSICO (no
   * módulo) y no puede tener un `import` arriba. Mientras no llegó, se usa el id: es el
   * peor caso y es exactamente lo que había antes, así que nada empeora si falla. */
  var TABLA = null;
  try {
    var aqui = (document.currentScript && document.currentScript.src) || "";
    import(aqui.replace(/ajustes\.js.*$/, "") + "espacios-tabla.js")
      .then(function (m) { TABLA = m; })
      .catch(function () {});
  } catch (e) {}

  function etiqueta(id) {
    if (TABLA && TABLA.etiqueta) return TABLA.etiqueta(id);
    return id || "";
  }

  function _t(k, fb) { try { var s = window.t && window.t(k); return (s && s !== k) ? s : fb; } catch (e) { return fb; } }

  /* ── EN QUÉ ESPACIO ESTAMOS ───────────────────────────────────────────────────────────
   * Las páginas de workspace declaran su id; el resto es la casa. Se lee del DOM y no de la
   * URL porque `workspaces/ciencia.html` puede abrirse con query distintas y el id es del
   * documento, no del navegante. */
  function espacio() {
    try {
      var m = document.querySelector('meta[name="aleph-workspace"]');
      if (m && m.content) return m.content;
      var p = (location.pathname || "").match(/\/workspaces\/([a-z0-9_-]+)\.html/i);
      return p ? p[1] : null;
    } catch (e) { return null; }
  }

  /* ── EL REGISTRO ──────────────────────────────────────────────────────────────────────
   * `clave` es la del almacén (`platform/workspaces/memoria.py:AJUSTES`). `aplicar` es lo
   * que hace que el ajuste SE VEA — sin `aplicar`, un panel acá sería una perilla pintada. */
  var PANELES = [
    {
      id: "tema", seccion: "Apariencia", clave: "tema",
      titulo: function () { return _t("set.theme.label", "Tema"); },
      sub: function () { return _t("set.theme.desc", "Claro, oscuro, o que siga tu sistema."); },
      opciones: [["light", "set.theme.light", "Claro"], ["dark", "set.theme.dark", "Oscuro"],
                 ["system", "set.theme.system", "Sistema"]],
      leer: function () { try { return window.AlephTheme ? window.AlephTheme.get() : "dark"; } catch (e) { return "dark"; } },
      aplicar: function (v) { try { if (window.AlephTheme) window.AlephTheme.set(v); } catch (e) {} },
      //: el tema es de la instalación entera; no tiene sentido «sólo en Ciencia».
      soloCasa: true,
    },
    {
      id: "idioma", seccion: "Apariencia", clave: "idioma",
      titulo: function () { return _t("set.lang.label", "Idioma"); },
      sub: function () { return _t("set.lang.desc", "El idioma de la interfaz."); },
      opciones: [["es", null, "Español"], ["en", null, "English"]],
      leer: function () { try { return window.AlephI18n ? window.AlephI18n.lang() : "es"; } catch (e) { return "es"; } },
      aplicar: function (v) { try { if (window.AlephI18n) window.AlephI18n.setLang(v); } catch (e) {} },
      //: El control se esconde donde no hay motor de idioma, en vez de mentir que cambia
      //: algo. Hoy eso es `brain-setup.html` y `cuarto/cuarto.html` —las dos únicas que
      //: cargan `theme.js` y no `i18n.js`—, y NO los workspaces: ellos sí lo cargan, con
      //: `?v=ws-1` en el src. (Lo medí mal la primera vez: un grep sin contemplar el query
      //: string decía 9 pantallas sin i18n cuando son 2.)
      disponible: function () { return !!window.AlephI18n; },
      soloCasa: true,
    },
    {
      id: "tamano_texto", seccion: "Apariencia", clave: "tamano_texto",
      titulo: function () { return _t("set.textsize.label", "Tamaño del texto"); },
      sub: function () { return _t("set.textsize.desc", "Para leer cómodo. Afecta a toda la interfaz."); },
      opciones: [["compacto", null, "Compacto"], ["estandar", null, "Estándar"], ["grande", null, "Grande"]],
      leer: function () { return document.documentElement.getAttribute("data-aleph-texto") || "estandar"; },
      // ESTO es lo que lo saca de ser una perilla pintada: escala la raíz, y todo lo que
      // esté en `rem` sigue. Se toma de Legal, la única de las seis que lo tiene.
      aplicar: function (v) {
        var esc = { compacto: "93.75%", estandar: "100%", grande: "112.5%" }[v] || "100%";
        document.documentElement.style.fontSize = esc;
        document.documentElement.setAttribute("data-aleph-texto", v);
      },
      soloCasa: true,
    },
  ];

  /* ── EL ALMACÉN, POR HTTP ─────────────────────────────────────────────────────────── */
  function traer(ambito) {
    var u = API + (ambito && ambito !== CASA ? "?ambito=" + encodeURIComponent(ambito) : "");
    return fetch(u, { headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  /* ── LA CARA: NO HAY. ─────────────────────────────────────────────────────────────────
   * Acá vivía un overlay entero —`estilos`, `pintar`, `abrir`, `cerrar`, la caja y su
   * hoja— con dos pestañas, `GENERAL` y el nombre del espacio. Se fue, y el motivo no es
   * de gusto: era un SEGUNDO Ajustes. El mismo ⚙ abría el overlay en Home y La Sala, y
   * navegaba a `Settings.dc.html` adentro de un workspace; dos destinos para un botón.
   *
   * Y su pestaña de ámbito no gobernaba nada: los tres paneles que dibujaba son
   * `soloCasa: true`, así que elegir «sólo Oficina» no cambiaba dónde se guardaba el
   * valor. Era un control que prometía un alcance que ninguna de sus perillas tenía.
   *
   * LO QUE NO SE FUE, y es lo único que este archivo hacía de verdad: `PANELES` sigue
   * siendo el registro, y `adoptar()` sigue siendo el LECTOR de `tamano_texto` en las 26
   * pantallas. Sacar el lector junto con la cara habría dejado el ajuste guardado y sin
   * efecto — perder función en una mudanza de UI, que es peor que la duplicación. */
  var ambitoActual = CASA, ws = null;

  /* A DÓNDE LLEVA EL ⚙. Una sola dirección, `Settings.dc.html`, y el espacio viaja con
   * ella: la página necesita saber de dónde venís para ofrecer la sección de ESE espacio.
   * La ruta es relativa porque las pantallas de workspace cuelgan de `workspaces/`. */
  function destinoAjustes() {
    var base = /\/workspaces\//.test(location.pathname || "") ? "../Settings.dc.html"
                                                             : "./Settings.dc.html";
    return ws ? base + "?espacio=" + encodeURIComponent(ws) : base;
  }

  /* ── ADOPTAR LO GUARDADO AL ARRANCAR ──────────────────────────────────────────────────
   * `tema` e `idioma` ya los adopta `theme.js` (fase 1b) — no se hace dos veces. Acá sólo
   * lo que nadie más adoptaba. */
  function adoptar() {
    traer(ws || CASA).then(function (d) {
      var a = d && d.ajustes; if (!a) return;
      PANELES.forEach(function (p) {
        if (p.clave === "tema" || p.clave === "idioma") return;   // dueño: theme.js
        if (a[p.clave] && a[p.clave] !== p.leer()) p.aplicar(a[p.clave]);
      });
    });
  }

  /* El CSS del ⚙, y nada más. La hoja vieja tenía 23 reglas: una para el botón y 22 para
   * la caja del overlay. Se fueron con la caja; dejarlas habría sido dejar el estilo de una
   * pantalla que ya no se puede abrir. */
  function estilos() {
    if (document.getElementById("aleph-ajustes-css")) return;
    var s = document.createElement("style");
    s.id = "aleph-ajustes-css";
    s.textContent = [
      "#aleph-cog{position:fixed;bottom:18px;right:18px;z-index:99999;width:40px;height:40px;",
      "border-radius:var(--r-sm,13px);border:0;background:var(--glass,rgba(20,20,22,.78));",
      "-webkit-backdrop-filter:blur(16px);backdrop-filter:blur(16px);box-shadow:var(--sh-1,0 4px 14px rgba(0,0,0,.4));",
      "color:var(--ink,#e6e6e3);font-size:16px;cursor:pointer;line-height:1}",
      /* [rediseño · fase 2 · 2.4] ⚠️ EL ⚙ SIEMPRE FUE `position:fixed`, TAMBIÉN ADENTRO DE
       * LA BARRA. El comentario de `montar()` decía «va ahí, al lado de Conectores» y eso era
       * cierto en el DOM y falso en la PANTALLA: la regla de arriba lo clava abajo a la
       * derecha sin importar dónde esté colgado, así que en los seis workspaces se veía
       * flotando igual que en el resto. Lo destapó una captura del sidebar nuevo: el pie
       * tenía «Ir a…» y el estado, y el ⚙ seguía en la esquina.
       * Adentro del pie del sidebar vuelve al flujo, que es lo que el estándar pide: Settings
       * en el pie del sidebar, sin botones flotantes. */
      "#aleph-cog{}",
      ".ws-pie #aleph-cog{position:static;width:auto;height:auto;padding:8px 12px;",
      "background:var(--paper);backdrop-filter:none;-webkit-backdrop-filter:none;box-shadow:none;",
      "font-size:14px;border-radius:var(--r-sm,13px)}",
    ].join("");
    (document.head || document.documentElement).appendChild(s);
  }

  function montar() {
    ws = espacio();
    ambitoActual = CASA;
    adoptar();
    if (window.ALEPH_AJUSTES_OFF) return;
    if (document.getElementById("aleph-cog")) return;

    /* [Finanzas · el nudo de las dos barras] EL ⚙ NO SE DIBUJA DONDE EL STACK YA LO TIENE.
     *
     * La regla de acá abajo —«donde hay `.ws-bar` va ahí, donde no hay, flota en la
     * esquina»— era correcta MIENTRAS la casa dibujara una barra sobre el lienzo ajeno. Con
     * el shell único esa barra se borró, así que el ⚙ caía a su modo flotante: una pastilla
     * suelta en la esquina inferior derecha, encima del workspace. El estándar la prohíbe con
     * todas las letras («se cayeron las pastillas de idioma y tema») y además está DUPLICADA:
     * el pie que el stack dibuja ya tiene su «⚙ Settings», que manda `aleph-open-settings` y
     * llega al mismo lugar.
     *
     * Así que donde la piel v2 está puesta para este espacio, este módulo no monta nada. No
     * se pierde el destino: se pierde la segunda puerta. */
    try {
      var ws = espacio();   // ya existe acá arriba: meta, y si no, la ruta
      if (ws && window.AlephPiel && window.AlephPiel.version(ws) === "v2") return;
    } catch (e) {}
    estilos();
    var b = document.createElement("button");
    b.id = "aleph-cog"; b.type = "button";
    b.textContent = "⚙";
    b.setAttribute("aria-label", _t("nav.ajustes", "Ajustes"));
    b.setAttribute("title", _t("nav.ajustes", "Ajustes"));
    // UN destino, siempre el mismo: los Ajustes de Aleph. No hay una versión corta del
    // panel para unas pantallas y la larga para otras.
    b.addEventListener("click", function () { window.location.href = destinoAjustes(); });

    /* DÓNDE VA EL ⚙, y esto lo corrigió MIRAR LA PANTALLA, no la vara.
     *
     * Primero lo colgué de `!ALEPH_THEME_NOFLOAT`, razonando «si la pantalla trae su propio
     * control de esquina, no pongo otro». Estaba mal: los 6 workspaces declaran NOFLOAT
     * —porque tienen su `.ws-bar`, no porque tengan ajustes— así que el ⚙ NO aparecía
     * justamente en el caso que esta fase existe para arreglar. NOFLOAT habla del toggle de
     * TEMA; usarlo para decidir sobre AJUSTES era conflar dos cosas distintas.
     *
     * La regla correcta es por LUGAR, no por bandera: donde la casa ya tiene una barra
     * propia encima del lienzo ajeno, el ⚙ va ahí —al lado de «Conectores», que ya vive en
     * esa barra por el mismo motivo—. Donde no hay barra, flota en la esquina. En los dos
     * casos es el mismo píxel para el usuario: el borde inferior-derecho de lo que es de
     * la casa. */
    var barra = document.querySelector(".ws-bar");
    if (barra) {
      b.className = "ws-conect-entrada";
      b.removeAttribute("style");
      // ANTES DEL ESTADO, no al final. Es la misma regla que `conectores-del-espacio.js`
      // ya había escrito para su botón —«así el botón no se mueve cuando el pack pasa de
      // arrancando a listo»— y que yo había ignorado poniéndolo al final: el ⚙ se corría
      // solo cada vez que cambiaba el texto del estado. Lo destapó mirar el orden real de
      // la barra, no la vara.
      var estado = barra.querySelector("#ws-estado");
      if (estado) barra.insertBefore(b, estado); else barra.appendChild(b);
    } else if (document.getElementById("aleph-riel")) {
      /* [rediseño · fase 2 · 2.1] EL RIEL YA TIENE SU AJUSTES, así que acá no va otro.
       * El riel dibuja AJUSTES en su pie —es una de las dos entradas que el estándar pone
       * abajo, con Ayuda—, y dejar además el ⚙ flotando daría DOS disparadores del mismo
       * destino en la misma pantalla: exactamente lo que el comentario de arriba cuenta que
       * ya pasó una vez con el overlay. Se salta, y no se pierde nada: el destino es el
       * mismo y el riel está en las mismas pantallas.
       * ⚠️ La rama de `.ws-bar` de arriba SIGUE viva: los seis workspaces no tienen riel
       * (`inApp` los excluye) y su ⚙ es el único que tienen hasta la obra 2.4. */
      return;
    } else {
      document.body.appendChild(b);
    }
  }

  window.AlephAjustes = { montar: montar, paneles: PANELES, destino: destinoAjustes,
                          ambito: function () { return ambitoActual; } };

  if (document.body) montar();
  else document.addEventListener("DOMContentLoaded", montar);
})();
