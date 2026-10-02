/* conexion-inline.js — conexión dentro del turno (P7 + P11).
 *
 * Una tool de cliente pide esta pieza; el cliente sólo la rinde. La credencial viaja
 * directamente al validador P11 y, si pasa, queda cifrada en el vault global. Nunca entra
 * en el resultado de la tool, el transcript, localStorage ni el estado de la conversación.
 *
 * División sellada:
 *   llave          → formulario completo inline;
 *   oauth          → abre consent y confirma la vuelta releyendo el vault;
 *   local/instalar → sólo comando + link a su pantalla (jamás instala desde el chat).
 */

import * as Sem from "../cuarto/cuarto.semaforo.js";
import { asegurarSesion, sesion } from "../conexiones/centro.api.js";

export const TOOL_NAME = "conectar_inline";
export const TOOL_NAMES = [TOOL_NAME];
/* Adaptador para consent embebible/mock. El retorno real vigente sigue siendo el callback
 * del backend → Conectar.dc.html?c=<slug>&oauth=ok|partial|cancelled|error[&reason|id].
 * Si una shell puede devolver al opener, éste es el ÚNICO mensaje aceptado; aun con `ok`,
 * el widget relee GET /users/{id}/keys antes de pintar verde. */
export const OAUTH_RETURN_CONTRACT = Object.freeze({
  type: "aleph:oauth:return", version: 1,
  fields: ["connector", "status", "nonce"],
  statuses: ["ok", "partial", "cancelled", "error"],
});

const fn = (name, description, properties, required) => ({
  type: "function",
  function: {
    name,
    description,
    parameters: {
      type: "object",
      properties: properties || {},
      required: required || [],
      additionalProperties: false,
    },
  },
});

const DOC = {
  es: [
    "Muestra la conexión que BLOQUEA este trabajo dentro del turno actual. Usarla sólo cuando una capacidad necesaria está identificada y no conectada.",
    "LLAVE: formulario inline que lee logo/nombre/formato/link exacto del catálogo, valida con P11 y guarda cifrado global. OAUTH: botón inline que abre el consent y espera la vuelta. LOCAL/INSTALAR: muestra comando + link a su pantalla; jamás instala inline.",
    "NO usar para una pregunta abierta, charla, desahogo, una preferencia, una capacidad opcional ni algo que ya está conectado. No pedir, copiar ni incluir la credencial en los argumentos: la pega el humano dentro del widget.",
    "Emitida la tool, esperar su resultado. La conversación retoma con metadata segura; nunca con la llave.",
  ].join("\n"),
  en: [
    "Render the connection BLOCKING this work inside the current turn. Use only when a required capability is known and not connected.",
    "KEY: inline form reads logo/name/format/exact link from the catalog, validates through P11, and stores encrypted globally. OAUTH: inline button opens consent and waits for return. LOCAL/INSTALL: show the command plus its screen link; never install inline.",
    "DO NOT use for an open question, conversation, venting, a preference, an optional capability, or something already connected. Never ask for, copy, or include a credential in the arguments: the human pastes it inside the widget.",
    "After emitting the tool, wait for its result. The conversation resumes with safe metadata, never the key.",
  ].join("\n"),
};

export function CONEXION_INLINE_TOOLS(lang) {
  const L = lang === "en" ? "en" : "es";
  return [fn(TOOL_NAME, DOC[L], {
    mensaje: {
      type: "string",
      description: L === "en"
        ? "One brief line explaining why this exact connection is needed now."
        : "Una línea breve: por qué hace falta esta conexión exacta ahora.",
    },
    connector: {
      type: "string",
      description: L === "en"
        ? "Exact connector slug from the equipped tool/catalog (for example zotero or gmail)."
        : "Slug exacto del conector equipado/catálogo (por ejemplo zotero o gmail).",
    },
    tipo: {
      type: "string",
      enum: ["llave", "oauth", "local"],
      description: L === "en" ? "Sealed rendering division." : "División de render sellada.",
    },
    nombre: {
      type: "string",
      description: L === "en" ? "Optional human name; catalog name wins." : "Nombre humano opcional; manda el catálogo.",
    },
    comando: {
      type: "string",
      description: L === "en" ? "LOCAL only: exact command to show, never execute." : "Sólo LOCAL: comando exacto a mostrar, jamás ejecutar.",
    },
    pantalla_url: {
      type: "string",
      description: L === "en" ? "LOCAL only: exact screen or official documentation link." : "Sólo LOCAL: pantalla exacta o documentación oficial.",
    },
  }, ["mensaje", "connector", "tipo"])];
}

