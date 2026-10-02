#!/usr/bin/env node
/**
 * verify_ui_siempre_solucion.mjs — LA LEY DE PRODUCTO, CONGELADA EN UNA VARA.
 *
 *   node qa/verify_ui_siempre_solucion.mjs
 *
 * LA LEY (sellada por persona usuaria, 2026-08-04): **SIEMPRE SOLUCIÓN.** Cero dead-ends. El usuario
 * jamás ve una confesión nuestra —«no sé», «no encontré», «no pude», «es un defecto
 * nuestro»— ni jerga interna, ni pasos que se contradicen. Cada estado termina en UN BOTÓN
 * QUE RESUELVE, y ese botón NO se inventa: sale de la tabla de repair.
 *
 * La honestidad del sistema no desaparece: se muda. Vive en el registro y en el [?]
 * técnico, que existen para que NOSOTROS arreglemos, no para exhibir la duda al usuario.
 *
 * TRES GUARDS, porque las tres formas de romperla ya ocurrieron:
 *
 *   a) LA MATRIZ · cada estado del registro × credencial × causa de repair tiene texto Y
 *      salida. Una card sin acción sale ROJA con nombre.
 *   b) EL CERO INVENTADO · `nombres_tools_comprobados: true` exige que haya `evidence.tools`
 *      de verdad. Sin medición, `disponibles` NO puede ser un número.
 *   c) LA CONFESIÓN · barrido de frases confesionales en las superficies visibles.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..");
const Sem = await import(join(RAIZ, "product/app/design/cuarto/cuarto.semaforo.js"));

const FALLOS = [];
const ok = (cond, etiqueta, detalle = "") => {
  console.log((cond ? "  ✅ " : "  ❌ ") + etiqueta + (detalle ? ` · ${detalle}` : ""));
  if (!cond) FALLOS.push(etiqueta);
  return cond;
};

// ══════════════════════════════════════════════════════════════════════════════════
// a) LA MATRIZ · ningún estado sin salida
// ══════════════════════════════════════════════════════════════════════════════════
console.log("══ LEY · SIEMPRE SOLUCIÓN ══\n");
console.log("a · LA MATRIZ · cada estado termina en una salida");

//: Los del REGISTRO (la fuente que ahora alimenta la UI) y los del MOTOR (que sigue
//: alimentando el [?]). Los dos vocabularios pasan por `caminoDe`, y por eso los dos se
//: prueban: el día que alguien agregue un estado y olvide su fila, esto lo nombra.
const ESTADOS_REGISTRO = ["viva", "sin_sondear", "rota"];
const ESTADOS_MOTOR = ["probado", "parcial", "detectado", "roto", "no_configurado", "premium"];
//: LOS QUE NO LLEVAN BOTÓN, y por dos motivos DISTINTOS que no hay que confundir:
//:   · `viva`/`probado` — anda: no hay nada que resolver;
//:   · `sin_sondear`    — falta MEDIRLO, y medir es NUESTRO (verificador · calentador ·
//:                        repair). Un botón acá sería trabajo interno delegado al usuario.
const SIN_BOTON_LEGITIMO = new Set(["viva", "probado", "sin_sondear", "detectado"]);

//: ⚠️ ACCIONES QUE SON TRABAJO NUESTRO, NO SUYO. Ninguna card puede ofrecerlas: pedirle al
//: usuario que dispare nuestra medición, que copie nuestro reporte o que mire nuestra
//: evidencia no es una solución — es delegarle la casa. La ley las prohíbe por nombre.
const ACCIONES_INTERNAS = new Set(["probar", "reporte", "ver_error", "copiar_evidencia"]);

//: Las que SÍ son del usuario: su llave, su programa, su cuenta, su plan, su red.
const ACCIONES_DEL_USUARIO = new Set([
  "credencial", "instalar", "instalar_runtime", "login", "premium", "centro",
  "configurar", "liberar", "reintentar", "no_disponible",
]);

for (const estado of [...ESTADOS_REGISTRO, ...ESTADOS_MOTOR]) {
  const causa = (estado === "rota" || estado === "roto") ? "falta_key" : null;
  const c = Sem.caminoDe({ estado, causa });
  if (SIN_BOTON_LEGITIMO.has(estado)) {
    ok(c === null, `«${estado}» no ofrece botón (anda, o lo medimos nosotros)`);
    continue;
  }
  ok(!!(c && c.accion && (c.es || "").trim()),
     `«${estado}» termina en una salida`, c ? `${c.accion} → «${c.es}»` : "SIN CAMINO");
}

// Todas las causas que repair conoce tienen que llegar a una salida.
console.log("\n   · y cada causa de repair, también");
const CAUSAS = [
  "falta_key", "key_invalida", "sin_sesion", "cli_no_instalado", "cli_version_vieja",
  "cli_sin_permisos", "plan_insuficiente", "sin_credito", "modelo_no_disponible",
  "error_upstream", "sin_red", "timeout", "proveedor_caido", "rate_limit",
  "cli_interactivo_colgado", "falla_de_aleph", "no_es_mcp", "fallo_desconocido",
  "sin_tools", "sin_tool_sondeable", "servidor_incompatible", "oauth_revocado",
  "sin_runtime", "sin_espacio", "descarga_cancelada", "formato_no_soportado",
  "una_causa_que_nadie_declaro_todavia",   // ← la que no existe: tampoco puede quedar muda
];
const sinSalida = [];
for (const causa of CAUSAS) {
  const c = Sem.caminoDe({ estado: "roto", causa });
  if (!(c && c.accion && (c.es || "").trim())) sinSalida.push(causa);
}
ok(sinSalida.length === 0, "las 27 causas terminan en una salida",
   sinSalida.length ? `MUDAS: ${sinSalida.join(", ")}` : "incluida una causa inventada");

// ⚠️ LA REGLA NUEVA (persona usuaria, 2026-08-04): una card O AFIRMA UN ESTADO O PIDE UNA ACCIÓN DEL
// USUARIO. Jamás le delega trabajo interno. Antes de esta ley el árbol ofrecía [Probar
// ahora], [Copiar el reporte] y [Ver error] — los tres le pedían al usuario que hiciera lo
// que el verificador, el calentador y repair ya saben hacer solos.
console.log("\n   · y ninguna salida delega trabajo NUESTRO");
const delegadas = [];
for (const causa of CAUSAS) {
  const c = Sem.caminoDe({ estado: "roto", causa });
  if (c && ACCIONES_INTERNAS.has(c.accion)) delegadas.push(`${causa} → ${c.accion}`);
}
for (const estado of [...ESTADOS_REGISTRO, ...ESTADOS_MOTOR]) {
  const c = Sem.caminoDe({ estado, causa: null });
  if (c && ACCIONES_INTERNAS.has(c.accion)) delegadas.push(`${estado} → ${c.accion}`);
}
ok(delegadas.length === 0, "ninguna card le pide al usuario que dispare nuestra medición",
   delegadas.length ? `DELEGAN: ${delegadas.join(", ")}` : "");

const fueraDeVocabulario = [];
for (const causa of CAUSAS) {
  const c = Sem.caminoDe({ estado: "roto", causa });
  if (c && c.accion && !ACCIONES_DEL_USUARIO.has(c.accion) && !ACCIONES_INTERNAS.has(c.accion))
    fueraDeVocabulario.push(`${causa} → ${c.accion}`);
}
ok(fueraDeVocabulario.length === 0,
   "y toda acción ofrecida está en el vocabulario declarado del usuario",
   fueraDeVocabulario.length ? fueraDeVocabulario.join(", ") : "");

// La medición interna se dispara sola: eso también se congela.
console.log("\n   · y lo que falta medir lo dispara el sistema, no el usuario");
ok(typeof Sem.necesitaMedicionInterna === "function",
   "existe `necesitaMedicionInterna()` — la costura de la tarea interna");
ok(Sem.necesitaMedicionInterna({ estado: "sin_sondear" }, null) === true,
   "`sin_sondear` dispara medición nuestra");
ok(Sem.necesitaMedicionInterna({ estado: "viva" }, { estado: "sin_medir" }) === true,
   "credencial `sin_medir` dispara medición nuestra");
ok(Sem.necesitaMedicionInterna({ estado: "viva" }, { estado: "verde" }) === false,
   "lo ya medido NO se vuelve a medir de gusto");
ok(Sem.necesitaMedicionInterna({ estado: "rota", causa: "falta_key" }, null) === false,
   "y un trámite DEL USUARIO no se pisa con una medición nuestra");

// El testigo que persona usuaria pidió que quedara perfecto.
console.log("\n   · el caso testigo (Maritime · falta la llave)");
const maritime = Sem.caminoDe({ estado: "rota", causa: "falta_key" });
ok(maritime && maritime.accion === "credencial",
   "falta_key → acción `credencial`", maritime && maritime.accion);
ok(maritime && maritime.inline === true,
   "y el campo va INLINE, en la card misma (no manda a otra pantalla)");
ok(maritime && /llave/i.test(maritime.es || ""),
   "y el rótulo habla de la llave", maritime && `«${maritime.es}»`);

// ══════════════════════════════════════════════════════════════════════════════════
// b) EL CERO INVENTADO · no medí ≠ medí y dio cero
// ══════════════════════════════════════════════════════════════════════════════════
console.log("\nb · EL CERO INVENTADO · sin medición no hay número");

const entry = {
  service: "maad", id: "maad", label: "Maritime",
  servers: [{ name: "maritime", tools: ["a", "b", "c"], belt_ref: "x.mcp.json" }],
};

// Caso 1 · fila SIN medición ninguna
const sinMedir = Sem.agregarEstadoEntidad(entry, [{ server: entry.servers[0], estado: null }], true);
const e1 = sinMedir.evidencia || {};
ok(e1.nombres_tools_comprobados === false,
   "sin medición, `nombres_tools_comprobados` es false", String(e1.nombres_tools_comprobados));
ok(e1.disponibles === null,
   "sin medición, `disponibles` NO es un número", JSON.stringify(e1.disponibles));
ok((e1.tools_no_disponibles || []).length === 0,
   "sin medición, no se afirma que ninguna tool esté disponible");
ok(e1.sin_medir === true, "y se dice explícitamente que no se midió");
ok(!/servidor/i.test(e1.detail || ""), "el detalle no dice «servidores» (jerga)",
   `«${e1.detail}»`);

// Caso 2 · la regla dura de la ley: true exige evidencia real
const conTools = Sem.agregarEstadoEntidad(entry, [{
  server: entry.servers[0],
  estado: { estado: "probado", evidencia: { tools: ["a", "b", "c"] } },
}], true);
const e2 = conTools.evidencia || {};
ok(e2.nombres_tools_comprobados === true && (e2.tools_disponibles || []).length === 3,
   "CON `evidence.tools`, sí se comprueban los nombres",
   `${(e2.tools_disponibles || []).length}/3`);

// Caso 3 · entidad sin credencial conectada (la segunda rama que inventaba ceros)
const sinCred = Sem.agregarEstadoEntidad(
  Object.assign({}, entry, { credential: { provider: "globalfishingwatch" } }), [], false);
const e3 = sinCred.evidencia || {};
ok(e3.disponibles === null && e3.nombres_tools_comprobados === false,
   "sin credencial tampoco se inventan ceros ni comprobaciones");
ok(sinCred.causa === "falta_key",
   "y la causa es `falta_key`, que ES la que lleva al campo de llave", sinCred.causa);

// ══════════════════════════════════════════════════════════════════════════════════
// c) LA CONFESIÓN · barrido de las superficies visibles
// ══════════════════════════════════════════════════════════════════════════════════
console.log("\nc · LA CONFESIÓN · barrido de frases prohibidas");

//: Las superficies que el usuario mira. No se barre TODO el árbol a propósito: un
//: verificador o un comentario pueden decir «no pude» sin que nadie lo lea en pantalla.
const SUPERFICIES = [
  "product/app/design/Conectar.dc.html",
  // [adaptador 2026-08-04] `conectores.ui.js` murió con la demolición. La superficie de
  // conectores es ahora `superficie.js`, y es la ÚNICA que escribe texto de conectores:
  // `montaje.js` no escribe ninguno (su vara lo comprueba) y `widget.js` no escribe texto
  // en absoluto. Barrer un archivo menos no es cobertura perdida — es que hay un archivo
  // menos que pueda confesar.
  "product/app/design/conectores/superficie.js",
  "product/app/design/cuarto/cuarto.semaforo.js",
  "product/backend/app/phase1/diagnostico_conectores.py",
];

//: Lo que el usuario JAMÁS puede leer. Se busca en CADENAS, no en prosa: un comentario que
//: EXPLICA por qué se sacó «no pude» no puede poner la vara roja — si no, el guard castiga
//: a quien documenta, que es la lección que ya pagó `test_el_dueno_no_spawnea…`.
const PROHIBIDAS = [
  [/no s[ée] qu[eé] pas[oó]/i, "«no sé qué pasó»"],
  [/no pude/i, "«no pude»"],
  [/no encontr[éeè]/i, "«no encontré»"],
  [/no logr[éeè]/i, "«no logré»"],
  [/defecto nuestro/i, "«defecto nuestro»"],
  [/culpa nuestra/i, "«culpa nuestra»"],
  [/\bel backend\b/i, "«el backend» (jerga)"],
  [/servidor MCP/i, "«servidor MCP» (jerga)"],
  [/\bla sonda\b/i, "«la sonda» (jerga)"],
];

/** Las CADENAS de un archivo: `L("…")`, literales de Python y texto entre `>` y `<`.
 *  Los comentarios quedan afuera, que es justo lo que hace usable a este guard. */
