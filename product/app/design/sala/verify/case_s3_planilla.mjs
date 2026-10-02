/* case_s3_planilla.mjs — VIVO: el camino producto por defecto entrega una planilla REAL.
 *
 * Puppet QA (belt-inline-rich + brain shim) → prompt de amortización → el agente computa
 * con run_python, escribe un .xlsx real con write_xlsx, la Sala lo captura y la grilla
 * se hidrata con las FILAS DEL ARCHIVO (SheetJS), no con texto del modelo.
 * Capas: motor (JSON del run) · UI (grilla real + descarga) · consola. */
import { BUDGET } from "./_env.mjs";
import { newSalaPage, runPrompt, snap, realConsoleErrors, makeChecker } from "./_drive.mjs";

export async function run(browser, state) {
  const chk = makeChecker("S3 planilla (vivo)");
  const { ctx, page, consoleErrors, pageErrors } = await newSalaPage(browser, state.user, {
    puppet: state.puppets["qa-sala-brain"],
  });
  try {
    const { out } = await runPrompt(page,
      "Arma una planilla de amortización de un préstamo de 10.000 a 12 meses al 9% anual con cuota fija: computa las cuotas con run_python y entrégala como xlsx con write_xlsx.",
      { budget: BUDGET.live });

    // capa MOTOR
    const rec = (out && out.record) || {};
    const toolsStr = JSON.stringify(rec.tool_calls || []);
    chk.check("motor: run ok", out && out.ok !== false, "out.ok=" + (out && out.ok));
    // el candado es ANTI-ENMASCARAMIENTO: falla si el modelo FINAL no es el brain real.
    // Una cascada transitoria que recupera al MISMO modelo es robustez, no masking → warn visible.
    chk.check("motor: terminó en el brain real", rec.model_final === "claude-code-opus-4.8",
      "model_final=" + rec.model_final);
    if (rec.degraded) console.log("  ~ warn: cascada transitoria (mismo brain): " + JSON.stringify(rec.degraded).slice(0, 300));
    chk.check("motor: computó con run_python", toolsStr.includes("run_python"));
    chk.check("motor: escribió xlsx real", toolsStr.includes("write_xlsx"));
    chk.check("motor: archivo capturado", ((out && out.outputs_captured) || []).some((o) => o.output_id));

    // capa UI — la grilla se hidrata del .xlsx (asíncrono: SheetJS + download)
    await page.waitForFunction(() => {
      const c = document.getElementById("canvas");
      return c && /sala-planilla/.test(c.className) && c.querySelectorAll("table tbody tr").length >= 10;
    }, { timeout: 25_000 }).catch(() => {});
    const ui = await page.evaluate(() => {
      const c = document.getElementById("canvas");
      const dl = document.getElementById("canvasDl");
      return {
        cls: c ? c.className : "",
        rows: c ? c.querySelectorAll("table tbody tr").length : 0,
        dlVisible: !!(dl && dl.style.display !== "none"),
      };
    });
    chk.check("ui: canvas es planilla", /sala-planilla/.test(ui.cls), ui.cls);
    chk.check("ui: grilla con filas reales del xlsx (≥10)", ui.rows >= 10, "rows=" + ui.rows);
    chk.check("ui: descarga real visible", ui.dlVisible);

    const errs = realConsoleErrors(consoleErrors, pageErrors);
    chk.check("consola limpia", errs.length === 0, errs.slice(0, 3).join(" | "));

    await snap(page, "s3-planilla");
  } finally { await ctx.close(); }
  return chk.finish();
}
