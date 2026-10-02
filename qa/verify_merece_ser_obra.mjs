/* verify_merece_ser_obra.mjs — QUÉ MERECE SER OBRA. [T2.8]
 *
 * EL DEFECTO QUE FIJA, visto en la Biblioteca de la .app instalada: nacía una obra por CADA
 * turno con texto. Entradas REALES que quedaron ahí, y son los casos de esta vara:
 *
 *     «A»
 *     «¿El presupuesto lo querés mensual o anual?»
 *     «La pregunta ya está en pantalla: tocá Mensual, Anual o Ambos…»
 *
 * Nada de eso es un entregable: es una respuesta de una letra y dos veces el agente
 * preguntando. Una multiplicación tampoco lo es.
 *
 * LA ASIMETRÍA QUE JUSTIFICA UNA REGLA CONSERVADORA, y que esta vara existe para sostener:
 * **no crear una obra no pierde nada** —el texto sigue en el hilo, visible y buscable—
 * mientras que crear una de más ensucia la Biblioteca PARA SIEMPRE y hay que borrarla a
 * mano. Falso negativo: costo cero. Falso positivo: permanente. Ante la duda, no nace.
 *
 * SE MIDE LA ESTRUCTURA, NO EL LARGO. Contar caracteres habría dejado pasar justo lo que
 * molesta (las preguntas largas del agente) y habría tirado lo que sirve (una tabla corta).
 *
 * PROBADA CAYENDO: los casos NEGATIVOS son la caída. Si la regla se afloja y empieza a
 * decir `true` sobre «A» o sobre una pregunta, esta vara se pone roja — que es exactamente
 * el estado que la Biblioteca tenía antes.
 *
 *     node qa/verify_merece_ser_obra.mjs
 */
const V = "\x1b[32m", R = "\x1b[31m", F = "\x1b[0m";

// IMPORT DINÁMICO, NO ESTÁTICO, Y NO ES ESTILO. Con `import {...} from` arriba, un árbol
// que no exporta `mereceSerObra` no da rojo: da un `SyntaxError` de Node con su stack. Y
// un stack no es un veredicto — quien lee `tail -1` ve «Node.js v22.20.0» y no sabe si la
// obra está bien o mal. El árbol donde eso pasa es JUSTAMENTE el que tiene el defecto, así
// que la vara se callaba exactamente cuando tenía algo que decir.
let mereceSerObra;
try {
  ({ mereceSerObra } = await import("../product/app/design/sala-v2/artefactos.js"));
} catch (e) {
  console.log(`\n${R}ROJA${F} · artefactos.js no exporta mereceSerObra — la regla no existe en este árbol`);
  console.log(`         ${e.message.split("\n")[0]}`);
  process.exit(1);
}
if (typeof mereceSerObra !== "function") {
  console.log(`\n${R}ROJA${F} · mereceSerObra existe pero no es una función (${typeof mereceSerObra})`);
  process.exit(1);
}

//  [texto, esperado, por qué]
const CASOS = [
  // ── NO son obra (los que ensuciaban la Biblioteca) ──────────────────────────────────
  ["A", false, "una sola letra"],
  ["¿El presupuesto lo querés mensual o anual?", false, "el agente PREGUNTA"],
  ["La pregunta ya está en pantalla: tocá Mensual, Anual o Ambos y con eso armo el presupuesto.",
   false, "confirma que preguntó"],
  ["25! = 15511210043330985984000000\n\nEs la salida exacta que imprimió el código.",
   false, "un número calculado no es un entregable"],
  ["Listo, ya lo hice.", false, "una confirmación"],
  // Los CUATRO que de verdad nacieron como obra en la .app instalada, cada uno con su
  // «Open here». No son ejemplos inventados: son las entradas que había que borrar a mano.
  ["La pregunta ya está en pantalla: tocá **Pesos (ARS)**, **Dólares (USD)** o **Ambas "
   + "(pesos con equivalente en USD)** y con eso armo el reporte.",
   false, "REAL · el agente dice que preguntó"],
  ["La pregunta ya está en pantalla: tocá **Barras**, **Líneas** o **Combinado (barras + "
   + "línea de media móvil 3M)** y con eso dibujo el gráfico de la serie 2025.",
   false, "REAL · idem, con negritas"],
  ["Listo, te dejé las cuatro preguntas con opciones tocables arriba. En cuanto elijas "
   + "(tipo, período, moneda y formato) armo el presupuesto.",
   false, "REAL · anuncia opciones, no entrega nada"],
  ["# Listo", false, "encabezado sin cuerpo"],
  ["", false, "vacío"],
  // ── SÍ son obra ────────────────────────────────────────────────────────────────────
  ["# Informe de ventas 2025\n\n## Resumen\n- Total: 833.500\n\n| Mes | Ventas |\n|---|---|\n| ene | 48200 |",
   true, "informe con tabla"],
  ["Acá va la serie:\n\n```chart\n{\"labels\":[1,2]}\n```", true, "trae un gráfico"],
  ["# Propuesta\n\nPrimer punto del plan.\nSegundo punto del plan.", true, "documento con cuerpo"],
  ["| a | b |\n|---|---|\n| 1 | 2 |", true, "una tabla sola ya es entregable"],
];

let mal = 0;
console.log("\n  qué merece ser obra\n\nMEDICIÓN");
for (const [txt, esperado, por] of CASOS) {
  const r = mereceSerObra(txt, null);
  const ok = r === esperado;
  if (!ok) mal++;
  console.log(`  [${ok ? V + "VERDE" + F : R + "ROJA" + F}] ${String(r).padEnd(5)} · ${por}`);
}

// La obra RICA nace siempre: el backend ya la tipó y acá no se opina.
const rica = mereceSerObra("x", { type: "planilla" }) === true;
if (!rica) mal++;
console.log(`  [${rica ? V + "VERDE" + F : R + "ROJA" + F}] la obra rica nace SIEMPRE (el backend ya decidió)`);

console.log("\n" + "=".repeat(66));
console.log(mal === 0
  ? `${V}VERDE${F} · la Biblioteca sólo recibe entregables`
  : `${R}ROJA${F} · ${mal} caso(s) fuera de la regla`);
console.log("=".repeat(66));
process.exit(mal === 0 ? 0 : 1);
