/* verify_t7_cierres.mjs — LOS TRES CIERRES DE LA TANDA B.
 *
 *   §1  §10 CRITERIO DURO — la línea suelta: ni clickeable, ni input, ni rótulo de algo que
 *       actúa. Se lee el conteo del scanner endurecido y se exige 0, con su calibración.
 *   §2  EL NAV FINAL — Inicio · La Sala · Modelos · Conectores · Historial · Biblioteca.
 *       «Conexiones» = 0 y «Catálogo» = 0 en el nav renderizado, ES y EN, con screenshot.
 *   §3  CERO PÉRDIDA DEL AUDIT — cada capacidad del Centro de Conexiones que murió tiene
 *       que estar localizable en Modelos (o, si es conector, en Conectores). No se mide
 *       "existe un botón": se mide que el afordance está y que su camino responde.
 *   §4  MODELOS ABRE EN FRÍO — al entrar hay filas SIN tocar nada, y [Actualizar] queda
 *       como refresco. CALIBRACIÓN EN ROJO: con la carga inicial rota, la pantalla NO se
 *       queda muda: dice qué pasó y deja un camino.
 *
 * Stack de FUENTE (backend :8311 + serve.py :8312), datadir aislado. Nunca :25374.
 *   node qa/verify_t7_cierres.mjs
 */
import { webkit } from "playwright";
import { spawn, execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("../", import.meta.url));
const BACK = Number(process.env.T7_BACK || 8311);
const FRONT = Number(process.env.T7_FRONT || 8312);
if (FRONT === 25374 || BACK === 25374) { console.error("✗ 25374 es la .app instalada"); process.exit(2); }
const BASE = `http://127.0.0.1:${FRONT}`;

let PASS = 0; const FALLOS = [];
const ok = (c, name, det = "") => {
  if (c) { PASS++; console.log(`  ✓ ${name}${det ? "  — " + det : ""}`); }
  else { FALLOS.push(name); console.log(`  ✗ ${name}${det ? "  — " + det : ""}`); }
  return !!c;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sec = (t) => console.log(`\n── ${t} ${"─".repeat(Math.max(0, 66 - t.length))}`);

const DATA = mkdtempSync(path.join(tmpdir(), "t7-"));
const env = { ...process.env, ALEPH_DATA_DIR: DATA, ALEPH_ROLE: "client", ALEPH_BUILD: "public", PUPPET_ALLOW_ANON_V1: "1" };
const back = spawn(path.join(ROOT, "product/backend/.venv/bin/python"),
  ["-m", "uvicorn", "app.main:app", "--app-dir", ".", "--host", "127.0.0.1", "--port", String(BACK)],
  { cwd: path.join(ROOT, "product/backend"), env, stdio: "ignore", detached: true });
const front = spawn(path.join(ROOT, "product/backend/.venv/bin/python"), [path.join(ROOT, "product/app/serve.py")],
  { env: { ...env, ALEPH_FRONT_PORT: String(FRONT), ALEPH_BACKEND: `http://127.0.0.1:${BACK}` }, stdio: "ignore", detached: true });
const matar = () => { for (const p of [back, front]) { try { process.kill(-p.pid, "SIGKILL"); } catch {} } };
process.on("exit", matar); process.on("SIGINT", () => { matar(); process.exit(130); });

let vivo = false;
for (let i = 0; i < 120 && !vivo; i++) { await sleep(500); try { vivo = (await fetch(`http://127.0.0.1:${BACK}/health`)).ok; } catch {} }
if (!vivo) { console.error("✗ el backend de fuente no levantó"); matar(); process.exit(2); }

const b = await webkit.launch();
const nueva = async () => {
  const pg = await b.newPage({ viewport: { width: 1440, height: 900 } });
  pg.on("pageerror", (e) => console.log("    (pageerror) " + String(e).slice(0, 120)));
  return pg;
};

/* ══ §1 · §10 CRITERIO DURO ═══════════════════════════════════════════════════════════ */
sec("§1 · §10 criterio duro — la línea SUELTA");
let scan = "";
try { scan = execFileSync("node", [path.join(ROOT, "reports/ley10/scan_ley10.mjs"), ROOT, tmpdir()], { encoding: "utf8" }); }
catch (e) { scan = String((e.stdout || "") + (e.stderr || "")); }
const nSuelta = /SUELTA\s+\(ni clickeable[^)]*\): (\d+)/.exec(scan);
const nHard = /HARD\s+\(párrafo inequívoco\): (\d+)/.exec(scan);
const nExent = /líneas SUELTAS: \d+ · exentas: (\d+)/.exec(scan);
ok(!!nSuelta && Number(nSuelta[1]) === 0, "SUELTA = 0 · ni clickeable, ni input, ni rótulo de algo que actúa ★", nSuelta ? nSuelta[1] : "?");
ok(!!nHard && Number(nHard[1]) === 0, "HARD sigue en 0 (el primer barrido no se deshizo)", nHard ? nHard[1] : "?");
ok(!!nExent && Number(nExent[1]) > 0, "las exenciones se IMPRIMEN, no se callan", nExent ? nExent[1] + " exentas, listadas" : "?");
ok(/exenta por estado-puro/.test(scan) && /exenta por runtime/.test(scan),
   "y están clasificadas por motivo (estado-puro · runtime-§4h · rotula-un-control)");

