// EL ADAPTADOR AG-UI.
//
// Traduce el sobre de Gate 3 al protocolo AG-UI. Es un ADAPTADOR en el sentido estricto:
// el backend de modelos sigue siendo el de Gate 1-3; la Sala nueva sólo usa su borde raw
// y vuelve sus señales al vocabulario que entiende.
//
// Se hereda de `AbstractAgent` porque es LA COSTURA QUE EL PROPIO REPO DEJÓ:
// `third_party/ag-ui/.../client/src/agent/agent.ts:140` declara
// `abstract run(input): Observable<BaseEvent>` y nada más. No se abre el cuerpo de ninguna
// clase ajena: se implementa un método abstracto, que es su punto de extensión público.
//
// ═══════════════════════════════════════════════════════════════════════════════════════
//  TABLA DE MAPEO — caso por caso
// ═══════════════════════════════════════════════════════════════════════════════════════
//
//  A · CHARLA — `POST /v1/puppets/run/stream` (router.py:2489-2581)
//
//  | frame de Aleph        | evento AG-UI                          | nota                        |
//  |-----------------------|---------------------------------------|-----------------------------|
//  | (apertura)            | RUN_STARTED                           | AG-UI exige que sea el 1º   |
//  | `token` {text}        | TEXT_MESSAGE_START (1ª vez)           | el START se emite perezoso: |
//  |                       | + TEXT_MESSAGE_CONTENT {delta}        | recién con el primer token  |
//  | `thinking` {text}     | REASONING_START + REASONING_MESSAGE_* | secuencia completa; Aleph   |
//  |                       |                                       | jamás fabrica thinking      |
//  | `turno` {turno_id}    | CUSTOM `aleph.turno`                  | id para `/v1/turnos/detener`|
//  | `modelo_sustituido`   | CUSTOM `aleph.modelo_sustituido`      | obra B de Gate 3: se anuncia|
//  | `sesion_perdida`      | CUSTOM `aleph.sesion_perdida`         | obra 6: aviso, NO error     |
//  | `usage` {tokens}      | CUSTOM `aleph.usage`                  | informativo, no gobierna    |
//  | `done` {answer}       | CUSTOM `aleph.veredicto`              | ES el entregable del turno: |
//  |                       | + TEXT_MESSAGE_END + RUN_FINISHED     | sin esto no nacía NINGUNA   |
//  |                       |                                       | obra por el camino charla   |
//  | `error` {detail}      | RUN_ERROR {message}                   | + la causa tipada si viene  |
//
//  B · OBRA EQUIPADA — `POST /v1/puppets/run` + `GET /v1/spaces/{id}/stream`
//      (taxonomía: platform/flywheel/EVENTS-SCHEMA.md)
//
//  | evento del espinazo   | evento AG-UI                          | nota                        |
//  |-----------------------|---------------------------------------|-----------------------------|
//  | `belt_ready`          | STEP_STARTED `cinturon`               | + STEP_FINISHED inmediato   |
//  | `turn_started`        | STEP_STARTED `turno:N`                | un paso por turno del loop  |
//  | `tool_call_started`   | TOOL_CALL_START + TOOL_CALL_ARGS      | `parentMessageId` = el hilo |
//  | `tool_call_finished`  | TOOL_CALL_END + TOOL_CALL_RESULT      | `status` ok/error va en el  |
//  |   status ok\|error    |                                       | CUSTOM `aleph.tool_meta`    |
//  | `tool_call_finished`  | TOOL_CALL_END (sin RESULT)            | `gated` = NO se ejecutó:    |
//  |   status `gated`      | + CUSTOM `aleph.gate_waiting`         | inventar un result mentiría |
//  | `gate_waiting`        | CUSTOM `aleph.gate_waiting` {gate_ux} | ver «por qué CUSTOM» abajo  |
//  | `gate_resolved`       | CUSTOM `aleph.gate_resolved`          | {approved, timed_out}       |
//  | `artifact_created`    | CUSTOM `aleph.artifact`               | el CONTRATO de artefactos   |
//  |                       |                                       | es Fase 2: acá no se inventa|
//  | `equipment_changed`   | STATE_DELTA (JSON Patch RFC 6902)     | es estado de verdad         |
//  | `final` {answer}      | TEXT_MESSAGE_* con la respuesta       | sólo si no se streameó ya   |
//  | `closed` {ok,…}       | RUN_FINISHED  (ok:true)               | terminal honesto del run    |
//  |                       | RUN_ERROR     (ok:false)              |                             |
//
//  B.bis · Los que el stream emite y EVENTS-SCHEMA.md NO documenta. Se agregaron mirando
//  un `events.jsonl` real, no el documento (ver `envelope.js`):
//
//  | evento                | evento AG-UI                          | nota                        |
//  |-----------------------|---------------------------------------|-----------------------------|
//  | `cost`                | CUSTOM `aleph.costo`                  | **es el PRIMER evento del   |
//  |                       |                                       | turno**: el primer signo de |
//  |                       |                                       | vida sale de acá            |
//  | `metric` `notice`     | CUSTOM `aleph.<tipo>`                 | informativos, no alarman    |
//  | `text` `plan_declared`|                                       |                             |
//  | `client_call`         |                                       |                             |
//  | `delegation_serialized`|                                      |                             |
//  | `sub_agent_started`   | STEP_STARTED `subagente:<slug>`       | un paso por sub-agente, +   |
//  |                       | + CUSTOM `aleph.paso` {sub,task,depth}| el NOMBRE y la TAREA        |
//  | `sub_agent_finished`  | STEP_FINISHED `subagente:<slug>`      | + el veredicto y lo que     |
//  |                       | + CUSTOM `aleph.paso_fin` {status,…}  | devolvió el hijo            |
//  |                       |                                       | La clave es el SLUG, no el  |
//  |                       |                                       | nombre: `meta_name` sólo    |
//  |                       |                                       | viene en el `started` y     |
//  |                       |                                       | casar por él dejaba el paso |
//  |                       |                                       | abierto para siempre.       |
//  | `loop_detected`       | CUSTOM `aleph.limite`                 | límites REALES del turno:   |
//  | `budget_exhausted`    |                                       | el usuario tiene que verlos |
//  | `brain_window_exhausted` |                                    |                             |
//  | `context_compacted`   |                                       |                             |
//  | `shared_bus_denied`   |                                       |                             |
//  | (cualquier otro)      | CUSTOM `aleph.evento_desconocido`     | se VE — así se descubrió    |
//  |                       |                                       | que faltaban éstos          |
//
//  ── Por qué `gate_waiting` es CUSTOM y no un interrupt de AG-UI ────────────────────────
//  AG-UI modela la interrupción como `RUN_FINISHED` con `outcome.type === "interrupt"`:
//  el run TERMINA y se reanuda con otro run. El gate de Aleph no funciona así — el run
//  sigue vivo, retenido server-side (`held_actions`), y se resuelve con un POST aparte a
//  `/v1/runs/{id}/approve` que NO abre un run nuevo. Mapearlo a `RUN_FINISHED` haría que
//  la pantalla diera el turno por terminado mientras el backend sigue esperando: una
//  pantalla que miente. CUSTOM dice la verdad y deja el run abierto, que es lo que pasa.
//  Si una fase futura cambia la mecánica del gate, este comentario es el lugar a corregir.
//
//  ── Los dos campos del sobre que NO EXISTEN ───────────────────────────────────────────
//  `connection_id` e `is_partial` se pidieron como parte del sobre y **no están en el
//  átomo** (medido; ver `envelope.js`). No se fabrican: el primero se deriva del server de
//  la tool y viaja marcado como derivado; el segundo se deriva de la posición en el stream
//  (un `tool_call_started` sin su `finished` al cerrar ⇒ parcial). Los dos van dentro de
//  CUSTOM `aleph.tool_meta`, nunca disfrazados de campo del backend.