const I18N = {
  es: {
    connect: "Conectar",
    connecting: "validando y guardando…",
    encrypted: "Se cifra en tu vault global. No entra al chat.",
    exact: "Obtener la llave en la página exacta",
    exactNeedsBase: "Escribe tu dominio y te dejo el link a la página exacta.",
    connected: "Conectado y guardado cifrado",
    unverified: "Guardado cifrado; se confirma en el primer uso real",
    consent: "Abrir autorización",
    waiting: "Autorización abierta — esperando la vuelta…",
    screen: "Abrir su pantalla",
    command: "Comando (se corre fuera del chat)",
    copy: "Copiar",
    copied: "Copiado",
    missing: "Falta completar el campo.",
    descriptor: "No pude leer la ficha canónica de este conector.",
    vault: "El validador respondió, pero no apareció en el vault global.",
  },
  en: {
    connect: "Connect",
    connecting: "validating and saving…",
    encrypted: "Encrypted in your global vault. It never enters chat.",
    exact: "Get the key on the exact page",
    exactNeedsBase: "Type your domain and I'll link you to the exact page.",
    connected: "Connected and stored encrypted",
    unverified: "Stored encrypted; it will be confirmed on first real use",
    consent: "Open authorization",
    waiting: "Authorization opened — waiting for return…",
    screen: "Open its screen",
    command: "Command (run outside chat)",
    copy: "Copy",
    copied: "Copied",
    missing: "Complete this field first.",
    descriptor: "I couldn't read this connector's canonical descriptor.",
    vault: "The validator replied, but the connection did not appear in the global vault.",
  },
};

const active = new Set();
const BUS_NAME = "aleph:conexiones-global:v1";
const STORAGE_PULSE = "aleph.connection.pulse.v1";
let channel = null;
let busReady = false;

