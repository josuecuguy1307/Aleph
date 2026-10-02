/* modelos.ui.js — MODELOS V2 · BUSCAR vs CONFIGURAR.
 *
 * La lista es una tabla visual de filas constantes. Elegir jamás expande una card: abre
 * un único panel lateral con el flujo de ESE modelo. HF es sólo descarga local; el browser
 * habla exclusivamente con el sidecar.
 */
import * as API from "./modelos.api.js";
import * as CX from "../conexiones/centro.api.js";
import M from "./modelos.semaforo.js";
// [F7 · obra 3] LAS DOS CAPAS DE F4c, POR FIN MONTADAS. Estaban escritas, verificadas y
// viajando en el bundle desde el 2026-08-04; la única referencia en todo el repo era su
// propia vara. `W` DERIVA (pertenencia · caducidad · censo) y `S` PINTA (funciones puras).
import * as W from "./modelos.widget.js";
import * as S from "./modelos.superficie.js";

const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => [...(r || document).querySelectorAll(s)];
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function en() {
  try { return String((window.AlephI18n && AlephI18n.lang && AlephI18n.lang()) || "es").startsWith("en"); }
  catch (e) { return false; }
}
const L = (es, ingles) => en() ? ingles : es;

function textoVisible(value) {
  const raw = String(value == null ? "" : value).trim();
  if (!raw) return "";
  try {
    const traducido = window.AlephI18n && window.AlephI18n.text
      ? window.AlephI18n.text(raw)
      : raw;
    return traducido || raw;
  } catch (e) {
    return raw;
  }
}

const ST = {
  filas: [], categorias: [], maquina: null, preferencias: {}, conteo: {}, contrato: {},
  origen: "todos", categoria: "todas", texto: "", seleccion: null, descarga: null,
  requestsListado: 0, cargando: false,
  // [F8 · obra 3] Flag DE UN SOLO USO: el deep-link `?catalogo=1` pidió que el panel abra
  // con el catálogo desplegado. No lleva slug —de qué fila se abre ya lo decide
  // `aplicarFoco()` con `?m=`— y `pintarPanel` lo apaga apenas lo lee, para que no quede
  // armado esperando al próximo panel que alguien abra a mano.
  abrirCatalogo: false,
  // [F7] las filas cuya medición vencida ya estamos re-midiendo. Sin esto, la caducidad
  // es un loop: pintar dispara medir, medir dispara pintar.
  midiendo: new Set(),
};
export function estado() { return ST; }

// ── caras ────────────────────────────────────────────────────────────────────────
window.__mdIniciales = function (label, size) {
  const n = document.createElement("span");
  n.className = "bface binit md-face";
  n.style.width = n.style.height = (size || 22) + "px";
  n.textContent = String(label || "?").replace(/[^A-Za-z0-9]/g, "").slice(0, 2).toUpperCase() || "?";
  return n;
};

export function cara(f, size) {
  size = size || 22;
  const AB = window.AlephBrand;
  const d = { slug: (f && f.marca) || "", connector: (f && f.marca) || "", label: (f && f.label) || "" };
  if (AB && AB.faceHTML) return AB.faceHTML(d, { size, cls: "md-face" });
  return window.__mdIniciales(d.label, size).outerHTML;
}

export function esFallback(f) {
  const AB = window.AlephBrand;
  return !(AB && AB.has && AB.has({ slug: (f && f.marca) || "", connector: (f && f.marca) || "" }));
}

function eDe(f) { return M.ESTADO[f.estado] || M.ESTADO.detectado; }

function estadoAuthVisible(f) {
  if (!f || f.familia !== "cli" || !f.sesion_cli) return "";
  const auth = String(f.sesion_cli.auth_state || "");
  if (auth === "expired") return L("Sesión vencida", "Session expired");
  if (auth === "not_authenticated") return L("Sin iniciar sesión", "Not signed in");
  if (auth === "unknown") return L("Sesión sin verificar", "Session unverified");
  return "";
}

function sesionExpirada(f) {
  return !!(f && f.familia === "cli" && f.sesion_cli && f.sesion_cli.auth_state === "expired");
}

export function textoEstado(f) {
  const authLabel = estadoAuthVisible(f);
  if (authLabel) return authLabel;
  if (f.hf) {
    const v = f.veredicto;
    const texto = v && (en() ? v.en : v.es);
    return texto || L("Veredicto no disponible", "Verdict unavailable");
  }
  const e = eDe(f);
  if (f.estado === "probado" && f.prueba && f.prueba.ts)
    return (en() ? e.en : e.es) + " " + textoVisible(M.Sem.haceRato(f.prueba.ts));
  if (f.estado === "roto" && f.causa)
    return (en() ? e.en : e.es) + " · " + M.textoCausa(f.causa, en()).toLowerCase();
  return en() ? e.en : e.es;
}

export function caminoFila(f) {
  return M.caminoModelo({ estado: f.estado, causa: f.causa || null });
}

export function imposibleDe(f, cam) {
  if (!f || !cam) return null;
  if (f.hf && !veredictoUtil(f)) return L("falta el veredicto del lote", "batch verdict is missing");
  if (f.hf && (f.veredicto || {}).veredicto === "no_entra")
    return en() ? f.veredicto.en : f.veredicto.es;
  return null;
}

export function roles(f) {
  const caps = (f && (f.categorias || f.capacidades)) || [];
  return caps.map((id) => ({ id, es: id, puede: true }));
}

function tierVisible(tier) {
  tier = String(tier || "").toLowerCase();
  if (tier === "frontier") return "FRONTIER";
  if (tier === "grande") return "GRANDE";
  return "MEDIO";
}

function origenVisible(f) {
  if (f.hf) return "HF";
  if (f.local) return "LOCAL";
  if (f.familia === "incluido") return L("INCLUIDO", "INCLUDED");
  return String(f.familia || "").toUpperCase();
}

function veredictoUtil(f) {
  const v = f && f.veredicto;
  const tipo = v && v.veredicto;
  return (tipo === "comodo" || tipo === "justo" || tipo === "no_entra")
    && !!String(v.es || "").trim() && !!String(v.en || "").trim();
}

/* [F7 · obra 3] `filaHTML` SE RETIRA. Era el renderer viejo de la fila y su reemplazo es
 * `modelos.superficie.js::filaLocalHTML` / `filaAduanaHTML` — «gana el adaptador, la UI
 * vieja se retira», el mismo camino de Gate 1. Nada de lo que mostraba se perdió: la cara,
 * el badge de Default, el tier y el veredicto de la máquina viajan ahora por `derivar()`
 * hasta la superficie, que es una función pura y por eso se puede verificar sin browser. */

function coincide(f) {
  if (ST.origen !== "todos" && (f.origen || f.familia) !== ST.origen) return false;
  if (ST.origen === "hf_local" && ST.categoria !== "todas") {
    const cats = f.categorias || [f.categoria];
    if (!cats.includes(ST.categoria)) return false;
  }
  const q = ST.texto.toLowerCase();
  if (q && ![f.label, f.ref, f.marca, f.tier, ...(f.categorias || [])]
    .join(" ").toLowerCase().includes(q)) return false;
  return true;
}

/* ══ LA LISTA · LA PINTA EL ADAPTADOR (F7 · obra 3) ══════════════════════════════════
 *
 * `modelos.widget.js` (DERIVA) y `modelos.superficie.js` (PINTA) son de F4c, viajaban en
 * el bundle desde el 2026-08-04 y **nadie los importaba**: la única referencia en todo el
 * repo era su propia vara. Acá se montan, y con eso entran las cuatro obras que estaban
 * construidas y no llegaban a la pantalla:
 *
 *   · pertenencia → «Tus modelos» vs la ADUANA 2.5, con su trámite
 *   · el [?] con la EVIDENCIA y su fecha (verde con prueba, no verde a secas)
 *   · el contador HONESTO — «5 · 2 andando», no un 5 que promete cinco
 *   · la caducidad como GATILLO: lo rancio se re-mide, no se etiqueta
 *
 * Lo que esta capa conserva es lo que el adaptador no tiene opinión sobre: el buscador,
 * los filtros de origen y categoría, el panel de la máquina y el panel lateral por modelo.
 * Eso no es conflicto — es que son capas distintas.
 */
