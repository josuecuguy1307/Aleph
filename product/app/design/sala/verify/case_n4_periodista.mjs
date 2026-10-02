/* case_n4_periodista.mjs — N4 · nicho nuevo PERIODISMO/RESEARCH — **GATED por catálogo**.
 *
 * Regla del sprint: N4 corre SOLO si los átomos research-live YA aparecen en
 * GET /v1/atoms/catalog (la promoción está decidida; verificamos que el merge llegó).
 * Si no están → GATED-SKIP explícito (JAMÁS correr por receta fixture).
 *
 * Cuando el gate abre, el puppet se FORJA DESDE EL CATÁLOGO (el path del producto):
 * belt.belt_refs[] se construye con los belt_ref de los átomos vivos (crossref keyless +
 * pysandbox) — no de un fixture prefabricado. */
import { BACK } from "./_env.mjs";
import { newSalaPage, runPrompt, snap, realConsoleErrors, makeChecker } from "./_drive.mjs";

const NAME = "QA N4 Periodista (catálogo)";

async function forgeFromCatalog(state) {
  const auth = { "Content-Type": "application/json", Authorization: "Bearer " + state.user.session_token };
  const cat = await fetch(BACK + "/v1/atoms/catalog", { headers: auth }).then((r) => r.json());
  const atoms = cat.atoms || [];
  const byServer = (srv) => atoms.find((a) => a.server === srv && a.belt_ref && (a.tools || []).length);
  const crossref = byServer("crossref");
  const pysandbox = byServer("pysandbox");
  if (!crossref || !pysandbox) return { gated: true, missing: { crossref: !!crossref, pysandbox: !!pysandbox } };

  const recipe = {
    schema_version: "v1",
    meta: { name: NAME, nicho: "research" },
    model: { alias: "brain", primary: "brain", fallback: "brain", base_url: "http://127.0.0.1:8923/v1", temperature: 0.2, max_tokens: 1400, max_turns: 8 },
    belt: {
      belt_refs: [...new Set([crossref.belt_ref, pysandbox.belt_ref])],
      tool_filters: { crossref: crossref.tools, pysandbox: ["run_python"] },
    },
    framing: { inline: "Sos un periodista de datos. Toda afirmación factual sale de una fuente REAL: buscá papers con search_works (DOI verificable) y computá números con run_python. Cerrá con un informe corto citando el DOI." },
    rag: { enabled: false }, keys: {},
    gates: { money_touch: "needs_ok", send: "needs_ok" },
  };
  const existing = await fetch(BACK + "/v1/users/" + state.user.id + "/puppets", { headers: auth }).then((r) => r.json());
  const prev = (existing.puppets || []).find((p) => (p.name || "").trim() === NAME);
  if (prev) return { gated: false, id: prev.id };
  const r = await fetch(BACK + "/v1/puppets", {
    method: "POST", headers: auth,
    body: JSON.stringify({ owner_id: state.user.id, name: NAME, nicho: "research", config: recipe }),
  });
  if (r.status !== 201) throw new Error("forja N4 rechazada: HTTP " + r.status + " — " + (await r.text()).slice(0, 300));
  return { gated: false, id: (await r.json()).id };
}

export async function run(browser, state) {
  const chk = makeChecker("N4 periodista research (forjado del catálogo, vivo)");
  const forged = await forgeFromCatalog(state);
  if (forged.gated) {
    // gate CERRADO: se reporta y NO se corre (regla del sprint: jamás por fixture)
    chk.check("GATED-SKIP: átomos research-live aún no están en el catálogo — N4 espera",
      true, JSON.stringify(forged.missing));
    const out = chk.finish(); out.gated = true; return out;
  }
  chk.check("gate: átomos research-live presentes en /v1/atoms/catalog → forja del catálogo", true);

  const { ctx, page, consoleErrors, pageErrors } = await newSalaPage(browser, state.user, { puppet: forged.id });
  try {
    const { out } = await runPrompt(page,
      "Busca un paper real sobre misinformation en redes sociales, y entrega una nota corta con el hallazgo principal citando el DOI.",
      { budget: 600_000 });

    const rec = (out && out.record) || {};
    const calls = (rec.tool_calls || []).map((c) => c.tool);
    chk.check("motor: run ok", out && out.ok !== false, "out.ok=" + (out && out.ok));
    chk.check("motor: degraded == null", rec.degraded == null, JSON.stringify(rec.degraded || null).slice(0, 150));
    chk.check("motor: terminó en el brain real", rec.model_final === "claude-code-opus-4.8", "model_final=" + rec.model_final);
    chk.check("motor: buscó papers de verdad (search_works)", calls.includes("search_works"), JSON.stringify(calls));
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
    chk.check("ui: nota en el canvas", /sala-informe|ar-prose/.test(ui.cls), ui.cls);
    chk.check("ui: DOI real citado", /10\.\d{4,9}\/[^\s"')\]]+/.test(ui.text));

    const errs = realConsoleErrors(consoleErrors, pageErrors);
    chk.check("consola limpia", errs.length === 0, errs.slice(0, 3).join(" | "));
    await snap(page, "n4-periodista");
  } finally { await ctx.close(); }
  return chk.finish();
}