const langNow = () => {
  try { return window.AlephI18n && window.AlephI18n.lang && window.AlephI18n.lang() === "en" ? "en" : "es"; }
  catch (e) { return "es"; }
};
const tr = (k) => I18N[langNow()][k] || I18N.es[k] || k;
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const slug = (s) => String(s || "").trim().toLowerCase();
const connectorValido = (s) => /^[a-z0-9][a-z0-9._-]{0,79}$/.test(slug(s));
const safeHref = (s) => {
  const v = String(s || "").trim();
  if (/^https?:\/\//i.test(v)) return v;
  if (/^(?:\.\.\/|\.\/|\/)[^<>"']+$/.test(v) && !/^\/\//.test(v)) return v;
  return "";
};
const face = (connector, name) => {
  try {
    if (window.AlephBrand && window.AlephBrand.faceHTML)
      return window.AlephBrand.faceHTML({ server: connector, connector, label: name }, { size: 28, cls: "aci-logo" });
  } catch (e) {}
  const ini = String(name || connector || "?").trim().slice(0, 2).toUpperCase();
  return '<span class="aci-fallback" aria-hidden="true">' + esc(ini) + "</span>";
};
const fullUser = async () => {
  let u = sesion();
  if (!(u && u.id && u.session_token)) u = await asegurarSesion();
  return (u && u.id && u.session_token) ? u : null;
};
const auth = (u, headers) => {
  const h = Object.assign({}, headers || {});
  if (u && u.session_token) h.Authorization = "Bearer " + u.session_token;
  return h;
};

export function validar(args) {
  const a = args && typeof args === "object" ? args : {};
  const err = (error) => ({ ok: false, error });
  const connector = slug(a.connector);
  const tipo = String(a.tipo || "").trim().toLowerCase();
  const mensaje = String(a.mensaje || "").trim();
  if (!mensaje) return err("falta `mensaje`");
  if (mensaje.length > 320) return err("`mensaje` demasiado largo");
  if (!connectorValido(connector)) return err("`connector` no es un slug válido");
  if (!["llave", "oauth", "local"].includes(tipo)) return err("`tipo` debe ser llave, oauth o local");
  // Defensa en profundidad: una credencial no puede viajar escondida en el tool_call.
  for (const k of Object.keys(a)) {
    if (/^(secret|token|credential|credencial|api_key|key)$/i.test(k))
      return err("la credencial no puede viajar en los argumentos de la tool");
  }
  if (tipo === "local" && !String(a.comando || "").trim())
    return err("LOCAL necesita `comando`: se muestra, jamás se ejecuta");
  return { ok: true, datos: {
    mensaje, connector, tipo,
    nombre: String(a.nombre || "").trim() || connector,
    comando: String(a.comando || "").trim() || null,
    pantalla_url: safeHref(a.pantalla_url) || null,
  } };
}

async function descriptor(connector, u) {
  const r = await fetch("/v1/connectors/" + encodeURIComponent(connector), {
    headers: auth(u, { Accept: "application/json" }),
  });
  if (!r.ok) return null;
  const d = await r.json().catch(() => null);
  return d && typeof d === "object" ? d : null;
}

async function vaultMeta(connector) {
  const u = await fullUser();
  if (!u) return null;
  const r = await fetch("/v1/users/" + encodeURIComponent(u.id) + "/keys", {
    headers: auth(u, { Accept: "application/json" }),
  }).catch(() => null);
  if (!r || !r.ok) return null;
  const d = await r.json().catch(() => null);
  return ((d && d.keys) || []).find((k) => slug(k && k.provider) === slug(connector)) || null;
}

function safeResult(w, extra) {
  return Object.assign({
    tool: TOOL_NAME,
    connector: w.datos.connector,
    tipo: w.kind,
    // Campo explícito para que la vara pueda afirmar el contrato: nunca existe `secret`.
    credencial_en_chat: false,
  }, extra || {});
}

function markConnected(w, meta, source) {
  if (w.done) return;
  w.node.dataset.state = "connected";
  w.node.classList.add("connected");
  const form = w.node.querySelector(".aci-form");
  if (form) form.hidden = true;
  const stat = w.node.querySelector("[data-aci-status]");
  if (stat) {
    stat.className = "aci-status good";
    stat.textContent = "✓ " + (meta && meta.verified === false ? tr("unverified") : tr("connected"));
  }
  w.finish(safeResult(w, {
    ok: true, estado: meta && meta.verified === false ? "detectado" : "probado",
    causa: null, guardada_global: true, source: source || "vault",
  }));
}

function announce(connector) {
  const msg = { type: "changed", version: 1, connector: slug(connector), ts: Date.now() };
  try { if (channel) channel.postMessage(msg); } catch (e) {}
  try { window.dispatchEvent(new CustomEvent("aleph:connection-changed", { detail: msg })); } catch (e) {}
  // Pulso cross-tab. Va SIEMPRE, no sólo cuando falta BroadcastChannel: que el canal EXISTA
  // no prueba que entregue entre pestañas, y una conexión que no aparece en la otra
  // superficie es justamente el defecto que esta pieza tiene que hacer imposible. El doble
  // aviso es inocuo — markConnected es idempotente (`w.done`). Se borra al instante: no deja
  // estado persistente y el payload sólo nombra el provider (jamás la credencial).
  try {
    localStorage.setItem(STORAGE_PULSE, JSON.stringify(msg));
    localStorage.removeItem(STORAGE_PULSE);
  } catch (e) {}
}

async function refreshProvider(connector, source) {
  const meta = await vaultMeta(connector);
  if (!meta) return false;
  active.forEach((w) => {
    if (w.datos.connector === slug(connector) && !w.done) markConnected(w, meta, source);
  });
  return true;
}

function ensureBus() {
  if (busReady || typeof window === "undefined") return;
  busReady = true;
  try {
    if (typeof BroadcastChannel === "function") {
      channel = new BroadcastChannel(BUS_NAME);
      channel.onmessage = (ev) => {
        const d = ev && ev.data;
        if (d && d.type === "changed" && d.version === 1 && connectorValido(d.connector))
          refreshProvider(d.connector, "broadcast");
      };
    }
  } catch (e) { channel = null; }
  window.addEventListener("aleph:connection-changed", (ev) => {
    const d = ev && ev.detail;
    if (d && connectorValido(d.connector)) refreshProvider(d.connector, "window");
  });
  window.addEventListener("storage", (ev) => {
    if (ev.key !== STORAGE_PULSE || !ev.newValue) return;
    let d = null; try { d = JSON.parse(ev.newValue); } catch (e) {}
    if (d && d.type === "changed" && connectorValido(d.connector))
      refreshProvider(d.connector, "storage");
  });
}

function p1bError(w, causa, detail, retry) {
  const c = Sem.CAUSAS[causa] || { es: "No se pudo verificar", en: "Could not verify" };
  const camino = Sem.caminoDe({ estado: "roto", causa });
  const status = w.node.querySelector("[data-aci-status]");
  if (!status) return;
  // El estado también se marca en el nodo: si se queda en "loading" mientras muestra un
  // error, cualquiera que lea el DOM (la vara, otra superficie) ve un trámite "cargando"
  // que en realidad ya falló.
  if (w.node.dataset.state !== "connected") w.node.dataset.state = "error";
  status.className = "aci-status bad";
  status.replaceChildren();
  const title = document.createElement("b");
  title.textContent = (langNow() === "en" ? c.en : c.es) || c.es;
  status.appendChild(title);
  if (detail) {
    const d = document.createElement("span");
    d.className = "aci-detail"; d.textContent = String(detail).slice(0, 260);
    status.appendChild(d);
  }
  if (camino && camino.es) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "aci-cause";
    b.textContent = langNow() === "en" ? camino.en : camino.es;
    b.onclick = () => {
      if (camino.accion === "credencial") {
        const inputs = [...w.node.querySelectorAll("input[data-aci-field]")];
        inputs.filter((x) => x.type === "password").forEach((x) => { x.value = ""; });
        const first = inputs.find((x) => x.type === "password") || inputs[0];
        if (first) first.focus();
      } else if (typeof retry === "function") retry();
    };
    status.appendChild(b);
  }
}

function shell(datos) {
  const node = document.createElement("section");
  node.className = "aci";
  node.dataset.connector = datos.connector;
  node.dataset.kind = datos.tipo;
  node.dataset.state = "loading";
  node.setAttribute("aria-label", "Conectar " + datos.nombre);
  node.innerHTML =
    '<div class="aci-head"><span data-aci-face></span><span class="aci-title"><b>' +
      esc(datos.nombre) + '</b><small>' + esc(datos.mensaje) + "</small></span></div>" +
    '<div class="aci-form" data-aci-body><span class="aci-loading">' + esc(tr("connecting")) + "</span></div>" +
    '<div class="aci-status" data-aci-status role="status" aria-live="polite"></div>';
  const f = node.querySelector("[data-aci-face]");
  if (f) f.innerHTML = face(datos.connector, datos.nombre);
  return node;
}

function localBody(w) {
  const href = w.datos.pantalla_url ||
    ("../Conectar.dc.html?c=" + encodeURIComponent(w.datos.connector));
  const body = w.node.querySelector("[data-aci-body]");
  body.innerHTML =
    '<div class="aci-command-label">' + esc(tr("command")) + "</div>" +
    '<div class="aci-command"><code></code><button type="button" data-copy>' + esc(tr("copy")) + "</button></div>" +
    '<a class="aci-link" target="_blank" rel="noopener noreferrer"></a>';
  body.querySelector("code").textContent = w.datos.comando;
  const link = body.querySelector(".aci-link");
  link.href = href; link.textContent = tr("screen") + " ↗";
  const copy = body.querySelector("[data-copy]");
  copy.onclick = async () => {
    try { await navigator.clipboard.writeText(w.datos.comando); copy.textContent = tr("copied"); }
    catch (e) { copy.textContent = tr("copy"); }
  };
  w.node.dataset.state = "external";
  w.finish(safeResult(w, {
    ok: true, estado: "requiere_pantalla", causa: "cli_no_instalado",
    mostrado: true, ejecutado_inline: false,
  }));
}

function fieldsBody(w, d) {
  const body = w.node.querySelector("[data-aci-body]");
  const fields = Array.isArray(d.credential_fields) ? d.credential_fields : [];
  /* EL LINK A LA PÁGINA EXACTA, TAMBIÉN PARA LOS SELF-HOSTED. La ficha de un conector
   * self-hosted no puede traer una URL absoluta: su página exacta vive en el dominio de la
   * institución, así que declara `{base_url}/profile/settings#access_tokens` (canvas, moodle).
   * Descartar esos links dejaba justo a los conectores MÁS difíciles sin el único dato que
   * hace el trámite corto: dónde se saca la llave. Acá el link nace anunciado y se vuelve
   * REAL en cuanto la persona escribe su dominio — nunca se ofrece un destino que no existe. */
  const rawDeep = String(d.deep_link || "").trim();
  const deepConBase = /\{base_url\}/.test(rawDeep);
  const deep = deepConBase ? "" : safeHref(rawDeep);
  const needsBase = !!d.needs_base_url;
  const hasUrl = fields.some((f) => f && f.id === "url");
  let html = "";
  if (deep) {
    html += '<a class="aci-link" href="' + esc(deep) +
      '" target="_blank" rel="noopener noreferrer">🔑 ' + esc(tr("exact")) + " ↗</a>";
  } else if (deepConBase) {
    html += '<a class="aci-link" data-aci-deep hidden target="_blank" rel="noopener noreferrer"></a>' +
      '<div class="aci-hint" data-aci-deep-hint>' + esc(tr("exactNeedsBase")) + "</div>";
  }
  if (needsBase && !hasUrl) {
    html += '<label class="aci-field"><span>URL</span><small>https://…</small>' +
      '<input data-aci-base type="url" autocomplete="off" spellcheck="false"></label>';
  }
  fields.forEach((f) => {
    if (!f || !f.id) return;
    const secret = f.secret !== false;
    html += '<label class="aci-field"><span>' + esc(f.label || f.id) + "</span>" +
      '<small>' + esc(f.shape || "") + "</small>" +
      '<input data-aci-field="' + esc(f.id) + '" type="' + (secret ? "password" : "text") +
      '" placeholder="' + esc(f.shape || f.label || "") +
      '" autocomplete="' + (secret ? "new-password" : "off") + '" spellcheck="false"></label>';
  });
  html += '<div class="aci-lock">🔒 ' + esc(tr("encrypted")) + "</div>" +
    '<button type="button" class="aci-primary" data-connect>' + esc(tr("connect")) + "</button>";
  body.innerHTML = html;

  /* El link self-hosted se arma con lo que la persona escribe. Se exige un http(s) completo
   * (safeHref) para no fabricar un destino roto a partir de medio dominio tipeado. */
  const deepLink = body.querySelector("[data-aci-deep]");
  if (deepLink) {
    const hint = body.querySelector("[data-aci-deep-hint]");
    const baseDe = () => String(((body.querySelector("[data-aci-base]") ||
      body.querySelector('input[data-aci-field="url"]') || {}).value) || "").trim().replace(/\/+$/, "");
    const pintarDeep = () => {
      const href = safeHref(rawDeep.replace("{base_url}", baseDe()));
      const vivo = !!baseDe() && !!href;
      deepLink.hidden = !vivo;
      if (hint) hint.hidden = vivo;
      if (vivo) { deepLink.href = href; deepLink.textContent = "🔑 " + tr("exact") + " ↗"; }
    };
    body.querySelectorAll("[data-aci-base], input[data-aci-field='url']")
      .forEach((i) => i.addEventListener("input", pintarDeep));
    pintarDeep();
  }

  const button = body.querySelector("[data-connect]");
  const submit = async () => {
    const inputs = [...body.querySelectorAll("input[data-aci-field]")];
    const missing = inputs.find((x) => !String(x.value || "").trim());
    if (missing) {
      const status = w.node.querySelector("[data-aci-status]");
      status.className = "aci-status bad"; status.textContent = tr("missing"); missing.focus(); return;
    }
    const u = await fullUser();
    if (!u) { p1bError(w, "sin_sesion", "", submit); return; }
    const creds = {};
    inputs.forEach((x) => { creds[x.dataset.aciField] = String(x.value || "").trim(); });
    const baseInput = body.querySelector("[data-aci-base]");
    const urlField = inputs.find((x) => x.dataset.aciField === "url");
    const payload = { creds, user_id: u.id };
    const base = String((baseInput && baseInput.value) || (urlField && urlField.value) || "").trim();
    if (needsBase && base) payload.base_url = base;
    button.disabled = true;
    const status = w.node.querySelector("[data-aci-status]");
    status.className = "aci-status work"; status.textContent = tr("connecting");
    let out = null, http = 0;
    try {
      const r = await fetch("/v1/connectors/" + encodeURIComponent(w.datos.connector) + "/connect", {
        method: "POST",
        headers: auth(u, { "Content-Type": "application/json", Accept: "application/json" }),
        body: JSON.stringify(payload),
      });
      http = r.status; out = await r.json().catch(() => ({}));
    } catch (e) {
      out = { state: "network", message: String((e && e.message) || e) };
    } finally {
      // La credencial deja de vivir en el DOM apenas el validador respondió.
      inputs.filter((x) => x.type === "password").forEach((x) => { x.value = ""; });
      button.disabled = false;
    }
    const state = String((out && out.state) || "");
    if (http < 400 && ["connected", "connected_unverified"].includes(state)) {
      const meta = await vaultMeta(w.datos.connector);
      if (meta) {
        markConnected(w, meta, "connect");
        announce(w.datos.connector);
        return;
      }
      p1bError(w, "error_upstream", tr("vault"), submit);
      return;
    }
    const causa = (out && out.causa) ||
      (state === "invalid" || state === "wrong_account" ? "key_invalida" :
       state === "no_session" || http === 401 || http === 403 ? "sin_sesion" :
       state === "network" ? "sin_red" : "error_upstream");
    p1bError(w, causa, out && (out.message || (out.detail && (out.detail.detail || out.detail))), submit);
  };
  button.onclick = submit;
  body.querySelectorAll("input").forEach((i) => i.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); submit(); }
  }));
}

