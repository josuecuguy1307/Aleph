/* verify_causa_capacidad.mjs — EL FALLO DE CAPACIDAD LLEGA AL USUARIO, Y NO MIENTE.
 *
 *   node qa/verify_causa_capacidad.mjs
 *   node qa/verify_causa_capacidad.mjs --caer     (la prueba de caída)
 *
 * QUÉ MIDE. `capability_unavailable` y `capability_unknown` las tira el resolver de
 * model-use y llegan a la pantalla por `sala-v2/ui/hilo.js:654`. No tenían copy: el hilo
 * caía en el respaldo `provisional` y el usuario leía «No se pudo completar el viaje de
 * esta pieza» sobre algo que sí sabemos explicar.
 *
 * ⚠️ LA MITAD IMPORTANTE DE ESTA VARA NO ES QUE HAYA COPY: ES QUE EL COPY NO MIENTA.
 * `capability_unavailable` es GENÉRICA — hoy la única capacidad exigida es `vision`, pero
 * una frase que diga «tu cerebro no ve imágenes» sería un diagnóstico inventado en cuanto
 * se exija otra. Es el mismo error del gate que imprimía «falta código nuestro» para
 * cualquier fallo: detectaba bien y diagnosticaba mal. El check 4 es el que lo caza.
 */
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..");
const D = join(RAIZ, "product/app/design");
const MUTAR = process.argv.includes("--caer");
let rojas = 0;
const ok = (cond, titulo, det = "") => {
  if (!cond) rojas++;
  console.log(`  ${cond ? "✅" : "❌"} ${titulo}${det ? `   [${det}]` : ""}`);
};

const V = await import(join(D, "conectores/causas-catalogo.js"));
const C = V.CAUSAS_CATALOGO;
const LAS_DOS = ["capability_unavailable", "capability_unknown"];
const LAS_OTRAS = ["no_session", "selection_missing"];
const LAS_CUATRO = ["model_unresolved", "selection_not_found",
                    "selection_unmapped", "model_not_connected"];
const TODAS = [...LAS_DOS, ...LAS_OTRAS, ...LAS_CUATRO];

console.log("═".repeat(78));
console.log("EL FALLO DE CAPACIDAD LLEGA AL USUARIO, Y NO MIENTE");
console.log("═".repeat(78));

console.log("\nA · existen y hablan los dos idiomas");
for (const c of TODAS) {
  const m = C[c] || {};
  ok(!!m.es && !!m.en && m.es !== m.en, `A · ${c} tiene copy ES y EN distintas`,
     m.es ? "" : "falta");
}

console.log("\nB · y el hilo las muestra en vez de caer en el respaldo");
for (const c of TODAS) {
  const r = V.causaDe(c) || {};
  ok(r.provisional === false && !!r.texto, `B · causaDe("${c}") ya no es provisional`,
     r.texto ? r.texto.slice(0, 52) + "…" : String(r.texto));
}

console.log("\nC · el respaldo SIGUE funcionando para las que no tienen entrada");
// Si esto se rompiera, la obra habría cambiado un agujero por otro más difícil de ver.
const desconocida = V.causaDe("una_causa_que_nadie_declaro_todavia") || {};
ok(desconocida.provisional === true && !!desconocida.texto,
   "C · una causa nueva del backend sigue cayendo en `provisional`, no desaparece",
   String(desconocida.provisional));

console.log("\nD · 🔴 EL COPY NO DIAGNOSTICA LO QUE NO SABE");
// `capability_unavailable` no puede afirmar CUÁL capacidad falta: la que falta viaja en
// `aleph.missing`, no en la frase. Nombrar «imágenes» acá es inventar el diagnóstico.
const PROHIBIDAS = ["imagen", "imágen", "image", "vision", "visión", "ver imágenes"];
for (const c of LAS_DOS) {
  // Los dos idiomas por separado, por lo mismo que en G: concatenarlos deja pasar un
  // mutante que ensucia uno solo.
  const dijo = [];
  for (const idioma of ["es", "en"]) {
    const t = String((C[c] || {})[idioma] || "").toLowerCase();
    for (const pr of PROHIBIDAS) if (t.includes(pr.toLowerCase())) dijo.push(`${idioma}:${pr}`);
  }
  ok(dijo.length === 0,
     `D · ${c} NO nombra una capacidad concreta (es genérica)`, dijo.join(","));
}

console.log("\nE · sin jerga, y con una acción que ya existía");
for (const c of TODAS) {
  ok(!V.causaDe(c).texto.includes(c), `E · ${c} no muestra su nombre técnico`);
}
// `elegir_modelo` ya lo usan `browser_sin_vision` y `browser_cerebro_lento`: no se inventó
// un verbo nuevo para la misma acción, que es como se llega a dos botones que hacen lo mismo.
const acciones = new Set(Object.values(C).map((m) => m && m.accion).filter(Boolean));
// Cada una con la SUYA, pero todas de un vocabulario que ya existía: `elegir_modelo` lo
// usaban `browser_sin_vision` y `browser_cerebro_lento`; `login`, `sin_sesion`.
const ESPERADA = { capability_unavailable: "elegir_modelo", capability_unknown: "elegir_modelo",
                   selection_missing: "elegir_modelo", no_session: "login",
                   model_unresolved: "elegir_modelo", selection_not_found: "elegir_modelo",
                   selection_unmapped: "elegir_modelo", model_not_connected: "elegir_modelo" };
for (const c of TODAS) {
  ok(C[c] && C[c].accion === ESPERADA[c] && acciones.has(ESPERADA[c]),
     `E · ${c} usa una acción del vocabulario, no una inventada`, C[c] && C[c].accion);
}

