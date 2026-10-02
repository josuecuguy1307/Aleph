#!/usr/bin/env node
/* verify_chats_sidebar.mjs — LA VARA DE LOS CHATS RECIENTES EN EL SIDEBAR DE LA SALA.
 *
 * WebKit real (el motor de WKWebView, el mismo de la .app) contra el SIDECAR FROZEN DE
 * ESTE ÁRBOL, en puerto propio :8309, con datadir aislado. El registro es REAL: la DB
 * SQLite del cliente, los chats creados por `POST /v1/chats`, los mensajes en
 * `chat_messages`, el renombre por `PATCH /v1/chats/{id}`. La lista que mide la vara es
 * la que sirve `GET /v1/chats` — acá no se stubea ningún store.
 *
 *   node product/app/design/sala/verify_chats_sidebar.mjs
 *
 * LO ÚNICO SIMULADO, Y ESTÁ DECLARADO: `GET /v1/brains/status` (§4). El datadir es
 * virgen, así que no hay modelo configurado y el composer queda —con razón— bloqueado
 * por el brain gate. Para poder ejercitar UN TURNO REAL se le dice a la webview que hay
 * lane incluida. El turno que sale de ahí NO se simula: va al backend de verdad, que
 * persiste el mensaje del humano ANTES de llamar al modelo (`_chat_gate`, router.py:471)
 * y después falla porque no hay credencial. Ese fallo es esperado: lo que se mide es el
 * REGISTRO, no la respuesta del modelo.
 *
 * CALIBRACIÓN EN ROJO — no es un flag, es una ENTRADA ADVERSA plantada en la DB: uno de
 * los cinco chats queda con `updated_at='2026-07-27T13:99:99.999'`, una fecha que ordena
 * como texto entre sus hermanas pero que `new Date()` no puede leer. Cae en MEDIO de la
 * lista a propósito: si el sidebar se rompiera, se llevaría por delante a las tres de
 * abajo. Lo exigido es §4h — esa fila DICE que no se pudo leer, no se puede abrir, y las
 * cuatro sanas siguen listadas, en orden y clickeables.
 *
 * PUERTO PROPIO :8309 — comprobado antes de arrancar. JAMÁS :25374 (la .app de persona usuaria).
 *
 * ⚠ GOTCHA: el sidecar frozen NO sirve tu árbol — sirve la COPIA de `product/app/design`
 * que quedó adentro del binario (datas → _MEIPASS). Después de tocar el front hay que
 * recongelar o se mide el front viejo:
 *   ALEPH_SIDECAR_ONEFILE=1 ALEPH_BUILD=public <venv>/bin/pyinstaller --clean --noconfirm \
 *       --distpath D --workpath W deploy/fase4/aleph_sidecar.spec
 */
import { webkit } from "playwright";
import net from "node:net";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { spawnFrozen, matarFrozen } from "../../../../qa/lib/frozen_guard.mjs";

const ROOT = fileURLToPath(new URL("../../../../", import.meta.url));
const PORT = Number(process.env.CHATS_SB_PORT || 8309);
if (PORT === 25374) { console.error("✗ 25374 es la .app instalada — hay que usar otro puerto"); process.exit(2); }
const BASE = `http://127.0.0.1:${PORT}`;
const SIDECAR = process.env.ALEPH_SIDECAR_BIN ||
  path.join(ROOT, "deploy/fase4/aleph-shell/src-tauri/binaries/aleph_sidecar-aarch64-apple-darwin");
const SHOTS = process.env.CHATS_SB_SHOTS || path.join(ROOT, "product/app/design/sala/screenshots");

