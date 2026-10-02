/* modelos.widget.js — LA DERIVACIÓN DE MODELOS. (Gate 2 · F4c)
 *
 * El gemelo de `conectores/widget.js` para el Centro de Modelos. **Calcado, no inventado**:
 * las mismas cinco capas, la misma regla anti-yo-yo, el mismo vocabulario de causas. Lo que
 * cambia es de qué se deriva cada cosa, porque un modelo no se conecta como un MCP.
 *
 *   QUÉ MUESTRA          ← DE DÓNDE SALE (todo ya existía antes de F4c)
 *   familia/vía          ← `centro_modelos.GRUPOS`, declarado EN EL BACKEND
 *   estado + causa       ← el motor de verdad (vocabulario CERRADO)
 *   evidencia del [?]    ← `fila.prueba` {estado, ts, detalle, evidencia}
 *   estuvoCompleta       ← `modelos_repo`, derivado de `ultimo_veredicto == 'probado'`
 *   copy de la causa     ← `cuarto.semaforo.js`, el diccionario ÚNICO
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * LA REGLA QUE HACE QUE ESCALE: **NADA SE ESCRIBE ACÁ POR MODELO.** Si un modelo necesita
 * un paso que este archivo no sabe derivar, la respuesta NO es un `if (id === "qwen")` —
 * es que a su fila le falta un campo. El dato se agrega A LA FUENTE (el catálogo de
 * `centro_modelos`), que es donde tiene autor y auditoría. Un `if` por modelo escala a 21
 * y muere en los 17.000 del catálogo público.
 */

import * as Sem from "../cuarto/cuarto.semaforo.js";
import { lang } from "../conectores/causas-catalogo.js";

/** Las cuatro vías. Se DECLARAN en el backend (`centro_modelos.GRUPOS`) y se leen acá:
 *  dos tablas se desincronizan, y ésa es la lección del Centro de Conexiones. */
export const INCLUIDO = "incluido";
export const CLI = "cli";
export const API = "api";
export const LOCAL = "local";

/** Los trámites de la ADUANA. Cerrado a propósito: agregar uno es una decisión de
 *  producto, no un efecto colateral de un modelo nuevo. */
export const TRAMITE_DESCARGAR = "descargar";   // local sin el gguf en disco
export const TRAMITE_LOGIN = "login";           // cli sin sesión
export const TRAMITE_LLAVE = "llave";           // api/openrouter sin credencial

/** Territorio del bloqueo, igual que en conectores. */
export const USUARIO = "usuario";
export const NUESTRO = "nuestro";

/** ¿La medición envejeció? Gatillo, no etiqueta (acta §7.c) — dispara un re-verify, no
 *  pinta un cartel. Sin medición NO es «rancia»: es «nunca se midió», que es otra cosa
 *  y tiene otro camino. (El molde pagó este bug: un `NaN` colapsaba a 0 y respondía
 *  «rancia» sobre una pieza sin medición previa.) */
export const TTL_MEDICION_MS = 24 * 60 * 60 * 1000;

export function medicionRancia(fila, ahora) {
  const ts = fila && fila.prueba && fila.prueba.ts ? fila.prueba.ts * 1000
           : (fila && fila.ts ? fila.ts * 1000 : null);
  if (!ts || !isFinite(ts)) return false;        // nunca medido ≠ rancio
  return ((ahora || Date.now()) - ts) > TTL_MEDICION_MS;
}

/** ¿Qué le falta a este modelo para poder CORRER? Por vía, y sin inventar nada.
 *
 *   local → el gguf descargado + un runtime vivo que lo pueda correr
 *   cli   → el binario detectado + la sesión del usuario viva
 *   api   → la llave en el vault (el verify la valida aparte)
 *   incluido → nada: viene con Aleph, por eso se llama así
 */