export function pintarLista() {
  const host = $("#mdFilas");
  if (!host) return;
  const visibles = ST.filas.filter(coincide);
  const ahora = Date.now();
  const opciones = { ahora, en: en(), textoVisible,
    caraHTML: (d) => cara(filaDe(d.slug) || d, 22) };
  if (!visibles.length) {
    host.innerHTML = `<p class="md-vacio">${L("No hay modelos con esos filtros.", "No models match those filters.")}</p>`;
  } else {
    host.innerHTML = S.pantallaHTML(visibles, opciones);
  }
  const censo = W.censo(visibles, opciones);
  const c = $("#mdConteo");
  if (c) c.textContent = L(`${visibles.length} de ${ST.filas.length}`, `${visibles.length} of ${ST.filas.length}`);
  pintarResumen(censo);
  medirLoQueFalta();
}

/* ── LOS CLICKS · DELEGADOS, UNO POR ACCIÓN ────────────────────────────────────────
 * Un `addEventListener` por fila significa re-atarlos en cada repintado y, cuando alguno
 * se olvida, un botón que existe en el HTML y no responde. El molde delega
 * (`conectores/montaje.js:23`); acá también. Se ata UNA vez, en `montar()`.
 */
async function alClickLista(ev) {
  const t = ev.target.closest("button");
  if (!t) {
    // [F7] LA FILA ENTERA ABRE SU PANEL. `.md-fila` declara `cursor:pointer` desde
    // siempre y NINGÚN click llegaba a ninguna parte: se anunciaba clickeable y no lo era.
    // El campo inline de la llave se excluye — ahí el click es para escribir.
    if (ev.target.closest("input, label, a")) return;
    const li = ev.target.closest(".md-fila");
    if (li && li.dataset.slug) return abrirPanel(li.dataset.slug);
    return;
  }
  const d = t.dataset || {};
  const slug = d.slug || d.ref || "";
  const f = slug ? (filaDe(slug) || ST.filas.find((x) => x.ref === slug)) : null;

  if (d.abrir) { ev.preventDefault(); return abrirPanel(d.abrir); }
  if (!f) return;

  // El [?] es el gesto uniforme: abre la EVIDENCIA. El `title` ya la lleva para el hover,
  // pero un hover no es un camino — en táctil no existe.
  if (t.classList.contains("md-ayuda")) { ev.preventDefault(); return abrirPanel(f.slug); }

  // TODA ACCIÓN DE UNA FILA ABRE SU PANEL, que es donde vive el trámite completo con su
  // guard. En particular `descargar` NO arranca desde acá: el panel de HF bloquea el botón
  // cuando el veredicto dice `no_entra`, y saltear el panel saltearía ese guard.
  if (t.classList.contains("md-tramite") || t.classList.contains("md-camino")) {
    ev.preventDefault();
    return abrirPanel(f.slug);
  }
}

/* ── LO INTERNO SE ARREGLA SOLO · la caducidad es un GATILLO, no una etiqueta ───────
 *
 * [F7 · obra 3] `medicionRancia()` existía en `modelos.widget.js` desde F4c y **no
 * disparaba nada**: medido el 2026-08-06, el Default de la app llevaba 27,9 h con un TTL
 * de 24 h y pintaba verde plano. Ahora una medición vencida genera trabajo NUESTRO, no un
 * botón para el usuario: se re-mide en background y la fila se repinta con el resultado.
 *
 * Tres cuidados, los tres por un modo de fallo concreto (calcados de
 * `conectores/montaje.js::medirLoQueFalta`):
 *   · UNA VEZ POR CARGA (`ST.midiendo`): si no, es un loop que nunca converge;
 *   · SILENCIOSO: si la re-medición falla, la fila queda como estaba. Un error de NUESTRA
 *     medición no puede convertirse en un rojo sobre el modelo del usuario;
 *   · SIN BLOQUEAR: no se espera. La pantalla ya está pintada con lo último que se sabe.
 */
function medirLoQueFalta() {
  const pendientes = ST.filas.filter((f) =>
    f.conectado && W.medicionRancia(f) && !ST.midiendo.has(f.slug));
  if (!pendientes.length) return;
  for (const f of pendientes) ST.midiendo.add(f.slug);
  Promise.all(pendientes.map((f) => API.checklistEnVivo([f.ref], () => {}).catch(() => null)))
    .then((res) => { if (res.some(Boolean)) return cargar({ silencioso: true }); })
    .catch(() => { /* silencioso a propósito: ver el docstring */ });
}

/* ★★★ EL RESUMEN SE DERIVA DE LAS MISMAS FILAS QUE LA LISTA — no de una fuente paralela.
 *
 * EL BUG MEDIDO EN LA APP (2026-08-07): la cabecera decía **CONECTADOS 2 · LISTOS 2** y
 * ninguna fila de API lo respaldaba; los dos verdes eran CLIs. Y **DEFAULT: Groq en ROJO**
 * mientras la fila de Groq estaba en AMARILLO («sin probar»).
 *
 * La causa: cada número salía de un lugar distinto.
 *   · CONECTADOS ← `preferencias.conectados`, la LISTA DEL ARCHIVO — una fuente paralela que
 *     se escribe en otro momento y puede quedar de otra época.
 *   · DEFAULT rojo ← `!def.conectado`, un booleano crudo, sin pasar por el semáforo.
 *   · ROTOS ← `f.estado === "roto"`, el estado INTERNO, no lo que la fila muestra.
 *
 * Ahora los cuatro salen del censo, que son LAS MISMAS FILAS DERIVADAS que se pintan abajo,
 * con su `semaforo`. Si la cabecera y la lista discrepan, es porque miran cosas distintas —
 * así que miran la misma. */
function pintarResumen(censo) {
  const filas = [...((censo || {}).local || []), ...((censo || {}).aduana || [])];
  const pref = ST.preferencias || {};
  const def = filas.find((d) => d.slug === pref.default);
  const d = $("#mdResumenDefault");
  if (d) {
    d.textContent = def ? (def.label || def.slug) : L("Sin definir", "Not set");
    // El TONO del Default es el de SU PROPIA FILA. Rojo sólo si la fila está roja; si dice
    // «sin probar», el Default dice «sin probar» — no puede estar más roto que su fila.
    const tono = def && def.semaforo ? def.semaforo.tono : null;
    d.className = "md-r-v" + (tono === "mal" ? " bad" : tono === "tibia" ? " amber" : "");
  }
  // CONECTADOS = las filas que la lista muestra como conectadas. Ni más ni menos.
  // CONECTADOS = el campo ÚNICO del backend, contado. No se re-deriva de requisitos: eso
  // fue lo que dio «7», contando locales que ni siquiera están descargados.
  if ($("#mdResumenConectados"))
    $("#mdResumenConectados").textContent = String(filas.filter((f) => f.conectado).length);
  // [F7] EL CONTADOR DICE LA VERDAD: los VERDES exigen prueba con fecha. Un «Listos: 3» que
  // incluye un modelo que nadie midió es la clase de número que hace que nadie vuelva a
  // creerle a un contador.
  if ($("#mdResumenListos")) $("#mdResumenListos").textContent = String((censo || {}).n_verdes || 0);
  if ($("#mdResumenRotos")) {
    // ROTOS = las que la lista PINTA rojas, no las que tienen `estado === "roto"` adentro.
    const n = filas.filter((f) => f.semaforo && f.semaforo.tono === "mal").length;
    $("#mdResumenRotos").textContent = String(n);
    $("#mdResumenRotos").className = "md-r-v" + (n ? " bad" : "");
  }
}

