/**
 * openscience.js — EL PLUGIN QUE LE DA ESPACIO Y PROCEDENCIA A LOS TURNOS DEL WORKSPACE.
 * [Gate 4 · Fase 4 · obra O2 · deuda 6 de la caminata de F3 · H6 de la auditoría]
 *
 * QUÉ RESUELVE
 * ------------
 * Dos agujeros medidos en la caminata de F3-Ciencia, que son el mismo agujero:
 *
 *   · **Sin `X-Aleph-Space`**: el borde de dialecto acepta la cabecera desde el día uno
 *     (`router.py`, `workspace_brain_openai`), pero nadie se la mandaba. Sin espacio no
 *     hay `workspace_step`; sin `workspace_step` no hay procedencia del turno; sin
 *     procedencia **el anti-grift S8 está ciego a todo lo que produce el workspace**.
 *   · **El puente desconectado**: `POST /v1/workspaces/artifacts` estaba construido,
 *     medido con sus 10 clases y servido… y **nadie lo llamaba en producción** (grep sobre
 *     todo el árbol: 2 hits, los dos en una vara). Los artefactos del stack vivían sólo en
 *     su propio almacén y jamás ganaban identidad en la casa.
 *
 * POR QUÉ UN PLUGIN, Y POR QUÉ ACÁ
 * --------------------------------
 * La ley 9 dice: tocar únicamente por la costura que el propio repo dejó. OpenScience
 * dejó tres, y son exactamente las que hacen falta:
 *
 *   `chat.headers`  → `tooling/plugin/src/index.ts:174-177`, disparado en
 *                     `backend/cli/src/session/llm.ts:146-158` con el `sessionID` adentro,
 *                     y aplicado con la precedencia más alta del pedido (`llm.ts:239-241`).
 *   `chat.message`  → el turno EMPIEZA (llega el mensaje del usuario).
 *   `event`         → `session.idle` es el turno TERMINADO (el propio CLI del stack lo usa
 *                     así para cortar su loop: `cli/cmd/run.ts:229`).
 *
 * Y los plugins se cargan desde `config.plugin` aceptando **`file://`**
 * (`src/plugin/index.ts:78-118`): sin `bun add`, sin registry, sin red. Por eso este
 * archivo vive **en el árbol de Aleph** y no adentro de `third_party/`: el stack importado
 * queda byte-idéntico y esta pieza es nuestra, versionada con la casa.
 *
 * MEDIDO ANTES DE ESCRIBIRLO (no asumido): el binario compilado con `bun --compile`
 * **sí** hace `import()` de un `file://` externo. Se probó con un plugin mínimo que
 * escribe una marca al cargarse, contra el binario del pack corriendo aislado.
 *
 * LO QUE ESTE PLUGIN NO HACE
 * --------------------------
 * No toca el borde de dialecto ni el camino del modelo (territorio de F5). No inventa un
 * `tool_call_finished` por lo que el harness ajeno dice haber hecho: el paso se anota como
 * `workspace_step` y el artefacto nace `produced_by:"workspace"`, que topa la calidad de
 * captura en `declared`. **Declarado es la verdad; `exact` sería mentira.**
 *
 * Y **jamás rompe un turno del stack**: todo lo de acá va envuelto. Si Aleph no contesta,
 * el usuario pierde la auditoría de ese turno, no el turno.
 */

const LIMITE_CONTENIDO = 8 * 1024 * 1024 // 8 MiB: por encima de esto se cruza la ficha
const LIMITE_MENSAJES = 40

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

/** Una línea a la bitácora del pack. Un plugin mudo es imposible de diagnosticar. */
async function anotar(cfg, texto) {
  if (!cfg?.log) return
  try {
    const fs = await import("node:fs/promises")
    await fs.appendFile(cfg.log, `[aleph] ${new Date().toISOString()} ${texto}\n`)
  } catch {
    /* la bitácora nunca puede tumbar un turno */
  }
}

/**
 * Un id de espacio que la casa acepta. `provenance.safe_ref` exige
 * `^[A-Za-z0-9._:-]{1,120}$`, así que el `sessionID` se sanea en vez de confiarse.
 */
import { createHash } from "node:crypto"

function nuevoEspacio(sessionID, n) {
  const limpio = String(sessionID || "s").replace(/[^A-Za-z0-9._:-]/g, "").slice(-24)
  return `space-ws-${limpio}-${Date.now().toString(36)}-${n.toString(36)}`
}

function textoDe(partes) {
  return (partes || [])
    .filter((p) => p && p.type === "text" && typeof p.text === "string")
    .map((p) => p.text)
    .join("\n")
    .trim()
}

