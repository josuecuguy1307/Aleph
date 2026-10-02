/* verify_inmersion_nivel2.mjs — LA INMERSIÓN NIVEL-2, MEDIDA EN LA PANTALLA.
 * [Gate 4 · Fase 4 · obra O3 · deudas 1 y 2 de la caminata de F3 · ley 3 · ley 3.8]
 *
 * QUÉ AFIRMA
 * ----------
 * Que entrar a un workspace se sienta UNA superficie y no dos pantallas pegadas:
 *
 *   1. **Cero localhost visible.** En el lienzo no aparece un `127.0.0.1:<puerto>` ni un
 *      `localhost`. Es la dirección de un proceso que Aleph levanta y apaga solo.
 *   2. **El tema cruza el borde de origen.** El lienzo corre en OTRO origen y no puede leer
 *      nuestro `localStorage`; la casa se lo manda. Se mide en las DOS direcciones (casa en
 *      oscuro y casa en claro) y contra los PÍXELES, no contra la intención: el fondo real
 *      del lienzo tiene que estar del mismo lado que el de la casa.
 *   3. **Cero pantallas intermedias.** Al entrar está el banco de trabajo, no el selector de
 *      proyectos del stack. El usuario ya eligió una vez, en la casa.
 *   4. **Cero marca ajena** en el texto que el usuario lee, y **cero errores de consola**.
 *   5. El cerebro que el workspace muestra es el de la casa.
 *
 * CÓMO SE MIDE
 * ------------
 * Contra el producto: backend real sirviendo la pantalla real, el pack levantando el
 * binario real, y un navegador de verdad. Se lee `innerText` —lo que el usuario LEE— y
 * `getComputedStyle` —lo que el usuario VE—, no propiedades del DOM que pueden mentir.
 * (Lección sellada: un `<iframe>` con un 404 adentro está perfectamente «visible».)
 *
 * Deja las capturas en `qa/screenshots/` para MIRARLAS, que es la otra mitad de la regla.
 *
 * PROBADA CAYENDO
 * ---------------
 *   --caer sin-ws     → no se le dice al lienzo que está adentro de Aleph: vuelven el
 *                       `127.0.0.1:<puerto>` y el selector de proyectos.
 *   --caer sin-tema   → no se le manda el tema: el lienzo sigue al sistema operativo y las
 *                       capas dejan de fundir.
 *
 *   node qa/verify_inmersion_nivel2.mjs
 */
import { chromium } from "playwright";
import { spawn, spawnSync } from "node:child_process";
import net from "node:net";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const RAIZ = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const CAPS = path.join(RAIZ, "qa/screenshots");
const CAER = (() => {
  const i = process.argv.indexOf("--caer");
  return i > 0 ? process.argv[i + 1] : "";
})();

const fallos = [];
const ok = (c, l, x = "") => {
  console.log(`${c ? "✓" : "✗"} ${l}${x ? "  " + x : ""}`);
  if (!c) fallos.push(l);
};

const libre = () =>
  new Promise((r) => {
    const s = net.createServer();
    s.listen(0, "127.0.0.1", () => {
      const p = s.address().port;
      s.close(() => r(p));
    });
  });

function pythonDelBackend() {
  for (const c of [
    path.join(RAIZ, "product/backend/.venv/bin/python"),
  ]) {
    if (fs.existsSync(c)) return c;
  }
  console.error("✗ no encontré el venv del backend");
  process.exit(2);
}

/** ¿El color es del lado oscuro? Se decide por LUMINANCIA, no por un nombre de token. */
function esOscuro(rgb) {
  const m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(rgb || "");
  if (!m) return null;
  const [r, g, b] = [Number(m[1]), Number(m[2]), Number(m[3])];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b < 128;
}

const DATOS = fs.mkdtempSync(path.join(os.tmpdir(), "f4-nivel2-"));
const PUERTO = await libre();
const BASE = `http://127.0.0.1:${PUERTO}`;
fs.mkdirSync(CAPS, { recursive: true });

const backend = spawn(
  pythonDelBackend(),
  ["-m", "uvicorn", "app.main:app", "--app-dir", path.join(RAIZ, "product/backend"),
   "--host", "127.0.0.1", "--port", String(PUERTO)],
  { stdio: "ignore", detached: true,
    env: { ...process.env, ALEPH_DATA_DIR: DATOS, ALEPH_ROLE: "client", ALEPH_ENV: "dev",
           PUPPET_ALLOW_ANON_V1: "1" } },
);

let arriba = false;
for (let i = 0; i < 60; i++) {
  await new Promise((r) => setTimeout(r, 1000));
  try {
    if ((await fetch(BASE + "/health")).ok) { arriba = true; break; }
  } catch { /* todavía no */ }
}
ok(arriba, "el backend real está en pie", BASE);