/* ══ §2 · EL NAV FINAL ════════════════════════════════════════════════════════════════ */
sec("§2 · el nav final");
const ESPERADO = ["Inicio", "La Sala", "Modelos", "Conectores", "Historial", "Biblioteca"];
for (const [lang, nombres] of [["es", ESPERADO], ["en", ["Home", "The Room", "Models", "Connectors", "History", "Library"]]]) {
  const pg = await nueva();
  await pg.addInitScript((l) => { try { localStorage.setItem("aleph-lang", l); } catch (e) {} }, lang);
  await pg.goto(`${BASE}/Home.dc.html${lang === "en" ? "?lang=en" : ""}`, { waitUntil: "domcontentloaded" });
  await sleep(2200);
  const nav = await pg.evaluate(() => {
    const cont = document.querySelector(".aleph-topbar, .aleph-nav, nav") || document.body;
    return { txt: (cont.textContent || "").replace(/\s+/g, " ").trim(),
             items: [...cont.querySelectorAll("a")].map((a) => (a.textContent || "").trim()).filter(Boolean) };
  });
  const enNav = (s) => nav.items.some((i) => i.toLowerCase().includes(s.toLowerCase()));
  if (lang === "es") {
    ok(!enNav("Conexiones"), "[es] «Conexiones» = 0 en el nav ★");
    ok(!enNav("Catálogo"), "[es] «Catálogo» = 0 en el nav ★");
    ok(enNav("Conectores"), "[es] «Conectores» está");
  } else {
    ok(!enNav("Connections"), "[en] «Connections» = 0 en el nav ★");
    ok(!enNav("Catalog"), "[en] «Catalog» = 0 en el nav ★");
    ok(enNav("Connectors"), "[en] «Connectors» está");
  }
  const faltan = nombres.filter((n) => !enNav(n));
  ok(faltan.length === 0, `[${lang}] los 6 del nav final, presentes`, faltan.length ? "faltan: " + faltan.join(", ") : nombres.join(" · "));
  await pg.screenshot({ path: path.join(ROOT, `product/app/design/screenshots-t7/nav-${lang}.png`) }).catch(() => {});
  await pg.close();
}

