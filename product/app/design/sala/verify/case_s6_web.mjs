/* case_s6_web.mjs — VIVO: obra web renderiza en iframe AISLADO con contenido real.
 *
 * Mismo puppet QA brain; el pedido de una landing autónoma debe rutear a type=web y
 * montarse en el iframe sandbox (sin allow-same-origin). Introspección DENTRO del frame
 * (patrón render/verify.mjs): tiene estructura real (h1/button), no texto plano. */
import { BUDGET } from "./_env.mjs";
import { newSalaPage, runPrompt, snap, realConsoleErrors, makeChecker } from "./_drive.mjs";

export async function run(browser, state) {
  const chk = makeChecker("S6 web (vivo)");
  const { ctx, page, consoleErrors, pageErrors } = await newSalaPage(browser, state.user, {
    puppet: state.puppets["qa-sala-brain"],
  });
  try {
    const { out } = await runPrompt(page,
      "Arma una landing page simple para una cafetería de especialidad — un solo documento html completo y autónomo (HTML+CSS inline), con un título grande y un botón de contacto.",
      { budget: BUDGET.live });

    const rec = (out && out.record) || {};
    chk.check("motor: run ok", out && out.ok !== false, "out.ok=" + (out && out.ok));
    chk.check("motor: terminó en el brain real", rec.model_final === "claude-code-opus-4.8",
      "model_final=" + rec.model_final);
    if (rec.degraded) console.log("  ~ warn: cascada transitoria (mismo brain): " + JSON.stringify(rec.degraded).slice(0, 300));

    // UI: canvas web + iframe con contenido REAL adentro
    await page.waitForFunction(() => {
      const c = document.getElementById("canvas");
      return c && /sala-web/.test(c.className) && c.querySelector("iframe");
    }, { timeout: 20_000 }).catch(() => {});
    const cls = await page.evaluate(() => (document.getElementById("canvas") || {}).className || "");
    chk.check("ui: canvas es web (iframe aislado)", /sala-web/.test(cls), cls);

    let inner = { h1: 0, btn: 0 };
    for (const f of page.frames()) {
      if (f === page.mainFrame()) continue;
      try {
        inner = await f.evaluate(() => ({
          h1: document.querySelectorAll("h1,h2").length,
          btn: document.querySelectorAll("button,a.btn,a[class*='btn'],[role='button']").length,
        }));
        if (inner.h1 || inner.btn) break;
      } catch { /* frame opaco o aún cargando — se evalúa el siguiente */ }
    }
    chk.check("ui: el iframe tiene estructura real (título)", inner.h1 >= 1, JSON.stringify(inner));
    chk.check("ui: el iframe tiene interacción (botón/CTA)", inner.btn >= 1, JSON.stringify(inner));

    const errs = realConsoleErrors(consoleErrors, pageErrors);
    chk.check("consola limpia", errs.length === 0, errs.slice(0, 3).join(" | "));

    await snap(page, "s6-web");
  } finally { await ctx.close(); }
  return chk.finish();
}