function requisitos(fila) {
  const via = fila.familia;
  if (via === LOCAL) {
    return {
      // ⚠️ [F7] `instalado === false` MANDA. Un candidato de Hugging Face llega con
      // `familia:"local"` y `local:true` —quiere decir «corre en tu máquina», no «está en
      // tu máquina»— y con `instalado:false`. Leyendo sólo `fila.local`, los 8 candidatos
      // del catálogo entraban a «Tus modelos» sin estar descargados. El bug apareció al
      // MONTAR el módulo: la vara de F4c lo alimentaba con filas sintéticas que no traían
      // ese campo, así que no podía verlo.
      descargado_ok: fila.instalado === false ? false : !!(fila.local || fila.descargado),
      credencial_ok: true,                       // un modelo local no pide llave
      runtime_ok: fila.causa !== "sin_runtime",
      modelo_ok: true,                           // el modelo ES la fila: no hay qué elegir
    };
  }
  if (via === CLI) {
    return {
      descargado_ok: !!fila.servicio_cli,        // el binario está en la máquina
      credencial_ok: !!fila.sesion_cli,          // la SESIÓN es la credencial del BYO-CLI
      runtime_ok: true,
      modelo_ok: true,                           // el modelo lo pone la suscripción del CLI
    };
  }
  if (via === API) {
    return {
      descargado_ok: true,
      credencial_ok: !!fila.hay_llave,
      runtime_ok: true,
      // ── [F8 · obra 2] LA LLAVE NO ALCANZA: TAMBIÉN HAY QUE SABER QUÉ MODELO USAR ──
      // Es el SEGUNDO requisito de la vía API y hasta ahora no existía porque siempre había
      // un id hardcodeado tapando el hueco. Con la elección del usuario mandando, el hueco
      // se puede ver — y tiene que verse como lo que es.
      //
      // ⚠️ AUSENTE ≠ NULL, y acá se paga caro confundirlos. `modelo_elegido: null` significa
      // «lo busqué y no hay»; que el campo NO VENGA significa «esta fila no me lo dijo» —un
      // sidecar viejo, una fila sintética, otra superficie— y castigarla por eso rompería
      // filas que están perfectas. Misma ley que `_toolsDeServidor` ya defiende: la ausencia
      // de medición jamás se reporta como una medición negativa.
      modelo_ok: !("modelo_elegido" in fila) || fila.modelo_elegido != null,
    };
  }
  // INCLUIDO: viene con Aleph. No hay trámite del usuario que pueda faltar.
  return { descargado_ok: true, credencial_ok: true, runtime_ok: true, modelo_ok: true };
}

/** pertenencia(fila) — ¿va en «Tus modelos» o en la aduana? Y si no va, QUÉ le falta.
 *
 * ══ LA REGLA ANTI-YO-YO (acta §7), calcada ════════════════════════════════════════
 *
 *   Un modelo del local que se ROMPE **no vuelve a la aduana ni desaparece**: se queda
 *   en el local con su causa operativa y su camino inline.
 *
 * ⚠️ SIN ESTO LA LEY SE COME A SÍ MISMA. `completa()` se re-evalúa en tres momentos —al
 * arrancar, al equipar y con la medición rancia—, así que un modelo cuyo runtime se apagó
 * dejaría de ser completo **en el próximo arranque** y se iría a la aduana. Al prender
 * Ollama volvería al local. Un yo-yo por cada fallo transitorio: para el usuario, sus
 * modelos se mueven de lugar solos.
 *
 * LA DISTINCIÓN, y no se adivina: **¿este modelo estuvo completo alguna vez?**
 *   · nunca lo estuvo  → onboarding incompleto → aduana, con su trámite;
 *   · lo estuvo y hoy falla → REGRESIÓN → local, con su causa y su botón.
 * Lo dice el registro: `estuvo_completa` sale de `ultimo_veredicto === "probado"`, que
 * exige que el modelo haya CORRIDO. No es «está descargado»: es «anduvo».
 */
