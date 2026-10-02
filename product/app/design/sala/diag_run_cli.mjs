/* diag_run_cli.mjs — H2: con Claude Code SANO y elegido (el caso REAL del humano),
 * ¿el turno llega a correr? Traza cada request/response con tiempos, 150s de ventana.
 * Run: node diag_run_cli.mjs
 */
import { webkit } from "playwright";

const BASE = process.env.SALA_BASE || "http://127.0.0.1:8201";
const PAGE = `${BASE}/sala/sala.html`;
const WAIT = Number(process.env.WAIT_MS || 150000);

const browser = await webkit.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 860 } });
const t0 = Date.now();
const ms = () => String(Date.now() - t0).padStart(6);
const open = new Map();

page.on("pageerror", (e) => console.log(`${ms()}  PAGEERROR ${String(e).slice(0, 160)}`));
page.on("request", (r) => {
  if (!r.url().includes("/v1/")) return;
  open.set(r, Date.now());
  console.log(`${ms()}  → ${r.method()} ${r.url().replace(BASE, "")}`);
});
page.on("response", async (r) => {
  if (!r.url().includes("/v1/")) return;
  const st = open.get(r.request()); open.delete(r.request());
  let body = "";
  try { body = (await r.text()).replace(/\s+/g, " ").slice(0, 220); } catch { body = "<stream/ilegible>"; }
  console.log(`${ms()}  ← ${r.status()} ${r.url().replace(BASE, "")} (${st ? Date.now() - st : "?"}ms) ${body}`);
});
page.on("requestfailed", (r) => {
  if (!r.url().includes("/v1/")) return;
  console.log(`${ms()}  ✗ FALLÓ ${r.method()} ${r.url().replace(BASE, "")} — ${r.failure()?.errorText}`);
});

await page.addInitScript(`try{
  sessionStorage.setItem("puppet_user", JSON.stringify({id:"u-diag",session_token:"tok-diag",email:"diag@aleph"}));
  localStorage.setItem("aleph-active-brain","claude_cli");
  localStorage.setItem("aleph-brain-configuration", JSON.stringify({version:1,mode:"cli",id:"claude_cli",cliModel:""}));
}catch(e){}`);

console.log("══ H2 — TURNO REAL con Claude Code sano (sidecar frozen 8201) ══");
await page.goto(PAGE, { waitUntil: "domcontentloaded", timeout: 30000 });
await page.waitForTimeout(5000);
console.log(`${ms()}  boot listo. send.disabled=${await page.evaluate(() => document.getElementById("send").disabled)}`);

await page.click("#composer");
await page.keyboard.type("cuanto es 2+2? responde solo el numero", { delay: 6 });
console.log(`${ms()}  ENVIANDO…`);
await page.click("#send");

const deadline = Date.now() + WAIT;
let last = "";
while (Date.now() < deadline) {
  await page.waitForTimeout(5000);
  const snap = await page.evaluate(() => {
    const box = document.querySelector(".chat-scroll");
    return {
      n: box ? box.children.length : -1,
      txt: box ? Array.from(box.children).map((x) => (x.textContent || "").trim().slice(0, 90)).join(" | ") : "",
      busy: document.getElementById("send")?.disabled,
    };
  });
  const line = `n=${snap.n} busy=${snap.busy} :: ${snap.txt}`;
  if (line !== last) { console.log(`${ms()}  CHAT ${line}`); last = line; }
  if (snap.n >= 2 && !snap.busy) { console.log(`${ms()}  ✓ turno CERRADO`); break; }
}
console.log(`${ms()}  FIN de ventana (${WAIT}ms)`);
const openLeft = [...open.keys()].map((r) => r.method() + " " + r.url().replace(BASE, ""));
console.log("requests SIN respuesta al cerrar:", openLeft.length ? openLeft : "ninguno");
await browser.close();