function cadenasVisibles(rel) {
  const src = readFileSync(join(RAIZ, rel), "utf8");
  const fuera = [];
  const lineas = src.split("\n");
  for (let i = 0; i < lineas.length; i++) {
    const linea = lineas[i];
    const limpia = linea.trimStart();
    if (limpia.startsWith("//") || limpia.startsWith("#") || limpia.startsWith("*")) continue;
    // ⚠️ EL CAMPO `interno:` ES EL DESTINO LEGÍTIMO DE LA JERGA. La ley no dice «que no
    // exista»: dice que el USUARIO no la vea. Lo que se escribe ahí va al [?] y al reporte,
    // que es exactamente adonde la ley la manda. Un guard que lo castigara empujaría a
    // borrar la evidencia técnica en vez de mudarla — el resultado contrario al buscado.
    // El valor de `interno:` puede venir partido en un ternario de varias líneas, así que
    // se mira hacia atrás hasta encontrar `interno:` o el fin de la expresión. Tres líneas
    // alcanzan para los ternarios del árbol y no tanto como para tapar otra cosa.
    let dentroDeInterno = false;
    for (let k = i; k >= Math.max(0, i - 3); k--) {
      const l = lineas[k];
      if (/\binterno:/.test(l)) { dentroDeInterno = true; break; }
      if (/[;}]\s*$/.test(l) && k !== i) break;
    }
    if (dentroDeInterno) continue;
    for (const m of linea.matchAll(/"([^"\\]{6,200})"/g)) fuera.push([i + 1, m[1]]);
    for (const m of linea.matchAll(/>([^<>{}]{10,200})</g)) fuera.push([i + 1, m[1]]);
  }
  return fuera;
}

