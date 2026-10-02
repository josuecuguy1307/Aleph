/* metodo.api.js — TODOS los seams backend de la pieza Método viven ACÁ (un archivo).
 * El carril A (method/backend) es dueño de las rutas reales; si un path cambia,
 * se ajusta en este módulo y el resto del frontend no se entera.
 *
 * Contrato del PASO (ORDEN_METODO §2 — schema publicado):
 *   { id, text, phase, checkpoint, executor, evidence_hint, timeout, retries }
 * Jerarquía: fases (4-6 máx) → mini-pasos. El objeto método preserva campos
 * desconocidos (forward-compat con el backend).
 *
 * Auth: auth.js (cargado por la pantalla) envuelve fetch → Bearer en rutas /v1. */

function uid(pre) {
  try { return pre + "-" + crypto.randomUUID().slice(0, 8); }
  catch (e) { return pre + "-" + Math.random().toString(36).slice(2, 10); }
}

async function j(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const r = await fetch(path, opts);
  let d = null; try { d = await r.json(); } catch (e) { d = null; }
  if (!r.ok) {
    const msg = (d && (d.detail || d.error || d.message)) || ("http " + r.status);
    throw Object.assign(new Error(typeof msg === "string" ? msg : JSON.stringify(msg)), { status: r.status, body: d });
  }
  return d || {};
}

export function currentUser() {
  // login suave + relaunch: por AlephSession.get() (rehidrata desde localStorage). Leer
  // sessionStorage directo mandaba Métodos a Auth tras relanzar la .app, con la sesión viva.
  try { if (window.AlephSession && window.AlephSession.get) return window.AlephSession.get(); return JSON.parse(sessionStorage.getItem("puppet_user") || "null"); } catch (e) { return null; }
}

/* ── modelo ──────────────────────────────────────────────────────────────── */

export function newStep(text, phase) {
  return { id: uid("s"), text: text || "", phase: phase || "", checkpoint: false,
    executor: null, evidence_hint: null, timeout: null, retries: 3 };
}

export function newMethod(name) {
  return { name: name || "", steps: [] };
}

/* normaliza SIN destruir: garantiza los campos del schema en cada paso y
 * preserva cualquier campo extra que el backend haya agregado. */
export function normalizeMethod(m) {
  const out = Object.assign({}, m || {});
  out.name = String(out.name || "");
  out.steps = Array.isArray(out.steps) ? out.steps.map(function (s) {
    const base = newStep("", "");
    const st = Object.assign(base, s || {});
    st.id = st.id || uid("s");
    st.text = String(st.text || "");
    st.phase = String(st.phase || "");
    st.checkpoint = !!st.checkpoint;
    st.retries = (st.retries === undefined || st.retries === null) ? 3 : Number(st.retries);
    return st;
  }) : [];
  return out;
}

/* fases = orden de primera aparición de step.phase (los pasos son planos, la fase
 * es un campo del paso — ver schema §2). Mapa SIN prototipo: una fase llamada
 * 'constructor'/'toString' es contenido válido del usuario, no una clave heredada
 * (review: con {} el lookup veía Object.prototype y crasheaba el render). */
export function phasesOf(method) {
  const groups = [], byName = Object.create(null);
  (method.steps || []).forEach(function (s) {
    const ph = s.phase || "";
    if (!byName[ph]) { byName[ph] = { name: ph, steps: [] }; groups.push(byName[ph]); }
    byName[ph].steps.push(s);
  });
  return groups;
}

/* [H6] scrub anti-secreto — espejo del de la Sala (misma casa, mismas reglas):
 * lo que se PINTA desde eventos del espinazo (diagnosis, step_text, remedios)
 * pasa por acá. Defensa en profundidad: un diagnóstico del motor PODRÍA
 * arrastrar una credencial. */
export function scrubSecrets(s) {
  return String(s == null ? "" : s)
    .replace(/\b(pass(?:word|wd)?|contrase[nñ]a|secret|token|api[_-]?key|auth)\b(\s*[:=]\s*)(\S+)/gi, "$1$2‹oculto›")
    .replace(/\b(Basic|Bearer)\s+[A-Za-z0-9+/=_\-.]{8,}/g, "$1 ‹oculto›")
    .replace(/\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+/g, "‹oculto›")
    .replace(/\b(sk|pk|rk|xox[baprs]|ghp|gho|ghu|ghs|github_pat|ntn)[-_][A-Za-z0-9_\-]{6,}/g, "‹oculto›")
    .replace(/\bAIza[0-9A-Za-z_\-]{20,}/g, "‹oculto›")
    .replace(/\bya29\.[0-9A-Za-z_\-]{10,}/g, "‹oculto›")
    .replace(/\bAKIA[0-9A-Z]{12,}\b/g, "‹oculto›")
    .replace(/\b[A-Fa-f0-9]{32,}\b/g, "‹oculto›")
    .replace(/[A-Za-z0-9+/_\-]{40,}={0,2}/g, "‹oculto›");
}

export function validateMethod(m) {
  const errors = [], warnings = [];
  if (!String(m.name || "").trim()) errors.push("name");
  if (!Array.isArray(m.steps)) errors.push("steps");
  (m.steps || []).forEach(function (s, i) {
    if (!String(s.text || "").trim()) errors.push("step:" + i + ":text");
    if (s.timeout !== null && s.timeout !== undefined && !(Number(s.timeout) > 0)) errors.push("step:" + i + ":timeout");
    if (!(Number(s.retries) >= 0)) errors.push("step:" + i + ":retries");
  });
  const nPh = phasesOf(m).filter(function (g) { return g.name !== ""; }).length;
  if (nPh > 6) warnings.push("phases>6");
  return { ok: errors.length === 0, errors: errors, warnings: warnings };
}