export function pertenencia(fila, opciones) {
  const o = opciones || {};
  const via = fila.familia;
  const req = requisitos(fila);
  const admitida = !!fila.estuvo_completa;

  // Una REGRESIÓN es una pieza del local que perdió un requisito que alguna vez tuvo.
  const falta_algo = !req.descargado_ok || !req.credencial_ok;
  const regresion = admitida && falta_algo;

  // QUÉ le falta, en el vocabulario de los trámites — para que la aduana muestre el
  // camino sin volver a decidir nada.
  const faltan = [];
  if (!regresion) {
    if (!req.descargado_ok) faltan.push(via === CLI ? TRAMITE_LOGIN : TRAMITE_DESCARGAR);
    if (!req.credencial_ok) faltan.push(via === CLI ? TRAMITE_LOGIN : TRAMITE_LLAVE);
  }

  // LA LLAVE ESTÁ PERO NO SIRVE — la única falla operativa que NO se arregla reintentando,
  // porque lo que hay que cambiar es la credencial. Su botón es [Rotar llave], y el modelo
  // se queda en el local: nunca dejó de estar completo.
  const rotar = req.credencial_ok &&
    ["key_invalida", "sin_credito", "oauth_revocado", "sin_sesion"].includes(fila.causa);

  return {
    // ── ¿va en «Tus modelos»? ──────────────────────────────────────────────────────
    // Completo HOY, o REGRESIÓN (estuvo completo y hoy falla). Las dos van al local.
    // ⚠️ [F8 · obra 2] `modelo_ok` NO ENTRA ACÁ, Y ES LA DECISIÓN DE LA OBRA. Una vía con la
    // llave puesta y sin modelo elegido es del LOCAL: está configurada, el trámite lo hizo,
    // y lo que le falta es una decisión —no un requisito de admisión—. Metiéndola en esta
    // condición se iba a la aduana, y la aduana sólo sabe pedir trámites: el primero de
    // `faltan` habría sido TRAMITE_LLAVE y la pantalla le habría dicho **«traé tu llave» a
    // quien ya la trajo**. Ese es exactamente el bug que `modelo_no_elegido` existe para no
    // tener, y por eso sale por `estadoOperativo` (causa + botón) y no por acá.
    local: (req.descargado_ok && req.credencial_ok) || regresion,
    descargado_ok: req.descargado_ok,
    credencial_ok: req.credencial_ok,
    runtime_ok: req.runtime_ok,
    modelo_ok: req.modelo_ok !== false,
    faltan, rotar, regresion, admitida,
    // La medición envejeció ⇒ hay que re-medir ANTES de pintar verde. Verde viejo no
    // existe: o verde con fecha fresca, o causa con botón.
    rancia: medicionRancia(fila, o.ahora),
    // El motivo de quedarse afuera, con su FUENTE — para el [?] y para el censo.
    motivo: regresion ? (via === LOCAL ? "ya no está descargado" : "la sesión se cerró")
          : !req.descargado_ok ? (via === CLI ? "falta iniciar sesión" : "falta descargarlo")
          : !req.credencial_ok ? (via === CLI ? "falta iniciar sesión" : "falta la llave")
          : null,
    fuente: regresion ? "anduvo antes (registro: ultimo_veredicto=probado) y hoy le falta "
                      + "un requisito: es una regresión, no un onboarding a medias"
          : !req.descargado_ok ? "la fila declara que no está en la máquina"
          : !req.credencial_ok ? "no hay credencial para esta vía"
          : "sin pendientes del usuario",
  };
}

/** El estado OPERATIVO de un modelo del local. Nunca «falta descargar/llave»: eso vive en
 *  la aduana, y mezclarlos es lo que hace que el local deje de significar «lo que corre».
 *
 *  Devuelve `null` si no hay nada que reportar (o sea: anda). */
export function estadoOperativo(fila, pert) {
  if (!pert.local) return null;                      // no es del local: no aplica
  const authCli = fila.familia === CLI && fila.sesion_cli
    ? String(fila.sesion_cli.auth_state || "") : "";
  if (["expired", "not_authenticated", "unknown"].includes(authCli))
    return { causa: "sin_sesion", auth_state: authCli };
  if (pert.regresion) {
    return { causa: fila.causa || (fila.familia === LOCAL ? "sin_runtime" : "sin_sesion"),
             regresion: true };
  }
  if (pert.rotar) return { causa: fila.causa, rotar: true };
  // [F8 · obra 2] LA LLAVE ESTÁ Y NO HAY MODELO. Va ANTES del `roto` genérico a propósito:
  // el backend ya manda `roto/modelo_no_elegido`, pero esta capa deriva la causa de los
  // REQUISITOS y no de que el sidecar la haya escrito. Si mañana una fila llega sin causa
  // —un sidecar viejo, otra superficie— la pantalla sigue diciendo la verdad en vez de
  // pintar verde una vía que no tiene con qué pensar.
  if (!pert.modelo_ok) return { causa: "modelo_no_elegido", elegir: true };
  if (fila.estado === "roto" && fila.causa) return { causa: fila.causa };
  if (pert.rancia) return { rancia: true };          // hay que re-medir antes de pintar verde
  // ⚠️ [F7] SIN PROBAR NO ES ROTO Y NO ES VERDE — es el tercer estado, y faltaba.
  // Sin esto, un modelo completo pero nunca medido (`detectado`, o `probado` sin evidencia
  // con fecha) caía en el `else` de la superficie y se pintaba 🔴 «Roto»: castigar a una
  // pieza por no haberla medido todavía es la mentira simétrica a pintarla verde.
  if (fila.estado !== "probado" || !fila.prueba || !fila.prueba.ts) return { sin_probar: true };
  return null;
}

