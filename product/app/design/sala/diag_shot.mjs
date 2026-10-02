/* diag_shot.mjs — cómo SE VE La Sala en el estado por defecto (lane incluida caída).
 * Mide el composer y saca foto. Run: node diag_shot.mjs
 */
import { webkit } from "playwright";
const BASE = process.env.SALA_BASE || "http://127.0.0.1:8201";
if (!process.env.OUT_DIR) throw new Error("Set OUT_DIR to an isolated diagnostic directory");
const OUT = process.env.OUT_DIR;
const browser = await webkit.launch();
for (const [name, w, h] of [["wide", 1440, 900], ["narrow", 1000, 720]]) {
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  await page.goto(`${BASE}/sala/sala.html`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(5000);
  const m = await page.evaluate(() => {
    const c = document.getElementById("composer"), b = c && c.closest(".box"), s = document.getElementById("send");
    const r = (el) => { const x = el && el.getBoundingClientRect(); return x ? { w: Math.round(x.width), h: Math.round(x.height), x: Math.round(x.left) } : null; };
    return { composer: r(c), box: r(b), send: r(s), sendDisabled: s ? s.disabled : null,
             pills: document.querySelectorAll(".composer .pill, .composer .atbtn").length };
  });
  console.log(`${name} ${w}x${h}:`, JSON.stringify(m));
  await page.screenshot({ path: `${OUT}/sala-${name}.png`, fullPage: false });
  await page.close();
}
await browser.close();
console.log("fotos en", OUT);
