// EL ALMACÉN DE OBRAS, DEL LADO DE LA SALA NUEVA. [Gate 4 · Fase 3 · obra 3.0 · deuda D3]
//
// El contrato de artefactos es de Fase 2 y ya está entero del lado del servidor: identidad
// adentro, versiones con su propia procedencia, tipo validado contra EL vocabulario, y los
// cinco endpoints que esta pantalla consume. FASE1 §6 declaró la ausencia sin disimularla —
// «la Sala vieja son dos columnas: chat + obra renderizada; sala-v2 hoy es sólo el chat»— y
// esto es la otra columna.
//
// NO SE INVENTA NADA ACÁ. Todo lo que sigue existe y funciona en la Sala vieja
// (`sala/sala.html`: `artSid` :1498, `artProv` :2092, `artCreate` :2100, `artEdit`, `artRevert`);
// lo que cambia es la forma —módulo ESM con una superficie chica en vez de funciones sueltas
// dentro de un HTML de 6.000 líneas— y la disciplina: el cliente manda REFERENCIAS y el
// servidor resuelve los hechos (contrato §3.2).
//
// LA CLAVE DE SESIÓN ES LA MISMA, Y ESO ES DELIBERADO. `puppet_sala_sid_<agente>` en
// localStorage es lo que 2.2 §6.2 selló para que cerrar la app y reabrirla no deje la
// Biblioteca vacía con los JSON huérfanos en disco. Usar OTRA clave acá partiría la
// Biblioteca en dos mitades invisibles entre sí: la vieja y la nueva verían obras distintas
// del mismo agente. La clave plena de dominio —(cuenta, agente)— sigue siendo la deuda D1.

const RAIZ = "/v1/sessions";

/** La sesión de obras de este agente. Misma clave y misma promoción del legacy que la vieja. */
export function artSid(puppetId) {
  const k = "puppet_sala_sid_" + (puppetId || "general");
  try {
    const v = localStorage.getItem(k);
    if (v) return v;
    let legacy = null;
    try {
      legacy = sessionStorage.getItem(k);
    } catch (_) {
      /* sin sessionStorage no hay legacy que promover */
    }
    const n =
      legacy ||
      (puppetId || "gen") + "-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    localStorage.setItem(k, n);
    return n;
  } catch (_) {
    // Sin localStorage la sesión vive lo que vive la pestaña. Se degrada, no se rompe —
    // y la Biblioteca de esa pestaña sigue funcionando mientras esté abierta.
    return (puppetId || "gen") + "-" + Date.now().toString(36);
  }
}

/**
 * Las REFERENCIAS del turno. Jamás afirmaciones: `model_final`, `tool_calls`, `degraded` y
 * `tools` los resuelve el servidor leyendo el `events.jsonl` del espacio. Si esta pantalla
 * pudiera declararlos, fabricaría capacidad — que es exactamente lo que el contrato §3.2
 * prohíbe y lo que el anti-grift existe para atrapar.
 */
/* ══ QUÉ MERECE SER OBRA ═══════════════════════════════════════════════════════════════
 *
 * EL DEFECTO, visto en la Biblioteca de la .app instalada: nacía una obra por CADA turno
 * con texto. Entradas reales que quedaron ahí — «A» · «¿El presupuesto lo querés mensual o
 * anual?» · «Preguntame con opciones si el informe lo querés corto o largo». Nada de eso es
 * un entregable: son una respuesta de una letra y dos preguntas que el agente hizo.
 *
 * LA ASIMETRÍA QUE DECIDE LA REGLA, y por eso es conservadora: **no crear una obra no
 * pierde nada** —el texto sigue en el hilo, visible y buscable— mientras que crear una de
 * más ensucia la Biblioteca PARA SIEMPRE, y el usuario tiene que borrarla a mano. Ante la
 * duda, no nace. El costo de un falso negativo es cero; el de un falso positivo es
 * permanente.
 *
 * EL CRITERIO ES LA ESTRUCTURA, NO EL LARGO. Un párrafo largo puede ser charla y una tabla
 * corta es un entregable. Medir caracteres habría dejado pasar justo lo que molesta (las
 * preguntas largas del agente) y habría tirado lo que sirve. Lo que se mira es si el turno
 * CONSTRUYÓ algo:
 *
 *   · la obra rica          → SIEMPRE. El backend ya la tipó; acá no se opina.
 *   · una tabla markdown    → dos filas con `|` es una tabla, y una tabla es un entregable.
 *   · un bloque cercado     → ```chart, ```html, ```python… el modelo produjo algo, no habló.
 *   · encabezado + cuerpo   → un `# Título` con contenido debajo es un documento.
 *
 * Y UN VETO EXPLÍCITO, que es el caso que más ensuciaba: un turno que TERMINA EN PREGUNTA
 * está pidiendo, no entregando — aunque traiga un encabezado. Se mira el final del texto
 * porque es donde vive la intención del turno.
 */
const _RE_TABLA = /^\s*\|.*\|\s*$/gm;
const _RE_CERCADO = /```[a-zA-Z]*\s*\n[\s\S]*?```/;
const _RE_ENCABEZADO = /^\s*#{1,3}\s+\S+/m;