/* ══════════════════════════════════════════════════════════════════════════════════
 * ★★★ EL DERIVADOR ÚNICO DE LA FILA — estado → {glifo, tono, texto, rótulo, acción}
 * ══════════════════════════════════════════════════════════════════════════════════
 *
 * LEY SELLADA (persona usuaria, 2026-08-07), después de que la MISMA raíz mordiera CUATRO veces en
 * una sola tanda: el `●` gris del selector, el diccionario paralelo de estados, el glifo de
 * la lista, y el label/acción/contador/banner decidiéndose cada uno por su cuenta.
 *
 *   «Un solo derivador por fila: estado → {glifo, label, acción, copy}. Todo lo demás lo
 *    consume; nadie lo recalcula. El contador se deriva de esas mismas filas, no de una
 *    fuente paralela.»
 *
 * Mientras cuatro lugares opinen sobre la misma fila, la contradicción vuelve una quinta
 * vez. Esta función es el ÚNICO lugar donde se decide qué se ve de una fila; las
 * superficies renderizan lo que sale de acá y no vuelven a preguntarse nada.
 *
 * ⚠️ `tono` es SEMÁNTICO (`ok` · `tibia` · `mal`), no una clase CSS. Cada superficie le
 * pone su prefijo (`md-ok`, `sem-verde`…) — eso es un mapeo mecánico, no una decisión. Meter
 * el nombre de la clase acá ataría el derivador a UNA pantalla, que es el problema al revés.
 *
 * ⚠️ EL COPY ES SELLADO Y NUNCA EL NOMBRE TÉCNICO. Lo que se dibuja sale de `CAUSAS[...]`
 * («Credencial inválida»), jamás la causa cruda (`key_invalida`) ni la palabra «roto» ni el
 * cuerpo que devolvió el proveedor. El estado interno se llama como se quiera; lo que se
 * lee es otra cosa.
 */
