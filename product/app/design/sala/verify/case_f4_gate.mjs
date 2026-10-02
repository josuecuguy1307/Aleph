/* case_f4_gate.mjs — VIVO: el gate money-touch por el path de PROD completo.
 *
 * Puppet QA con belt-gated (fixture hecho para esto): lookup_price ejecuta, place_order
 * NUNCA ejecuta en el run — queda retenida (held_actions) y aparece la tarjeta ámbar
 * "🔒 Pide tu OK". Aprobar → POST /v1/runs/{id}/approve ejecuta y la tarjeta cierra ✓. */
import { BUDGET } from "./_env.mjs";
import { newSalaPage, runPrompt, snap, realConsoleErrors, makeChecker } from "./_drive.mjs";

export async function run(browser, state) {
  const chk = makeChecker("F4 gate money-touch (vivo)");
  const { ctx, page, consoleErrors, pageErrors } = await newSalaPage(browser, state.user, {
    puppet: state.puppets["qa-sala-gate"],
  });
  try {
    const { out } = await runPrompt(page,
      "Consulta el precio de la acción ACME con lookup_price y luego coloca una orden de compra de 10 acciones con place_order.",
      { budget: BUDGET.gate });

    const rec = (out && out.record) || {};
    const toolsStr = JSON.stringify(rec.tool_calls || []);
    const held = (out && out.held_actions) || [];
    chk.check("motor: run ok (el gate no tumba el run)", out && out.ok !== false, "out.ok=" + (out && out.ok));
    chk.check("motor: intentó place_order", toolsStr.includes("place_order"));
    chk.check("motor: la acción quedó RETENIDA (held_actions)", held.length >= 1, "held=" + held.length);
    chk.check("motor: la retenida es place_order con approval_id",
      held.some((h) => h.tool === "place_order" && h.approval_id), JSON.stringify(held).slice(0, 200));

    const gate1 = await page.evaluate(() => {
      const g = document.querySelector("#chat .gate");
      return { present: !!g, text: g ? g.textContent : "", okBtn: !!(g && g.querySelector("button.ok")) };
    });
    chk.check("ui: tarjeta ámbar del gate visible", gate1.present);
    chk.check("ui: pide el OK en humano (mover tu dinero)", /Pide tu OK/.test(gate1.text) && /dinero|sensible/.test(gate1.text), gate1.text.slice(0, 120));
    chk.check("ui: botón Aprobar presente", gate1.okBtn);

    await snap(page, "f4-gate-held");

    // Aprobar → el backend ejecuta la retenida y la tarjeta cierra honesta.
    // .catch(null) en AMBOS: si el run vino roto (sin gate), el caso FALLA sus checks
    // pero no tumba la batería entera con una promise rechazada sin dueño.
    const approveP = page.waitForResponse((r) => r.url().includes("/approve") && r.request().method() === "POST", { timeout: 30_000 }).catch(() => null);
    await page.click("#chat .gate button.ok", { timeout: 5_000 }).catch(() => {});
    const approveR = await approveP;
    chk.check("aprobar pegó a /v1/runs/{id}/approve con 200", !!approveR && approveR.status() === 200,
      "status=" + (approveR ? approveR.status() : "sin respuesta"));
    await page.waitForFunction(() => /✓ Hecho/.test((document.querySelector("#chat .gate") || {}).textContent || ""), { timeout: 15_000 }).catch(() => {});
    const gate2 = await page.evaluate(() => (document.querySelector("#chat .gate") || {}).textContent || "");
    chk.check("ui: la tarjeta cierra '✓ Hecho'", /✓ Hecho/.test(gate2), gate2.slice(0, 120));

    const errs = realConsoleErrors(consoleErrors, pageErrors);
    chk.check("consola limpia", errs.length === 0, errs.slice(0, 3).join(" | "));

    await snap(page, "f4-gate-approved");
  } finally { await ctx.close(); }
  return chk.finish();
}