export const AlephWorkspace = async (input) => {
  let cfg = await ajustes()
  const turnos = new Map() // sessionID → { espacio, turno, desde, prompt }
  let secuencia = 0

  // LOS AJUSTES SE RELEEN AL EMPEZAR CADA TURNO, y no una sola vez al cargar. El pack
  // reescribe ese archivo en cada `enter` —la sesión de Aleph vence, y el hilo del
  // workspace puede cambiar—, pero el proceso del stack SE REUSA entre entradas (el dueño
  // comparte por huella). Un plugin que se quedara con la foto del arranque le hablaría a
  // la casa con una credencial vieja y nadie sabría por qué.
  const refrescar = async () => {
    const nuevo = await ajustes()
    if (nuevo) cfg = nuevo
    return cfg
  }

  if (!cfg) {
    // Sin config del pack no se inventa nada: el stack corre igual, sin auditoría. Es el
    // caso de alguien que levantó el stack a mano, y no tiene por qué fallar por eso.
    return {}
  }
  await anotar(cfg, `plugin cargado · workspace=${cfg.workspace} · aleph=${cfg.base}`)

  const cabeceras = () => {
    const h = { "Content-Type": "application/json" }
    if (cfg.token) h["Authorization"] = `Bearer ${cfg.token}`
    return h
  }

  const aAleph = async (ruta, cuerpo) => {
    const r = await fetch(cfg.base.replace(/\/$/, "") + ruta, {
      method: "POST",
      headers: cabeceras(),
      body: JSON.stringify(cuerpo),
    })
    if (!r.ok) throw new Error(`${ruta} → ${r.status} ${(await r.text()).slice(0, 200)}`)
    return r.json().catch(() => null)
  }

  const alStack = async (ruta) => {
    const r = await fetch(String(input.serverUrl).replace(/\/$/, "") + ruta)
    return r.ok ? r.json() : null
  }

  /** Los BYTES de un archivo del stack, por su propia ruta. `null` si no se pudo. */
  const bytesDelStack = async (ruta, sessionID) => {
    const q = new URLSearchParams({ path: ruta })
    if (sessionID) q.set("sessionID", sessionID)
    const r = await fetch(
      String(input.serverUrl).replace(/\/$/, "") + "/file/raw?" + q.toString(),
    )
    if (!r.ok) return null
    return Buffer.from(await r.arrayBuffer())
  }

  /** Los artefactos que ESTE turno dejó en el stack, cruzados al puente.
   *
   * DE DÓNDE SALEN, Y POR QUÉ NO DE DONDE SALÍAN. Hasta el 2026-08-29 esto leía `/provenance`
   * y filtraba `kind === "artifact"`. MEDIDO contra un Ciencia vivo con tres figuras recién
   * producidas —una sesión de mecánica cuántica que dejó `fig1_eigenstates.png`,
   * `fig2_superposition.png` y `anim_superposition.gif` en disco—:
   *
   *     GET /provenance      → 49 nodos, LOS 49 `kind: "run"`, CERO artefactos
   *     GET /file/artifacts  → 15 artefactos, con esos tres adentro
   *
   * O sea que el filtro no matcheaba nunca y el puente cruzaba cero, siempre, en silencio.
   * El archivo existía, el stack lo conocía —su propio review los lista como «Artifacts on
   * disk» leyendo `File.artifacts`— y en Aleph no había nada que abrir. Ésta es la góndola
   * que el propio stack usa (`session/review.ts:60`), y la ruta acepta `sessionID`.
   */
  async function cruzarArtefactos(t, sessionID) {
    const q = new URLSearchParams()
    if (sessionID) q.set("sessionID", sessionID)
    const lista = await alStack("/file/artifacts" + (q.toString() ? "?" + q : ""))
    const todos = Array.isArray(lista) ? lista : []
    // `modified` viene en milisegundos epoch. Sin él no se puede decir si es de este turno,
    // y cruzar de nuevo las quince de la sesión en cada turno sería peor que no cruzar.
    const nuevos = todos.filter((a) => a && Number(a.modified) >= t.desde)
    let cruzados = 0
    for (const n of nuevos) {
      // El DATO sale del archivo cuando se puede; si no, cruza la REFERENCIA y el puente
      // devuelve una ficha honesta (medido en F3: «un panel en blanco es una mentira; una
      // ficha honesta no»). Nunca se rellena lo que falta.
      const esImagen = /^(figure|image)$/.test(n.kind)
      const datos = {
        name: n.name,
        path: n.path,
        format: n.format,
        bytes: n.size,
      }
      if (n.path && Number(n.size) <= LIMITE_CONTENIDO) {
        try {
          const bin = await bytesDelStack(n.path, sessionID)
          if (bin) {
            datos.content = esImagen ? bin.toString("base64") : bin.toString("utf8")
            datos.encoding = esImagen ? "base64" : "utf8"
          } else {
            datos.omitido = "el stack no me dio los bytes del archivo"
          }
        } catch (e) {
          datos.omitido = `no pude leer el archivo: ${e?.message || e}`
        }
      } else if (n.path) {
        // Sin truncar en silencio: se dice por qué viaja sólo la referencia.
        datos.omitido = `pesa ${n.size} b, por encima del tope de ${LIMITE_CONTENIDO} b`
      }
      try {
        await aAleph("/v1/workspaces/artifacts", {
          sid: cfg.sid || cfg.user_id || "workspace",
          workspace: cfg.workspace,
          kind: n.kind,
          name: n.name,
          title: n.name,
          data: datos,
          user_id: cfg.user_id,
          space_id: t.espacio,
          chat_id: cfg.chat_id,
          // EL PASAPORTE DEL STACK, COMO REFERENCIA — y estaba acá al alcance de la mano.
          //
          // El nodo `artifact` de OpenScience declara `contentHash` (sha256 de los bytes)
          // y un `provenance` entero (`science/provenance/store.ts:38-48`), con el commit
          // del código y el id de la corrida adentro. Hasta esta línea se copiaban cuatro
          // campos de presentación y esos dos se tiraban: un archivo que el stack SÍ
          // ejecutó y SÍ hasheó llegaba a la casa sin ninguna forma de volver.
          //
          // NO cambia el grado. El artefacto sigue naciendo `produced_by:"workspace"` y su
          // `capture_quality` sigue topada en `declared`, porque Aleph midió el modelo y no
          // ejecutó el kernel. Lo que cambia es que la afirmación queda COMPROBABLE — que
          // es la regla que el propio `provenance.py` se escribió («la referencia queda,
          // así cualquiera puede re-derivar después») y que acá no se estaba cumpliendo.
          //
          // Son REFERENCIAS, no dato: tres strings opacos que `provenance.safe_ref` sanea
          // y que nadie lee para decidir nada. Un sobre ajeno que se declare `exact` no
          // compra credibilidad acá, y ése es justamente el punto del tope.
          //
          // ⚠️ ESTA GÓNDOLA NO TRAE EL SOBRE. `/file/artifacts` es un escaneo del disco de la
          // sesión: da nombre, tipo, formato, tamaño y `modified`, y NADA de procedencia —
          // ni `contentHash` ni el `run_id` ni el commit. El grafo sí los tenía… y no tenía
          // los artefactos. No se inventa lo que falta: el sha256 se calcula sobre LOS BYTES
          // QUE ACABAMOS DE LEER, que es una afirmación nuestra y verificable, y los otros
          // dos viajan ausentes en vez de fabricados.
          source_sha256: datos.content && datos.encoding === "base64"
            ? createHash("sha256").update(Buffer.from(datos.content, "base64")).digest("hex")
            : undefined,
        })
        cruzados++
      } catch (e) {
        // Un tipo que el puente RECHAZA con causa no es un error del turno: es el puente
        // haciendo su trabajo (ley 4: lo no reclamado cae a la base, no rompe nada).
        await anotar(cfg, `artefacto no cruzó (${n.kind}): ${e?.message || e}`)
      }
    }
    return cruzados
  }

  async function cerrarTurno(sessionID) {
    const t = turnos.get(sessionID)
    if (!t) return
    turnos.delete(sessionID)
    let respuesta = ""
    try {
      const msgs = await alStack(`/session/${encodeURIComponent(sessionID)}/message?limit=${LIMITE_MENSAJES}`)
      const asistentes = (msgs || []).filter((m) => m?.info?.role === "assistant")
      respuesta = textoDe(asistentes[asistentes.length - 1]?.parts)
    } catch {
      /* sin respuesta legible, el cierre igual va: el `final` del espacio importa más */
    }
    let cruzados = 0
    try {
      // ⚠️ EL CIERRE VA PRIMERO, Y ESTO SE MIDIÓ AL REVÉS ANTES DE ESCRIBIRLO ASÍ.
      //
      // La intuición decía «cruzá el artefacto y después cerrá», para que el espacio no
      // siguiera creciendo después de guardarlo (D-S8-ESPACIO-VIVO). Pero la calidad de la
      // captura se resuelve EN EL MOMENTO DE ESCRIBIR el artefacto
      // (`platform/artifacts/provenance.py:194`): sin evento terminal en el espacio, la
      // calidad es `partial` — y se queda `partial` para siempre. Medido: cruzando antes,
      // el artefacto salía `workspace/partial`; cerrando antes, sale `workspace/declared`,
      // que es el techo honesto que el contrato le pone a lo que produce un workspace.
      //
      // Y de paso es el orden SEGURO para S8: cerrado el espacio, ya no crece después del
      // artefacto, que es justo lo que D-S8-ESPACIO-VIVO advierte.
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
      // se guarda igual, con la calidad que le corresponda. Perder la obra por no poder
      // anotar su cierre sería cobrarle al usuario un problema nuestro.
      await anotar(cfg, `no pude cerrar el turno: ${e?.message || e}`)
    }
    try {
      cruzados = await cruzarArtefactos(t, sessionID)
    } catch (e) {
      await anotar(cfg, `no pude leer la procedencia del stack: ${e?.message || e}`)
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

    /** TERMINA EL TURNO: cruzan los artefactos y se cierra el espacio. */
    event: async ({ event }) => {
      if (event?.type !== "session.idle") return
      await cerrarTurno(event.properties?.sessionID)
    },
  }
}

export default AlephWorkspace