const intrusos = [];
for (const rel of SUPERFICIES) {
  for (const [ln, txt] of cadenasVisibles(rel)) {
    for (const [re, nombre] of PROHIBIDAS) {
      if (re.test(txt)) intrusos.push(`${rel}:${ln} ${nombre} → «${txt.slice(0, 60)}»`);
    }
  }
}
ok(intrusos.length === 0, `cero confesiones en las ${SUPERFICIES.length} superficies visibles`,
   intrusos.length ? "\n       " + intrusos.join("\n       ") : "");

// ══════════════════════════════════════════════════════════════════════════════════
// d) EL CABLEADO · cada acción visible se traza a SU verbo, o al territorio del usuario
// ══════════════════════════════════════════════════════════════════════════════════
console.log("\nd · EL CABLEADO · cada acción tiene su verbo o es del usuario");

/** LOS 12 VERBOS HACEN EL TRABAJO; LA UI SÓLO PINTA SU RESULTADO (persona usuaria, 2026-08-04).
 *
 *   card estado      ← persist   (el registro, fuente única)
 *   card botón       ← repair    (causa→acción, el mapa de R4)
 *   card evidencia   ← verify    (la doble, fechas) → al [?]
 *   abrir agente     ← restore + calentador (verify corre solo)
 *   credencial nueva ← authorize (y verify corre SOLO al guardar)
 *   sin medir        ← verify    (background, jamás un botón)
 *   desconectar      ← disconnect (la lápida, muerte YA)
 *
 * `authorize` es EL ÚNICO verbo con parte del usuario. Todo lo demás corre solo, y por eso
 * cada acción que la UI ofrece tiene que trazarse acá: a un verbo que la respalda, o a algo
 * que es genuinamente del usuario —su llave, su programa, su cuenta, su plan, su disco—.
 * Una acción sin fila en esta tabla es una card inventando lógica propia. */
