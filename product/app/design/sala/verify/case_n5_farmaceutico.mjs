/* case_n5_farmaceutico.mjs — N5 · nicho nuevo FARMACIA — **GATED por catálogo** (igual N4).
 *
 * El gate estuvo CERRADO hasta el batch a4-medicina (openFDA aterrizó 2026-07-04 noche,
 * org/DECISIONS.md). Cuando abre, el puppet se FORJA DESDE EL CATÁLOGO: el átomo openfda
 * (keyless, solo lectura, «NO consejo médico») aporta belt_ref+tools reales.
 * El caso: prospecto REAL de un fármaco de la API pública de la FDA → informe con la
 * data del label (no de memoria) + el descargo dev/no-consejo-médico. */
import { BACK } from "./_env.mjs";
import { newSalaPage, runPrompt, snap, realConsoleErrors, makeChecker } from "./_drive.mjs";

const NAME = "QA N5 Farmaceutico (catalogo)";

async function forgeFromCatalog(state) {
  const auth = { "Content-Type": "application/json", Authorization: "Bearer " + state.user.session_token };
  const cat = await fetch(BACK + "/v1/atoms/catalog", { headers: auth }).then((r) => r.json());
  const fda = (cat.atoms || []).find((a) => a.id === "openfda" && a.belt_ref && (a.tools || []).length);
  if (!fda) return { gated: true };

  const recipe = {
    schema_version: "v1",
    meta: { name: NAME, nicho: "medicina" },
    model: { alias: "brain", primary: "brain", fallback: "brain", base_url: "http://127.0.0.1:8923/v1", temperature: 0.2, max_tokens: 1400, max_turns: 8 },
    belt: { belt_refs: [fda.belt_ref], tool_filters: { openfda: fda.tools } },
    framing: { inline: "Sos un asistente FARMACÉUTICO de referencia (DEV/TEST, NO consejo médico ni diagnóstico — aclaralo siempre). Todo dato de un fármaco sale de openFDA en vivo (labels, eventos adversos, recalls); jamás de memoria. Citá qué endpoint usaste." },
    rag: { enabled: false }, keys: {},
    gates: { money_touch: "needs_ok", send: "needs_ok" },
  };
  const existing = await fetch(BACK + "/v1/users/" + state.user.id + "/puppets", { headers: auth }).then((r) => r.json());
  const prev = (existing.puppets || []).find((p) => (p.name || "").trim() === NAME);
  if (prev) return { gated: false, id: prev.id };
  const r = await fetch(BACK + "/v1/puppets", {
    method: "POST", headers: auth,
    body: JSON.stringify({ owner_id: state.user.id, name: NAME, nicho: "medicina", config: recipe }),
  });
  if (r.status !== 201) throw new Error("forja N5 rechazada: HTTP " + r.status + " — " + (await r.text()).slice(0, 300));
  return { gated: false, id: (await r.json()).id };
}

export async function run(browser, state) {
  const chk = makeChecker("N5 farmacéutico openFDA (forjado del catálogo, vivo)");
  const forged = await forgeFromCatalog(state);
  if (forged.gated) {
    chk.check("GATED-SKIP: átomo openfda aún no está en el catálogo — N5 espera", true);
    const out = chk.finish(); out.gated = true; return out;
  }
  chk.check("gate: átomo openfda presente en /v1/atoms/catalog → forja del catálogo", true);

  const { ctx, page, consoleErrors, pageErrors } = await newSalaPage(browser, state.user, { puppet: forged.id });
  try {
    const { out } = await runPrompt(page,
      "Trae del prospecto oficial (label) del ibuprofeno las advertencias principales y el uso indicado, y entrega una ficha corta de referencia citando la fuente.",
      { budget: 600_000 });

    const rec = (out && out.record) || {};
    const calls = (rec.tool_calls || []).map((c) => c.tool);
    chk.check("motor: run ok", out && out.ok !== false, "out.ok=" + (out && out.ok));
    chk.check("motor: degraded == null", rec.degraded == null, JSON.stringify(rec.degraded || null).slice(0, 150));
    chk.check("motor: terminó en el brain real", rec.model_final === "claude-code-opus-4.8", "model_final=" + rec.model_final);
    chk.check("motor: consultó openFDA de verdad", calls.some((t) => /^openfda_/.test(t)), JSON.stringify(calls));
    chk.check("motor: toda tool cableada", calls.length > 0 && calls.every((t) => (rec.tools_cabled || []).includes(t)),
      JSON.stringify(calls));

    await page.waitForFunction(() => {
      const c = document.getElementById("canvas");
      return c && /sala-informe|ar-prose/.test(c.className);
    }, { timeout: 25_000 }).catch(() => {});
    const ui = await page.evaluate(() => {
      const c = document.getElementById("canvas");
      return { cls: c ? c.className : "", text: c ? c.textContent : "" };
    });
    chk.check("ui: ficha en el canvas", /sala-informe|ar-prose/.test(ui.cls), ui.cls);
    chk.check("ui: data real del label (ibuprofeno + advertencias)", /ibuprofen/i.test(ui.text) && /adverten|warning/i.test(ui.text));
    chk.check("ui: descargo honesto (no consejo médico)", /no (es |constituye )?(un )?consejo médico|referencia|dev\/test/i.test(ui.text),
      ui.text.slice(0, 150));

    const errs = realConsoleErrors(consoleErrors, pageErrors);
    chk.check("consola limpia", errs.length === 0, errs.slice(0, 3).join(" | "));
    await snap(page, "n5-farmaceutico");
  } finally { await ctx.close(); }
  return chk.finish();
}
