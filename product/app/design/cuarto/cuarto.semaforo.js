/* cuarto.semaforo.js — EL SEMÁFORO (CUARTO HONESTO · T2 · §3).
 *
 * Cliente ÚNICO del Motor de Verdad (T1, /v1/motor/*) para toda la UI del Cuarto. Traduce el
 * resultado tipado del motor —{tipo, ref, estado, causa, evidencia, ts}— a lo que la ley §0.2
 * exige: ESTADO VISIBLE + CAMINO VISIBLE. Cada superficie (cards de Conectar, piezas del
 * diorama, closets, selector de modelo, chat del Guía, botón Ejecutar) pinta con esto; ninguna
 * inventa su propio color ni su propio "¿está ok?". Jamás verde sin evidencia del motor.
 *
 * NO decide la verdad (eso es el motor). Sólo: (1) la LEE barata (GET /estado) o la PRUEBA
 * (POST /probar), (2) la PINTA con el vocabulario cerrado de §1, y (3) para cada no-verde
 * ofrece EL botón exacto al workflow que lo arregla (§3). El workflow real vive en cada
 * superficie o es global (login/premium): este módulo lo despacha, no lo implementa.
 *
 * Contrato de §1 (vocabulario CERRADO — mismo que motor_verdad.py):
 *   estado ∈ {probado 🟢, detectado 🟡, roto 🔴, no_configurado ⚪, premium 🔒}
 *   causa  ∈ {falta_key, sin_red, cli_no_instalado, sin_sesion, timeout, error_upstream} | null
 *   tipo   ∈ {cerebro, mcp, key, cli}   ← el VALOR del contrato con el motor; no es texto de UI
 *
 * Sin dependencias (Pixi-free, framework-free). Se expone como ES module Y como
 * window.CuartoSemaforo (las superficies no-module lo usan por el global).
 */

// ── sesión → Bearer (MISMO patrón que catalog_equip.js / cuarto.inspect.js) ──────────
function _sessAuth(h) {
  h = h || {};
  try {
    const u = (window.AlephSession && window.AlephSession.get)
      ? window.AlephSession.get()
      : JSON.parse(sessionStorage.getItem("puppet_user") || localStorage.getItem("puppet_user") || "null");
    if (u && u.session_token) h["Authorization"] = "Bearer " + u.session_token;
  } catch (e) { /* sin sesión → el motor responde honesto (sin_sesion / owner nulo) */ }
  return h;
}

function _esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

// ── VOCABULARIO §1 · un tono por estado, cero colores nuevos fuera de este mapa ──────
// Los colores viven acá y en el CSS (.sem-*); las superficies NO los redefinen.
export const ESTADOS = {
  probado:        { emoji: "🟢", clave: "probado",        css: "sem-verde",   es: "Probado",         en: "Verified" },
  // Estado de la ENTIDAD Conector (no lo emite el motor por-server): al menos un
  // servidor/tool sano y al menos uno indisponible.
  parcial:        { emoji: "🟡", clave: "parcial",        css: "sem-amber",   es: "Parcial",         en: "Partial" },
  detectado:      { emoji: "🟡", clave: "detectado",      css: "sem-amber",   es: "Sin probar",      en: "Untested" },
  roto:           { emoji: "🔴", clave: "roto",           css: "sem-rojo",    es: "Roto",            en: "Broken" },
  no_configurado: { emoji: "⚪", clave: "no_configurado", css: "sem-blanco",  es: "Sin configurar",  en: "Not set up" },
  premium:        { emoji: "🔒", clave: "premium",        css: "sem-premium", es: "Premium",         en: "Premium" },
};

// ── CAUSAS §1 → texto honesto + qué workflow lo arregla (el "camino visible") ─────────
// accion = qué botón se ofrece; el label del botón y el destino los resuelve _botonDe().
// [FIX-P1B · §7 dura] LA 1ª LÍNEA DICE DE QUIÉN ES LA CULPA. No es cosmética: es la
// diferencia entre que la persona vaya a revisar su WiFi (que está bien) o su llave (que
// está mal). `culpa` ∈ {tuya, tu_maquina, proveedor, plan, aleph} — declarada, no implícita,
// para que ninguna superficie tenga que deducirla del texto.
export const CAUSAS = {
  falta_key:       { es: "Falta tu llave",         en: "Your key is missing",    accion: "credencial", culpa: "tuya" },
  sin_red:         { es: "Tu conexión está caída", en: "Your connection is down",accion: "reintentar", culpa: "tuya" },
  cli_no_instalado:{ es: "Ese programa no está instalado", en: "That program isn't installed", accion: "instalar", culpa: "tu_maquina" },
  sin_sesion:      { es: "No entraste a tu cuenta",en: "You're not signed in",   accion: "login",      culpa: "tuya" },
  timeout:         { es: "El servidor tardó demasiado", en: "The server timed out", accion: "reintentar", culpa: "proveedor" },
  error_upstream:  { es: "Error del proveedor",    en: "Provider error",         accion: "reintentar", culpa: "proveedor" },
  // ── vocabulario AMPLIADO del motor (mismas causas de motor_verdad.CAUSAS). Sin estas
  //    entradas caían todas en "Error del proveedor" — el fallo mudo que estamos matando.
  cli_version_vieja:      { es: "Tu programa está viejo",  en: "Your program is outdated", accion: "centro",     culpa: "tu_maquina" },
  cli_interactivo_colgado:{ es: "Quedó esperando teclado", en: "Stuck on a prompt",      accion: "reintentar", culpa: "tu_maquina" },
  cli_sin_permisos:       { es: "Sin permisos en tu máquina", en: "No permissions",     accion: "centro",     culpa: "tu_maquina" },
  plan_insuficiente:      { es: "Tu plan no lo cubre",     en: "Your plan doesn't cover it", accion: "centro", culpa: "plan" },
  // ⚠️ COPY SELLADO POR PERSONA USUARIA (2026-08-07). Decía «Tu llave no sirve»: cumplía la regla de
  // no decir «roto», pero el tono de Aleph es TÉCNICO Y NEUTRO y esa frase le habla al
  // usuario de tú a tú. `culpa: "tuya"` sigue viajando para el [?] y el reporte interno —
  // la atribución es un DATO, no algo que la card tenga que decir con el dedo.
  key_invalida:           { es: "Credencial inválida",      en: "Invalid credential",     accion: "credencial", culpa: "tuya" },
  sin_credito:            { es: "Tu cuenta no tiene saldo",en: "Your account is out of credit", accion: "centro", culpa: "tuya" },
  rate_limit:             { es: "El proveedor te frenó",   en: "The provider throttled you", accion: "reintentar", culpa: "proveedor" },
  modelo_no_disponible:   { es: "Ese modelo no está en tu plan", en: "That model isn't in your plan", accion: "centro", culpa: "plan" },
  // ── [FIX-P1B · §8] la culpa NUESTRA tiene nombre. Su camino no es un arreglo del
  //    usuario (no hay llave que poner ni programa que instalar): es un reporte.
  // ⚠️ LA CONFESIÓN ES INTERNA (ley sellada). Acá decía «Esto es un defecto nuestro» y su
  // camino era [Copiar el reporte]: le anunciábamos al usuario una falla nuestra Y le
  // pedíamos que nos hiciera el trabajo de reportarla. Dos cosas que no le sirven para nada.
  // La culpa sigue viajando en `culpa: "aleph"` —el [?] y el reporte interno la leen— pero
  // lo que se lee en la card es lo único accionable que hay: no está disponible ahora.
  falla_de_aleph:         { es: "No disponible por ahora", en: "Not available right now", accion: "no_disponible", culpa: "aleph" },
  proveedor_caido:        { es: "El proveedor está caído", en: "The provider is down",   accion: "reintentar", culpa: "proveedor" },
  // ── MODELOS LOCALES · deuda #1 de P8 disuelta ───────────────────────────────
  // Son causas del MISMO motor de verdad visible, no un vocabulario paralelo del Centro.
  // ── [obra 3] LAS DOS DEL RESOLVER DE MODELO, que viajaban SIN COPY ─────────
  // `model_use_resolver.py:145,158` las levanta con 409 y hasta acá no tenían entrada,
  // así que `(CAUSAS[causa] || {}).es` caía en el default y la causa **no se podía
  // mostrar en ninguna superficie**. Ninguna causa llega a una superficie sin copy.
  //
  // EL COPY DICE LA VERDAD DE CADA UNA, y son verdades distintas — meterlas en la misma
  // frase sería el gate que detectaba bien y diagnosticaba mal:
  //   · `capability_unavailable` = el modelo elegido SÍ declara su matriz, y le falta lo
  //     que este pedido exige (imagen, tools…). Se arregla eligiendo otro: `culpa: tuya`
  //     no es un reproche, es lo que dice de dónde sale el arreglo.
  //   · `capability_unknown` = el modelo NO declara nada, así que Aleph no sabe si puede.
  //     La falta es NUESTRA (`culpa: "aleph"`, que viaja para el [?] y el reporte
  //     interno) pero por la ley de la confesión interna lo que se lee es lo accionable.
  // ⚠️ COPY PROVISIONAL, derivado del mensaje del resolver. Queda marcado como tal hasta
  // que el dueño lo selle, igual que se hizo con las seis de F1c.
  capability_unavailable:  { es: "Ese modelo no hace lo que este pedido necesita", en: "That model can't do what this request needs", accion: "centro", culpa: "tuya" },
  capability_unknown:      { es: "Ese modelo no declara qué sabe hacer", en: "That model doesn't declare what it supports", accion: "centro", culpa: "aleph" },
  sin_runtime:             { es: "No hay con qué correrlo", en: "No runtime to run it", accion: "instalar_runtime", culpa: "tu_maquina" },
  sin_espacio:             { es: "No entra en tu máquina", en: "Doesn't fit on your machine", accion: "liberar", culpa: "tu_maquina" },
  descarga_cancelada:      { es: "La cortaste tú", en: "You canceled it", accion: "reintentar", culpa: "tuya" },
  formato_no_soportado:    { es: "Formato que no sé correr", en: "Unsupported format", accion: "ver_error", culpa: "aleph" },
  // ── [GATE 2 · F4b] LAS SEIS DE F1c, con su copy ────────────────────────────
  // F4a las agregó al vocabulario del motor y dejó el copy declarado como deuda de esta
  // fase: sin entrada acá, `(CAUSAS[causa] || {}).es || "roto"` las pintaba «Roto» —
  // exactamente el fallo mudo que las seis existen para matar.
  //
  // Las tres de ESPERAR llevan `culpa: "tu_maquina"` y no `"aleph"`, y es una decisión:
  // técnicamente el techo es NUESTRO (`origen: aleph` en la evidencia), pero la ley de la
  // confesión interna dice que al usuario no se le anuncia una falla nuestra. Y acá ni
  // siquiera hay falla: hay un turno adelante en SU máquina. «Tu CLI está ocupado» es a la
  // vez lo verdadero y lo accionable; «Aleph te frenó» sería confesión sin acción.
  contexto_excedido:      { es: "El pedido no entra en ese modelo", en: "Too long for that model", accion: "acortar",    culpa: "tuya" },
  politica_de_contenido:  { es: "El proveedor no acepta eso",      en: "The provider refused that", accion: "reformular", culpa: "proveedor" },
  cli_ocupado:            { es: "Tu CLI está con otro turno",      en: "Your CLI is on another turn", accion: "esperar",  culpa: "tu_maquina" },
  runtime_ocupado:        { es: "Tu modelo local está ocupado",    en: "Your local model is busy",  accion: "esperar",    culpa: "tu_maquina" },
  // Se rehace SOLA: el server rearma el turno con el contexto completo. Por eso no lleva
  // acción del usuario ni [Copiar el reporte] — que es lo que hacía cuando era
  // `falla_de_aleph`, o sea pedirle un bug report por algo que ya se está arreglando.
  sesion_perdida:         { es: "Se rearmó la conversación",       en: "Conversation restarted",    accion: "esperar",    culpa: "aleph" },
  // LA ÚNICA QUE NO ES UN FALLO. `alarma: false` no es cosmético: es lo que impide que la
  // Sala la pinte de rojo y le ofrezca un botón por una decisión que tomó el usuario.
  turno_detenido:         { es: "Lo paraste tú",                  en: "You stopped it",            accion: "ninguna",    culpa: "tuya", alarma: false },
  // ── [GATE 3 · obra 2/3] las dos de la COSTURA DE TOOLS ─────────────────────
  // ⚠️ COPY SELLADO POR PERSONA USUARIA (2026-08-07, obra A). Reemplaza al provisional que había
  // puesto F4b derivándolo de las varas — que era lo correcto mientras no hubiera copy
  // definitivo, y deja de serlo ahora que lo hay. Ninguna causa llega a una superficie sin
  // copy y ninguna se queda con el provisional cuando el definitivo existe.
  //
  // Lo que las varas dejaron sellado (`verify_costura_obra2.py:202-208`) y por qué manda:
  //   `argumentos_invalidos`  origen=modelo · reintentable=TRUE  → el que se equivocó fue el
  //       MODELO, no la persona: la culpa es nuestra (`aleph`) y el camino es reintentar. El
  //       copy nombra primero EL HECHO —la herramienta no corrió— y después el porqué,
  //       porque lo que la persona necesita saber es que la acción no pasó.
  //   `gate_bloqueado`        origen=aleph  · reintentable=FALSE → el gate hizo su trabajo.
  //
  // ⚠️ `gate_bloqueado` LLEVA `alarma: false`, Y ES EL ARREGLO, NO UN DETALLE. El provisional
  // no lo tenía, así que el gate se pintaba como un fallo — con cartel rojo y botón por una
  // PROTECCIÓN que funcionó. **EL GATE ES PROTECCIÓN, NO FALLO** (acta de persona usuaria, 2026-08-06),
  // la misma acta que ordena la obra 5, donde la línea de la Sala ya lo pinta ÁMBAR y no
  // rojo. Ésta es la otra mitad: que las superficies que preguntan por la CAUSA lleguen a la
  // misma respuesta que la que mira el evento. Y `accion: "ninguna"` por lo mismo que
  // `turno_detenido`: el [OK] ya está en la tarjeta del gate, y un segundo camino es la
  // lección que dejó el segundo [Reintentar]. Ver `repair_clasificar.GATE_BLOQUEADO`.
  // ── [GATE 3 · obra B] LA SUSTITUCIÓN DE MODELO ─────────────────────────────
  // ACTA 2 DE PERSONA USUARIA (2026-08-07): **SUSTITUIR SÍ, EN SILENCIO NO.** El modelo elegido no
  // produjo nada, entró el de respaldo y el turno SALIÓ.
  //
  // `alarma: false` porque **no falló nada**: la red de seguridad hizo su trabajo y el
  // usuario tiene su respuesta. Pintarlo rojo sería mentir sobre un resultado que estuvo
  // bien — el mismo criterio que la obra 5 selló para el gate. Pero tampoco es silencio: el
  // título dice el HECHO y el `detalle` que arma el emisor dice los tres datos que el acta
  // exige (qué se pidió, qué entró, por qué falló el primero).
  //
  // `culpa: "aleph"` porque la decisión de sustituir es NUESTRA, no del usuario ni del
  // proveedor. Y `accion: "ninguna"` porque no hay nada que el usuario deba hacer: si el
  // modelo elegido está caído de verdad, quien lo dice es el semáforo (`MV.probar`), que
  // es la puerta única — no un botón colgado de un aviso.
  //
  // ⚠️ COPY DERIVADO, PENDIENTE DE QUE PERSONA USUARIA LO SELLE. Se deriva del acta y del lenguaje de
  // las vecinas (mismo patrón que usó F4b con las dos de la costura). Dejarla sin entrada
  // sería entregar el fallo mudo que esta obra existe para matar.
  modelo_sustituido:      { es: "Corrí con el modelo de respaldo", en: "Ran with the backup model", accion: "ninguna", culpa: "aleph", alarma: false },
  argumentos_invalidos:   { es: "La herramienta no corrió: el pedido llegó mal armado", en: "The tool didn't run: the call came in malformed", accion: "reintentar", culpa: "aleph" },
  gate_bloqueado:         { es: "Esperando tu OK — ¿La hago, o la dejo?", en: "Waiting for your OK — go ahead, or leave it?", accion: "ninguna", culpa: "tuya", alarma: false },
  // ── [GATE 2 · F8] LA VÍA ESTÁ CONFIGURADA Y AUN ASÍ NO HAY CON QUÉ PENSAR ─────
  // ⚠️ CAUSA SELLADA POR PERSONA USUARIA (2026-08-07), y las tres decisiones son suyas:
  //
  //   · es CAUSA y no ESTADO. Un estado nuevo obliga a las seis superficies a aprender un
  //     color; una causa entra por el camino que ya existe (`roto/<causa>` → botón) y
  //     aparece con copy y salida el día uno.
  //   · `alarma: false`. No falló nada: la llave está, el proveedor contesta, y lo único
  //     que falta es una decisión de una lista. Pintarlo de rojo sería alarmar por un menú.
  //   · SIN `culpa`, y es la única del diccionario que no la lleva. Las otras responden
  //     «¿quién tiene que arreglar esto?»; acá no se equivocó nadie —ni el usuario, ni el
  //     proveedor, ni nosotros— y declarar una culpa falsa para llenar la columna sería
  //     inventar un dato que el [?] y el reporte interno leen como cierto.
  //
  // LO QUE MATA: que la fila dijera «Falta tu llave» con la llave PUESTA. Mandar a hacer
  // de nuevo el trámite que ya se hizo es el peor camino posible — no sólo no arregla, sino
  // que le enseña a la persona que la pantalla no sabe lo que ella acaba de hacer.
  modelo_no_elegido:      { es: "Modelo sin elegir",               en: "No model picked",              accion: "elegir_modelo", alarma: false },
};