import {
  AbstractAgent,
  EventType,
  Observable,
} from "../vendor/assistant-ui.bundle.js";
import {
  CHARLA,
  ESPINAZO,
  leerSSE,
  causaDe,
  falloDeRun,
  connectionIdDerivado,
  latenciaMs,
  nombreVisible,
  nombreDeAgente,
  claveDeAgente,
} from "./envelope.js?v=sala-te";
import { rawModelUse, shadowResolve } from "../../model-use.js?v=model-chip-3";

/** Ids de mensaje/paso estables dentro de un run. */
let _seq = 0;
const nuevoId = (p) => `${p}-${Date.now().toString(36)}-${(_seq++).toString(36)}`;

export class AlephAgent extends AbstractAgent {
  /**
   * @param {object} o
   * @param {() => object} o.contexto  devuelve {puppetId,userId,recipe,model,agent,spaceId,chatId,autonomy,lang,clientTurnId}
   *        Es una FUNCIÓN, no un objeto: el contexto cambia entre turnos (el usuario cambia
   *        de agente, de idioma o de autonomía) y capturarlo una vez congelaría el primero.
   * @param {() => object} o.authHeaders  headers con la sesión, resueltos por turno
   * @param {(a:object)=>void} [o.onAleph]  canal lateral para lo que no es del hilo
   *        (estados en vivo, gate, usage). Recibe lo MISMO que viaja en los CUSTOM.
   */
  constructor({ contexto, authHeaders, onAleph } = {}) {
    super({ agentId: "aleph", description: "Aleph — La Sala" });
    this._contexto = contexto || (() => ({}));
    this._authHeaders = authHeaders || (() => ({}));
    this._onAleph = onAleph || (() => {});
    /** turno_id en vuelo, para `/v1/turnos/detener`. */
    this.turnoId = null;
    /** space_id del turno en vuelo, para el espinazo. */
    this.spaceId = null;
  }

  /** El único método que AG-UI pide implementar. */
  run(input) {
    return new Observable((sub) => {
      const abort = new AbortController();
      const ctx = this._contexto() || {};
      const emisor = new Emisor(sub, input, (a) => this._onAleph(a), this._prompt(input));

      // La elección del transporte replica la regla que ya rige en producción
      // (sala.html:5543): con agente guardado o con imágenes hay loop de tools ⇒ el run
      // completo; una charla suelta va por el stream de texto, que es el camino barato.
      //
      // `ctx.equipado` permite forzarlo sin mentir sobre la identidad: el transporte y el
      // `puppet_id` que viaja en el body son dos cosas distintas, y hacer que una implique
      // la otra obligaba a inventar un id que el backend después no encuentra.
      //
      // [T1 · LEY 15] Y EL PISO TAMBIÉN. Hasta acá `raw` (sin agente y sin receta) era el
      // único estado del producto que iba por el camino barato — y por eso el único sin
      // manos: el stream es toolless por diseño. Ahora el borde `run.raw` de
      // `/v1/puppets/run` le pone el KIT BASE, así que el piso va por el run completo
      // como cualquier turno con herramientas.
      //
      // No cambia la identidad: `puppet_id` sigue sin viajar y el body manda `agent:null`.
      // El cinturón es de LA SALA, no un agente del usuario — no se elige, no se guarda,
      // no aparece en el Cuarto. Lo que el usuario ve es la tool que se usó en la línea
      // de razonamiento («belt python», «leyendo el archivo»), jamás un menú de servers.
      //
      // ⚠️ CONSECUENCIA DECLARADA, no escondida: con esto `_correrCharla` (y con él
      // `/v1/puppets/run/stream`) queda SIN LLAMADOR desde la Sala. No se borra en este
      // commit —es el camino certificado y el stream tiene sus propios consumidores—
      // pero queda dicho que hoy es inalcanzable desde acá, para que nadie lo lea como
      // vivo. Y queda ABIERTA la medición que decide si esto se instala así: un turno
      // del piso ahora arranca el kit (6 servers MCP) aunque el humano sólo diga «hola».
      // Cuánto cuesta ese arranque en el camino más caliente del producto NO está medido.
      const conTools = true;

      // El hilo se asegura ANTES de mandar el turno: el `chat_id` viaja EN el body del run,
      // que es lo que hace que el backend registre la conversación y la pueda rehidratar.
      // Fail-soft a propósito: si no se puede crear, el turno corre igual sin registro.
      const promesa = (async () => {
          // A clean installation can have no usable provider. Check the same
          // status as the model indicator before creating a chat or starting tools.
          if (!ctx.puppetId && !ctx.recipe && window.AlephBrain?.resolve) {
            let status = null;
            try { status = await window.AlephBrain.resolve(); } catch (_) { /* unknown */ }
            if (status?.id === "none") {
              emisor.marcarError(status.detail || "No hay un modelo utilizable.", {
                causa: "no_provider", detalle: status.detail || "Conecta un modelo en Modelos.",
              });
              return;
            }
          }
          const chatId = await Promise.resolve(this._asegurarHilo ? this._asegurarHilo() : null)
            .catch(() => null);
          const c = {
            ...ctx,
            chatId: chatId || ctx.chatId || undefined,
            // Raw deja una referencia de procedencia, pero no fabrica un agente ni una
            // sesión de workspace: sólo identifica los eventos de este turno.
            spaceId: ctx.spaceId || (!conTools ? nuevoId("raw") : undefined),
          };
          return conTools
            ? this._correrObra(emisor, c, abort.signal)
            : this._correrCharla(emisor, c, abort.signal);
        })();

      promesa
        .then(() => emisor.cerrarOk())
        .catch((e) => {
          if (abort.signal.aborted) return void emisor.cerrarOk();
          emisor.cerrarError(e);
        });

      return () => abort.abort();
    });
  }