function pintarCategorias() {
  const host = $("#mdCategorias");
  if (!host) return;
  // La vara es literal: fuera de HF/local, el filtro NO existe visualmente.
  host.hidden = ST.origen !== "hf_local";
  if (host.hidden) return;
  const cats = [{ id: "todas", es: "Todas", en: "All" }].concat(ST.categorias || []);
  host.innerHTML = `<span class="md-filter-label">${L("Categoría", "Category")}</span>` +
    cats.map((c) => `<button type="button" class="md-cat${c.id === ST.categoria ? " on" : ""}"
      data-cat="${esc(c.id)}">${esc(en() ? c.en : c.es)}</button>`).join("");
  $$(".md-cat", host).forEach((b) => {
    b.onclick = () => { ST.categoria = b.dataset.cat; pintarCategorias(); pintarLista(); };
  });
}

function pintarMaquina() {
  const host = $("#mdMaquina");
  if (!host) return;
  host.hidden = ST.origen !== "hf_local";
  if (host.hidden || !ST.maquina) return;
  const q = ST.maquina;
  const discoPct = q.disco_total_gb && q.disco_libre_gb != null
    ? Math.max(0, Math.min(100, Math.round(100 * q.disco_libre_gb / q.disco_total_gb))) : 0;
  const ramPct = q.ram_total_gb && q.ram_libre_gb
    ? Math.max(0, Math.min(100, Math.round(100 * q.ram_libre_gb / q.ram_total_gb))) : 0;
  host.innerHTML = `
    <div class="md-recurso"><b>${L("Disco libre", "Free disk")}</b>
      <span class="md-resource-bar"><span class="md-resource-in" style="width:${discoPct}%"></span></span>
      <span>${q.disco_libre_gb != null ? q.disco_libre_gb + " GB" : "—"}</span></div>
    <div class="md-recurso"><b>${L("RAM libre", "Free RAM")}</b>
      <span class="md-resource-bar"><span class="md-resource-in" style="width:${ramPct}%"></span></span>
      <span>${q.ram_libre_gb != null ? q.ram_libre_gb + " GB" : "—"}</span></div>`;
}

function elegirOrigen(origen) {
  ST.origen = origen;
  if (origen !== "hf_local") ST.categoria = "todas";
  $$("#mdOrigen .md-switch").forEach((b) => b.classList.toggle("on", b.dataset.origin === origen));
  pintarCategorias();
  pintarMaquina();
  pintarLista();
}

// ── panel lateral ────────────────────────────────────────────────────────────────
function filaDe(slug) { return ST.filas.find((f) => f.slug === slug); }

function abrirPanel(slug) {
  const f = filaDe(slug);
  if (!f) return;
  ST.seleccion = f.slug;
  $("#mdPanel").hidden = false;
  $("#mdPanelBack").hidden = false;
  $("#mdPanelTitulo").textContent = f.label;
  actualizarResumenPanel(f);
  $("#mdPanelFace").innerHTML = cara(f, 22);
  pintarPanel(f);
}

function actualizarResumenPanel(f) {
  const sub = $("#mdPanelSub");
  if (sub) sub.textContent = `${origenVisible(f)} · ${tierVisible(f.tier)} · ${textoEstado(f)}`;
}
export const abrirFila = abrirPanel; // compatibilidad nominal: ahora abre overlay, nunca expande

function cerrarPanel() {
  if (ST.descarga) return;
  ST.seleccion = null;
  $("#mdPanel").hidden = true;
  $("#mdPanelBack").hidden = true;
  const body = $("#mdPanelBody");
  if (body) body.replaceChildren(); // una llave pegada no queda viva detrás del overlay
}

function flowEstado(f) {
  const e = eDe(f);
  const authCli = f.familia === "cli" && f.sesion_cli ? f.sesion_cli.auth_state : "";
  const causa = f.causa && !["expired", "not_authenticated", "unknown"].includes(authCli)
    ? `<p>${esc(M.textoCausa(f.causa, en()))}</p>` : "";
  const expired = sesionExpirada(f);
  const glifo = expired ? "⚠" : authCli === "unknown" ? "🟡" : e.g;
  return `<section class="md-flow-card">
    <h3>${glifo} ${esc(textoEstado(f))}</h3>${causa}
    ${f.prueba && f.prueba.detalle ? `<p>${esc(textoVisible(f.prueba.detalle))}</p>` : ""}
  </section>`;
}

function defaultAction(f) {
  if (!f.conectado || f.default) return "";
  return `<button type="button" class="md-btn md-default">${L("Definir como Default", "Make Default")}</button>`;
}

function pintarPanel(f) {
  const host = $("#mdPanelBody");
  if (!host) return;
  // [F8 · obra 3] El pedido de «abrí el catálogo» se LEE Y SE APAGA acá, en el único lugar
  // por donde pasan todos los paneles. Dejarlo prendido haría que el catálogo se abriera
  // solo la próxima vez que alguien abra un panel de API, sin haberlo pedido.
  const pedirCatalogo = ST.abrirCatalogo === true;
  ST.abrirCatalogo = false;
  if (f.hf) return pintarPanelHf(f, host);
  if (f.local) return pintarPanelLocal(f, host);
  if (f.familia === "api") return pintarPanelApi(f, host, pedirCatalogo);
  if (f.familia === "cli") return pintarPanelCli(f, host);
  return pintarPanelIncluido(f, host);
}

function wireDefault(f, host) {
  const b = $(".md-default", host);
  if (!b) return;
  b.onclick = async () => {
    b.disabled = true;
    try {
      ST.preferencias = await API.guardarPreferencias({ default: f.slug });
      f.default = true;
      aviso("ok", L(`${f.label} es el nuevo Default.`, `${f.label} is the new Default.`));
      cerrarPanel();
      await cargar({ silencioso: true });
    } catch (e) {
      aviso("bad", String(e && e.message || e));
    } finally { b.disabled = false; }
  };
}

function pintarPanelIncluido(f, host) {
  host.innerHTML = `<div class="md-flow">${flowEstado(f)}
    <section class="md-flow-card"><h3>${L("Ruta incluida", "Included route")}</h3>
      <p>${esc(f.sub || L("Viene con Aleph.", "Comes with Aleph."))}</p></section>
    <div class="md-actions">
      <button type="button" class="md-btn primario md-probar-host">${L("Comprobar conexión", "Check connection")}</button>
      ${defaultAction(f)}
    </div><div class="md-flow-result"></div></div>`;
  $(".md-probar-host", host).onclick = () => probarHost(f, host);
  wireDefault(f, host);
}

