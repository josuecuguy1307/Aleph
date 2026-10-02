/* verify_modelos_v2.mjs — VARA · MODELOS V2 · BUSCAR vs CONFIGURAR.
 *
 * Esta vara no usa el sidecar del humano. Sirve la UI de fuente y un sidecar-fixture en
 * el puerto indicado por MODELOS_V2_PORT, cuenta el lote inicial y limpia todo al terminar.
 *
 * Corrida completa (toma el lock BSD de frozen por sí sola):
 *   node qa/verify_modelos_v2.mjs
 *
 * Contra un sidecar frozen de ESTA rama ya levantado en :8306:
 *   MODELOS_V2_FROZEN_URL=http://127.0.0.1:8306 MODELOS_V2_LOCK_HELD=1 \
 *     node qa/verify_modelos_v2.mjs
 *
 * Sólo contratos estáticos, sin servidor:
 *   node qa/verify_modelos_v2.mjs --static
 *
 * Calibración roja pedida: corta UN veredicto HF del lote. La corrida DEBE salir 1:
 *   MODELOS_V2_CALIBRATE_MISSING_VERDICT=1 node qa/verify_modelos_v2.mjs
 *
 * En macOS el equivalente de `flock` disponible es:
 *   /usr/bin/lockf -k /tmp/aleph-frozen.lock env MODELOS_V2_LOCK_HELD=1 \
 *     node qa/verify_modelos_v2.mjs
 */
import http from "node:http";
import { createRequire } from "node:module";
import { existsSync } from "node:fs";
import { mkdir, readFile } from "node:fs/promises";
import { dirname, extname, join, normalize } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = dirname(HERE);
const DESIGN = join(REPO, "product", "app", "design");
// ══ [H2] LAS CAPTURAS NO VAN AL ÁRBOL ═══════════════════════════════════════════════
// `qa/screenshots/modelos-v2-lista-constante.png` está COMMITEADO, y esta vara lo
// reescribía en cada corrida: medido el 2026-08-08 en la regresión de esta fase —
// 147.300 → 149.839 bytes, un `git status` sucio que no es trabajo de nadie.
// Es la misma clase que `frontera_d4_events.json`, y el mismo arreglo: la captura es
// EVIDENCIA de la corrida, así que va a un temporal; pisar la del árbol es un acto
// explícito, porque cambiar una captura de referencia es una decisión.
const CAPTURAS_AL_ARBOL = process.argv.includes("--capturas-al-arbol");
const SHOTS = CAPTURAS_AL_ARBOL ? join(HERE, "screenshots")
  : join(tmpdir(), `aleph-modelos-v2-${process.pid}`);
const SCRIPT = fileURLToPath(import.meta.url);
const LOCK = "/tmp/aleph-frozen.lock";
const PORT = Number(process.env.MODELOS_V2_PORT || 8306);
const FROZEN_URL = String(process.env.MODELOS_V2_FROZEN_URL || "").replace(/\/+$/, "");
const CALIBRATE_MISSING = process.env.MODELOS_V2_CALIBRATE_MISSING_VERDICT === "1";
const STATIC_ONLY = process.argv.includes("--static");

if (PORT === 25374) {
  console.error("✗ :25374 pertenece a la app del humano; la vara se niega a tocarlo");
  process.exit(2);
}
if (FROZEN_URL && FROZEN_URL !== `http://127.0.0.1:${PORT}`) {
  console.error(`✗ el frozen de esta vara debe vivir exactamente en http://127.0.0.1:${PORT}`);
  process.exit(2);
}

// Las corridas frozen de Step 5 se serializan con el lock BSD. La vara se re-ejecuta
// dentro de `lockf` para que invocarla a mano no dependa de recordar el prefijo.
if (!STATIC_ONLY && process.env.MODELOS_V2_LOCK_HELD !== "1" && existsSync("/usr/bin/lockf")) {
  const child = spawnSync("/usr/bin/lockf", [
    "-k", LOCK, "/usr/bin/env", "MODELOS_V2_LOCK_HELD=1",
    process.execPath, SCRIPT, ...process.argv.slice(2),
  ], { stdio: "inherit", env: process.env });
  process.exit(child.status == null ? 2 : child.status);
}

const failures = [];
let assertions = 0;
function ok(cond, label, extra = "") {
  assertions += 1;
  console.log(`${cond ? "✓" : "✗"} ${label}${extra ? " · " + String(extra).slice(0, 220) : ""}`);
  if (!cond) failures.push(label);
}
function section(label) {
  console.log(`\n── ${label} ${"─".repeat(Math.max(2, 74 - label.length))}`);
}