  /** Texto del prompt del último mensaje de usuario que trae AG-UI. */
  _prompt(input) {
    const msgs = input?.messages || this.messages || [];
    for (let i = msgs.length - 1; i >= 0; i--) {
      const m = msgs[i];
      if (m?.role !== "user") continue;
      if (typeof m.content === "string") return m.content;
      if (Array.isArray(m.content)) {
        return m.content
          .filter((p) => p?.type === "text")
          .map((p) => p.text)
          .join("");
      }
    }
    return "";
  }

  /**
   * Observa el contrato nuevo sin gobernar la ejecución heredada. El resultado sólo se
   * publica por el canal de diagnóstico; un 401, un catálogo incompleto o una capacidad
   * ausente NO cambian ni retrasan el turno que sigue yendo por `/puppets/run*`.
   */
  _shadowRawModelUse(ctx, body) {
    const selectionRef = String(body.model || "").trim();
    if (!selectionRef || body.puppet_id || body.recipe) return;
    const request = rawModelUse({
      id: body.client_turn_id || undefined,
      idempotencyKey: body.client_turn_id || undefined,
      workspaceId: "sala",
      callClass: "chat.raw",
      selectionRef,
      sessionId: body.chat_id,
      entityId: body.space_id,
      messages: [{ role: "user", content: body.prompt }],
      attachments: (body.images || []).map((_, i) => ({ type: "image", index: i })),
      requiredCapabilities: body.images?.length ? ["vision"] : [],
      preferredCapabilities: ["streaming"],
      stream: true,
    });
    shadowResolve(request, { headers: this._authHeaders() })
      .then((result) => this._onAleph({ nombre: "aleph.model_use_shadow", valor: result }));
  }

  // ── A · CHARLA ────────────────────────────────────────────────────────────────────────
  async _correrCharla(emisor, ctx, signal) {
    const body = {
      user_id: ctx.userId,
      prompt: emisor.prompt,
      lang: ctx.lang || "es",
      chat_id: ctx.chatId || undefined,
      client_turn_id: ctx.clientTurnId || undefined,
      autonomy: ctx.autonomy || undefined,
      recipe: ctx.recipe || undefined,
      puppet_id: ctx.puppetId || undefined,
      agent: ctx.puppetId || null,
      model: !ctx.puppetId && !ctx.recipe ? (ctx.model || undefined) : undefined,
      space_id: ctx.spaceId || undefined,
    };
    // Fire-and-observe: no se espera y no comparte AbortSignal con el turno legacy.
    this._shadowRawModelUse(ctx, body);
    const r = await fetch("/v1/puppets/run/stream", {
      method: "POST",
      headers: this._authHeaders({ "Content-Type": "application/json", Accept: "text/event-stream" }),
      body: JSON.stringify(body),
      signal,
    });
    if (!r.ok) throw new Error(`el motor no aceptó el turno (HTTP ${r.status})`);

    await leerSSE(r, {
      signal,
      onMalformed: (crudo) => emisor.aleph("aleph.frame_ilegible", { crudo: crudo.slice(0, 200) }),
      onFrame: (f) => {
        switch (f.type) {
          case CHARLA.TOKEN:
            emisor.texto(f.text || "");
            break;
          case CHARLA.THINKING:
            emisor.razonamiento(f.text || "");
            break;
          case CHARLA.TURNO:
            this.turnoId = f.turno_id || null;
            emisor.aleph("aleph.turno", { turno_id: f.turno_id });
            break;
          case CHARLA.MODELO_SUSTITUIDO:
            emisor.aleph("aleph.modelo_sustituido", f);
            break;
          case CHARLA.MODEL_FINAL:
            emisor.aleph("aleph.model_final", f);
            break;
          case CHARLA.SESION_PERDIDA:
            // Obra 6 de Gate 3: el turno NO falló. Es aviso de estado, jamás rojo.
            emisor.aleph("aleph.sesion_perdida", f);
            break;
          case CHARLA.USAGE:
            emisor.aleph("aleph.usage", f);
            break;
          case CHARLA.DONE:
            // Un `done` con `answer` y cero `token` previos pasa si el replay idempotente
            // contesta de una. Se vuelca el texto entero para no perder la respuesta.
            if (!emisor.huboTexto && f.answer) emisor.texto(f.answer);
            if (f.model_final) emisor.aleph("aleph.model_final", { model_final: f.model_final });
            // ── EL VEREDICTO DE LA CHARLA · POR QUÉ NO NACÍA NINGUNA OBRA ──────────────
            //
            // La Sala v2 no producía un artefacto JAMÁS, y ésta era la mitad de la causa:
            // `nacerObra` cuelga de UN solo evento (`aleph.veredicto`, sala-v2.js) y la
            // charla no lo emitía NUNCA. El turno terminaba con `model_final` + `usage` +
            // `marcarFinal`, que son señales de la PANTALLA — ninguna dice «acá está el
            // entregable». O sea que el camino más usado de la Sala cerraba bien, pintaba
            // bien, y no dejaba nada en la Biblioteca.
            //
            // El `done` de `router.py` trae `answer` · `model_final` · `space_id` · `agent`
            // (no trae `obra`: la obra RICA es del contrato de artefactos, que es del
            // camino equipado). Con eso alcanza: el turno de charla deja un informe de
            // texto, y `Obras.mereceSerObra` decide si merece serlo. No se inventa nada —
            // `obra` y `run_id` viajan en null porque este camino no los tiene, y decirlo
            // en null es más honesto que fabricarlos.
            emisor.aleph("aleph.veredicto", {
              ok: true,
              model_final: f.model_final ?? null,
              model_identity: f.model_identity ?? null,
              run_id: null,
              degraded: null,
              answer: f.answer ?? null,
              obra: null,
              space_id: f.space_id ?? null,
              // LA LLAVE DEL TURNO. `nacerObra` la usa para no crear dos veces la misma
              // obra; en el replay idempotente el backend no manda `space_id`, así que sin
              // esto un mismo turno re-contestado nacería otra vez.
              client_turn_id: ctx.clientTurnId || null,
              intent: emisor.prompt || null,
            });
            emisor.marcarFinal();
            break;
          case CHARLA.ERROR:
            {
              const fallo = falloDeRun({ ...f, message: f.message || f.detail });
              emisor.marcarError(fallo.mensaje, fallo.causa, fallo);
            }
            break;
          default:
            // Un frame nuevo del backend no se traga: se ve. (Fallo visible, jamás mudo.)
            emisor.aleph("aleph.frame_desconocido", { type: f.type, frame: f });
        }
      },
    });
  }