function pintarPanelCli(f, host) {
  const ses = f.sesion_cli || {};
  const svc = f.servicio_cli || {};
  const okSes = ses.auth_state === "authenticated", okSvc = svc.state === "ready";
  const expired = ses.auth_state === "expired";
  const acceso = ses.access_state === "denied"
    ? L("Acceso de suscripción denegado por el proveedor", "Provider denied subscription access")
    : ses.access_state === "allowed"
      ? L("Acceso al proveedor verificado", "Provider access verified")
      : L("Acceso al proveedor aún no probado", "Provider access not tested yet");
  const providerId = String(f.ref || f.slug || "").replace(/^cli\./, "");
  host.innerHTML = `<div class="md-flow">${flowEstado(f)}
    <section class="md-flow-card"><h3>${L("Checklist de tu CLI", "Your CLI checklist")}</h3>
      <div class="md-check"><i>${ses.installed === false ? "○" : "✓"}</i><span>${L("Programa instalado", "Program installed")}</span></div>
      <div class="md-check"><i>${okSes ? "✓" : expired ? "⚠" : "○"}</i><span>${esc(okSes ? L("Sesión autenticada", "Authenticated session") : textoVisible(ses.detail || L("Sesión no verificada", "Session unverified")))}</span></div>
      <div class="md-check"><i>${ses.access_state === "denied" ? "✕" : ses.access_state === "allowed" ? "✓" : "○"}</i><span>${esc(acceso)}</span></div>
      <div class="md-check"><i>${okSvc ? "✓" : "○"}</i><span>${esc(textoVisible(svc.detail || L("Servicio local no verificado", "Local service unverified")))}</span></div>
      <div class="md-check"><i>${okSes && ses.last_test_state === "passed" ? "✓" : "○"}</i><span>${esc(expired ? L("Ejecución bloqueada hasta volver a iniciar sesión", "Execution blocked until you sign in again") : ses.last_test_state === "passed" ? L("Ejecución verificada", "Execution verified") : L("Ejecución no verificada", "Execution not verified"))}</span></div>
    </section>
    <section class="md-flow-card"><h3>${L("Ejecutable local", "Local executable")}</h3>
      <div class="md-check"><label><input type="radio" name="md-cli-mode" class="md-cli-auto" checked> ${L("Detectar automáticamente", "Detect automatically")}</label></div>
      <div class="md-check"><label><input type="radio" name="md-cli-mode" class="md-cli-manual"> ${L("Elegir ruta manual", "Choose a manual path")}</label></div>
      <div class="md-field"><label>${L("Ruta del ejecutable", "Executable path")}</label><input class="md-cli-path" type="text" autocomplete="off" spellcheck="false" disabled></div>
      <p class="md-cli-resolution" style="overflow-wrap:anywhere;margin-top:8px">${L("Consultando ruta…", "Checking path…")}</p>
      <div class="md-actions"><button type="button" class="md-btn md-cli-browse">${L("Elegir…", "Browse…")}</button><button type="button" class="md-btn md-cli-verify">${L("Verificar y guardar", "Verify and save")}</button><button type="button" class="md-btn md-cli-reset">${L("Restablecer auto", "Reset to auto")}</button></div>
      <p class="md-cli-message" role="status" aria-live="polite"></p>
    </section>
    <div class="md-actions">
      <button type="button" class="md-btn primario md-probar-host">${providerId === "claude_cli" ? L("Revisar sesión", "Recheck session") : L("Volver a comprobar", "Check again")}</button>
      ${defaultAction(f)}
    </div><div class="md-flow-result"></div></div>`;
  $(".md-probar-host", host).onclick = providerId === "claude_cli"
    ? (event) => conBoton(event.currentTarget, async () => {
        const out = $(".md-flow-result", host);
        try {
          const status = await API.revalidarClaude(); // sólo `claude auth status`; ningún turno/modelo
          const fresh = ST.filas.find((row) => row.slug === f.slug);
          if (fresh) {
            fresh.sesion_cli = status.providers?.[providerId] || fresh.sesion_cli;
            fresh.servicio_cli = status.service || fresh.servicio_cli;
            fresh.estado = fresh.sesion_cli?.state === "ready" && fresh.servicio_cli?.state === "ready"
              ? "probado" : "detectado";
            fresh.causa = null;
            pintarLista();
            if (ST.seleccion === f.slug) {
              actualizarResumenPanel(fresh);
              pintarPanel(fresh);
            }
          }
        } catch (e) {
          if (out) out.textContent = String(e?.message || e);
        }
      })
    : () => probarHost(f, host);
  const path = $(".md-cli-path", host), auto = $(".md-cli-auto", host), manual = $(".md-cli-manual", host);
  const message = $(".md-cli-message", host);
  const applyMode = () => { path.disabled = !manual.checked; $(".md-cli-browse", host).disabled = !manual.checked; };
  auto.onchange = async () => {
    if (!auto.checked) return;
    await conBoton(auto, async () => {
      try { await API.guardarEjecutableCli(providerId, "auto"); message.textContent = L("Detección automática guardada.", "Automatic detection saved."); await cargarEjecutableCli(); }
      catch (e) { message.textContent = String(e?.message || e); }
    });
  };
  manual.onchange = applyMode;
  $(".md-cli-browse", host).onclick = async () => {
    try {
      const selected = await window.__TAURI__?.core?.invoke?.("choose_cli_executable");
      if (selected) path.value = selected;
      else if (!window.__TAURI__?.core?.invoke) message.textContent = L("Escribe una ruta absoluta.", "Enter an absolute path.");
    } catch { message.textContent = L("El selector no está disponible; escribe la ruta.", "The chooser is unavailable; enter the path."); }
  };
  $(".md-cli-verify", host).onclick = (event) => conBoton(event.currentTarget, async () => {
    if (!manual.checked) { await cargarEjecutableCli(); return; }
    try {
      await API.verificarEjecutableCli(providerId, path.value.trim());
      await API.guardarEjecutableCli(providerId, "manual", path.value.trim());
      message.textContent = L("Ejecutable verificado y guardado.", "Executable verified and saved.");
      await cargarEjecutableCli();
    } catch (e) { message.textContent = String(e?.message || e); }
  });
  $(".md-cli-reset", host).onclick = (event) => conBoton(event.currentTarget, async () => {
    try { await API.guardarEjecutableCli(providerId, "auto"); message.textContent = L("Detección automática restaurada.", "Automatic detection restored."); await cargarEjecutableCli(); }
    catch (e) { message.textContent = String(e?.message || e); }
  });
  async function cargarEjecutableCli() {
    try {
      const data = await API.ejecutablesCli();
      if (!path.isConnected) return;
      const choice = data.providers?.[providerId] || {};
      manual.checked = choice.mode === "manual"; auto.checked = !manual.checked;
      path.value = choice.mode === "manual" ? choice.path || "" : choice.resolved_path || "";
      applyMode();
      $(".md-cli-resolution", host).textContent = choice.configuration_error ||
        `${L("Ruta resuelta", "Resolved path")}: ${choice.resolved_path || L("no encontrada", "not found")}`;
    } catch (e) { if (path.isConnected) $(".md-cli-resolution", host).textContent = String(e?.message || e); }
  }
  cargarEjecutableCli();
  wireDefault(f, host);
}

/** Un botón que no cambia al apretarlo se ve como uno que no funcionó, y el usuario lo
 *  aprieta otra vez. Se deshabilita mientras dura y vuelve solo — incluso si el trabajo
 *  revienta, que es justo cuando más importa que el botón vuelva. (Molde:
 *  `conectores/montaje.js::conBoton`.) */
async function conBoton(b, trabajo) {
  if (!b) return trabajo();
  b.disabled = true;
  b.dataset.trabajando = "1";
  try { return await trabajo(); }
  finally { b.disabled = false; delete b.dataset.trabajando; }
}

/* ── COMPROBAR = CORRER EL CHECKLIST, Y PINTAR LO QUE DECIDIÓ ──────────────────────
 *
 * [F7 · obra 2] Antes esto sólo miraba `resultado.ok` y, si era true, escribía «probado».
 * El cable ya trae el veredicto tipado en `fila.cerrada` {estado, causa}: usarlo es la
 * diferencia entre pintar lo que el checklist decidió y pintar lo que el llamador supuso.
 * Un checklist que cierra en 🟡 «detectado» ahora se ve 🟡, no verde.
 */
async function probarHost(f, host, boton) {
  const b = boton || $(".md-probar-host", host), out = $(".md-flow-result", host);
  if (out) out.innerHTML = `<div class="md-aviso"><span class="md-spin"></span> ${L("Comprobando…", "Checking…")}</div>`;
  let cierre = null;
  try {
    await conBoton(b, () => CX.correrChecklist([f.slug], (ev) => {
      if (!ev) return;
      if (ev.type === "fila.cerrada") cierre = ev;
      if (out && ev.type === "requisito.resultado")
        out.innerHTML = `<div class="md-aviso">${esc(ev.detalle || ev.estado || "")}</div>`;
    }, {}));
    if (!cierre)
      throw new Error(L("La comprobación no llegó a cerrar.", "The check never closed."));
    // ⚠️ NO SE INVENTA PROSA ACÁ. El detalle provisorio sirve mientras la lista recarga;
    // apenas vuelve, `aplicarVeredicto` reescribe el banner con lo que DICE LA FILA. Que
    // este texto y el de la lista se decidieran por separado es como se llegó a un banner
    // en verde con cero verdes.
    await aplicarVeredicto(f, {
      estado: cierre.estado, causa: cierre.causa,
      detalle: M.textoCausa(cierre.causa, en()) || null,
    });
  } catch (e) {
    if (out) out.innerHTML = `<div class="md-aviso bad">${esc(String(e && e.message || e))}</div>`;
  }
}

const API_HINT = {
  anthropic: "sk-ant-…", openai: "sk-…", openrouter: "sk-or-…",
  groq: "gsk_…", deepseek: "sk-…", mistral: "…", together: "…", gemini: "AIza…",
};