function oauthBody(w, d) {
  const body = w.node.querySelector("[data-aci-body]");
  body.innerHTML =
    '<div class="aci-lock">🔒 ' + esc(tr("encrypted")) + "</div>" +
    '<button type="button" class="aci-primary" data-connect>' + esc(tr("consent")) + "</button>";
  const button = body.querySelector("[data-connect]");
  let timer = 0;
  const wc = (typeof window !== "undefined" && window.crypto) || null;
  const nonce = (wc && wc.randomUUID) ? wc.randomUUID() :
    (Date.now().toString(36) + Math.random().toString(36).slice(2));
  w.node.dataset.oauthNonce = nonce;
  const stop = () => { if (timer) clearInterval(timer); timer = 0; };
  const check = async () => {
    if (await refreshProvider(w.datos.connector, "oauth_return")) { stop(); announce(w.datos.connector); return true; }
    return false;
  };
  const onMessage = (ev) => {
    const m = ev && ev.data;
    if (ev.origin !== location.origin || !m || m.type !== "aleph:oauth:return" ||
        m.version !== 1 || m.connector !== w.datos.connector || m.nonce !== nonce ||
        !OAUTH_RETURN_CONTRACT.statuses.includes(m.status)) return;
    // El mensaje nunca alcanza para pintar verde: sólo despierta una relectura del vault.
    check();
  };
  window.addEventListener("message", onMessage);
  w.cleanup.push(() => { stop(); window.removeEventListener("message", onMessage); });
  button.onclick = async () => {
    const u = await fullUser();
    if (!u) { p1bError(w, "sin_sesion", "", () => button.click()); return; }
    button.disabled = true;
    const status = w.node.querySelector("[data-aci-status]");
    status.className = "aci-status work"; status.textContent = tr("connecting");
    let out = null;
    try {
      const r = await fetch("/v1/connectors/" + encodeURIComponent(w.datos.connector) + "/connect", {
        method: "POST",
        headers: auth(u, { "Content-Type": "application/json", Accept: "application/json" }),
        body: JSON.stringify({ creds: {}, user_id: u.id }),
      });
      out = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error((out && out.message) || ("HTTP " + r.status));
    } catch (e) {
      button.disabled = false; p1bError(w, "error_upstream", String((e && e.message) || e), () => button.click()); return;
    }
    if (out.state !== "oauth_redirect" || !safeHref(out.authorize_url)) {
      button.disabled = false;
      /* `oauth_pending` = la app OAuth de Puppet no está registrada para ese proveedor. Eso
       * es defecto NUESTRO, no de la persona — y tiene que salir con una causa QUE EXISTA en
       * la tabla de P1B: `no_configurado` es un ESTADO del semáforo, no una causa, y caía en
       * el texto genérico "No se pudo verificar" — justo lo que esta pieza prohíbe. */
      p1bError(w, out.state === "oauth_pending" ? "falla_de_aleph" : "error_upstream",
        out.message || "OAuth no devolvió la URL de autorización", () => button.click());
      return;
    }
    try { window.open(out.authorize_url, "_blank", "noopener"); } catch (e) { location.href = out.authorize_url; }
    status.className = "aci-status work"; status.textContent = tr("waiting");
    button.disabled = false;
    timer = setInterval(check, 1200);
    window.addEventListener("focus", check, { once: true });
  };
}