/** [F4b] Causas que NO son fallos: no se pintan como alarma y no llevan botón.
 *  `repair_clasificar` las clasifica con la acción `sin_alarma` (F4a §2.2 ter), y esta
 *  constante es su reflejo en la cara — se DERIVA de `alarma: false`, no se escribe a mano,
 *  para que las dos mitades no puedan separarse.
 *
 *  [GATE 3 · obra A] Ya son DOS, y crecer fue la decisión que este comentario pedía que
 *  fuera explícita: `turno_detenido` (lo paró el usuario) y `gate_bloqueado` (el gate hizo
 *  su trabajo y está preguntando). Comparten la forma: el sistema funcionó, y lo que hay en
 *  pantalla es una decisión de la persona, no algo roto. La lista blanca del lado python
 *  está en `test_repair_clasificar._NO_SON_FALLOS`, y sumar una tercera tiene que costar
 *  tocar los dos archivos. */
export const SIN_ALARMA = new Set(
  Object.entries(CAUSAS).filter(([, v]) => v && v.alarma === false).map(([k]) => k));

/** ¿Esta causa merece cartel rojo? Público: lo consultan la Sala y el chat antes de pintar. */
export function esAlarma(causa) {
  return !!causa && !SIN_ALARMA.has(causa);
}

/** caraDeCausa(c) — una `CausaModelo` del backend → lo que la Sala pinta. (Gate 2 · F4b)
 *
 * ⚠️ VIVE ACÁ, JUNTO AL DICCIONARIO, Y NO EN LA SALA. El motivo es el mismo que
 * `widget.js` ya declara sobre `CAUSAS_HUMANAS`: **dos derivadores son cómo se llega a que
 * la misma falla se lea distinto según la pantalla.** El chat de la Sala, el Guía y la
 * card del Cuarto tienen que decir lo mismo ante `key_invalida`, y la única forma de
 * garantizarlo es que haya UNA función que lo derive.
 *
 * Entra el dict serializado de `errores_modelo.CausaModelo`
 * (`{causa, detalle, reintentable, retry_after_s, evidencia}`) y sale:
 *
 *   titulo   ← `CAUSAS[causa].es` — la línea corta, la misma del Cuarto
 *   texto    ← el `detalle` del TRADUCTOR, que ya viene redactado y con la acción adentro.
 *              **Jamás `str(exc)`**: ese puede traer el cuerpo crudo del proveedor.
 *   alarma   ← false para lo que no es un fallo (`turno_detenido`)
 *   camino   ← `caminoDe`, o sea el MISMO mapa causa→botón, con su guard de
 *              «reintentar sobre permanente se degrada» ya aplicado
 *   hora     ← si el proveedor dijo CUÁNDO (`retry_after_s`), la hora de pared. El
 *              «esperá» sin hora es un consejo; con hora es un dato.
 *
 * Devuelve `null` sin causa: quien llama sigue con su camino de siempre. Una causa que el
 * diccionario no conoce igual sale con su `detalle` y `desconocida: true` — se ve que
 * falta una entrada, en vez de quedar muda.
 */
//: [Gate 4 · F5 · 5.1] LA MISMA CAUSA, DICHA DISTINTO SEGÚN EL MOTIVO.
//: NO es un vocabulario nuevo —la causa sigue siendo UNA, sellada y con su copy— sino la
//: precisión que la evidencia del traductor ya traía y que la superficie tiraba. Sólo se
//: pisa lo que cambia de verdad: la línea corta y **de quién es la culpa**.
export const MOTIVOS = {
  // El 413 por cinturón es de la casa, no de la persona: nosotros armamos el pedido.
  // `culpa: "aleph"` y no `"tuya"` — y la ley de la confesión interna no aplica acá
  // porque SÍ hay una acción suya que resuelve (sacar una pieza, cambiar de modelo).
  "contexto_excedido#demasiadas_tools": {
    es: "Tu agente no entra en este modelo",
    en: "Your agent doesn't fit this model",
    culpa: "aleph",
  },
};

export function caraDeCausa(c, ahora) {
  if (!c || !c.causa) return null;
  const motivo = (c.evidencia && c.evidencia.motivo) || "";
  // `base` decide `desconocida` (una causa que el diccionario no vio nunca) y `meta` es
  // lo que se PINTA. Se separan a propósito: fusionar el motivo sobre un `{}` haría que
  // toda causa pareciera conocida y mataría la señal que avisa que falta una entrada.
  const base = CAUSAS[c.causa];
  const meta = (motivo && MOTIVOS[c.causa + "#" + motivo])
    ? Object.assign({}, base, MOTIVOS[c.causa + "#" + motivo])
    : base;
  const camino = caminoDe({ estado: "roto", causa: c.causa, motivo: motivo });
  let hora = null;
  const seg = Number(c.retry_after_s);
  if (isFinite(seg) && seg > 0) {
    const t = new Date((ahora || Date.now()) + seg * 1000);
    hora = String(t.getHours()).padStart(2, "0") + ":" + String(t.getMinutes()).padStart(2, "0");
  }
  return {
    causa: c.causa,
    titulo: (meta && meta.es) || "Algo falló",
    texto: c.detalle || "",
    culpa: (meta && meta.culpa) || null,
    alarma: esAlarma(c.causa),
    reintentable: !!c.reintentable,
    camino: camino,
    sinBoton: !!(camino && camino.sinBoton),
    hora: hora,
    desconocida: !base,
  };
}

//: [§7 dura] ¿REINTENTAR PUEDE FUNCIONAR? Reintentar una causa PERMANENTE es el botón que
//: deja a la persona igual: la llave sigue siendo inválida, el programa sigue sin estar, el
//: modelo sigue fuera del plan. Estas causas ofrecen EL BOTÓN QUE RESUELVE, jamás el que
//: repite. Lo que no está acá sí puede cambiar solo entre un intento y el siguiente.
export const CAUSAS_PERMANENTES = new Set([
  // las dos del resolver son PERMANENTES: reintentar con el mismo modelo da lo mismo.
  "capability_unavailable", "capability_unknown",
  "falta_key", "key_invalida", "cli_no_instalado", "sin_sesion", "plan_insuficiente",
  "modelo_no_disponible", "sin_credito", "cli_version_vieja", "cli_sin_permisos",
  "falla_de_aleph", "sin_runtime", "sin_espacio", "formato_no_soportado",
  // [REPAIR · R4] LAS QUE FALTABAN, y no era cosmético. `repair_clasificar` las da por
  // PERMANENTES y esta lista no las tenía, así que el guard de `caminoDe` no las degradaba:
  // · `cli_interactivo_colgado` estaba en CAMINOS como [Conectar de nuevo] — un reintento
  //   sobre un server que espera un prompt que nadie va a contestar devuelve el mismo rojo;
  // · `servidor_incompatible` no estaba en ninguna de las dos.
  // La regla la fija `test_repair_boton.py`: esta lista y la de repair no pueden separarse.
  "cli_interactivo_colgado", "servidor_incompatible", "no_es_mcp", "fallo_desconocido",
  "sin_tools", "sin_tool_sondeable",
  // [ONSHAPE · OAuth] Un grant revocado en el proveedor no vuelve solo: reintentar pega
  // contra el mismo `invalid_grant`. El botón que resuelve es reconectar (volver a
  // consentir), NUNCA revisar una llave que está perfecta.
  "oauth_revocado",
  // [GATE 2 · F1c] Las tres NO-reintentables de las seis causas selladas. Es lo ÚNICO que
  // F4a toca de la UI, y lo toca porque `test_repair_boton.py` lo exige con el motivo
  // escrito: si repair las da por permanentes y esta lista no las tiene, `puedeReintentar`
  // devuelve true y **la superficie ofrece un [Reintentar] imposible**.
  //   · `contexto_excedido`     el mismo texto no entra la próxima vez; hay que acortarlo
  //   · `politica_de_contenido` una negativa repetida sigue siendo la misma negativa
  //   · `turno_detenido`        lo paró el usuario: reintentar es DESHACER SU DECISIÓN
  // El COPY de las tres (su entrada en `CAUSAS`/`CAMINOS`) es de F4b — hoy ninguna llega
  // a esta superficie, porque el motor mide conexiones y estas seis son de inferencia
  // (`motor_verdad.CAUSAS_F1C`, y `verify_f4a.py` lo verifica).
  "contexto_excedido", "politica_de_contenido", "turno_detenido",
  // [GATE 2 · F8] Reintentar no elige un modelo. El catálogo va a volver igual y la fila va
  // a seguir sin elección: lo único que cambia el resultado es que alguien elija. Está acá
  // para que el guard de `caminoDe` no pueda degradarla nunca a un [Reintentar] imposible.
  "modelo_no_elegido",
]);

/** ¿Tiene sentido ofrecer [Reintentar] ante este resultado? Público: lo consultan las
 *  superficies antes de pintar un reintento propio (y la vara, para calibrar en rojo). */
export function puedeReintentar(res) {
  if (!res || res.estado !== "roto") return false;
  return !CAUSAS_PERMANENTES.has(res.causa || "");
}

const TIPOS = new Set(["cerebro", "mcp", "key", "cli"]);

// ══ caminoDe(causa) — EL DICCIONARIO ÚNICO causa→botón (hermano de faltaDe) ═══════════
// faltaDe() conjuga la falta ("Gmail necesita tu llave"); caminoDe() da EL BOTÓN que la
// resuelve. Uno dice qué pasa, el otro a dónde se va. Las dos mitades del §0.2 (ESTADO
// VISIBLE + CAMINO VISIBLE), y una sola tabla para las dos: el chat, el diorama, el
// preflight, el Centro y los closets ofrecen LA MISMA salida ante la MISMA causa.
//
//   ⚪ falta conexión   → [Conectar]
//   🔴 falta credencial → [Poner la key]  (inline: el widget se abre EN el lugar, no navega)
//   🔴 error proveedor  → [Probar de nuevo] + [Ver error]
//   🟡 sin probar       → [Probar ahora]
//   🔒 premium          → [Ver planes]
//
// REGLA: una causa que no está acá NO inventa botón. Cae al texto canónico honesto de
// CAUSAS + [Ver error] (que es real: destapa la evidencia cruda). Jamás un botón falso.
const _VER_ERROR = { accion: "ver_error", es: "Ver error", en: "See error" };

/** LA TERCERA SALIDA DE LA LEY (sellada por persona usuaria): cuando no hay nada que el usuario pueda
 *  hacer, la card dice ESO y nada más. Ni una confesión («defecto nuestro», «no sé qué
 *  pasó»), ni un trámite que nos hace el trabajo («copiá el reporte»), ni un botón que
 *  devuelve el mismo rojo.
 *
 *  `interno: true` es la costura: la causa técnica, la traza y la culpa siguen viajando
 *  intactas hacia el [?] y el reporte interno — la honestidad del sistema no se pierde, se
 *  guarda donde sirve para arreglar en vez de exhibirse donde sólo preocupa. */
const _NO_DISPONIBLE = {
  accion: "no_disponible", es: "No disponible por ahora",
  en: "Not available right now", interno: true,
};

/** [REPAIR · R4] Causas CONOCIDAS que a propósito NO llevan botón: no hay acción del usuario
 *  que sirva, así que la salida honesta es la evidencia + la escalada (§5 del diseño de
 *  repair). Están acá para poder distinguirlas de una causa nueva de verdad. */
export const SIN_BOTON = new Set([
  "no_es_mcp", "fallo_desconocido", "sin_tools", "sin_tool_sondeable",
  // R5 · llega acá SÓLO después de que el auto-ajuste de versión falló (un intento, sin
  // loops). Ofrecer un botón encima sería pedirle al usuario que repita lo que ya se hizo.
  "servidor_incompatible",
]);