export function semaforoDe(fila, pert, op, cara, medidoEn, ahora) {
  const E = (clave) => (Sem.ESTADOS && Sem.ESTADOS[clave]) || {};
  const authCli = fila.familia === CLI && fila.sesion_cli
    ? String(fila.sesion_cli.auth_state || "") : "";
  /* ⚠️ LA ADUANA NO ESTÁ ROTA — LE FALTA UN TRÁMITE, y son cosas distintas.
   *
   * MEDIDO sobre la app instalada: la cabecera decía **ROTOS 15**, contando como rojas las
   * filas de HF y los locales sin descargar. Una fila que nunca se configuró no está rota:
   * está en la aduana con su camino. Confundirlas convierte «lo que falta hacer» en «lo que
   * se rompió» — la misma mezcla que la ley del local prohíbe desde F4c. */
  if (!pert.local) {
    return { clave: "no_configurado", tono: "tibia", glifo: E("no_configurado").emoji || "⚪",
             texto: pert.motivo || "sin configurar", accion: null, rotulo: null,
             enAduana: true, probadoAlgunaVez: !!medidoEn };
  }
  if (["expired", "not_authenticated", "unknown"].includes(authCli)) {
    const ingles = lang() === "en";
    const camino = (cara && cara.camino) || {};
    if (authCli === "unknown") {
      return { clave: "detectado", tono: "tibia", glifo: E("detectado").emoji || "🟡",
               texto: ingles ? "session unverified" : "sesión sin verificar",
               accion: "probar", rotulo: ingles ? "Recheck session" : "Revisar sesión",
               probadoAlgunaVez: !!medidoEn };
    }
    const expired = authCli === "expired";
    return { clave: "roto", tono: "mal", glifo: expired ? "⚠" : E("roto").emoji || "🔴",
             texto: expired ? (ingles ? "session expired" : "sesión vencida")
                            : (ingles ? "not signed in" : "sin iniciar sesión"),
             accion: camino.accion || "login",
             rotulo: camino[ingles ? "en" : "es"] || (ingles ? "Sign in" : "Iniciar sesión"),
             probadoAlgunaVez: !!medidoEn };
  }
  const verde = !op && fila.estado === "probado" && !!fila.prueba && !!medidoEn;
  if (verde) {
    /* ⚠️ EL TEXTO DICE QUÉ SE MIDIÓ, y para el CLI eso NO es una inferencia.
     *
     * MEDIDO EN LA APP: Claude Code y Codex decían «probado hace 0s», SIEMPRE 0s. El `ts`
     * de esas filas es el de la sonda de SESIÓN —«¿hay sesión?»— que se re-estampa en cada
     * pintada; su evidencia es `{sesion_cli:true, servicio_local:true}` y ninguna generación
     * corrió jamás. Decir «probado hace 0s» sobre eso es afirmar una prueba que no hubo, y
     * el «0s» perpetuo es la delación: una medición real envejece.
     *
     * Que el CLI se corone por tener sesión es deuda con nombre y se salda aparte. Lo que
     * NO puede seguir es que el texto mienta mientras tanto: si el sensor es la sesión, el
     * texto dice «sesión activa». Misma fila, misma verdad. */
    const porSesion = !!(fila.prueba && fila.prueba.evidencia
                         && fila.prueba.evidencia.sesion_cli);
    return { clave: "probado", tono: "ok", glifo: E("probado").emoji || "🟢",
             texto: porSesion
               ? "sesión activa " + (haceTexto(medidoEn, ahora) || "")
               : "probado " + (haceTexto(medidoEn, ahora) || ""),
             // Un verde no necesita botón: no hay nada que resolver.
             accion: null, rotulo: null, probadoAlgunaVez: true, porSesion };
  }
  if (op && op.rancia) {
    // RANCIA no es un cartel: hay que re-medir ANTES de afirmar verde, y el re-verify ya
    // está en camino (lo dispara la caducidad). Por eso tampoco lleva botón.
    return { clave: "detectado", tono: "tibia", glifo: E("detectado").emoji || "🟡",
             texto: "comprobando…", accion: null, rotulo: null,
             probadoAlgunaVez: true };
  }
  if (op && op.sin_probar) {
    /* ⚠️ «SIN PROBAR» NO ES «VOLVER A PROBAR». Medido en la app: OpenRouter tenía llave,
     * decía «sin probar», y su botón decía **[Volver a comprobar]** — si nunca se probó no
     * hay a qué volver. El rótulo sale de si ESTA fila tiene una prueba con fecha, no de
     * una constante escrita en la pantalla. */
    const yaSeProbo = !!medidoEn;
    return { clave: "detectado", tono: "tibia", glifo: E("detectado").emoji || "🟡",
             texto: "sin probar", accion: "probar",
             rotulo: yaSeProbo ? "Volver a comprobar" : "Comprobar",
             probadoAlgunaVez: yaSeProbo };
  }
  /* ROJO. El texto SIEMPRE del diccionario sellado — nunca «roto», nunca el nombre de la
   * causa, nunca el cuerpo del proveedor. Sin cara conocida se dice lo único cierto. */
  return { clave: "roto", tono: "mal", glifo: E("roto").emoji || "🔴",
           texto: (cara && cara.titulo) || "No disponible por ahora",
           accion: (cara && cara.camino && cara.camino.accion) || null,
           rotulo: (cara && cara.camino && cara.camino.es) || null,
           probadoAlgunaVez: !!medidoEn };
}

/** «hace 2 min» — vive acá porque el TEXTO del semáforo se arma acá. La superficie ya no
 *  compone estado + fecha por su cuenta: recibe la línea hecha. */
export function haceTexto(ts, ahora) {
  if (!ts) return "";
  const s = Math.max(0, Math.round(((ahora || Date.now()) - ts * 1000) / 1000));
  if (s < 60) return `hace ${s}s`;
  if (s < 3600) return `hace ${Math.round(s / 60)} min`;
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
  return `hace ${Math.round(s / 86400)} d`;
}


/** derivar(fila) — el modelo COMPLETO que la superficie pinta. UNA función para toda vía.
 *
 * Cada elemento que sale de acá lleva su `fuente`: el campo del que salió o el verbo que lo
 * produjo. Un elemento sin fuente trazable es contenido hardcodeado, y la vara lo caza. */