async function staticContracts() {
  section("0 · CONTRATOS ESTÁTICOS · P8 + P1B");
  const semUrl = pathToFileURL(join(DESIGN, "modelos", "modelos.semaforo.js")).href +
    `?vara=${Date.now()}`;
  const sem = await import(semUrl);
  const causas = ["sin_runtime", "sin_espacio", "descarga_cancelada", "formato_no_soportado"];
  for (const causa of causas) {
    ok(!!(sem.default.Sem.CAUSAS[causa] && sem.CAUSAS_MODELO[causa]),
      `P8: ${causa} vive en CAUSAS única y el adaptador sólo la deriva`);
    ok(!!sem.default.Sem.CAMINOS["roto/" + causa],
      `P8: roto/${causa} vive en CAMINOS único`);
  }
  const noPlan = sem.caminoModelo({ estado: "roto", causa: "modelo_no_disponible" });
  ok(noPlan && noPlan.es === "Elegir otro modelo",
    "P1B también rige en Modelos: fuera del plan → [Elegir otro modelo]",
    JSON.stringify(noPlan));

  const [html, ui, api] = await Promise.all([
    readFile(join(DESIGN, "Modelos.dc.html"), "utf8"),
    readFile(join(DESIGN, "modelos", "modelos.ui.js"), "utf8"),
    readFile(join(DESIGN, "modelos", "modelos.api.js"), "utf8"),
  ]);
  ok(/id="mdFilas"/.test(html) && !/data-origen="(cli|api|incluido)"/.test(html),
    "un solo host de lista; no sobreviven grupos/cards POR ORIGEN " +
    "(la aduana agrupa por TRÁMITE, que es otra cosa: dice qué te falta, no de dónde viene)");
  ok(/\.md-fila\{height:64px;min-height:64px/.test(html.replace(/\s/g, "")),
    "la regla CSS fija alto y min-height de cada fila");
  ok(/await cargar\(\)/.test(ui) && /listarV2/.test(ui),
    "Modelos carga desde el inicio; Actualizar queda como refresco");

  /* ══ [F8 · obra 0] NINGÚN `<input>` DENTRO DE UNA FILA DE LISTA ═══════════════════
   *
   * REGLA SELLADA POR PERSONA USUARIA (2026-08-07). El caso que la pagó: la fila de la aduana
   * renderizaba `<input type="password" class="md-llave">` y **no lo leía nadie** —
   * medido el 2026-08-07, `.md-llave` existía en su propio render y en el CSS, y en
   * ningún handler. Se podía tipear la llave entera ahí, apretar el botón de al lado, y
   * lo único que pasaba era abrirse el panel con el campo vacío y lo tipeado perdido.
   *
   * Una lista es para comparar y elegir. El momento de escribir tiene su lugar —el
   * panel— y es UNO solo. Dos campos para un trámite es cómo se llega a que sólo uno
   * esté conectado.
   *
   * El guard es ESTÁTICO (sobre la fuente del renderer) y además VIVO (sobre el DOM
   * pintado, más abajo): el estático caza la fila que hoy no se pinta en este fixture,
   * el vivo caza la que se cuele por otro camino. */
  const filas_src = await readFile(join(DESIGN, "modelos", "modelos.superficie.js"), "utf8");
  const cuerpoFilas = filas_src
    .replace(/\/\*[\s\S]*?\*\//g, "")            // sin comentarios de bloque
    .replace(/^\s*\/\/.*$/gm, "");                 // sin comentarios de línea
  ok(!/<input/i.test(cuerpoFilas),
    "★ [F8] ninguna fila de lista renderiza un `<input>` — el trámite pasa en el panel",
    (cuerpoFilas.match(/.{0,70}<input.{0,50}/i) || [])[0]);

  /* ══ [F8 · obra 3] UN SOLO COMPONENTE — NO UN QUINTO PICKER ═══════════════════════
   *
   * El pliego de la auditoría contó CUATRO catálogos de modelos conviviendo en la
   * plataforma. La orden de persona usuaria para esta obra fue explícita: **un solo componente
   * compartido entre Modelos y el Cuarto**. Un picker «propio del panel», aunque fuera
   * mejor, sería el quinto lugar donde la misma pregunta se responde distinto.
   *
   * El guard es estático porque el vivo no alcanza: una copia del renderer pintaría el
   * MISMO DOM y pasaría cualquier chequeo sobre la pantalla. Lo que se exige es que este
   * módulo NO tenga su propia plantilla de ítems y que DELEGUE en el componente. */
  const cuerpoUi = ui
    .replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  ok(/AlephModelSelector/.test(cuerpoUi) && /catalogoRender\(/.test(cuerpoUi),
    "★★ [F8] el panel DELEGA el catálogo en el componente compartido (`catalogoRender`)");
  ok(!/amc-item|class="amc-list"/.test(cuerpoUi),
    "★★ [F8] …y NO tiene su propia plantilla de ítems: cero pickers nuevos",
    (cuerpoUi.match(/.{0,60}amc-item.{0,40}/) || [])[0]);
  const cuerpoBrain = (await readFile(join(DESIGN, "brain-status.js"), "utf8"))
    .replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  ok(/catalogoHtml|catalogoRender/.test(cuerpoBrain) && /usarModelo/.test(cuerpoBrain),
    "★ y el componente compartido es quien lo pinta y quien escribe la elección");
  /* ⚠️ NINGÚN `<button>` DENTRO DE OTRO. La línea «usando X · [Cambiar]» se pinta TAMBIÉN
   * adentro de la fila del selector, que ya es un `<button>`. Un botón anidado es HTML
   * inválido: el navegador parte el externo y la fila entera deja de responder. Por eso
   * [Cambiar] es un `span[role=button]` — y por eso el guard vive acá y no en una revisión. */
  ok(/class="amc-cambiar" role="button" tabindex="0"/.test(cuerpoBrain),
    "★★ [F8] [Cambiar] es un `span[role=button]`, no un `<button>`: va dentro de la fila " +
    "del selector, que ya es uno — anidarlos rompe la fila entera");

  /* ══ [F7 · obra 4] LAS DOS REGLAS QUE ESTA VARA SE APLICA A SÍ MISMA ═══════════════
   *
   * Una vara que hornea el caso feliz y sintetiza el gesto que falta no mide el flujo:
   * mide su propio fixture. Las dos cosas pasaron acá y las dos se sellan por escrito. */
  // El patrón se ARMA por pedazos a propósito: si estuviera escrito entero, el guard se
  // cazaría a sí mismo al leer su propio archivo.
  const GESTO_SINTETICO = new RegExp("dispatch" + "Event\\(\\s*[\"']paste[\"']");
  const varasDeModelos = [SCRIPT,
    join(DESIGN, "modelos", "verify_modelos.mjs"),
    join(DESIGN, "modelos", "verify_modelos_p8_legacy.mjs")];
  const sintetizan = [];
  for (const v of varasDeModelos) {
    if (!existsSync(v)) continue;
    if (GESTO_SINTETICO.test(await readFile(v, "utf8"))) sintetizan.push(v.split("/").pop());
  }
  ok(sintetizan.length === 0,
    "★ ninguna vara de Modelos sintetiza el gesto de pegar: si una prueba tiene que " +
    "despachar el evento a mano para que el flujo ande, el flujo NO anda — " +
    "un humano no puede despachar eventos", sintetizan.join(", "));
  const yo = await readFile(SCRIPT, "utf8");
  ok(/estado:\s*"detectado"/.test(yo) && /causa:\s*"key_invalida"/.test(yo),
    "★ el stub de la llave contesta los TRES veredictos, no sólo el feliz: un backend " +
    "de mentira que sólo sabe decir «probado» hace imposible cazar un verde falso");

  /* ══ LA CADENA DE MONTAJE ═══════════════════════════════════════════════════════════
   * Medido el 2026-08-06: `modelos.superficie.js` y `modelos.widget.js` viajaban en el
   * bundle y NADIE los importaba. Existía el componente, no el camino. */
  ok(/modelos\.ui\.js/.test(html), "Modelos.dc.html monta `modelos.ui.js`");
  ok(/from "\.\/modelos\.superficie\.js"/.test(ui) && /from "\.\/modelos\.widget\.js"/.test(ui),
    "★ y el montaje IMPORTA el adaptador de F4c (superficie + widget): sin esto, las dos " +
    "capas viajan en el bundle y ningún click de la app llega a ellas");
  ok(/checklistEnVivo/.test(api) && /\/v1\/modelos\/checklist/.test(api),
    "★ y el checklist vivo de F4c tiene cliente: el endpoint existía con CERO llamadores");
  ok(/\/v1\/modelos\/v2/.test(api) && /T_LOTE/.test(api),
    "el cliente usa el endpoint batch documentado por su adaptador");
  ok(!/huggingface\.co\/api|api-inference\.huggingface/i.test(api),
    "el browser no consulta HF ni expone HF Inference API");

  for (const [file, label] of [
    ["verify_modelos.mjs", "el entrypoint canónico V2"],
    ["verify_modelos_p8_legacy.mjs", "la caminata histórica P8 de 125 aserciones"],
  ]) {
    const parsed = spawnSync(process.execPath, [
      "--check", join(DESIGN, "modelos", file),
    ], { encoding: "utf8" });
    ok(parsed.status === 0, `${label} sigue parseando`,
      (parsed.stderr || "").trim());
  }
}

await staticContracts();
if (STATIC_ONLY) {
  console.log(failures.length
    ? `\n✗ MODELOS V2 static: ${failures.length} falla(s) / ${assertions} aserciones`
    : `\n✓ MODELOS V2 static: ${assertions} aserciones verdes`);
  process.exit(failures.length ? 1 : 0);
}

/* [Vertical Sliding Focus · 2026-07-31] La lista de Modelos ya no es una grilla donde toda
 * fila tiene sus acciones a la vista: es una PISTA donde exactamente una está en foco. Las
 * acciones de las filas retrocedidas siguen en el DOM —para lectores de pantalla y para que
 * un submit programático funcione— pero con `pointer-events:none`, así que un click directo
 * de Playwright se queda esperando y da timeout.
 *
 * No es un bug: el patrón cambia cómo se ALCANZAN las acciones, no cuáles son. Un humano
 * hace exactamente esto — toca la fila, la fila se enfoca, y recién ahí toca el botón.
 * `elegirEn()` reproduce esos dos pasos. Devuelve el locator de la acción por si el caller
 * quiere seguir interrogándola.
 */
/* [F7 · obra 4] La acción de una fila depende de DÓNDE VIVE, y ésa es la obra: en «Tus
 * modelos» es `.md-elegir`; en la aduana es `.md-tramite` ([Guardar y probar] /
 * [Descargar] / [Iniciar sesión]). El helper toma la que la fila emita — pedir siempre
 * `.md-elegir` era suponer que todas las filas son iguales, que es justo lo que la
 * pertenencia deja de ser cierto. */
async function elegirEn(page, filaSel, accionSel = null) {
  const fila = page.locator(filaSel);
  await fila.waitFor({ state: "visible", timeout: 10000 });
  if (!accionSel) {
    // [F7] LA FILA ENTERA ABRE SU PANEL — `.md-fila` declaraba `cursor:pointer` desde
    // siempre y ningún click llegaba a ninguna parte. Si el click en la fila ya abrió el
    // panel, no hay segundo gesto que dar: pedirlo sería clickear un botón tapado por el
    // overlay, que es exactamente lo que hace un humano: nada.
    await fila.click();
    const abrio = await page.locator("#mdPanel").isVisible().catch(() => false);
    if (abrio) return page.locator("#mdPanelBody");
    accionSel = await fila.evaluate((el) =>
      el.querySelector(".md-elegir") ? ".md-elegir" : ".md-tramite");
  }
  // si ya está en foco no hace falta el primer click (y clickear dos veces abriría y cerraría)
  const enFoco = await fila.evaluate((el) => el.getAttribute("data-focus") === "1").catch(() => false);
  if (!enFoco) {
    await fila.click();                       // trae la fila al foco de la pista
    await page.waitForFunction(
      (sel) => { const e = document.querySelector(sel); return e && e.getAttribute("data-focus") === "1"; },
      filaSel, { timeout: 5000 },
    ).catch(() => {});                        // pantallas sin pista: el click ya alcanzó
  }
  const accion = fila.locator(accionSel);
  await accion.click();
  return accion;
}

function loadPlaywright() {
  const roots = [
    process.env.PLAYWRIGHT_PROJECT,
    REPO,
  ].filter(Boolean);
  for (const root of roots) {
    const pkg = join(root, "node_modules", "playwright", "package.json");
    if (!existsSync(pkg)) continue;
    const requireFromRoot = createRequire(join(root, "package.json"));
    return { api: requireFromRoot("playwright"), root };
  }
  throw new Error("Playwright no está disponible. Usá PLAYWRIGHT_PROJECT apuntando a un worktree que ya lo tenga; no hace falta instalar.");
}

const runtime = {
  batchRequests: 0,
  catalogRequests: 0,
  verdictRequests: 0,
  keyRequests: 0,
  cancelRequests: 0,
  preferenceWrites: [],
  apiComplete: false,
  // [F7] fuerza el veredicto que contesta el stub de la llave. Existe para poder medir el
  // camino AMARILLO —el backend guardó la llave y NO la pudo probar—, que es el que el
  // front convertía en verde leyendo `r.ok` en vez de `r.estado`.
  keyMode: null,
  downloadComplete: false,
  activeTimers: new Set(),
  // [F8 · obra 3] EL CATÁLOGO DEL PROVEEDOR. `modeloElegido` es el estado que el backend
  // guardaría; el fixture lo devuelve resuelto en `usando`/`elegido_por` igual que
  // `_modelo_de_api` — si el stub inventara otra regla, la vara mediría un backend que no
  // existe (que es exactamente lo que F7 encontró en el builder viejo).
  catalogoRequests: 0,
  modeloElegido: null,
  modeloWrites: [],
  // Fuerza el caso «hay llave y NO hay modelo»: el proveedor contesta pero su catálogo no
  // trae nada servible. Es la causa `modelo_no_elegido` que la obra 2 selló; sin este flag
  // la vara mediría sólo el camino feliz.
  catalogoSinModelo: false,
};

//: 4 modelos con la forma de §11 (`model_id · label · context · capacidades · free`).
//: `sin-tools-xl` existe a propósito: la obra 1 selló que «un cerebro sin tool-calling no
//: es un cerebro», y el picker tiene que DECIRLO antes de que alguien lo elija a mano.
const CATALOGO_FIXTURE = [
  { provider_id: "openai", model_id: "gpt-grande", label: "GPT grande",
    context: 128000, capacidades: ["texto", "tools", "razonamiento"], free: false },
  { provider_id: "openai", model_id: "gpt-chico", label: "GPT chico",
    context: 32000, capacidades: ["texto", "tools"], free: true },
  { provider_id: "openai", model_id: "sin-tools-xl", label: "Sin tools XL",
    context: 200000, capacidades: ["texto"], free: false },
  { provider_id: "openai", model_id: "gpt-medio", label: "GPT medio",
    context: 64000, capacidades: ["texto", "tools"], free: false },
];

/** El catálogo tal como lo devuelve `GET /v1/modelos/proveedor/{slug}/catalogo`.
 *  `usando`/`elegido_por` salen de la MISMA regla del backend: la elección del usuario
 *  gana si sigue viva; si no, el id declarado. */
function fixtureCatalogo(slug) {
  const elegido = runtime.modeloElegido;
  const vivo = elegido && CATALOGO_FIXTURE.some((m) => m.model_id === elegido);
  return {
    slug, ref: String(slug).split(".").pop(), label: "GPT API",
    modelos: CATALOGO_FIXTURE,
    usando: runtime.catalogoSinModelo ? null : (vivo ? elegido : "gpt-grande"),
    elegido_por: runtime.catalogoSinModelo ? "ninguno" : (vivo ? "usuario" : "declarado"),
    eleccion_del_usuario: vivo ? elegido : null,
    descubierto_en: "2026-08-07T10:00:00", fuente: "red", rancio: false, causa: null,
  };
}

const VERDICT_OK = {
  veredicto: "comodo", es: "Entra cómodo", en: "Fits comfortably",
  ram_pedida_gb: 5.3,
};
const VERDICT_NO = {
  veredicto: "no_entra", es: "No entra: te faltan 3.5 GB",
  en: "Does not fit: you need 3.5 GB more", ram_pedida_gb: 19.5, faltan_gb: 3.5,
};

/* ══ EL STUB DE LA LLAVE CONTESTA LOS TRES VEREDICTOS ═══════════════════════════════
 *
 * ⚠️ [F7 · obra 4] ANTES CONTESTABA UNO SOLO: `{ok:true, estado:"probado", guardada:true}`
 * para CUALQUIER llave. Con eso horneado, esta vara **no podía cazar el verde falso** que
 * la auditoría del 2026-08-06 midió — el verde era lo único que su backend sabía decir.
 * Un stub que sólo conoce el caso feliz no prueba un flujo: prueba el caso feliz.
 *
 * Los tres son los del backend real (`centro_conexiones.agregar_key`):
 *   · llave con forma equivocada / rechazada  → ok:false · roto · key_invalida · NO se guarda
 *   · proveedor sin validador conocido        → ok:true  · **detectado** · se guarda
 *   · llave que el proveedor acepta           → ok:true  · probado    · se guarda
 */
function veredictoDeLaLlave(body) {
  const provider = String((body || {}).provider || "");
  const secret = String((body || {}).secret || "");
  if (runtime.keyMode === "detectado" || provider === "sinvalidador") {
    return { ok: true, estado: "detectado", guardada: true, last4: secret.slice(-4),
             mensaje: `guardé tu llave de ${provider} cifrada, pero no la pude probar.` };
  }
  if (!/^sk-/.test(secret)) {
    return { ok: false, estado: "roto", causa: "key_invalida", guardada: false,
             mensaje: `${provider} rechazó la llave (401): no sirve. No la guardé.` };
  }
  return { ok: true, estado: "probado", guardada: true, last4: secret.slice(-4),
           prueba: "catalogo_autenticado", discriminante: true,
           mensaje: `${provider} aceptó tu llave y quedó guardada cifrada en tu máquina.` };
}

function fixtureV2() {
  const successVerdict = CALIBRATE_MISSING ? null : { ...VERDICT_OK };
  const filas = [
    {
      slug: "incluido.default-caido", familia: "incluido", origen: "incluido",
      ref: "cognicion", label: "Aleph incluido", marca: "aleph", tier: "frontier",
      estado: "roto", causa: "error_upstream", conectado: false, default: true,
      frontier: true, local: false, sub: "Ruta incluida de Aleph.",
    },
    {
      slug: "cli.claude", familia: "cli", origen: "cli",
      ref: "claude_cli", label: "Claude Code", marca: "anthropic", tier: "frontier",
      estado: "detectado", causa: null, conectado: true, frontier: true, local: false,
      sesion_cli: { installed: true, state: "ready", detail: "sesión activa · plan Max" },
      servicio_cli: { state: "ready", detail: "sidecar CLI listo" },
    },
    {
      slug: "api.openai", familia: "api", origen: "api",
      ref: "openai", label: "GPT API", marca: "openai", tier: "grande",
      estado: runtime.apiComplete ? "probado" : "no_configurado", causa: null,
      conectado: runtime.apiComplete, hay_llave: runtime.apiComplete,
      frontier: true, local: false,
      // [F7] el backend real emite `prueba` {estado, ts, detalle} para las filas API
      // (`centro_modelos._prueba_de`). Sin evidencia con fecha NO hay verde, y un fixture
      // que la omite mide una pantalla que no existe.
      prueba: runtime.apiComplete
        ? { estado: "probado", ts: Math.floor(Date.now() / 1000) - 5,
            detalle: "openai aceptó tu llave (200 en 140 ms)" }
        : null,
    },
    {
      slug: "hf.acme-success", familia: "local", origen: "hf_local",
      ref: "acme/vision-7B-GGUF", hf_id: "acme/vision-7B-GGUF",
      label: "Vision 7B GGUF", marca: "acme", tier: "medio",
      estado: runtime.downloadComplete ? "probado" : "detectado", causa: null,
      conectado: runtime.downloadComplete, frontier: false, hf: true,
      local: runtime.downloadComplete, instalado: runtime.downloadComplete,
      prueba: runtime.downloadComplete
        ? { estado: "probado", ts: Math.floor(Date.now() / 1000) - 5,
            detalle: "descargado y probado" }
        : null,
      categoria: "vision", categorias: ["vision"],
      archivo: "vision-q4.gguf", archivos: ["vision-q4.gguf"], formato: "gguf",
      cuantizacion: "Q4_K_M", peso_gb: 4, veredicto: successVerdict,
      url: "https://huggingface.co/acme/vision-7B-GGUF",
    },
    {
      slug: "hf.acme-cancel", familia: "local", origen: "hf_local",
      ref: "acme/code-3B-GGUF", hf_id: "acme/code-3B-GGUF",
      label: "Code 3B GGUF", marca: "acme", tier: "medio",
      estado: "detectado", causa: null, conectado: false, frontier: false, hf: true,
      local: false, categoria: "codigo", categorias: ["codigo"],
      archivo: "code-q4.gguf", archivos: ["code-q4.gguf"], formato: "gguf",
      cuantizacion: "Q4_K_M", peso_gb: 2.1, veredicto: { ...VERDICT_OK },
    },
    {
      slug: "hf.acme-too-big", familia: "local", origen: "hf_local",
      ref: "acme/big-70B-GGUF", hf_id: "acme/big-70B-GGUF",
      label: "Big 70B GGUF", marca: "acme", tier: "grande",
      estado: "detectado", causa: null, conectado: false, frontier: true, hf: true,
      local: false, categoria: "razonamiento", categorias: ["razonamiento"],
      archivo: "big-q4.gguf", archivos: ["big-q4.gguf"], formato: "gguf",
      cuantizacion: "Q4_K_M", peso_gb: 31, veredicto: { ...VERDICT_NO },
    },
    {
      slug: "local.ollama", familia: "local", origen: "hf_local",
      ref: "ollama/qwen3:8b", label: "Qwen3 8B local", marca: "ollama", tier: "medio",
      estado: "detectado", causa: null, conectado: false, frontier: false,
      hf: false, local: true, preexistente: true, categoria: "codigo",
      categorias: ["codigo"], sub: "Ya está en Ollama.",
    },
  ];
  const conectados = filas.filter((f) => f.conectado).map((f) => f.slug);
  return {
    filas,
    categorias: [
      { id: "vision", es: "Visión", en: "Vision" },
      { id: "codigo", es: "Código", en: "Code" },
      { id: "razonamiento", es: "Razonamiento", en: "Reasoning" },
    ],
    maquina: { disco_libre_gb: 12.4, ram_libre_gb: 10.7, ram_total_gb: 16 },
    preferencias: {
      version: 2, default: "incluido.default-caido",
      conectados, contextos: { sala: "cli.claude" },
    },
    conteo: { total: filas.length, hf: 3, conectados: conectados.length },
    contrato: {
      lote: true, requests_listado: 1,
      veredictos_en_fila: filas.filter((f) => f.hf).every((f) => !!f.veredicto),
    },
    hf: { red: true },
  };
}

const selectorFixture = {
  contexto: "sala",
  default: "incluido.default-caido",
  default_id: "included-dead",
  seleccion: "incluido.default-caido",
  seleccion_id: "included-dead",
  regla: "conectados+default",
  modelos: [
    {
      id: "included-dead", slug: "incluido.default-caido", label: "Aleph incluido",
      conectado: false, connected: false, default: true, frontier: true,
    },
    {
      id: "claude-live", slug: "cli.claude", label: "Claude Code",
      conectado: true, connected: true, default: false, frontier: true,
    },
    {
      id: "api-small", slug: "api.small", label: "API pequeña",
      conectado: true, connected: true, default: false, frontier: false,
      // [F8 · obra 3] la fila del selector lleva QUÉ MODELO usa y QUIÉN lo eligió — lo
      // emite `_selector_de`. Es lo que le permite al Cuarto decir «usando X» sin pedir
      // nada más y sin mantener una segunda tabla.
      familia: "api", model: "gpt-chico", modelo_elegido: "gpt-chico",
      modelo_elegido_por: "usuario",
    },
    {
      id: "stray", slug: "api.stray", label: "No conectada",
      conectado: false, connected: false, default: false, frontier: true,
    },
  ],
};

function fixtureSelector(contexto) {
  const data = structuredClone(selectorFixture);
  data.contexto = contexto;
  if (contexto === "guia") {
    data.modelos = data.modelos.filter((m) => m.frontier);
    data.regla = "conectados+default ∩ frontier";
  }
  return data;
}

function sseFixtureBody(events) {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
}

/** En modo frozen sólo interceptamos la API: HTML/JS/CSS salen del bundle PyInstaller.
 *  Esto mantiene deterministas los estados (incluido el Default caído) sin certificar
 *  accidentalmente los assets sueltos del worktree. */
async function installFrozenApiFixture(page) {
  await page.route("**/v1/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const method = req.method();
    const json = (body, status = 200) => route.fulfill({
      status, contentType: "application/json; charset=utf-8",
      headers: { "Cache-Control": "no-store" },
      body: JSON.stringify(body),
    });
    let body = {};
    try { body = req.postDataJSON() || {}; } catch {}

    if (url.pathname === "/v1/modelos/v2") {
      runtime.batchRequests += 1;
      return json(fixtureV2());
    }
    if (url.pathname === "/v1/modelos/catalogo") {
      runtime.catalogRequests += 1;
      return json({ red: true, modelos: [] });
    }
    if (url.pathname === "/v1/modelos/veredicto" || url.pathname === "/v1/modelos/maquina") {
      runtime.verdictRequests += 1;
      return json({});
    }
    if (url.pathname === "/v1/modelos/descargar" && method === "POST") {
      const cancelFlow = /code-3B/i.test(String(body.hf_id || ""));
      const events = [
        { tipo: "arranque", pct: 2, mb: 2, mb_total: 100, mbps: 8 },
        { tipo: "progreso", pct: 52, mb: 52, mb_total: 100, mbps: 10 },
      ];
      if (!cancelFlow) {
        events.push({ tipo: "probando" });
        runtime.downloadComplete = true;
        events.push({
          tipo: "fin", estado: "probado",
          detalle: "descargado y probado por la vara frozen",
        });
      }
      return route.fulfill({
        status: 200, contentType: "text/event-stream; charset=utf-8",
        headers: { "Cache-Control": "no-cache" },
        body: sseFixtureBody(events),
      });
    }
    if (url.pathname === "/v1/modelos/cancelar" && method === "POST") {
      runtime.cancelRequests += 1;
      return json({ cancelado: true, limpio: true });
    }
    if (url.pathname.startsWith("/v1/modelos/avatar/")) {
      return json({ cacheado: false });
    }
    // [F8 · obra 3] El catálogo de UN proveedor — el que el picker del panel consume.
    if (/^\/v1\/modelos\/proveedor\/[^/]+\/catalogo$/.test(url.pathname)) {
      runtime.catalogoRequests += 1;
      return json(fixtureCatalogo(decodeURIComponent(url.pathname.split("/")[4])));
    }
    if (url.pathname === "/v1/modelos/preferencias" && method === "PUT") {
      // [F8] DOS ESCRITURAS DISTINTAS POR LA MISMA PUERTA: `{contexto, seleccion}` elige la
      // VÍA para un contexto; `{slug, modelo}` elige el MODELO de un proveedor. El stub las
      // separa igual que el backend — mezclarlas haría pasar por verde un front que manda
      // el payload equivocado.
      if (Object.prototype.hasOwnProperty.call(body || {}, "modelo")) {
        runtime.modeloWrites.push(body);
        const pedido = String(body.modelo || "");
        if (pedido && !CATALOGO_FIXTURE.some((m) => m.model_id === pedido))
          return json({ detail: `«${pedido}» ya no está en el catálogo de openai.` }, 409);
        runtime.modeloElegido = pedido || null;
        return json({ ...fixtureV2().preferencias,
                      modelos: pedido ? { [body.slug]: pedido } : {} });
      }
      runtime.preferenceWrites.push(body);
      return json({
        ...fixtureV2().preferencias,
        contextos: {
          ...fixtureV2().preferencias.contextos,
          [body.contexto || "sala"]: body.seleccion,
        },
      });
    }
    if (url.pathname === "/v1/modelos/preferencias") return json(fixtureV2().preferencias);
    if (url.pathname === "/v1/modelos/selector") {
      return json(fixtureSelector(url.searchParams.get("contexto") || "default"));
    }
    if (url.pathname === "/v1/conexiones/key" && method === "POST") {
      runtime.keyRequests += 1;
      const r = veredictoDeLaLlave(body);
      if (r.estado === "probado") runtime.apiComplete = true;
      return json(r);
    }
    if (url.pathname === "/v1/auth/local") {
      return json({ id: "vara", session_token: "fixture-token" });
    }
    if (url.pathname === "/v1/brains/status") {
      return json({
        service: { state: "ready", detail: "fixture vivo" },
        providers: {
          included: { state: "unavailable", detail: "caída plantada" },
          claude_cli: {
            state: "ready", detail: "sesión activa",
            extra: { subscriptionType: "max" },
          },
          codex_cli: { state: "not_installed", detail: "fixture" },
        },
      });
    }
    return json({});
  });
}

const MIME = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml",
  ".png": "image/png", ".webp": "image/webp", ".woff2": "font/woff2",
};
function jsonResponse(res, body, status = 200) {
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
  res.end(JSON.stringify(body));
}
async function requestJson(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  try { return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}"); }
  catch { return {}; }
}
function sse(res, event) {
  try { res.write(`data: ${JSON.stringify(event)}\n\n`); } catch {}
}
function downloadFixture(req, res, body) {
  res.writeHead(200, {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache", Connection: "keep-alive",
  });
  const cancelFlow = /code-3B/i.test(String(body.hf_id || ""));
  sse(res, { tipo: "arranque", pct: 2, mb: 2, mb_total: 100, mbps: 8 });
  const timer = setTimeout(() => {
    runtime.activeTimers.delete(timer);
    if (res.destroyed || res.writableEnded) return;
    sse(res, { tipo: "progreso", pct: 52, mb: 52, mb_total: 100, mbps: 10 });
    if (cancelFlow) return;
    sse(res, { tipo: "probando" });
    runtime.downloadComplete = true;
    sse(res, { tipo: "fin", estado: "probado", detalle: "descargado y probado por la vara" });
    res.end();
  }, 90);
  runtime.activeTimers.add(timer);
  const clean = () => {
    if (!runtime.activeTimers.has(timer)) return;
    clearTimeout(timer);
    runtime.activeTimers.delete(timer);
  };
  req.on("close", clean);
  res.on("close", clean);
}

const server = http.createServer(async (req, res) => {
  req.on("error", () => {});
  res.on("error", () => {});
  const url = new URL(req.url || "/", `http://127.0.0.1:${PORT}`);
  if (url.pathname === "/health") return jsonResponse(res, { ok: true });
  if (url.pathname === "/v1/modelos/v2") {
    runtime.batchRequests += 1;
    return jsonResponse(res, fixtureV2());
  }
  if (url.pathname === "/v1/modelos/catalogo") {
    runtime.catalogRequests += 1;
    return jsonResponse(res, { red: true, modelos: [] });
  }
  if (url.pathname === "/v1/modelos/veredicto" || url.pathname === "/v1/modelos/maquina") {
    runtime.verdictRequests += 1;
    return jsonResponse(res, {});
  }
  if (url.pathname === "/v1/modelos/descargar" && req.method === "POST") {
    return downloadFixture(req, res, await requestJson(req));
  }
  if (url.pathname === "/v1/modelos/cancelar" && req.method === "POST") {
    runtime.cancelRequests += 1;
    return jsonResponse(res, { cancelado: true, limpio: true });
  }
  if (url.pathname.startsWith("/v1/modelos/avatar/")) {
    return jsonResponse(res, { cacheado: false });
  }
  // [F8 · obra 3] mismo par de rutas que el mock de la página — si divergen, la vara mide
  // un backend distinto según por dónde entre la request.
  if (/^\/v1\/modelos\/proveedor\/[^/]+\/catalogo$/.test(url.pathname)) {
    runtime.catalogoRequests += 1;
    return jsonResponse(res, fixtureCatalogo(decodeURIComponent(url.pathname.split("/")[4])));
  }
  if (url.pathname === "/v1/modelos/preferencias" && req.method === "PUT") {
    const body = await requestJson(req);
    if (Object.prototype.hasOwnProperty.call(body || {}, "modelo")) {
      runtime.modeloWrites.push(body);
      const pedido = String(body.modelo || "");
      if (pedido && !CATALOGO_FIXTURE.some((m) => m.model_id === pedido))
        return jsonResponse(res, { detail: `«${pedido}» ya no está en el catálogo de openai.` }, 409);
      runtime.modeloElegido = pedido || null;
      return jsonResponse(res, { ...fixtureV2().preferencias,
                                 modelos: pedido ? { [body.slug]: pedido } : {} });
    }
    runtime.preferenceWrites.push(body);
    return jsonResponse(res, {
      ...fixtureV2().preferencias,
      contextos: { ...fixtureV2().preferencias.contextos, [body.contexto || "sala"]: body.seleccion },
    });
  }
  if (url.pathname === "/v1/modelos/preferencias") {
    return jsonResponse(res, fixtureV2().preferencias);
  }
  if (url.pathname === "/v1/modelos/selector") {
    const contexto = url.searchParams.get("contexto") || "default";
    return jsonResponse(res, fixtureSelector(contexto));
  }
  if (url.pathname === "/v1/conexiones/key" && req.method === "POST") {
    runtime.keyRequests += 1;
    const r = veredictoDeLaLlave(await requestJson(req));
    if (r.estado === "probado") runtime.apiComplete = true;
    return jsonResponse(res, r);
  }
  if (url.pathname === "/v1/auth/local") {
    return jsonResponse(res, { id: "vara", session_token: "fixture-token" });
  }
  if (url.pathname === "/v1/brains/status") {
    return jsonResponse(res, {
      service: { state: "ready", detail: "fixture vivo" },
      providers: {
        included: { state: "unavailable", detail: "caída plantada" },
        claude_cli: { state: "ready", detail: "sesión activa", extra: { subscriptionType: "max" } },
        codex_cli: { state: "not_installed", detail: "fixture" },
      },
    });
  }
  if (url.pathname.startsWith("/v1/")) return jsonResponse(res, {});

  let rel;
  try { rel = decodeURIComponent(url.pathname).replace(/^\/+/, "") || "Modelos.dc.html"; }
  catch { res.writeHead(400); res.end("bad path"); return; }
  const file = normalize(join(DESIGN, rel));
  if (!file.startsWith(DESIGN + "/") && file !== DESIGN) {
    res.writeHead(403); res.end("forbidden"); return;
  }
  try {
    const body = await readFile(file);
    res.writeHead(200, {
      "Content-Type": MIME[extname(file)] || "application/octet-stream",
      "Cache-Control": "no-store",
    });
    res.end(body);
  } catch {
    res.writeHead(404); res.end("not found");
  }
});

let browser = null;
let page = null;
function stop() {
  for (const timer of runtime.activeTimers) clearTimeout(timer);
  runtime.activeTimers.clear();
  try { server.close(); } catch {}
}
for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) {
  process.once(sig, () => { stop(); process.exit(130); });
}

