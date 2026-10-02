/* case_f3_errorcard.mjs — STUB: contrato de FALLA RECUPERABLE del frontend.
 *
 * Se stubea SOLO /v1/puppets/run (respuesta vacía del motor) + los clasificadores
 * (determinismo, cero modelo). Página real, renderers reales. Contrato:
 *   respuesta vacía → .errcard "No salió" + canvas RESTAURADO (jamás "armando…" colgado)
 *   ↻ Reintentar → re-dispara EXACTAMENTE el mismo pedido (2º POST observado). */
import { BUDGET } from "./_env.mjs";
import { newSalaPage, runPrompt, snap, realConsoleErrors, makeChecker } from "./_drive.mjs";

export async function run(browser, state) {
  const chk = makeChecker("F3 errorcard+retry (stub)");
  let runCount = 0;
  const routes = [
    { url: "**/v1/classify-turn", handler: (r) => r.fulfill({ json: { turn: "obra" } }) },
    { url: "**/v1/artifacts/classify-action", handler: (r) => r.fulfill({ json: { action: "new", type: "informe" } }) },
    {
      url: "**/v1/puppets/run",
      handler: async (r) => {
        runCount++;
        await new Promise((res) => setTimeout(res, 600));   // ventana para ver "armando…"
        await r.fulfill({ json: { ok: false, answer: "", record: { tool_calls: [] } } });
      },
    },
  ];
  const { ctx, page, consoleErrors, pageErrors } = await newSalaPage(browser, state.user, { routes });
  try {
    await runPrompt(page, "arma un informe corto sobre el clima de Quito", { budget: BUDGET.stub });

    const st1 = await page.evaluate(() => ({
      err: !!document.querySelector("#chat .errcard"),
      retryBtn: !!document.querySelector("#chat .errcard button.retry"),
      badgeHidden: (document.getElementById("bbadge") || {}).style?.display === "none",
      sendEnabled: !(document.getElementById("send") || {}).disabled,
      canvasRestored: !!document.querySelector("#canvas .empty") || !/sala-/.test((document.getElementById("canvas") || {}).className || ""),
    }));
    chk.check("errcard visible con rol de alerta", st1.err);
    chk.check("botón ↻ Reintentar presente", st1.retryBtn);
    chk.check("canvas restaurado (no quedó 'armando…')", st1.badgeHidden && st1.canvasRestored,
      JSON.stringify(st1));
    chk.check("composer re-habilitado", st1.sendEnabled);
    chk.check("el motor recibió 1 POST", runCount === 1, "runCount=" + runCount);

    await snap(page, "f3-errorcard");

    // ↻ Reintentar → mismo pedido, 2º POST, y (falla de nuevo) 2º errcard
    await page.click("#chat .errcard button.retry");
    await page.waitForFunction(() => document.querySelector("#chat .errcard"), { timeout: BUDGET.stub });
    chk.check("retry re-disparó el run (2º POST)", runCount === 2, "runCount=" + runCount);
    chk.check("la 2ª falla vuelve a ser visible", await page.evaluate(() => !!document.querySelector("#chat .errcard")));

    const errs = realConsoleErrors(consoleErrors, pageErrors);
    chk.check("consola limpia", errs.length === 0, errs.slice(0, 3).join(" | "));
  } finally { await ctx.close(); }
  return chk.finish();
}