  // ── B · OBRA EQUIPADA ─────────────────────────────────────────────────────────────────
  async _correrObra(emisor, ctx, signal) {
    const spaceId = nuevoId("space");
    this.spaceId = spaceId;

    // El espinazo se abre ANTES del POST: el run empieza a emitir apenas arranca, y abrirlo
    // después perdería los primeros eventos (que son justo los que bajan la latencia
    // percibida — `belt_ready` y el primer `turn_started` llegan mucho antes que el POST).
    // El respaldo del respaldo arranca limpio en cada turno: un `_terminalStream` heredado
    // del turno anterior haría nacer la obra de AYER si éste no deja nada.
    this._terminalStream = null;
    const espinazo = this._abrirEspinazo(emisor, spaceId, signal);

    const body = {
      puppet_id: ctx.puppetId || undefined,
      user_id: ctx.userId,
      prompt: emisor.prompt,
      space_id: spaceId,
      lang: ctx.lang || "es",
      chat_id: ctx.chatId || undefined,
      client_turn_id: ctx.clientTurnId || undefined,
      autonomy: ctx.autonomy || undefined,
      recipe: ctx.recipe || undefined,
      images: ctx.images?.length ? ctx.images : undefined,
      agent: ctx.puppetId || null,
      // [T2.3] LAS TOOLS DEL CLIENTE. Se le DECLARAN al modelo junto al belt; el motor NO
      // las ejecuta — devuelve la call (`client_calls` en el record + evento `client_call`
      // en el espinazo) y la pinta la superficie. El backend las aceptaba desde FIX-P9;
      // lo único que faltaba era que la Sala las mandara.
      client_tools: ctx.clientTools?.length ? ctx.clientTools : undefined,
    };

    let out = null;
    try {
      const r = await fetch("/v1/puppets/run", {
        method: "POST",
        headers: this._authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(body),
        signal,
      });
      out = await r.json().catch(() => null);
      if (!r.ok) {
        const fallo = falloDeRun({
          ...(out || {}),
          message: out?.detail?.detail || out?.detail || `el motor rechazó el turno (HTTP ${r.status})`,
        });
        emisor.marcarError(fallo.mensaje, fallo.causa, fallo);
      }
    } finally {
      // EL POST VUELVE ANTES QUE LOS ÚLTIMOS EVENTOS DEL STREAM, Y ESO IMPORTA.
      //
      // Medido con la vara el 2026-08-08: cerrar el espinazo apenas vuelve el POST se comía
      // `tool_call_finished`, `final` y `closed`. Consecuencia visible: la tool quedaba
      // pintada «corriendo…» para siempre y `model_final` salía null —aunque el
      // `events.jsonl` del run SÍ decía `claude-sonnet-5`—, o sea que el anti-grift daba
      // rojo por culpa de la pantalla, no del motor. Un veredicto perdido por cerrar
      // temprano es peor que uno que tarda: parece un fallo del backend.
      //
      // Por eso se DRENA: se espera al `closed` (que es el terminal honesto del run) o a un
      // plazo corto. Los eventos ya están persistidos; sólo falta terminar de leerlos.
      const GRACIA_MS = 4000;
      await Promise.race([
        espinazo.vioCierre,
        new Promise((r) => setTimeout(r, GRACIA_MS)),
      ]);
      espinazo.cerrar();
      await espinazo.terminado;
    }

    // Respaldo idempotente: si el stream murió, el terminal del POST igual pinta el turno.
    if (out) {
      if (!emisor.huboTexto && out.answer) emisor.texto(out.answer);
      for (const h of out.held_actions || []) emisor.gate("held", h, out.run_id);
      emisor.aleph("aleph.veredicto", {
        ok: out.ok ?? null,
        model_final: out.model_final ?? null,
        model_identity: out.record?.model_identity ?? out.model_identity ?? null,
        run_id: out.run_id ?? null,
        degraded: out.degraded ?? null,
        trajectory_steps: out.trajectory_steps ?? null,
        // [Gate 4 · Fase 3 · 3.0] Lo que el CANVAS necesita para persistir la obra del
        // turno, y nada más: la respuesta, la obra rica si el backend la surfaceó, el
        // espacio (que es la REFERENCIA re-verificable de la procedencia) y los archivos
        // capturados. Todo sale del terminal del run — la pantalla no deriva ninguno.
        answer: out.answer ?? null,
        obra: out.obra ?? null,
        space_id: spaceId,
        outputs_captured: out.outputs_captured ?? null,
        // [T2.4] LA PROCEDENCIA DEL TURNO. `rag_injected` ({n_chunks, provenance:[…]}) lo
        // emite el motor desde siempre (`recipe_assembler._rag_wrap`) y NADIE lo leía: la
        // promesa de honestidad del producto —«de dónde salió esto»— llegaba hasta el
        // record y ahí se moría. Viaja crudo, sin derivar nada: la pantalla lo formatea.
        rag: out.record?.rag_injected ?? null,
        // [T2.6] EL MÉTODO QUE DIRIGIÓ EL TURNO. Trae `{method_id, name, status, steps…}`
        // del arnés (`method_harness.finish`), así que el NOMBRE ya viene — la pantalla no
        // necesita pedir `/v1/methods/{id}` para poder decir de dónde salió la obra.
        method: out.method ?? null,
        // [T2.3] La verdad TERMINAL del POST. Las que ya llegaron vivas por el espinazo no
        // se repiten: el dedup es por `call_id`, que el motor emite en las dos vías.
        client_calls: out.record?.client_calls ?? null,
        intent: emisor.prompt || null,
      });
      if (out.ok === false) {
        const fallo = falloDeRun(out);
        emisor.marcarError(fallo.mensaje, fallo.causa, fallo);
      }
    } else if (this._terminalStream) {
      // ── EL POST NO DEJÓ TERMINAL, PERO EL RUN SÍ TERMINÓ ───────────────────────────
      // Pasa cuando el POST se cae, se aborta o contesta algo que no es JSON, mientras el
      // espinazo —que es otro socket— llegó hasta el `closed`. Antes ese turno se perdía
      // entero para la Biblioteca: el único veredicto con entregable era el del POST, así
      // que sin él no nacía nada aunque el trabajo estuviera hecho y persistido.
      //
      // Se emite lo que el stream SÍ vio, y nada más. `rag`, `method` y `client_calls` van
      // ausentes a propósito: son del record del POST, y fabricarlos acá sería inventar
      // procedencia — justo lo que la obra promete no hacer.
      emisor.aleph("aleph.veredicto", {
        ...this._terminalStream,
        space_id: spaceId,
        intent: emisor.prompt || null,
        fuente: "espinazo",
      });
    }
    emisor.marcarFinal();
  }

