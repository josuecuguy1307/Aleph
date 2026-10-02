/**
 * dochaus.js — EL PUENTE DE LEGAL: espacio, procedencia, PERMISOS y artefactos.
 * [Legal · artefactos]
 *
 * QUÉ RESOLVÍA ANTES, Y QUÉ LE FALTABA
 * ------------------------------------
 * Este plugin nació chico: repartía el `X-Aleph-Space` de cada turno y, al cerrar,
 * cruzaba UNA cosa —la respuesta de texto, y sólo si traía una cita verificada—. Con eso
 * Legal contestaba preguntas y **no entregaba nunca su oficio**: ni un redline, ni un
 * documento redactado, ni una edición con control de cambios. Las dos causas, medidas
 * leyendo el árbol del stack, y ninguna es del motor de doc.haus:
 *
 * 1 · **EL PERMISO QUE NADIE CONTESTABA.** Las cinco herramientas que PRODUCEN obra
 *     (`draft-document`, `redline`, `tracked-changes`, `word-integration`, `redact`)
 *     están declaradas `"ask"` — y las declara ALEPH, en `script/aleph-legal-config.ts`,
 *     sobre la config que le escribe al pack. Adentro del motor, `"ask"` no es una
 *     pregunta: es `Deferred.await(deferred)` **sin timeout**
 *     (`packages/opencode/src/permission/index.ts:112-118`). Nadie replica → la tool
 *     queda colgada hasta que el watchdog de Aleph mata el turno. doc.haus SUELTO sí lo
 *     produce, porque su app muestra el pedido y el dueño hace click; adentro de Aleph
 *     no hay ninguna superficie que lo muestre, así que el pedido se emitía al vacío.
 *     **No es que Aleph le niegue algo: es que nunca le dio una puerta para contestar.**
 *
 * 2 · **LA COSECHA QUE NO EXISTÍA.** Aun produciéndola, la obra no llegaba a la casa:
 *     este plugin sólo posteaba `legal_review`. Es el mismo agujero que se le midió a
 *     Oficina (`openwork.js` posteaba y la tabla del puente no tenía su clave): lo que
 *     el workspace produce se pierde, y se pierde en silencio.
 *
 * ⚠️ LA TRAMPA QUE COSTÓ LA PRIMERA VERSIÓN DE ESTA OBRA. El paquete de plugins DECLARA
 * un hook `"permission.ask"` (`packages/plugin/src/index.ts:261`) que parece hecho justo
 * para esto. **El motor no lo dispara nunca**: `grep '"permission.ask"'` sobre
 * `packages/opencode/src/` da CERO. Implementarlo habría sido código muerto con cara de
 * arreglo. Lo que el motor SÍ hace es publicar el evento `permission.asked`
 * (`permission/index.ts:114`) por el bus que este plugin ya escucha, y exponer la
 * respuesta por HTTP. Por ahí va el cable, y por eso este archivo no toca una línea del
 * stack importado.
 *
 * DÓNDE VIVEN LOS ARTEFACTOS DE LEGAL, que no es donde vivían los de Oficina
 * -------------------------------------------------------------------------
 * Oficina cosecha barriendo su directorio de proyecto por `mtime`. Acá eso NO sirve, por
 * dos razones medidas: los matters de Legal viven en `<data>/<matter>` y no bajo
 * `<proyecto>` (ver la fila del registro en `router.py`), y **el redline ni siquiera es
 * un archivo** — es una fila en `<matter>/.dochaus/legal.db` (`lib/redlines.ts:27-29`).
 * Un barrido de disco no lo encontraría, y leerle la base al stack sería meterse en su
 * oficio.
 *
 * Por eso la cosecha es POR EL BORDE DE LA HERRAMIENTA: `tool.execute.after` —que el
 * motor sí dispara, cuatro sitios en `session/prompt.ts` y `session/tools.ts`— entrega
 * `{tool, args}` y `{title, output, metadata}`. El `metadata` de cada tool de obra trae
 * el dato REAL (`oldText`/`replacement` del redline, la ruta del `.docx` redactado), y de
 * ahí sale el artefacto sin adivinar nada.
 *
 * Y **jamás rompe un turno del stack**: todo va envuelto. Si Aleph no contesta, el
 * usuario pierde la auditoría de ese turno, no el turno.
 */