export function derivar(fila, opciones) {
  const o = opciones || {};
  const pert = pertenencia(fila, o);
  const op = estadoOperativo(fila, pert);
  const cara = op && op.causa
    ? Sem.caraDeCausa({ causa: op.causa, detalle: "", reintentable: false }, o.ahora)
    : null;
  const evidencia = fila.prueba || null;
  const medidoEn = (fila.prueba && fila.prueba.ts) || null;
  return {
    ref: fila.ref || fila.slug || fila.alias,
    slug: fila.slug || fila.ref,
    via: fila.familia,
    label: fila.label,
    estado: fila.estado || null,
    // [F7] LO QUE LA FILA VIEJA MOSTRABA Y EL ADAPTADOR NO LLEVABA. Montar el adaptador
    // sin esto habría cambiado un bug (verde sin evidencia) por otro (perder el badge de
    // Default, el tier y —lo caro— el veredicto de disco de los candidatos de HF, que es
    // lo único que dice si un modelo entra en la máquina antes de bajarlo).
    // Se COPIAN de la fila, no se deducen: siguen teniendo un solo autor, el backend.
    marca: fila.marca || null,
    tier: fila.tier || null,
    origen: fila.origen || fila.familia || null,
    esDefault: !!fila.default,
    recomendado: !!fila.recomendado,
    // El campo ÚNICO del backend: «¿está conectada?» se responde en un solo lugar (y desde
    // F9 con una sola regla para todas las vías). La cabecera lo CUENTA, no lo re-deriva.
    conectado: fila.conectado === true,
    // ── [F8 · obra 2] QUÉ MODELO USA ESTA VÍA Y QUIÉN LO ELIGIÓ ───────────────────
    // Se COPIAN del backend, no se deducen (misma regla que `marca`/`tier`/`veredicto`):
    // el resolvedor es UNO y vive en `_modelo_de_api`. `modeloElegidoPor` es lo que le
    // permite a la card decir «usando X» sin mentir sobre de quién fue la decisión.
    modelo: fila.modelo_elegido !== undefined
      ? (fila.modelo_elegido || null) : (fila.model || null),
    modeloElegidoPor: fila.modelo_elegido_por || null,
    hf: !!fila.hf,
    veredicto: fila.veredicto || null,
    pertenencia: pert,
    // ── EL VERDE, SIEMPRE CON EVIDENCIA DETRÁS DEL [?] ────────────────────────────
    // Verde sin prueba no existe (ley del Cuarto honesto). Lo que se muestra es lo que
    // el verbo devolvió, con su fecha: «probado · respondió en 812 ms · hace 2 min».
    //
    // ⚠️ [F7] LAS TRES CONDICIONES SON UNA SOLA LEY, y antes se cumplía UNA. `verde` era
    // `pert.local && !op`: un modelo completo y sin falla operativa salía 🟢 aunque su
    // estado fuera `detectado` —o sea, **nunca probado**—, porque `estadoOperativo` sólo
    // mira `roto`. `incluido.cognicion` llega así en la app real. Ahora el verde exige
    // las tres: que el motor haya dicho PROBADO, que haya evidencia, y que tenga FECHA
    // (sin fecha no se puede envejecer, y entonces la caducidad de acá abajo no existe).
    verde: pert.local && !op && fila.estado === "probado" && !!evidencia && !!medidoEn,
    evidencia,
    medidoEn,
    // ── EL NO-VERDE, SIEMPRE CON CAUSA TIPADA Y BOTÓN QUE VALE ────────────────────
    operativo: op,
    cara,                                   // copy + camino, del diccionario ÚNICO
    // ★ EL DERIVADOR ÚNICO. Todo lo que la fila MUESTRA sale de acá: glifo, tono, texto,
    // rótulo y acción. Ninguna superficie vuelve a decidir nada de esto.
    semaforo: semaforoDe(fila, pert, op, cara, medidoEn, o.ahora),
    // ── LA ADUANA: qué trámite le falta, derivado ─────────────────────────────────
    tramite: pert.local ? null : (pert.faltan[0] || null),
    motivo: pert.motivo,
    fuente: pert.fuente,
  };
}

/** El censo de la pantalla. **El contador dice la verdad**: «Tus modelos» cuenta SOLO las
 *  completas, y por eso la aduana no infla el número que el usuario lee. */
export function censo(filas, opciones) {
  const ds = (filas || []).map((f) => derivar(f, opciones));
  return {
    local: ds.filter((d) => d.pertenencia.local),
    aduana: ds.filter((d) => !d.pertenencia.local),
    // el contador del local = sólo completas (incluye regresiones, que SON del local)
    n_local: ds.filter((d) => d.pertenencia.local).length,
    n_aduana: ds.filter((d) => !d.pertenencia.local).length,
    n_verdes: ds.filter((d) => d.verde).length,
  };
}