export const CAMINOS = {
  // ── EL VOCABULARIO DEL REGISTRO ────────────────────────────────────────────────────
  // La UI se cablea al REGISTRO (`viva` · `sin_sondear` · `rota`), no al semáforo viejo del
  // motor (`probado` · `detectado` · …). Los dos vocabularios conviven acá a propósito: el
  // del motor sigue sirviendo al [?] técnico, y esta tabla es la única que traduce a botón,
  // así que hay UN lugar donde mirar cuando una card no ofrece nada.
  //
  // `viva` no está: una conexión que anda no necesita botón, y ponerle uno sería inventarle
  // un trámite. `caminoDe` devuelve null para ella, explícitamente.
  //
  // ⚠️ `sin_sondear` TAMPOCO ESTÁ, y acá estuvo mi error de la primera pasada: le puse
  // [Probar ahora]. Un botón así no es una solución, es **trabajo interno delegado**:
  // `sin_sondear` significa que NOSOTROS no encontramos una tool llamable sin inventarle un
  // argumento — un límite de nuestra medición, no algo que el usuario pueda arreglar. Para
  // eso se construyeron el verificador, el calentador y repair: el sistema mide solo y
  // pinta el resultado. Lo maneja `necesitaMedicionInterna()`, no esta tabla.
  // por ESTADO del motor (sin causa)
  "parcial":        { accion: "reintentar", es: "Conectar de nuevo", en: "Connect again" },
  // ⚠️ `detectado` NO LLEVA BOTÓN. Decía [Conectar] con acción `probar`, o sea: pedirle al
  // usuario que dispare NUESTRA medición. La credencial ya está; lo que falta es que
  // `verify` corra — y `verify` corre solo (calentador al abrir el agente, y
  // `necesitaMedicionInterna` en la card). Un botón acá era trabajo interno delegado.
  "no_configurado": { accion: "configurar", es: "Conectar",       en: "Connect", wizard: true },
  "premium":        { accion: "premium",    es: "Ver planes",     en: "See plans" },
  // por CAUSA (estado roto) — la clave es "roto/<causa>"
  // `wizard: true` = esta reparación ABRE EL WORKFLOW DE SU TIPO (§1). No es un segundo
  // diccionario: es una columna más de ÉSTE. El tipo concreto (cuenta web · llave ·
  // suscripción · programa) lo resuelve el wizard con el contexto de la pieza, porque
  // depende de datos que esta tabla no tiene (y no debe tener) — el catálogo del conector.
  "roto/falta_key":               { accion: "credencial", es: "Poner la llave",   en: "Add your key",    inline: true, wizard: true },
  "roto/key_invalida":            { accion: "credencial", es: "Cambiar la llave", en: "Change your key", inline: true, wizard: true },
  "roto/sin_sesion":              { accion: "login",      es: "Iniciar sesión",   en: "Sign in" },
  "roto/cli_no_instalado":        { accion: "instalar",   es: "Instalarlo",       en: "Install it",      wizard: true },
  // [FIX-P3 · §2] LA FUSIÓN, en el diccionario y no en cada superficie. «Probar» y
  // «Reintentar» eran DOS rótulos para EL MISMO disparo (`probarPieza`), y tener los dos
  // hacía que la persona buscara la diferencia que no existe. La acción sigue llamándose
  // `reintentar` —es el VALOR del contrato, y las superficies deciden con él— pero el
  // RÓTULO es uno solo: [Probar de nuevo]. Cero botón «Reintentar» en el Cuarto.
  "roto/error_upstream":          { accion: "reintentar", es: "Conectar de nuevo", en: "Connect again", extra: _VER_ERROR },
  "roto/sin_red":                 { accion: "reintentar", es: "Conectar de nuevo", en: "Connect again", extra: _VER_ERROR, autoAlVolver: true },
  "roto/timeout":                 { accion: "reintentar", es: "Conectar de nuevo", en: "Connect again", extra: _VER_ERROR },
  "roto/proveedor_caido":         { accion: "reintentar", es: "Conectar de nuevo", en: "Connect again", extra: _VER_ERROR, conHora: true },
  "roto/rate_limit":              { accion: "reintentar", es: "Conectar de nuevo", en: "Connect again", extra: _VER_ERROR },
  // repair la clasifica PERMANENTE · MANO_HUMANA («esperó un prompt que nadie puede
  // contestar»): no hay acción del usuario que sirva, y [Ver error] sólo lo mandaba a
  // nuestra evidencia. Tercera salida, con la traza entera en el [?].
  "roto/cli_interactivo_colgado": Object.assign({}, _NO_DISPONIBLE, { reporte_interno: true }),
  "roto/cli_version_vieja":       { accion: "instalar",   es: "Actualizarlo",     en: "Update it",       wizard: true },
  "roto/cli_sin_permisos":        { accion: "centro",     es: "Dar permisos",     en: "Grant access" },
  "roto/plan_insuficiente":       { accion: "premium",    es: "Ver planes",       en: "See plans" },
  "roto/sin_credito":             { accion: "centro",     es: "Ver la cuenta",    en: "Open account" },
  "roto/modelo_no_disponible":    { accion: "centro",     es: "Elegir otro modelo", en: "Pick another model" },
  // [F8] `inline: true` como la llave: el picker se abre EN la card, no navega. Es la
  // diferencia entre resolverlo donde apareció y mandar a la persona a buscar la pantalla.
  // NO lleva `wizard`: no hay trámite que hacer —ni cuenta, ni credencial, ni instalación—,
  // hay una lista de la que se elige uno.
  "roto/modelo_no_elegido":       { accion: "elegir_modelo", es: "Elegir modelo",  en: "Pick a model",    inline: true },
  // §8 · lo nuestro no manda a nadie a configurar nada: entrega el reporte.
  // §8 · lo nuestro NO se le cuenta al usuario ni se le delega. El reporte se sigue armando
  // —lo consume el [?] y la escalada interna— pero la card no le pide que lo copie.
  "roto/falla_de_aleph":          Object.assign({}, _NO_DISPONIBLE, { reporte_interno: true }),
  // ── [GATE 2 · F4b] las seis de F1c ─────────────────────────────────────────
  // LAS DOS DEL PEDIDO no llevan botón, y no es un olvido: lo que hay que cambiar es el
  // texto que la persona escribió, y eso pasa en el chat, no en un botón nuestro. Un
  // [Reintentar] acá devolvería la MISMA negativa gastando otra llamada — que es
  // exactamente lo que hacían cuando eran `error_upstream`.
  "roto/contexto_excedido":       { accion: "acortar",    es: "Acorta el pedido y mándalo de nuevo", en: "Shorten it and send again", sinBoton: true },
  // [Gate 4 · F5 · 5.1] EL MISMO 413, PERO LA CULPA NO ES SUYA.
  // Medido 2026-08-08: 5 piezas equipadas = 49 tools, y Groq rechaza el pedido entero
  // (HTTP 413) con la cuota intacta. El usuario no escribió nada largo: **le mandamos el
  // cinturón entero al modelo**. Decirle «acortá el pedido» ahí es pedirle que arregle
  // algo que no hizo y que además no puede: puede borrar su mensaje entero y el 413
  // vuelve igual.
  // La casa ya intentó sola (presupuesto + repliegue de `tool_budget`); si esta card se
  // ve, es porque ni con la mitad entró. Las dos salidas REALES son suyas y son las que
  // se nombran: menos piezas equipadas, u otro modelo que acepte pedidos más grandes.
  "roto/contexto_excedido#demasiadas_tools": {
    accion: "reducir_cinturon",
    es: "Tu agente lleva más herramientas de las que este modelo acepta por pedido. Saca alguna pieza en El Cuarto, o elige un modelo con más lugar.",
    en: "Your agent carries more tools than this model accepts per request. Remove a piece in El Cuarto, or pick a model with more room.",
    sinBoton: true,
  },
  "roto/politica_de_contenido":   { accion: "reformular", es: "Reformula el pedido",                 en: "Rephrase your request",     sinBoton: true },
  // LAS TRES DE ESPERAR sí ofrecen reintentar, porque el reintento SÍ puede salir bien:
  // el turno de adelante termina en segundos. `conHora` sólo donde hay hora que decir.
  "roto/cli_ocupado":             { accion: "reintentar", es: "Probar de nuevo", en: "Try again", extra: _VER_ERROR },
  "roto/runtime_ocupado":         { accion: "reintentar", es: "Probar de nuevo", en: "Try again", extra: _VER_ERROR },
  // SE ARREGLA SOLA — el server ya rearmó el turno. Ofrecer algo sería pedirle a la
  // persona que haga lo que el sistema está haciendo.
  "roto/sesion_perdida":          { accion: "esperar",    es: "Se rearmó sola", en: "Restarted on its own", sinBoton: true },
  // NO ES UN FALLO. Sin botón, sin alarma, sin evidencia de error: alguien apretó parar y
  // el sistema hizo lo que le pidieron. Ver `SIN_ALARMA`.
  "roto/turno_detenido":          { accion: "ninguna",    es: "Lo paraste tú", en: "You stopped it", sinBoton: true, alarma: false },
  // [REPAIR · R5] `servidor_incompatible` NO LLEVA BOTÓN, y es una decisión sellada, no un
  // hueco: **la receta es territorio de Aleph, no del usuario**. Cuando el paquete publica
  // una versión incompatible, repair vuelve solo a la última que anduvo (UPDATE a la fila,
  // jamás al catálogo) y relevanta. Si sale VIVO, el usuario no ve card ni botón — se entera
  // en el [?], que dice cuándo se ajustó. Pedirle permiso para arreglar algo que es nuestro
  // sería mandarle un trámite por un problema que no creó.
  //
  // Si el ajuste NO alcanza, recién ahí llega acá: sin botón, a la ESCALADA con su traza.
  // Por eso está en SIN_BOTON y no en CAMINOS — para cuando el usuario lo ve, ya se probó
  // lo único que se podía probar solo.
  // Modelos locales: los cuatro caminos viven en la tabla ÚNICA de la casa.
  "roto/sin_runtime":             { accion: "instalar_runtime", es: "Instalar el runtime", en: "Install the runtime" },
  "roto/sin_espacio":             { accion: "liberar",          es: "Liberar espacio", en: "Free up space" },
  "roto/descarga_cancelada":      { accion: "reintentar",       es: "Descargar de nuevo", en: "Download again" },
  "roto/formato_no_soportado":    Object.assign({}, _NO_DISPONIBLE, { reporte_interno: true }),
};

/** caminoDe(res) → {accion, es, en, inline?, extra?} | null (verde no fuerza camino).
 *  Una causa desconocida NO cae en un botón inventado: devuelve [Ver error], que sí lleva
 *  a alguna parte real (la evidencia), con el texto canónico de CAUSAS al lado. */
/** ¿Esta fila necesita que MIDAMOS NOSOTROS, en background, sin molestar a nadie?
 *
 * LEY (persona usuaria, 2026-08-04): **lo interno se arregla solo, no se muestra.** Para eso existen
 * el verificador, el calentador y repair. Una card sólo puede pedirle algo al usuario
 * cuando la acción es SUYA —su llave, su programa, su cuenta, su plan—. Todo lo demás lo
 * dispara el sistema y la card pinta el resultado cuando llega.
 *
 * Los dos casos son exactamente los que antes se le devolvían como duda:
 *   · `sin_sondear` — el canal está establecido y no hallamos tool sondeable. Nuestro.
 *   · credencial `sin_medir` / `candidata` — la llave está, no la probamos todavía. Nuestro.
 *
 * Devuelve `false` para lo que YA se midió (no se re-mide de gusto) y para lo que es del
 * usuario (no se le pisa su trámite con una medición nuestra).
 */
export function necesitaMedicionInterna(cx, cr) {
  const estadoCx = cx && cx.estado;
  const estadoCr = cr && cr.estado;
  if (estadoCx === "sin_sondear" || estadoCx === "detectado") return true;
  if ((estadoCx === "viva" || estadoCx === "sin_sondear") &&
      (estadoCr === "sin_medir" || estadoCr === "candidata")) return true;
  return false;
}

export function caminoDe(res) {
  let estado = res && res.estado;
  if (!estado) return null;
  // ⚠️ LOS DOS ESTADOS DE «FALTA MEDIR» NO OFRECEN BOTÓN. `sin_sondear` (canal arriba, sin
  // tool sondeable) y `detectado` (credencial puesta, `verify` todavía no corrió) son
  // pendientes NUESTROS, no trámites suyos: los dispara `necesitaMedicionInterna()` y la
  // card pinta el resultado cuando vuelve. Un botón acá era pedirle al usuario que
  // ejecutara un verbo que corre solo.
  if (estado === "sin_sondear" || estado === "detectado") return null;
  // EL PUENTE ENTRE LOS DOS VOCABULARIOS, en una línea y con nombre. El registro dice
  // `rota`; el motor dice `roto`. Traducir acá —y no en cada superficie— es lo que hace que
  // el mapa causa→botón siga siendo UNO: si cada card normalizara por su cuenta, dos
  // pantallas podrían ofrecer botones distintos para la misma fila.
  if (estado === "rota") estado = "roto";
  // Verde de cualquiera de los dos vocabularios: nada que resolver, ningún botón.
  if (estado === "probado" || estado === "viva") return null;
  if (estado === "roto") {
    const causa = (res && res.causa) || "";
    // [Gate 4 · F5 · 5.1] UNA CAUSA, DOS CAMINOS. `contexto_excedido` llega por dos
    // motivos que piden cosas OPUESTAS del usuario: si el texto es largo, lo acorta él;
    // si lo que no entró fue el cinturón, no hay nada que él pueda acortar y mandarlo a
    // hacerlo es mandarlo a perder la tarde. El motivo viaja en la evidencia del
    // traductor; si no viene, el camino es el de siempre, byte por byte.
    const motivo = (res && res.motivo) || "";
    const c = (motivo && CAMINOS["roto/" + causa + "#" + motivo]) || CAMINOS["roto/" + causa];
    if (c) {
      // [§7 dura · el guard] Una entrada que ofrezca [Reintentar] sobre una causa
      // PERMANENTE es un bug de tabla, no una opción de diseño: el reintento devolvería el
      // mismo rojo. Se degrada a [Ver error], que sí lleva a algo real. Está acá y no en
      // una revisión manual para que la regla no dependa de que nadie se equivoque.
      if (c.accion === "reintentar" && CAUSAS_PERMANENTES.has(causa))
        return Object.assign({}, _VER_ERROR, { degradado: "reintento_imposible" });
      return Object.assign({}, c);
    }
    // [REPAIR · R4] «SIN BOTÓN» ≠ «DESCONOCIDA», y la diferencia importa: `desconocida`
    // significa «apareció una causa que esta tabla no vio nunca» —una señal para quien
    // mantiene el diccionario— mientras que `no_es_mcp`, `sin_tools` y compañía se
    // decidieron a propósito sin botón porque **no hay acción del usuario que sirva**.
    // Marcarlas como desconocidas hacía que un hueco deliberado se leyera como un olvido.
    // LEY · CERO DEAD-ENDS. Antes las dos salidas de acá eran [Ver error]: un botón que
    // lleva a la evidencia técnica, o sea a nuestra incertidumbre. Para el usuario eso no
    // es un camino, es una sala de espera con jerga adentro. Las dos pasan a la tercera
    // salida declarada —«no disponible por ahora»— y el detalle sigue entero en el [?].
    if (SIN_BOTON.has(causa))
      return Object.assign({}, _NO_DISPONIBLE, { sin_boton: true });
    // Una causa que esta tabla nunca vio sigue marcándose `desconocida` PARA NOSOTROS —es
    // la señal de que el diccionario quedó corto— pero el usuario no ve un «no sé qué pasó»:
    // ve la misma puerta honesta que en cualquier otro caso sin acción.
    return Object.assign({}, _NO_DISPONIBLE, { desconocida: true });
  }
  const c = CAMINOS[estado];
  if (c) return Object.assign({}, c);
  // ⚠️ NINGÚN ESTADO SE QUEDA SIN SALIDA. `viva` y `probado` ya salieron arriba con null,
  // porque no hay nada que resolver. Cualquier OTRO estado que llegue sin entrada en la
  // tabla es un hueco, y un hueco pintaba una card MUDA: sin texto y sin botón. Cae a «no
  // disponible por ahora», que al menos es cierto, y se marca para que el guard lo nombre.
  return Object.assign({}, _NO_DISPONIBLE, { estado_sin_camino: estado });
}