/* ── seams HTTP (carril A) ───────────────────────────────────────────────── */

export const MetodoAPI = {
  list: function () { return j("GET", "/v1/methods").then(function (d) { return d.methods || d.items || (Array.isArray(d) ? d : []); }); },
  get: function (id) { return j("GET", "/v1/methods/" + encodeURIComponent(id)).then(function (d) { return normalizeMethod(d.method || d); }); },
  create: function (m) { return j("POST", "/v1/methods", m).then(function (d) { return d.method || d; }); },
  update: function (id, m) { return j("PUT", "/v1/methods/" + encodeURIComponent(id), m).then(function (d) { return d.method || d; }); },
  remove: function (id) { return j("DELETE", "/v1/methods/" + encodeURIComponent(id)); },

  /* captura multimodal "Traer mi proceso": texto pegado O archivo (b64). El
   * modelo estructura fases/pasos; el usuario pule en el editor. */
  structure: function (payload) { return j("POST", "/v1/methods/structure", payload).then(function (d) { return normalizeMethod(d.draft || d.method || d); }); },

  /* editar conversando: instrucción en lenguaje natural → el modelo propone
   * los pasos NUEVOS completos; el diff lo pinta el frontend (aceptar/rechazar). */
  proposeEdit: function (id, instruction, method) {
    return j("POST", "/v1/methods/" + encodeURIComponent(id) + "/propose_edit", { instruction: instruction, method: method })
      .then(function (d) { return { steps: (d.proposal && d.proposal.steps) || d.steps || [], summary: d.summary || "" }; });
  },

  /* guardar-desde-run: el plan del run exitoso se congela como método (draft). */
  fromRun: function (runId) { return j("POST", "/v1/methods/from_run", { run_id: runId }).then(function (d) { return d.method || d.draft || d; }); },

  /* propuesta contextual en la Sala: ¿este pedido hace eco de un método equipado? */
  match: function (puppetId, prompt) {
    return j("POST", "/v1/methods/match", { puppet_id: puppetId, prompt: prompt })
      .then(function (d) { return d.match || null; });
  },

  /* equipar por REFERENCIA (nunca copia) — ORDEN §2 */
  equipped: function (puppetId) { return j("GET", "/v1/puppets/" + encodeURIComponent(puppetId) + "/methods").then(function (d) { return d.methods || []; }); },
  equip: function (puppetId, methodId) { return j("POST", "/v1/puppets/" + encodeURIComponent(puppetId) + "/methods", { method_id: methodId }); },
  unequip: function (puppetId, methodId) { return j("DELETE", "/v1/puppets/" + encodeURIComponent(puppetId) + "/methods/" + encodeURIComponent(methodId)); },

  /* pausa→editar→reanudar: LA ÚNICA edición en vivo permitida (ORDEN §6). */
  pauseRun: function (runId) { return j("POST", "/v1/runs/" + encodeURIComponent(runId) + "/method/pause", {}); },
  resumeRun: function (runId, method) { return j("POST", "/v1/runs/" + encodeURIComponent(runId) + "/method/resume", method ? { method: method } : {}); },

  /* remedios de la política de fallo §5 (action: apply|retry|retry_in|skip). */
  remedy: function (runId, stepId, action, extra) {
    return j("POST", "/v1/runs/" + encodeURIComponent(runId) + "/method/remedy",
      Object.assign({ step_id: stepId, action: action }, extra || {}));
  },

  puppets: function () {
    const u = currentUser();
    if (!u || !u.id) return Promise.resolve([]);
    return j("GET", "/v1/users/" + encodeURIComponent(u.id) + "/puppets").then(function (d) { return d.puppets || []; });
  }
};

/* ── espinazo VIVO (mismo patrón que la Sala: fetch+reader, NO EventSource — el
 *    Bearer viaja por auth.js; reintenta el 404 porque events.jsonl nace con el
 *    1er evento persistido). onEvent recibe cada evento JSON del stream. ──── */
export function openSpine(spaceId, onEvent) {
  const spine = { stop: false, on: true, events: [] };
  if (!spaceId) { spine.on = false; return spine; }
  let tries = 0;
  (function connect() {
    if (spine.stop) return;
    fetch("/v1/spaces/" + encodeURIComponent(spaceId) + "/stream", { headers: { "Accept": "text/event-stream" } })
      .then(function (r) {
        if (!r.ok || !r.body) {
          if (r.status === 404 && tries++ < 60 && !spine.stop) { setTimeout(connect, 250); return; }
          spine.on = false; return;
        }
        const reader = r.body.getReader(), dec = new TextDecoder(); let buf = "";
        (function pump() {
          if (spine.stop) { try { reader.cancel(); } catch (e) {} return; }
          reader.read().then(function (res) {
            if (spine.stop) { try { reader.cancel(); } catch (e) {} return; }
            if (res.done) { spine.on = false; return; }
            buf += dec.decode(res.value, { stream: true });
            const frames = buf.split("\n\n"); buf = frames.pop();
            frames.forEach(function (frame) {
              const line = frame.split("\n").filter(function (l) { return l.indexOf("data:") === 0; })[0];
              if (!line) return;
              let ev; try { ev = JSON.parse(line.slice(5).trim()); } catch (e) { return; }
              spine.events.push(ev);
              try { onEvent(ev); } catch (e) {}
            });
            pump();
          }).catch(function () { spine.on = false; });
        })();
      }).catch(function () {
        if (tries++ < 60 && !spine.stop) setTimeout(connect, 250);
        else spine.on = false;
      });
  })();
  return spine;
}