  _abrirEspinazo(emisor, spaceId, signalPadre) {
    const abort = new AbortController();
    const cerrar = () => abort.abort();
    if (signalPadre) signalPadre.addEventListener("abort", cerrar, { once: true });

    // Se resuelve cuando llega el `closed`, que es el terminal honesto del run. Es lo que
    // le permite al POST esperar a que el stream termine de contar en vez de cortarlo.
    let marcarCierre;
    const vioCierre = new Promise((r) => (marcarCierre = r));

    const terminado = (async () => {
      // EL ESPACIO NO EXISTE TODAVÍA CUANDO ARRANCAMOS, Y ESO ES ESPERABLE.
      //
      // Medido el 2026-08-08: `GET /v1/spaces/{id}/stream` devuelve **404** hasta que el run
      // crea su `events.jsonl`. Abrirlo antes del POST —que es lo que hace falta para no
      // perder los primeros eventos— chocaba con ese 404 y el espinazo quedaba mudo: la
      // primera corrida del medidor dio 0 eventos y sala-v2 se comportaba igual que la Sala
      // vieja. Por eso se reintenta: el 404 acá no es un fallo, es «todavía no».
      //
      // El reintento para solo cuando (a) conecta, (b) el POST del run ya volvió y cerró el
      // turno, o (c) se agota el plazo. Nunca gira para siempre.
      const ESPERA_MS = 120;
      const PLAZO_MS = 20000;
      const t0 = Date.now();
      let r = null;
      for (;;) {
        if (abort.signal.aborted) return;
        try {
          r = await fetch(`/v1/spaces/${encodeURIComponent(spaceId)}/stream`, {
            headers: this._authHeaders({ Accept: "text/event-stream" }),
            signal: abort.signal,
          });
        } catch (e) {
          if (abort.signal.aborted) return;
          r = null;
        }
        if (r && r.ok) break;
        if (r && r.status !== 404) {
          // Un 401/403/500 NO es «todavía no»: es un fallo y se dice, sin reintentar.
          emisor.aleph("aleph.espinazo_caido", { http: r.status });
          return;
        }
        if (Date.now() - t0 > PLAZO_MS) {
          // Sin espinazo el turno NO se cae: el POST sigue siendo la verdad terminal. Pero
          // el usuario pierde el vivo, y eso se dice (fallo visible, jamás mudo).
          emisor.aleph("aleph.espinazo_caido", { motivo: "el espacio nunca abrió", plazo_ms: PLAZO_MS });
          return;
        }
        await new Promise((res) => setTimeout(res, ESPERA_MS));
      }
      try {
        await leerSSE(r, {
          signal: abort.signal,
          onMalformed: (crudo) => emisor.aleph("aleph.frame_ilegible", { crudo: crudo.slice(0, 200) }),
          onFrame: (ev) => {
            this._traducirEspinazo(emisor, ev);
            const t = ev?.type || ev?.payload?.type;
            if (t === ESPINAZO.CLOSED) marcarCierre();
          },
        });
      } catch (e) {
        // Un abort nuestro NO es un fallo del stream: es el cierre normal del turno.
        // Reportarlo como caída ensuciaba la pantalla con un aviso falso, y en el navegador
        // salía además como `pageerror: AbortError` (lo destapó la vara).
        const abortado = abort.signal.aborted || (e && e.name === "AbortError");
        if (!abortado) emisor.aleph("aleph.espinazo_caido", { detail: String(e && e.message) });
      } finally {
        marcarCierre();
      }
    })();

    return { cerrar, terminado, vioCierre };
  }

  /** Lo que un terminal del stream (`final`/`closed`) trae de ENTREGABLE, acumulado.
   *
   * Los dos terminales llegan uno detrás del otro y no traen lo mismo: `final` suele traer
   * el `answer` y `closed` los `trajectory_steps`. Se ACUMULA en vez de pisar para que el
   * respaldo tenga lo mejor de los dos; un campo que llega en null no borra al que ya
   * estaba, porque «no lo mandé» no es «es vacío». */
  _recordarTerminal(e) {
    const antes = this._terminalStream || {};
    this._terminalStream = {
      ok: e.ok ?? antes.ok ?? null,
      model_final: e.model_final ?? antes.model_final ?? null,
      run_id: e.run_id ?? antes.run_id ?? null,
      degraded: e.degraded ?? antes.degraded ?? null,
      trajectory_steps: e.trajectory_steps ?? antes.trajectory_steps ?? null,
      answer: e.answer ?? antes.answer ?? null,
      obra: e.obra ?? antes.obra ?? null,
      outputs_captured: e.outputs_captured ?? antes.outputs_captured ?? null,
    };
  }

