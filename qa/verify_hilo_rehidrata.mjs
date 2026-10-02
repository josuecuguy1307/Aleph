/* verify_hilo_rehidrata.mjs — UN CHAT GUARDADO VUELVE A LA PANTALLA.
 *
 * EL DEFECTO, medido en la .app instalada (sidecar 30cde224) y TAMBIÉN en la anterior
 * (2aa64a13, o sea que no era de la tanda de la Sala moderna): se abría un chat de ayer,
 * `GET /v1/chats/{id}` contestaba con sus mensajes —se vio `msgs=2` y `msgs=4` en la red—
 * y la pantalla seguía diciendo «Contame qué necesitás y lo hacemos». El hilo en blanco
 * con el registro lleno: para el usuario, la conversación se perdió.
 *
 * DÓNDE SE CORTABA. `agente.setMessages()` guarda el array en el `AbstractAgent` y avisa a
 * sus `subscribers` por `onMessagesChanged`. **Nadie implementa ese handler**: el runtime
 * de assistant-ui llena su repositorio SÓLO por el stream de eventos AG-UI
 * (`MESSAGES_SNAPSHOT` → `importMessagesSnapshot`), y `AlephAgent` emite 19 tipos de evento
 * y ése no. El dato llegaba y se tiraba en la última pulgada.
 *
 * LA PUERTA YA ESTABA: `runtime.thread.reset(msgs)` es la API pública de assistant-ui para
 * restaurar un hilo, y está entera en el bundle vendorizado. No se agregó maquinaria — se
 * agregó el llamador. Mismo patrón que `render.js` y que el motor de widgets.
 *
 * QUÉ MIDE ESTA VARA, sin mentir sobre su alcance: que **la puerta exista en el bundle** y
 * que **el llamador la toque bien** (con el runtime en las dependencias del efecto y el
 * `content` como partes, que es la forma que `fromArray` sabe leer). Lo que NO puede medir
 * es el pintado real — eso se mira en pantalla contra la .app instalada, y así se hizo.
 *
 *     node qa/verify_hilo_rehidrata.mjs
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..");
const V = "\x1b[32m", R = "\x1b[31m", F = "\x1b[0m";
const filas = [];
const a = (n, ok, det) => { filas.push([n, ok]); console.log(`  [${ok ? V+"VERDE"+F : R+"ROJA"+F}] ${n} — ${det}`); };

const leer = (p) => { try { return readFileSync(join(RAIZ, p), "utf8"); } catch { return ""; } };
const bundle = leer("product/app/design/sala-v2/vendor/assistant-ui.bundle.js");
const sala   = leer("product/app/design/sala-v2/sala-v2.js");
const agente = leer("product/app/design/sala-v2/agui/aleph-agent.js");

console.log("\n  un chat guardado vuelve a la pantalla\n\nMEDICIÓN");

// R1 · la puerta existe en el runtime vendorizado, y es la que creemos.
const puerta = /reset\(\w\)\{this\.import\(\w+\.fromArray\(\w+\?\?\[\]\)\)\}/.test(bundle);
a("R1 · la puerta existe en el bundle", puerta,
  puerta ? "`reset(e){this.import(Ha.fromArray(e ?? []))}` — API pública de assistant-ui"
         : "no está el reset() que importa un array: la puerta cambió de forma, revisar antes de tocar nada");

// R2 · POR QUÉ hace falta la puerta: el runtime no escucha onMessagesChanged.
//      Todos los hits del bundle son el agente EMITIENDO, ninguno es un handler.
const emisiones = (bundle.match(/onMessagesChanged\?\./g) || []).length;
const handlers  = (bundle.match(/onMessagesChanged\s*[:(]/g) || []).length;
a("R2 · nadie escucha onMessagesChanged", emisiones > 0 && handlers === 0,
  `${emisiones} emisiones, ${handlers} handlers — por eso setMessages solo no alcanza`);

// R3 · y el agente tampoco manda el evento que el runtime sí sabría leer.
a("R3 · el agente no emite MESSAGES_SNAPSHOT", !agente.includes("MESSAGES_SNAPSHOT"),
  "confirma que la vía del evento no está en uso (la que se usa es reset)");

// R4 · EL LLAMADOR. Lo que faltaba.
a("R4 · la rehidratación llama a thread.reset", /runtime\?\.thread\?\.reset\(/.test(sala),
  /runtime\?\.thread\?\.reset\(/.test(sala) ? "toca la puerta" : "NADIE la toca — el hilo queda en blanco");

// R5 · con el runtime en las dependencias: si no, el efecto corre antes de que exista.
const dep = /\}, \[agente, runtime, hiloActual\]\);/.test(sala);
a("R5 · el efecto depende del runtime", dep,
  dep ? "[agente, runtime, hiloActual]" : "el efecto puede correr con el runtime todavía sin crear");

// R6 · el content va como PARTES: `fromArray` no lee un string pelado.
//      ⚠️ SE BUSCA DENTRO DEL BLOQUE DEL `reset`, NO EN TODO EL ARCHIVO. La primera versión
//      de esta fila buscaba el patrón suelto y daba VERDE contra el árbol de antes del
//      arreglo — matcheaba el `thread.append({role:"user", content:[{type:"text"…}]})` del
//      composer (sala-v2.js:918), que ya usaba partes y no tiene nada que ver con
//      rehidratar. Una vara verde que no mide nada es peor que no tenerla.
const bloqueReset = (sala.match(/runtime\?\.thread\?\.reset\([\s\S]{0,320}/) || [""])[0];
const partes = /content:\s*\[\{\s*type:\s*"text",\s*text:/.test(bloqueReset);
a("R6 · el content del reset va como partes", partes,
  partes ? '[{type:"text",text}] — la forma que fromArray sabe leer'
         : "no hay reset con partes: string pelado no pinta");

// R7 · setMessages SE MANTIENE: el estado del agente es otra cosa que lo pintado.
a("R7 · setMessages sigue ahí", /agente\.setMessages\(msgs\)/.test(sala),
  "el estado del agente no se sacrifica por pintar");

console.log("\nPROBADA CAYENDO");
// El árbol de ANTES no tenía llamador: R4/R5/R6 son la caída. Y esto lo verifica sin
// depender de otro checkout — si alguien borra el llamador, las tres se ponen rojas juntas.
const sinLlamador = !/runtime\?\.thread\?\.reset\(/.test(sala);
a("R4 · CAÍDA", !sinLlamador,
  sinLlamador ? "sin llamador: éste es exactamente el estado que tenía el usuario" : "el llamador está");

const verde = filas.every(([, ok]) => ok);
console.log("\n" + "=".repeat(70));
console.log(verde ? `${V}VERDE${F} · el registro llega y la pantalla se entera`
                  : `${R}ROJA${F} · ` + filas.filter(([, ok]) => !ok).map(([n]) => n).join(", "));
console.log("=".repeat(70));
process.exit(verde ? 0 : 1);
