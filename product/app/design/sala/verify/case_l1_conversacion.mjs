/* case_l1_conversacion.mjs — L1 · conversación LARGA (≥8 turnos) sobre la misma obra.
 *
 * Prueba que el hilo AGUANTA: 8 turnos reales (crear + 5 ediciones con marcador único +
 * 2 turnos de charla intercalados) sin errcards, con la bitácora ESCALANDO y el contexto
 * PERSISTIENDO — la obra final conserva TODOS los marcadores de las ediciones previas
 * (una edición que regenerara desde cero los perdería) y sigue siendo UNA obra (no apila). */
import { newSalaPage, runPrompt, snap, realConsoleErrors, makeChecker } from "./_drive.mjs";

const MARKS = ["ALFA-11", "BETA-22", "GAMMA-33", "DELTA-44", "EPSILON-55", "ZETA-66"];

export async function run(browser, state) {
  const chk = makeChecker("L1 conversación ≥8 turnos (vivo)");
  const { ctx, page, consoleErrors, pageErrors } = await newSalaPage(browser, state.user, {
    puppet: state.puppets["qa-sala-brain"],
  });
  const B = 300_000;
  try {
    // t1 · crear la obra con el primer marcador
    await runPrompt(page, "Crea una lista corta titulada «Bitácora de vuelo» con un único punto: " + MARKS[0] + ".", { budget: B });
    // t2-t5 · ediciones acumulativas (cada una agrega SU marcador, preservando el resto)
    for (const m of MARKS.slice(1, 5)) {
      await runPrompt(page, "Agrega a la lista un punto nuevo: " + m + ". No toques los puntos existentes.", { budget: B });
    }
    // t6 · charla intercalada (pregunta sobre la obra — NO debe tocar el canvas)
    await runPrompt(page, "¿Cuántos puntos lleva la lista hasta ahora? Solo dime el número.", { budget: B });
    // t7 · edición final
    await runPrompt(page, "Agrega el último punto: " + MARKS[5] + ". No toques los existentes.", { budget: B });
    // t8 · cierre en charla
    await runPrompt(page, "Gracias. En una frase: ¿qué contiene la lista?", { budget: B });

    // volver a la obra de la LISTA antes de escanear (si una charla mal ruteada creó otra
    // obra, el canvas quedó mostrando esa — el assert de libItems===1 lo caza aparte)
    await page.evaluate(() => {
      const items = [...document.querySelectorAll("#libList .lib-item")];
      const target = items.find((i) => /Bitácora de vuelo|bit/i.test(i.textContent)) || items[0];
      if (target) target.click();
    });
    await page.waitForTimeout(1200);

    const st = await page.evaluate(() => ({
      userMsgs: document.querySelectorAll("#chat .msg.user").length,
      agentMsgs: document.querySelectorAll("#chat .msg.agent").length,
      errcards: document.querySelectorAll("#chat .errcard").length,
      ledgerContinues: [...document.querySelectorAll("#chat .ledger-note")].filter((n) => /Sigo con|Continuing/.test(n.textContent)).length,
      libItems: document.querySelectorAll("#libList .lib-item").length,
      obra: (document.getElementById("canvas") || {}).textContent || "",
      composerOn: !(document.getElementById("send") || {}).disabled,
    }));

    chk.check("8 turnos del usuario en el hilo", st.userMsgs >= 8, "user=" + st.userMsgs);
    chk.check("el agente respondió en todos", st.agentMsgs >= 6, "agent=" + st.agentMsgs);
    chk.check("cero errcards en 8 turnos", st.errcards === 0, "errcards=" + st.errcards);
    chk.check("bitácora escala: ≥4 continuaciones declaradas (↳ Sigo con)", st.ledgerContinues >= 4, "continues=" + st.ledgerContinues);
    chk.check("UNA obra (el hilo edita, no apila)", st.libItems === 1, "lib=" + st.libItems);
    const kept = MARKS.filter((m) => st.obra.includes(m));
    chk.check("contexto PERSISTE: los 6 marcadores sobreviven en la obra final",
      kept.length === MARKS.length, "kept=" + kept.join(","));
    chk.check("composer re-habilitado al cierre", st.composerOn);

    // la bitácora de la obra registró el hilo (ⓘ Detalles → turnos; el panel PINTA async
    // tras el fetch de versiones — esperar el contenido, no leer al toque)
    await page.click("#infoBtn").catch(() => {});
    await page.waitForSelector("#artInfo section", { timeout: 8_000 }).catch(() => {});
    const steps = await page.evaluate(() => document.querySelectorAll("#artInfo .ai-step").length);
    chk.check("Detalles: bitácora con ≥5 entradas del hilo", steps >= 5, "steps=" + steps);

    const errs = realConsoleErrors(consoleErrors, pageErrors);
    chk.check("consola limpia", errs.length === 0, errs.slice(0, 3).join(" | "));
    await snap(page, "l1-conversacion");
  } finally { await ctx.close(); }
  return chk.finish();
}