let PASS = 0; const FALLOS = [];
const ok = (c, name, det = "") => {
  if (c) { PASS++; console.log(`  ✓ ${name}${det ? "  — " + det : ""}`); }
  else { FALLOS.push(name); console.log(`  ✗ ${name}${det ? "  — " + det : ""}`); }
  return !!c;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sec = (t) => console.log(`\n── ${t} ${"─".repeat(Math.max(0, 68 - t.length))}`);

/* ── el puerto es mío o no hay veredicto ─────────────────────────────────────────── */
await new Promise((res, rej) => {
  const p = net.createConnection({ port: PORT, host: "127.0.0.1" });
  p.on("connect", () => { p.destroy(); rej(new Error(
    `:${PORT} YA ESTÁ OCUPADO. Esta vara mide su propio árbol o no mide nada.\n` +
    `  lsof -nP -iTCP:${PORT} -sTCP:LISTEN  →  kill <pid>   ·   o CHATS_SB_PORT=8310`)); });
  p.on("error", () => res());
});
if (!fs.existsSync(SIDECAR)) {
  console.error(`✗ no existe el sidecar frozen de ESTE árbol: ${SIDECAR}\n` +
                `  ALEPH_SIDECAR_BIN=<ruta> node ${process.argv[1]}`);
  process.exit(2);
}

const DATADIR = fs.mkdtempSync(path.join(os.tmpdir(), "aleph-chats-sb-"));
const DB = path.join(DATADIR, "aleph.db");
const sq = (sql) => execFileSync("sqlite3", [DB, sql], { encoding: "utf8" }).trim();
const esc = (s) => String(s).replace(/'/g, "''");

let PROC = null, LOG = "";
async function esperarPuerto(ms, libre = false) {
  const t0 = Date.now();
  for (;;) {
    const ocupado = await new Promise((r) => {
      const s = net.connect(PORT, "127.0.0.1");
      s.on("connect", () => { s.destroy(); r(true); });
      s.on("error", () => { s.destroy(); r(false); });
    });
    if (ocupado !== libre) return true;
    if (Date.now() - t0 > ms) return false;
    await sleep(250);
  }
}
async function bootear() {
  PROC = spawnFrozen(SIDECAR, ["--port", String(PORT)], {
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, ALEPH_ROLE: "client", ALEPH_DATA_DIR: DATADIR },
  });
  LOG = "";
  PROC.stdout.on("data", (b) => { LOG += b.toString(); });
  PROC.stderr.on("data", (b) => { LOG += b.toString(); });
  if (!(await esperarPuerto(90000))) throw new Error("el sidecar frozen no levantó");
  await sleep(700);
}
async function matar() {
  if (!PROC) return;
  try { matarFrozen(PROC); } catch (e) {}
  PROC = null;
  await esperarPuerto(20000, true);
  await sleep(250);
}
const api = async (m, ruta, { token, body } = {}) => {
  const h = { "Content-Type": "application/json" };
  if (token) h.Authorization = "Bearer " + token;
  const r = await fetch(BASE + ruta, { method: m, headers: h, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text();
  let j = null; try { j = t ? JSON.parse(t) : null; } catch (e) {}
  return { status: r.status, json: j, text: t };
};

console.log(`▸ sidecar : ${SIDECAR}`);
console.log(`▸ datadir : ${DATADIR}`);
console.log(`▸ base    : ${BASE}`);

/* El estado del cerebro: el ÚNICO stub, y sólo para §4 (ver cabecera). */
const BRAINS_OK = { providers: { included: { state: "ready", detail: "" } }, service: null };

let browser = null;
try {
  await bootear();
  const s0 = await api("POST", "/v1/auth/local");
  const SESION = s0.json || {};
  ok(s0.status === 200 && SESION.session_token, "sesión de equipo del frozen", `http ${s0.status}`);
  const TOK = SESION.session_token;

  /* ══ SIEMBRA · CINCO HILOS REALES ════════════════════════════════════════════════
   * Los chats nacen por el endpoint real. Los turnos van a `chat_messages` con sqlite3
   * y el título se siembra con el MISMO efecto que tiene `append_message` (repo:
   * `title = LEFT(primer mensaje del humano, 80)` sólo si el chat no tiene título).
   * `updated_at` se fija a mano: el orden de creación NO es el orden de actividad, que
   * es justamente lo que la lista tiene que respetar. */
  const HILOS = [
    { k: "A", pri: "cuánto sale el flete a Cuenca de dos pallets", ult: "Con esa ruta te queda en 180 por pallet.", up: "2026-07-27T10:00:00.000", esperado: "cuánto sale el flete a Cuenca de dos pallets" },
    { k: "B", pri: "necesito el presupuesto de la obra del sábado", ult: "Listo, quedó el desglose por rubro.", up: "2026-07-27T14:00:00.000", rename: "Presupuesto de la obra", esperado: "Presupuesto de la obra" },
    { k: "C", pri: null, ult: "El informe de septiembre quedó armado.", up: "2026-07-27T09:00:00.000", esperado: "El informe de septiembre quedó armado." },
    { k: "D", pri: "revisá la planilla de horas del equipo", ult: "Hay tres días sin fichar.", up: "2026-07-27T12:00:00.000", esperado: "revisá la planilla de horas del equipo" },
    // ── CALIBRACIÓN EN ROJO: el registro ilegible, plantado en MEDIO de la lista ──
    { k: "E", pri: "este hilo tiene el registro podrido", ult: "…", up: "2026-07-27T13:99:99.999", roto: true, esperado: null },
  ];
  for (const h of HILOS) {
    const c = await api("POST", "/v1/chats", { token: TOK, body: {} });
    h.id = (c.json || {}).id;
    if (!h.id) throw new Error(`no se pudo crear el chat ${h.k}: http ${c.status} ${c.text}`);
    const filas = [];
    if (h.pri) filas.push(`('${h.id}','user','chat','${esc(h.pri)}')`);
    filas.push(`('${h.id}','agent','chat','${esc(h.ult)}')`);
    sq(`INSERT INTO chat_messages (chat_id,role,kind,content) VALUES ${filas.join(",")};`);
    if (h.pri) sq(`UPDATE chats SET title=substr('${esc(h.pri)}',1,80) WHERE id='${h.id}' AND title='';`);
  }
  // el renombre va por el endpoint real (es el «o nombre si existe» del dictado)
  {
    const b = HILOS.find((x) => x.rename);
    const r = await api("PATCH", `/v1/chats/${b.id}`, { token: TOK, body: { title: b.rename } });
    ok(r.status === 200, "el renombre real (PATCH /v1/chats/{id}) queda en el registro", `http ${r.status}`);
  }
  // la actividad, a mano: el orden de la lista NO puede ser el de creación
  for (const h of HILOS) sq(`UPDATE chats SET updated_at='${h.up}' WHERE id='${h.id}';`);

  const ROJO = HILOS.find((h) => h.roto);
  ok(sq(`SELECT updated_at FROM chats WHERE id='${ROJO.id}';`) === ROJO.up,
     "ROJO plantado: un registro con fecha de actividad ilegible", ROJO.up);
  ok(isNaN(new Date(ROJO.up).getTime()), "…y es ilegible de verdad (Date la rechaza)");

  // el orden que el registro declara (última actividad, más nueva primero)
  const ORDEN = [...HILOS].sort((a, b) => (a.up < b.up ? 1 : a.up > b.up ? -1 : 0));
  const SANOS = ORDEN.filter((h) => !h.roto);
  console.log(`  · orden por actividad: ${ORDEN.map((h) => h.k).join(" > ")}`);

  const lista = await api("GET", "/v1/chats?limit=20", { token: TOK });
  ok(lista.status === 200 && (lista.json.chats || []).length === 5,
     "el registro sirve los cinco hilos", `n=${(lista.json.chats || []).length}`);

  /* ── WebKit ─────────────────────────────────────────────────────────────────────── */
  browser = await webkit.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await ctx.addInitScript((u) => { try { localStorage.setItem("puppet_user", JSON.stringify(u)); } catch (e) {} }, SESION);
  fs.mkdirSync(SHOTS, { recursive: true });
  const filas = (pg) => pg.evaluate(() => (window.__sidebar && window.__sidebar.chats()) || null);

  /* ══ §1 · LOS HILOS ESTÁN A LA VISTA, EN ORDEN ═══════════════════════════════════ */
  sec("§1 · LISTADOS — debajo de «Nueva conversación», por última actividad");
  const pg = await ctx.newPage();
  const errores = [];
  pg.on("pageerror", (e) => errores.push(String(e).slice(0, 200)));
  await pg.goto(`${BASE}/sala/sala.html`, { waitUntil: "domcontentloaded" });
  await pg.waitForSelector("#sbChats", { timeout: 20000 });
  await pg.waitForFunction(() => document.querySelectorAll("#sbChats .sb-chat").length > 0, { timeout: 20000 });
  await sleep(600);

  const f1 = await filas(pg);
  ok(Array.isArray(f1) && f1.length === 5, "§1.1 los cinco hilos, listados", `n=${f1 && f1.length}`);
  ok(f1 && f1.every((x) => x.visible), "§1.2 y todos visibles (nada se pinta y se esconde)");

  // la fila ilegible no ofrece id (no hay hilo que abrir), así que el orden se compara
  // sobre las sanas; DÓNDE cayó la rota lo mide §2.6.
  const clave = (x) => (x.roto ? "roto" : HILOS.find((h) => h.id === x.id)?.k || "?");
  const vistoSano = (f1 || []).filter((x) => !x.roto).map((x) => x.id);
  ok(JSON.stringify(vistoSano) === JSON.stringify(SANOS.map((h) => h.id)),
     "§1.3 EL ORDEN es el de última actividad (no el de creación)",
     `visto=${(f1 || []).map(clave).join(">")} · esperado=${ORDEN.map((h) => (h.roto ? "roto" : h.k)).join(">")}`);

  for (const h of SANOS) {
    const fila = (f1 || []).find((x) => x.id === h.id);
    ok(!!fila && fila.titulo === h.esperado,
       `§1.4·${h.k} el título es ${h.rename ? "el nombre puesto a mano" : h.pri ? "el primer mensaje" : "el último turno (no hay primero)"}`,
       `«${fila && fila.titulo}»`);
  }
  ok(!errores.length, "§1.5 la página no tiró un solo error", errores.join(" | "));

  // la posición en el DOM: la lista va DEBAJO del botón de nueva conversación
  const geo = await pg.evaluate(() => {
    const n = document.getElementById("sbNew").getBoundingClientRect();
    const c = document.getElementById("sbChats").getBoundingClientRect();
    const r = document.getElementById("sbRows").getBoundingClientRect();
    const h = document.getElementById("sbChatsH");
    return { debajoDeNueva: c.top >= n.bottom - 1, encimaDeNav: c.top <= r.top + 1,
             enca: !h.hidden && getComputedStyle(h).display !== "none" };
  });
  ok(geo.debajoDeNueva, "§1.6 la lista vive DEBAJO de «Nueva conversación»", JSON.stringify(geo));
  ok(geo.enca, "§1.7 …con su encabezado a la vista cuando hay hilos");

  /* ══ §2 · LA CALIBRACIÓN EN ROJO ═════════════════════════════════════════════════ */
  sec("§2 · ROJO — el registro ilegible lo DICE y no se lleva la lista");
  const fRoto = (f1 || []).find((x) => x.roto);
  ok(!!fRoto, "§2.1 el hilo ilegible tiene SU fila marcada como rota");
  ok(!!fRoto && /no pude leer|couldn't read/i.test(fRoto.titulo),
     "§2.2 …y el fallo es VISIBLE en la fila (§4h: jamás mudo)", `«${fRoto && fRoto.titulo}»`);
  ok(!!fRoto && !fRoto.id, "§2.3 …y no ofrece un hilo que no puede abrir");
  ok(!!fRoto && /ilegible|no se puede leer/i.test(fRoto.title || ""),
     "§2.4 …y dice POR QUÉ", fRoto && fRoto.title);
  const sanasVistas = (f1 || []).filter((x) => !x.roto);
  ok(sanasVistas.length === 4, "§2.5 LA LISTA ENTERA SIGUE VIVA: las cuatro sanas, listadas",
     `n=${sanasVistas.length}`);
  const idxRoto = (f1 || []).findIndex((x) => x.roto);
  ok(idxRoto > 0 && idxRoto < 4, "§2.6 …y el rojo estaba en MEDIO (no al final, donde no probaría nada)",
     `posición ${idxRoto + 1}/5`);
  const clickRoto = await pg.evaluate(() => {
    const b = document.querySelector("#sbChats .sb-chat.roto");
    const antes = location.href;
    try { b.click(); } catch (e) {}
    return { disabled: !!b.disabled, movio: location.href !== antes };
  });
  ok(clickRoto.disabled && !clickRoto.movio, "§2.7 …y clickearla no lleva a ningún lado", JSON.stringify(clickRoto));

  /* ══ §3 · CLICK → CARGA EL HILO CORRECTO (contra el transcript) ══════════════════ */
  sec("§3 · CLICK — abre EL hilo, con SUS turnos");
  const OBJ = HILOS.find((h) => h.k === "A");          // 4º de la lista: ni el primero ni el último
  await pg.click(`#sbChats .sb-chat[data-chat-id="${OBJ.id}"]`);
  await pg.waitForFunction((id) => location.search.includes("chat=" + id), OBJ.id, { timeout: 20000 });
  await pg.waitForSelector("#sbChats .sb-chat", { timeout: 20000 });
  await sleep(3500);   // rehidratación + markdown async

  ok(pg.url().includes(`chat=${OBJ.id}`), "§3.1 la URL apunta al hilo clickeado", pg.url().split("?")[1]);

  // el transcript REAL del backend, y lo que la Sala pintó
  const tr = await api("GET", `/v1/chats/${OBJ.id}`, { token: TOK });
  const msgs = ((tr.json || {}).messages || []).map((m) => String(m.content || ""));
  ok(tr.status === 200 && msgs.length === 2, "§3.2 el transcript del registro tiene sus dos turnos",
     `n=${msgs.length}`);
  const pintado = await pg.evaluate(() => {
    const dc = document.querySelector("deep-chat");
    const sr = dc && dc.shadowRoot;
    return ((sr && sr.textContent) || document.body.textContent || "").replace(/\s+/g, " ");
  });
  const posiciones = msgs.map((m) => pintado.indexOf(m.replace(/\s+/g, " ")));
  ok(posiciones.every((p) => p >= 0),
     "§3.3 LOS TURNOS PINTADOS SON LOS DEL TRANSCRIPT (assert contra el registro)",
     JSON.stringify(posiciones));
  ok(posiciones.every((p, i) => i === 0 || p > posiciones[i - 1]),
     "§3.4 …y en el orden en que ocurrieron");
  // y NO se coló el hilo de al lado
  const ajeno = HILOS.find((h) => h.k === "D");
  ok(!pintado.includes(ajeno.pri), "§3.5 …y NADA del hilo vecino se filtró", `«${ajeno.pri}»`);

  /* ══ §4 · EL ACTIVO, MARCADO ════════════════════════════════════════════════════ */
  sec("§4 · EL HILO ABIERTO queda marcado");
  const f2 = await filas(pg);
  const activas = (f2 || []).filter((x) => x.activo);
  ok(activas.length === 1, "§4.1 hay exactamente UNA fila marcada", `n=${activas.length}`);
  ok(activas.length === 1 && activas[0].id === OBJ.id, "§4.2 …y es la del hilo abierto",
     activas[0] && activas[0].titulo);
  const marca = await pg.evaluate((id) => {
    const b = document.querySelector(`#sbChats .sb-chat[data-chat-id="${id}"]`);
    const o = document.querySelector("#sbChats .sb-chat:not(.on):not(.roto)");
    const cs = getComputedStyle(b), co = getComputedStyle(o);
    return { fondo: cs.backgroundColor !== co.backgroundColor, peso: cs.fontWeight !== co.fontWeight,
             aria: b.getAttribute("aria-current") };
  }, OBJ.id);
  ok(marca.fondo || marca.peso, "§4.3 …y la marca SE VE (no es sólo una clase)", JSON.stringify(marca));
  ok(marca.aria === "true", "§4.4 …y también para quien no la ve (aria-current)");

  await pg.screenshot({ path: path.join(SHOTS, "chats-sidebar-es.png"), clip: { x: 0, y: 0, width: 300, height: 900 } });

  /* ══ §5 · NUEVA CONVERSACIÓN → ARRIBA AL PRIMER MENSAJE ══════════════════════════ */
  sec("§5 · UN HILO NUEVO sube al tope apenas hay primer mensaje");
  const pg2 = await ctx.newPage();
  const err2 = [];
  pg2.on("pageerror", (e) => err2.push(String(e).slice(0, 200)));
  // el ÚNICO stub, declarado: el datadir es virgen y sin modelo el composer está —bien—
  // bloqueado. El turno que sale de acá va al backend REAL.
  await pg2.route("**/v1/brains/status*", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(BRAINS_OK) }));
  await pg2.goto(`${BASE}/sala/sala.html?chat=${OBJ.id}`, { waitUntil: "domcontentloaded" });
  await pg2.waitForSelector("#sbNew", { timeout: 20000 });
  await sleep(2500);

  await pg2.click("#sbNew");
  await pg2.waitForFunction(() => !location.search.includes("chat="), { timeout: 20000 });
  await pg2.waitForSelector("#sbChats .sb-chat", { timeout: 20000 });
  await sleep(2500);
  ok(!pg2.url().includes("chat="), "§5.1 «Nueva conversación» deja el hilo y abre uno en blanco", pg2.url());
  const f3 = await filas(pg2);
  ok((f3 || []).length === 5 && !(f3 || []).some((x) => x.activo),
     "§5.2 …con los cinco viejos listados y ninguno marcado", `n=${f3 && f3.length}`);

  const puedeEnviar = await pg2.evaluate(() => (window.__salaTurno || {}).canSend);
  ok(puedeEnviar === true, "§5.3 el composer está habilitado (brain gate declarado en la cabecera)",
     `canSend=${puedeEnviar}`);

  const PRIMERO = "arrancá el acta de la reunión del lunes";
  await pg2.evaluate((t) => {
    const dc = document.querySelector("deep-chat");
    const inp = dc && dc.shadowRoot && dc.shadowRoot.querySelector("#text-input");
    inp.focus(); inp.textContent = t;
    inp.dispatchEvent(new Event("input", { bubbles: true }));
  }, PRIMERO);
  await sleep(400);
  await pg2.evaluate(() => {
    const dc = document.querySelector("deep-chat");
    const sr = dc && dc.shadowRoot;
    const b = sr.querySelector(".input-button-container .input-button, #submit-icon, .submit-button");
    if (b) b.click();
    else sr.querySelector("#text-input").dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  });

  // el turno REAL: el backend persiste el mensaje del humano y DESPUÉS falla por no tener
  // credencial. Se espera al REGISTRO, que es lo que se mide.
  let subio = null;
  for (let i = 0; i < 60; i++) {
    await sleep(1000);
    const f = await filas(pg2);
    if (f && f.length === 6 && f[0] && f[0].titulo === PRIMERO) { subio = f; break; }
    if (f && f.length === 6 && !subio) subio = f;   // ya nació: se sigue esperando el título
    if (i === 59) subio = f;
  }
  ok(!!subio && subio.length === 6, "§5.4 el hilo nuevo existe en el registro", `n=${subio && subio.length}`);
  ok(!!subio && subio[0] && subio[0].titulo === PRIMERO,
     "§5.5 …y quedó ARRIBA, titulado con el primer mensaje", `«${subio && subio[0] && subio[0].titulo}»`);
  ok(!!subio && subio[0] && subio[0].activo, "§5.6 …y marcado como el hilo abierto");
  // el registro del backend confirma que no es una pintura del front
  const l2 = await api("GET", "/v1/chats?limit=20", { token: TOK });
  const top = ((l2.json || {}).chats || [])[0] || {};
  ok(top.title === PRIMERO && top.id === (subio && subio[0] && subio[0].id),
     "§5.7 …y el registro dice lo mismo (no es una fila pintada de adorno)",
     `«${top.title}»`);
  ok(!err2.length, "§5.8 y la página siguió sin errores", err2.join(" | "));

  /* ══ §6 · ES / EN EN LOCKSTEP ═══════════════════════════════════════════════════ */
  sec("§6 · ES/EN — las claves nuevas viajan en los dos idiomas");
  const dict = fs.readFileSync(path.join(ROOT, "product/app/design/i18n.js"), "utf8");
  for (const k of ["sala.sb.recientes", "sala.sb.chat_roto"]) {
    const n = (dict.match(new RegExp('"' + k.replace(/\./g, "\\.") + '"', "g")) || []).length;
    ok(n === 2, `§6.1 «${k}» está en ES y en EN`, `apariciones=${n}`);
  }
  const pgEn = await ctx.newPage();
  await pgEn.addInitScript(() => { try { localStorage.setItem("aleph-lang", "en"); } catch (e) {} });
  await pgEn.goto(`${BASE}/sala/sala.html?chat=${OBJ.id}`, { waitUntil: "domcontentloaded" });
  await pgEn.waitForFunction(() => document.querySelectorAll("#sbChats .sb-chat").length > 0, { timeout: 20000 });
  await sleep(1800);
  const en = await pgEn.evaluate(() => ({
    enca: (document.getElementById("sbChatsH").textContent || "").trim(),
    nueva: (document.querySelector("#sbNew .sb-t").textContent || "").trim(),
    roto: ((document.querySelector("#sbChats .sb-chat.roto .sb-ct") || {}).textContent || "").trim(),
    titulos: [...document.querySelectorAll("#sbChats .sb-chat:not(.roto) .sb-ct")].map((e) => e.textContent.trim()),
  }));
  ok(en.enca === "Recent", "§6.2 el encabezado en EN dice «Recent»", `«${en.enca}»`);
  ok(/couldn't read/i.test(en.roto), "§6.3 …y el fallo también habla EN", `«${en.roto}»`);
  ok(en.titulos.includes(OBJ.esperado),
     "§6.4 …y los títulos NO se traducen (son del humano, no de la UI)", JSON.stringify(en.titulos.slice(0, 2)));
  await pgEn.screenshot({ path: path.join(SHOTS, "chats-sidebar-en.png"), clip: { x: 0, y: 0, width: 300, height: 900 } });

  /* ══ §7 · EL SIDEBAR PLEGADO ════════════════════════════════════════════════════ */
  sec("§7 · PLEGADO — una lista de títulos no se pinta donde no cabe");
  await pg.click("#sbFold");
  await sleep(500);
  const plegado = await pg.evaluate(() => {
    const c = document.getElementById("sbChats"), h = document.getElementById("sbChatsH");
    return { sb: document.getElementById("shell").getAttribute("data-sb"),
             lista: getComputedStyle(c).display, enca: getComputedStyle(h).display,
             nav: getComputedStyle(document.getElementById("sbRows")).display };
  });
  ok(plegado.sb === "0" && plegado.lista === "none" && plegado.enca === "none",
     "§7.1 plegado: la lista se retira entera", JSON.stringify(plegado));
  ok(plegado.nav !== "none", "§7.2 …y la navegación de iconos sigue ahí");
  await pg.click("#sbFold");
  await sleep(500);
  const vuelta = await pg.evaluate(() => getComputedStyle(document.getElementById("sbChats")).display);
  ok(vuelta !== "none", "§7.3 …y vuelve al desplegar", vuelta);

  /* ══ §8 · ¿LA CALIBRACIÓN ROJA SIRVE DE ALGO? ═══════════════════════════════════
   * Una calibración que no puede ponerse roja es un adorno. Acá se corre la MISMA
   * página con una sola cosa cambiada al vuelo —el guard que declara ilegible un
   * registro devuelve siempre «está sano»— y se exige que §2 se caiga: si el sidebar
   * no distinguiera, ese hilo se pintaría como uno normal, ofreciendo abrir algo que
   * no puede leer. O sea: lo que §2 mide es el guard, no la suerte. */
  sec("§8 · SENSIBILIDAD — sin el guard, el registro ilegible pasaría por sano");
  const pgS = await ctx.newPage();
  await pgS.route("**/sala/sala.html*", async (r) => {
    const res = await r.fetch();
    const cuerpo = (await res.text())
      .replace("function sbChatMotivoRoto(r){", "function sbChatMotivoRoto(r){ return null;");
    await r.fulfill({ response: res, body: cuerpo, headers: { ...res.headers(), "content-length": undefined } });
  });
  await pgS.goto(`${BASE}/sala/sala.html`, { waitUntil: "domcontentloaded" });
  await pgS.waitForFunction(() => document.querySelectorAll("#sbChats .sb-chat").length > 0, { timeout: 20000 });
  await sleep(900);
  const sensible = await pgS.evaluate(() => ({
    parcheado: typeof sbChatMotivoRoto === "undefined" ? null : true,
    rotas: document.querySelectorAll("#sbChats .sb-chat.roto").length,
    total: document.querySelectorAll("#sbChats .sb-chat").length,
  })).catch(() => null);
  const sinGuard = await pgS.evaluate(() => document.querySelectorAll("#sbChats .sb-chat.roto").length);
  ok(sinGuard === 0, "§8.1 sin el guard, NINGUNA fila se marca — §2 se pondría rojo",
     `rotas=${sinGuard} de ${(sensible || {}).total}`);
  const abrible = await pgS.evaluate(() => {
    const b = [...document.querySelectorAll("#sbChats .sb-chat")].filter((x) => !x.disabled);
    return b.length;
  });
  // el total incluye el hilo que nació en §5 — se compara contra lo que hay en ESTA página
  const totalS = (sensible || {}).total;
  ok(abrible === totalS && totalS >= 6, "§8.2 …y el hilo ilegible pasaría por abrible (el bug que §2 impide)",
     `abribles=${abrible}/${totalS}`);

  console.log(`\n${"═".repeat(72)}`);
  console.log(FALLOS.length ? `ROJO — ${PASS} verdes, ${FALLOS.length} fallos:` : `VERDE — ${PASS}/${PASS}`);
  FALLOS.forEach((f) => console.log(`   ✗ ${f}`));
} catch (e) {
  console.error("\n✗ LA VARA SE CAYÓ:", e && e.stack ? e.stack : e);
  FALLOS.push("la vara se cayó: " + (e && e.message));
} finally {
  try { if (browser) await browser.close(); } catch (e) {}
  await matar();
  try { fs.rmSync(DATADIR, { recursive: true, force: true }); } catch (e) {}
}
process.exit(FALLOS.length ? 1 : 0);
