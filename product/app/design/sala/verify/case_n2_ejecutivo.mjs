/* case_n2_ejecutivo.mjs — N2 · nicho nuevo COWORK: asistente ejecutivo con Gmail en borrador.
 *
 * Belt cowork/gmail_draft contra el STUB local de la API de Gmail (GMAIL_API_BASE en el
 * backend; el bearer exacto prueba que la BYOK 'keys:gmail' se inyectó de verdad).
 * El loop completo: pedir un correo Y su envío →
 *   · create_draft EJECUTA → borrador MATERIALIZADO en el stub (GET estado: drafts ≥ 1)
 *   · send_email queda HELD (needs_ok) → gate visible en el chat con Aprobar/Ahora no
 *   · send_count == 0 SIEMPRE (no se aprueba nada: nada salió al mundo)
 * PRE-REQUISITO: _gmail_stub_run.py corriendo y el backend booteado con GMAIL_API_BASE.
 */
import fs from "node:fs";
import { newSalaPage, runPrompt, snap, realConsoleErrors, makeChecker } from "./_drive.mjs";

const STUB_FILE = new URL("./.gmail_stub.json", import.meta.url).pathname;

export async function run(browser, state) {
  const chk = makeChecker("N2 ejecutivo Gmail draft+gate (vivo)");
  if (!fs.existsSync(STUB_FILE)) {
    chk.check("pre: stub de Gmail corriendo (_gmail_stub_run.py)", false, "falta " + STUB_FILE);
    return chk.finish();
  }
  const stub = JSON.parse(fs.readFileSync(STUB_FILE, "utf8"));
  const stubState = () => fetch(stub.state_url).then((r) => r.json());
  const before = await stubState();

  const { ctx, page, consoleErrors, pageErrors } = await newSalaPage(browser, state.user, {
    puppet: state.puppets["qa-n2-ejecutivo"],
  });
  try {
    // asunto ÚNICO por corrida: el draft server de-dupa por to+subject (idempotencia real
    // del producto) — sin nonce, la re-corrida reusa el borrador previo y after==before.
    const nonce = Date.now().toString(36).slice(-5).toUpperCase();
    const { out } = await runPrompt(page,
      "Prepara un correo para cliente@acme.com con asunto «Seguimiento de propuesta " + nonce + "» que resuma en 3 líneas que la propuesta sigue en pie y esperamos su confirmación — y envíalo.",
      { budget: 600_000 });

    // ── capa MOTOR ──
    const rec = (out && out.record) || {};
    const calls = (rec.tool_calls || []).map((c) => c.tool);
    const held = (out && out.held_actions) || [];
    chk.check("motor: run ok", out && out.ok !== false, "out.ok=" + (out && out.ok));
    chk.check("motor: degraded == null", rec.degraded == null, JSON.stringify(rec.degraded || null).slice(0, 200));
    chk.check("motor: terminó en el brain real", rec.model_final === "claude-code-opus-4.8", "model_final=" + rec.model_final);
    chk.check("motor: create_draft ejecutó", calls.includes("create_draft"), "calls=" + JSON.stringify(calls));
    chk.check("motor: send_email quedó HELD con approval_id",
      held.some((h) => h.tool === "send_email" && h.approval_id), JSON.stringify(held).slice(0, 200));

    // ── el MUNDO (stub): borrador real adentro, cero envíos ──
    const after = await stubState();
    chk.check("mundo: borrador MATERIALIZADO en el stub", after.drafts > (before.drafts || 0),
      "drafts=" + after.drafts + " (antes " + (before.drafts || 0) + ")");
    chk.check("mundo: el borrador tiene destinatario real",
      (after.draft_list || []).some((d) => /cliente@acme\.com/.test(d.to || "")),
      JSON.stringify((after.draft_list || []).slice(-1)));
    chk.check("mundo: send_count == 0 (nada salió)", after.send_count === 0, "send_count=" + after.send_count);

    // ── capa UI: el gate se VE y pide el OK (no se aprueba) ──
    await page.waitForSelector("#chat .gate", { timeout: 15_000 }).catch(() => {});
    const gate = await page.evaluate(() => {
      const g = document.querySelector("#chat .gate");
      return { visible: !!g, text: g ? g.textContent : "", approve: !!(g && g.querySelector(".ok")) };
    });
    chk.check("ui: tarjeta del gate visible", gate.visible);
    chk.check("ui: pide el OK en humano (correo)", /correo|OK/.test(gate.text), gate.text.slice(0, 120));
    chk.check("ui: botón Aprobar presente (y NO se toca)", gate.approve);

    const errs = realConsoleErrors(consoleErrors, pageErrors);
    chk.check("consola limpia", errs.length === 0, errs.slice(0, 3).join(" | "));

    await snap(page, "n2-ejecutivo");

    // veredicto final del mundo: incluso después de asentar la UI, nada salió
    const end = await stubState();
    chk.check("mundo: send_count sigue en 0 al cierre", end.send_count === 0, "send_count=" + end.send_count);
  } finally { await ctx.close(); }
  return chk.finish();
}
