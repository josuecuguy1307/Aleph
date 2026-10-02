/* RECOMENDADOS POR WORKSPACE · la vista que contesta «qué le sirve a ESTE espacio».
 *
 * Lee `GET /v1/connectors?workspace=<ws>` — el MISMO endpoint que va a leer la vista del
 * canvas. Eso no es economía de código: es la garantía de que las dos no se contradigan.
 * Si cada superficie resolviera su propia lista, configurar `github` en Ciencia podría verse
 * «sin configurar» en Diseño, y eso sería la cara mintiendo sobre el destino — que es
 * exactamente lo que la tabla de recomendaciones existe para evitar.
 *
 * Y la Lista A sale de `GET /v1/workspaces`, que YA sirve las fuentes por workspace (medido:
 * legal 33 · ciencia 42 · diseño 2 · finanzas 29). No se construyó endpoint nuevo.
 */

import { camposDeCredencial, CAUSAS_HUMANAS } from "./widget.js";
import { guardarLlave, empezarOauth } from "./fuentes.js";
import { traerRecomendados, traerFicha, traerFuentesPorEspacio } from "./recomendaciones.js";
import { pintarCampoLlave } from "./superficie-catalogo.js";
import { L, lang } from "./causas-catalogo.js";
import { ORDEN_ETIQUETA } from "../espacios-tabla.js";

/* LOS SEIS ESPACIOS Y SU NOMBRE HUMANO — UNA SOLA VEZ EN LA CASA.
 *
 * Se exporta porque dejó de ser sólo del selector de Recomendados: Historial y Biblioteca
 * filtran por espacio con esta MISMA tabla (`espacios.js`). Una segunda copia de seis
 * strings es cómo «Diseño» termina escrito «diseno» en una pantalla y «Diseño» en otra, y
 * cómo el orden de los chips difiere entre dos vistas que el usuario lee como una. */
// La tabla se mudó a `../espacios-tabla.js` —seis strings sin dependencias— porque el ⚙ de
// Ajustes la necesita en 26 pantallas y este archivo arrastra media docena de módulos.
// Se RE-EXPORTA para que ningún llamador de acá cambie su import.
export { ORDEN_ETIQUETA } from "../espacios-tabla.js";

/** El texto de una capability_line, que viene como string o como {es,en}. */
function linea(cap) {
  if (!cap) return "";
  if (typeof cap === "string") return cap;
  return cap[lang()] || cap.es || cap.en || "";
}

const nombreEspacio = (ws) => window.AlephI18n?.t(`ws.${ws}.nombre`) || ORDEN_ETIQUETA[ws] || ws;

/** La capacidad, SIN el «Listo —» que sólo aplica después de conectar.
 *
 *  ⚠️ EL DEFECTO QUE ESTO ARREGLA LO ENCONTRÓ EL DUEÑO MIRANDO LA PANTALLA, y era mío:
 *  `capability_line` es el mensaje de CONFIRMACIÓN —lo que Aleph dice una vez que la pieza
 *  quedó conectada, y por eso empieza con «Listo — ya puedo…»— y yo lo estaba usando como
 *  descripción de algo que el usuario NO configuró. Resultado: cada tarjeta de
 *  «Recomendados» decía «Listo», igual que las de «Ya funcionan», y las dos listas se
 *  volvían indistinguibles. La pregunta «¿cuál es la diferencia?» era la prueba del defecto.
 *
 *  Se le saca el marcador de confirmación cuando la pieza todavía no está puesta. No es
 *  reescribir el copy del catálogo: es no mostrar un «Listo» que no corresponde.
 *
 *  DEUDA DECLARADA: lo correcto de fondo es que el catálogo tenga su línea de ANTES además
 *  de la de después. Mientras no exista, esto es lo honesto; inventarle una descripción a 29
 *  conectores desde la UI sería peor.
 *
 *  ⚠️ EL PARÁMETRO ES `probada`, NO «tiene llave» — y la diferencia es el defecto entero.
 *  «Listo — ya puedo buscar en la web» sobre una llave que está GUARDADA y que nadie probó
 *  es afirmar que algo funciona sin haberlo medido nunca. El marcador de confirmación entra
 *  con el veredicto verde, no con el guardado. (Se exporta por el mismo motivo que `estado`
 *  y `selloDe`: el panel del canvas tenía esta misma regla escrita en línea.)
 */