/* ══ EL PANEL DE UN PROVEEDOR API ═══════════════════════════════════════════════════
 *
 * [F7 · obra 2] LOS DOS AGUJEROS QUE TENÍA, los dos medidos el 2026-08-06:
 *
 *  · **NO SE PODÍA CARGAR LA LLAVE TIPEÁNDOLA.** El único disparador de todo el flujo era
 *    `input.onpaste`. Sin botón, sin Enter, sin blur. La vara lo tapaba despachando el
 *    evento `paste` a mano — si una prueba necesita sintetizar el gesto, el gesto no existe.
 *    Ahora hay **[Guardar y probar]**, y el nombre es una promesa que se cumple: guarda y
 *    corre el checklist. Enter y blur disparan lo mismo. Pegar sigue andando.
 *
 *  · **UN PROVEEDOR YA CONECTADO QUEDABA SIN NINGÚN BOTÓN**: `defaultAction` devuelve ""
 *    cuando la fila ya es Default, y no había nada más. El panel de OpenRouter —el Default
 *    de la app— era un campo de contraseña y nada. Ahora, con llave guardada, van
 *    **[Volver a comprobar]** · **[Rotar llave]** · **[Quitar llave]**.
 *
 * El campo arranca PLEGADO cuando ya hay llave: nadie necesita mirar un input vacío de un
 * proveedor que ya configuró. [Rotar llave] lo despliega — que es exactamente lo que hace
 * el molde (`conectores/montaje.js:684`: rotar ES pegar otra llave, no un flujo aparte).
 */