/** PIEZA LOCAL SIN TRÁMITE (§1 · una pieza sin credencial no tiene trámite que hacer).
 *  pysandbox/sqlite/files/wikipedia no llevan llave y no se "configuran": o corren (🟢) o
 *  están rotas con su causa (🔴). Cualquier ⚪/falta_key sobre una pieza así es un estado
 *  IMPOSIBLE — casi siempre el motor respondiendo por una coordenada equivocada. Se
 *  normaliza acá, en el único lugar por donde pasan todas las superficies. */
// SIN CREDENCIAL = SIN TRÁMITE. `auth === "keyless"` es el único dato que importa: varias
// piezas locales declaran un `connector` (pysandbox, wikipedia, arxiv…) que NO pide nada —
// es un nombre de proveedor, no una puerta con llave. Mirar el connector las mandaba a
// "configurar" una cuenta que no existe.
export function esLocalSinTramite(d) {
  if (!d) return false;
  if (d.nativa) return true;
  return (d.auth || "keyless") === "keyless" && (d.atom || "tool") !== "conexion";
}

export function normalizarLocal(res, local) {
  if (!local || !res) return res;
  if (res.estado === "no_configurado")
    return Object.assign({}, res, { estado: "detectado", causa: null,
      evidencia: Object.assign({}, res.evidencia, { local: true, detail: "corre en tu máquina — no lleva llave" }) });
  // Un keyless que vuelve con falta_key es una CONTRADICCIÓN (no hay dónde poner esa llave:
  // la pieza no tiene onboarding). Se cambia la CAUSA, no la evidencia: el mensaje crudo del
  // motor sigue entero detrás de [Ver error]. Nada se esconde; lo que se saca es un botón
  // que llevaba a una pantalla vacía.
  if (res.estado === "roto" && (res.causa === "falta_key" || res.causa === "key_invalida"))
    return Object.assign({}, res, { causa: "error_upstream",
      evidencia: Object.assign({}, res.evidencia, { local: true }) });
  return res;
}

function _toolsDeServidor(server, estado) {
  const declared = (server && server.tools || []).map(String);
  const aliases = server && server.tool_aliases || {};
  const final = (raw) => String(aliases[raw] || raw);
  const evidence = estado && estado.evidencia || {};
  // ⚠️ NO MEDÍ ≠ MEDÍ Y DIO CERO. Acá se devolvía `cantidadDisponible: 0`,
  // `noDisponibles: [todas]` y `nombresComprobados: true` para CUALQUIER estado que no
  // fuera `probado` — incluida la ausencia total de medición (`!estado`). O sea que una
  // pieza que nadie probó decía, en el mismo aliento, «sin probar» · «0 disponibles» · «y
  // los nombres los comprobé». Las tres afirmaciones salían de la lista DECLARADA del
  // catálogo, no de una medición: ninguna se había preguntado nunca.
  //
  // Es la misma clase que ya costó dos veces: el gate de secretos diciendo «client_secret
  // ausente» sin haber comparado nada, y el `ScrubReport` que hacía pasar un test de fuga
  // sin redactar. Ausencia de medición presentada como medición negativa.
  //
  // Diez líneas más abajo, la rama de `tool_count` SÍ distingue —«el motor contó, pero no
  // dijo CUÁLES»—. Ésta ahora también: `sinMedir` viaja hasta la evidencia y la UI dice
  // «sin medir», jamás un cero que nadie contó.
  if (!estado || estado.estado !== "probado") {
    return {
      disponibles: [],
      noDisponibles: [],
      cantidadDisponible: null,      // null = NO SE SABE. Cero es un número; esto no lo es.
      nombresComprobados: false,
      sinMedir: true,
      declaradas: declared.map(final),   // lo que el catálogo DECLARA, nombrado como tal
    };
  }
  if (Array.isArray(evidence.tools)) {
    const actual = new Set(evidence.tools.map(String));
    const disponibles = declared.filter((tool) => actual.has(tool)).map(final);
    return {
      disponibles,
      noDisponibles: declared.filter((tool) => !actual.has(tool)).map(final),
      cantidadDisponible: disponibles.length,
      nombresComprobados: true,
    };
  }
  if (Number.isFinite(evidence.tool_count)) {
    // El motor contó, pero no dijo CUÁLES. Conservamos el número sin inventar nombres.
    const cantidadDisponible = Math.min(declared.length, Number(evidence.tool_count));
    return {
      disponibles: [],
      noDisponibles: [],
      cantidadDisponible,
      nombresComprobados: cantidadDisponible === declared.length,
    };
  }
  return {
    disponibles: declared.map(final),
    noDisponibles: [],
    cantidadDisponible: declared.length,
    nombresComprobados: true,
  };
}

/** Agregador ÚNICO de la entidad Conector, compartido por Conectores y El Cuarto.
 * Un rojo interno jamás puede salir verde; una credencial ausente es blanco, no fallo. */
export function agregarEstadoEntidad(entry, serverRows, credentialConnected) {
  const servers = entry && entry.servers || [];
  const total = servers.reduce((n, server) => n + (server.tools || []).length, 0);
  if (entry && entry.credential && !credentialConnected) {
    const noDisponibles = servers.flatMap((server) =>
      (server.tools || []).map((raw) => String(
        server.tool_aliases && server.tool_aliases[raw] || raw
      ))
    );
    // MISMA CLASE, SEGUNDO CASO. Acá era aún menos defendible: no se intentó ni levantar la
    // pieza —falta la credencial— y aun así se afirmaba `disponibles: 0`, se listaba cada
    // tool como no-disponible y se declaraba `nombres_tools_comprobados: true`.
    // Sin credencial no hay medición: lo único cierto es lo que el catálogo DECLARA.
    // Y el `detail` decía «servidores», que es vocabulario nuestro, no del usuario.
    return {
      tipo: "connector", ref: entry.service || entry.id,
      estado: "no_configurado", causa: "falta_key", ts: Math.floor(Date.now() / 1000),
      evidencia: {
        detail: `falta tu llave de ${entry.credential.provider}`,
        disponibles: null, total, credential_provider: entry.credential.provider,
        tools_disponibles: [],
        tools_no_disponibles: [],
        tools_declaradas: noDisponibles,
        nombres_tools_comprobados: false,
        sin_medir: true,
      },
    };
  }
  const rows = serverRows || [];
  const herramientas = rows.map((row) => ({
    row,
    medida: _toolsDeServidor(row.server, row.estado),
  }));
  // ⚠️ `cantidadDisponible: null` = NO SE MIDIÓ, y sumarlo con `+` lo convertiría en 0 —
  // que es exactamente el bug que la rama de arriba acaba de matar, reapareciendo en la
  // aritmética. Si ALGUNA fila no se midió, el total no se sabe: `available` queda `null`
  // y nadie puede escribir «0 de N».
  const algoSinMedir = herramientas.some((item) => item.medida.sinMedir);
  const available = algoSinMedir
    ? null
    : herramientas.reduce((n, item) => n + (item.medida.cantidadDisponible || 0), 0);
  const toolsAvailable = herramientas.flatMap((item) => item.medida.disponibles);
  const toolsUnavailable = herramientas.flatMap((item) => item.medida.noDisponibles);
  const toolsDeclaradas = herramientas.flatMap((item) => item.medida.declaradas || []);
  // Sin medición no hay nombres comprobados: `every` sobre una lista donde todos dicen
  // `false` ya da `false`, pero se deja explícito para que se lea la intención.
  const toolNamesMeasured = !algoSinMedir
    && herramientas.every((item) => item.medida.nombresComprobados);
  const states = rows.map((row) => row.estado && row.estado.estado);
  const allGreen = rows.length > 0 && states.every((state) => state === "probado")
    && available === total;
  const allRed = rows.length > 0 && states.every((state) => state === "roto");
  const allPremium = rows.length > 0 && states.every((state) => state === "premium");
  let estado = "detectado", causa = null;
  if (allGreen) estado = "probado";
  else if (allPremium) estado = "premium";
  else if (allRed) {
    estado = "roto";
    const first = rows.find((row) => row.estado && row.estado.causa);
    causa = first && first.estado.causa || "error_upstream";
  } else if ((available || 0) > 0 || states.some((state) => state === "roto")) {
    estado = "parcial";
    const first = rows.find((row) => row.estado && row.estado.causa);
    causa = first && first.estado.causa || null;
  }
  const broken = rows.filter((row) => row.estado && row.estado.estado === "roto");
  const evidencia = {
    disponibles: available, total,
    sin_medir: algoSinMedir,
    tools_disponibles: toolsAvailable,
    tools_no_disponibles: toolsUnavailable,
    tools_declaradas: toolsDeclaradas,
    nombres_tools_comprobados: toolNamesMeasured,
    // El `detail` es lo primero que se lee, así que no puede afirmar lo que no se midió.
    // Decía «servidores sin probar» —jerga— y, cuando `available` era el 0 inventado,
    // «0 de N tools disponibles», que era una medición falsa. Ahora: si no se midió, se
    // dice sin medir; si se midió, se dice el número real.
    detail: algoSinMedir
      ? "sin medir todavía"
      : estado === "parcial"
        ? `${available} de ${total} tools disponibles`
        : estado === "probado"
          ? `${total} de ${total} tools disponibles`
          : allRed
            ? ((broken[0].estado.evidencia || {}).detail || "ninguna respondió")
            : "sin medir todavía",
    servidores_rotos: broken.map((row) => row.server.name),
  };
  const representante = allRed
    ? broken.find((row) => row.estado && row.estado.veredicto)
    : null;
  const veredictoServidor = representante && representante.estado.veredicto;
  const veredicto = veredictoServidor ? {
    ...veredictoServidor,
    estado,
    causa,
    evidencia: {
      ...(veredictoServidor.evidencia || {}),
      ...evidencia,
    },
    presentacion: {
      ...(veredictoServidor.presentacion || {}),
      // El título conserva la causa precisa; el detalle conserva el crudo del servidor.
      detalle: (veredictoServidor.presentacion || {}).detalle
        || evidencia.detail,
    },
  } : null;
  return {
    tipo: "connector", ref: entry && (entry.service || entry.id), estado, causa,
    ts: Math.max(0, ...rows.map((row) => Number(row.estado && row.estado.ts || 0))),
    evidencia,
    ...(veredicto ? { veredicto } : {}),
  };
}

