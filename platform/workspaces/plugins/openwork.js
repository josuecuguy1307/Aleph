/**
 * openwork.js — EL PLUGIN QUE LE DA ESPACIO Y PROCEDENCIA A LOS TURNOS DE OFICINA.
 * [Gate 4 · F6-oficina · obra C]
 *
 * QUÉ RESUELVE
 * ------------
 * El borde de dialecto acepta `X-Aleph-Space` desde el día uno
 * (`router.py::workspace_brain_openai`), pero la config de un proveedor sólo puede
 * declarar cabeceras FIJAS, y el espacio no es fijo: nace y muere con cada turno. Sin
 * espacio no hay `workspace_step`; sin `workspace_step` no hay procedencia; sin
 * procedencia **el anti-grift S8 está ciego a todo lo que produce el workspace**.
 *
 * POR QUÉ UN PLUGIN, Y POR QUÉ ÉSTE Y NO EL DE CIENCIA
 * ----------------------------------------------------
 * El motor de Oficina es `opencode`, y su API de plugins es la misma que ya usa el plugin
 * de Ciencia (`chat.message`, `chat.headers`, `chat.params`, `chat.completion` — medido
 * sobre el binario v1.17.11, no supuesto). La mitad del espacio, entonces, es idéntica.
 *
 * Lo que NO se puede compartir es el cruce de artefactos, y ahí está la diferencia real
 * entre los dos stacks: **OpenScience tiene un grafo de procedencia** (`GET /provenance`)
 * y **OpenWork tiene archivos**. Sus «artefactos» son literalmente los archivos que el
 * agente deja en el directorio del proyecto —medido en su propia vara,
 * `apps/server/src/artifact-files.e2e.test.ts:22-30`, que los siembra como
 * `reports/*.{md,csv,xlsx,pptx,docx,html}`—. Por eso acá el turno se cierra mirando el
 * disco y no un grafo.
 *
 * CÓMO LLEGA A CARGARSE, sin tocarle una línea al stack: el pack escribe
 * `{config}/opencode/opencode.json` con `plugin: ["file://…"]`, y el motor lo carga desde
 * su `OPENCODE_CONFIG_DIR`. Medido el 2026-08-10 contra el binario: un plugin de prueba
 * declarado ahí se carga **aunque `OPENCODE_CONFIG` apunte a otro archivo** — las dos
 * fuentes se funden. Se eligió esa vía y no `POST /workspace/:id/plugins` porque esa ruta
 * pasa por `requireApproval`, y una aprobación manual en medio del `enter` sería un
 * workspace que no abre hasta que alguien diga que sí.
 *
 * Por eso este archivo vive en el árbol de ALEPH y no adentro de `third_party/`: el stack
 * importado queda byte-idéntico y la pieza que le habla a la casa se versiona con la casa.
 *
 * ⭐ CONVERGENCIA: comparte esqueleto con `openscience.js`. Se dejaron los dos separados a
 * propósito —tocar el de Ciencia para factorizar arriesgaba una regresión en un vertical
 * ya mergeado—, y la factorización queda anotada como candidata de la tanda final.
 *
 * Y **jamás rompe un turno del stack**: todo va envuelto. Si Aleph no contesta, el usuario
 * pierde la auditoría de ese turno, no el turno.
 */

const LIMITE_CONTENIDO = 8 * 1024 * 1024 // 8 MiB: por encima de esto cruza la ficha
const LIMITE_MENSAJES = 40
//: Lo que NO es obra del usuario aunque cambie de fecha: config del propio motor, basura
//: de sistema y el estado que el stack escribe solo. Sin esto, cada turno «produciría»
//: artefactos que nadie hizo.
const IGNORAR = [
  /(^|\/)\.git(\/|$)/, /(^|\/)node_modules(\/|$)/, /(^|\/)\.opencode(\/|$)/,
  /(^|\/)\.DS_Store$/, /(^|\/)\.gitignore$/, /(^|\/)opencode\.jsonc?$/,
  /(^|\/)openwork\.jsonc?$/, /(^|\/)AGENTS\.md$/,
]

/** Lee la config que el pack dejó (0600). Es la ÚNICA fuente: base, sesión, dueño, hilo. */
async function ajustes() {
  const ruta = process.env["ALEPH_PACK_CONFIG"]
  if (!ruta) return null
  const fs = await import("node:fs/promises")
  try {
    return JSON.parse(await fs.readFile(ruta, "utf8"))
  } catch {
    return null
  }
}

async function anotar(cfg, texto) {
  if (!cfg?.log) return
  try {
    const fs = await import("node:fs/promises")
    await fs.appendFile(cfg.log, `[${new Date().toISOString()}] openwork-plugin: ${texto}\n`)
  } catch {
    /* la bitácora nunca rompe un turno */
  }
}