function pintarPanelApi(f, host, pedirCatalogo) {
  const hayLlave = !!(f.hay_llave || f.conectado);
  host.innerHTML = `<div class="md-flow">${flowEstado(f)}
    <section class="md-flow-card"><h3>${L("API con tu llave", "API with your key")}</h3>
      <p>${L("Se valida contra el proveedor y se guarda cifrada en esta máquina.",
             "Validated against the provider and stored encrypted on this machine.")}</p></section>
    <div class="md-field md-api-campo"${hayLlave ? " hidden" : ""}>
      <label for="mdApiKey">${hayLlave ? L("Nueva llave de", "New key for") : L("Llave de", "Key for")} ${esc(f.label)}</label>
      <input id="mdApiKey" type="password" placeholder="${esc(API_HINT[f.ref] || "pegar aquí")}"
        autocomplete="off" spellcheck="false">
      <div class="md-actions" style="margin-top:9px">
        <button type="button" class="md-btn primario md-guardar">${L("Guardar y probar", "Save and test")}</button>
      </div>
    </div>
    <div class="md-aviso md-api-msg" hidden></div>
    ${hayLlave ? `<section class="md-flow-card md-modelo">
      <h3>${L("Modelo", "Model")}</h3>
      <div class="md-en-uso"></div>
      <div class="md-catalogo" hidden></div>
    </section>` : ""}
    <div class="md-actions">
      ${hayLlave ? `<button type="button" class="md-btn primario md-probar-host">${
        // [F9] «Volver a comprobar» PROMETE que ya se comprobó. Medido en la app: OpenRouter
        // tenía llave, decía «sin probar», y el botón decía «Volver a comprobar» — si nunca
        // se probó no hay a qué volver. El rótulo mira SU prueba, no una constante.
        (f.prueba && f.prueba.ts) ? L("Volver a comprobar", "Check again")
                                  : L("Comprobar", "Check")}</button>
        <button type="button" class="md-btn md-rotar">${L("Rotar llave", "Rotate key")}</button>
        <button type="button" class="md-btn md-quitar">${L("Quitar llave", "Remove key")}</button>` : ""}
      ${defaultAction(f)}
    </div>
    <div class="md-confirmar" hidden></div>
    <div class="md-flow-result"></div></div>`;
  const input = $("#mdApiKey", host), msg = $(".md-api-msg", host);
  let token = 0;
  // Cuatro gestos disparan lo mismo y dos pueden encadenarse (blur + click sobre
  // [Guardar y probar]): sin esto, la MISMA llave saldría dos veces por el cable —y la
  // prueba dura de F7 es un POST de generación, o sea que se pagaría dos veces.
  let enVuelo = null;
  const validar = async () => {
    const secret = (input.value || "").trim();
    if (enVuelo === secret) return;
    if (secret.length < 8) {
      // [F7] SE DICE. Antes salía en silencio: el usuario apretaba y no pasaba nada
      // visible, que es indistinguible de un botón roto.
      if (secret.length) {
        msg.hidden = false; msg.className = "md-aviso md-api-msg bad";
        msg.textContent = L("Esa llave es demasiado corta para ser una llave.",
                            "That key is too short to be a key.");
      }
      return;
    }
    enVuelo = secret;
    const mine = ++token;
    input.disabled = true;
    msg.hidden = false; msg.className = "md-aviso md-api-msg";
    msg.innerHTML = `<span class="md-spin"></span> ${L("Validando contra el proveedor…", "Validating with provider…")}`;
    try {
      const r = await CX.agregarKey({ provider: f.ref, secret });
      if (mine !== token || ST.seleccion !== f.slug) return;
      if (!r) throw new Error(L("La llave no validó.", "The key didn't validate."));
      // [F7 · obra 1b] EL ESTADO LO DICE EL BACKEND, no `r.ok`. `ok:true` sólo significa
      // que la llamada salió bien; el veredicto sobre la llave está en `r.estado`, y se
      // pinta por el diccionario ÚNICO. Un `detectado` es 🟡, jamás 🟢.
      const estado = M.ESTADO[r.estado] ? r.estado : (r.ok === false ? "roto" : "detectado");
      const detalle = r.mensaje || r.detalle
        || (estado === "roto" ? M.textoCausa(r.causa, en()) : "");
      if (estado === "roto") throw new Error(detalle || L("La llave no validó.", "The key didn't validate."));
      input.value = "";
      msg.className = "md-aviso md-api-msg " + (estado === "probado" ? "ok" : "amber");
      msg.textContent = detalle;
      // Guardada = hay credencial, ande o no. Que el modelo esté CONECTADO no depende de
      // que la prueba haya salido verde: depende de que la llave exista.
      await aplicarVeredicto(f, { estado, causa: r.causa, detalle, conectado: r.guardada !== false });
    } catch (e) {
      if (mine !== token || ST.seleccion !== f.slug) return;
      msg.className = "md-aviso md-api-msg bad"; msg.textContent = String(e && e.message || e);
    } finally {
      // [F7] SIEMPRE se rehabilita. Antes sólo volvía en el `catch`: en el camino de éxito
      // el campo quedaba muerto detrás del panel.
      if (mine === token) {
        enVuelo = null;
        input.disabled = false;
        if (msg.className.includes("bad")) input.focus();
      }
    }
  };
  /* LOS CUATRO GESTOS QUE GUARDAN. Pegar era el ÚNICO que existía — por eso tipear la
   * llave no hacía nada, y por eso la vara tenía que despachar `paste` a mano. */
  const guardar = $(".md-guardar", host);
  if (guardar) guardar.onclick = () => conBoton(guardar, validar);
  input.onpaste = () => setTimeout(validar, 40);
  input.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); validar(); } };
  input.onblur = () => validar();

  // [Volver a comprobar] · corre el checklist de 7 pasos contra el proveedor. Es el mismo
  // verbo de conectores (`POST /v1/conexiones/checklist`), que para el carril API incluye
  // el paso `streaming` — el único que discrimina cuando el catálogo del proveedor es
  // público (F7 · obra 1a).
  const comprobar = $(".md-probar-host", host);
  if (comprobar) comprobar.onclick = () => probarHost(f, host, comprobar);

  /* ══ [F8 · obra 3] QUÉ MODELO USA, Y EL CATÁLOGO PARA CAMBIARLO ══════════════════
   *
   * ⚠️ EL CATÁLOGO ABRE **ACÁ**, EN EL PANEL — ley sellada por persona usuaria. La fila de la lista
   * no lo abre ni lo muestra: es la misma regla que en la obra 0 sacó el `<input>` de llave
   * de las filas. Una lista es para comparar; el momento de configurar tiene un solo lugar.
   *
   * ⚠️ Y LO PINTA `window.AlephModelSelector`, NO ESTE ARCHIVO. Ya hubo CUATRO catálogos de
   * modelos conviviendo en la plataforma; escribir acá un quinto picker «para el panel»
   * sería el quinto lugar donde el mismo dato se muestra distinto. Este módulo aporta el
   * host y el momento; el componente compartido aporta la lista, el buscador y la escritura.
   *
   * El «usando X» sale del CATÁLOGO y no de `f`: las filas de `/v1/modelos/v2` no llevan
   * modelo resuelto (eso vive en el selector), y el endpoint del proveedor lo devuelve
   * calculado por `_modelo_de_api` — el MISMO resolvedor que pinta la fila. Preguntarle a
   * él es lo que evita que el panel diga un modelo y la card diga otro.
   */
  const enUso = $(".md-en-uso", host), catBox = $(".md-catalogo", host);
  const AMS = window.AlephModelSelector;
  if (enUso && AMS && AMS.catalogo) {
    const pintarEnUso = (usando, porQuien) => {
      if (ST.seleccion !== f.slug) return;
      enUso.innerHTML = usando
        ? AMS.enUsoHtml({ slug: f.slug, modelo_elegido: usando, modelo_elegido_por: porQuien })
        // Sin modelo la card NO se queda muda ni inventa uno: dice la causa sellada y
        // ofrece el único camino que la resuelve.
        : `<div class="amc-usando"><span>${esc(M.textoCausa("modelo_no_elegido", en())
            || L("Modelo sin elegir", "No model picked"))}</span>
           <span class="amc-cambiar" role="button" tabindex="0" data-cambiar="${esc(f.slug)}"
             >${L("Elegir modelo", "Pick a model")}</span></div>`;
      const btn = $("[data-cambiar]", enUso);
      if (btn) {
        const abrir = () => alternarCatalogo();
        btn.onclick = abrir;
        btn.onkeydown = (ev) => {
          if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); abrir(); }
        };
      }
    };
    const alternarCatalogo = (forzarAbierto) => {
      if (!catBox) return;
      const abrir = forzarAbierto === true || catBox.hidden;
      catBox.hidden = !abrir;
      if (!abrir) { catBox.replaceChildren(); return; }
      AMS.catalogoRender(catBox, {
        slug: f.slug,
        data: AMS.catalogoData(f.slug),
        onPick: (res) => {
          if (ST.seleccion !== f.slug) return;
          pintarEnUso(res && res.usando, res && res.elegido_por);
          // La fila de la lista lleva el modelo: si no se refresca, la pantalla de atrás
          // sigue afirmando el anterior. Es el mismo bug de «dos vistas de lo mismo».
          const fila = filaDe(f.slug);
          if (fila) { fila.modelo_elegido = (res && res.usando) || null;
                      fila.modelo_elegido_por = (res && res.elegido_por) || null; }
          pintarLista();
        },
      });
    };
    enUso.innerHTML = `<span class="amc-usando"><span class="md-spin"></span> ${
      L("Buscando el catálogo…", "Loading catalog…")}</span>`;
    // `recargar`: al ABRIR el panel se vuelve a preguntar quién está en uso — el caché del
    // cliente puede traer un `usando` que otra superficie ya cambió. No lleva `fresco`: la
    // LISTA del proveedor la cachea el backend con su propia caducidad, y salir a su red en
    // cada apertura sería pagar red por un dato que cambia en días.
    AMS.catalogo(f.slug, { recargar: true }).then((cat) => {
      pintarEnUso(cat && cat.usando, cat && cat.elegido_por);
      // Deep-link `?catalogo=1`: se llega acá desde el [Cambiar] de una superficie SIN
      // panel (el selector de la Sala/Cuarto). Aterrizar en el panel cerrado obligaría a
      // buscar otra vez el mismo botón que ya se apretó.
      if (pedirCatalogo) alternarCatalogo(true);
    }).catch((e) => {
      if (ST.seleccion !== f.slug) return;
      // Fallo VISIBLE: sin catálogo no se afirma nada sobre el modelo en uso.
      enUso.innerHTML = `<span class="amc-usando">${esc(
        L("No pude traer el catálogo del proveedor.", "Couldn't load the provider catalog."))}</span>`;
    });
  }

  // [Rotar llave] · rotar ES pegar otra llave. No tiene flujo propio: despliega el mismo
  // campo. Darle uno aparte sería construir por segunda vez algo que ya existe.
  const rotar = $(".md-rotar", host);
  if (rotar) rotar.onclick = () => {
    const campo = $(".md-api-campo", host);
    if (campo) { campo.hidden = false; input.focus(); }
  };

  // [Quitar llave] · PRIMER CLICK: SÓLO EL IMPACTO. Ninguna mutación ocurre en el primero
  // — el usuario ve qué se rompe antes de decidir, que es la mitad que convierte un botón
  // peligroso en una decisión informada (molde: `conectores/montaje.js:565-596`).
  const quitar = $(".md-quitar", host), conf = $(".md-confirmar", host);
  if (quitar && conf) quitar.onclick = () => {
    conf.hidden = false;
    conf.innerHTML = `<div class="md-aviso amber">
      <b>${L(`Quitar la llave de ${f.label}`, `Remove the ${f.label} key`)}</b>
      <div>${f.default
        ? L("Es tu Default: al quitarla te quedas sin modelo por defecto.",
            "It's your Default: removing it leaves you with no default model.")
        : L("Este modelo deja de estar disponible hasta que pegues otra.",
            "This model stops being available until you paste another one.")}</div>
      <div class="md-actions" style="margin-top:9px">
        <button type="button" class="md-btn primario md-quitar-ok">${L("Quitar", "Remove")}</button>
        <button type="button" class="md-btn md-quitar-no">${L("Dejarla", "Keep it")}</button>
      </div></div>`;
    $(".md-quitar-no", conf).onclick = () => { conf.hidden = true; conf.innerHTML = ""; };
    $(".md-quitar-ok", conf).onclick = (ev) => conBoton(ev.target, async () => {
      try {
        const d = await CX.quitarKey(f.ref);
        if (d && d.deleted === false && d.http)
          throw new Error(L(`No pude quitarla (HTTP ${d.http}).`, `Couldn't remove it (HTTP ${d.http}).`));
        await aplicarVeredicto(f, {
          estado: "no_configurado", conectado: false,
          detalle: L(`Quité la llave de ${f.label}.`, `Removed the ${f.label} key.`),
        });
      } catch (e) {
        conf.innerHTML = `<div class="md-aviso bad">${esc(String(e && e.message || e))}</div>`;
      }
    });
  };

  wireDefault(f, host);
}

function veredictoHTML(f) {
  const v = f.veredicto;
  if (!veredictoUtil(f)) return `<div class="md-aviso bad" data-veredicto-faltante="1">
    <b>${L("Falta el veredicto del lote.", "Batch verdict is missing.")}</b>
    ${v ? `<div>${esc(en() ? v.en : v.es)}</div>` : ""}
    ${L("No se puede descargar a ciegas.", "Blind download is disabled.")}</div>`;
  const cls = v.veredicto === "no_entra" ? "bad" : v.veredicto === "justo" ? "amber" : "ok";
  return `<div class="md-aviso ${cls}" data-veredicto="${esc(v.veredicto)}"><b>${esc(en() ? v.en : v.es)}</b>
    ${v.ram_pedida_gb ? `<div>${L("RAM estimada", "Estimated RAM")}: ${v.ram_pedida_gb} GB</div>` : ""}</div>`;
}