  /** El corazón de la tabla de mapeo, lado espinazo. */
  _traducirEspinazo(emisor, ev) {
    // Los eventos de `events.jsonl` pueden venir «planos» o con `payload` (EVENTS-SCHEMA
    // §evento: la lib conserva las claves planas de session.py). Se aplana una sola vez acá
    // para que el resto del archivo no tenga que preguntarse cuál de las dos formas llegó.
    const e = ev && ev.payload && typeof ev.payload === "object" ? { ...ev.payload, ...ev } : ev || {};

    switch (e.type) {
      // [OBRA 2] EL PAR DEL CINTURÓN. `paso`/`pasoFin` ya existían y siguen igual —son la
      // traza del hilo—, pero abrían y cerraban en el mismo milisegundo y por eso NO movían
      // la línea de estado: el usuario veía «Pensando…» durante todo el arranque. El canal
      // lateral `aleph.cinturon` es lo que la mueve, y lleva los dos bordes REALES del
      // suceso: cuándo empieza (con cuántas piezas) y cuándo terminó (con qué arrancó).
      case ESPINAZO.BELT_STARTING:
        emisor.aleph("aleph.cinturon", { listo: false, piezas: e.piezas ?? null });
        break;

      case ESPINAZO.BELT_READY:
        emisor.paso("cinturon", { servers: e.servers, tools: e.tools, saltados: e.servers_skipped });
        emisor.pasoFin("cinturon");
        emisor.aleph("aleph.cinturon", {
          listo: true,
          servers: e.servers || [],
          tools: (e.tools || []).length,
          saltados: e.servers_skipped || [],
          ms: e.ms ?? null,
        });
        break;

      case ESPINAZO.TURN_STARTED:
        emisor.paso(`turno:${e.turn ?? "?"}`, { turn: e.turn, reused_belt: e.reused_belt });
        break;

      case ESPINAZO.TOOL_CALL_STARTED:
        emisor.toolInicio(e);
        break;

      case ESPINAZO.TOOL_CALL_FINISHED:
        emisor.toolFin(e);
        break;

      case ESPINAZO.GATE_WAITING:
        emisor.gate("waiting", e, e.run_id);
        break;

      case ESPINAZO.GATE_RESOLVED:
        emisor.aleph("aleph.gate_resolved", { approved: e.approved, timed_out: e.timed_out, tool: e.tool });
        break;

      case ESPINAZO.ARTIFACT_CREATED:
        // El CONTRATO de artefactos es la Fase 2. Acá se pasa el evento tal cual, sin
        // inventarle tipo, versión ni procedencia: inventarlo ahora sería fabricar el
        // contrato que otra fase tiene que diseñar bien.
        emisor.aleph("aleph.artifact", e);
        break;

      case ESPINAZO.EQUIPMENT_CHANGED:
        emisor.estadoDelta([
          { op: "replace", path: "/cinturon", value: { tools: e.tools ?? null, version: e.belt_version ?? null } },
        ]);
        break;

      // ── LOS DOS TERMINALES DEL STREAM ────────────────────────────────────────────────
      //
      // Venían SIN entregable —sólo `ok`/`model_final`/`run_id`/`degraded`— así que aunque
      // llegaran, `nacerObra` salía temprano (`cuerpo` vacío) y el turno no dejaba nada.
      // Ahora el entregable se GUARDA (`_terminalStream`), y quien decide si se usa es
      // `_correrObra`, no la carrera:
      //
      //   · el POST vuelve  → manda SU terminal, que es el rico (trae `obra`, `rag`,
      //                       `method`, `client_calls`); el del stream no se usa.
      //   · el POST no deja → se emite ESTE, enriquecido, y la obra igual nace.
      //
      // ⚠️ Y POR ESO NO SE EMITE `answer` ACÁ. El `closed` llega ANTES que el terminal del
      // POST (el POST drena el espinazo antes de emitir), así que mandarlo enriquecido
      // haría nacer la obra POBRE primero y el dedup de `nacerObra` descartaría después la
      // rica. Ganar la carrera no es lo mismo que tener razón.
      case ESPINAZO.FINAL:
        if (!emisor.huboTexto && e.answer) emisor.texto(e.answer);
        this._recordarTerminal(e);
        emisor.aleph("aleph.veredicto", {
          ok: e.ok ?? null,
          model_final: e.model_final ?? null,
          model_identity: e.model_identity ?? null,
          run_id: e.run_id ?? null,
          degraded: e.degraded ?? null,
        });
        break;

      case ESPINAZO.CLOSED:
        for (const h of e.held_actions || []) emisor.gate("held", h, e.run_id);
        this._recordarTerminal(e);
        emisor.aleph("aleph.veredicto", {
          ok: e.ok ?? null,
          model_final: e.model_final ?? null,
          model_identity: e.model_identity ?? null,
          run_id: e.run_id ?? null,
          degraded: e.degraded ?? null,
          trajectory_steps: e.trajectory_steps ?? null,
        });
        if (e.ok === false) {
          const fallo = falloDeRun(e);
          emisor.marcarError(fallo.mensaje, fallo.causa, fallo);
        }
        break;

      // ── informativos: se pasan, no alarman ─────────────────────────────────────────
      // `cost` es el PRIMER evento del turno (medido) y por eso vale doble: además de
      // llevar tokens/tier/degraded, es el que le dice a la pantalla «esto arrancó».
      case ESPINAZO.COST:
        emisor.aleph("aleph.costo", {
          model: e.model ?? null,
          tier: e.tier ?? null,
          degraded: e.degraded ?? null,
          tokens: e.tokens ?? null,
          usd: e.usd ?? null,
          tool: e.tool ?? null,
          executed: e.executed ?? null,
        });
        break;

      case ESPINAZO.METRIC:
      case ESPINAZO.NOTICE:
      case ESPINAZO.TEXT:
      case ESPINAZO.PLAN_DECLARED:
      case ESPINAZO.CLIENT_CALL:
      case ESPINAZO.DELEGATION_SERIALIZED:
        emisor.aleph("aleph." + e.type, e);
        break;

      // LA DELEGACIÓN, CON NOMBRE Y TAREA. Esto leía `e.name ?? e.agent`, y el espinazo NO
      // MANDA NINGUNO DE LOS DOS (`recipe_assembler.py:3641`: tool · tool_raw · slug ·
      // meta_name · depth · parent_run_id · task · turn). Resultado medido: TODO sub-agente
      // se llamaba `subagente:?` y los ocho campos que sí venían se tiraban acá.
      //
      // El orden es del más humano al más técnico: `meta_name` es el nombre que el usuario
      // le puso al agente, `slug` es su id, `tool` es el último recurso. Nunca "?".
      // La CLAVE es el slug (está en los dos eventos); el NOMBRE viaja como dato. Casarlos
      // por el nombre visible dejaba el paso abierto para siempre — ver `claveDeAgente`.
      case ESPINAZO.SUB_AGENT_STARTED:
        emisor.paso(`subagente:${claveDeAgente(e)}`, {
          sub: nombreDeAgente(e),        // cómo lo llamó el dueño en su receta
          task: e.task ?? null,          // qué se le pidió, con sus palabras
          depth: e.depth ?? null,        // qué tan anidada está la delegación
          parent_run_id: e.parent_run_id ?? null,
        });
        break;

      // El cierre viaja con el veredicto: sin esto el bloque muestra que EMPEZÓ y nunca
      // que terminó, que es la mitad inútil.
      case ESPINAZO.SUB_AGENT_FINISHED:
        emisor.pasoFin(`subagente:${claveDeAgente(e)}`, {
          status: e.status ?? null,      // ok | error | gate
          child_ok: e.child_ok ?? null,
          held: e.held ?? 0,             // >0 ⇒ quedó esperando un OK del humano
          result: e.result ?? null,      // qué devolvió
        });
        break;

      // ── los que el usuario TIENE que ver: son límites reales del turno ─────────────
      case ESPINAZO.LOOP_DETECTED:
      case ESPINAZO.BUDGET_EXHAUSTED:
      case ESPINAZO.BRAIN_WINDOW_EXHAUSTED:
      case ESPINAZO.CONTEXT_COMPACTED:
      case ESPINAZO.SHARED_BUS_DENIED:
        emisor.aleph("aleph.limite", { type: e.type, ...e });
        break;

      default:
        // Un tipo que no está en la tabla SE VE. Es la única forma de enterarse de que el
        // backend sumó un evento sin avisarle a la pantalla — y ya pasó: `cost` y compañía
        // salían por el stream sin estar en EVENTS-SCHEMA.md.
        emisor.aleph("aleph.evento_desconocido", { type: e.type, evento: e });
    }
  }
}