try {
  const pw = loadPlaywright();
  section("1 · ARRANQUE AISLADO");
  console.log(`· Playwright existente: ${pw.root}`);
  console.log(`· lock: ${LOCK}`);
  if (FROZEN_URL) {
    const health = await fetch(FROZEN_URL + "/health");
    ok(health.ok, "el sidecar frozen de esta rama responde en :8306");
    console.log(`· assets: frozen ${FROZEN_URL}`);
  } else {
    await new Promise((resolve, reject) => {
      server.once("error", reject);
      server.listen(PORT, "127.0.0.1", resolve);
    });
    console.log("· assets: fuente (modo rápido)");
  }
  const { webkit } = pw.api;
  browser = await webkit.launch();
  page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
  if (FROZEN_URL) await installFrozenApiFixture(page);
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(String(e && e.message || e)));
  await page.addInitScript(() => {
    sessionStorage.setItem("puppet_user", JSON.stringify({
      id: "vara", session_token: "fixture-token",
    }));
  });

  const batchBefore = runtime.batchRequests;
  await page.goto(`${FROZEN_URL || `http://127.0.0.1:${PORT}`}/Modelos.dc.html`,
    { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#mdFilas .md-fila");
  await page.waitForFunction(() => window.AlephModelosV2 && window.AlephModelosV2.estado().filas.length >= 7);

  section("2 · BUSCADOR · UNA LISTA, FILAS CONSTANTES, LOTE ÚNICO");
  const initial = await page.locator("#mdFilas .md-fila").evaluateAll((rows) => ({
    n: rows.length,
    /* [Vertical Sliding Focus] getBoundingClientRect() incluye el `transform: scale(.965)`
       con que la pista retrocede las filas que no están en foco, así que devolvía
       [64, 61.76, 61.76, …] — y 61.76 es exactamente 64 x 0.965. El alto de LAYOUT no
       cambió: lo que se mide acá es la caja pintada. offsetHeight ignora la
       transformación y es lo que esta aserción siempre quiso comprobar. */
    heights: rows.map((r) => r.offsetHeight),
    slugs: rows.map((r) => r.dataset.slug),
    expandedInside: rows.filter((r) => r.querySelector(".md-flow-card,[aria-expanded='true']")).length,
    overflowed: rows.filter((r) => r.scrollHeight > r.clientHeight + 1).length,
  }));
  ok(initial.n === 7, "N modelos aparecen desde el inicio en UNA lista", JSON.stringify(initial.slugs));
  ok(new Set(initial.heights.map((h) => h.toFixed(2))).size === 1 && initial.heights[0] === 64,
    "N filas tienen alto constante de 64 px", JSON.stringify(initial.heights));
  ok(initial.expandedInside === 0 && initial.overflowed === 0,
    "cero cards expandidas y cero contenido desbordado dentro de las filas");
  ok(await page.locator("#mdPanel").isHidden(), "el panel del elegido empieza cerrado");

  await mkdir(SHOTS, { recursive: true });
  const screenshotPath = join(SHOTS, CALIBRATE_MISSING
    ? "modelos-v2-calibracion-sin-veredicto.png"
    : "modelos-v2-lista-constante.png");
  await page.screenshot({ path: screenshotPath, fullPage: true });
  ok(existsSync(screenshotPath), "screenshot de la lista constante guardado", screenshotPath);

  const hfInline = await page.locator(".md-fila[data-origen='hf_local']").evaluateAll((rows) =>
    rows.filter((r) => r.dataset.slug.startsWith("hf.")).map((r) => {
      const verdict = r.querySelector(".md-veredicto-fila");
      return {
        slug: r.dataset.slug,
        text: (verdict && verdict.textContent || "").trim(),
        missing: !!(verdict && verdict.dataset.falta === "1"),
      };
    }));
  const missingVerdicts = hfInline.filter((r) =>
    r.missing || !/(entra cómodo|no entra: te faltan)/i.test(r.text));
  ok(hfInline.length === 3 && missingVerdicts.length === 0,
    "cada HF trae el veredicto inline sin abrirla (incluido el faltante exacto)",
    JSON.stringify(hfInline));
  ok(runtime.batchRequests - batchBefore === 1,
    "listar N=3 HF hace exactamente 1 request batch",
    `batch=${runtime.batchRequests - batchBefore}`);
  ok(runtime.catalogRequests === 0 && runtime.verdictRequests === 0,
    "el browser no hace requests HF/veredicto por fila",
    `catálogo=${runtime.catalogRequests}, veredicto=${runtime.verdictRequests}`);

  if (CALIBRATE_MISSING) {
    ok(failures.some((f) => /veredicto inline/.test(f)),
      "CALIBRACIÓN: cortar el dato vuelve roja la vara");
    throw new Error("calibración roja completada (fallo esperado)");
  }

  section("3 · SWITCHES REALES · FILTROS SIN CADÁVERES");
  async function switchTo(origin) {
    await page.locator(`#mdOrigen [data-origin="${origin}"]`).click();
    return await page.locator("#mdFilas .md-fila").evaluateAll((rows) =>
      rows.map((r) => ({ slug: r.dataset.slug, origin: r.dataset.origen })));
  }
  const cliRows = await switchTo("cli");
  ok(cliRows.length === 1 && cliRows.every((r) => r.origin === "cli"),
    "switch CLI filtra de verdad", JSON.stringify(cliRows));
  ok(await page.locator("#mdCategorias").isHidden() && await page.locator("#mdMaquina").isHidden(),
    "fuera de HF no se ven categorías ni barras de disco/RAM");
  const apiRows = await switchTo("api");
  ok(apiRows.length === 1 && apiRows.every((r) => r.origin === "api"),
    "switch API filtra de verdad", JSON.stringify(apiRows));
  ok(await page.locator("#mdCategorias").isHidden() && await page.locator("#mdMaquina").isHidden(),
    "API tampoco muestra filtros muertos");
  const hfRows = await switchTo("hf_local");
  ok(hfRows.length === 4 && hfRows.every((r) => r.origin === "hf_local"),
    "switch HF/local filtra de verdad", JSON.stringify(hfRows));
  ok(await page.locator("#mdCategorias").isVisible() && await page.locator("#mdMaquina").isVisible(),
    "categorías y disco/RAM viven sólo en HF/local");
  await page.locator("#mdCategorias [data-cat='vision']").click();
  const visionRows = await page.locator("#mdFilas .md-fila").evaluateAll((rows) => rows.map((r) => r.dataset.slug));
  ok(visionRows.length === 1 && visionRows[0] === "hf.acme-success",
    "el filtro de categoría también filtra de verdad", JSON.stringify(visionRows));
  const allRows = await switchTo("todos");
  ok(allRows.length === 7 && await page.locator("#mdCategorias").isHidden() &&
    await page.locator("#mdMaquina").isHidden(),
  "Todos restaura la lista y quita filtros/recursos exclusivos de HF");

  section("4 · PANEL DEL ELEGIDO · API Y CLI");
  await switchTo("api");
  await elegirEn(page, ".md-fila[data-slug='api.openai']");
  ok(await page.locator("#mdPanel").isVisible() && await page.locator("#mdFilas").isVisible(),
    "elegir abre overlay lateral y deja la lista atrás");
  ok(await page.locator("#mdApiKey").isVisible() &&
    await page.locator(".md-guardar").isVisible() &&
    /API con tu llave/i.test(await page.locator("#mdPanelBody").innerText()),
  "panel API completo: campo de llave + BOTÓN [Guardar y probar]");

  /* ⚠️ [F7 · obra 4] SE TIPEA Y SE APRIETA EL BOTÓN. Cero gestos sintetizados.
   *
   * La versión anterior hacía `fill()` y después despachaba el evento `paste` A MANO,
   * porque `fill()` no dispara nada — y el ÚNICO disparador del flujo era `onpaste`. Esa
   * línea era la confesión del bug: si una prueba tiene que sintetizar el gesto, el gesto
   * no existe para el usuario. El guard estático de la sección 0 ahora lo prohíbe. */
  const rojoAntes = runtime.keyRequests;
  await page.locator("#mdApiKey").fill("basura-que-no-es-una-llave");
  await page.locator(".md-guardar").click();
  await page.waitForSelector(".md-api-msg.bad");
  ok(runtime.keyRequests === rojoAntes + 1,
    "★ tipear y apretar [Guardar y probar] manda la llave (sin sintetizar ningún evento)");
  ok(/no sirve|rechaz/i.test(await page.locator(".md-api-msg").innerText()),
    "★ una llave que el proveedor rechaza sale ROJA con su causa, no verde");
  ok(await page.locator("#mdPanel").isVisible(),
    "…y el panel NO se cierra sobre un fallo: el usuario tiene que poder corregir");
  ok(await page.locator(".md-fila[data-slug='api.openai'][data-verde='1']").count() === 0,
    "★ y la fila NO queda verde");
  ok(await page.locator("#mdApiKey").isEnabled(),
    "el campo vuelve habilitado (antes sólo volvía en el camino de error del `catch`)");

  /* ★ EL CAMINO AMARILLO — el que el bug convertía en verde.
   * El backend contesta `ok:true` (la llamada salió bien, la llave se guardó) con
   * `estado:"detectado"` («no la sé validar directo»). Leyendo `r.ok` eso salía 🟢. */
  runtime.keyMode = "detectado";
  await page.locator("#mdApiKey").fill("sk-vara-sin-validador-000");
  await page.locator(".md-guardar").click();
  await page.waitForFunction(() => document.getElementById("mdPanel").hidden === true);
  ok(await page.locator(".md-fila[data-slug='api.openai'][data-verde='1']").count() === 0,
    "★★ un `ok:true` con estado `detectado` NO se pinta verde: el estado lo dice el " +
    "backend, y «la guardé pero no la pude probar» no es «anda»");
  ok(/no la pude probar|no la sé validar/i.test(await page.locator("#mdAviso").innerText()),
    "…y el aviso dice exactamente eso, con las palabras del backend");
  runtime.keyMode = null;

  await elegirEn(page, ".md-fila[data-slug='api.openai']");
  await page.locator("#mdApiKey").fill("sk-vara-1234567890");
  await page.locator("#mdApiKey").press("Enter");
  await page.waitForFunction(() => document.getElementById("mdPanel").hidden === true);
  ok(runtime.keyRequests === rojoAntes + 3, "Enter también guarda (cuatro gestos, un flujo)");
  ok(await page.locator(".md-fila[data-slug='api.openai'][data-verde='1']").count() === 1,
    "éxito API vuelve a la lista y deja su fila 🟢");

  /* ══ [F8 · obra 3] «USANDO X» + [Cambiar] · EL CATÁLOGO ABRE EN EL PANEL ══════════
   *
   * La ley: al cargar la llave, Aleph ELIGE UN DEFAULT SENSATO Y LO MUESTRA. El usuario
   * arranca sin decidir nada — y si quiere decidir, tiene dónde. */
  section("4b · F8 · EL MODELO DEL PROVEEDOR, EN EL PANEL");
  const catAntes = runtime.catalogoRequests;
  await elegirEn(page, ".md-fila[data-slug='api.openai']");
  await page.waitForSelector(".md-en-uso .amc-usando-m");
  ok(runtime.catalogoRequests === catAntes + 1,
    "el panel le PREGUNTA el modelo al backend (un resolvedor, no una copia en el cliente)");
  const usandoTxt = await page.locator(".md-en-uso").innerText();
  ok(/usando/i.test(usandoTxt) && /gpt-grande/.test(usandoTxt),
    "★ la card dice QUÉ MODELO USA sin que el usuario haya elegido nada", usandoTxt);
  ok(/Aleph/i.test(usandoTxt),
    "★ …y dice que lo elegimos NOSOTROS: «elegiste vos» sobre una heurística sería mentira",
    usandoTxt);
  ok(await page.locator(".md-catalogo .amc").count() === 0,
    "el catálogo NO se abre solo: la card muestra el modelo, el catálogo es un gesto");
  // ★ LA LEY DE PERSONA USUARIA, MEDIDA SOBRE EL DOM: el catálogo vive en el panel y en ningún otro
  //   lado. Una fila de lista con un catálogo adentro es el mismo bug que el campo de llave.
  ok(await page.locator("#mdFilas .amc").count() === 0,
    "★★ [F8] NINGUNA fila de la lista tiene catálogo adentro — abre en el panel, nunca en la fila");

  await page.locator(".md-en-uso [data-cambiar]").click();
  await page.waitForSelector(".md-catalogo .amc-item");
  ok(await page.locator(".md-catalogo .amc").count() === 1 &&
     await page.locator(".amc").count() === 1,
    "★ [Cambiar] abre el catálogo DENTRO DEL PANEL, y hay UNO solo en toda la pantalla");
  ok(await page.locator(".md-catalogo .amc-item").count() === CATALOGO_FIXTURE.length,
    "…con los modelos que devolvió el proveedor");
  ok(await page.locator(".md-catalogo .amc-item.on[data-modelo='gpt-grande']").count() === 1,
    "★ y MARCA el que está en uso: un picker que no dice dónde estás parado obliga a adivinar");
  // «Un cerebro sin tool-calling no es un cerebro» (obra 1). El backend lo usa para
  // desempatar; el picker tiene que DECIRLO antes de que alguien lo elija a mano.
  ok(await page.locator(".md-catalogo .amc-item[data-modelo='sin-tools-xl'] .amc-warn").count() === 1,
    "★★ [F8] el modelo SIN tool-calling se marca — es el más grande del catálogo y elegirlo " +
    "a ciegas rompe el turno recién cuando la persona ya armó todo");

  await page.locator(".md-catalogo .amc-search").fill("chico");
  await page.waitForFunction(() => document.querySelectorAll(".md-catalogo .amc-item").length === 1);
  ok(await page.locator(".md-catalogo .amc-item[data-modelo='gpt-chico']").count() === 1,
    "★ el catálogo es BUSCABLE (400 modelos es lo que devuelve openrouter: sin buscador no " +
    "hay forma de llegar al que uno quiere)");

  const escrituras = runtime.modeloWrites.length;
  await page.locator(".md-catalogo .amc-item[data-modelo='gpt-chico']").click();
  await page.waitForFunction(() => /gpt-chico/.test(
    document.querySelector(".md-en-uso").innerText || ""));
  ok(runtime.modeloWrites.length === escrituras + 1,
    "elegir ESCRIBE una sola vez");
  const ultima = runtime.modeloWrites[runtime.modeloWrites.length - 1];
  ok(ultima && ultima.slug === "api.openai" && ultima.modelo === "gpt-chico",
    "★ …con el payload del MODELO (`{slug, modelo}`), no el de la vía por contexto",
    JSON.stringify(ultima));
  const trasElegir = await page.locator(".md-en-uso").innerText();
  ok(/gpt-chico/.test(trasElegir) && /vos/i.test(trasElegir),
    "★★ y ahora la card dice que lo elegiste VOS: la procedencia es un dato, no un adorno",
    trasElegir);
  /* ★★ EL BUG QUE ESTA VARA CAZÓ (2026-08-07): el catálogo NO se re-pintaba después de
   * elegir. Seguía marcando «en uso» el modelo VIEJO y el [Que elija Aleph] —que sólo
   * existe cuando hay elección propia— no aparecía nunca. El picker afirmaba lo contrario
   * de lo que acababa de pasar. */
  ok(await page.locator(".md-catalogo .amc-item.on[data-modelo='gpt-chico']").count() === 1 &&
     await page.locator(".md-catalogo .amc-item.on").count() === 1,
    "★★ [F8] la marca «en uso» SE MUEVE al recién elegido — un picker que sigue señalando " +
    "el anterior está afirmando lo contrario de lo que acaba de pasar");
  ok(await page.locator(".md-catalogo .amc-search").inputValue() === "chico",
    "…y lo tipeado en el buscador SOBREVIVE: perderlo obliga a re-escribirlo para comparar dos");
  ok(await page.locator(".md-catalogo .amc-auto").count() === 1,
    "★ con una elección propia aparece [Que elija Aleph]: sin esa salida, quien probó un " +
    "modelo una vez queda casado con él");

  await page.locator(".md-catalogo .amc-auto").click();
  await page.waitForFunction(() => /gpt-grande/.test(
    document.querySelector(".md-en-uso").innerText || ""));
  const vuelta = runtime.modeloWrites[runtime.modeloWrites.length - 1];
  ok(vuelta && vuelta.modelo === "",
    "★ [Que elija Aleph] BORRA la elección (`modelo: \"\"`), no guarda otra", JSON.stringify(vuelta));
  ok(/Aleph/i.test(await page.locator(".md-en-uso").innerText()),
    "…y la card vuelve a decir que el modelo lo elegimos nosotros");

  /* ★★ LA CAUSA DE LA OBRA 2, EN LA SUPERFICIE. Hay llave, el proveedor contesta, y aun así
   * no hay modelo. Lo que NO puede pasar acá es que la card mande a poner una llave que ya
   * está — ése es el bug que `modelo_no_elegido` existe para no tener. */
  await page.locator("#mdPanelVolver").click();
  runtime.catalogoSinModelo = true;
  await elegirEn(page, ".md-fila[data-slug='api.openai']");
  await page.waitForSelector(".md-en-uso [data-cambiar]");
  const sinModelo = await page.locator(".md-en-uso").innerText();
  ok(/Modelo sin elegir/i.test(sinModelo),
    "★★ [F8] llave puesta y sin modelo → la card dice la CAUSA sellada, con su copy", sinModelo);
  ok(/Elegir modelo/i.test(sinModelo) && !/llave/i.test(sinModelo),
    "★★ [F8] …y ofrece [Elegir modelo] — JAMÁS «poné tu llave» a quien ya la puso", sinModelo);
  runtime.catalogoSinModelo = false;
  await page.locator("#mdPanelVolver").click();
  await elegirEn(page, ".md-fila[data-slug='api.openai']");
  await page.waitForSelector(".md-en-uso .amc-usando-m");
  await page.locator("#mdPanelVolver").click();

  /* ★★ EL ATERRIZAJE — la otra mitad del [Cambiar] que viene de una pantalla sin panel.
   *
   * `setupHref({brain})` escribía `?m=<slug>` desde hace tiempo y NADIE lo leía: se
   * aterrizaba en la lista genérica. Con el catálogo viviendo sólo en el panel, eso pasaba
   * de molestia a DEAD-END — el botón prometía un catálogo y entregaba una lista. Esto mide
   * que la promesa se cumple: se llega al panel de ESE proveedor y con el catálogo abierto. */
  await page.goto(`${FROZEN_URL || `http://127.0.0.1:${PORT}`}/Modelos.dc.html?m=api.openai&catalogo=1`,
                  { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".md-catalogo .amc-item");
  ok(await page.locator("#mdPanel").isVisible() &&
     /GPT API/.test(await page.locator("#mdPanelTitulo").innerText()),
    "★★ [F8] `?m=<slug>` aterriza EN EL PANEL de ese proveedor (el parámetro existía y no " +
    "lo leía nadie)");
  ok(await page.locator(".md-catalogo .amc").count() === 1,
    "★★ [F8] …y `catalogo=1` lo deja ABIERTO: quien apretó [Cambiar] no tiene que volver a " +
    "buscar el mismo botón");
  // Se vuelve a la URL LIMPIA: el `reload` de abajo conserva el query, y con `?m=` puesto
  // el panel se reabriría y su overlay taparía los filtros del resto de la caminata.
  await page.goto(`${FROZEN_URL || `http://127.0.0.1:${PORT}`}/Modelos.dc.html`,
                  { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#mdFilas .md-fila");

  // Replanta el escenario inicial para que el flujo HF pueda medir una única fila verde.
  runtime.apiComplete = false;
  runtime.downloadComplete = false;
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForSelector("#mdFilas .md-fila");
  await switchTo("cli");
  await elegirEn(page, ".md-fila[data-slug='cli.claude']");
  const cliPanel = await page.locator("#mdPanelBody").innerText();
  ok(/Checklist de tu CLI/.test(cliPanel) && /sesión activa · plan Max/.test(cliPanel) &&
    /sidecar CLI listo/.test(cliPanel),
  "panel CLI completo: instalación + sesión persistida + servicio sidecar");
  await page.locator("#mdPanelVolver").click();
  ok(await page.locator("#mdPanel").isHidden(), "volver del panel es un tap, no navegación");

  section("5 · HF LOCAL · VEREDICTO, CANCELACIÓN, PRUEBA AUTOMÁTICA, 🟢");
  await switchTo("hf_local");
  await elegirEn(page, ".md-fila[data-slug='hf.acme-too-big']");
  ok(/No entra: te faltan 3.5 GB/i.test(await page.locator("#mdPanelBody").innerText()) &&
    await page.locator(".md-descargar").isDisabled(),
  "panel HF conserva el veredicto de máquina y bloquea la descarga que no entra");
  await page.locator("#mdPanelVolver").click();

  await elegirEn(page, ".md-fila[data-slug='hf.acme-cancel']");
  await page.locator(".md-descargar").click();
  await page.waitForSelector(".md-cancelar");
  ok(await page.locator(".md-progress").isVisible(), "descarga muestra progreso");
  await page.locator(".md-cancelar").click();
  await page.waitForFunction(() => /Cancelada/.test(document.getElementById("mdPanelBody").innerText));
  ok(runtime.cancelRequests === 1 &&
    /No quedó nada a medio bajar/.test(await page.locator("#mdPanelBody").innerText()),
  "descarga cancelable: el sidecar recibe cancel y la UI confirma limpieza");
  await page.locator("#mdPanelVolver").click();

  await elegirEn(page, ".md-fila[data-slug='hf.acme-success']");
  const successPanel = await page.locator("#mdPanelBody").innerText();
  ok(/Entra cómodo/i.test(successPanel) && /4 GB/i.test(successPanel) &&
    /Descargar y probar/i.test(successPanel),
  "panel HF completo: veredicto + peso + descarga con prueba automática");
  await page.locator(".md-descargar").click();
  await page.waitForFunction(() => document.getElementById("mdPanel").hidden === true, null, { timeout: 10000 });
  await switchTo("todos");
  const greenRows = await page.locator(".md-fila[data-verde='1']").evaluateAll((rows) =>
    rows.map((r) => ({ slug: r.dataset.slug, fecha: r.textContent.match(/hace [^·<]+/)?.[0] || "" })));
  ok(greenRows.length === 1 && greenRows[0].slug === "hf.acme-success",
    "completar vuelve a la lista y deja sólo la fila elegida 🟢", JSON.stringify(greenRows));
  ok(greenRows.every((r) => r.fecha),
    "★ y esa fila verde lleva su FECHA: verde sin fecha no existe", JSON.stringify(greenRows));
  ok(await page.locator("#mdPanel").isHidden() && await page.locator("#mdPanelBack").isHidden(),
    "la salida de éxito cierra panel y overlay");

  /* [F8 · obra 0] …y el mismo guard, sobre el DOM que el usuario toca de verdad. */
  await switchTo("todos");
  await page.waitForSelector("#mdFilas .md-fila");
  const inputsEnFilas = await page.locator("#mdFilas .md-fila").evaluateAll((rows) =>
    rows.flatMap((r) => Array.from(r.querySelectorAll("input, textarea, select"))
      .map((i) => (r.dataset.slug || "?") + ":" + i.tagName.toLowerCase() +
                  "[" + (i.type || "") + "]")));
  ok(inputsEnFilas.length === 0,
    "★ [F8] y en la lista PINTADA tampoco hay ningún campo de entrada dentro de una fila",
    JSON.stringify(inputsEnFilas));

  section("6 · SELECTOR ÚNICO · POOL, DEFAULT, GUÍA Y CAÍDA");
  const selectorResult = await page.evaluate((data) => {
    const A = window.AlephModelSelector;
    const normal = A.options({ contexto: "sala", data }).map((m) => m.id);
    const guia = A.options({ contexto: "guia", data }).map((m) => m.id);
    const host = document.createElement("div");
    document.body.appendChild(host);
    let addTapped = false;
    A.render(host, { contexto: "sala", data, onAdd: () => { addTapped = true; } });
    const selected = host.querySelector(".ams-option.on")?.dataset.model || null;
    const hasAdd = !!host.querySelector(".ams-add[data-add='1']");
    host.querySelector(".ams-add").click();
    const setup = window.AlephBrain.setupHref({});
    host.remove();
    return { normal, guia, selected, hasAdd, addTapped, setup };
  }, selectorFixture);
  ok(JSON.stringify(selectorResult.normal) === JSON.stringify(["included-dead", "claude-live", "api-small"]),
    "selector ofrece sólo conectados + Default caído", JSON.stringify(selectorResult.normal));
  ok(JSON.stringify(selectorResult.guia) === JSON.stringify(["included-dead", "claude-live"]),
    "en contexto Guía aplica conectados+Default ∩ frontier", JSON.stringify(selectorResult.guia));
  ok(selectorResult.selected === "included-dead",
    "el Default queda preseleccionado aunque esté caído");
  ok(selectorResult.hasAdd && selectorResult.addTapped && /Modelos\.dc\.html/.test(selectorResult.setup),
    "[+] usa el componente compartido y aterriza en Modelos", JSON.stringify(selectorResult));

  const persistedBefore = runtime.preferenceWrites.length;
  const selectedContext = await page.evaluate(async (data) => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    let chosen = null;
    window.AlephModelSelector.render(host, {
      contexto: "sala", data, onSelect: (m) => { chosen = m.id; },
    });
    host.querySelector('[data-model="claude-live"]').click();
    await new Promise((r) => setTimeout(r, 100));
    host.remove();
    return chosen;
  }, selectorFixture);
  const persisted = runtime.preferenceWrites.slice(persistedBefore);
  ok(selectedContext === "claude-live" && persisted.some((p) =>
    p.contexto === "sala" && p.seleccion === "cli.claude"),
  "la elección se persiste por contexto sin cambiar el Default", JSON.stringify(persisted));

  const guard = await page.evaluate((data) => {
    const allowed = window.AlephModelSelector.guardUse("sala", "included-dead", { data });
    const dlg = document.getElementById("ams-fallen");
    return {
      allowed,
      visible: !!dlg && !dlg.hidden,
      text: dlg ? dlg.innerText : "",
      reconnect: dlg?.querySelector("[data-reconnect]")?.textContent || "",
      other: dlg?.querySelector("[data-other]")?.textContent || "",
    };
  }, selectorFixture);
  ok(guard.allowed === false && guard.visible &&
    /Reconectar/.test(guard.reconnect) && /Usar otro conectado/.test(guard.other),
  "Default caído al usarlo abre popup con los dos caminos", JSON.stringify(guard));

  /* ══ [F8 · obra 3] EL MISMO COMPONENTE, EN EL OTRO HOST ══════════════════════════
   *
   * La orden de persona usuaria: UN SOLO componente compartido entre Modelos y el Cuarto. El
   * selector de la Sala/Cuarto NO tiene panel, así que su [Cambiar] **manda al panel** en
   * vez de abrir el catálogo ahí — la ley se cumple también donde no hay dónde abrirlo. */
  const enFila = await page.evaluate((data) => {
    const A = window.AlephModelSelector;
    const host = document.createElement("div");
    document.body.appendChild(host);
    let elegido = null, destino = null;
    // El click real haría `location.href = …` y se llevaría puesta la caminata. Se espía
    // la MISMA función que arma el destino: si el botón dejara de usarla, esto se entera.
    const real = A.cambiarHref;
    A.cambiarHref = (slug) => { destino = real(slug); return "#f8-cambiar"; };
    A.render(host, { contexto: "sala", data, onSelect: (m) => { elegido = m.id; } });
    const fila = host.querySelector('[data-model="api-small"]');
    const linea = fila.querySelector(".amc-usando");
    const cambiar = fila.querySelector("[data-cambiar]");
    const anidados = host.querySelectorAll("button button").length;
    cambiar.click();
    const r = {
      texto: linea ? linea.innerText : "", tag: cambiar.tagName,
      rol: cambiar.getAttribute("role"), tab: cambiar.getAttribute("tabindex"),
      anidados, destino, elegido, catalogoEnFila: host.querySelectorAll(".amc").length,
    };
    A.cambiarHref = real; host.remove();
    return r;
  }, selectorFixture);
  ok(/usando/i.test(enFila.texto) && /gpt-chico/.test(enFila.texto),
    "★★ [F8] la fila del selector COMPARTIDO dice qué modelo usa — el Cuarto lo hereda sin " +
    "una línea propia", enFila.texto);
  ok(/vos/i.test(enFila.texto),
    "…y de quién fue la decisión", enFila.texto);
  ok(enFila.tag === "SPAN" && enFila.rol === "button" && enFila.tab === "0" &&
     enFila.anidados === 0,
    "★★ [F8] [Cambiar] es alcanzable por teclado y NO es un `<button>` anidado (0 anidados): " +
    "anidarlo partiría la fila entera", JSON.stringify(enFila));
  ok(enFila.elegido === null && enFila.catalogoEnFila === 0,
    "★★ [F8] apretarlo NO elige el modelo NI abre el catálogo en la fila", JSON.stringify(enFila));
  ok(/Modelos\.dc\.html/.test(enFila.destino || "") && /catalogo=1/.test(enFila.destino || "") &&
     /m=api\.small/.test(decodeURIComponent(enFila.destino || "")),
    "★★ [F8] MANDA AL PANEL de ESE proveedor con el catálogo abierto — el catálogo abre en " +
    "el panel, nunca en la fila", enFila.destino);

  /* ══ [F9] EL ÚNICO ESTADO SIN COLOR ERA EL SANO ══════════════════════════════════
   * Toda fila rota llevaba emoji de color (🔴 ⚪ 🟡 🔒); la que ANDA llevaba un `●` dentro
   * de `.ams-meta`, que es `var(--faint)` — gris. En la misma lista, «no disponible» se veía
   * y «conectado» se apagaba: el estado que uno busca era el que menos se distinguía. */
  const colores = await page.evaluate((data) => {
    const A = window.AlephModelSelector, S = window.CuartoSemaforo;
    const host = document.createElement("div");
    document.body.appendChild(host);
    A.render(host, { contexto: "sala", data, todos: true });
    const de = (id) => {
      const f = host.querySelector(`[data-model="${id}"] .ams-meta`);
      return f ? f.textContent.trim() : null;
    };
    const r = { conectado: de("claude-live"), roto: de("stray"),
                verdeDelDiccionario: S.ESTADOS.probado.emoji };
    host.remove();
    return r;
  }, selectorFixture);
  ok(colores.conectado && colores.conectado.startsWith(colores.verdeDelDiccionario),
    "★★ [F9] la fila CONECTADA lleva el verde del diccionario único, no un `●` gris",
    JSON.stringify(colores));
  ok(!/^●/.test(colores.conectado || ""),
    "★ …y ya no es el punto sin color: el estado sano dejó de ser el único apagado",
    JSON.stringify(colores));
  // ⚠️ La fila `stray` del fixture NO declara `estado`, así que su marca es el NEUTRO `○`
  // —«no sé qué le pasa»— y eso está bien: no se le inventa un color a un estado que nadie
  // declaró. Lo que se exige acá es que el verde no se derrame sobre lo no conectado.
  ok(!colores.roto.startsWith(colores.verdeDelDiccionario),
    "★ y el verde NO se derrama: lo no conectado conserva su marca", JSON.stringify(colores));

  /* ══ [F9] UN SOLO DICCIONARIO DE ESTADOS ═════════════════════════════════════════
   * `modelos.semaforo.ESTADO` era una copia paralela del único: mismos emojis, clases CSS
   * distintas, y le FALTABA `parcial`. Dos diccionarios del mismo vocabulario es cómo se
   * llega a que la misma pieza salga de un color en una superficie y de otro en la de al
   * lado. Ahora se DERIVA — y esta vara lo exige, no lo supone. */
  const dicc = await page.evaluate(async () => {
    const M = (await import("./modelos/modelos.semaforo.js")).default;
    const S = window.CuartoSemaforo;
    const dif = Object.keys(S.ESTADOS).filter((k) =>
      !M.ESTADO[k] || M.ESTADO[k].g !== S.ESTADOS[k].emoji || M.ESTADO[k].cls !== S.ESTADOS[k].css);
    return { faltan: Object.keys(S.ESTADOS).filter((k) => !M.ESTADO[k]), dif,
             n_unico: Object.keys(S.ESTADOS).length, n_modelos: Object.keys(M.ESTADO).length };
  });
  ok(dicc.faltan.length === 0,
    "★★ [F9] la superficie de Modelos conoce TODOS los estados del diccionario único",
    JSON.stringify(dicc));
  ok(dicc.dif.length === 0,
    "★★ [F9] …y su color/emoji SALE de ahí, no de una copia paralela que puede discrepar",
    JSON.stringify(dicc));

  /* ══ ★★★ UN SOLO DERIVADOR POR FILA — el guard de la ley ═════════════════════════
   *
   * «Un solo derivador por fila: estado → {glifo, label, acción, copy}. Todo lo demás lo
   *  consume; nadie lo recalcula.» (persona usuaria, 2026-08-07, después de que la misma raíz mordiera
   *  CUATRO veces en una tanda.)
   *
   * Esta vara FALLA si alguien vuelve a pintar color, label o acción fuera del derivador.
   * Es estática porque el vivo no alcanza: una superficie que re-decide puede pintar el
   * mismo DOM hoy y discrepar mañana. */
  const src_sup = await readFile(join(DESIGN, "modelos", "modelos.superficie.js"), "utf8");
  const cuerpo_sup = src_sup.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

  ok(/d\.semaforo|const sem = d\.semaforo/.test(cuerpo_sup),
    "★★★ la superficie CONSUME el derivador único (`d.semaforo`)");
  const emojis = cuerpo_sup.match(/[🟢🟡🔴⚪🔒]/gu) || [];
  ok(emojis.length === 0,
    "★★★ …y NO escribe glifos de estado por su cuenta: el color sale de un solo lugar",
    `encontrados: ${emojis.join(" ")}`);
  const textosDeEstado = ["probado ", "sin probar", "comprobando", "Roto", "roto"]
    .filter((t) => new RegExp(`["\`']${t}`).test(cuerpo_sup));
  ok(textosDeEstado.length === 0,
    "★★★ …ni compone el TEXTO del estado: el copy sellado sale del diccionario",
    `encontrados: ${JSON.stringify(textosDeEstado)}`);
  ok(!/cara\.camino\.(es|accion)/.test(cuerpo_sup),
    "★★★ …ni elige el rótulo/acción del botón: también viene derivado",
    (cuerpo_sup.match(/.{0,50}cara\.camino\.(es|accion).{0,30}/) || [])[0]);

  /* ⚠️ Y EL COPY QUE SE DIBUJA JAMÁS ES EL NOMBRE TÉCNICO. «roto», «key_invalida» y el
   * cuerpo crudo del proveedor son estado INTERNO; lo que se lee es «Credencial inválida». */
  const pintado = await page.evaluate(async () => {
    const W = await import("./modelos/modelos.widget.js");
    const ahora = Date.now();
    const f = { familia: "api", ref: "x", slug: "api.x", label: "X", estado: "roto",
                causa: "key_invalida", hay_llave: true, estuvo_completa: true };
    return W.derivar(f, { ahora }).semaforo;
  });
  ok(pintado.texto === "Credencial inválida",
    "★★★ una llave inválida se DIBUJA con el copy sellado", JSON.stringify(pintado));
  ok(!/roto|key_invalida|error|\{/.test(pintado.texto),
    "★★★ …y nunca con el nombre técnico ni el cuerpo del proveedor", JSON.stringify(pintado));

  /* ══ ★★★ EL RESUMEN Y EL BANNER SALEN DE LAS MISMAS FILAS ════════════════════════
   * Medido en la app: cabecera «CONECTADOS 2 · LISTOS 2» sin una sola fila de API que lo
   * respaldara, y «DEFAULT: Groq» en ROJO con la fila de Groq en AMARILLO. Cada número
   * salía de un lugar distinto — CONECTADOS del ARCHIVO de preferencias, el rojo del
   * Default de un booleano crudo, ROTOS del estado interno. */
  const src_ui = await readFile(join(DESIGN, "modelos", "modelos.ui.js"), "utf8");
  const cuerpo_ui2 = src_ui.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  const resumen = cuerpo_ui2.slice(cuerpo_ui2.indexOf("function pintarResumen"),
                                   cuerpo_ui2.indexOf("function pintarCategorias"));
  ok(!/pref\.conectados|preferencias\.conectados/.test(resumen),
    "★★★ el contador CONECTADOS ya no sale del archivo de preferencias (fuente paralela)",
    (resumen.match(/.{0,40}pref\.conectados.{0,30}/) || [])[0]);
  ok(/censo/.test(resumen) && /semaforo/.test(resumen),
    "★★★ …sale del censo, que son LAS MISMAS filas derivadas que se pintan abajo");
  ok(!/estado === "roto"/.test(resumen),
    "★★★ …y ROTOS cuenta lo que se PINTA rojo, no el estado interno",
    (resumen.match(/.{0,40}estado === "roto".{0,20}/) || [])[0]);
  ok(/sem\.tono/.test(cuerpo_ui2) && /aplicarVeredicto/.test(cuerpo_ui2),
    "★★★ y el TONO del banner se deriva de la fila — no puede afirmar un desenlace propio");
  ok(!/terminó en verde/.test(cuerpo_ui2),
    "★★★ …ya no existe la frase que afirmaba el desenlace por su cuenta",
    (cuerpo_ui2.match(/.{0,40}terminó en verde.{0,20}/) || [])[0]);

  ok(pageErrors.length === 0, "cero errores JS en la caminata V2", pageErrors.join(" | "));
} catch (error) {
  if (!(CALIBRATE_MISSING && /calibración roja completada/.test(String(error && error.message)))) {
    ok(false, "la vara completó la caminata sin excepción", error && (error.stack || error.message));
  }
} finally {
  if (page) await page.close().catch(() => {});
  if (browser) await browser.close().catch(() => {});
  stop();
}

const summary = failures.length
  ? `✗ MODELOS V2: ${failures.length} falla(s) / ${assertions} aserciones`
  : `✓ MODELOS V2: ${assertions} aserciones verdes`;
console.log(`\n${summary}`);
if (CALIBRATE_MISSING) {
  const expectedRed = failures.some((f) => /veredicto inline/.test(f));
  console.log(expectedRed
    ? "✓ calibración confirmada: sin veredicto, la vara salió roja"
    : "✗ calibración inválida: cortar el veredicto no activó la vara");
  process.exit(expectedRed ? 1 : 2);
}
process.exit(failures.length ? 1 : 0);