const nav = await chromium.launch();
try {
  for (const tema of ["dark", "light"]) {
    // El SISTEMA se deja en claro A PROPÓSITO en las dos pasadas: así, cuando la casa está
    // en oscuro, un lienzo que siga al sistema sale CLARO y el desajuste es visible. Con el
    // sistema acompañando al tema, la vara pasaría sin medir nada.
    const ctx = await nav.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "light" });
    await ctx.addInitScript((t) => {
      try { localStorage.setItem("aleph-theme", t); }
      catch (e) { /* sin storage, el tema queda en su default */ }
    }, tema);

    const pg = await ctx.newPage();
    const errores = [];
    pg.on("console", (m) => { if (m.type() === "error") errores.push(m.text().slice(0, 140)); });

    // ── EL SABOTAJE, EN EL NACIMIENTO DEL CABLE ─────────────────────────────────────
    // Se le quita el parámetro AL `src` DEL IFRAME, que es exactamente lo que la obra puso.
    //
    // ⚠️ DOS FORMAS QUE NO FUNCIONAN, y las dos dejaban la vara VERDE «probando» que el
    // defecto no existe (la trampa sellada del repo: una vara puede ser verde y no medir
    // nada):
    //   · `page.route("**/?aleph_ws=**")` — en el glob de Playwright `?` es un comodín de UN
    //     carácter, no el signo de pregunta de la query: la ruta jamás matcheaba.
    //   · `route.continue({ url })` — reescribe el PEDIDO, no la navegación: el documento
    //     que carga conserva su `location.search` original, que es justo lo que el lienzo
    //     lee. Se interceptaba (1 pedido, medido) y no cambiaba nada.
    // La que sí funciona es cambiar el `src` antes de que el navegador navegue.
    if (CAER === "sin-ws" || CAER === "sin-tema") {
      await pg.addInitScript((caer) => {
        const d = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, "src");
        Object.defineProperty(HTMLIFrameElement.prototype, "src", {
          ...d,
          set(v) {
            try {
              const u = new URL(v, location.href);
              if (caer === "sin-ws") { u.searchParams.delete("aleph_ws"); u.searchParams.delete("aleph_label"); }
              if (caer === "sin-tema") u.searchParams.delete("aleph_scheme");
              window.__saboteadas = (window.__saboteadas || 0) + 1;
              return d.set.call(this, u.toString());
            } catch (e) {
              return d.set.call(this, v);
            }
          },
        });
      }, CAER);
    }

    await pg.goto(`${BASE}/workspaces/ciencia.html`, { waitUntil: "domcontentloaded" });
    await pg.waitForTimeout(14000);
    await pg.screenshot({ path: path.join(CAPS, `inmersion-nivel2-${tema}.png`) });

    const marco = await pg.evaluate(() => getComputedStyle(document.body).backgroundColor);
    const lienzo = pg.frameLocator("#ws-frame");
    const texto = (await lienzo.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
    const fondo = await pg
      .frameLocator("#ws-frame")
      .locator("body")
      .evaluate((el) => {
        // Se sube hasta encontrar un fondo REALMENTE pintado: `body` puede ser transparente
        // y entonces lo que el usuario ve es el del `html`.
        for (let n = el; n; n = n.parentElement) {
          const c = getComputedStyle(n).backgroundColor;
          if (c && c !== "rgba(0, 0, 0, 0)" && c !== "transparent") return c;
        }
        return getComputedStyle(document.documentElement).backgroundColor;
      })
      .catch(() => "");

    console.log(`\n── la casa en ${tema} ──`);
    // La aplicación del sabotaje se AFIRMA, no se confía.
    if (CAER) {
      const n = await pg.evaluate(() => window.__saboteadas || 0).catch(() => 0);
      ok(n > 0, `el sabotaje «${CAER}» SE APLICÓ`, `${n} src reescrito/s`);
    }
    ok(await pg.locator("#ws-estado").innerText().then((t) => t.includes("vivo")).catch(() => false),
       "la barra de la casa dice que está en vivo");
    ok(texto.length > 40, "el lienzo tiene contenido de verdad", `${texto.length} chars`);

    // 1 · CERO LOCALHOST
    const localhost = texto.match(/127\.0\.0\.1(:\d+)?|localhost(:\d+)?/i);
    ok(!localhost, "cero localhost en lo que el usuario LEE", localhost ? `dice «${localhost[0]}»` : "");

    // 2 · EL TEMA CRUZA
    ok(esOscuro(marco) === (tema === "dark"), "el marco de la casa está en su tema", marco);
    ok(esOscuro(fondo) === esOscuro(marco),
       "y EL LIENZO ESTÁ DEL MISMO LADO — una superficie, no dos pantallas",
       `casa=${marco} · lienzo=${fondo}`);

    // 3 · CERO PANTALLAS INTERMEDIAS
    ok(!/Recent research, files, and sessions|Projects\s+\d/.test(texto),
       "cero pantalla intermedia: no aparece el selector de proyectos del stack");
    ok(/Terminal|Compute|Files/.test(texto),
       "y adentro está el banco de trabajo");

    // 4 · CERO MARCA AJENA · CERO ERRORES
    ok(!/openscience|synsci|synthetic\s*sciences/i.test(texto),
       "cero marca del proyecto de origen en el texto del lienzo");
    ok(errores.length === 0, "cero errores de consola", errores.slice(0, 2).join(" | "));

    // 5 · EL CEREBRO ES EL DE LA CASA
    ok(/Cerebro de Aleph/.test(texto), "el workspace dice con qué cerebro piensa");

    await ctx.close();
  }
} finally {
  await nav.close();
  try { process.kill(-backend.pid, "SIGTERM"); } catch { /* ya no está */ }
  spawnSync("pkill", ["-f", `ALEPH_DATA_DIR=${DATOS}`]);
  fs.rmSync(DATOS, { recursive: true, force: true });
}

console.log(`\ncapturas: ${CAPS}`);
console.log(fallos.length ? `\nROJAS: ${fallos.join(", ")}` : "\nVERDE");
process.exit(fallos.length ? 1 : 0);