export function capacidad(cap, probada) {
  const t = linea(cap);
  if (probada) return t;
  if (lang() === "en") return t.replace(/^\s*Done\s*[—–-]\s*/i, "").replace(/^I can now\s+/i, "Can ");
  return t.replace(/^\s*Listo\s*[—–-]\s*/i, "")
          .replace(/^ya\s+puedo\s+/i, "Puede ")
          .replace(/^conecté\s+tu\s+/i, "Conecta tu ");
}

/** Qué te pide, en una etiqueta. Es la mitad que le faltaba a la distinción entre las dos
 *  listas: «Ya funcionan» no pide nada, y acá cada fila DICE qué pide. */
function pide(auth) {
  const a = String(auth || "").toLowerCase();
  if (a === "oauth") return L("Pide autorizar tu cuenta", "Needs account authorization");
  if (a === "keyless") return "";                 // no debería llegar acá: ver `partir`
  return L("Pide tu llave", "Needs your key");
}

/** Los otros espacios donde el mismo conector se recomienda, en castellano. */
function tambienEn(ws, actual) {
  const otros = (ws || []).filter((w) => w !== actual).map(nombreEspacio);
  if (!otros.length) return "";
  if (otros.length === 1) return L(`También en ${otros[0]}.`, `Also in ${otros[0]}.`);
  const lista = otros.slice(0, -1).join(", ") + L(" y ", " and ") + otros[otros.length - 1];
  return L(`También en ${lista}.`, `Also in ${lista}.`);
}

/** El estado, con TRES valores y no dos.
 *
 *  ⚠️ `tiene_llave === null` NO es «sin configurar»: es «no sé» (no hay sesión, o no se pudo
 *  leer el vault). Pintarlo como «sin configurar» sería decirle a alguien que quizá lo tiene
 *  puesto que no lo tiene — la misma clase de mentira que el `connected: set.length > 0` que
 *  Ciencia midió, donde la pantalla afirmaba más de lo que sabía. */
/** LOS TRES ESTADOS DE UNA LLAVE, EN UN SOLO LUGAR — y por eso se exporta. El panel del
 *  canvas tenía su propia copia de esta decisión, que es exactamente cómo la misma llave
 *  termina diciendo «Guardada» en una pantalla y «Probada» en la otra. Una función, N
 *  vistas: la misma regla que obliga a las dos a leer el mismo endpoint. */
export function estado(c) {
  if (c.tiene_llave === true) {
    // ⚠️ DOS HECHOS, DOS PALABRAS. «Listo» sobre una llave que nadie probó es el mismo
    // `connected=True` que medí en Ciencia — y lo repetí acá sirviendo un solo hecho.
    // Medido en el vault real: `exa` tenía llave con veredicto vacío y `zotero` tenía
    // `{"estado":"verde","tool_prueba":"whoami","ts":…}`, y los dos decían «Listo».
    //   Probada  → hay veredicto verde, y se dice CUÁNDO (un veredicto sin fecha es
    //              afirmar de memoria)
    //   Guardada → la llave está; nadie la probó. NO es «falló».
    if (c.verificado === true) {
      return { txt: L("Probada", "Tested"), listo: "si", cuando: c.verificado_cuando || null,
               con: c.verificado_con || null };
    }
    //   Rechazada → SE PROBÓ Y NO PASÓ, que es el tercer estado y no existía. Sin él, una
    //              llave que el proveedor rechazó se leía «Guardada» igual que una que
    //              nadie tocó, y el usuario no tenía cómo enterarse de que hay que cambiarla.
    //   ⚠️ EL TEXTO NO SE ESCRIBE ACÁ. Sale de `CAUSAS_HUMANAS`, que es el diccionario
    //   sellado del semáforo — el mismo que lee la card del Cuarto y el chat de la Sala.
    //   Redactar «Credencial inválida» por mi cuenta es cómo la misma falla termina
    //   diciéndose distinto según la pantalla.
    if (c.verificado === false && c.verificado_falla) {
      const m = CAUSAS_HUMANAS[c.verificado_falla];
      return { txt: (m && (m[lang()] || m.es || m.en)) || L("No pasó la prueba", "Test failed"), listo: "falla",
               cuando: c.verificado_cuando || null };
    }
    return { txt: L("Guardada", "Saved"), listo: "guardada" };
  }
  if (c.tiene_llave === false) return { txt: L("Sin configurar", "Not configured"), listo: "no" };
  return { txt: "", listo: "?" };
}