/**
 * EL EMISOR — la mitad de escritura.
 *
 * AG-UI verifica la secuencia y tira si se emite mal (`client/src/verify/verify.ts`:
 * el primero debe ser RUN_STARTED, no se puede cerrar el run con mensajes/tools/pasos
 * abiertos, un CONTENT sin su START es error…). Toda esa disciplina vive acá, en un solo
 * lugar, para que la tabla de mapeo de arriba se pueda leer sin ruido de bookkeeping.
 */
class Emisor {
  constructor(sub, input, onAleph, prompt) {
    this.sub = sub;
    this.onAleph = onAleph;
    this.threadId = input?.threadId || "sala";
    this.runId = input?.runId || nuevoId("run");
    this.prompt = prompt || "";
    this.huboTexto = false;
    this.cerrado = false;

    this._msgId = null; // mensaje de texto abierto
    this._razId = null; // razonamiento abierto
    this._pasos = new Set(); // pasos abiertos
    this._tools = new Map(); // call_id -> {nombre, cerrada}
    this._error = null;

    this._emitir({ type: EventType.RUN_STARTED, threadId: this.threadId, runId: this.runId });
  }

  _emitir(ev) {
    if (this.cerrado) return;
    this.sub.next(ev);
  }

  /** Canal lateral: lo mismo viaja como CUSTOM al hilo y como callback a la pantalla. */
  aleph(nombre, valor) {
    this._emitir({ type: EventType.CUSTOM, name: nombre, value: valor });
    try {
      this.onAleph({ nombre, valor });
    } catch (_) {
      /* la pantalla no puede tumbar el stream */
    }
  }

  // ── texto ───────────────────────────────────────────────────────────────────────────
  texto(delta) {
    if (!delta) return;
    this._cerrarRazonamiento(); // el razonamiento y la respuesta no se mezclan
    if (!this._msgId) {
      this._msgId = nuevoId("msg");
      this._emitir({ type: EventType.TEXT_MESSAGE_START, messageId: this._msgId, role: "assistant" });
    }
    this.huboTexto = true;
    this._emitir({ type: EventType.TEXT_MESSAGE_CONTENT, messageId: this._msgId, delta });
  }

  razonamiento(delta) {
    if (!delta) return;
    if (!this._razId) {
      this._razId = nuevoId("raz");
      this._emitir({ type: EventType.REASONING_START, messageId: this._razId });
      this._emitir({ type: EventType.REASONING_MESSAGE_START, messageId: this._razId, role: "reasoning" });
    }
    this._emitir({ type: EventType.REASONING_MESSAGE_CONTENT, messageId: this._razId, delta });
  }

  _cerrarTexto() {
    if (!this._msgId) return;
    this._emitir({ type: EventType.TEXT_MESSAGE_END, messageId: this._msgId });
    this._msgId = null;
  }

  _cerrarRazonamiento() {
    if (!this._razId) return;
    this._emitir({ type: EventType.REASONING_MESSAGE_END, messageId: this._razId });
    this._emitir({ type: EventType.REASONING_END, messageId: this._razId });
    this._razId = null;
  }

  // ── pasos ───────────────────────────────────────────────────────────────────────────
  paso(nombre, datos) {
    if (this._pasos.has(nombre)) return;
    this._pasos.add(nombre);
    this._emitir({ type: EventType.STEP_STARTED, stepName: nombre });
    if (datos) this.aleph("aleph.paso", { paso: nombre, ...datos });
  }

  pasoFin(nombre, datos) {
    if (!this._pasos.delete(nombre)) return;
    this._emitir({ type: EventType.STEP_FINISHED, stepName: nombre });
    // Simétrico a `paso()`: el CUSTOM lleva el veredicto por el canal lateral. Sin esto un
    // paso sólo podía decir que empezó — el STEP_FINISHED de AG-UI no admite carga útil.
    if (datos) this.aleph("aleph.paso_fin", { paso: nombre, ...datos });
  }

  // ── tools ───────────────────────────────────────────────────────────────────────────
  toolInicio(e) {
    const id = String(e.call_id || nuevoId("tc"));
    if (this._tools.has(id)) return;
    const nombre = nombreVisible(e);
    this._tools.set(id, { nombre, cerrada: false });
    // El tool_call cuelga del mensaje del asistente si ya hay uno abierto; si no, va suelto.
    this._emitir({
      type: EventType.TOOL_CALL_START,
      toolCallId: id,
      toolCallName: nombre,
      ...(this._msgId ? { parentMessageId: this._msgId } : {}),
    });
    this._emitir({
      type: EventType.TOOL_CALL_ARGS,
      toolCallId: id,
      delta: JSON.stringify(e.args ?? {}),
    });
    this.aleph("aleph.tool_inicio", {
      call_id: id,
      nombre,
      server: e.tool ?? null,
      args: e.args ?? null,
      connection_id: connectionIdDerivado(e),
    });
  }

