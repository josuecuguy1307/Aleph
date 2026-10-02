/* case_m_delegacion.mjs — M1 delegación VISIBLE + M2 memoria por task-threading.
 *
 * M1: el padre (qa-m-delegador, cero tools propias) DELEGA en «Sub-agente Research»
 * (catalog/agents/research-sub) y la delegación se VE: chip "↳ Le pedí a «X»…" en el
 * chat + entrada .ai-deleg en la Bitácora (ⓘ Detalles) con los pasos del hijo.
 *
 * M2: memoria del hilo por TASK-THREADING EXPLÍCITO — el dato del turno 1 (código de
 * proyecto) tiene que viajar EN el `task` de la delegación del turno 2 (visible en la
 * bitácora) y el resultado del hijo volver y persistir en la obra.
 *
 * ── GAP DOCUMENTADO (M2, prohibido tocar delegation.py) ─────────────────────────
 * NO existe memoria automática padre→hijo: el canal es SOLO el string `task`.
 *   · delegation.py · RIEL #5 `bridge_child_result` — "sólo el resultado cruza, jamás
 *     el contexto del hijo": el padre recibe {sub_agente, ok, resultado} y nada más.
 *   · delegation.py · schema de la fn delegada — "Pasale la tarea concreta en `task`;
 *     corre con SU propio [contexto]": el hijo NO ve la conversación del padre.
 *   · delegation.py · RIEL #4 `_sub_workdir` — workdir AISLADO por sub-run.
 *   · Ver platform/assembler/DELEGATION-NOTES.md (rieles y decisiones 1-8).
 * Si el usuario da un dato en el turno 1 y el padre NO lo re-inyecta en `task`, el hijo
 * jamás lo ve. Este caso pasa en verde SOLO si el threading explícito funciona — y ese
 * es exactamente el contrato de hoy. Memoria automática = mejora futura (fuera de scope). */
import { newSalaPage, runPrompt, snap, realConsoleErrors, makeChecker } from "./_drive.mjs";

export async function run(browser, state) {
  const chk = makeChecker("M1+M2 delegación visible + task-threading (vivo)");
  const { ctx, page, consoleErrors, pageErrors } = await newSalaPage(browser, state.user, {
    puppet: state.puppets["qa-m-delegador"],
  });
  try {
    // ── turno 1: el dato del usuario entra al hilo (charla, sin obra) ──
    await runPrompt(page, "Un dato para lo que sigue: mi código de proyecto es AX-7791. Confírmame que lo tienes.",
      { budget: 300_000 });

    // ── turno 2: la tarea que OBLIGA a threadear el dato en la delegación ──
    const { out } = await runPrompt(page,
      "Pídele al sub-agente que sume 700 más 91, etiquetando la tarea con mi código de proyecto, y preséntame el resultado etiquetado.",
      { budget: 600_000 });

    // ── capa MOTOR: delegación real + threading visible en el task ──
    // el record guarda args de la delegación como STRING JSON acotado (_trim) — parsear igual
    // que el frontend (_delegTask) para leer la tarea que de verdad viajó al hijo.
    const rec = (out && out.record) || {};
    const dels = (rec.tool_calls || []).filter((c) => c.delegated);
    const subs = rec.sub_runs || [];
    const rawArgs = dels.length ? dels[0].args : "";
    let task = "";
    if (rawArgs && typeof rawArgs === "object") task = rawArgs.task || rawArgs.tarea || "";
    else if (typeof rawArgs === "string") {
      try { const o = JSON.parse(rawArgs); task = (o && (o.task || o.tarea)) || ""; }
      catch { const m = rawArgs.match(/"(?:task|tarea)"\s*:\s*"((?:[^"\\]|\\.)*)/); task = m ? m[1] : ""; }
    }
    chk.check("motor: run ok", out && out.ok !== false, "out.ok=" + (out && out.ok));
    chk.check("motor: terminó en el brain real", rec.model_final === "claude-code-opus-4.8", "model_final=" + rec.model_final);
    chk.check("M1 motor: delegó de verdad (tool_call delegated + sub_run)", dels.length >= 1 && subs.length >= 1,
      "delegated=" + dels.length + " sub_runs=" + subs.length);
    chk.check("M2 motor: el dato del turno 1 viaja EN el task del hijo (threading explícito)",
      /AX-?7791/i.test(task), "task=" + String(task).slice(0, 140));
    // 791 REAL del cómputo del hijo (no el 791 de "AX-7791"): se descuenta la etiqueta antes
    const childAns = String((subs[0] || {}).answer || "");
    chk.check("M2 motor: el hijo COMPUTÓ y devolvió 791 (no un eco de la etiqueta)",
      /\b791\b/.test(childAns.replace(/AX-?7791/gi, "")), "child=" + childAns.slice(0, 120));

    // ── capa UI: la delegación SE VE (chip en chat + bitácora ai-deleg) ──
    // el chip llega tras el caption ASÍNCRONO (closeObra → /v1/obra-caption → pushObraCard):
    // esperar el sub, no leerlo al toque.
    await page.waitForFunction(() =>
      [...document.querySelectorAll("#chat .obracard .oc-sub")].some((n) => /Le pedí a|I asked/.test(n.textContent)),
      { timeout: 15_000 }).catch(() => {});
    const chip = await page.evaluate(() => ({
      subs: [...document.querySelectorAll("#chat .obracard .oc-sub")].map((n) => n.textContent),
    }));
    chk.check("M1 ui: chip de delegación en el chat («Le pedí a …»)",
      chip.subs.some((s) => /Le pedí a|I asked/.test(s)), JSON.stringify(chip.subs).slice(0, 160));

    await page.click("#infoBtn").catch(() => {});
    await page.waitForSelector("#artInfo .ai-deleg", { timeout: 5_000 }).catch(() => {});
    const deleg = await page.evaluate(() => {
      const d = document.querySelector("#artInfo .ai-deleg");
      const head = d ? d.querySelector(".dt") : null;
      return { present: !!d, head: head ? head.textContent : "", full: head ? (head.getAttribute("title") || "") : "" };
    });
    chk.check("M1 ui: bitácora muestra la delegación (.ai-deleg)", deleg.present, deleg.head.slice(0, 120));
    // la línea se corta a 80 chars para el layout; el task COMPLETO vive en el tooltip (title)
    chk.check("M2 ui: el task threadeado es VISIBLE en la bitácora (línea+tooltip)",
      /AX-?7791/i.test(deleg.head + " " + deleg.full), (deleg.head + " ⧉ " + deleg.full).slice(0, 200));

    // ── M2: persiste — la obra final lleva el resultado etiquetado (791 real + etiqueta) ──
    const obraTxt = await page.evaluate(() => (document.getElementById("canvas") || {}).textContent || "");
    chk.check("M2 ui: resultado etiquetado persiste en la obra",
      /\b791\b/.test(obraTxt.replace(/AX-?7791/gi, "")) && /AX-?7791/i.test(obraTxt),
      obraTxt.slice(0, 160));

    const errs = realConsoleErrors(consoleErrors, pageErrors);
    chk.check("consola limpia", errs.length === 0, errs.slice(0, 3).join(" | "));
    await snap(page, "m-delegacion");
  } finally { await ctx.close(); }
  return chk.finish();
}