function nuevoEspacio(sessionID, n) {
  const corto = String(sessionID || "s").replace(/[^a-zA-Z0-9]/g, "").slice(-12)
  return `ws_oficina_${corto}_${n}`
}

function textoDe(partes) {
  return (partes || [])
    .filter((p) => p?.type === "text" && typeof p.text === "string")
    .map((p) => p.text)
    .join("\n")
    .trim()
}

/** Todo archivo bajo `raiz`, con su mtime. Sin seguir enlaces y sin los ignorados. */
async function archivosDe(raiz) {
  const fs = await import("node:fs/promises")
  const path = await import("node:path")
  const salida = []
  async function caminar(dir) {
    let entradas = []
    try {
      entradas = await fs.readdir(dir, { withFileTypes: true })
    } catch {
      return
    }
    for (const e of entradas) {
      const completo = path.join(dir, e.name)
      const rel = path.relative(raiz, completo)
      if (IGNORAR.some((re) => re.test(rel))) continue
      if (e.isDirectory()) {
        await caminar(completo)
      } else if (e.isFile()) {
        try {
          const st = await fs.stat(completo)
          salida.push({ path: completo, rel, mtimeMs: st.mtimeMs, size: st.size })
        } catch {
          /* un archivo que desaparece entre readdir y stat no es un error */
        }
      }
    }
  }
  await caminar(raiz)
  return salida
}

//: Extensión → el `kind` CRUDO que el stack declara. El puente lo traduce al vocabulario
//: canónico (`platform/artifacts/bridge.py`); acá no se elige tipo de la casa a propósito,
//: porque si el stack pudiera elegirlo habría dos vocabularios otra vez.
function claseDe(rel) {
  const ext = (rel.split(".").pop() || "").toLowerCase()
  if (ext === "xlsx" || ext === "csv") return "spreadsheet"
  if (ext === "docx" || ext === "md" || ext === "txt") return "document"
  if (ext === "pptx") return "presentation"
  if (ext === "pdf") return "document"
  if (ext === "html" || ext === "htm") return "page"
  if (["png", "jpg", "jpeg", "webp", "gif", "svg"].includes(ext)) return "image"
  return "file"
}

function esBinario(rel) {
  const ext = (rel.split(".").pop() || "").toLowerCase()
  return ["xlsx", "docx", "pptx", "pdf", "png", "jpg", "jpeg", "webp", "gif"].includes(ext)
}

