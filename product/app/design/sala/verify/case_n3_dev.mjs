/* case_n3_dev.mjs — N3 · nicho nuevo PROGRAMACIÓN: informe con código PROBADO en sandbox.
 * script_runner (run_python, gap B3) ejecuta de verdad; la obra es un informe con code
 * blocks MONOESPACIADOS PLANOS (decisión tomada: sin highlight.js hasta post-launch). */
import { newSalaPage, runPrompt, snap, realConsoleErrors, makeChecker } from "./_drive.mjs";

export async function run(browser, state) {
  const chk = makeChecker("N3 dev sandbox→informe con código (vivo)");
  const { ctx, page, consoleErrors, pageErrors } = await newSalaPage(browser, state.user, {
    puppet: state.puppets["qa-n3-dev"],
  });
  try {
    // los años de prueba salen de un PRNG con seed — inasibles sin ejecutar de verdad
    // (con años fijos famosos, el modelo a veces «sabe» las respuestas y saltea el sandbox).
    const { out } = await runPrompt(page,
      "Escribe una función Python `es_bisiesto(anio)` correcta. En el sandbox: random.seed(42); genera 5 años con random.randint(1900, 2400) y pruébala con ESOS años (no los elijas tú). Entrega un informe corto con el código, los 5 años generados y el resultado observado de cada uno.",
      { budget: 600_000 });

    const rec = (out && out.record) || {};
    const calls = (rec.tool_calls || []).map((c) => c.tool);
    chk.check("motor: run ok", out && out.ok !== false, "out.ok=" + (out && out.ok));
    chk.check("motor: degraded == null", rec.degraded == null, JSON.stringify(rec.degraded || null).slice(0, 150));
    chk.check("motor: terminó en el brain real", rec.model_final === "claude-code-opus-4.8", "model_final=" + rec.model_final);
    chk.check("motor: ejecutó en el sandbox (run_python)", calls.includes("run_python"), JSON.stringify(calls));

    // UI: informe con code blocks monoespaciados PLANOS
    await page.waitForFunction(() => {
      const c = document.getElementById("canvas");
      return c && /sala-(informe|prose)/.test(c.className) && c.querySelectorAll("pre code, pre").length >= 1;
    }, { timeout: 25_000 }).catch(() => {});
    const ui = await page.evaluate(() => {
      const c = document.getElementById("canvas");
      const code = c ? c.querySelector("pre code, pre") : null;
      const mono = code ? /mono|courier|menlo|consolas/i.test(getComputedStyle(code).fontFamily) : false;
      return {
        cls: c ? c.className : "",
        blocks: c ? c.querySelectorAll("pre").length : 0,
        mono,
        hljs: c ? c.querySelectorAll('[class*="hljs"]').length : 0,
        text: c ? c.textContent.slice(0, 4000) : "",
      };
    });
    chk.check("ui: canvas es informe", /sala-informe|ar-prose/.test(ui.cls), ui.cls);
    chk.check("ui: ≥1 code block presente", ui.blocks >= 1, "blocks=" + ui.blocks);
    chk.check("ui: código monoespaciado", ui.mono);
    chk.check("ui: PLANO — cero highlight.js", ui.hljs === 0, "hljs nodes=" + ui.hljs);
    chk.check("ui: la función probada aparece en la obra", /es_bisiesto/.test(ui.text));

    const errs = realConsoleErrors(consoleErrors, pageErrors);
    chk.check("consola limpia", errs.length === 0, errs.slice(0, 3).join(" | "));
    await snap(page, "n3-dev");
  } finally { await ctx.close(); }
  return chk.finish();
}