  toolFin(e) {
    const id = String(e.call_id || "");
    if (!this._tools.has(id)) this.toolInicio(e); // un `finished` sin su `started` igual se pinta
    const t = this._tools.get(id);
    if (!t || t.cerrada) return;
    t.cerrada = true;

    this._emitir({ type: EventType.TOOL_CALL_END, toolCallId: id });

    const gated = e.status === "gated" || e.executed === false;
    if (!gated) {
      // TOOL_CALL_RESULT necesita un messageId de tool; AG-UI lo trata como el mensaje que
      // representa el resultado, así que se genera uno propio y estable.
      this._emitir({
        type: EventType.TOOL_CALL_RESULT,
        messageId: nuevoId("tres"),
        toolCallId: id,
        content: typeof e.result === "string" ? e.result : JSON.stringify(e.result ?? ""),
        role: "tool",
      });
    }

    this.aleph("aleph.tool_meta", {
      call_id: id,
      nombre: t.nombre,
      status: e.status ?? null, // ok | error | gated — del sobre, tal cual
      executed: e.executed ?? null,
      latency_ms: latenciaMs(e), // null si el assembler no lo midió; jamás 0 inventado
      connection_id: connectionIdDerivado(e), // DERIVADO, y dice de qué
      is_partial: false, // este tool_call cerró: no quedó parcial
      causa: causaDe(e), // la causa tipada, sin re-derivar ni traducir
      gate_action: e.gate_action ?? e.gate_decision ?? null,
    });

    if (gated) this.gate("waiting", e, e.run_id);
  }

  // ── gate (Ó11 · el órgano ya existe: acá se CONECTA, no se reconstruye) ──────────────
  gate(fase, e, runId) {
    // Firma estable a través de los 3 orígenes del gate, igual criterio que la Sala vieja
    // (sala.html:4612): server|fn, sin args — el `closed` los omite y una firma con args
    // duplicaría la tarjeta en vez de subirla a operable.
    //
    // LAS DOS FORMAS NO SE PARECEN, Y HAY QUE MIRARLAS POR SEPARADO. Medido sobre un gate
    // real (2026-08-08, `datatools.write_csv` con autonomía manual):
    //
    //   gate_waiting     tool="datatools" (SERVER) · tool_raw="write_csv" · tool_name="write_csv"
    //   held_actions[i]  server="datatools"        · tool="write_csv" (LA FUNCIÓN)
    //
    // O sea que `tool` significa cosas OPUESTAS en cada una. Resolverlo con un `??` en
    // cadena daba `write_csv|write_csv` para la retenida y `datatools|write_csv` para la
    // viva: dos firmas distintas para el MISMO gate ⇒ la tarjeta se duplicaba y ninguna de
    // las dos llegaba a operable. Es exactamente el defecto que la Sala vieja documenta en
    // `sala.html:4605-4611`, reencontrado por otro camino.
    const server = fase === "held" ? (e.server ?? e.tool ?? null) : (e.tool ?? e.server ?? null);
    const fn = fase === "held" ? (e.tool ?? null) : (e.tool_raw ?? e.tool_name ?? null);
    this.aleph("aleph.gate_waiting", {
      fase, // "waiting" (vivo, sin ids) | "held" (con approval_id ⇒ operable)
      sig: `${server || ""}|${fn || ""}`,
      server,
      tool: fn,
      ux: e.gate_ux ?? e.ux ?? null, // el contrato de UX del gate, tal cual lo arma el backend
      turn_text: e.turn_text ?? null,
      args: e.args ?? null,
      run_id: runId ?? e.run_id ?? null,
      approval_id: e.approval_id ?? null,
    });
  }

  // ── estado ──────────────────────────────────────────────────────────────────────────
  estadoDelta(patch) {
    this._emitir({ type: EventType.STATE_DELTA, delta: patch });
  }

  // ── cierre ──────────────────────────────────────────────────────────────────────────
  marcarFinal() {
    this._final = true;
  }

  marcarError(mensaje, causa, diagnostico) {
    if (this._error) return;
    this._error = {
      mensaje: String(mensaje || "el turno falló"),
      causa: causa || null,
      diagnostico: diagnostico?.diagnostico || null,
      runtime_state: diagnostico?.runtime_state || causa?.runtime_state || null,
      quota_availability: diagnostico?.quota_availability || causa?.quota_availability || "unknown",
      provider_rate_limit_event: diagnostico?.provider_rate_limit_event ||
        causa?.provider_rate_limit_event || null,
    };
  }

  /** Cierra TODO lo abierto: AG-UI rechaza un RUN_FINISHED con cosas en vuelo. */
  _cerrarPendientes() {
    for (const [id, t] of this._tools) {
      if (t.cerrada) continue;
      t.cerrada = true;
      this._emitir({ type: EventType.TOOL_CALL_END, toolCallId: id });
      // `is_partial` DERIVADO: quedó un tool_call abierto cuando el run cerró.
      this.aleph("aleph.tool_meta", {
        call_id: id,
        nombre: t.nombre,
        status: null,
        executed: null,
        latency_ms: null,
        connection_id: null,
        is_partial: true,
        derivado_de: "tool_call_started sin su tool_call_finished al cerrar el run",
        causa: null,
      });
    }
    this._cerrarRazonamiento();
    this._cerrarTexto();
    for (const p of [...this._pasos]) this.pasoFin(p);
  }

  cerrarOk() {
    if (this.cerrado) return;
    this._cerrarPendientes();
    if (this._error) {
      // El `message` que sube es el DETALLE del backend cuando lo hay: «Se agotó tu ventana
      // de uso del CLI» le sirve a una persona, `HTTP Error 429: Too Many Requests` no.
      const _c = this._error.causa;
      this._emitir({ type: EventType.RUN_ERROR,
                     message: (_c && _c.detalle) || this._error.mensaje,
                     ...(_c?.causa ? { code: String(_c.causa) } : {}),
                     ...(this._error.diagnostico
                       ? { diagnostic: this._error.diagnostico } : {}),
                     ...(this._error.runtime_state
                       ? { runtime_state: this._error.runtime_state } : {}),
                     quota_availability: this._error.quota_availability,
                     ...(this._error.provider_rate_limit_event
                       ? { provider_rate_limit_event: this._error.provider_rate_limit_event } : {}) });
    } else {
      this._emitir({ type: EventType.RUN_FINISHED, threadId: this.threadId, runId: this.runId });
    }
    this.cerrado = true;
    this.sub.complete();
  }

  cerrarError(e) {
    if (this.cerrado) return;
    this._cerrarPendientes();
    this._emitir({ type: EventType.RUN_ERROR, message: String((e && e.message) || e || "el turno falló") });
    this.cerrado = true;
    this.sub.complete();
  }
}