async function hydrate(w) {
  if (w.datos.tipo === "local") { localBody(w); return; }
  const u = await fullUser();
  const d = await descriptor(w.datos.connector, u).catch(() => null);
  if (!d) {
    p1bError(w, "falla_de_aleph", tr("descriptor"));
    return;
  }
  const authMethod = String(d.auth_method || "").toLowerCase();
  w.kind = authMethod === "oauth" ? "oauth" : "llave";
  w.node.dataset.kind = w.kind;
  /* El onboarding object NO trae nombre de vitrina (`connector` es el slug: "exa", "canvas").
   * Poner el slug como título sería peor que el nombre humano que ya mandó el modelo. Orden:
   * lo canónico si existe → lo que dijo el modelo → el slug como último recurso. */
  const name = String(d.label || d.name || w.datos.nombre || d.connector || w.datos.connector);
  const title = w.node.querySelector(".aci-title b"); if (title) title.textContent = name;
  const f = w.node.querySelector("[data-aci-face]"); if (f) f.innerHTML = face(w.datos.connector, name);
  const already = await vaultMeta(w.datos.connector);
  if (already) { markConnected(w, already, "initial_vault"); return; }
  if (w.kind === "oauth") oauthBody(w, d); else fieldsBody(w, d);
  w.node.dataset.state = "ready";
}