function pintarPanelHf(f, host) {
  const bloquea = !veredictoUtil(f) || f.veredicto.veredicto === "no_entra";
  host.innerHTML = `<div class="md-flow">${veredictoHTML(f)}
    <section class="md-flow-card"><h3>${L("Descarga local", "Local download")}</h3>
      <p>${f.peso_gb != null ? `${f.peso_gb} GB · ` : ""}${esc((f.formato || "").toUpperCase())}
      ${f.cuantizacion ? " · " + esc(f.cuantizacion) : ""}</p></section>
    <div class="md-actions">
      <button type="button" class="md-btn primario md-descargar"${bloquea ? " disabled" : ""}>${L("Descargar y probar", "Download and test")}</button>
      ${f.url ? `<a class="md-btn" href="${esc(f.url)}" target="_blank" rel="noopener">${L("Ver ficha", "View page")}</a>` : ""}
    </div><div class="md-download-host"></div></div>`;
  const b = $(".md-descargar", host);
  if (b) b.onclick = () => empezarDescarga(f);
}

function pintarPanelLocal(f, host) {
  host.innerHTML = `<div class="md-flow">${flowEstado(f)}
    <section class="md-flow-card"><h3>${L("En esta máquina", "On this machine")}</h3>
      <p>${esc(f.sub || "")}</p></section>
    <div class="md-actions">
      <button type="button" class="md-btn primario md-probar-local">${L("Probar automáticamente", "Test automatically")}</button>
      ${defaultAction(f)}
      ${f.preexistente ? "" : `<button type="button" class="md-btn md-borrar">${L("Liberar espacio", "Free space")}</button>`}
    </div><div class="md-flow-result"></div></div>`;
  $(".md-probar-local", host).onclick = () => probarLocal(f, host);
  const del = $(".md-borrar", host);
  if (del) del.onclick = () => borrarLocal(f, host);
  wireDefault(f, host);
}

async function probarLocal(f, host) {
  const out = $(".md-flow-result", host);
  if (out) out.innerHTML = `<div class="md-aviso"><span class="md-spin"></span> ${L("Probando de verdad…", "Actually testing…")}</div>`;
  try {
    const p = await API.probar(f.ref, { tag: f.ollama_tag, categoria: f.categoria });
    if (p.estado !== "probado") throw new Error(p.detalle || M.textoCausa(p.causa, en()));
    await finalizarExito(f, p.detalle || L("Prueba completa.", "Test complete."));
  } catch (e) {
    if (out) out.innerHTML = `<div class="md-aviso bad">${esc(String(e && e.message || e))}</div>`;
  }
}

async function borrarLocal(f, host) {
  const out = $(".md-flow-result", host);
  try {
    const d = await API.borrar(f.ref);
    if (out) out.innerHTML = `<div class="md-aviso ok">${L("Espacio liberado", "Space freed")}: ${d.liberado_gb || 0} GB</div>`;
    setTimeout(() => { cerrarPanel(); cargar({ silencioso: true }); }, 500);
  } catch (e) {
    if (out) out.innerHTML = `<div class="md-aviso bad">${esc(String(e && e.message || e))}</div>`;
  }
}

export function empezarDescarga(f) {
  const host = $("#mdPanelBody .md-download-host");
  if (!host || ST.descarga) return;
  host.innerHTML = `<div class="md-flow-card">
    <div class="md-progress-copy">${L("Empezando…", "Starting…")}</div>
    <div class="md-progress"><span style="width:0%"></span></div>
    <div class="md-actions" style="margin-top:9px"><button type="button" class="md-btn md-cancelar">${L("Cancelar", "Cancel")}</button></div>
  </div>`;
  const copy = $(".md-progress-copy", host), bar = $(".md-progress span", host);
  let terminado = false;
  const evento = async (ev) => {
    if (ev.tipo === "veredicto") {
      if (copy) copy.textContent = en() ? ev.veredicto.en : ev.veredicto.es;
    } else if (ev.tipo === "arranque" || ev.tipo === "progreso") {
      if (bar && ev.pct != null) bar.style.width = ev.pct + "%";
      if (copy) copy.textContent = L(
        `Bajando ${ev.mb || 0} de ${ev.mb_total || 0} MB · ${ev.mbps || 0} MB/s`,
        `Downloading ${ev.mb || 0} of ${ev.mb_total || 0} MB · ${ev.mbps || 0} MB/s`);
    } else if (ev.tipo === "instalando") {
      if (copy) copy.textContent = L("Instalando…", "Installing…");
    } else if (ev.tipo === "probando") {
      if (copy) copy.textContent = L("Prueba automática…", "Automatic test…");
    } else if (ev.tipo === "fin" && !terminado) {
      terminado = true; ST.descarga = null;
      if (ev.estado === "probado") {
        host.innerHTML = `<div class="md-aviso ok">🟢 ${esc(ev.detalle || L("Descargado y probado.", "Downloaded and tested."))}</div>`;
        await finalizarExito(f, ev.detalle || L("Descargado y probado.", "Downloaded and tested."));
      } else {
        host.innerHTML = `<div class="md-aviso bad">🔴 ${esc(ev.detalle || M.textoCausa(ev.causa, en()))}</div>`;
      }
    }
  };
  const dl = API.descargar({
    id: f.hf_id || f.ref, archivo: f.archivo, archivos: f.archivos, formato: f.formato,
    categoria: f.categoria, peso_gb: f.peso_gb, tier: f.tier,
  }, evento);
  ST.descarga = { slug: API.slugDe(f.hf_id || f.ref), abortar: dl.abortar };
  API.cachearAvatar(f.marca);
  $(".md-cancelar", host).onclick = async () => {
    const running = ST.descarga;
    if (!running) return;
    try { await API.cancelar(running.slug); } catch (e) {}
    running.abortar(); ST.descarga = null;
    host.innerHTML = `<div class="md-aviso">${L("Cancelada. No quedó nada a medio bajar.", "Canceled. Nothing was left half-downloaded.")}</div>`;
  };
}

/* ── EL RESULTADO DE UN VERBO SE ESCRIBE UNA VEZ, Y CON EL ESTADO QUE SE MIDIÓ ──────
 *
 * [F7 · obra 1b/1c] Dos bugs de anti-grift vivían acá, los dos medidos el 2026-08-06:
 *
 *  1b · el llamador derivaba VERDE de `r.ok`. Pero `ok:true` significa «la llamada salió
 *       bien», no «tu llave anda»: el backend puede contestar `ok:true, estado:"detectado"`
 *       («la guardé, no la sé validar»), y eso salía 🟢. Ahora entra el ESTADO medido y se
 *       mapea por el diccionario ÚNICO (`modelos.semaforo.js`), que es el mismo que pinta
 *       la lista. Un estado que el diccionario no conoce NO se inventa: cae a `detectado`.
 *
 *  1c · después de releer el lote fresco del backend, se le sobrescribía el estado a
 *       «probado». Se pedía la verdad y se la pisaba. **El lote fresco manda**: lo que
 *       queda es el `pintarLista()`.
 *
 * Lo que SÍ se conserva es la escritura optimista sobre la fila vieja (antes del refresh):
 * el hecho ya ocurrió, y una caída del refresh no puede convertir ese hecho en rojo. Esa
 * fila la reemplaza el lote en cuanto llega.
 */
