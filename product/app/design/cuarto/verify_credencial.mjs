/* verify_credencial.mjs — Feature 6 · widget de credencial-guía (paridad reel + honestidad de auth).
 * El widget se rinde POR auth_method del onboarding object (/v1/connectors/{name}):
 *   TOKEN   → deep-link a la página de KEYS + guía 2-3 pasos + campo password + Validar 🟢/🔴 + trust.
 *   KEYLESS → switch on/off · SIN campo de key · link informativo (no de keys) · "no requiere key".
 *   OAUTH   → botón "Conectar con {Servicio}" · SIN campo de key.
 * SEGURIDAD (asserts duros):
 *   · el campo es type=password · la key viaja SOLO en el body del POST (creds keyed por field id) ·
 *     se LIMPIA del DOM tras validar · NUNCA aparece en textContent/atributos · deep-link con rel=noopener.
 * Puerto :8156. onboarding + connect mockeados (probamos el WIDGET, no el connect_engine real).
 * Run: node verify_credencial.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync, existsSync } from "node:fs";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
// los connector JSONs REALES (repo-root/catalog/…) — el harness los sirve tal cual → prueba el contenido enviado.
const CATALOG = join(HERE, "..", "..", "..", "..", "catalog", "connectors", "onboarding");
const PORT = 8156;
const PAGE = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const fails = [];
const ok = (c, label, extra) => { console.log(`${c ? "✓" : "✗"} ${label}${extra ? "  · " + extra : ""}`); if (!c) fails.push(label); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let lastConnectBody = null;
const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await sleep(700);
const browser = await chromium.launch();
try {
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 }, deviceScaleFactor: 1 });
  await context.addInitScript(() => { try { localStorage.setItem("aleph-lang", "en"); localStorage.setItem("aleph-theme", "dark"); } catch (e) {} });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.route("**/v1/**", (r) => {
    const u = r.request().url();
    const m = u.match(/\/v1\/connectors\/([^/?]+)\/connect/);
    if (m) { lastConnectBody = r.request().postData(); return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ state: "connected", message: "conectado" }) }); }
    const g = u.match(/\/v1\/connectors\/([^/?]+)$/);
    // 404 con body JSON (como FastAPI) — el widget NO debe parsearlo como descriptor válido (Fix 4).
    if (g && g[1] === "ghost404") return r.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "conector no encontrado" }) });
    // servir el connector JSON REAL desde disco → el harness prueba el contenido bilingüe enviado.
    if (g) { const fp = join(CATALOG, g[1] + ".json"); if (existsSync(fp)) return r.fulfill({ status: 200, contentType: "application/json", body: readFileSync(fp, "utf-8") }); }
    return r.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.goto(PAGE, { waitUntil: "load" });
  // __inspectAndEquip se asigna al FINAL del init (después de `let curPiece`): garantiza módulo listo.
  await page.waitForFunction(() => window.__cuarto && window.__openInspector && window.__inspectAndEquip, null, { timeout: 12000 });

  const openConn = async (tool) => {
    await page.evaluate((t) => {
      const c = window.__cuarto;
      c.placeTile(t);
      const d = c.pieceData(t.id);
      window.__openInspector(d);
      // [T3 · Calma] el inspector abre COLAPSADO (nivel 1); el widget de credencial vive en el
      // nivel 2 (Opciones) → revelar el detalle antes de interactuar con él.
      if (window.__setInspectorExpanded) window.__setInspectorExpanded(true);
    }, tool);
    // el widget vive en la pestaña "Opciones" (d-opts) — activarla para que sea visible/interactuable
    await page.click('#inspector .tab[data-d="opts"]').catch(() => {});
    await sleep(400); // wireConnect fetch + render
    return page.evaluate(() => {
      const box = document.querySelector("#d-opts .connect");
      if (!box) return { none: true };
      return {
        html: box.innerHTML,
        text: box.textContent,
        hasKeyField: !!box.querySelector('input.ckey[type="password"]'),
        hasSwitch: !!box.querySelector(".ctoggle"),
        deepHref: (box.querySelector("a.cdeep") || {}).href || "",
        deepText: (box.querySelector("a.cdeep") || {}).textContent || "",
        deepRel: (box.querySelector("a.cdeep") || {}).getAttribute?.("rel") || "",
        isInfoLink: !!box.querySelector("a.cdeep.info"),
        hasGuide: !!box.querySelector("ol.cguide"),
        guideSteps: box.querySelectorAll("ol.cguide li").length,
        oauthBtn: (box.querySelector("button.coauth") || {}).textContent || "",
        keylessLabel: !!box.querySelector(".ckeyless"),
        validateBtn: [...box.querySelectorAll("button")].some((b) => /Validar|Validate/.test(b.textContent)),
        guideLinks: [...box.querySelectorAll(".clinks a")].map((a) => ({ href: a.href, rel: a.getAttribute("rel") })),
        trustText: (box.querySelector(".ctrust") || {}).textContent || "",
        guideText: (box.querySelector("ol.cguide") || {}).textContent || "",
        placeholder: (box.querySelector("input.ckey") || {}).placeholder || "",
      };
    });
  };

  // ── (a) TOKEN mode (github) ──
  const tk = await openConn({ id: "cg-gh", label: "GitHub", category: "write", atom: "tool", server: "github", connector: "github", auth: "personal_token", connectable: true, tools: ["create_or_update_file"] });
  ok(!tk.none && tk.hasKeyField && tk.hasGuide && tk.guideSteps >= 2 && tk.validateBtn && !tk.hasSwitch,
     "(a) TOKEN: deep-link + guía(≥2) + campo password + Validar, sin switch", `steps=${tk.guideSteps}`);
  ok(tk.deepHref === "https://github.com/settings/personal-access-tokens/new" && /key/i.test(tk.deepText),
     "(a2) deep-link apunta a la página de KEYS + copy '…key'", tk.deepHref);

  // ── (j) BILINGÜE bajo lang=en: guía+trust del overlay `en`, CERO español ──
  const SPANISH_MARK = /token se guarda|cifrado|lo quitas|genera uno nuevo|necesitas|Banco Mundial|pega tu/i;
  ok(/stored encrypted/i.test(tk.trustText) && /Fine-grained token/.test(tk.guideText) && !SPANISH_MARK.test(tk.trustText + " " + tk.guideText),
     "(j) EN: guía+trust en inglés (overlay `en`), sin español", JSON.stringify(tk.trustText));
  // (j2) placeholder del campo en inglés (overlay en.credential_fields) — sin el " o " español
  ok(/or ghp_/.test(tk.placeholder) && !/ o ghp_/.test(tk.placeholder),
     "(j2) EN: placeholder del campo en inglés ('or', no 'o')", JSON.stringify(tk.placeholder));

  // ── (d) deep-link safety ──
  ok(tk.deepHref.startsWith("https://") && /noopener/.test(tk.deepRel),
     "(d) deep-link seguro: https + rel=noopener", `rel="${tk.deepRel}"`);

  // ── (d2) UN solo link-guía Aleph (Vercel), https + noopener ──
  ok(tk.guideLinks.length === 1 && tk.guideLinks[0].href === "https://aleph-site-jade.vercel.app/" && /noopener/.test(tk.guideLinks[0].rel || ""),
     "(d2) 1 link-guía Aleph (Vercel) · https + noopener", JSON.stringify(tk.guideLinks));

  // ── (m) TOKEN sin deep-link (hubspot: la página real necesita portal_id → no linkeable) ──
  //     regla: mejor SIN link + guía en texto que un link roto. El campo y la guía siguen.
  const hub = await openConn({ id: "cg-hub", label: "HubSpot", category: "write", atom: "tool", server: "hubspot", connector: "hubspot", auth: "personal_token", connectable: true, tools: ["x"] });
  ok(!hub.none && hub.hasKeyField && hub.hasGuide && hub.deepHref === "" && !hub.isInfoLink,
     "(m) token sin deep-link → campo + guía, SIN link roto (hubspot)", `deepHref='${hub.deepHref}' guía=${hub.guideSteps}`);

  // ── (b) KEYLESS mode (worldbank) ──
  const kl = await openConn({ id: "cg-wb", label: "World Bank", category: "read", atom: "tool", server: "worldbank", connector: "worldbank", auth: "keyless", connectable: true, tools: ["get_series"] });
  ok(!kl.none && !kl.hasKeyField && kl.hasSwitch && kl.keylessLabel,
     "(b) KEYLESS: switch + 'sin credencial', SIN campo de key", `keyField=${kl.hasKeyField}`);
  ok(kl.isInfoLink && !/key/i.test(kl.deepText || "") && !/get your key|obtené tu key/i.test(kl.deepText || ""),
     "(b2) el link keyless es INFORMATIVO (no 'get your key', no página de keys)", JSON.stringify(kl.deepText));
  // (b2-i18n) bajo EN el link informativo dice 'What is …', no 'Qué es …' (span aislado, Fix review #2)
  ok(/What is/.test(kl.deepText || "") && !/Qué es/.test(kl.deepText || ""),
     "(b2-i18n) info-link keyless en inglés ('What is'), sin Spanglish", JSON.stringify(kl.deepText));
  // (b3) el switch keyless POSTea con la clave `creds` (aunque vacía) — sin ella el backend da 422 (Fix review #1)
  lastConnectBody = null;
  await page.click("#d-opts .connect .ctoggle button[data-con='on']").catch(() => {});
  await sleep(250);
  ok(lastConnectBody !== null && "creds" in JSON.parse(lastConnectBody),
     "(b3) el connect keyless manda body con clave 'creds' (no 422)", lastConnectBody);

  // ── (c) OAUTH mode (gmail) ──
  const oa = await openConn({ id: "cg-gm", label: "Gmail", category: "send", atom: "tool", server: "gmail", connector: "gmail", auth: "oauth", connectable: true, tools: ["send"] });
  ok(!oa.none && !oa.hasKeyField && /Conectar con Gmail|Connect with Gmail/.test(oa.oauthBtn) && !oa.hasSwitch,
     "(c) OAUTH: botón 'Conectar con Gmail', SIN campo de key", JSON.stringify(oa.oauthBtn));
  // (c2) el botón OAuth POSTea con la clave `creds` (aunque vacía) — sin ella el redirect nunca arranca (Fix review #1)
  lastConnectBody = null;
  await page.click("#d-opts .connect button.coauth").catch(() => {});
  await sleep(250);
  ok(lastConnectBody !== null && "creds" in JSON.parse(lastConnectBody),
     "(c2) el connect OAuth manda body con clave 'creds' (no 422)", lastConnectBody);

  // ── (i) info 404 → estado de error, NO se rinde como keyless (Fix review #4) ──
  const g404 = await openConn({ id: "cg-404", label: "Ghost", category: "read", atom: "tool", server: "ghost404", connector: "ghost404", auth: "token", connectable: true, tools: ["x"] });
  ok(!g404.none && !g404.hasSwitch && !g404.hasKeyField && /no pude leer|couldn|could not/i.test(g404.text || ""),
     "(i) info 404 → error honesto, NO switch keyless", JSON.stringify((g404.text || "").slice(0, 40)));

  // ── (e)+(f) SEGURIDAD: la key viaja en body, se limpia del DOM, no queda en texto/atributos ──
  // reabrir github, escribir key, validar
  await openConn({ id: "cg-gh2", label: "GitHub", category: "write", atom: "tool", server: "github", connector: "github", auth: "personal_token", connectable: true, tools: ["create_or_update_file"] });
  const FAKE = "github_pat_SECRET_TESTKEY_zzz999";
  await page.fill("#d-opts .connect input.ckey", FAKE);
  await page.click("#d-opts .connect button:has-text('Validar'), #d-opts .connect button:has-text('Validate')");
  await sleep(300);
  const sec = await page.evaluate((fake) => {
    const box = document.querySelector("#d-opts .connect");
    const field = box.querySelector("input.ckey");
    // ¿el string de la key aparece en algún texto visible o atributo del widget?
    const inText = box.textContent.includes(fake);
    let inAttr = false;
    box.querySelectorAll("*").forEach((el) => { for (const a of el.attributes) if (a.value.includes(fake)) inAttr = true; });
    return { fieldValueAfter: field ? field.value : "(sin campo)", isPassword: field ? field.type === "password" : false, inText, inAttr, statGood: !!box.querySelector(".cstat.good") };
  }, FAKE);
  ok(sec.isPassword, "(e1) el campo es type=password", `type ok`);
  ok(lastConnectBody && JSON.parse(lastConnectBody).creds && JSON.parse(lastConnectBody).creds.token === FAKE,
     "(f) creds en el body keyed por field id (creds.token), no hardcode", lastConnectBody ? "body ok" : "sin body");
  ok(sec.fieldValueAfter === "" && sec.statGood,
     "(e2) tras validar OK: key LIMPIADA del campo + estado 🟢", `val='${sec.fieldValueAfter}'`);
  ok(!sec.inText && !sec.inAttr,
     "(e3) la key NUNCA aparece en texto/atributos del DOM del widget", `inText=${sec.inText} inAttr=${sec.inAttr}`);

  // ── (g) EN gate: el widget habla inglés (TM) ──
  await sleep(200);
  const en = await page.evaluate(() => {
    const box = document.querySelector("#d-opts .connect");
    return { validate: [...box.querySelectorAll("button")].map((b) => b.textContent).join("|"), lang: document.documentElement.getAttribute("lang") };
  });
  ok(en.lang === "en" && /Validate/.test(en.validate), "(g) EN gate: botón 'Validate'", en.validate);

  ok(errors.length === 0, "(h) 0 errores JS/render", errors.slice(0, 2).join(" ; "));

  // ── (k) FALLBACK ES: flip lang→es, re-abrir github → contenido en español (overlay `en` NO usado) ──
  // wireConnect lee AlephI18n.lang() en cada render → basta flipear localStorage (sin recargar).
  await page.evaluate(() => { try { localStorage.setItem("aleph-lang", "es"); } catch (e) {} });
  const es = await openConn({ id: "cg-es", label: "GitHub", category: "write", atom: "tool", server: "github", connector: "github", auth: "personal_token", connectable: true, tools: ["create_or_update_file"] });
  ok(/token se guarda cifrado/i.test(es.trustText) && !/stored encrypted/i.test(es.trustText),
     "(k) ES: mismo servicio en español (fallback, sin overlay en)", JSON.stringify(es.trustText));
  await page.evaluate(() => { try { localStorage.setItem("aleph-lang", "en"); } catch (e) {} });

  // captura para paridad visual (modo TOKEN, github)
  await openConn({ id: "cg-shot", label: "GitHub", category: "write", atom: "tool", server: "github", connector: "github", auth: "personal_token", connectable: true, tools: ["create_or_update_file"] });
  await page.screenshot({ path: join(HERE, "screenshots", "credencial-token-dark.png") });
} catch (e) {
  console.error("HARNESS ERROR:", e); fails.push(`harness: ${e && e.message ? e.message : String(e)}`);
} finally {
  await browser.close(); server.kill();
}
console.log("");
if (fails.length === 0) { console.log("RESULTADO: VERDE — credencial-guía (3 modos por auth · deep-link a keys · guía · validación 🟢/🔴 · key nunca al DOM)"); process.exit(0); }
console.log(`RESULTADO: ROJO (${fails.length})`); fails.forEach((f) => console.log(" - " + f)); process.exit(1);