export function montar(chat, opts) {
  opts = opts || {};
  ensureBus();
  let seq = 0;

  function emitir(args) {
    const v = validar(args);
    if (!v.ok) {
      console.error("[conexion-inline] tool rechazada — " + v.error);
      return Object.assign(v, { resultado: Promise.resolve({
        tool: TOOL_NAME, ok: false, estado: "contrato_invalido", error: v.error,
        credencial_en_chat: false,
      }) });
    }
    const node = shell(v.datos);
    let resolver = null;
    const resultado = new Promise((resolve) => { resolver = resolve; });
    const w = {
      id: "aci" + (++seq), datos: v.datos, node, kind: v.datos.tipo,
      done: false, cleanup: [],
      finish: (r) => {
        if (w.done) return;
        w.done = true;
        w.cleanup.splice(0).forEach((f) => { try { f(); } catch (e) {} });
        resolver(r);
        if (typeof opts.onResultado === "function") {
          try { opts.onResultado(r, v.datos, node); } catch (e) {}
        }
      },
    };
    active.add(w);
    w.cleanup.push(() => active.delete(w));
    chat.slot(node);
    hydrate(w).catch((e) => p1bError(w, "error_upstream", String((e && e.message) || e)));
    return { ok: true, datos: v.datos, node, resultado };
  }

  const ctl = {
    emitir,
    validar,
    refrescar: (connector) => refreshProvider(connector, "manual"),
    snapshot: () => [...active].filter((w) => w.node.isConnected).map((w) => ({
      connector: w.datos.connector, tipo: w.kind, state: w.node.dataset.state,
      // El snapshot público es deliberadamente incapaz de contener credenciales.
      credencial: false,
    })),
  };
  return ctl;
}