const LIMITE_CONTENIDO = 8 * 1024 * 1024 // 8 MiB: por encima de esto cruza la ficha

//: LOS PERMISOS QUE ALEPH CONTESTA QUE SÍ, Y POR QUÉ SÓLO ÉSTOS.
//: Son exactamente las cinco herramientas que producen la obra que el usuario acaba de
//: pedir, y su alcance es el matter abierto. No es un «allow» general: `edit`, `bash` y
//: `websearch` están en `deny` en el ruleset, así que ni siquiera llegan a preguntar
//: (`permission/index.ts:88-90` corta antes), y todo lo demás que pregunta —crear,
//: actualizar o borrar plantillas, playbooks, skills, agentes y workflows— se RECHAZA:
//: eso es biblioteca persistente del dueño, no la obra de este turno.
//:
//: El redline y el tracked-change son PROPUESTAS: quedan en la cola de revisión y el
//: documento canónico no se toca hasta que el dueño las acepta en la app de doc.haus
//: (`tool/redline.ts:20-22`). O sea que decir que sí acá no aprueba un cambio: habilita
//: que la propuesta exista para que alguien pueda mirarla.
const PERMISOS_DE_OBRA = new Set([
  "draft-document", "redline", "tracked-changes", "word-integration", "redact",
])

//: `tool → cómo se llama lo que produjo`. El `kind` es el que el stack DECLARA; la
//: traducción al vocabulario de la casa la hace el puente (`platform/artifacts/bridge.py`),
//: que es donde vive el contrato. Acá no se elige un tipo de Aleph a propósito: si el
//: stack pudiera elegirlo habría dos vocabularios otra vez.
const TOOLS_DE_OBRA = {
  "redline":          { kind: "legal_redline",  que: "redline" },
  "tracked-changes":  { kind: "legal_redline",  que: "cambio con control de cambios" },
  "draft-document":   { kind: "legal_document", que: "documento redactado" },
  "word-integration": { kind: "legal_document", que: "documento editado" },
  "redact":           { kind: "legal_document", que: "documento con tachaduras" },
}

const texto = (parts) => (parts || []).filter((p) => p?.type === "text" && typeof p.text === "string").map((p) => p.text).join("\n").trim()
const espacio = (sid, n) => `space-ws-${String(sid || "s").replace(/[^A-Za-z0-9._:-]/g, "").slice(-24)}-${Date.now().toString(36)}-${n}`

