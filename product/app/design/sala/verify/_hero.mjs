/* _hero.mjs — corredor compartido de los casos R (regresión de héroes build→use).
 *
 * Un héroe = puppet de catálogo REAL (belt + framing de producto, brain shim) que produce
 * una OBRA RICA vía su productor (fem/backtest/spice/segmentación). El caso prueba el loop
 * completo por la UI viva y ancla el verde al RUN RECORD (anti-grift):
 *   · degraded == null                   (nada degradó en silencio)
 *   · model_final == el brain real       (el shim no fue enmascarado)
 *   · toda tool llamada ∈ tools_cabled   (no hay tools fantasma fuera del belt)
 *   · el/los productores esperados corrieron de verdad (≥1 tool_call)
 *   · out.obra.type == el tipo declarado por el productor
 *   · held_actions vacío                 (un héroe read-only no debe gatear nada)
 * Y en la UI: canvas con el renderer correcto + bitácora visible (ⓘ Detalles) con ≥1 paso
 * + consola limpia. Estado interno == estado visible: PASS técnico con UI opaca = FAIL. */
import { newSalaPage, runPrompt, snap, realConsoleErrors, makeChecker } from "./_drive.mjs";

export async function runHero(browser, state, spec) {
  const chk = makeChecker(spec.title);
  const { ctx, page, consoleErrors, pageErrors } = await newSalaPage(browser, state.user, {
    puppet: state.puppets[spec.puppetKey],
  });
  try {
    const { out } = await runPrompt(page, spec.prompt, { budget: spec.budget || 600_000 });

    // ── capa MOTOR (run record de executor.py) ──
    const rec = (out && out.record) || {};
    const calls = (rec.tool_calls || []).map((c) => c.tool);
    const cabled = rec.tools_cabled || [];
    chk.check("motor: run ok", out && out.ok !== false, "out.ok=" + (out && out.ok));
    chk.check("motor: degraded == null (cero degradación silenciosa)", rec.degraded == null,
      "degraded=" + JSON.stringify(rec.degraded || null).slice(0, 200));
    chk.check("motor: terminó en el brain real", rec.model_final === "claude-code-opus-4.8",
      "model_final=" + rec.model_final);
    chk.check("motor: toda tool llamada está cableada en el belt",
      calls.length > 0 && calls.every((t) => cabled.includes(t)),
      "calls=" + JSON.stringify(calls.slice(0, 8)) + " cabled=" + JSON.stringify(cabled.slice(0, 10)));
    for (const t of spec.expectTools) {
      chk.check("motor: corrió el productor " + t, calls.includes(t), "calls=" + JSON.stringify(calls.slice(0, 8)));
    }
    chk.check("motor: obra rica del tipo " + spec.obraType,
      !!(out && out.obra) && out.obra.type === spec.obraType,
      "obra.type=" + (out && out.obra && out.obra.type));
    chk.check("motor: sin acciones retenidas espurias", ((out && out.held_actions) || []).length === 0,
      JSON.stringify((out && out.held_actions) || []));
    if (spec.assertObra) spec.assertObra(chk, out && out.obra);

    // ── capa UI: el renderer correcto pintó la obra ──
    await page.waitForFunction((cls) => {
      const c = document.getElementById("canvas");
      return c && new RegExp(cls).test(c.className);
    }, spec.canvasClass, { timeout: 25_000 }).catch(() => {});
    const ui = await page.evaluate((sel) => {
      const c = document.getElementById("canvas");
      return { cls: c ? c.className : "", marker: !!document.querySelector(sel) };
    }, spec.uiMarker);
    chk.check("ui: canvas → " + spec.canvasClass, new RegExp(spec.canvasClass).test(ui.cls), ui.cls);
    chk.check("ui: renderer montó " + spec.uiMarker, ui.marker);

    // ── bitácora VISIBLE: ⓘ Detalles → sección Bitácora con ≥1 paso de tool ──
    await page.click("#infoBtn").catch(() => {});
    await page.waitForSelector("#artInfo .ai-step, #artInfo .ai-deleg", { timeout: 5_000 }).catch(() => {});
    const steps = await page.evaluate(() =>
      document.querySelectorAll("#artInfo .ai-step.tool, #artInfo .ai-deleg").length);
    chk.check("ui: bitácora visible con ≥1 tool", steps >= 1, "steps=" + steps);
    await page.click("#infoBtn").catch(() => {});

    const errs = realConsoleErrors(consoleErrors, pageErrors);
    chk.check("consola limpia", errs.length === 0, errs.slice(0, 3).join(" | "));

    await snap(page, spec.snapName);
  } finally { await ctx.close(); }
  return chk.finish();
}