/* Viaja al shadow root una sola vez desde aleph-chat.js. */
export const CSS = `
  .aci{width:min(100%,520px);box-sizing:border-box;border:1px solid var(--line2,#4A433A);
    border-radius:14px;background:var(--paper2,#242120);padding:13px;display:flex;flex-direction:column;gap:10px}
  .aci.connected{border-color:rgba(52,211,153,.48);background:rgba(52,211,153,.06)}
  .aci-head{display:flex;align-items:center;gap:10px}
  /* ⚠ brandface.js inyecta su CSS canónico en el DOCUMENTO, y este chat vive en un SHADOW
     ROOT — que no hereda nada de ahí. Sin estas dos reglas el <span class="bface"> medía sus
     28px pero su <img> interno salía a tamaño natural, desbordaba la caja y el nombre del
     conector se le encimaba (medido en la primera captura de esta vara). El CSS que viaja al
     shadow tiene que traer TAMBIÉN lo que el documento le da gratis al resto. */
  .aci-logo,.aci-fallback{width:28px;height:28px;min-width:28px;border-radius:8px;flex:none;
    box-sizing:border-box;overflow:hidden;display:inline-flex;align-items:center;
    justify-content:center;background:rgba(255,255,255,.08);font-size:10px;font-weight:500}
  .aci-logo img{width:100%;height:100%;object-fit:contain;display:block}
  .aci-title{min-width:0;display:flex;flex-direction:column;gap:2px}.aci-title b{font-size:13px;color:var(--ink,#F3ECE0)}
  .aci-title small{font-size:11.5px;line-height:1.4;color:var(--muted,#A89C8B)}
  .aci-form{display:flex;flex-direction:column;gap:9px}
  /* markConnected() oculta el formulario con el atributo [hidden]. Sin esta regla no pasaba
     nada: el display:flex de autor de arriba le gana al display:none del user-agent, así
     que la caja quedaba en verde CON el input y el [Conectar] todavía abajo — invitando a
     pegar de nuevo una llave que ya está guardada. Se vio en la captura de La Sala. */
  .aci [hidden],.aci-form[hidden]{display:none}
  .aci-loading{font-size:11.5px;color:var(--muted,#A89C8B)}
  .aci-link{font-size:11.5px;font-weight:500;color:var(--accent-deep,#B4B1FF);text-decoration:none;
    align-self:flex-start}.aci-link:hover{text-decoration:underline}
  .aci-field{display:grid;grid-template-columns:1fr auto;gap:3px 10px}.aci-field>span{
    font-size:11.5px;font-weight:500;color:var(--ink,#F3ECE0)}.aci-field>small{
    font-size:10.5px;color:var(--faint,#897F70);max-width:290px;text-align:right}
  .aci-field input{grid-column:1/-1;box-sizing:border-box;width:100%;border:1px solid var(--line2,#4A433A);
    border-radius:9px;padding:8px 10px;background:var(--paper,#191716);color:var(--ink,#F3ECE0);font:12px inherit}
  .aci-field input:focus{outline:2px solid rgba(139,92,246,.35);border-color:var(--accent,#8B5CF6)}
  .aci-lock,.aci-hint{font-size:10.5px;color:var(--faint,#897F70);line-height:1.4}
  .aci-primary,.aci-cause,.aci-command button{align-self:flex-start;border:0;border-radius:9px;
    padding:7px 13px;background:var(--accent,#8B5CF6);color:#fff;font:500 11.5px inherit;cursor:pointer}
  .aci-primary:disabled{opacity:.5;cursor:default}.aci-cause{margin-top:2px;background:transparent;
    color:var(--accent-deep,#B4B1FF);border:1px solid var(--line2,#4A433A)}
  .aci-status{display:flex;flex-direction:column;align-items:flex-start;gap:4px;font-size:11.5px;line-height:1.4}
  .aci-status.work{color:var(--muted,#A89C8B)}.aci-status.good{color:var(--green,#34D399)}
  .aci-status.bad{color:#ef7777}.aci-status.bad b{font-size:12px}.aci-detail{color:var(--muted,#A89C8B)}
  .aci-command-label{font-size:10.5px;color:var(--faint,#897F70)}.aci-command{display:flex;gap:7px;
    align-items:center;border:1px solid var(--line2,#4A433A);border-radius:9px;padding:7px 8px}
  .aci-command code{flex:1;min-width:0;overflow:auto;color:var(--ink,#F3ECE0);font-size:11px;white-space:pre}
  .aci-command button{flex:none;padding:5px 9px;background:transparent;color:var(--accent-deep,#B4B1FF);
    border:1px solid var(--line2,#4A433A)}
`;

export default {
  TOOL_NAME, TOOL_NAMES, CONEXION_INLINE_TOOLS, OAUTH_RETURN_CONTRACT,
  validar, montar, CSS,
};