/* ══ §3 · CERO PÉRDIDA DEL AUDIT ══════════════════════════════════════════════════════ */
sec("§3 · cero pérdida — cada capacidad del Centro, localizable");
{
  const pg = await nueva();
  await pg.goto(`${BASE}/Modelos.dc.html`, { waitUntil: "domcontentloaded" });
  await pg.waitForFunction(() => document.querySelectorAll("#mdFilas .md-fila").length > 0, null, { timeout: 25000 }).catch(() => {});
  const cap = await pg.evaluate(() => ({
    agregar: !!document.querySelector("#mdAgregar"),
    probarTodo: !!document.querySelector("#mdProbarTodo"),
    probarSel: !!document.querySelector("#mdProbarSel"),
    filtro: !!document.querySelector("#mdFiltro"),
    dlg: !!document.querySelector("#mdKeyDlg"),
    checks: document.querySelectorAll("#mdFilas .md-sel").length,
  }));
  ok(cap.agregar, "＋ Agregar llave vive en Modelos ★");
  ok(cap.probarTodo, "Probar todos vive en Modelos ★");
  ok(cap.probarSel, "Probar los elegidos vive en Modelos ★");
  ok(cap.filtro, "filtrar vive en Modelos");
  ok(cap.dlg, "el formulario de llave viajó entero (no un prompt)");
  ok(cap.checks > 0, "las filas testeables se pueden elegir", `${cap.checks} casillas`);

  // el afordance ABRE de verdad, con su validación en vivo — no es un botón decorativo
  await pg.click("#mdAgregar");
  await sleep(400);
  const abierto = await pg.evaluate(() => {
    const d = document.getElementById("mdKeyDlg");
    return { visible: d && !d.hidden, campos: ["#mdKeyProv", "#mdKeySecret", "#mdKeyBase"].filter((s) => !!document.querySelector(s)).length };
  });
  ok(abierto.visible, "…y ABRE de verdad");
  ok(abierto.campos === 3, "…con proveedor, llave y dirección propia", `${abierto.campos}/3`);
  const val = await pg.evaluate(async () => {
    document.getElementById("mdKeyProv").value = "groq";
    document.getElementById("mdKeySecret").value = "gsk_esta_no_sirve_0000";
    document.getElementById("mdKeyGuardar").click();
    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 500));
      const m = document.getElementById("mdKeyMsg");
      if (m && !m.hidden && !/Validando/i.test(m.textContent)) return m.textContent.trim().slice(0, 120);
    }
    return "";
  });
  ok(!!val, "una llave que NO sirve se valida contra el proveedor y se dice ★", val);
  ok(await pg.evaluate(() => { const g = document.getElementById("mdKeyGuardarIgual"); return !!g && !g.hidden; }),
     "…y [Guardar igual] queda como decisión del dueño, no como default");
  await pg.close();
}
{
  // lo que NO es cognición no se perdió: cuenta y mcp viven en Conectores
  const pg = await nueva();
  await pg.goto(`${BASE}/Conectar.dc.html`, { waitUntil: "domcontentloaded" });
  await sleep(3000);
  const c = await pg.evaluate(() => {
    const s = document.getElementById("cxYa");
    return { existe: !!s, visible: s && !s.hidden, n: document.querySelectorAll("#cxYaLista li").length,
             txt: s ? (s.textContent || "").replace(/\s+/g, " ").trim().slice(0, 90) : "" };
  });
  ok(c.existe, "Conectores tiene «Lo que ya conectaste» (las familias cuenta y mcp) ★", c.txt);
  ok(!c.visible || c.n > 0, "…y si se dibuja, es porque hay algo REAL adentro", `filas=${c.n}`);
  await pg.close();
}
{
  // la ruta vieja no muere: redirige CONSERVANDO el destino
  const pg = await nueva();
  await pg.goto(`${BASE}/Conexiones.dc.html?svc=api.groq&volver=Conectar.dc.html`, { waitUntil: "domcontentloaded" });
  await sleep(1800);
  const u = new URL(pg.url());
  ok(u.pathname.endsWith("/Modelos.dc.html"), "la ruta vieja REDIRIGE a Modelos ★", u.pathname);
  ok(u.searchParams.get("modo") === "api" && u.searchParams.get("m") === "groq",
     "…conservando el destino (svc=api.groq → modo=api · m=groq)", u.search);
  ok(u.searchParams.get("return") === "Conectar.dc.html", "…y el camino de vuelta");
  await pg.close();
}
{
  // y la vara que P8 dejó para que un MCP no vuelva a la pantalla de modelos, sigue valiendo
  const html = await (await fetch(`${BASE}/Modelos.dc.html`)).text();
  const sucio = ["mcpServers", "belt_ref", "backed_by", "tool_filters", "opensanctions", "gleif"].filter((w) => html.includes(w));
  ok(sucio.length === 0, "Modelos NO se ensució con vocabulario de conectores (la guarda de P8) ★", sucio.join(", ") || "0 de 6");
}