// ── "probado hace 2 min" — formateo honesto del ts (epoch segundos) ──────────────────
export function haceRato(ts) {
  if (!ts) return "";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - Number(ts)));
  if (s < 5) return "recién";
  if (s < 60) return `hace ${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `hace ${m} min`;
  const h = Math.floor(m / 60);
  if (h < 24) return `hace ${h} h`;
  return `hace ${Math.floor(h / 24)} d`;
}

// ── "18:57:12" — la HORA de pared del resultado (el timestamp que exige el desenlace) ─
export function horaDe(ts) {
  const d = new Date((Number(ts) || Math.floor(Date.now() / 1000)) * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

// ── MOTOR · lectura barata (GET /estado): no dispara pruebas caras ───────────────────
export async function leerEstado(tipo, ref, opts) {
  if (!TIPOS.has(tipo)) throw new Error(`semaforo: tipo inválido ${tipo}`);
  opts = opts || {};
  try {
    /* [FIX-P11 · §3] LA LECTURA TIENE QUE PREGUNTAR POR LO MISMO QUE SE PROBÓ.
     * El motor invalida un estado guardado cuando la HUELLA de la config cambia, y la
     * huella de un MCP se calcula con `belt_ref`/`backed_by`. `POST /probar` los manda;
     * este `GET /estado` no los mandaba. Resultado: se probaba con una huella y se leía
     * con otra → el estado guardado NUNCA se volvía a encontrar, y la pieza aparecía
     * «sin probar» un segundo después de haber salido verde. Es el mismo síntoma que §3
     * viene a matar, por una causa distinta: no amnesia, sino preguntar mal. */
    const qs = "?tipo=" + encodeURIComponent(tipo) + "&ref=" + encodeURIComponent(ref || "")
      + ["belt_ref", "backed_by", "cli_model"]
          .filter((k) => opts[k] != null && opts[k] !== "")
          .map((k) => "&" + k + "=" + encodeURIComponent(opts[k])).join("");
    const r = await fetch("/v1/motor/estado" + qs, { headers: _sessAuth({ "Accept": "application/json" }) });
    if (!r.ok) return _fallo(tipo, ref, r.status, await r.text().catch(() => ""));
    return await r.json();
  } catch (e) {
    // FALLO VISIBLE §0.1: la red murió → lo decimos, no lo escondemos.
    return { tipo, ref, estado: "roto", causa: "sin_red", evidencia: { detail: String(e && e.message || e) }, ts: Math.floor(Date.now() / 1000) };
  }
}

// ── MOTOR · prueba fresca (POST /probar): la acción explícita del humano ──────────────
export async function probar(tipo, ref, opts) {
  if (!TIPOS.has(tipo)) throw new Error(`semaforo: tipo inválido ${tipo}`);
  opts = opts || {};
  const body = { tipo, ref, force: opts.force !== false, motivo: opts.motivo || "manual" };
  for (const k of ["cli_model", "belt_ref", "backed_by", "spec"]) if (opts[k] != null) body[k] = opts[k];
  try {
    const r = await fetch("/v1/motor/probar", {
      method: "POST",
      headers: _sessAuth({ "Content-Type": "application/json", "Accept": "application/json" }),
      body: JSON.stringify(body),
    });
    if (!r.ok) return _fallo(tipo, ref, r.status, await r.text().catch(() => ""));
    return await r.json();
  } catch (e) {
    return { tipo, ref, estado: "roto", causa: "sin_red", evidencia: { detail: String(e && e.message || e) }, ts: Math.floor(Date.now() / 1000) };
  }
}

// HTTP no-2xx del propio motor → estado honesto (401 = sin sesión; resto = upstream).
// [P1A · §5] El status SOLO no alcanza: "Error del proveedor" a secas es el fallo mudo que
// estamos matando. El CUERPO de la respuesta viaja en la evidencia, así que el desenlace
// siempre tiene un error REAL que mostrar plegado — no un código seco.
function _fallo(tipo, ref, status, cuerpo) {
  const causa = status === 401 ? "sin_sesion" : "error_upstream";
  const ev = { http: status, endpoint: "/v1/motor/*" };
  if (cuerpo) {
    let d = String(cuerpo).slice(0, 1200);
    try {
      const j = JSON.parse(cuerpo);
      const cand = (j && j.detail && (j.detail.detail || j.detail)) || (j && j.error) || null;
      if (cand) d = typeof cand === "string" ? cand : JSON.stringify(cand);
    } catch (e) { /* no era JSON → el texto crudo ya sirve */ }
    ev.detail = d;
  }
  return { tipo, ref, estado: "roto", causa, evidencia: ev, ts: Math.floor(Date.now() / 1000) };
}

/* ══ P1A · probarPieza() — LA ÚNICA FUNCIÓN DE PRUEBA ══════════════════════════════════
 * El bug que esto cierra: [Reintentar] existía en tres lugares (el abanico de la pieza, el
 * panel «N piezas frenan la entrega» y el chip de LAS PIEZAS) y en los tres el click no
 * producía NADA perceptible. La causa exacta está en reports/step5/FIX-P1A-REINTENTAR.md;
 * el resumen es que la prueba SÍ salía, pero:
 *   · el latido no caía sobre el botón que la persona apretó (el abanico delegaba en OTRO
 *     botón y después repintaba el abanico entero, borrando el "Probando…" en vuelo);
 *   · el desenlace era un repintado al MISMO rojo con la MISMA etiqueta — indistinguible
 *     de «no pasó nada»; sin hora, sin evidencia, sin «lo reintenté y sigue igual»;
 *   · dos de las tres entradas nunca mutaban: se podía apretar tres veces y quedar igual.
 *
 * Esta función es el ÚNICO camino por el que se prueba una pieza. Garantiza las tres cosas
 * que la ley 4 (NADA ESPERA EN SILENCIO) exige, y las garantiza para toda superficie que
 * la llame — presente y futura (P1B · P3 · P7 la consumen):
 *   1. LATIDO desde el instante del click, SOBRE EL BOTÓN QUE SE APRETÓ.
 *   2. PRUEBA REAL contra el Motor de Verdad (POST /v1/motor/probar). Jamás estado declarado.
 *   3. DESENLACE SIEMPRE: verde con evidencia + hora, o rojo con la causa legible y el
 *      error CRUDO plegado debajo. Nunca «Error del proveedor» como texto terminal.
 * Y la cuarta, que es la regla sellada en la ola 1 de R: un botón que te deja igual dos
 * veces está prohibido → el reintento SE GASTA y el botón MUTA a destinos reales.
 *
 * CONTEO DE FALLOS (por qué muta al primer reintento): el rojo que la pieza YA tenía es el
 * fallo nº1 — es lo que hizo aparecer el [Reintentar]. El reintento que vuelve rojo es el
 * nº2. Ahí muta. Así nadie aprieta dos veces el mismo botón para nada, y es exactamente el
 * contrato que ya medía `conexiones/verify_cuarto_puente.mjs §D`.
 */
export const REINTENTOS_ANTES_DE_MUTAR = 1;
// Piso del latido. El motor puede contestar en 3 ms (un MCP local que no arranca falla al
// instante): con 3 ms el "Probando…" es invisible y el click se lee como muerto. 420 ms es
// lo mínimo que el ojo registra como «pasó algo». No es trabajo falso: es el cambio de
// estado hecho legible. Las varas lo bajan a 0 con window.__semLatidoInstante = true.
const MIN_LATIDO_MS = 420;
const _INTENTOS = new Map();                 // "tipo:ref" → pruebas que terminaron NO-verde
const _clave = (coord) => (coord ? `${coord.tipo || "?"}:${coord.ref || ""}` : "?:");

export function intentosDe(coord) { return _INTENTOS.get(_clave(coord)) || 0; }
export function olvidarIntentos(coord) { _INTENTOS.delete(_clave(coord)); }
export function reiniciarIntentos() { _INTENTOS.clear(); }

/** El error REAL, siempre una string legible. Es lo que va DEBAJO de la causa canónica,
 *  plegado: la causa dice qué clase de falla es, esto dice qué respondió la máquina. */
export function crudoDe(res) {
  const e = (res && res.evidencia) || {};
  const partes = [];
  if (e.detail) partes.push(String(e.detail));
  if (e.falta && e.falta !== e.detail) partes.push(String(e.falta));
  if (e.http) partes.push(`HTTP ${e.http} de ${e.endpoint || "el motor"}`);
  const resto = {};
  for (const k of Object.keys(e)) if (!["detail", "falta", "http", "endpoint"].includes(k)) resto[k] = e[k];
  if (Object.keys(resto).length) partes.push(JSON.stringify(resto, null, 2));
  if (!partes.length)
    partes.push("El motor corrió la prueba y volvió sin evidencia. Eso también es un dato: no hay mensaje del proveedor que mostrar.");
  return partes.join("\n");
}

/** El texto del desenlace: {emoji, titulo, sub}. Verde → evidencia + hora. Rojo → la causa
 *  legible, y si CAMBIÓ respecto del intento anterior se dice cuál era y cuál es ahora. */
export function textoDesenlace(res, o) {
  o = o || {};
  const meta = ESTADOS[res && res.estado] || ESTADOS.detectado;
  const ev = (res && res.evidencia) || {};
  if (res && res.estado === "probado") {
    const det = [];
    if (ev.latencia_ms != null) det.push(ev.latencia_ms + " ms");
    if (ev.model_final) det.push(String(ev.model_final));
    if (ev.tools != null) det.push(ev.tools + " tools");
    if (ev.snippet) det.push('"' + String(ev.snippet).slice(0, 40) + '"');
    return { emoji: meta.emoji, titulo: "Probado",
             sub: horaDe(res.ts) + (det.length ? " · " + det.join(" · ") : "") };
  }
  /* ══ [FIX-P11 · §3] UN ESTADO, UNA VERDAD ═══════════════════════════════════════════
   * Lo que se leyó en el panel durante la caminata del 27:
   *       «Sin probar · probado a mano · 13:41:34»
   * Una pieza no puede estar sin probar y probada a la vez. Las dos mitades venían de
   * lugares distintos y ninguna estaba mal por su cuenta:
   *   · el TÍTULO salía de `ESTADOS.detectado.es` = "Sin probar" — correcto como etiqueta
   *     de semáforo en frío (🟡 = nadie lo probó todavía);
   *   · el SUB decía "probado a mano" porque efectivamente ACABABA de correr una prueba.
   * El agujero es que `detectado` significa DOS cosas y sólo tenía un nombre: «nunca se
   * probó» y «se probó y no pude confirmarlo» (el caso del validador ausente — §1). La
   * segunda no es "sin probar": es "probado, sin confirmar". Se separan acá, con el dato
   * que el motor ya manda (`evidencia.nunca_probado` / la existencia de una prueba real). */
  const nuncaProbado = !!ev.nunca_probado;
  const corrio = !nuncaProbado && (o.reintento || !!res.probado_ts || !!ev.motivo);
  let causa = (CAUSAS[res && res.causa] || {}).es ||
              (res && res.estado === "roto" ? "Roto" : meta.es);
  if (res && res.estado === "detectado" && corrio) causa = "Probado, sin confirmar";
  const prev = o.previo || null;
  const cambio = prev && prev.causa && res && res.causa && prev.causa !== res.causa
    ? `cambió la causa: antes «${(CAUSAS[prev.causa] || {}).es || prev.causa}», ahora «${causa}»`
    : null;
  // …y el SUB deja de afirmar una prueba que no hubo: sin prueba corrida no se dice
  // "probado a mano", se dice qué falta.
  const veces = nuncaProbado ? "sin probar todavía"
    : !o.reintento ? (corrio ? "probado a mano" : "última lectura")
    : ((o.intentos || 0) >= 2 ? `lo reintenté ${o.intentos} veces y sigue igual` : "lo reintenté y sigue igual");
  return { emoji: meta.emoji, titulo: causa,
           sub: (cambio ? cambio + " · " : "") + veces + " · " + horaDe(res && res.ts) };
}

// El latido SOBRE EL BOTÓN QUE SE APRETÓ. Devuelve el restaurador.
function _latido(btn) {
  if (!btn) return () => {};
  const t = btn.querySelector(".ab-t") || btn;      // el abanico pinta su texto en un span
  const txt0 = t.textContent, dis0 = btn.disabled;
  btn.disabled = true;
  btn.dataset.probando = "1";
  btn.setAttribute("aria-busy", "true");
  t.textContent = "Probando…";
  return () => {
    try {
      delete btn.dataset.probando;
      btn.removeAttribute("aria-busy");
      btn.disabled = dis0;
      if (t.textContent === "Probando…") t.textContent = txt0;
    } catch (e) { /* el botón ya no está en el DOM (la superficie repintó): nada que restaurar */ }
  };
}

function _esLocalRes(res, opts) {
  return !!(((opts || {}).ctx || {}).local) || !!(((res || {}).evidencia) || {}).local;
}

/** probarPieza(spec) → {res, verde, intentos, gastado, texto, crudo, coord}
 *
 *  spec = {
 *    coord      : {tipo, ref, opts?, ctx?, local?}  — la coordenada del Motor de Verdad
 *    probar     : () => Promise<res>   (opcional) prueba propia de la superficie; si no
 *                 viene, se usa probar(coord.tipo, coord.ref, coord.opts) — el motor real
 *    boton      : HTMLElement   el botón que la persona apretó (recibe el latido)
 *    previo     : res           el estado que se veía ANTES (para «cambió la causa»)
 *    host       : HTMLElement   dónde pintar el desenlace (opcional; si no, sólo se devuelve)
 *    ctx        : {}            contexto que viaja al despacho (pieceId, conector, local…)
 *    onDesenlace: (out) => void callback con el resultado (SIEMPRE se llama)
 *    onQuitar   : () => void    la superficie sabe cómo sacar la pieza (habilita [Quitar])
 *  }
 *  NUNCA lanza y NUNCA vuelve en silencio: sin coordenada válida devuelve un rojo honesto. */
export async function probarPieza(spec) {
  spec = spec || {};
  const coord = spec.coord || null;
  const t0 = Date.now();
  const restaurar = _latido(spec.boton);
  if (typeof spec.onLatido === "function") { try { spec.onLatido(); } catch (e) {} }

  let res = null;
  try {
    if (typeof spec.probar === "function") {
      res = await spec.probar();
    } else if (coord && TIPOS.has(coord.tipo) && coord.ref) {
      res = await probar(coord.tipo, coord.ref, Object.assign({ motivo: spec.motivo || "reintento" }, coord.opts));
    }
  } catch (e) {
    res = { tipo: (coord || {}).tipo || "mcp", ref: (coord || {}).ref || "", estado: "roto",
            causa: "error_upstream", evidencia: { detail: String((e && e.message) || e) },
            ts: Math.floor(Date.now() / 1000) };
  }
  // PINTADO ≠ CABLEADO: un botón cuya prueba no existe (o devuelve nada) tenía que decirlo.
  // Antes ése era EL fallo mudo: click y silencio. Ahora es un rojo con su causa.
  if (!res) {
    res = { tipo: (coord || {}).tipo || "mcp", ref: (coord || {}).ref || "", estado: "roto",
            causa: "error_upstream", ts: Math.floor(Date.now() / 1000),
            // LEY · las dos decían lo mismo de dos formas prohibidas: la primera confesaba
            // un bug nuestro, la segunda lo explicaba con vocabulario nuestro. El detalle
            // técnico se conserva en `interno`, que es lo que lee el [?] y el reporte.
            evidencia: { detail: "No disponible por ahora.",
                         interno: coord
                           ? "el botón no tenía prueba cableada (bug del Cuarto)"
                           : "la pieza no declara servidor MCP, cuenta ni cerebro" } };
  }
  res = normalizarLocal(res, !!(coord && coord.local));

  const verde = res.estado === "probado";
  const k = _clave(coord);
  const intentos = verde ? 0 : (_INTENTOS.get(k) || 0) + 1;
  if (verde) _INTENTOS.delete(k); else _INTENTOS.set(k, intentos);

  const piso = (typeof window !== "undefined" && window.__semLatidoInstante) ? 0 : MIN_LATIDO_MS;
  const falta = piso - (Date.now() - t0);
  if (falta > 0) await new Promise((r) => setTimeout(r, falta));
  restaurar();

  const prev = spec.previo || null;
  const reintento = !!(prev && prev.estado && prev.estado !== "probado");
  const out = { res, verde, intentos, coord,
                gastado: !verde && intentos >= REINTENTOS_ANTES_DE_MUTAR,
                texto: textoDesenlace(res, { previo: prev, intentos, reintento }),
                crudo: crudoDe(res) };
  if (spec.host) pintarDesenlace(spec.host, out, spec);
  if (typeof spec.onDesenlace === "function") { try { spec.onDesenlace(out); } catch (e) {} }
  return out;
}

/** «Probar el server a mano»: el pedido EXACTO que corrió el motor, copiable. No inventa el
 *  comando del server MCP —el cliente no lo tiene, y no hay endpoint que lo entregue (queda
 *  declarado en el informe)— pero sí entrega la misma puerta por la que pasó la prueba. */
export function manoDe(res, ctx) {
  ctx = ctx || {};
  const tipo = (res && res.tipo) || "mcp";
  const ref = String((res && res.ref) || "").split("#")[0];
  const cuerpo = { tipo, ref, force: true };
  if (ctx.belt_ref) cuerpo.belt_ref = ctx.belt_ref;
  if (ctx.backed_by) cuerpo.backed_by = ctx.backed_by;
  const ev = (res && res.evidencia) || {};
  const org = (typeof location !== "undefined" ? location.origin : "");
  const L = [];
  L.push("la prueba que corrí:");
  L.push(`  POST ${org}/v1/motor/probar`);
  L.push("  " + JSON.stringify(cuerpo));
  if (ev.transport) L.push("  transporte: " + ev.transport);
  if (ctx.runtime_detail) L.push("", "no encontrado en tu máquina:", "  " + String(ctx.runtime_detail));
  L.push("", "córrelo tú:");
  L.push(`  curl -s -X POST ${org}/v1/motor/probar \\`);
  L.push("    -H 'content-type: application/json' \\");
  L.push("    -H \"authorization: Bearer $TOKEN\" \\");
  L.push("    -d '" + JSON.stringify(cuerpo) + "'");
  L.push("", "el comando del server vive en su belt (ábrelo abajo); el cliente no lo recibe.");
  return L.join("\n");
}

// [Abrir el belt] — real: POST /v1/dev/abrir. Sólo en la app de escritorio; si el backend
// dice 409/no_local, se DICE. Jamás un botón que no hace nada.
async function _abrirBelt(btn, ctx) {
  const server = String(ctx.backed_by || ctx.conector || "").trim();
  const belt_ref = ctx.belt_ref || null;
  if (!server && !belt_ref) { btn.textContent = "no sé qué archivo abrir"; btn.disabled = true; return; }
  const t0 = btn.textContent;
  btn.disabled = true; btn.textContent = "abriendo…";
  try {
    const r = await fetch("/v1/dev/abrir", { method: "POST",
      headers: _sessAuth({ "Content-Type": "application/json", "Accept": "application/json" }),
      body: JSON.stringify({ ref: server, belt_ref }) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      const d = (j && j.detail && (j.detail.detail || j.detail)) || `HTTP ${r.status}`;
      btn.textContent = "no se pudo: " + String(d).slice(0, 90);
      return;
    }
    btn.textContent = j.via === "vscode" ? "abierto en VS Code" : "revelado en el Finder";
    btn.disabled = false; setTimeout(() => { btn.textContent = t0; }, 4000);
  } catch (e) {
    btn.textContent = "no se pudo: " + String((e && e.message) || e).slice(0, 90);
  }
}

/** El DESENLACE, pintado. Una sola implementación para las tres entradas (y para las que
 *  vengan): la línea de estado, el error crudo PLEGADO y —si el reintento ya se gastó— las
 *  salidas reales. `host` se reemplaza entero, así que repintar es idempotente. */
export function pintarDesenlace(host, out, opts) {
  if (!host) return null;
  opts = opts || {};
  // [FIX-P11 · §5] `coord.opts` (belt_ref/backed_by) entra al ctx que viaja al wizard. Es la
  // red por si alguna superficie arma su coordenada sin duplicarlos en `ctx` — sin ellos el
  // workflow de programa no puede pedir la receta y se queda sin el paso [Instalarlo].
  const ctx = Object.assign({}, (opts.coord || {}).opts, (opts.coord || {}).ctx, opts.ctx);
  const local = _esLocalRes(out.res, { ctx });
  host.className = String(host.className || "").split(/\s+/).filter((c) => c && c !== "sem-out").concat(["sem-out"]).join(" ");
  host.setAttribute("data-estado", (out.res && out.res.estado) || "roto");
  host.setAttribute("role", "status");
  host.setAttribute("aria-live", "polite");

  /* ══ [FIX-P3 · §5] BUG #34 — EL POPUP DE MUTACIÓN SALÍA DUPLICADO ═══════════════════
   * Reproducido (qa/p3_bug34.mjs): con el reintento gastado sobre una pieza local, ESTE
   * MISMO popup imprimía cada salida DOS VECES, en dos idiomas distintos y apilados:
   *
   *   <details class="sem-out-crudo"><summary>Ver el error completo</summary>   ← 1ª vez
   *   <details class="sem-out-mano"><summary>Probar el server a mano</summary>  ← 1ª vez
   *   <div class="sem-salidas">
   *     <button>Ver el error completo</button>      ← 2ª vez
   *     <button>Probar el server a mano</button>    ← 2ª vez
   *     <button>Quitar</button>
   *
   * LA CAUSA no es un repintado ni dos hosts: es que el cuerpo se armaba de DOS fuentes
   * que se solapaban y ninguna sabía de la otra. Los `<details>` YA SON la salida — son
   * el lugar donde vive el texto. Los botones `ver`/`mano` no llevaban a ningún lado
   * nuevo: su handler hacía `detalle.open = true` sobre el pliegue de arriba. Un botón
   * cuyo único efecto es abrir lo que ya está impreso al lado no es un segundo camino:
   * es el mismo camino escrito dos veces.
   *
   * El guard de duplicados que ya existía (`opts.omitir`) NO podía verlo: sólo sacaba lo
   * que ofrecía el botón MUTADO de la superficie (wizard/centro), nunca miró lo que este
   * mismo innerHTML acababa de imprimir.
   *
   * LA CURA, en dos capas:
   *   1. las salidas quedan sólo con lo que LLEVA a otra parte (el workflow) o HACE algo
   *      (quitar la pieza). Ver el error y probar a mano SON los pliegues.
   *   2. y un filtro final que tacha cualquier salida cuya etiqueta ya esté impresa como
   *      `<summary>` en este popup — para que sumar una salida nueva no reabra el #34. */
  /* [FIX-P11 · §8·1] BAJO UN VERDE NO HUBO ERROR — el mismo pliegue guarda evidencia
   * cuando anduvo y error cuando falló; su rótulo tiene que decir cuál de las dos contiene. */
  const _verde = (out.res && out.res.estado) === "probado";
  const _rotuloCrudo = _verde ? "Ver el detalle"
    : ((out.res && out.res.estado) === "detectado" ? "Ver el detalle" : "Ver el error completo");
  const pliegues = [{ cls: "sem-out-crudo", label: _rotuloCrudo }];
  if (out.gastado) pliegues.push({ cls: "sem-out-mano", label: "Probar el server a mano" });

  let salidas = [];
  // `sinSalidas` = la superficie ya ofrece las salidas en SU lista (el arco las pone como
  // acciones): pintarlas dos veces sería el mismo botón repetido a 40px de distancia.
  if (out.gastado && !opts.sinSalidas) {
    // Una conexión/cuenta que sigue rota tiene una fila en el Centro con sus requisitos;
    // una pieza LOCAL no tiene «conexión que configurar» — tiene un error que mostrar y un
    // server que probar a mano. ([reforma · c] · ola1 vara: local NUNCA al Centro.)
    // [FIX-P1B · §1] «Configurar» ya no NAVEGA a un catálogo: abre EL WORKFLOW de esta
    // pieza, acá mismo. Una pieza local tampoco queda sin workflow — el suyo es el de
    // programa (qué falló → dependencia → instalar → probar), que es el que le sirve.
    salidas.push({ id: "wizard", label: local ? "Arreglarlo" : "Configurar" });
    if (typeof opts.onQuitar === "function") salidas.push({ id: "quitar", label: "Quitar" });
    // …y nunca el MISMO destino que ya ofrece el botón mutado de la superficie: dos botones
    // idénticos a 20px uno del otro no son dos caminos, son un camino escrito dos veces.
    // [FIX-P3 · §5] `omitir` acepta ids Y ETIQUETAS. Era la otra mitad del #34: la fila del
    // preflight mutaba a «Configurar» (accion `centro`) y pedía `omitir:["centro"]`, pero la
    // salida duplicada era `wizard`, que se LLAMA igual. Un guard por id no puede ver dos
    // acciones distintas con el mismo rótulo; uno por rótulo sí — y el rótulo es lo que la
    // persona lee. Se filtra por las dos cosas.
    const fuera = new Set((opts.omitir || []).map((x) => String(x).toLowerCase()));
    const yaImpreso = new Set(pliegues.map((p) => p.label.toLowerCase()));
    salidas = salidas.filter((s) => !fuera.has(String(s.id).toLowerCase()) &&
                                    !fuera.has(String(s.label).toLowerCase()) &&
                                    !yaImpreso.has(String(s.label).toLowerCase()));
  }

  /* [FIX-P3 · §6 · UNA INFORMACIÓN, UN DUEÑO] dos recortes, y los dos son de PROPIEDAD:
   *   `soloCrudo` — la superficie YA dice el estado en su propia línea (el pie del arco).
   *      Repetir «🔴 Roto» 20px más abajo no informa: confirma. Queda sólo el pliegue del
   *      error, que es lo que la línea de estado NO puede decir.
   *   `sinCrudo`  — esta superficie NO es la dueña del error (el preflight, el registro).
   *      El error crudo vive en UN lugar —el popup de la pieza— y acá se ofrece el CAMINO
   *      hasta él, no una segunda copia del texto. Es lo que hace medible la unicidad. */
  /* `sinTitulo` — la superficie ya dice el ESTADO en su propia línea (el pie del arco dice
   * «🔴 Roto · Falta tu llave»), así que repetir la causa como título del desenlace 20px más
   * abajo es la misma frase dos veces. Se conserva el SUB, que es lo único que el pie no
   * puede decir: qué pasó cuando apretaste («lo reintenté y sigue igual · 15:45:52»). */
  const linea =
    `<div class="sem-out-linea"><span class="sem-out-luz" aria-hidden="true">${out.texto.emoji}</span>` +
    `<span class="sem-out-txt">` +
    (opts.sinTitulo ? "" : `<span class="sem-out-tit">${_esc(out.texto.titulo)}</span>`) +
    `<span class="sem-out-sub">${_esc(out.texto.sub)}</span></span></div>`;
  const crudo =
    // [§5] el error REAL, siempre, plegado. "Error del proveedor" dejó de ser texto terminal.
    `<details class="sem-out-crudo"><summary>${_esc(_rotuloCrudo)}</summary><pre>${_esc(out.crudo)}</pre></details>`;
  if (opts.soloCrudo) { host.innerHTML = crudo; return _cablearDesenlace(host, out, opts, ctx); }
  host.innerHTML =
    linea +
    (opts.sinCrudo
      ? `<button type="button" class="sem-salida sem-verror" data-salida="ir_error">Ver error →</button>`
      : crudo) +
    (out.gastado && !opts.sinCrudo
      ? `<details class="sem-out-mano"><summary>Probar el server a mano</summary><pre>${_esc(manoDe(out.res, ctx))}</pre>` +
        (ctx.belt_ref || ctx.backed_by ? `<button type="button" class="sem-out-abrir">Abrir el belt</button>` : "") +
        `</details>`
      : "") +
    (salidas.length
      ? `<div class="sem-salidas">` + salidas.map((s) =>
          `<button type="button" class="sem-salida" data-salida="${s.id}">${_esc(s.label)}</button>`).join("") + `</div>`
      : "");
  return _cablearDesenlace(host, out, opts, ctx);
}

/** El cableado de lo que `pintarDesenlace` acaba de escribir. Aparte para que el modo
 *  `soloCrudo` (que escribe menos) comparta exactamente los mismos handlers. */
function _cablearDesenlace(host, out, opts, ctx) {
  const crudo = host.querySelector(".sem-out-crudo");
  const mano = host.querySelector(".sem-out-mano");
  const abrir = host.querySelector(".sem-out-abrir");
  if (abrir) abrir.addEventListener("click", (e) => { e.stopPropagation(); _abrirBelt(abrir, ctx); });
  host.querySelectorAll(".sem-salida").forEach((b) => b.addEventListener("click", (e) => {
    e.stopPropagation();
    const id = b.dataset.salida;
    if (id === "ver") { if (crudo) { crudo.open = true; crudo.scrollIntoView({ block: "nearest" }); } return; }
    if (id === "mano") { if (mano) { mano.open = true; mano.scrollIntoView({ block: "nearest" }); } return; }
    if (id === "quitar") { if (typeof opts.onQuitar === "function") opts.onQuitar(); return; }
    if (id === "wizard") { despachar("wizard", out.res, Object.assign({}, ctx, { el: b })); return; }
    // [FIX-P3 · §6] esta superficie no es dueña del error: lleva a quien sí lo es.
    if (id === "ir_error") { if (typeof opts.onVerError === "function") opts.onVerError(); return; }
  }));
  return host;
}

/** Dónde pintar un desenlace cuando el botón no trajo `host`: un `.sem-out` hermano del
 *  badge, creado una vez y reusado. Así [Ver error] deja de necesitar un window.alert(). */
function _hostCrudo(el) {
  if (!el || !el.parentElement) return null;
  const ancla = el.closest(".sem-badge") || el;
  const padre = ancla.parentElement; if (!padre) return null;
  let h = padre.querySelector(":scope > .sem-out");
  if (!h) { h = document.createElement("div"); ancla.insertAdjacentElement("afterend", h); }
  return h;
}

// ── El BOTÓN de §3: dado un resultado no-verde, QUÉ ofrecer y a DÓNDE lleva ───────────
// Devuelve null cuando no hay acción (probado sin re-probar explícito lo maneja la superficie).
// botonDe = EL BOTÓN PRIMARIO de caminoDe(). Se conserva como nombre porque lo llaman las
// 6 superficies (y las varas); la tabla ya no vive acá — vive en CAMINOS, una sola vez.
export function botonDe(res) {
  return caminoDe(res);   // null en 🟢 probado → sin botón forzado
}

// ── EL CENTRO DE CONEXIONES · a dónde manda un no-verde que necesita trabajo profundo ──
// El slug es el del Centro (familia.ref). Tolerante a propósito: el backend resuelve
// «groq», «claude_cli» o «belt#servidor» aunque falte el prefijo de familia.
export function slugDeCentro(res, ctx) {
  ctx = ctx || {};
  const tipo = res && res.tipo, ref = (res && res.ref) || "";
  if (tipo === "cli") return "cli." + ref;
  if (tipo === "key") return String(ctx.conector || ref || "");
  if (tipo === "mcp") return "mcp." + (ctx.backed_by ? ref + "#" + ctx.backed_by : ref);
  return "";   // cerebro: no es una fila del Centro → se abre el Centro sin fila
}

// ─────────────────────────────────────────────────────────────────────────────────────
// A DÓNDE MANDA UN SLUG — la ÚNICA tabla, porque el Centro de Conexiones murió y sus
// familias se repartieron por lo que SON:
//     cognición (incluido · cli · api · el cerebro sin fila) → Modelos.dc.html
//     conectores (mcp · las keys de un servicio)             → Conectar.dc.html
// Conexiones.dc.html redirige, pero eso es la RED DE SEGURIDAD para los links que ya
// están sueltos por ahí — no puede ser el motivo por el que la app funciona. Acá se
// construye el destino final, con los parámetros NATIVOS de cada pantalla.
export function destinoDeSlug(slug) {
  const s = String(slug || "");
  if (!s) return { pantalla: "Modelos.dc.html", q: {} };            // el cerebro, sin fila
  // `mcp.belts/x.mcp.json#zotero` → el conector es lo de después del `#`, o el último
  // tramo del path. Conectar.dc.html ya abre su wizard con `?c=<conector>`: ESE es el
  // deep-link por fila del lado de los conectores, y se conserva.
  if (s.startsWith("mcp.")) {
    const r = s.slice(4);
    const ref = r.includes("#") ? r.split("#").pop() : r.split("/").pop().replace(/\.mcp\.json$/, "");
    return { pantalla: "Conectar.dc.html", q: ref ? { c: ref } : {} };
  }
  if (s.startsWith("cli.")) return { pantalla: "Modelos.dc.html", q: { modo: "cli", m: s.slice(4) } };
  if (s.startsWith("api.")) return { pantalla: "Modelos.dc.html", q: { modo: "api", m: s.slice(4) } };
  // una key suelta («groq», «stripe»…): si es un proveedor de cognición conocido va a
  // Modelos; si no, es de un servicio y vive en Conectores.
  return COGNICION.has(s.toLowerCase())
    ? { pantalla: "Modelos.dc.html", q: { modo: "api", m: s } }
    : { pantalla: "Conectar.dc.html", q: { c: s } };
}
const COGNICION = new Set(["groq", "openai", "anthropic", "openrouter", "deepseek", "mistral",
  "together", "gemini", "huggingface", "ollama", "claude_code", "codex",
  "claude_cli", "codex_cli", "incluido"]); /* E1-FALLBACK ids CLI; catalog los suma */