const TRAZA = {
  credencial:       ["authorize", "su llave: la pega él, el canje y el cifrado son de los verbos"],
  configurar:       ["authorize", "el wizard de su cuenta"],
  login:            ["authorize", "su sesión"],
  instalar:         ["usuario",   "su máquina: instalar un programa no lo hace un verbo"],
  instalar_runtime: ["usuario",   "idem, para el runtime local"],
  liberar:          ["usuario",   "su disco"],
  premium:          ["usuario",   "su plan"],
  centro:           ["usuario",   "su cuenta / sus permisos de sistema"],
  // `reintentar` sobrevive SÓLO para las causas donde la precondición es del usuario (su
  // red). El sistema ya reintenta solo al volver la conectividad (`autoAlVolver`); el botón
  // es un acelerador, no una delegación.
  reintentar:       ["usuario",   "su red: el sistema ya reintenta solo al volver"],
  // No es una acción: es la tercera salida declarada de la ley.
  no_disponible:    ["ninguno",   "no hay acción de nadie; el detalle va al [?]"],
};

const sinTraza = [];
for (const causa of CAUSAS) {
  const c = Sem.caminoDe({ estado: "roto", causa });
  if (c && c.accion && !TRAZA[c.accion]) sinTraza.push(`${causa} → ${c.accion}`);
}
for (const estado of [...ESTADOS_REGISTRO, ...ESTADOS_MOTOR]) {
  const c = Sem.caminoDe({ estado, causa: null });
  if (c && c.accion && !TRAZA[c.accion]) sinTraza.push(`${estado} → ${c.accion}`);
}
ok(sinTraza.length === 0, "toda acción ofrecida se traza a un verbo o al usuario",
   sinTraza.length ? `SIN TRAZA: ${sinTraza.join(", ")}` : `${Object.keys(TRAZA).length} acciones trazadas`);

