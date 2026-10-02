/* diag_brain_gate.mjs — H1 (parte 2): ¿POR QUÉ canSend() es false?
 * Resuelve AlephBrain.resolve() VERBATIM para cada selección posible contra el
 * SIDECAR FROZEN (8201) y prueba el camino ENTER (que sí llama submit()).
 * Run: node diag_brain_gate.mjs
 */
import { webkit } from "playwright";

const BASE = process.env.SALA_BASE || "http://127.0.0.1:8201";
const PAGE = `${BASE}/sala/sala.html`;
const browser = await webkit.launch();

async function scenario(name, seed) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 860 } });
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e).slice(0, 160)));
  if (seed) await page.addInitScript(seed);
  await page.goto(PAGE, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForTimeout(5000);

  const res = await page.evaluate(async () => {
    const st = window.AlephBrain ? await window.AlephBrain.resolve({ refresh: true }) : null;
    const s = document.getElementById("send");
    const chip = document.getElementById("brainState");
    const sub = document.getElementById("agentSub");
    return {
      resolved: st ? { active: st.active, id: st.id, state: st.state, blockExecution: st.blockExecution, detail: String(st.detail || "").slice(0, 110), model: st.model } : null,
      send_disabled: s ? s.disabled : null,
      send_title: s ? s.title : null,
      chip_text: chip ? (chip.textContent || "").replace(/\s+/g, " ").trim().slice(0, 130) : null,
      agentSub: sub ? (sub.textContent || "").trim().slice(0, 90) : null,
    };
  });

  // camino ENTER: submit() SÍ se invoca (el botón disabled no lo hace)
  await page.click("#composer").catch(() => {});
  await page.keyboard.type("prueba enter", { delay: 8 });
  const reqs = [];
  page.on("request", (r) => { if (r.url().includes("/v1/")) reqs.push(r.method() + " " + r.url().replace(BASE, "").slice(0, 60)); });
  await page.keyboard.press("Enter");
  await page.waitForTimeout(4500);
  const after = await page.evaluate(() => {
    const box = document.querySelector(".chat-scroll");
    return {
      burbujas: box ? Array.from(box.children).map((n) => (n.textContent || "").trim().slice(0, 110)) : "<sin .chat-scroll>",
      composer: (document.getElementById("composer") || {}).value,
      url: location.pathname + location.search,
    };
  });

  console.log(`\n══ ${name} ══`);
  console.log("  resolve():", JSON.stringify(res.resolved));
  console.log("  send.disabled:", res.send_disabled, "| title:", res.send_title);
  console.log("  chip:", res.chip_text);
  console.log("  agentSub:", res.agentSub);
  console.log("  ── ENTER →");
  console.log("    requests /v1:", reqs.length ? reqs : "NINGUNO");
  console.log("    burbujas:", JSON.stringify(after.burbujas));
  console.log("    composer quedó:", JSON.stringify(after.composer));
  console.log("    url:", after.url);
  if (errs.length) console.log("  errores:", errs);
  await page.close();
  return res;
}

const SESSION = `try{ sessionStorage.setItem("puppet_user", JSON.stringify({id:"u-diag",session_token:"tok-diag",email:"diag@aleph"})); }catch(e){}`;

console.log("══ H1·2 — ¿POR QUÉ EL GATE BLOQUEA? (sidecar frozen 8201) ══");
await scenario("A · PERFIL LIMPIO (sin cerebro elegido) + sesión", SESSION);
await scenario("B · CLAUDE CODE elegido (lo del humano) + sesión",
  SESSION + `try{ localStorage.setItem("aleph-active-brain","claude_cli"); localStorage.setItem("aleph-brain-configuration", JSON.stringify({version:1,mode:"cli",id:"claude_cli",cliModel:""})); }catch(e){}`);
await scenario("C · INCLUIDO elegido explícitamente + sesión",
  SESSION + `try{ localStorage.setItem("aleph-active-brain","included"); localStorage.setItem("aleph-brain-configuration", JSON.stringify({version:1,mode:"included",id:"included"})); }catch(e){}`);
await scenario("D · PERFIL LIMPIO **SIN** sesión (lo que ve un usuario nuevo)", null);

await browser.close();