/** La coletilla del veredicto: cuándo se probó y con qué. Vacía si no hay fecha. */
export function selloDe(e) {
  if (e.listo === "falla") {
    // La etiqueta ya dice QUÉ pasó (con la copy sellada); el sello dice CUÁNDO, y cierra
    // con lo único accionable: la llave se cambia, no se reintenta.
    const fecha = e.cuando ? String(e.cuando).slice(0, 10) : "";
    return L(`La probamos${fecha ? ` el ${fecha}` : ""} y no pasó. Pon otra llave para reemplazarla.`,
      `The test${fecha ? ` on ${fecha}` : ""} failed. Replace the key.`);
  }
  if (e.listo !== "si") {
    return e.listo === "guardada" ? L("Está guardada, pero todavía nadie la probó.", "Saved, but not tested yet.") : "";
  }
  if (!e.cuando) return L("Probada, sin fecha registrada.", "Tested; no date recorded.");
  const d = String(e.cuando).slice(0, 10);
  return L(`Probada el ${d}${e.con ? ` con ${e.con}` : ""}.`, `Tested on ${d}${e.con ? ` with ${e.con}` : ""}.`);
}

/** LA CAUSA DE QUE NO HAYA BOTÓN, DICHA.
 *
 *  El defecto que esto arregla no fue sólo técnico: la pantalla ESCONDÍA el botón y no
 *  explicaba por qué, así que el usuario veía «Pide tu llave» sin ningún lugar donde
 *  ponerla. Un estado que no se puede accionar y no dice por qué es peor que un error.
 *  «La causa siempre con copy» también vale para lo que NO se muestra. */
function copyDeSinSesion() {
  return L("No pude abrir la sesión local de este equipo, así que no sé cuáles ya tienes "
       + "configuradas y no puedo guardar una llave a tu nombre. Recarga la pantalla; "
       + "si sigue igual, es que el backend no está respondiendo /v1/auth/local.",
       "I could not open this device's local session, so I cannot determine which keys are configured or save a key for you. Reload the page. If the problem persists, the backend is not responding at /v1/auth/local.");
}

/** LA FILA DE UN RECOMENDADO · el ÚNICO render, para las dos vistas.
 *
 * La primera versión tenía este markup escrito dos veces —acá y en el panel del canvas— y
 * eso ya había producido el mismo defecto de OAuth en los dos lados. Se exporta para que el
 * canvas lo LLAME. `cruzaTxt` se pasa desde afuera porque cada vista lo dice a su manera:
 * la general nombra los espacios, la del canvas cuenta cuántos son. */
export function pintarFilaReco(c, { etiqueta, listo, capacidad: cap, cruzaTxt, accion, clase = "cx-row" }) {
  return `<li class="${clase}" data-fila="${esc(c.slug)}">
    <div>
      <strong>${esc(c.connector || c.slug)}</strong>
      ${etiqueta ? `<span class="cx-reco-estado" data-listo="${esc(listo)}">${esc(etiqueta)}</span>` : ""}
      <div class="cx-section-copy" style="margin:2px 0 0">${esc(cap)}</div>
      ${cruzaTxt ? `<div class="cx-reco-cruza">${esc(cruzaTxt)}</div>` : ""}
      <div class="cx-reco-form" data-form="${esc(c.slug)}" hidden></div>
    </div>
    ${accion || ""}
  </li>`;
}