if (typeof window !== "undefined" && window.AlephBrain && window.AlephBrain.cliOrder) {
  window.AlephBrain.cliOrder().forEach((id) => COGNICION.add(id));
}

/** La URL a la que manda un resultado del semáforo. `sub` porque el Cuarto/Sala/Método
 *  viven un nivel abajo de design/. */
export function urlDelCentro(res, ctx) {
  const sub = /\/(cuarto|sala|metodo)\//.test(location.pathname) ? "../" : "";
  const d = destinoDeSlug(slugDeCentro(res, ctx));
  const q = new URLSearchParams(d.q);
  q.set("return", location.pathname + location.search);
  return sub + d.pantalla + "?" + q.toString();
}

// ── DESPACHO del workflow (§3). Global: login/premium/reintentar/centro. Superficie:
//    credencial/instalar/configurar → CustomEvent que la superficie escucha con su contexto. ──
/* ══ [FIX-P1B · §1 §2] EL WORKFLOW ÚNICO POR TIPO ══════════════════════════════════════
 * El bug de la caminata: apretabas [Configurar] y te sacaba del Cuarto a una pantalla de
 * catálogo — o peor, te dejaba un [Reintentar] que reintentaba al vacío. El estándar bueno
 * ya existía dentro de la pantalla de conectores; el Cuarto no sabía abrirlo.
 *
 * Ahora toda reparación pasa por acá y ABRE EL WORKFLOW DE SU TIPO, anclado, sin sacar a
 * nadie del Cuarto (regla de R: sólo se sale si el trámite necesita navegador). El wizard
 * se carga a demanda: no cuesta nada hasta que algo se rompe.
 *
 * FALLBACK HONESTO: si el wizard no carga (bundle raro, red de assets), NO se traga el
 * click — se cae al camino viejo (el evento que escuchan las superficies), que sigue
 * llevando a alguna parte real. Un botón mudo sería peor que un botón que navega.
 *
 * ⚠️ [ADAPTADOR 2026-08-04] LO QUE SE CARGA ACÁ CAMBIÓ, Y ES EL PUNTO DE TODA LA TANDA.
 *
 * Antes era `diagnostico/wizard.js`: 2873 líneas con su propia idea de qué tipo de trámite
 * hacía falta (`cuenta_web` · `llave` · `suscripcion` · `programa`), sus propios textos y su
 * propio criterio de estado. O sea: **la misma pieza se veía y se arreglaba distinto según
 * desde dónde la miraras** — el Cuarto abría el wizard, Conectores abría un modal, y las
 * dos cosas decidían por su cuenta.
 *
 * Ahora carga el ADAPTADOR. El panel que se abre acá es exactamente el que se abre en la
 * lista de Conectores: los mismos pasos derivados de la misma ficha y el mismo belt, con la
 * misma tabla de conocimiento juzgando. No hay nada que sincronizar entre las dos
 * superficies porque no son dos.
 *
 * Lo que NO cambió es lo único que el wizard hacía bien y que había que conservar: el panel
 * se ancla al botón y no saca a nadie del Cuarto.                                        */
