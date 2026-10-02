/* MÉTODO · sección D — grafo Obsidian VIVO (modo workflow, ORDEN §6 + fallo §5).
 * D1 estático (sin run) · D2 vivo (telemetría inyectada por el hook feed()). */

export async function run({ browser, newPage, PAGE, ok, sleep }) {
  /* ══ D1 · GRAFO ESTÁTICO (sin run: respira; click → editor) ══════════ */
  {
    const { page, errors } = await newPage(browser);
    await page.goto(PAGE + "?view=grafo&method=m-earnings", { waitUntil: "load" });
    await page.waitForFunction(() => window.__metodoGraph, null, { timeout: 9000 });

    const topo = await page.evaluate(() => {
      const g = window.__metodoGraph;
      return { nodes: g.nodes(), edges: g.edges(), estado: document.getElementById("grEstado").innerText,
        nombre: document.getElementById("grNombre").textContent,
        pausaHidden: document.getElementById("grPausa").hidden, editarHidden: document.getElementById("grEditar").hidden };
    });
    const keys = topo.nodes.map((n) => n.key).sort().join(",");
    ok(topo.nodes.length === 3 && keys === "gmail,nucleo,secedgar", "D1 · nodos = Núcleo + SOLO las piezas que el método toca", keys);
    ok(topo.edges.length === 2 && topo.edges.every((e) => e.includes("nucleo")), "D1 · topología: TODA arista es pieza↔Núcleo (jamás pieza↔pieza)", JSON.stringify(topo.edges));
    const core = topo.nodes.find((n) => n.core);
    ok(core.steps.includes("s2"), "D1 · paso de puro razonamiento (executor null) vive en el Núcleo", JSON.stringify(core.steps));
    ok(!topo.nodes.some((n) => /\d/.test(n.label.replace(/10-Q|10-K/, ""))) && !/\b\d+[.)]/.test(topo.estado), "D1 · CERO numeración (ni badges ni orden gráfico)", JSON.stringify(topo.nodes.map((n) => n.label)));
    ok(/respira|sin run/.test(topo.estado), "D1 · estado honesto: sin run, el método respira", topo.estado);
    ok(topo.pausaHidden && !topo.editarHidden, "D1 · sin run: no hay Pausar, sí hay Editar");

    // VISUAL, no solo atributo: [hidden] de verdad oculta (el CSS de autor no lo pisa)
    const vis = await page.evaluate(() => ({
      lib: getComputedStyle(document.getElementById("metLib")).display,
      grafo: getComputedStyle(document.getElementById("metGrafo")).display,
      pausa: getComputedStyle(document.getElementById("grPausa")).display,
    }));
    ok(vis.lib === "none" && vis.grafo !== "none" && vis.pausa === "none",
      "D1 · la biblioteca queda REALMENTE oculta bajo el grafo (display computado, no el atributo)", JSON.stringify(vis));

    // la red RESPIRA sin run (drift orgánico)
    const p1 = await page.evaluate(() => { const n = window.__metodoGraph.nodes().find((x) => x.key === "gmail"); return [n.x, n.y]; });
    await sleep(450);
    const p2 = await page.evaluate(() => { const n = window.__metodoGraph.nodes().find((x) => x.key === "gmail"); return [n.x, n.y]; });
    ok(Math.hypot(p2[0] - p1[0], p2[1] - p1[1]) > 0.05, "D1 · la red respira aún sin run (drift sutil)", JSON.stringify([p1, p2]));

    // click en una pieza → abre SUS pasos en el panel editor
    await page.evaluate(() => window.__metodoGraph._clickNode("sec_edgar"));
    await page.waitForFunction(() => document.getElementById("grDrawer").classList.contains("on") && document.querySelector("#grDrawer .ed"), null, { timeout: 6000 });
    const edd = await page.evaluate(() => {
      const ta = document.querySelector('#grDrawer .step[data-id="s1"] textarea');
      const row = document.querySelector('#grDrawer .step[data-id="s1"]');
      return { txt: ta ? ta.value : "", focused: !!(row && row.style.outline) };
    });
    ok(edd.txt === "Bajar el 10-Q" && edd.focused, "D1 · click en pieza → el/los pasos que la usan, resaltados en el editor", JSON.stringify(edd));

    ok(errors.length === 0, "D1 · 0 errores JS", errors.slice(0, 3).join(" | "));
    await page.close();
  }

  /* ══ D2 · GRAFO VIVO (telemetría real inyectada) ═════════════════════ */
  {
    const { page, errors, calls } = await newPage(browser);
    await page.route("**/v1/spaces/**", (r) => r.fulfill({ status: 200, contentType: "text/event-stream", body: "" }));
    await page.route("**/v1/runs/**", (r) => {
      calls.push(r.request().method() + " " + new URL(r.request().url()).pathname + " " + (r.request().postData() || ""));
      return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
    });
    await page.goto(PAGE + "?view=grafo&method=m-earnings&space=sp-1&run=r-1", { waitUntil: "load" });
    await page.waitForFunction(() => window.__metodoGraph && window.__metodoGraph.state().live, null, { timeout: 9000 });

    // chispa donde la actividad está AHORA (tool → pieza)
    await page.evaluate(() => window.__metodoGraph.feed({ type: "method_step_started", step_id: "s1", executor: "sec_edgar" }));
    let n = await page.evaluate(() => window.__metodoGraph.nodes().find((x) => x.key === "secedgar"));
    ok(n.heat === 1 && n.active && n.ember, "D2 · chispa: la pieza que ejecuta AHORA se enciende", JSON.stringify({ heat: n.heat, active: n.active }));

    // razonamiento puro → chispa en el Núcleo
    await page.evaluate(() => window.__metodoGraph.feed({ type: "method_step_done", executor: "sec_edgar" }));
    await page.evaluate(() => window.__metodoGraph.feed({ type: "method_step_started", step_id: "s2", executor: null }));
    const coreN = await page.evaluate(() => window.__metodoGraph.nodes().find((x) => x.core));
    ok(coreN.heat === 1, "D2 · paso de razonamiento → chispa en el Núcleo");

    // brasa: decae ~30s a residuo tenue que NO se apaga (estela)
    await page.evaluate(() => window.__metodoGraph._tick(5));
    n = await page.evaluate(() => window.__metodoGraph.nodes().find((x) => x.key === "secedgar"));
    ok(n.heat < 1 && n.heat > 0.2, "D2 · brasa: decae tras completar la actividad", String(n.heat));
    await page.evaluate(() => window.__metodoGraph._tick(60));
    n = await page.evaluate(() => window.__metodoGraph.nodes().find((x) => x.key === "secedgar"));
    ok(n.heat >= 0.15 && n.heat <= 0.17, "D2 · la brasa NO se apaga del todo (residuo hasta el fin del run)", String(n.heat));

    // checkpoint: chispa congelada en el Núcleo + estado 'te espera'
    await page.evaluate(() => window.__metodoGraph.feed({ type: "gate_waiting", tool: "gmail" }));
    let st = await page.evaluate(() => ({ s: window.__metodoGraph.state(), chip: document.getElementById("grEstado").innerText }));
    ok(st.s.checkpoint && /te espera/.test(st.chip), "D2 · checkpoint: el proceso te espera (pulso lento en el Núcleo)", st.chip);
    await page.evaluate(() => window.__metodoGraph.feed({ type: "tool_call_finished", tool: "gmail", status: "ok", result: {} }));
    st = await page.evaluate(() => window.__metodoGraph.state());
    ok(!st.checkpoint, "D2 · actividad posterior destraba el checkpoint");

    // fallo §5: pieza trabada en ámbar + card de remedios con las 5 salidas + libre
    await page.evaluate(() => window.__metodoGraph.feed({ type: "method_step_failed", step_id: "s3", executor: "gmail", diagnosis: "credencial faltante", remedies: { suggested: "reconnect", suggested_label: "reconectar gmail" } }));
    st = await page.evaluate(() => ({ s: window.__metodoGraph.state(), n: window.__metodoGraph.nodes().find((x) => x.key === "gmail"), chip: document.getElementById("grEstado").innerText }));
    ok(st.n.failed && st.s.failed && /trabado/.test(st.chip), "D2 · fallo: la pieza queda trabada + estado honesto", st.chip);
    await page.evaluate(() => window.__metodoGraph._clickNode("gmail"));
    await page.waitForSelector("#grDrawer .grfail", { timeout: 5000 });
    const card = await page.evaluate(() => ({
      diag: document.querySelector(".grfail .diag").textContent,
      acts: [...document.querySelectorAll(".grfail .acts button")].map((b) => b.getAttribute("data-rem")),
      free: !!document.querySelector(".grfail [data-rem-free]"),
      stx: (document.querySelector(".grfail .stx") || {}).textContent || "",
    }));
    ok(/credencial faltante/.test(card.diag), "D2 · card de remedios muestra el diagnóstico del Motor B", card.diag);
    ok(card.acts.join(",") === "apply,retry,retry_in,skip,edit" && card.free, "D2 · remedios §5: aplicar/reintentar/en X min/saltar/editar + respuesta libre", JSON.stringify(card.acts));
    ok(/Enviar el resumen/.test(card.stx), "D2 · la card nombra el paso trabado");
    await page.evaluate(() => document.querySelector('.grfail [data-rem="retry"]').click());
    await sleep(250);
    ok(calls.some((c) => c.startsWith("POST /v1/runs/r-1/method/remedy") && /"action":\s*"retry"/.test(c)), "D2 · Reintentar ahora → seam remedy con action=retry", calls.filter((c) => /remedy/.test(c)).join(" | "));
    st = await page.evaluate(() => window.__metodoGraph.state());
    ok(!st.failed, "D2 · el remedio destraba el estado");

    // pausa → editar → reanudar (LA única edición en vivo)
    const strip0 = await page.evaluate(() => ({ pausa: document.getElementById("grPausa").hidden, editar: document.getElementById("grEditar").hidden }));
    ok(!strip0.pausa && strip0.editar, "D2 · corriendo: hay Pausar, NO hay Editar (nada se edita en caliente)");
    await page.evaluate(() => document.getElementById("grPausa").click());
    await sleep(250);
    ok(calls.some((c) => c.startsWith("POST /v1/runs/r-1/method/pause")), "D2 · Pausar → seam pause");
    const strip1 = await page.evaluate(() => ({ paused: window.__metodoGraph.state().paused, editar: document.getElementById("grEditar").hidden, lbl: document.getElementById("grPausa").textContent }));
    ok(strip1.paused && !strip1.editar && /Reanudar/.test(strip1.lbl), "D2 · pausado: aparece Editar + el botón ofrece Reanudar", JSON.stringify(strip1));
    // pausado → click en pieza abre el EDITOR (no la lectura)
    await page.evaluate(() => window.__metodoGraph._clickNode("sec_edgar"));
    await page.waitForFunction(() => document.querySelector("#grDrawer .ed [data-ed-save]"), null, { timeout: 6000 });
    ok(true, "D2 · pausado + click en pieza → editor montado en el drawer");
    await page.evaluate(() => document.getElementById("grPausa").click());
    await sleep(250);
    ok(calls.some((c) => c.startsWith("POST /v1/runs/r-1/method/resume") && /"method"/.test(c)), "D2 · Reanudar → seam resume CON el método (posiblemente editado)");

    // pieza materializada POR LA TELEMETRÍA (review HIGH: método Simple sin executors
    // ya no rinde un Núcleo solo — la tool real crea su nodo, topología intacta)
    await page.evaluate(() => window.__metodoGraph.feed({ type: "tool_call_finished", tool: "yfinance", status: "ok", result: {} }));
    const dyn = await page.evaluate(() => ({
      node: window.__metodoGraph.nodes().find((n) => n.key === "yfinance") || null,
      edges: window.__metodoGraph.edges().filter((e) => e.includes("yfinance")),
    }));
    ok(!!dyn.node && dyn.node.heat === 1, "D2 · tool NO declarada como executor → nodo materializado al vuelo + chispa", JSON.stringify(dyn.node && { key: dyn.node.key, heat: dyn.node.heat }));
    ok(dyn.edges.length === 1 && dyn.edges[0].includes("nucleo"), "D2 · el nodo al vuelo respeta la topología pieza↔Núcleo");

    // cierre del run: la estela queda a la vista
    await page.evaluate(() => window.__metodoGraph.feed({ type: "closed", run_id: "r-1" }));
    const fin = await page.evaluate(() => ({ s: window.__metodoGraph.state(), chip: document.getElementById("grEstado").innerText,
      ember: window.__metodoGraph.nodes().find((x) => x.key === "secedgar").heat }));
    ok(fin.s.closed && /estela|termin/.test(fin.chip), "D2 · closed → estado terminal honesto", fin.chip);
    ok(fin.ember >= 0.15, "D2 · al terminar, la estela completa sigue visible (brasas)", String(fin.ember));

    ok(errors.length === 0, "D2 · 0 errores JS", errors.slice(0, 3).join(" | "));
    await page.close();
  }
}