export function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export function montarRecomendados(nodos, opciones = {}) {
  const { selector, filas, conteo, ambito, listaAFilas, listaAConteo, aviso } = nodos;
  if (!selector || !filas) return { ir() {} };
  // LA SESIÓN LLEGA DESPUÉS, porque `ensureLocal()` es asincrónico: pide
  // `POST /v1/auth/local` y persiste la identidad de ESTE equipo. Fijarla en el montaje
  // era lo que rompía todo — quedaba `null` para siempre y el botón no aparecía nunca.
  let userId = opciones.userId || null;
  let fuentesPorWs = {};

  // ⚠️ ACÁ HABÍA UNA `cabecera()` PROPIA, armada de un `auth` que esta vista se guardaba.
  // El token de sesión lo resuelve `fuentes.cabeceras()` —una vez, leyendo el mismo
  // `puppet_user` que el resto de la casa— y ahora lo hace la capa LEE. Dos lugares que
  // arman la autorización es cómo una pantalla queda autenticada y la otra no, contra el
  // mismo backend y en el mismo instante.

  async function traerFuentes() {
    // `null` = no se pudo leer. Se deja `fuentesPorWs` sin la clave para que `pintarListaA`
    // diga «no sé», que es distinto de «no hay».
    const mapa = await traerFuentesPorEspacio();
    if (mapa) fuentesPorWs = mapa;
  }

  function pintarListaA(ws, keylessDelCatalogo = []) {
    if (!listaAFilas) return;
    const todas = fuentesPorWs[ws];
    // LA AUSENCIA DE DATO NO ES UN CERO. Si este workspace no está instalado en esta
    // máquina, `fuentesPorWs` no lo tiene, y decir «0 ya funcionan» sería afirmar algo que
    // no medimos. Se dice que no se sabe.
      if (!todas) {
      listaAFilas.textContent = L("No pude leer qué hay listo en este espacio.", "Could not read what is ready in this workspace.");
      if (listaAConteo) listaAConteo.textContent = "—";
      return;
    }
    const keyless = todas.filter((f) => {
      const k = String(f.key == null ? "none" : f.key).toLowerCase();
      return k === "none" || k === "keyless";
    });
    // Los keyless del catálogo curado se suman acá, que es donde corresponden: se
    // recomiendan en este espacio Y no piden nada. `worldbank` es el único de los 29.
    const nombres = keyless.map((f) => f.label || f.id)
      .concat(keylessDelCatalogo.map((c) => c.connector || c.slug));
    if (listaAConteo) listaAConteo.textContent = String(nombres.length);
    // SIN BOTONES Y SIN ROTULAR ORIGEN: son etiquetas, separadas por punto medio. Nada de
    // «fuente de Ciencia» ni del nombre del stack que las trajo — para el usuario es de Aleph.
    listaAFilas.textContent = nombres.length
      ? nombres.join(" · ")
      : L("Todavía no hay nada listo sin configurar en este espacio.", "Nothing is ready without configuration in this workspace yet.");
  }

  async function pintar(ws) {
    if (ambito) ambito.textContent = nombreEspacio(ws).toUpperCase();
    filas.innerHTML = `<li class="cx-row">${L("Buscando…", "Searching…")}</li>`;
    // LA LECTURA VIVE EN `recomendaciones.js`. Acá sólo se decide QUÉ DECIR con lo que
    // devolvió — que es el trabajo de esta capa. La causa tipada llega ya separada del
    // número: la regla «la causa siempre con copy» se cumple igual, en el piso que le toca.
    const d = await traerRecomendados(ws, userId);
    if (d && d.error) {
      const { http, causa } = d.error;
      filas.innerHTML = `<li class="cx-row">${L("No pude traer los recomendados", "Could not load recommendations")}${causa ? `: ${esc(causa)}` : (http ? ` (HTTP ${http})` : L(": no hubo respuesta", ": no response"))}.</li>`;
      if (conteo) conteo.textContent = "—";
      return;
    }
    // ── LOS KEYLESS NO VAN EN LA LISTA DE ACCIÓN ────────────────────────────────────
    // Segundo defecto que encontró el dueño mirando: `worldbank` aparecía entre los
    // «Recomendados» y su propia línea dice «sin que pongas ninguna llave». Es el ÚNICO
    // `auth_method: keyless` de los 29 (medido), así que no pertenece a una lista de cosas
    // que configurás: pertenece a «Ya funcionan». Se recomienda igual —eso no cambia— pero
    // en la lista donde no se le pide nada al usuario.
    const todos = d.connectors || [];
    if (aviso) aviso.textContent = userId ? "" : copyDeSinSesion();
    const cs = todos.filter((c) => String(c.auth_method || "").toLowerCase() !== "keyless");
    const yaVan = todos.filter((c) => String(c.auth_method || "").toLowerCase() === "keyless");
    if (conteo) conteo.textContent = String(cs.length);
    // Y SI LA TABLA NO SE PUDO LEER, SE DICE — un 0 con la tabla caída no es «no hay
    // recomendados». Es la lección del `sin_tabla` de F1.
    if (d.tabla && d.tabla !== "catalogo") {
      filas.innerHTML = `<li class="cx-row">${L("No pude leer la tabla de recomendaciones. Esto no quiere decir que no haya: quiere decir que no la pude leer.", "Could not read the recommendation table. This does not mean there are no recommendations; their availability is unknown.")}</li>`;
      return;
    }
    filas.innerHTML = cs.length ? cs.map((c) => {
      const e = estado(c);
      const cruza = tambienEn(c.workspaces, ws);
      // La etiqueta dice UNA de dos cosas y nunca las dos: o está puesta («Listo»), o qué te
      // pide («Pide tu llave» / «Pide autorizar tu cuenta»). Con `tiene_llave === null` no
      // dice ninguna: sin sesión no sabemos si está puesta, y afirmarlo sería la mentira de
      // `connected`.
      const etiqueta = (e.listo === "si" || e.listo === "guardada") ? e.txt
                     : e.listo === "no" ? pide(c.auth_method) : "";
      // EL BOTÓN. Sin esto «Pide tu llave» es una lista de deseos: la vista existe para que
      // el usuario ACTÚE. No se ofrece cuando ya está puesta (no hay nada que hacer) ni
      // cuando no sabemos (sin sesión no hay a nombre de quién guardar).
      // ⚠️ OAUTH NO SE HACE INLINE, Y ESTA VISTA LO ROMPIÓ UNA VEZ. El consentimiento pasa
      // en el sitio del proveedor: la clase `cx-autorizar` es la que `montaje.js:860` ya
      // maneja mandando a `/v1/connectors/<id>/oauth/start`. Antes este botón abría un
      // formulario de contraseña para los 8 OAuth de los 29 — pedía una llave que no existe.
      const esOauth = String(c.auth_method || "").toLowerCase() === "oauth";
      const sello = selloDe(e);
      const accion = e.listo === "no"
        ? (esOauth
            ? `<button class="cx-btn cx-reco-btn cx-autorizar" type="button" data-entity="${esc(c.slug)}">${L("Autorizar", "Authorize")}</button>`
            : `<button class="cx-btn cx-reco-btn" type="button" data-conectar="${esc(c.slug)}">${L("Poner mi llave", "Enter my key")}</button>`)
        : "";
      return pintarFilaReco(c, {
        etiqueta, listo: e.listo, capacidad: capacidad(c.capability_line_i18n || c.capability_line, e.listo === "si"),
        cruzaTxt: [sello, cruza ? `${cruza} ${L("Se configura una vez.", "Configure once.")}` : ""].filter(Boolean).join(" "),
        accion,
      });
    }).join("") : `<li class="cx-row">${L("Este espacio no tiene conectores recomendados.", "This workspace has no recommended connectors.")}</li>`;
    pintarListaA(ws, yaVan);
  }

  /* ── PONER LA LLAVE ────────────────────────────────────────────────────────────────
   * Reusa las dos puertas que ya existen: `GET /v1/connectors/{slug}` para saber QUÉ campos
   * pide, y `POST /v1/connectors/{slug}/connect` para guardar. Ajustes ya las usaba, con
   * `prompt()`; acá es un formulario adentro de la fila.
   *
   * ⚠️ Y SE RESPETAN LOS TRES ESTADOS QUE ESA PUERTA YA DEVUELVE, que es lo que la hace
   * honesta y sería fácil de arruinar aplanándolos a dos:
   *   · `connected`             — guardada Y confirmada contra el proveedor.
   *   · `connected_unverified`  — guardada, y el proveedor NO permite confirmarla acá (Alpha
   *                               Vantage sirve data hasta con una key inexistente). Decirle
   *                               «listo» sería la mentira de `connected`; decirle «no
   *                               conectó» sería falso, porque la llave SÍ se guardó.
   *   · cualquier otro          — no se guardó, y se dice el motivo del servidor.
   * El secreto se escribe en un `type="password"`, no se loguea y no se retiene: se manda y
   * el campo se destruye con el formulario.
   */
  async function abrirForm(slug, host) {
    host.hidden = false;
    host.innerHTML = `<p class='cx-section-copy'>${L("Buscando qué pide…", "Loading requirements…")}</p>`;
    const obj = await traerFicha(slug);
    if (!obj) { host.innerHTML = `<p class='cx-section-copy'>${L("No pude leer qué pide este conector.", "Could not read this connector's requirements.")}</p>`; return; }
    const ficha = lang() === "en" ? { ...obj, ...obj.en } : obj;
    // SE LLAMA, NO SE REESCRIBE. `camposDeCredencial` acepta las tres formas del nombre y
    // trae `secreto` y `forma`; `pintarCampoLlave` es el MISMO campo que usa el catálogo
    // público. La primera versión de esta vista tenía copias peores de las dos.
    const campos = camposDeCredencial(ficha);
    host.innerHTML = `<form data-slug="${esc(slug)}" class="cx-reco-fields">`
      + pintarCampoLlave(campos, { link: obj.deep_link || null, boton: L("Guardar", "Save") })
      + (obj.needs_base_url
          ? `<label><span>${L("Tu dominio", "Your domain")}</span><input type="url" name="__base_url"
               placeholder="https://tu-org.ejemplo.com" required></label>` : "")
      + `<button class="cx-btn" type="button" data-cancelar="1">${L("Cancelar", "Cancel")}</button>
         <p class="cx-section-copy" data-msg style="margin:0"></p></form>`;
  }

  /** OAUTH · SE LLAMA AL VERBO. Acá había un `fetch` propio a `/oauth/start` con su propio
   *  manejo de la respuesta — o sea, un segundo lugar donde vivía el contrato de esa puerta.
   *  `fuentes.empezarOauth` ya existía y ya devuelve `{http, url, motivo}` normalizado; es el
   *  mismo que usa `montaje.js`. Dos clientes del mismo endpoint es cómo terminan
   *  contestando distinto ante el mismo motivo. */
  async function autorizar(slug) {
    if (aviso) aviso.textContent = L("Abriendo la autorización…", "Opening authorization…");
    const r = await empezarOauth(slug);
    if (r.url) { location.href = r.url; return; }   // el consentimiento pasa en el proveedor
    if (aviso) {
      aviso.textContent = r.motivo || L(`No se pudo iniciar la autorización (HTTP ${r.http}).`, `Could not start authorization (HTTP ${r.http}).`);
    }
  }

  /** GUARDAR · POR LA PUERTA DE LA CASA, que es `POST /v1/conexiones/key` → `agregar_key`.
   *
   * ⚠️ ACÁ ESTABA EL DEFECTO DE FONDO DE ESTA VISTA, y no era de copy. Yo mandaba a
   * `POST /v1/connectors/<slug>/connect`, que es el WIZARD del catálogo público. Lo tomé de
   * Ajustes… que es la superficie que esta misma obra declaró duplicada. La puerta de la casa
   * —la que usan Modelos, el Cuarto y el resto de Conectores— es la otra, y trae cuatro cosas
   * que el wizard no tiene:
   *
   *   1. `secret.strip()` (`centro_conexiones.py:1467`). El wizard interpola el valor crudo:
   *      un espacio o un salto pegado viajaban hasta el header.
   *   2. SIN VALIDADOR, GUARDA. `exa` no está en `_KEY_VALIDATORS`, así que por acá cae en
   *      «guardé tu llave cifrada, no la sé validar directo, se confirma en el primer uso».
   *      Por el wizard, el 401 de un endpoint de OTRO producto de Exa se leía como veredicto
   *      sobre la llave — y la llave NI SE GUARDABA. El dueño pegaba y perdía.
   *   3. CAUSAS FINAS con copy: `key_invalida`, `sin_credito`, `rate_limit`, `sin_red`,
   *      `timeout` — cada una con su frase. El wizard aplana todo a `errors.invalid`.
   *   4. `guardar_igual`: cuando la llave NO tiene la culpa (sin saldo, límite, red), se
   *      ofrece guardarla igual en vez de hacerte re-pegarla.
   *
   * Y no hace falta disparar la verificación acá: `agregar_key` siembra el motor y corre
   * `verificar_uno` detrás del response. El verbo ya trae eso puesto. */
  async function guardar(form, host, { guardarIgual = false } = {}) {
    const slug = form.dataset.slug;
    const msg = form.querySelector("[data-msg]");
    if (!userId) { msg.textContent = L("Necesito tu sesión para guardar la llave a tu nombre.", "Your session is required to save the key for you."); return; }
    const creds = {};
    let base_url = null;
    for (const el of form.querySelectorAll("input")) {
      if (el.name === "__base_url") base_url = el.value.trim();
      else creds[el.name] = el.value;           // NO se loguea ni se guarda en ninguna variable de módulo
    }
    // Un campo → el valor; varios → el objeto, que el verbo serializa igual que el otro
    // camino. No se elige «cuál es el secreto» desde acá: eso sería una decisión de UI sobre
    // un dato del catálogo.
    const claves = Object.keys(creds);
    const valor = claves.length === 1 ? creds[claves[0]] : creds;
    msg.textContent = L("Guardando…", "Saving…");
    let r = null;
    try {
      // `base_es_validador: false` — la dirección que pide este formulario sale de
      // `needs_base_url` del catálogo: es el dominio del usuario, no una API contra la
      // cual probar la llave. Ver el docstring de `agregar_key`.
      r = await guardarLlave(slug, valor, { base_url, guardar_igual: guardarIgual,
                                            base_es_validador: false });
    } catch (e) {
      msg.textContent = L("No hubo respuesta del servidor. La llave no se guardó.", "No response from the server. The key was not saved.");
      return;
    }
    if (r && r.guardada) {
      host.hidden = true; host.innerHTML = "";     // el formulario se destruye con el secreto adentro
      await pintar(selector.value);                // relee: el estado sale del servidor, no de acá
      if (aviso && r.mensaje) aviso.textContent = r.mensaje;
      return;
    }
    // NO SE GUARDÓ · el mensaje del servidor ya viene redactado por causa (§ agregar_key).
    msg.textContent = (r && r.mensaje) || L("No se pudo guardar. La llave no quedó guardada.", "Could not save the key. It remains unsaved.");
    // LA LLAVE NO SIEMPRE TIENE LA CULPA. Sin saldo, límite del proveedor o sin red no dicen
    // nada de la credencial, y hacerte re-pegarla por eso es castigarte por un problema ajeno.
    const AJENAS = ["sin_credito", "rate_limit", "sin_red", "timeout"];
    if (r && AJENAS.includes(String(r.causa)) && !guardarIgual) {
      // DELEGADO, no un listener sobre un botón recién creado: ese botón se pinta y se
      // repinta con la fila, y un listener por instancia es exactamente lo que la ley de
      // `montaje.js` prohíbe — «perder uno es un botón muerto que nadie nota».
      msg.insertAdjacentHTML("beforeend",
        `<br><button type="button" class="cx-btn" data-guardar-igual="1">${L("Guardar igual", "Save anyway")}</button>`);
    }
  }

  /* ── LO QUE PASA AL TOCAR · expuesto, NO atado ──────────────────────────────────────
   *
   * ⚠️ ACÁ HABÍA DOS `addEventListener` SOBRE `filas` Y UNO SOBRE EL SELECTOR. Cumplían la
   * ley de delegación —uno por host, no uno por fila— pero vivían en el piso equivocado:
   * `montaje.js` es EL que conecta nodos y clicks, y tener una vista que se ata sola es
   * cómo se llega a dos lugares que deciden qué hace un click. Las funciones siguen acá
   * (saben del estado de esta vista y de nadie más); quien las ata es montaje.
   *
   * Y siguen siendo delegadas: montaje ata UN listener al host y estas leen el `ev`. */
  function alClick(ev) {
    const a = ev.target.closest(".cx-autorizar");
    if (a) { ev.preventDefault(); autorizar(a.getAttribute("data-entity")); return; }
    const b = ev.target.closest("[data-conectar]");
    if (b) {
      const slug = b.getAttribute("data-conectar");
      const host = filas.querySelector(`[data-form="${slug}"]`);
      if (host) { if (host.hidden) abrirForm(slug, host); else { host.hidden = true; host.innerHTML = ""; } }
      return;
    }
    const gi = ev.target.closest("[data-guardar-igual]");
    if (gi) {
      ev.preventDefault();
      const f = gi.closest("form");
      if (f) guardar(f, f.closest("[data-form]"), { guardarIgual: true });
      return;
    }
    const g = ev.target.closest("[data-traer-con-llave]");
    if (g) { ev.preventDefault(); const f = g.closest("form"); if (f) guardar(f, f.closest("[data-form]")); return; }
    if (ev.target.closest("[data-cancelar]")) {
      const host = ev.target.closest("[data-form]");
      if (host) { host.hidden = true; host.innerHTML = ""; }
    }
  }

  function alSubmit(ev) {
    const form = ev.target.closest("form[data-slug]");
    if (!form) return;
    ev.preventDefault();
    guardar(form, form.closest("[data-form]"));
  }

  const wss = opciones.workspaces || Object.keys(ORDEN_ETIQUETA);
  selector.innerHTML = wss.map((w) =>
    `<option value="${esc(w)}">${esc(nombreEspacio(w))}</option>`).join("");
  // El `change` del selector también lo ata montaje: es un nodo, y los nodos son suyos.

  let listo = false;
  let vistaAbierta = false;
  return {
    // LAS TRES ACCIONES, para que montaje las ate a los hosts. La vista dice QUÉ pasa; el
    // adaptador dice DÓNDE se escucha.
    alClick, alSubmit,
    alCambiarEspacio() { return pintar(selector.value); },
    /** La sesión, cuando `ensureLocal()` resuelve. Si la vista ya estaba abierta se repinta:
     *  el usuario no tiene por qué volver a hacer clic para que aparezca el botón. */
    sesion(u) {
      userId = (u && u.id) ? u.id : null;
      if (vistaAbierta) pintar(selector.value || wss[0]);
    },
    async ir() {
      vistaAbierta = true;
      if (!listo) { await traerFuentes(); listo = true; }
      await pintar(selector.value || wss[0]);
    },
  };
}