let _wizardMod = null, _wizardCarga = null;
function _wizard() {
  if (_wizardMod) return Promise.resolve(_wizardMod);
  if (!_wizardCarga) {
    _wizardCarga = import("../conectores/montaje.js")
      .then((m) => { _wizardMod = m.default || m; return _wizardMod; })
      .catch(() => null);
  }
  return _wizardCarga;
}

//: Las acciones que SON una reparación (§1: «TODA reparación lleva al workflow de su tipo»).
//: `centro` NO está acá a propósito: es la navegación explícita a una pantalla, y sigue
//: siendo eso para quien la pida por su nombre. Lo que cambió es que las REPARACIONES del
//: Cuarto ya no la piden — piden `wizard`, que es su workflow anclado.
const _REPARACIONES = new Set(["credencial", "configurar", "instalar", "reporte", "wizard"]);

/** Abre el workflow del tipo que corresponda. Devuelve true si lo abrió. */
export async function abrirWorkflow(res, ctx) {
  const W = await _wizard();
  if (!W || typeof W.abrirAnclado !== "function") return false;
  try {
    ctx = ctx || {};
    // QUÉ PIEZA ES. El adaptador trabaja con `entity_id` —la clave del registro, la misma
    // que usan el vault, el belt y la ficha— así que acá se resuelve una vez y bien. El
    // orden va de lo más específico a lo más general: `backed_by` es el server concreto que
    // el Cuarto estaba probando; `ref` es la coordenada; `conector` el nombre del servicio.
    //
    // ⚠️ Y NO SE INVENTA NINGUNO. Si ninguna de las tres está, se devuelve `false` y el
    // caller cae a su camino viejo. Abrir el panel de una pieza equivocada sería peor que
    // no abrirlo: el usuario pegaría su llave en el trámite de otra cosa.
    const entityId = ctx.backed_by || (ctx.opts && ctx.opts.backed_by) ||
                     ctx.conector || ctx.connector || (res && res.ref) || null;
    if (!entityId) return false;
    return await W.abrirAnclado({ entityId: String(entityId), ancla: ctx.el || null });
  } catch (e) { return false; }
}

export function despachar(accion, res, ctx) {
  ctx = ctx || {};
  // ── §1 · TODA reparación → SU workflow. Antes de cualquier navegación. ──────────────
  if (_REPARACIONES.has(accion) && !ctx.__sinWizard) {
    const p = abrirWorkflow(res, Object.assign({ accion }, ctx));
    // Se responde en el acto (los callers son síncronos) pero se cubre el caso de que el
    // wizard no cargue: recién ahí se usa el camino viejo, nunca antes.
    p.then((abierto) => { if (!abierto) despachar(accion, res, Object.assign({}, ctx, { __sinWizard: true })); });
    return { workflow: true, accion };
  }
  switch (accion) {
    case "centro":
      location.href = urlDelCentro(res, ctx);
      return { navegado: true };
    case "probar":
    case "reintentar":
      return { local: true }; // la superficie re-llama probar() y repinta (tiene el ref/opts).
    case "login": {
      const next = encodeURIComponent(location.pathname + location.search);
      // ⚠️ ACÁ DECÍA `/login.html`, Y ESA PÁGINA NO EXISTE. Es la única referencia a ese
      // archivo en todo el árbol, y el archivo nunca estuvo: viene así desde `f3c3fbd`
      // (2026-07-23). MEDIDO el 2026-08-07 contra la app instalada:
      //
      //     GET /login.html?next=%2FModelos.dc.html  →  404  ·  {"detail":"Not Found"}
      //
      // O sea: cualquier causa `sin_sesion` ofrece [Iniciar sesión], y ese botón sacaba a la
      // persona de la aplicación a una pantalla muerta —JSON crudo, sin nav, sin vuelta—.
      // La sesión vencida es el caso COMÚN: una app abierta hace horas y un 401 en el
      // primer POST que necesita credencial.
      //
      // El destino real es `Auth.dc.html`, que es a donde ya iban las OTRAS cuatro rutas de
      // login del producto (`sala.html:1342`, `cuarto.pixi.html:2084`, `metodo.html:392`,
      // `nav.js:312`). Absoluto y no relativo a propósito: este módulo lo importan tanto
      // páginas de la raíz (Modelos) como de subcarpeta (la Sala, el taller).
      // Barrido del 2026-08-07: de los 9 destinos de navegación del producto, éste era el
      // ÚNICO que no resolvía.
      location.href = "/Auth.dc.html?next=" + next;
      return { navegado: true };
    }
    case "premium": {
      if (typeof window.alephMostrarPaywall === "function") {
        window.alephMostrarPaywall({ tier_gated: true, feature: ctx.feature || (res && res.ref) || "esta acción" });
      } else {
        location.href = "/#premium";
      }
      return { premium: true };
    }
    case "ver_error": {
      // [Ver error] es REAL: destapa la evidencia cruda que el motor ya devolvió. Si la
      // superficie no monta panel propio, se pinta EN EL LUGAR (plegado, junto al botón) —
      // nunca un no-op, y nunca más un window.alert(): un modal nativo no es legible, en la
      // .app puede no aparecer, y no deja el texto ahí para leerlo dos veces. [P1A · §5]
      const ev = new CustomEvent("cuarto:semaforo-accion", { detail: { accion: "ver_error", res, ctx }, cancelable: true, bubbles: true });
      const t = ctx.el && ctx.el.dispatchEvent ? ctx.el : window;
      if (!t.dispatchEvent(ev)) return { emitido: true, sinManejador: false };
      const anfitrion = _hostCrudo(ctx.el);
      if (anfitrion) {
        pintarDesenlace(anfitrion, { res, verde: false, intentos: intentosDe({ tipo: res && res.tipo, ref: res && res.ref }),
                                     gastado: false, texto: textoDesenlace(res, { reintento: true }), crudo: crudoDe(res) },
                        { ctx });
        const d = anfitrion.querySelector(".sem-out-crudo"); if (d) d.open = true;
        return { emitido: true, sinManejador: false, pintado: true };
      }
      const e = (res && res.evidencia) || {};
      const txt = e.detail || e.falta || JSON.stringify(e, null, 2) || "sin evidencia";
      try { window.alert(String(txt).slice(0, 1200)); } catch (_) {}
      return { emitido: true, sinManejador: false };
    }
    case "credencial":
    case "instalar":
    case "configurar":
    default: {
      // La superficie tiene el contexto (qué conector, qué provider, deep_link). Se lo pasamos
      // por evento — quien monte la superficie lo escucha y abre su widget. FALLO VISIBLE si
      // nadie escucha: devolvemos {sinManejador:true} para que la superficie muestre un aviso.
      const ev = new CustomEvent("cuarto:semaforo-accion", { detail: { accion, res, ctx }, cancelable: true, bubbles: true });
      const target = ctx.el && ctx.el.dispatchEvent ? ctx.el : window;
      const noCancelado = target.dispatchEvent(ev);
      return { emitido: true, sinManejador: noCancelado }; // preventDefault() del oyente = manejado
    }
  }
}

/* ══ [FIX-P1B · §7] «sin internet → [Reintentar] (AUTO AL VOLVER)» ═════════════════════
 * Un rojo por conexión caída es el único que se arregla solo: vuelve el WiFi y la pieza
 * podría estar bien. Pedirle a la persona que apriete [Reintentar] en cada pieza cuando el
 * navegador YA sabe que volvió la red es trabajo manual por nada.
 *
 * Se registra sólo lo que quedó en `sin_red` (nada más se re-prueba solo: una llave
 * inválida no se arregla porque vuelva el WiFi). Al volver, se re-prueba y se repinta. Si
 * el chip ya no está en el DOM, la entrada se descarta — no se acumulan fantasmas.        */
const _ESPERANDO_RED = new Map();      // clave coord → {el, res, opts}

function _anotarParaCuandoVuelva(el, res, opts) {
  if (!el || !res) return;
  const k = _clave(opts && opts.coord);
  if (res.estado === "roto" && res.causa === "sin_red") _ESPERANDO_RED.set(k, { el, res, opts });
  else _ESPERANDO_RED.delete(k);
}

/** Re-prueba todo lo que había quedado sin conexión. Público: la vara lo dispara sin
 *  tener que fabricar un evento del sistema operativo. */
export async function reintentarLoQueEsperabaRed() {
  const pendientes = Array.from(_ESPERANDO_RED.entries());
  _ESPERANDO_RED.clear();
  let repintados = 0;
  for (const [, e] of pendientes) {
    if (!e.el || !e.el.isConnected) continue;               // el chip ya no existe: se olvida
    const coord = (e.opts || {}).coord;
    if (!coord || !TIPOS.has(coord.tipo)) continue;
    olvidarIntentos(coord);            // volvió la red: el contador de fallos arranca limpio
    const res = await probar(coord.tipo, coord.ref, Object.assign({ motivo: "red_volvio" }, coord.opts));
    if (e.el.isConnected) { pintarBadge(e.el, normalizarLocal(res, !!coord.local), e.opts); repintados++; }
  }
  return { repintados, mirados: pendientes.length };
}

if (typeof window !== "undefined" && !window.__semRedWired) {
  window.__semRedWired = true;
  window.addEventListener("online", () => { reintentarLoQueEsperabaRed(); });
}

// ── BADGE DOM · el chip visible del estado, con su botón de arreglo si aplica ─────────
// pintarBadge(el, res, { onProbar, ctx, compacto }) — reemplaza el contenido de `el`.
//   onProbar(res) → callback que la superficie da para re-probar y repintar (probar/reintentar).
//   ctx → contexto que viaja al despacho (credencial/instalar/configurar).
export function pintarBadge(el, res, opts) {
  if (!el) return;
  opts = opts || {};
  const meta = ESTADOS[res && res.estado] || ESTADOS.detectado;
  const boton = botonDe(res);
  const cacheado = res && res.cacheado;
  const i18n = typeof window !== "undefined" && window.AlephI18n;
  const lang = i18n && i18n.lang() === "en" ? "en" : "es";
  const ui = (text) => i18n && i18n.text ? i18n.text(text) : text;
  const tr = (key, fallback, vars) => i18n && i18n.t ? i18n.t(key, vars) : fallback;
  const stateText = meta[lang];

  // texto secundario: "probado hace 2 min" · la causa honesta · "sin probar aún"
  let sub = "";
  if (res && res.estado === "probado") {
    const age = Math.max(0, Math.floor(Date.now() / 1000 - Number(res.ts)));
    const [amount, unit] = age < 60 ? [age, "s"] : age < 3600 ? [Math.floor(age / 60), "min"]
      : age < 86400 ? [Math.floor(age / 3600), "h"] : [Math.floor(age / 86400), "d"];
    const when = !res.ts ? "" : age < 5 ? tr("workshop.badge.just_now", "recién")
      : tr("workshop.badge.ago", haceRato(res.ts), { amount, unit });
    sub = tr("workshop.badge.tested_ago", "probado " + haceRato(res.ts), { when });
  }
  else if (res && res.estado === "roto") {
    sub = (CAUSAS[res.causa] || {})[lang] || ESTADOS.roto[lang].toLowerCase();
    // [§7] «proveedor caído → [Reintentar] + hora». La hora es el dato que convierte
    // «está caído» en algo accionable: decís si vale la pena reintentar ya o en un rato.
    if (boton && boton.conHora) sub += " · " + horaDe(res.ts);
  }
  else if (res && res.estado === "detectado") sub = tr("workshop.badge.untried", "sin probar aún");
  else if (res && res.estado === "parcial")
    sub = ui(res.evidencia && res.evidencia.detail) || tr("workshop.badge.partial", "algunas tools no están disponibles");
  else if (res && res.estado === "no_configurado") {
    const ev = res.evidencia || {};
    sub = ui(ev.falta || ev.detail) || tr("workshop.badge.configuration_missing", "falta configuración");
  }
  else if (res && res.estado === "premium") sub = tr("workshop.badge.premium", "requiere premium");

  const compact = !!opts.compacto;
  // PRESERVA las clases que puso la superficie (p.ej. .prow-sem, .sem-mount) — sólo intercambia las
  // clases del badge/estado. Reemplazar className a secas borraba el layout del caller (bug T2).
  const kept = String(el.className || "").split(/\s+/).filter((c) =>
    c && c !== "sem-badge" && c !== "sem-compacto" && !/^sem-(verde|amber|rojo|blanco|premium)$/.test(c));
  el.className = kept.concat(["sem-badge", meta.css], compact ? ["sem-compacto"] : []).join(" ");
  el.setAttribute("data-estado", meta.clave);
  if (res && res.causa) el.setAttribute("data-causa", res.causa); else el.removeAttribute("data-causa");
  el.setAttribute("role", "status");
  el.setAttribute("aria-label", stateText + (sub ? " — " + sub : ""));

  let html = `<span class="sem-luz" aria-hidden="true">${meta.emoji}</span>`;
  if (!compact) {
    html += `<span class="sem-txt"><span class="sem-estado">${_esc(stateText)}</span>`;
    if (sub) html += `<span class="sem-sub">${_esc(sub)}</span>`;
    html += `</span>`;
  }
  if (boton) html += `<button type="button" class="sem-accion" data-accion="${boton.accion}">${_esc(boton[lang] || ui(boton.es))}</button>`;
  // el SEGUNDO camino de la misma causa ([Ver error] junto a [Reintentar]): no compite con
  // el primario — lo acompaña. En compacto no entra (el chip es un punto, no una barra).
  if (boton && boton.extra && !compact)
    html += `<button type="button" class="sem-accion sem-extra" data-accion="${boton.extra.accion}">${_esc(boton.extra[lang] || ui(boton.extra.es))}</button>`;
  el.innerHTML = html;
  if (compact) el.title = stateText + (sub ? " — " + sub : "");
  _anotarParaCuandoVuelva(el, res, opts);   // §7 · sólo si quedó en «sin conexión»

  // cableado del botón secundario ([Ver error]) — despacho directo, sin mutaciones
  const ext = el.querySelector(".sem-extra");
  if (ext) ext.addEventListener("click", (e) => {
    e.stopPropagation(); despachar("ver_error", res, { ...(opts.ctx || {}), el });
  });
  // cableado del botón
  const btn = el.querySelector(".sem-accion:not(.sem-extra)");
  if (btn && boton) {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (boton.accion === "probar" || boton.accion === "reintentar") {
        // [P1A] UNA sola implementación: el latido, la prueba real, el desenlace y la
        // mutación viven en probarPieza(). Esta superficie ya no las reimplementa — sólo
        // dice CON QUÉ probar (su coord, o su propio closure) y DÓNDE pintar el desenlace.
        const out = await probarPieza({
          coord: opts.coord || null,
          // con `coord` la prueba la hace probarPieza (el motor real, una sola vez); sin
          // coord se usa el closure de la superficie — el contrato viejo sigue valiendo.
          probar: (!opts.coord && typeof opts.onProbar === "function") ? () => opts.onProbar(res) : null,
          boton: btn, previo: res, ctx: opts.ctx, host: opts.outHost || null,
          onQuitar: opts.onQuitar, motivo: opts.motivo, onDesenlace: opts.onOut,
        });
        // §D · [REINTENTAR] CON CAMINO. Un reintento que devuelve el MISMO rojo es un botón
        // que no lleva a ninguna parte (el humano lo aprieta, vuelve el rojo, y ahí se
        // queda). El rojo que la pieza YA tenía es el fallo nº1; el reintento que vuelve
        // rojo es el nº2 → el botón deja de reintentar y pasa a LLEVAR.
        pintarBadge(el, out.res, out.gastado ? { ...opts, _gastado: true } : opts);
      } else {
        const out = despachar(boton.accion, res, { ...(opts.ctx || {}), el });
        if (out && out.sinManejador) {
          // FALLO VISIBLE: nadie manejó el workflow → decirlo, no fingir.
          btn.textContent = "(sin flujo aún)"; btn.disabled = true;
        }
      }
    });
    // §D · el reintento YA se gastó y la cosa sigue sin estar verde → el botón deja de
    // reintentar (sería el mismo rojo otra vez) y pasa a LLEVAR al Centro. Vale para
    // CUALQUIER causa: lo que no puede volver a pasar es un botón que te deja igual.
    // [P1A] `_gastado` se DEDUCE del contador compartido cuando hay coordenada: si no, cada
    // repintado de la superficie devolvía un [Reintentar] flamante sobre un reintento ya
    // gastado — la mutación se perdía en el primer renderPieces().
    const gastado = !!opts._gastado ||
      (!!opts.coord && res && res.estado !== "probado" &&
       intentosDe(opts.coord) >= REINTENTOS_ANTES_DE_MUTAR);
    if (gastado && res && res.estado !== "probado") {
      const mut = _mutarTrasReintento(btn, res, opts);
      // …y con él las OTRAS salidas: [Ver el error completo] · [Probar el server a mano] ·
      // [Quitar]. El primario nombra el destino natural de la pieza (Centro si es una
      // cuenta, el error si es local); las demás quedan al lado, todas reales. [P1A · §4]
      const host = opts.outHost || _hostCrudo(mut || btn);
      // el botón mutado YA ofrece este destino: no se repite a 20px de distancia.
      // [FIX-P3 · §5] se omite por ACCIÓN **y por RÓTULO**: el botón mutado dice
      // «Arreglarlo»/«Configurar», y la salida `wizard` dice exactamente lo mismo.
      const yaOfrecido = [(mut && mut.dataset.accion) || "ver",
                          (mut && (mut.textContent || "").trim()) || ""].filter(Boolean);
      const n = intentosDe(opts.coord || { tipo: res.tipo, ref: res.ref });
      if (host) pintarDesenlace(host, {
        res, verde: false, gastado: true, coord: opts.coord || null, intentos: n,
        texto: textoDesenlace(res, { reintento: true, intentos: n }),
        crudo: crudoDe(res),
      }, Object.assign({}, opts, { omitir: (opts.omitir || []).concat(yaOfrecido) }));
    }
  }
  return el;
}

