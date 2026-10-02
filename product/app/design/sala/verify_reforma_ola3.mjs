/* verify_reforma_ola3.mjs — REFORMA DEL CUARTO Y EL CHROME · OLA 3 (EL CHROME).
 *
 * Contra el SIDECAR FROZEN real (WebKit, :8261):
 *   n · SIDEBAR completo, colapsable a iconos · wordmark sin mascota ni monograma ·
 *       filas = logo + nombre y nada más · presionar abre su panel ·
 *       EXCEPCIÓN: el no-verde marca su fila con punto
 *   o · MUEREN las 3 bandas del header (cerebro · cinturón · la corrida): su contenido
 *       vive en los paneles del sidebar y el chat queda limpio
 *   p · caminoDe EN EL CHAT: el mismo diccionario, montado en la conversación
 *
 * Run:  SIDECAR=http://127.0.0.1:8261 node product/app/design/sala/verify_reforma_ola3.mjs
 */
import { webkit } from "playwright";

const BASE = process.env.SIDECAR || "http://127.0.0.1:8261";
const PAGE = `${BASE}/sala/sala.html`;

const fails = [];
const ok = (c, label, extra) => {
  console.log(`${c ? "✓" : "✗"} ${label}${extra != null && extra !== "" ? "  — " + extra : ""}`);
  if (!c) fails.push(label);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

try {
  const r = await fetch(BASE + "/health");
  if (!r.ok) throw new Error("health " + r.status);
  console.log(`── sidecar ${BASE} vivo\n`);
} catch (e) {
  console.log(`✗ el sidecar ${BASE} no responde (${e.message})`);
  process.exit(1);
}

const browser = await webkit.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errores = [];
page.on("pageerror", (e) => errores.push(String(e)));
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) errores.push(m.text().slice(0, 140)); });
await page.goto(PAGE, { waitUntil: "domcontentloaded" });
await page.waitForFunction(() => !!window.__sidebar, null, { timeout: 45000 }).catch(() => {});
await sleep(2500);
ok(errores.length === 0, "La Sala carga sin errores de JS", errores.slice(0, 2).join(" | "));

// ══ n · EL SIDEBAR ══════════════════════════════════════════════════════════════════
console.log("\n§n · el sidebar");
const sb = await page.evaluate(() => ({
  hay: !!window.__sidebar,
  filas: window.__sidebar.filas(),
  wordmark: (document.querySelector(".sb-mark") || {}).textContent,
  monograma: !!document.querySelector(".spine .logo"),
  espinazo: !!document.querySelector("nav.spine"),
  mascota: !!document.querySelector(".sidebar img, .sidebar svg"),
}));
ok(sb.hay && !sb.espinazo, "el espinazo de iconos mudos murió; hay sidebar");
ok(sb.wordmark === "Aleph" && !sb.monograma && !sb.mascota,
   "wordmark «Aleph» — sin mascota, sin monograma", sb.wordmark);
const nombres = sb.filas.map((f) => f.texto);
// [integración tanda-B] la fila se llama «Modelos» desde el rename de FIX-P8 (9c968c8:
// sala.sb.brain). P8 midió esta vara contra el sidecar frozen de la .app INSTALADA —que
// sirve su propia copia de design/, la de antes del rename— y por eso su verde no vio el
// cambio. La ley no cambió: cambió el nombre de la fila.
const esperadas = ["Chats", "Modelos", "Cinturón", "Instrucciones", "El Cuarto", "La Sala"];
ok(esperadas.every((e) => nombres.includes(e)), "están las filas de la ley", nombres.join(" · "));
ok(!!(await page.$("#sbNew")), "…y ＋ Nueva conversación");
ok(!!(await page.$("#sbUser")), "…y el usuario abajo");

// filas en reposo: logo + nombre y NADA más (el punto sólo si no-verde)
const reposo = await page.evaluate(() => {
  return [...document.querySelectorAll("#sbRows .sb-row")].map((r) => {
    const hijos = [...r.children].map((c) => c.className);
    const extra = [...r.children].filter((c) => !/sb-i|sb-t|sb-dot/.test(c.className)).length;
    const puntoVisible = !!(r.querySelector(".sb-dot") && getComputedStyle(r.querySelector(".sb-dot")).display !== "none");
    return { hijos, extra, puntoVisible, estado: r.getAttribute("data-estado") };
  });
});
ok(reposo.every((r) => r.extra === 0), "cada fila es logo + nombre (cero adornos)",
   JSON.stringify(reposo.map((r) => r.hijos.length)));
ok(reposo.every((r) => !r.puntoVisible || r.estado === "warn" || r.estado === "bad"),
   "el punto sale SÓLO cuando algo no está verde",
   reposo.filter((r) => r.puntoVisible).map((r) => r.estado).join(",") || "ninguno");
const cerebro = sb.filas.find((f) => f.panel === "cerebro");
ok(cerebro && cerebro.estado, "la fila del Cerebro declara su estado", (cerebro || {}).estado);

// presionar = abre su panel
console.log("\n§n · presionar una fila abre su panel");
const abrir = await page.evaluate(async () => {
  const r = (p) => document.querySelector(`#sbRows .sb-row[data-panel="${p}"]`);
  r("cerebro").click(); await new Promise((x) => setTimeout(x, 200));
  const a = window.__sidebar.panel();
  const tituloA = (document.getElementById("sbpTitle") || {}).textContent;
  r("cinturon").click(); await new Promise((x) => setTimeout(x, 200));
  const b = window.__sidebar.panel();
  const tituloB = (document.getElementById("sbpTitle") || {}).textContent;
  r("cinturon").click(); await new Promise((x) => setTimeout(x, 200));   // segundo toque cierra
  const c = window.__sidebar.panel();
  return { a, b, c, tituloA, tituloB };
});
ok(abrir.a.abierto && abrir.a.cual === "cerebro", "Cerebro abre su panel", abrir.tituloA);
ok(abrir.b.abierto && abrir.b.cual === "cinturon", "Cinturón abre el suyo", abrir.tituloB);
ok(!abrir.c.abierto, "y el segundo toque lo cierra");