console.log("\nG · 🔴 NO SE COPIA DE MÁS: reusar la acción no es reusar la frase");
// `no_session` es el MISMO hecho que `sin_sesion`, que ya tenía copy. Pero la de
// `sin_sesion` dice «para traer una pieza a tu local»: está atada al flujo de conectores.
// Mostrarla cuando lo que se cayó fue un TURNO le contaría al usuario que estaba haciendo
// algo que no estaba haciendo. Es la misma mentira que inventar un diagnóstico, sólo que
// por copiar en vez de por inventar.
ok(C.sin_sesion && C.no_session && C.sin_sesion.es !== C.no_session.es,
   "G · `no_session` NO reusa la frase de `sin_sesion` (que habla de otro flujo)",
   (C.no_session || {}).es);
for (const idioma of ["es", "en"]) {
  ok(C.no_session && !/pieza|local\b|piece/i.test(String(C.no_session[idioma] || "")),
     `G · y en ${idioma} no le menciona un flujo que el usuario no estaba haciendo`,
     (C.no_session || {})[idioma]);
}
ok(C.sin_sesion && C.no_session && C.sin_sesion.accion === C.no_session.accion,
   "G · pero SÍ comparte la acción, que es lo que de verdad es común",
   (C.no_session || {}).accion);
// `selection_missing` falla por DOS mitades —ni elección ni default— y el copy tiene que
// cubrir las dos: decir sólo «elegí un modelo» deja afuera al que tenía uno y se le rompió.
// ⚠️ CADA IDIOMA POR SEPARADO. Con `es + " " + en` concatenados, un mutante que rompía
// SÓLO el castellano pasaba verde porque el inglés todavía decía «default». Una vara que
// mide la unión de dos textos no mide ninguno de los dos.
for (const [idioma, txt] of [["es", (C.selection_missing || {}).es],
                             ["en", (C.selection_missing || {}).en]]) {
  ok(!!txt && /defecto|default/i.test(txt),
     `G · \`selection_missing\` nombra las DOS mitades en ${idioma} (sin elección Y sin default)`,
     txt);
}

console.log("\nH · 🔴 LAS CUATRO NUEVAS TAMPOCO DIAGNOSTICAN DE MÁS");
// `model_not_connected` es un ENVOLTORIO: el motivo fino viaja en `aleph.cause` y puede ser
// `falta_key`, `key_invalida`, `cli_no_instalado`, `sin_sesion` o `plan_insuficiente`.
// Decir «pegá tu llave» acertaría a veces y mentiría el resto.
for (const idioma of ["es", "en"]) {
  const t = String((C.model_not_connected || {})[idioma] || "");
  ok(!!t && !/llave|key|credencial|credential|instal/i.test(t),
     `H · \`model_not_connected\` en ${idioma} no nombra el motivo fino (viaja en aleph.cause)`,
     t);
}
// El resolver dice «no existe» y la ejecución «YA no existe». Afirmar que estaba es
// inventar la mitad que no sabemos.
for (const idioma of ["es", "en"]) {
  const t = String((C.selection_not_found || {})[idioma] || "");
  ok(!!t && !/ya no|no longer|desapareci|vanish/i.test(t),
     `H · \`selection_not_found\` en ${idioma} no afirma que el modelo ESTUVO`, t);
}
// `selection_unmapped` no es una elección del usuario: es la receta de un Aleph. Culparlo
// de haber elegido mal sería culparlo de algo que no eligió.
for (const idioma of ["es", "en"]) {
  const t = String((C.selection_unmapped || {})[idioma] || "");
  ok(!!t && !/elegiste|you picked|you chose/i.test(t),
     `H · \`selection_unmapped\` en ${idioma} no culpa al usuario de una elección ajena`, t);
}
// Y `model_unresolved` es un dato NUESTRO incompleto: tampoco culpa al usuario.
for (const idioma of ["es", "en"]) {
  const t = String((C.model_unresolved || {})[idioma] || "");
  ok(!!t && /catálogo|catalog/i.test(t),
     `H · \`model_unresolved\` en ${idioma} dice que el modelo SÍ está (y lo que falta)`, t);
}

console.log("\nI · y ninguna copió una frase de otro flujo");
// Las tres candidatas que existían están atadas a otro dominio. Si alguna de las cuatro
// nuevas repitiera su frase, sería la mentira por copiar de más.
const AJENAS = ["servicio_inexistente", "credencial_no_declarada", "sin_sesion"];
for (const c of LAS_CUATRO) {
  const repitio = AJENAS.filter((a) => C[a] && C[c] && C[a].es === C[c].es);
  ok(repitio.length === 0, `I · ${c} no repite la frase de otra causa`, repitio.join(","));
}

console.log("\nF · y no se duplicó el aviso PREVIO, que ya existía");
// La Sala ya avisa ANTES de enviar cuando el cerebro no ve. Esto es lo OTRO: lo que se
// dice cuando el turno ya falló. Si el previo desapareciera, esta obra habría cambiado un
// aviso a tiempo por uno tarde.
const hilo = readFileSync(join(D, "sala-v2/ui/hilo.js"), "utf8");
ok(hilo.includes("salav2.adjuntar.sin_vision"),
   "F · el aviso previo de la Sala sigue en su lugar");
ok(hilo.includes("causaDe("),
   "F · y el hilo sigue leyendo la causa del catálogo compartido");

console.log("\n" + "─".repeat(78));
console.log(`ROJAS: ${rojas}`);
if (MUTAR) {
  console.log(`\nPRUEBA DE CAÍDA: ${rojas > 0
    ? "la vara SE PUSO ROJA con la pieza mutada — mide"
    : "la vara siguió VERDE con la pieza rota — NO MIDE NADA"}`);
  process.exit(rojas > 0 ? 0 : 1);
}
process.exit(rojas ? 1 : 0);