// §D · la mutación: el mismo botón deja de reintentar y pasa a LLEVARTE al arreglo.
// [reforma · c] …salvo que la pieza sea LOCAL. Mandar un pysandbox al Centro de Conexiones
// era el origen del banner de path crudo («No encontré mcp.catalog/…#pysandbox» + [Agregar
// llave]) sobre una pieza que no lleva llave: el Centro sólo tiene filas de cuentas, CLIs y
// belts forjados. Una pieza local que sigue rota no tiene "conexión que configurar" — tiene
// un error que mostrar.
function _mutarTrasReintento(btn, res, opts) {
  const local = !!((opts || {}).ctx || {}).local ||
                !!((res || {}).evidencia || {}).local;
  // [FIX-P1B · §1] El reintento gastado ya no manda a una pantalla de catálogo (ni deja a
  // una pieza local sin más salida que mirar el error): abre EL WORKFLOW de su tipo. Para
  // una pieza local ese workflow es el de programa, que chequea la dependencia ANTES de
  // volver a reintentar — que era exactamente el reintento al vacío que estamos matando.
  const accion = "wizard";
  btn.dataset.accion = accion;
  btn.dataset.mutado = "1";
  btn.textContent = local ? "Arreglarlo" : "Configurar";
  btn.title = local
    ? "Ya lo reintenté y sigue igual — te abro los pasos para arreglarlo"
    : "Ya lo reintenté y sigue igual — te abro los pasos para conectarlo";
  const clon = btn.cloneNode(true);       // saca el listener de reintento (ya se gastó)
  btn.replaceWith(clon);
  clon.addEventListener("click", (e) => {
    e.stopPropagation();
    despachar(accion, res, { ...((opts || {}).ctx || {}), el: clon });
  });
  return clon;
}

function _faltaLinea(res) {
  const ev = (res && res.evidencia) || {};
  return ev.falta || ev.detail || "falta configuración";
}

// ── CSS del semáforo · inyectado UNA vez · tokens de la marca Aleph (violeta) ─────────
// Colores: verde/amber/rojo estándar + gris para ⚪ + violeta de marca para 🔒. Claro/oscuro
// vía las variables ya vivas del tema (theme.js define --bg/--fg; caemos a valores si faltan).
const CSS = `
.sem-linea{display:flex;align-items:center;gap:.4em;flex-wrap:wrap;margin:6px 0}
.sem-cap{opacity:.72;font-size:.82em}
.sem-mount:empty{display:none}
.sem-badge{display:inline-flex;align-items:center;gap:.4em;font:inherit;font-size:.82em;line-height:1.2;
  padding:.18em .5em;border-radius:.5em;background:var(--sem-bg,rgba(127,127,127,.10));white-space:nowrap;vertical-align:middle}
.sem-badge.sem-compacto{padding:.1em .25em;gap:0}
.sem-luz{font-size:.9em;filter:saturate(1.1)}
.sem-txt{display:inline-flex;flex-direction:column;line-height:1.05}
.sem-estado{font-weight:400}
.sem-sub{opacity:.72;font-size:.86em}
.sem-accion{margin-left:.35em;border:0;background:color-mix(in srgb, currentColor 13%, transparent);color:inherit;cursor:pointer;
  font:inherit;font-size:.86em;padding:.08em .5em;border-radius:var(--r-xs);font-weight:400}
.sem-accion:hover{background:currentColor}
.sem-accion:hover{color:var(--bg,#fff)}
.sem-accion:disabled{opacity:.55;cursor:default}
/* el segundo camino acompaña al primero: mismo tamaño, menos peso (no compite por el ojo) */
.sem-extra{font-weight:300;opacity:.8}
/* §D · el botón que ya se gastó su reintento y ahora LLEVA a alguna parte */
.sem-accion[data-mutado="1"]{font-weight:400}
.sem-accion[data-mutado="1"]::after{content:" →";opacity:.75}
/* ── P1A · EL LATIDO: cae sobre el botón que se apretó, desde el instante del click ── */
[data-probando="1"]{opacity:1 !important;cursor:progress}
[data-probando="1"]::before{content:"";display:inline-block;width:.72em;height:.72em;margin-right:.4em;
  vertical-align:-.06em;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;
  animation:sem-gira .62s linear infinite}
@keyframes sem-gira{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){
  [data-probando="1"]::before{animation:none;border-right-color:currentColor;opacity:.5}
}
/* ── P1A · EL DESENLACE: una línea + el error crudo plegado + las salidas ── */
.sem-out{display:block;margin-top:5px;font-size:11.5px;line-height:1.35}
.sem-out:empty{display:none}
.sem-out-linea{display:flex;align-items:flex-start;gap:.4em}
.sem-out-luz{flex:none;font-size:.95em;line-height:1.35}
.sem-out-txt{display:flex;flex-direction:column;min-width:0}
.sem-out-tit{font-weight:400}
.sem-out-sub{opacity:.75;font-size:.92em}
.sem-out[data-estado="probado"] .sem-out-tit{color:var(--green)}
.sem-out[data-estado="roto"] .sem-out-tit{color:var(--red)}
.sem-out[data-estado="no_configurado"] .sem-out-tit{color:var(--muted)}
.sem-out[data-estado="premium"] .sem-out-tit{color:var(--accent)}
.sem-out-crudo,.sem-out-mano{margin-top:4px}
.sem-out-crudo>summary,.sem-out-mano>summary{cursor:pointer;opacity:.8;font-size:.92em;list-style:none}
.sem-out-crudo>summary::-webkit-details-marker,.sem-out-mano>summary::-webkit-details-marker{display:none}
.sem-out-crudo>summary::before,.sem-out-mano>summary::before{content:"▸ ";opacity:.7}
.sem-out-crudo[open]>summary::before,.sem-out-mano[open]>summary::before{content:"▾ "}
.sem-out-crudo>pre,.sem-out-mano>pre{margin:4px 0 0;padding:6px 7px;max-height:170px;overflow:auto;
  border-radius:.4em;background:rgba(127,127,127,.12);font-size:10.5px;line-height:1.45;
  white-space:pre-wrap;word-break:break-word;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.sem-out-abrir{margin-top:5px;border:0;background:color-mix(in srgb, currentColor 13%, transparent);color:inherit;
  cursor:pointer;font:inherit;font-size:.92em;padding:.14em .55em;border-radius:var(--r-xs)}
/* [FIX-P3 · §6] el camino al dueño del error: la superficie que NO lo es sólo lleva */
.sem-verror{display:inline-block;margin-top:5px;border:0;background:transparent;padding:1px 2px}
.sem-verror:hover{background:transparent;text-decoration:underline}
.sem-salidas{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}
.sem-salida{border:0;background:color-mix(in srgb, currentColor 13%, transparent);color:inherit;cursor:pointer;font:inherit;
  font-size:.92em;padding:.16em .55em;border-radius:var(--r-xs);font-weight:400}
.sem-salida:hover{background:rgba(127,127,127,.16)}
@media (prefers-color-scheme:dark){
  .sem-out[data-estado="probado"] .sem-out-tit{color:#4ade80}
  .sem-out[data-estado="roto"] .sem-out-tit{color:#f87171}
  .sem-out[data-estado="no_configurado"] .sem-out-tit{color:#9ca3af}
  .sem-out[data-estado="premium"] .sem-out-tit{color:#a78bfa}
}
html[data-theme="dark"] .sem-out[data-estado="probado"] .sem-out-tit{color:#4ade80}
html[data-theme="dark"] .sem-out[data-estado="roto"] .sem-out-tit{color:#f87171}
html[data-theme="dark"] .sem-out[data-estado="no_configurado"] .sem-out-tit{color:#9ca3af}
html[data-theme="dark"] .sem-out[data-estado="premium"] .sem-out-tit{color:#a78bfa}
.sem-verde{color:#15803d;--sem-bg:rgba(21,128,61,.12)}
.sem-amber{color:#b45309;--sem-bg:rgba(180,83,9,.12)}
.sem-rojo{color:#b91c1c;--sem-bg:rgba(185,28,28,.12)}
.sem-blanco{color:#6b7280;--sem-bg:rgba(107,114,128,.12)}
.sem-premium{color:#7c3aed;--sem-bg:rgba(124,58,237,.12)}
.sem-badge[data-estado="probando"]{color:#b45309}
@media (prefers-color-scheme:dark){
  .sem-verde{color:#4ade80}.sem-amber{color:#fbbf24}.sem-rojo{color:#f87171}
  .sem-blanco{color:#9ca3af}.sem-premium{color:#a78bfa}
}
html[data-theme="dark"] .sem-verde{color:#4ade80}
html[data-theme="dark"] .sem-amber{color:#fbbf24}
html[data-theme="dark"] .sem-rojo{color:#f87171}
html[data-theme="dark"] .sem-blanco{color:#9ca3af}
html[data-theme="dark"] .sem-premium{color:#a78bfa}
`;

export function inyectarCSS(doc) {
  doc = doc || document;
  if (doc.getElementById("cuarto-semaforo-css")) return;
  const s = doc.createElement("style");
  s.id = "cuarto-semaforo-css";
  s.textContent = CSS;
  (doc.head || doc.documentElement).appendChild(s);
}

// ── Un color hex por estado (para superficies canvas/Pixi que no usan DOM) ────────────
export const COLOR_HEX = {
  probado: 0x22c55e, detectado: 0xf59e0b, roto: 0xef4444,
  no_configurado: 0x9ca3af, premium: 0xa78bfa,
};
export function colorDe(estado) { return COLOR_HEX[estado] != null ? COLOR_HEX[estado] : COLOR_HEX.detectado; }

// ── global para superficies no-module ────────────────────────────────────────────────
// ⚠️ [F7·C] `caraDeCausa` FALTABA ACÁ. Estaba `export`ada —o sea alcanzable por las
// superficies que importan el módulo— pero no en el objeto que se publica en `window`, que
// es el único camino de las superficies NO-module (`brain-status.js`, el picker
// compartido). El síntoma no era una causa fea: era un `TypeError` que se tragaba el
// `catch` del llamante y dejaba la lista de modelos VACÍA. La regla sellada dice que
// ninguna causa llega a una superficie sin copy; si la función que da ese copy no está en
// la superficie pública, la regla no se puede cumplir desde afuera del módulo.
const API = { ESTADOS, CAUSAS, CAMINOS, caminoDe, caraDeCausa, esAlarma,
              esLocalSinTramite, normalizarLocal,
              leerEstado, probar, botonDe, despachar, pintarBadge, inyectarCSS,
              haceRato, horaDe, colorDe, COLOR_HEX, slugDeCentro, urlDelCentro,
              // [FIX-P1B] el workflow por tipo + las dos reglas duras de la tabla
              abrirWorkflow, puedeReintentar, CAUSAS_PERMANENTES, reintentarLoQueEsperabaRed,
              // [P1A] la función ÚNICA de prueba + su desenlace (la consumen P1B · P3 · P7)
              probarPieza, pintarDesenlace, textoDesenlace, crudoDe, manoDe,
              intentosDe, olvidarIntentos, reiniciarIntentos, REINTENTOS_ANTES_DE_MUTAR };
if (typeof window !== "undefined") {
  window.CuartoSemaforo = API;
  try { if (document && (document.head || document.documentElement)) inyectarCSS(document); } catch (e) { /* SSR/no-DOM */ }
}
export default API;
