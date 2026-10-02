/* sonda_plugin_cierre.mjs — CORRE el plugin de un workspace y devuelve el cuerpo que le
 * manda a `POST /v1/workspaces/brain/close`.
 *
 * Es ejecución REAL del archivo de producción, no un regex sobre su fuente: un regex
 * sobre `close(…)` mide cómo está escrita la línea, no qué viaja. Los dos `fetch` que el
 * plugin hace se interceptan — el del motor del stack (GET de mensajes) y el de Aleph
 * (POST) — así que no sale un byte a la red ni se toca ningún estado.
 *
 *   node qa/lib/sonda_plugin_cierre.mjs <ruta-al-plugin> <nombre-del-export>
 *   → stdout: JSON  { ok, cierre|motivo }
 */
import { writeFileSync, mkdtempSync } from "node:fs"
import { join } from "node:path"
import { tmpdir } from "node:os"
import { pathToFileURL } from "node:url"

const [, , rutaPlugin, nombreExport] = process.argv
const SID = "sesion-de-la-vara"
const PROMPT = "¿cuánto es 17 por 23?"
const RESPUESTA = "391"

const dir = mkdtempSync(join(tmpdir(), "vara-hilo-"))
const cfgPath = join(dir, "aleph-pack.json")
writeFileSync(cfgPath, JSON.stringify({
  workspace: "vara", base: "http://127.0.0.1:1/", token: "t-vara",
  user_id: "u-vara", chat_id: "chat-de-la-vara", sid: "sid-vara",
  proyecto: dir, log: join(dir, "pack.log"),
}))
process.env.ALEPH_PACK_CONFIG = cfgPath

/* El mensaje que el motor del stack devolvería: un assistant con texto y una cita
 * verificada (Legal no cruza artefacto sin cita, y sin eso su rama no llega al cierre). */
const mensajesDelMotor = [
  { info: { role: "user" }, parts: [{ type: "text", text: PROMPT }] },
  { info: { role: "assistant" }, parts: [
    { type: "text", text: RESPUESTA, metadata: { citations: [{ verified: true, cite: "x" }] } },
  ] },
]

let cierre = null
globalThis.fetch = async (url, init = {}) => {
  const u = String(url)
  if (u.includes("/v1/workspaces/brain/close")) {
    cierre = JSON.parse(init.body || "{}")
    return new Response("{}", { status: 200, headers: { "content-type": "application/json" } })
  }
  if (init.method === "POST") {                    // artefactos y demás: aceptados y descartados
    return new Response("{}", { status: 200, headers: { "content-type": "application/json" } })
  }
  return new Response(JSON.stringify(mensajesDelMotor),
                      { status: 200, headers: { "content-type": "application/json" } })
}

try {
  const mod = await import(pathToFileURL(rutaPlugin).href)
  const fabrica = mod[nombreExport] || mod.default
  if (typeof fabrica !== "function") throw new Error(`export «${nombreExport}» no es una función`)
  const hooks = await fabrica({ serverUrl: "http://127.0.0.1:1", client: {}, $: {}, directory: dir })
  const msg = hooks["chat.message"]
  if (typeof msg !== "function") throw new Error("el plugin no expone «chat.message»")
  await msg({ sessionID: SID }, { parts: [{ type: "text", text: PROMPT }] })
  const hdr = hooks["chat.headers"]
  if (typeof hdr === "function") { const o = { headers: {} }; await hdr({ sessionID: SID }, o) }
  if (typeof hooks.event !== "function") throw new Error("el plugin no expone «event»")
  await hooks.event({ event: { type: "session.idle", properties: { sessionID: SID } } })
  process.stdout.write(JSON.stringify({ ok: cierre !== null, cierre }))
} catch (e) {
  process.stdout.write(JSON.stringify({ ok: false, motivo: String(e?.message || e) }))
}