// Y EL CABLE QUE LA LEY NOMBRA EXPLÍCITAMENTE, ahora sobre la superficie nueva. Los tres
// hechos que se comprueban son los mismos; lo que cambió es dónde viven, y para mejor: el
// estado ya no se lee «igual que las cards», se lee UNA sola vez y las cards son eso.
const fuentes = readFileSync(join(RAIZ, "product/app/design/conectores/fuentes.js"), "utf8");
const montaje = readFileSync(join(RAIZ, "product/app/design/conectores/montaje.js"), "utf8");
ok(/\/v1\/conexiones\/fuentes/.test(fuentes) && /medicion/.test(fuentes),
   "card estado ← persist · la superficie lee el REGISTRO, en una sola lectura");
ok(/hayQueMedir/.test(fuentes) && /\/v1\/motor\/probar/.test(fuentes) &&
   /medirLoQueFalta/.test(montaje),
   "sin medir ← verify · la UI dispara la medición sola, en background");
ok(/reconectar/.test(fuentes) && /desconectar/.test(fuentes),
   "desconectar/reconectar ← disconnect · la lápida sigue cableada");
// [nuevo] LA LEY TIENE UNA CUARTA MITAD desde que existe la tabla de conocimiento: una
// pieza que una regla marcó para re-medir TAMBIÉN se mide sola. Antes esas piezas se
// quedaban en rojo hasta que alguien las tocara a mano — eran los rojos falsos del censo.
ok(/verify_pendiente/.test(fuentes),
   "y lo que una regla marcó para re-medir también se mide solo");

console.log("\n" + (FALLOS.length === 0
  ? "══ ✅ LA LEY SE CUMPLE · siempre solución, cero confesión ══"
  : `══ ❌ ${FALLOS.length} VIOLACIÓN(ES): ${JSON.stringify(FALLOS)} ══`));
process.exit(FALLOS.length ? 1 : 0);