// colapsable a iconos
console.log("\n§n · colapsable a iconos");
const col = await page.evaluate(async () => {
  const anchoDe = () => document.getElementById("sidebar").getBoundingClientRect().width;
  const antes = anchoDe();
  document.getElementById("sbFold").click(); await new Promise((x) => setTimeout(x, 260));
  const chico = anchoDe();
  const nombreVisible = getComputedStyle(document.querySelector("#sbRows .sb-t")).display !== "none";
  const iconoVisible = getComputedStyle(document.querySelector("#sbRows .sb-i")).display !== "none";
  document.getElementById("sbFold").click(); await new Promise((x) => setTimeout(x, 260));
  return { antes, chico, vuelta: anchoDe(), nombreVisible, iconoVisible };
});
ok(col.chico < col.antes && col.chico <= 60, "colapsa a una columna de iconos", `${Math.round(col.antes)}px → ${Math.round(col.chico)}px`);
ok(!col.nombreVisible && col.iconoVisible, "colapsado: quedan los iconos, se van los nombres");
ok(Math.abs(col.vuelta - col.antes) < 2, "y vuelve a expandirse");

// ══ o · MUEREN LAS 3 BANDAS ═════════════════════════════════════════════════════════
console.log("\n§o · las 3 bandas del header murieron");
const bandas = await page.evaluate(() => ({
  enChat: {
    brain: !!document.querySelector(".chat #brainState"),
    stack: !!document.querySelector(".chat #stackPanel"),
    narr: !!document.querySelector(".chat #narrative"),
  },
  enPanel: {
    brain: !!document.querySelector("#sbpCerebro #brainState"),
    stack: !!document.querySelector("#sbpCinturon #stackPanel"),
    narr: !!document.querySelector("#sbpCinturon #narrative"),
  },
  // el chat queda con su header + la franja de conversación, nada apilado encima
  hijosDelChat: [...document.querySelector(".chat").children].map((c) => c.id || c.className),
}));
ok(!bandas.enChat.brain && !bandas.enChat.stack && !bandas.enChat.narr,
   "ninguna de las tres sigue en el chat", JSON.stringify(bandas.enChat));
ok(bandas.enPanel.brain && bandas.enPanel.stack && bandas.enPanel.narr,
   "las tres viven en los paneles del sidebar (mismos nodos, mismos ids)", JSON.stringify(bandas.enPanel));

// ══ p · caminoDe EN EL CHAT ═════════════════════════════════════════════════════════
console.log("\n§p · caminoDe montado en el chat");
const cam = await page.evaluate(() => {
  const f = window.__caminoChat;
  if (!f) return { hay: false };
  return {
    hay: true,
    key: f("falta_key"),
    keyMala: f("key_invalida"),
    sesion: f("sin_sesion"),
    plan: f("plan_insuficiente"),
    nueva: f("una_causa_inexistente"),
    mismoQueElCuarto: (window.CuartoSemaforo.caminoDe({ estado: "roto", causa: "falta_key" }) || {}).es,
  };
});
ok(cam.hay, "la Sala expone el camino del diccionario");
ok(cam.key && cam.key.label === cam.mismoQueElCuarto,
   "el label del chat es EL MISMO que el del Cuarto (un diccionario, no dos)", `${(cam.key || {}).label} == ${cam.mismoQueElCuarto}`);
ok(cam.key && cam.key.accion === "credencial", "sin key → [Poner la key]", (cam.key || {}).label);
ok(cam.sesion && cam.sesion.accion === "login", "sin sesión → iniciar sesión", (cam.sesion || {}).label);
ok(cam.plan && cam.plan.accion === "premium", "plan insuficiente → ver planes", (cam.plan || {}).label);
ok(cam.nueva === null, "una causa que el diccionario no conoce NO inventa botón", String(cam.nueva));

// las tres cards nombradas por la ley existen y son clickeables
const cards = await page.evaluate(async () => {
  const antes = () => (document.querySelector("aleph-chat, deep-chat") ? 1 : 0);
  const out = { cinturon: typeof window.__ofertaCinturon };
  // el cinturón caído: se dispara y deja una card con su camino
  if (window.__ofertaCinturon) window.__ofertaCinturon(2);
  await new Promise((r) => setTimeout(r, 400));
  const sr = window.__salaShadow ? window.__salaShadow() : null;
  const txt = sr ? sr.textContent : document.body.textContent;
  return Object.assign(out, {
    tieneCard: /cinturón no cargó|belt didn't fully load/i.test(txt),
    tieneBoton: /Reparar en el Cuarto|Fix it in The Room/i.test(txt),
  });
});
ok(cards.cinturon === "function", "el camino del cinturón caído existe");
ok(cards.tieneCard && cards.tieneBoton,
   "cinturón no cargó → card en el chat con [Reparar en el Cuarto]", `card=${cards.tieneCard} botón=${cards.tieneBoton}`);

await browser.close();
console.log(`\n${fails.length ? "✗ FALLOS: " + fails.length : "✓ TODO VERDE"}`);
fails.forEach((f) => console.log("   · " + f));
process.exit(fails.length ? 1 : 0);