export const AlephOficina = async (input) => {
  let cfg = await ajustes()
  const turnos = new Map() // sessionID → { espacio, turno, desde, prompt }
  let secuencia = 0

  // LOS AJUSTES SE RELEEN AL EMPEZAR CADA TURNO. El pack reescribe ese archivo en cada
  // `enter` —la sesión de Aleph vence— pero el proceso del stack SE REUSA entre entradas
  // (el dueño comparte por huella). Un plugin que se quedara con la foto del arranque le
  // hablaría a la casa con una credencial vieja y nadie sabría por qué.
  const refrescar = async () => {
    const nuevo = await ajustes()
    if (nuevo) cfg = nuevo
    return cfg
  }

  if (!cfg) {
    // Sin config del pack no se inventa nada: el stack corre igual, sin auditoría. Es el
    // caso de alguien que levantó el motor a mano, y no tiene por qué fallar por eso.
    return {}
  }
  await anotar(cfg, `plugin cargado · workspace=${cfg.workspace} · aleph=${cfg.base}`)

  const aAleph = async (ruta, cuerpo) => {
    const h = { "Content-Type": "application/json" }
    if (cfg.token) h["Authorization"] = `Bearer ${cfg.token}`
    const r = await fetch(cfg.base.replace(/\/$/, "") + ruta, {
      method: "POST", headers: h, body: JSON.stringify(cuerpo),
    })
    if (!r.ok) throw new Error(`${ruta} → ${r.status} ${(await r.text()).slice(0, 200)}`)
    return r.json().catch(() => null)
  }

  /**
   * LA CREDENCIAL DEL MOTOR YA ESTÁ ACÁ ADENTRO — sólo había que usarla.
   *
   * El motor de Oficina lo levanta el server de OpenWork, y al hacerlo le genera un
   * usuario y una contraseña al azar y se los pasa EN EL ENTORNO DEL PROPIO PROCESO
   * (`apps/server/src/managed-opencode.ts:70-83`). Este plugin corre DENTRO de ese
   * proceso, así que la tiene en su `process.env` desde siempre. La obra no es escribir
   * un mecanismo de auth: es enchufar el que ya existe.
   *
   * MEDIDO 2026-08-14 contra el motor vivo del pack, con la llamada exacta de abajo:
   *
   *   GET /session/<sid>/message?limit=40   sin credencial                   → 401
   *   GET /session/<sid>/message?limit=40   Basic base64(user:pass) del env  → 200, 2 mensajes
   *   … y con `?directory=` además                                          → 200, igual
   *
   * `directory` NO hacía falta: era sólo el auth. Y el motor de Legal contesta 200 sin
   * cabecera (medido) porque a él nadie le puso credencial — por eso su plugin gemelo
   * (`dochaus.js:19`) hace el mismo `fetch` pelado y funciona. No hay patrón que copiar
   * de allá: lo que difiere no es el plugin, es la puerta.
   *
   * Sin credencial en el entorno se manda la llamada pelada, que es exactamente lo que
   * necesita un motor sin auth (Legal, o uno levantado a mano).
   */
  const credencialDelMotor = () => {
    const u = process.env.OPENCODE_SERVER_USERNAME
    const p = process.env.OPENCODE_SERVER_PASSWORD
    if (!u || !p) return {}
    return { Authorization: "Basic " + Buffer.from(`${u}:${p}`).toString("base64") }
  }

  const alMotor = async (ruta) => {
    // EL FALLO DEJA DE SER MUDO. El `catch { return null }` de antes convertía un 401 en
    // «no hay mensajes», y el turno se cerraba con `answer: ""` sin una línea en ningún
    // lado: 0 de 22 turnos de Oficina llegaron al ledger con su respuesta, medido. El
    // valor de retorno sigue siendo `null` a propósito —la auditoría no puede romper un
    // turno— pero ahora la causa queda escrita donde se la puede leer.
    try {
      const r = await fetch(String(input.serverUrl || "").replace(/\/$/, "") + ruta,
                            { headers: credencialDelMotor() })
      if (r.ok) return await r.json()
      await anotar(cfg, `el motor rechazó ${ruta}: ${r.status}`)
      return null
    } catch (e) {
      await anotar(cfg, `no pude preguntarle al motor por ${ruta}: ${e?.message || e}`)
      return null
    }
  }

  /** Los archivos que ESTE turno dejó en el proyecto, cruzados al puente. */
  async function cruzarArtefactos(t) {
    if (!cfg.proyecto) return 0
    const nuevos = (await archivosDe(cfg.proyecto)).filter((f) => f.mtimeMs >= t.desde)
    let cruzados = 0
    for (const f of nuevos) {
      // El DATO sale del archivo cuando se puede; si no, cruza la REFERENCIA y el puente
      // devuelve una ficha honesta (medido en F3: «un panel en blanco es una mentira; una
      // ficha honesta no»). Nunca se rellena lo que falta.
      const datos = { name: f.rel.split("/").pop(), path: f.path, bytes: f.size, rel: f.rel }
      if (f.size <= LIMITE_CONTENIDO) {
        try {
          const fs = await import("node:fs/promises")
          const bin = await fs.readFile(f.path)
          datos.encoding = esBinario(f.rel) ? "base64" : "utf8"
          datos.content = bin.toString(datos.encoding)
        } catch (e) {
          datos.omitido = `no pude leer el archivo: ${e?.message || e}`
        }
      } else {
        // Sin truncar en silencio: se dice por qué viaja sólo la referencia.
        datos.omitido = `pesa ${f.size} b, por encima del tope de ${LIMITE_CONTENIDO} b`
      }
      try {
        await aAleph("/v1/workspaces/artifacts", {
          sid: cfg.sid || cfg.user_id || "workspace",
          workspace: cfg.workspace,
          kind: claseDe(f.rel),
          name: datos.name,
          title: datos.name,
          data: datos,
          user_id: cfg.user_id,
          space_id: t.espacio,
          chat_id: cfg.chat_id,
        })
        cruzados++
      } catch (e) {
        // Un tipo que el puente RECHAZA con causa no es un error del turno: es el puente
        // haciendo su trabajo (ley 4: lo no reclamado cae a la base, no rompe nada).
        await anotar(cfg, `artefacto no cruzó (${f.rel}): ${e?.message || e}`)
      }
    }
    return cruzados
  }

  async function cerrarTurno(sessionID) {
    const t = turnos.get(sessionID)
    if (!t) return
    turnos.delete(sessionID)
    let respuesta = ""
    const msgs = await alMotor(`/session/${encodeURIComponent(sessionID)}/message?limit=${LIMITE_MENSAJES}`)
    if (Array.isArray(msgs)) {
      const asistentes = msgs.filter((m) => m?.info?.role === "assistant")
      respuesta = textoDe(asistentes[asistentes.length - 1]?.parts)
    }
    let cruzados = 0
    try {
      // ⚠️ EL CIERRE VA PRIMERO — misma razón medida que en Ciencia: la calidad de la
      // captura se resuelve AL ESCRIBIR el artefacto (`platform/artifacts/provenance.py:194`),
      // y sin evento terminal en el espacio queda `partial` para siempre. Cerrando antes
      // sale `declared`, que es el techo honesto de lo que produce un workspace.
      await aAleph("/v1/workspaces/brain/close", {
        space_id: t.espacio,
        workspace: cfg.workspace,
        answer: respuesta,
        ok: true,
        turns: t.turno,
        user_id: cfg.user_id,
        chat_id: cfg.chat_id,
        prompt: t.prompt,
      })
    } catch (e) {
      // Un cierre que falla NO cancela el cruce: el artefacto es el trabajo del usuario y
      // se guarda igual, con la calidad que le corresponda.
      await anotar(cfg, `no pude cerrar el turno: ${e?.message || e}`)
    }
    try {
      cruzados = await cruzarArtefactos(t)
    } catch (e) {
      await anotar(cfg, `no pude leer los archivos del proyecto: ${e?.message || e}`)
    }
    await anotar(cfg, `turno cerrado · espacio=${t.espacio} · pasos=${t.turno} · artefactos=${cruzados}`)
  }

  return {
    /** EMPIEZA EL TURNO: nace su espacio. */
    "chat.message": async (inp, out) => {
      try {
        await refrescar()
        secuencia += 1
        turnos.set(inp.sessionID, {
          espacio: nuevoEspacio(inp.sessionID, secuencia),
          turno: 0,
          desde: Date.now(),
          prompt: textoDe(out?.parts).slice(0, 4000),
        })
      } catch (e) {
        await anotar(cfg, `no pude abrir el turno: ${e?.message || e}`)
      }
    },

    /** CADA PASO DEL HARNESS: la cabecera que le faltaba al borde. */
    "chat.headers": async (inp, out) => {
      try {
        let t = turnos.get(inp.sessionID)
        if (!t) {
          // Un paso sin `chat.message` previo (una sesión que arrancó antes que nosotros)
          // igual merece espacio: sin esto, ese turno sería otra vez invisible para S8.
          secuencia += 1
          t = { espacio: nuevoEspacio(inp.sessionID, secuencia), turno: 0, desde: Date.now(), prompt: "" }
          turnos.set(inp.sessionID, t)
        }
        t.turno += 1
        out.headers["X-Aleph-Space"] = t.espacio
        out.headers["X-Aleph-Turn"] = String(t.turno)
        if (cfg.chat_id) out.headers["X-Aleph-Chat"] = cfg.chat_id
      } catch (e) {
        await anotar(cfg, `no pude poner la cabecera del espacio: ${e?.message || e}`)
      }
    },

    /**
     * [Ó11 · la mitad de la casa] CADA TOOL SENSIBLE QUEDA ANOTADA, la frene quien la frene.
     *
     * El bloqueo NO se hace acá y no podría hacerse: la puerta que de verdad detiene la
     * acción es la del motor (`permission: {bash: {...}}`), porque es el motor el que
     * ejecuta. Este hook es la otra mitad —la auditoría de la casa— y por eso corre para
     * TODA invocación de las manos cloud, la apruebe el usuario o la rechace.
     *
     * Va a un JSONL en el dir de datos de Aleph y no a un evento de la casa porque HOY no
     * existe un endpoint de auditoría de workspace (los que hay son cerebro, artefactos,
     * enter/leave). Promoverlo a evento consultable es obra aparte, anotada en el acta:
     * inventarle un endpoint acá habría sido construir el diseño que el dueño descartó.
     */
    "tool.execute.before": async (inp, out) => {
      try {
        const orden = String(out?.args?.command ?? out?.args?.cmd ?? "")
        if (!/(^|[\s;&|])gws(\s|$)/.test(orden)) return
        const t = turnos.get(inp?.sessionID)
        const fs = await import("node:fs/promises")
        const path = await import("node:path")
        const destino = path.join(path.dirname(cfg.log || "/tmp/pack.log"), "o11-manos-cloud.jsonl")
        await fs.appendFile(destino, JSON.stringify({
          cuando: new Date().toISOString(),
          workspace: cfg.workspace,
          user_id: cfg.user_id,
          espacio: t?.espacio || null,
          sesion: inp?.sessionID || null,
          tool: inp?.tool || "bash",
          orden,
        }) + "\n")
      } catch (e) {
        await anotar(cfg, `no pude anotar la acción de manos cloud: ${e?.message || e}`)
      }
    },

    /** TERMINA EL TURNO: se cierra el espacio y cruzan los archivos que dejó. */
    event: async ({ event }) => {
      if (event?.type !== "session.idle") return
      await cerrarTurno(event.properties?.sessionID)
    },
  }
}

export default AlephOficina