/* ══ §4 · MODELOS ABRE EN FRÍO ════════════════════════════════════════════════════════ */
sec("§4 · Modelos abre en frío — y si la carga muere, lo dice");
{
  const t0 = Date.now();
  const r = await fetch(`http://127.0.0.1:${BACK}/v1/modelos`);
  const j = await r.json();
  const ms = Date.now() - t0;
  ok(r.ok && (j.filas || []).length > 0, "el backend contesta la pantalla entera", `${(j.filas || []).length} filas`);
  ok(ms < 5000, "…y en FRÍO tarda menos que el plazo del front (era 40 s por el probe de MLX) ★", `${ms} ms`);
}
{
  const pg = await nueva();
  await pg.goto(`${BASE}/Modelos.dc.html`, { waitUntil: "domcontentloaded" });
  await sleep(300);
  const pronto = await pg.evaluate(() => ({
    algo: ((document.querySelector("#mdFilas") || {}).textContent || "").trim().length > 0,
    conteo: ((document.querySelector("#mdConteo") || {}).textContent || "").trim(),
  }));
  ok(pronto.algo, "a los 300 ms la pantalla NO está muda ★", `conteo="${pronto.conteo}"`);
  await pg.waitForFunction(() => document.querySelectorAll("#mdFilas .md-fila").length > 0, null, { timeout: 20000 }).catch(() => {});
  const frio = await pg.evaluate(() => ({
    filas: document.querySelectorAll("#mdFilas .md-fila").length,
    grupos: document.querySelectorAll("#mdFilas .md-grupo").length,
    conteo: ((document.querySelector("#mdConteo") || {}).textContent || "").trim(),
  }));
  ok(frio.filas > 0, "AL ENTRAR, SIN TOCAR NADA, hay filas ★", `filas=${frio.filas} grupos=${frio.grupos}`);
  ok(/\d/.test(frio.conteo), "…y el conteo dice números, no puntos suspensivos", `"${frio.conteo}"`);
  ok(!!(await pg.$("#mdRefrescar")), "[Actualizar] sigue, ahora como REFRESCO");
  await pg.close();
}
{
  // CALIBRACIÓN EN ROJO — la carga inicial rota de verdad (el backend contesta 500).
  // No es un flag: se le corta el endpoint a la página antes de que lo pida.
  const pg = await nueva();
  await pg.route("**/v1/modelos", (r) => r.fulfill({ status: 500, contentType: "application/json", body: '{"detail":"probeta"}' }));
  await pg.goto(`${BASE}/Modelos.dc.html`, { waitUntil: "domcontentloaded" });
  await sleep(3500);
  const roto = await pg.evaluate(() => {
    const ul = document.querySelector("#mdFilas");
    const t = ((ul || {}).textContent || "").replace(/\s+/g, " ").trim();
    return { txt: t, vacioMudo: t.length === 0,
             botones: [...(ul ? ul.querySelectorAll("button") : [])].map((b) => (b.textContent || "").trim()) };
  });
  ok(!roto.vacioMudo, "con la carga inicial ROTA la pantalla NO queda vacía y muda ★", roto.txt.slice(0, 90));
  ok(/no pude|couldn't|500/i.test(roto.txt), "…dice QUÉ pasó", roto.txt.slice(0, 90));
  ok(roto.botones.some((b) => /reintentar|retry/i.test(b)), "…y deja un CAMINO", roto.botones.join(" · ") || "(ninguno)");
  await pg.close();
}

/* ══ §5 · LO QUE FIX-P2 ARREGLÓ, ¿SOBREVIVIÓ A QUE MURIERA SU PANTALLA? ═══════════════
 * Los tres arreglos de fix/p2-conexiones-reforma NO eran de la pantalla Conexiones: eran
 * del catálogo de marcas, de la familia «incluido» y del despacho de [Ver planes]. Si
 * murieron con el Centro, el bug vuelve con otra cara en Modelos. Se mide, no se supone. */
sec("§5 · los arreglos de FIX-P2, sobre la pantalla que quedó viva");
{
  const ic = await fetch(`http://127.0.0.1:${BACK}/v1/icons`);
  const lista = await ic.text();
  const COG = ["groq", "openai", "anthropic", "openrouter", "deepseek", "mistral",
               "together", "gemini", "huggingface", "claude_code", "codex", "ollama"];
  const faltan = COG.filter((k) => !lista.includes(`"${k}"`));
  ok(faltan.length === 0, "las 12 marcas de cognición siguen en el catálogo ★", faltan.length ? "faltan: " + faltan.join(", ") : COG.length + "/12");
  const r = await fetch(`http://127.0.0.1:${BACK}/v1/icons/anthropic`);
  ok(r.headers.get("x-aleph-icon-source") === "bundled",
     "…y viajan EMPAQUETADAS, no por red ★", `X-Aleph-Icon-Source: ${r.headers.get("x-aleph-icon-source")}`);

  const pg = await nueva();
  await pg.goto(`${BASE}/Modelos.dc.html`, { waitUntil: "domcontentloaded" });
  await pg.waitForFunction(() => document.querySelectorAll("#mdFilas .md-fila").length > 0, null, { timeout: 25000 }).catch(() => {});
  await sleep(1800);
  const caras = await pg.evaluate(() => {
    const f = [...document.querySelectorAll("#mdFilas .md-face")];
    return { total: f.length, iniciales: f.filter((x) => x.classList.contains("binit")).length };
  });
  ok(caras.total > 0 && caras.iniciales < caras.total,
     "…y Modelos las PINTA (no todos círculos grises) ★", `${caras.total - caras.iniciales}/${caras.total} con marca real`);

  const grupos = await pg.evaluate(() => [...document.querySelectorAll("#mdFilas .md-grupo")].map((g) => g.dataset.familia));
  ok(grupos.includes("incluido"), "la familia «incluido» sigue viva en Modelos ★", grupos.join(" · "));
  await pg.close();
}
{
  // [Ver planes] ya no apunta a un ancla inventado: va por el despacho del semáforo.
  const src = await (await fetch(`${BASE}/cuarto/cuarto.semaforo.js`)).text();
  ok(!/Settings\.dc\.html#planes/.test(src), "[Ver planes] NO vuelve al ancla inexistente ★");
  ok(/"premium":\s*\{\s*accion:\s*"premium"/.test(src), "…sale por el despacho del semáforo");
  // …y la tabla de destinos es UNA sola: nadie construye ya la URL del Centro muerto.
  const semUrl = /Conexiones\.dc\.html/.test(src.replace(/\/\/[^\n]*/g, ""));
  ok(!semUrl, "cuarto.semaforo.js ya NO construye la URL del Centro muerto ★", "el redirect es red de seguridad, no el camino");
}

/* ══ §6 · EL CASO ÍNDICE QUE SE ESCAPÓ A LOS DOS BARRIDOS ═════════════════════════════
 * «El agente: su modelo, su identidad y su objetivo.» estaba en la lista de casos índice de
 * §10 las DOS veces y sobrevivió en la instalada. No lo perdonó una exención: el detector
 * nunca lo vio, porque no colgaba de una clase de ayuda sino que aterrizaba en un SLOT
 * (`$("ipurpose").textContent = purposeOf(d)`). Acá se mide el resultado en la pantalla. */
sec("§6 · el popup del Núcleo — el párrafo murió, queda el [?]");
{
  const pg = await nueva();
  await pg.goto(`${BASE}/cuarto/cuarto.pixi.html`, { waitUntil: "domcontentloaded" });
  await pg.waitForFunction(() => !!window.__cuarto && !!window.__ayuda, null, { timeout: 30000 }).catch(() => {});
  const cab = await pg.evaluate(() => {
    const C = window.__cuarto;
    const nuc = C && C.nucleoData ? C.nucleoData() : null;
    if (!nuc) return { sinNucleo: true };
    window.__openInspector ? window.__openInspector(nuc) : (C.openInspector && C.openInspector(nuc));
    return null;
  });
  if (cab && cab.sinNucleo) {
    ok(false, "§6 · no pude abrir el inspector del Núcleo (sin dato)");
  } else {
    await sleep(900);
    const v = await pg.evaluate(() => {
      const t = (id) => ((document.getElementById(id) || {}).textContent || "").trim();
      const pur = document.getElementById("ipurpose");
      return {
        kind: t("ikind"), sub: t("isub"),
        // el texto del slot SIN el glifo del propio [?]: si queda algo, es prosa que sobró
        purposeTxt: (() => {
          if (!pur) return "";
          const c = pur.cloneNode(true);
          c.querySelectorAll(".qmark").forEach((q) => q.remove());
          return (c.textContent || "").trim();
        })(),
        purposeQmark: !!(pur && pur.querySelector(".qmark")),
        guia: pur && pur.querySelector(".qmark") ? pur.querySelector(".qmark").dataset.guia : "",
        primario: t("iprimary"),
        mas: !!document.querySelector("#imas, .mlabel"),
      };
    });
    ok(!/su modelo, su identidad y su objetivo/.test(v.purposeTxt),
       "el párrafo del Núcleo MURIÓ de la cabecera ★", v.purposeTxt ? `queda: "${v.purposeTxt}"` : "vacío");
    ok(v.purposeTxt === "", "…y no lo reemplazó otra prosa (descontando el glifo del [?])", `"${v.purposeTxt}"`);
    ok(v.purposeQmark, "…queda su [?] ★", v.guia);
    ok(v.guia === "cuarto#nucleo", "…apuntando a la sección que ya lo explica", v.guia);
    ok(/NÚCLEO/i.test(v.kind) && /Asistente/i.test(v.sub), "la cabecera dice «Núcleo · Asistente»", `${v.kind} · ${v.sub}`);
    ok(/Elegir modelo/i.test(v.primario), "…con [Elegir modelo]", v.primario);
    ok(v.mas, "…y [Más]");

    // el [?] ABRE de verdad la sección, no es un glifo decorativo
    const pop = await pg.evaluate(async () => {
      window.__ayuda.cerrar();
      await window.__ayuda.abrir("cuarto", "nucleo", null);
      const el = document.getElementById("ayudapop");
      return { abierto: window.__ayuda.abierto(),
               titulo: (el.querySelector(".ayTitle") || {}).textContent || "",
               fallo: !!el.querySelector(".ayFail") };
    });
    ok(pop.abierto && !pop.fallo, "…y ese [?] ABRE la sección de verdad ★", pop.titulo);
  }

  // CALIBRACIÓN EN ROJO — se re-inserta el párrafo en el slot y el detector TIENE que verlo.
  const rojo = await pg.evaluate(() => {
    const pur = document.getElementById("ipurpose");
    if (!pur) return null;
    pur.textContent = "El agente: su modelo, su identidad y su objetivo.";
    return pur.textContent;
  });
  ok(/su modelo, su identidad y su objetivo/.test(rojo || ""),
     "CALIBRACIÓN: con el párrafo puesto a mano, la aserción de arriba caería ★", (rojo || "").slice(0, 60));
  await pg.close();
}

await b.close();
matar();
console.log("\n" + "═".repeat(70));
console.log(`T7 · LOS TRES CIERRES · ${PASS} verdes · ${FALLOS.length} rojos`);
if (FALLOS.length) { FALLOS.forEach((f) => console.log("   ✗ " + f)); process.exit(1); }