export const AlephLegal = async (input) => {
  const ruta = process.env.ALEPH_PACK_CONFIG
  let cfg = null; try { cfg = ruta ? JSON.parse(await (await import("node:fs/promises")).readFile(ruta, "utf8")) : null } catch {}
  if (!cfg) return {}
  const turnos = new Map(); let n = 0

  /** La bitácora del pack. Nunca rompe un turno, y es donde se lee lo que no se ve. */
  const anotar = async (msg) => {
    if (!cfg?.log) return
    try {
      const fs = await import("node:fs/promises")
      await fs.appendFile(cfg.log, `[${new Date().toISOString()}] dochaus-plugin: ${msg}\n`)
    } catch { /* la bitácora nunca rompe un turno */ }
  }

  const call = async (path, body) => {
    const headers = { "Content-Type": "application/json" }; if (cfg.token) headers.Authorization = `Bearer ${cfg.token}`
    const r = await fetch(cfg.base.replace(/\/$/, "") + path, { method: "POST", headers, body: JSON.stringify(body) })
    if (!r.ok) throw new Error(`${path}: ${r.status} ${(await r.text()).slice(0, 200)}`); return r.json().catch(() => null)
  }

  // ── LA PUERTA QUE FALTABA: CONTESTARLE AL MOTOR ────────────────────────────────────
  //
  // DOS RUTAS, Y SE INTENTAN EN ESE ORDEN A PROPÓSITO. `/permission/:id/reply` es la
  // vigente (`routes/instance/httpapi/groups/permission.ts:31`) y su cuerpo es `{reply}`;
  // `/session/:sid/permissions/:id` sigue registrada pero está anotada `deprecated: true`
  // y su cuerpo se llama `{response}` (`groups/session.ts:74-76`). No es la misma llave
  // con dos nombres: son dos contratos, y mandar el campo equivocado da 400. El respaldo
  // existe porque el motor viaja congelado adentro de la `.app` y una ruta que hoy
  // contesta puede no ser la que conteste después de un `git merge upstream`.
  const responder = async (sid, id, decision, mensaje) => {
    const base = String(input.serverUrl || "").replace(/\/$/, "")
    const h = { "Content-Type": "application/json" }
    const intentos = [
      [`${base}/permission/${encodeURIComponent(id)}/reply`, { reply: decision, ...(mensaje ? { message: mensaje } : {}) }],
      [`${base}/session/${encodeURIComponent(sid)}/permissions/${encodeURIComponent(id)}`, { response: decision }],
    ]
    for (const [url, cuerpo] of intentos) {
      try {
        const r = await fetch(url, { method: "POST", headers: h, body: JSON.stringify(cuerpo) })
        if (r.ok) return true
        await anotar(`el motor rechazó la respuesta al permiso en ${url}: ${r.status}`)
      } catch (e) {
        await anotar(`no pude contestarle al permiso por ${url}: ${e?.message || e}`)
      }
    }
    return false
  }

  /**
   * EL PEDIDO DE PERMISO, CONTESTADO — Y LA DECISIÓN, DICHA.
   *
   * Un `reject` mudo es peor que no contestar: el modelo recibe «el usuario rechazó» y,
   * sin saber por qué, INVENTA el motivo. Eso ya se midió en Oficina (pedía dos cosas que
   * no existen). Por eso el rechazo viaja con su causa escrita, en la lengua del stack,
   * diciendo qué se puede hacer en su lugar.
   *
   * `once` y no `always`: `always` graba una regla que sobrevive al turno, y una
   * aprobación que el dueño nunca vio no tiene por qué durar más que el pedido que la
   * originó.
   */
  const atenderPermiso = async (p) => {
    const permiso = String(p?.permission || "")
    const id = p?.id, sid = p?.sessionID
    if (!id) return
    if (PERMISOS_DE_OBRA.has(permiso)) {
      const ok = await responder(sid, id, "once")
      await anotar(`permiso ${permiso} → ${ok ? "otorgado (once)" : "NO se pudo contestar"}`)
      const t = turnos.get(sid)
      if (t && ok) t.permisos.push(permiso)
      return
    }
    const ok = await responder(sid, id, "reject",
      `Aleph no puede aprobar "${permiso}": adentro de Aleph no hay una pantalla que le ` +
      `muestre este pedido al dueño del matter, y sólo se conceden sin preguntar las ` +
      `herramientas que producen la obra de este turno. No inventes un motivo distinto ni ` +
      `pidas permisos que no existen: di que esta acción hay que hacerla en la app de ` +
      `doc.haus, y sigue con lo que sí puedes hacer aquí.`)
    await anotar(`permiso ${permiso} → rechazado con causa${ok ? "" : " (y NO se pudo contestar)"}`)
  }

  // ── LA COSECHA, POR EL BORDE DE LA HERRAMIENTA ─────────────────────────────────────

  /** Los bytes del archivo que la tool dejó, si se pueden leer. Nunca se rellena nada. */
  const contenidoDe = async (ruta) => {
    const datos = { path: ruta, name: String(ruta).split("/").pop() }
    try {
      const fs = await import("node:fs/promises")
      const st = await fs.stat(ruta)
      datos.size = st.size
      if (st.size > LIMITE_CONTENIDO) {
        // Sin truncar en silencio: se dice por qué viaja sólo la referencia.
        datos.omitido = `pesa ${st.size} b, por encima del tope de ${LIMITE_CONTENIDO} b`
        return datos
      }
      const bin = await fs.readFile(ruta)
      // El `.docx` es binario y Aleph no lo puede re-derivar: viaja en base64 y el puente
      // entrega una ficha honesta. Abrirlo para sacarle el texto sería DERIVAR dato.
      datos.encoding = /\.(docx|pdf)$/i.test(ruta) ? "base64" : "utf8"
      datos.content = bin.toString(datos.encoding)
    } catch (e) {
      datos.omitido = `no pude leer el archivo: ${e?.message || e}`
    }
    return datos
  }

  /**
   * Lo que una tool de obra acaba de producir, en la forma que el puente sabe recibir.
   *
   * El `metadata` de cada tool trae el dato de verdad y de ahí sale todo: del redline,
   * `oldText` y `replacement` —el antes y el después REALES, los que quedaron grabados en
   * la cola de revisión—; del documento, la ruta absoluta del `.docx`. Lo que la tool no
   * devolvió no se completa: si no hay `oldText`, el artefacto viaja sin él y el puente
   * dirá lo que falta en vez de pintar un panel en blanco.
   */
  const obraDe = async (tool, meta, salida) => {
    const fila = TOOLS_DE_OBRA[tool]
    if (!fila) return null
    const m = meta && typeof meta === "object" ? meta : {}
    const doc = typeof m.document === "string" ? m.document : null
    const nombreDoc = doc ? doc.split("/").pop() : null

    if (fila.kind === "legal_redline") {
      // Un redline sin el antes NI el después no es un redline: sería una ficha que dice
      // «hubo un cambio» sin decir cuál. Se deja pasar igual —con lo que haya— y el
      // puente decide; lo que no se hace es fabricar el lado que falta.
      return {
        kind: fila.kind,
        name: `Redline en ${nombreDoc || "el documento"}`,
        data: {
          name: `Redline en ${nombreDoc || "el documento"}`,
          document: nombreDoc, path: doc,
          // `oldText` es del redline por cláusula; `find` es del tracked-change
          // quirúrgico. Son el mismo lado del cambio con dos nombres, y el que exista
          // depende de qué tool corrió — no de una preferencia nuestra.
          antes: typeof m.oldText === "string" ? m.oldText : (typeof m.find === "string" ? m.find : null),
          despues: typeof m.replacement === "string" ? m.replacement : (typeof m.replace === "string" ? m.replace : null),
          autor: m.author ?? null,
          redline_id: m.redline ?? null,
          alcance: fila.que,
          resumen: typeof salida === "string" ? salida : null,
        },
      }
    }

    if (!doc) return null
    const datos = await contenidoDe(doc)
    return {
      kind: fila.kind,
      name: datos.name,
      data: { ...datos, que_es: fila.que, resumen: typeof salida === "string" ? salida : null },
    }
  }

  const cruzar = async (t, obra) => {
    try {
      await call("/v1/workspaces/artifacts", {
        sid: cfg.sid || cfg.user_id || "workspace", workspace: cfg.workspace,
        kind: obra.kind, name: obra.name, title: obra.name, data: obra.data,
        space_id: t.space, user_id: cfg.user_id, chat_id: cfg.chat_id,
      })
      return true
    } catch (e) {
      // Un tipo que el puente RECHAZA con causa no es un error del turno: es el puente
      // haciendo su trabajo. Pero se ANOTA — el silencio de esta misma línea es lo que
      // hizo que el 100 % de lo que producía Oficina se perdiera sin que nadie lo supiera.
      await anotar(`artefacto no cruzó (${obra.kind} · ${obra.name}): ${e?.message || e}`)
      return false
    }
  }

  const cerrar = async (sid) => {
    const t = turnos.get(sid); if (!t) return
    try {
      const r = await fetch(String(input.serverUrl).replace(/\/$/, "") + `/session/${encodeURIComponent(sid)}/message`)
      const mensajes = r.ok ? await r.json() : []
      const ultimo = [...mensajes].reverse().find((m) => m?.info?.role === "assistant")
      const respuesta = texto(ultimo?.parts)
      const citas = (ultimo?.parts || []).flatMap((p) => Array.isArray(p?.metadata?.citations) ? p.metadata.citations : []).filter((c) => c?.verified)
      if (respuesta && citas.length) await call("/v1/workspaces/artifacts", { sid: cfg.sid || cfg.user_id || "workspace", workspace: cfg.workspace, kind: "legal_review", name: "Revisión legal con cita verificada", title: "Revisión legal", data: { name: "Revisión legal", content: respuesta, citations: citas, citation_count: citas.length }, space_id: t.space, user_id: cfg.user_id, chat_id: cfg.chat_id })
      // [convergencia · superficie 1] `prompt` FALTABA, y `chat.message` ya lo tenía guardado
      // al lado (`t.prompt`). Sin él, `_chat_record_user` no dispara y el hilo de Legal
      // guardaba la respuesta sin la pregunta: medido en la DB real, 0 mensajes `user` y 1
      // `agent`. Una conversación de una sola voz no es una conversación.
      //
      // ⚠️ EL CIERRE VA ANTES QUE EL CRUCE, por la misma razón medida en Ciencia y Oficina:
      // la calidad de la captura se resuelve AL ESCRIBIR el artefacto
      // (`platform/artifacts/provenance.py`), y sin evento terminal en el espacio queda
      // `partial` para siempre.
      await call("/v1/workspaces/brain/close", { space_id: t.space, workspace: cfg.workspace, answer: respuesta, prompt: t.prompt, turns: t.turnos, user_id: cfg.user_id, chat_id: cfg.chat_id })
    } catch { /* la auditoría no puede romper una revisión */ }
    // Las obras se cruzan AUNQUE el cierre haya fallado: el artefacto es el trabajo del
    // usuario y se guarda igual, con la calidad que le corresponda.
    try {
      let cruzadas = 0
      for (const obra of t.obras) if (await cruzar(t, obra)) cruzadas++
      if (t.obras.length) await anotar(`turno con obra: ${cruzadas}/${t.obras.length} artefacto(s) cruzado(s)`)
    } catch (e) {
      await anotar(`no pude cruzar las obras del turno: ${e?.message || e}`)
    } finally { turnos.delete(sid) }
  }

  const nuevo = (sid) => { n += 1; const t = { space: espacio(sid, n), turnos: 0, obras: [], permisos: [] }; turnos.set(sid, t); return t }

  return {
    "chat.message": async (i, o) => { const t = nuevo(i.sessionID); t.prompt = texto(o?.parts) },
    "chat.headers": async (i, o) => { let t = turnos.get(i.sessionID); if (!t) t = nuevo(i.sessionID); t.turnos += 1; o.headers["X-Aleph-Space"] = t.space; o.headers["X-Aleph-Turn"] = String(t.turnos); if (cfg.chat_id) o.headers["X-Aleph-Chat"] = cfg.chat_id },
    // La obra se junta acá y se cruza al cerrar. Si el turno murió antes del `session.idle`
    // no se cruza nada, que es lo correcto: un artefacto sin turno cerrado no tiene espacio
    // al que pertenecer.
    "tool.execute.after": async (i, o) => {
      try {
        const t = turnos.get(i.sessionID); if (!t) return
        const obra = await obraDe(i.tool, o?.metadata, o?.output)
        if (obra) { t.obras.push(obra); await anotar(`obra producida por ${i.tool}: ${obra.name}`) }
      } catch (e) { await anotar(`no pude leer la obra de ${i?.tool}: ${e?.message || e}`) }
    },
    event: async ({ event }) => {
      if (event?.type === "session.idle") return await cerrar(event.properties?.sessionID)
      if (event?.type === "permission.asked") { try { await atenderPermiso(event.properties) } catch (e) { await anotar(`no pude atender el permiso: ${e?.message || e}`) } }
    },
  }
}
export default AlephLegal