async function aplicarVeredicto(f, v) {
  const estado = M.ESTADO[v.estado] ? v.estado : "detectado";
  const detalle = v.detalle || (en() ? M.ESTADO[estado].en : M.ESTADO[estado].es);
  f.estado = estado;
  f.causa = estado === "roto" ? (v.causa || null) : null;
  f.conectado = v.conectado != null ? !!v.conectado : (estado === "probado");
  f.prueba = Object.assign({}, f.prueba || {}, {
    estado, causa: f.causa, detalle, ts: Math.floor(Date.now() / 1000),
  });
  cerrarPanel();
  pintarLista();
  aviso(estado === "probado" ? "ok" : estado === "roto" ? "bad" : "amber", detalle);
  try {
    await cargar({ silencioso: true });   // ← y NO se pisa: acá está la verdad
    pintarLista();
    /* ★ EL BANNER DICE LO QUE DICE LA FILA. Antes decía la frase que había escrito el
     * llamador («La comprobación terminó en verde») y la lista podía mostrar otra cosa —
     * medido en la app: banner en verde con CERO verdes de API. Texto y luz del mismo campo
     * derivado no pueden discrepar; así que el banner se REESCRIBE con lo que quedó en la
     * fila después de recargar, que es la única verdad que hay. */
    const fresca = ST.filas.find((x) => x.slug === f.slug);
    if (fresca) {
      const sem = (W.derivar(fresca, { ahora: Date.now() }) || {}).semaforo || {};
      /* ⚠️ EL TONO SE DERIVA DE LA FILA; LAS PALABRAS DEL BACKEND SOBREVIVEN.
       *
       * Lo que no podía seguir era que el banner AFIRMARA un desenlace por su cuenta —
       * «La comprobación terminó en verde» con cero verdes en la lista. Esa frase la
       * inventaba el llamador y nadie la contrastaba con nada.
       *
       * Pero borrar el detalle del backend sería la pérdida opuesta: «la guardé pero no la
       * pude probar» dice MUCHO más que «sin probar», y es exactamente la clase de precisión
       * que F7 peleó para tener. Así que el TONO —lo que no puede discrepar— sale del mismo
       * derivador que pinta la fila, y el TEXTO conserva lo que el backend dijo cuando dijo
       * algo. Si no dijo nada, se usa el texto derivado, que siempre concuerda. */
      aviso(sem.tono === "ok" ? "ok" : sem.tono === "mal" ? "bad" : "amber",
            detalle || `${fresca.label}: ${sem.texto}`);
    }
  } catch (e) {
    pintarLista();
    aviso("amber", L(
      `${detalle} No pude refrescar el listado todavía.`,
      `${detalle} I couldn't refresh the list yet.`));
  }
}

/** Azúcar para los verbos que sí terminaron en verde (CLI · local · descarga HF). */
const finalizarExito = (f, detalle) => aplicarVeredicto(f, { estado: "probado", detalle });

// ── Default caído: aparece sólo cuando una superficie intenta usarlo ─────────────
export function usarDefault() {
  const slug = (ST.preferencias || {}).default;
  const f = filaDe(slug);
  if (f && f.conectado) return true;
  const dlg = $("#mdDefaultCaido");
  if (!dlg) return false;
  $("#mdFallenCopy").textContent = f
    ? L(`${f.label} sigue siendo tu Default, pero ahora está caído.`, `${f.label} is still your Default, but it's down now.`)
    : L("Tu Default ya no está disponible.", "Your Default is no longer available.");
  dlg.hidden = false;
  $("#mdReconectar").onclick = () => { dlg.hidden = true; if (f) abrirPanel(f.slug); };
  $("#mdUsarOtro").onclick = () => {
    dlg.hidden = true;
    const otro = ST.filas.find((x) => x.conectado && x.slug !== slug);
    if (otro) abrirPanel(otro.slug);
    else aviso("bad", L("No hay otro modelo conectado.", "There is no other connected model."));
  };
  return false;
}

function aviso(clase, texto) {
  const a = $("#mdAviso");
  if (!a) return;
  a.hidden = false; a.className = "md-aviso " + clase; a.textContent = texto;
  clearTimeout(aviso._t);
  aviso._t = setTimeout(() => { a.hidden = true; }, 7000);
}

export async function cargar(opts) {
  opts = opts || {};
  if (ST.cargando) return;
  ST.cargando = true;
  const ref = $("#mdRefrescar");
  if (ref) ref.disabled = true;
  try {
    ST.requestsListado += 1;
    const d = await API.listarV2({ limiteHf: 2 });
    ST.filas = d.filas || [];
    ST.categorias = d.categorias || [];
    ST.maquina = d.maquina || null;
    ST.preferencias = d.preferencias || {};
    ST.conteo = d.conteo || {};
    ST.contrato = d.contrato || {};
    if (d.hf && d.hf.red === false)
      aviso("amber", L("Parte del catálogo HF no respondió; los modelos conectados siguen disponibles.",
                        "Part of the HF catalog didn't respond; connected models remain available."));
    pintarCategorias(); pintarMaquina(); pintarLista();
    if (!opts.silencioso) aplicarFoco();
  } catch (e) {
    const host = $("#mdFilas");
    if (host) host.innerHTML = `<p class="md-vacio">${L("No pude leer los modelos: ", "Couldn't load models: ")}
      ${esc(String(e && e.message || e))} <button type="button" class="md-btn" id="mdReintentar">↻ ${L("Reintentar", "Retry")}</button></p>`;
    const b = $("#mdReintentar"); if (b) b.onclick = () => cargar();
    throw e;
  } finally {
    ST.cargando = false;
    if (ref) ref.disabled = false;
  }
}

function aplicarFoco() {
  const f = API.focoDeLaUrl();
  if (f.categoria) {
    ST.categoria = f.categoria; elegirOrigen("hf_local");
  } else if (f.modo) {
    elegirOrigen(f.modo === "local" || f.modo === "hf" ? "hf_local" : f.modo);
  }
  if (f.slug) {
    const row = ST.filas.find((x) => x.slug === f.slug || x.ref === f.slug);
    if (row) abrirPanel(row.slug);
  }
}

export function abrirCategoria(cat) {
  ST.categoria = cat || "todas";
  elegirOrigen("hf_local");
}

export function andar(slug) { abrirPanel(slug); }

export async function montar() {
  const filtro = $("#mdFiltro");
  if (filtro) filtro.oninput = () => { ST.texto = filtro.value.trim(); pintarLista(); };
  $$("#mdOrigen .md-switch").forEach((b) => { b.onclick = () => elegirOrigen(b.dataset.origin); });
  $("#mdRefrescar").onclick = () => {
    // Apretar ↻ es pedir una medición NUEVA: el acumulador de la caducidad no puede
    // tragársela (molde: `conectores/montaje.js:679`).
    ST.midiendo.clear();
    return cargar();
  };
  /* [F8 · obra 3] EL ATERRIZAJE DEL [Cambiar] QUE VIENE DE UNA PANTALLA SIN PANEL.
   *
   * ⚠️ ACÁ NO SE LEE `?m=`, Y ES A PROPÓSITO: `aplicarFoco()` YA lo lee (vía
   * `API.focoDeLaUrl`) y ya abre el panel de esa fila. La primera versión de esta obra
   * volvió a leerlo y a llamar `abrirPanel` — el resultado fue que el panel se pintaba DOS
   * veces y el segundo pintado le borraba al primero el catálogo recién abierto. Lo cazó la
   * vara, y es la lección de siempre con otra cara: el segundo implementador de algo que ya
   * existe no agrega, pisa.
   *
   * Lo único que falta acá es el `catalogo=1`: un flag DE UN SOLO USO que el próximo panel
   * de API consume. No lleva slug —el foco ya decide cuál fila abre— y se apaga al pintar
   * cualquier panel, para que no quede armado esperando al próximo que alguien abra. */
  try {
    ST.abrirCatalogo = new URLSearchParams(location.search).get("catalogo") === "1";
  } catch (e) { /* un query raro no puede impedir que la pantalla monte */ }
  $("#mdPanelVolver").onclick = cerrarPanel;
  $("#mdPanelBack").onclick = cerrarPanel;
  // [F7 · obra 3] UN listener para toda la lista, atado UNA vez. Antes se re-ataba un
  // `onclick` por fila en cada repintado; el que se olvidaba era un botón que existía en
  // el HTML y no respondía — que es el bug de alcanzabilidad de Gate 1, otra vez.
  const lista = $("#mdFilas");
  if (lista) lista.addEventListener("click", alClickLista);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") cerrarPanel(); });
  await cargar();
  window.AlephModelosV2 = {
    estado: () => ST, abrir: abrirPanel, cerrar: cerrarPanel, usarDefault,
    filasVisibles: () => ST.filas.filter(coincide),
    // [F7] el censo derivado, para que una vara pueda preguntarle a la pantalla montada
    // qué está contando — y no tener que re-derivarlo por su cuenta.
    censo: () => W.censo(ST.filas.filter(coincide), { ahora: Date.now() }),
  };
}

export default {
  montar, cargar, pintarLista, abrirFila, abrirCategoria, empezarDescarga, andar,
  roles, cara, esFallback, textoEstado, caminoFila, imposibleDe, estado, usarDefault,
};