export function mereceSerObra(cuerpo, rica) {
  if (rica) return true;                       // el backend ya decidió: no se discute
  const t = String(cuerpo || "").trim();
  if (!t) return false;

  // VETO: el turno pregunta en vez de entregar. Se mira la última línea con texto, que es
  // donde el agente deja lo que espera del humano.
  const lineas = t.split("\n").map((l) => l.trim()).filter(Boolean);
  const ultima = lineas[lineas.length - 1] || "";
  if (/\?\s*$/.test(ultima) && lineas.length <= 6) return false;

  if ((t.match(_RE_TABLA) || []).length >= 2) return true;
  if (_RE_CERCADO.test(t)) return true;
  if (_RE_ENCABEZADO.test(t)) {
    // Un encabezado solo no alcanza: «# Listo» no es un documento. Tiene que haber cuerpo
    // debajo — al menos dos líneas más de contenido.
    const sinEncabezados = lineas.filter((l) => !/^#{1,3}\s/.test(l));
    return sinEncabezados.length >= 2;
  }
  return false;
}

export function refsDelTurno({ out, intent, chatId, puppetId, spaceId, workspace }) {
  const p = {
    produced_by: workspace ? "workspace" : out ? "run" : "stream",
    chat_id: chatId || undefined,
    agent_id: puppetId || undefined,
    intent: (intent || "").slice(0, 200) || undefined,
  };
  // [Fase 3 · 3.4] El stack heredado que produjo el contenido. El borde de escritura lo usa
  // para topar `capture_quality` en `declared`: Aleph midió el modelo del turno, no la
  // función que escribió esto.
  if (workspace) p.workspace = workspace;
  if (out || spaceId) {
    p.space_id = spaceId || undefined;
    p.run_id = out?.run_id || undefined;
    if (out?.method) {
      p.method_id = out.method.method_id || undefined;
      p.method_run_id = out.run_id || undefined;
    }
  }
  return p;
}

function url(sid, cola) {
  return RAIZ + "/" + encodeURIComponent(sid) + "/artifacts" + (cola || "");
}

/**
 * La Biblioteca: RESÚMENES, no obras enteras. El almacén devuelve `{id,title,type,
 * created_at,updated_at,n_versions}` a propósito — listar no debería arrastrar el
 * contenido de cada obra ni sus versiones. El cuerpo se pide por `obtener()` cuando hay
 * una obra que dibujar, y una sola por vez.
 */
export async function listar(sid, headers) {
  const r = await fetch(url(sid), { headers: headers() });
  if (!r.ok) throw new Error("artifacts_list_" + r.status);
  const j = await r.json();
  return j?.artifacts || [];
}

/** UNA obra entera: contenido, versiones y procedencia. */
export async function obtener(sid, headers, aid) {
  const r = await fetch(url(sid, "/" + encodeURIComponent(aid)), { headers: headers() });
  if (!r.ok) throw new Error("artifacts_get_" + r.status);
  const j = await r.json();
  return j?.artifact || null;
}

/** Nace una obra con su identidad adentro. Devuelve el artefacto completo, no sólo el id. */
export async function crear(sid, headers, { title, type, content, userId, refs }) {
  const body = { title, type, content, user_id: userId || undefined };
  for (const k in refs || {}) if (refs[k] !== undefined) body[k] = refs[k];
  const r = await fetch(url(sid), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers() },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    // FALLO VISIBLE: el borde rechaza tipado (`artifact_type_invalid` 422,
    // `artifact_session_newer_schema` 409) y ese motivo tiene que llegar a la pantalla.
    // Tragarlo dejaría una obra que el usuario ve y el disco no tiene.
    const d = await r.json().catch(() => null);
    const e = new Error(d?.detail?.error || "artifacts_create_" + r.status);
    e.detalle = d?.detail || null;
    throw e;
  }
  const j = await r.json();
  return j?.artifact || null;
}

/** Edita: el contenido previo va a `versions[]` CON su procedencia (contrato §4). */
export async function editar(sid, headers, aid, { content, title, userId, refs }) {
  const body = { content, title, user_id: userId || undefined };
  for (const k in refs || {}) if (refs[k] !== undefined) body[k] = refs[k];
  const r = await fetch(url(sid, "/" + encodeURIComponent(aid)), {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...headers() },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error("artifacts_edit_" + r.status);
  const j = await r.json();
  return j?.artifact || null;
}

/** Revertir: devuelve contenido Y procedencia previos JUNTOS. 409 = no hay versión. */
export async function revertir(sid, headers, aid) {
  const r = await fetch(url(sid, "/" + encodeURIComponent(aid) + "/revert"), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers() },
    body: "{}",
  });
  if (r.status === 409) {
    const e = new Error("no_version");
    e.sinVersion = true;
    throw e;
  }
  if (!r.ok) throw new Error("artifacts_revert_" + r.status);
  const j = await r.json();
  return j?.artifact || null;
}

/**
 * La URL de descarga. El parámetro es `fmt` (no `format`) y el token puede ir por query
 * porque la descarga suele ser navegación directa, sin headers — así lo declara el
 * endpoint (`router.py`, `artifact_download`). Sin `fmt` el backend elige el primero que
 * el vocabulario declara para el tipo.
 */
export function urlDescarga(sid, aid, fmt, token) {
  const q = [];
  if (fmt) q.push("fmt=" + encodeURIComponent(fmt));
  if (token) q.push("token=" + encodeURIComponent(token));
  return url(sid, "/" + encodeURIComponent(aid) + "/download" + (q.length ? "?" + q.join("&") : ""));
}
