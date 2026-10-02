/* MÉTODO · sección B (editor Simple/Pro + esqueletos) y C (captura + conversar).
 * Importado por verify_metodo.mjs cuando metodo.editor.js existe. */

export async function run({ browser, newPage, PAGE, ok, sleep }) {
  /* ══ B · EDITOR (ES) ═════════════════════════════════════════════════ */
  {
    const { page, errors, calls } = await newPage(browser);
    await page.goto(PAGE, { waitUntil: "load" });
    await page.waitForFunction(() => window.__metodo && window.__metodo.state.methods.length === 2, null, { timeout: 9000 });

    // esqueletos de FORMA (chooser)
    await page.evaluate(() => document.getElementById("metNuevo").click());
    await page.waitForSelector(".met-scrim .sk-opt", { timeout: 5000 });
    const sk = await page.evaluate(() => [...document.querySelectorAll(".sk-opt")].map((b) => b.getAttribute("data-sk")));
    ok(sk.length === 4 && sk.includes("blank") && sk.includes("iape"), "B · chooser con 4 esqueletos de FORMA", JSON.stringify(sk));
    await page.evaluate(() => document.querySelector('.sk-opt[data-sk="iape"]').click());
    await page.waitForFunction(() => window.__metodoEditor, null, { timeout: 5000 });
    const skPh = await page.evaluate(() => [...document.querySelectorAll(".ph")].map((g) => g.getAttribute("data-phase")));
    ok(skPh.length === 4 && skPh[0] === "Investigar" && skPh[3] === "Entregar", "B · esqueleto = 4 fases de forma, cero pasos de oficio", JSON.stringify(skPh));
    const skSteps = await page.evaluate(() => window.__metodoEditor.getMethod().steps.length);
    ok(skSteps === 0, "B · el esqueleto NO trae contenido (0 pasos)");

    // abrir M1 (guard: esqueleto sin tocar → no está dirty)
    await page.evaluate(() => document.querySelectorAll(".met-card")[0].click());
    await page.waitForFunction(() => window.__metodoEditor && window.__metodoEditor.getMethod().id === "m-earnings", null, { timeout: 5000 });
    const est = await page.evaluate(() => ({
      phases: [...document.querySelectorAll(".ph")].map((g) => g.getAttribute("data-phase")),
      rows: document.querySelectorAll(".step[data-id]").length,
      name: document.querySelector(".ed-name").value,
    }));
    ok(est.phases.join("|") === "Recolectar|Analizar|Entregar" && est.rows === 3, "B · M1 abre con sus 3 fases y 3 pasos", JSON.stringify(est));
    ok(est.name === "Cierre de earnings", "B · nombre en el header del editor");

    // agregar un paso (texto libre + Enter) en Analizar
    await page.focus('.ph[data-phase="Analizar"] [data-add]');
    await page.fill('.ph[data-phase="Analizar"] [data-add]', "Cruzar contra el guidance");
    await page.keyboard.press("Enter");
    await sleep(120);
    const afterAdd = await page.evaluate(() => {
      const m = window.__metodoEditor.getMethod();
      const nu = m.steps.find((s) => s.text === "Cruzar contra el guidance");
      return { n: m.steps.length, ph: nu && nu.phase, retries: nu && nu.retries, idx: m.steps.indexOf(nu) };
    });
    ok(afterAdd.n === 4 && afterAdd.ph === "Analizar" && afterAdd.idx === 2, "B · paso nuevo entra al final de SU fase", JSON.stringify(afterAdd));
    ok(afterAdd.retries === 3, "B · schema §2: retries default 3 en paso nuevo");

    // toggle checkpoint
    await page.evaluate(() => document.querySelector('.step[data-id="s1"] [data-ck]').click());
    const ck = await page.evaluate(() => window.__metodoEditor.getMethod().steps.find((s) => s.id === "s1").checkpoint);
    ok(ck === true, "B · toggle checkpoint escribe el schema");

    // reordenar con ▼/▲ — cruza fronteras de fase
    await page.evaluate(() => document.querySelector('.step[data-id="s1"] [data-mv="1"]').click());
    await sleep(80);
    const mv1 = await page.evaluate(() => { const m = window.__metodoEditor.getMethod(); const s = m.steps.find((x) => x.id === "s1"); return { ph: s.phase, order: m.steps.map((x) => x.id).join(",") }; });
    ok(mv1.ph === "Analizar" && mv1.order.indexOf("s1") < mv1.order.indexOf("s2"), "B · ▼ al borde de fase cruza a la siguiente", JSON.stringify(mv1));
    await page.evaluate(() => document.querySelector('.step[data-id="s1"] [data-mv="1"]').click());
    await sleep(80);
    const mv2 = await page.evaluate(() => window.__metodoEditor.getMethod().steps.map((x) => x.id).join(","));
    ok(mv2.indexOf("s2") < mv2.indexOf("s1"), "B · ▼ dentro de la fase intercambia con el siguiente", mv2);
    await page.evaluate(() => { document.querySelector('.step[data-id="s1"] [data-mv="-1"]').click(); });
    await sleep(80);
    await page.evaluate(() => { document.querySelector('.step[data-id="s1"] [data-mv="-1"]').click(); });
    await sleep(80);
    const mv3 = await page.evaluate(() => window.__metodoEditor.getMethod().steps.find((x) => x.id === "s1").phase);
    ok(mv3 === "Recolectar", "B · ▲▲ lo devuelve a su fase original", mv3);

    // colapsar fase
    await page.evaluate(() => document.querySelector('.ph[data-phase="Recolectar"] [data-chev]').click());
    const closed = await page.evaluate(() => document.querySelector('.ph[data-phase="Recolectar"]').classList.contains("closed"));
    ok(closed, "B · colapsar fase (mini-pasos se pliegan)");

    // renombrar fase → los pasos siguen a la fase
    await page.evaluate(() => {
      const inp = document.querySelector('.ph[data-phase="Recolectar"] [data-phname]');
      inp.value = "Juntar"; inp.dispatchEvent(new Event("change"));
    });
    await sleep(80);
    const ren = await page.evaluate(() => window.__metodoEditor.getMethod().steps.find((x) => x.id === "s1").phase);
    ok(ren === "Juntar", "B · renombrar fase re-etiqueta sus pasos", ren);

    // PRO: chips por paso
    await page.evaluate(() => document.querySelector('[data-ed-sw] button[data-sw="pro"]').click());
    await page.waitForSelector(".step-pro", { state: "attached", timeout: 4000 });
    await page.fill('.step[data-id="s2"] [data-pf="executor"]', "excel");
    await page.fill('.step[data-id="s2"] [data-pf="retries"]', "5");
    await page.fill('.step[data-id="s2"] [data-pf="timeout"]', "120");
    const proV = await page.evaluate(() => { const s = window.__metodoEditor.getMethod().steps.find((x) => x.id === "s2"); return { e: s.executor, r: s.retries, t: s.timeout }; });
    ok(proV.e === "excel" && proV.r === 5 && proV.t === 120, "B · chips Pro escriben executor/retries/timeout del schema", JSON.stringify(proV));

    // [REESCRITO · reforma·l] LA VISTA JSON EDITABLE MURIÓ. Medía tres cosas: que el JSON
    // reflejara el spec, que aplicarlo cambiara el método, y que un JSON roto diera un error
    // honesto. Las tres eran garantías DEL EDITOR, no del <textarea>: un método es
    // configuración y se edita con formulario (código → VS Code · configuración → formulario).
    // Pegar JSON a mano sin esquema ni deshacer era la forma más fácil de romper un método
    // guardado. Lo que se mide ahora es que la puerta no está y que la regla que ella
    // custodiaba (4–6 fases) la sigue haciendo cumplir el formulario, unas líneas más abajo.
    const sinJson = await page.evaluate(() => ({
      tab: !![...document.querySelectorAll(".ed-sw button")].find((b) => b.getAttribute("data-t") === "json"),
      area: !!document.querySelector(".ed-json textarea"),
      aplicar: !!document.querySelector("[data-japply]"),
    }));
    ok(!sinJson.tab && !sinJson.area && !sinJson.aplicar,
       "B · la vista JSON editable murió (tab, textarea y [Aplicar])", JSON.stringify(sinJson));
    // …y el método sigue entero: la puerta que se cerró no se llevó ningún dato
    const intacto = await page.evaluate(() => {
      const m = window.__metodoEditor.getMethod();
      return { pasos: m.steps.length, s1: (m.steps.find((x) => x.id === "s1") || {}).text };
    });
    ok(intacto.pasos >= 2 && /10-Q/.test(intacto.s1 || ""),
       "B · el método sigue entero sin la puerta JSON", JSON.stringify(intacto));

    // máximo 6 fases
    await page.evaluate(() => document.querySelector("[data-addph]").click());
    await sleep(60);
    await page.evaluate(() => document.querySelector("[data-addph]").click());
    await sleep(60);
    await page.evaluate(() => document.querySelector("[data-addph]").click());
    await sleep(60);
    const maxed = await page.evaluate(() => ({
      n: document.querySelectorAll(".ph").length,
      dis: document.querySelector("[data-addph]").disabled,
      hint: !!document.querySelector(".ed-addph .hint"),
    }));
    ok(maxed.n === 6 && maxed.dis && maxed.hint, "B · tope 4–6 fases: botón deshabilitado + pista", JSON.stringify(maxed));

    // guardar → PUT con phases[] aditivo + steps
    const putsBefore = calls.filter((c) => c.startsWith("PUT /v1/methods/m-earnings")).length;
    await page.evaluate(() => document.querySelector("[data-ed-save]").click());
    await sleep(250);
    const put = calls.filter((c) => c.startsWith("PUT /v1/methods/m-earnings"));
    ok(put.length === putsBefore + 1, "B · Guardar → PUT /v1/methods/{id}");
    ok(put.length && /"phases"/.test(put[put.length - 1]) && /Bajar el 10-Q/.test(put[put.length - 1]), "B · el PUT viaja con steps + phases (campo aditivo)", (put[put.length - 1] || "").slice(0, 140));
    const cleanAfter = await page.evaluate(() => document.querySelector("[data-ed-save]").disabled);
    ok(cleanAfter, "B · tras guardar el botón vuelve a reposo (sin dirty)");

    // validación honesta: sin nombre NO hay PUT
    await page.evaluate(() => { const n = document.querySelector(".ed-name"); n.value = ""; n.dispatchEvent(new Event("input")); });
    await page.evaluate(() => document.querySelector("[data-ed-save]").click());
    await sleep(200);
    const put2 = calls.filter((c) => c.startsWith("PUT /v1/methods/m-earnings")).length;
    const toastOn = await page.evaluate(() => document.getElementById("metToast").classList.contains("on"));
    ok(put2 === put.length && toastOn, "B · validación: sin nombre no se guarda + aviso honesto");

    ok(errors.length === 0, "B · 0 errores JS", errors.slice(0, 3).join(" | "));
    await page.close();
  }

  /* ══ C · CAPTURA + CONVERSAR ═════════════════════════════════════════ */
  {
    const { page, errors, calls } = await newPage(browser);
    await page.route("**/v1/methods/structure", (r) => {
      calls.push("POST /v1/methods/structure " + (r.request().postData() || "").slice(0, 80));
      return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ draft: { name: "Cotización", steps: [
        { id: "c1", text: "Llamar al cliente", phase: "Contacto", checkpoint: false, executor: null, evidence_hint: null, timeout: null, retries: 3 },
        { id: "c2", text: "Enviar la cotización", phase: "Cierre", checkpoint: true, executor: null, evidence_hint: null, timeout: null, retries: 3 },
      ] } }) });
    });
    await page.route("**/v1/methods/m-earnings/propose_edit", (r) => {
      calls.push("POST propose_edit");
      return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ summary: "Valida el RUC antes de enviar y afina el análisis.", proposal: { steps: [
        { id: "s1", text: "Bajar el 10-Q", phase: "Recolectar", checkpoint: false, executor: "sec_edgar", evidence_hint: null, timeout: null, retries: 3 },
        { id: "s2", text: "Comparar márgenes YoY contra guidance", phase: "Analizar", checkpoint: false, executor: null, evidence_hint: null, timeout: null, retries: 3 },
        { id: "s9", text: "Validar el RUC del cliente", phase: "Analizar", checkpoint: false, executor: null, evidence_hint: null, timeout: null, retries: 3 },
      ] } }) });
    });
    await page.goto(PAGE, { waitUntil: "load" });
    await page.waitForFunction(() => window.__metodo && window.__metodo.state.methods.length === 2, null, { timeout: 9000 });

    // captura: pegar texto → estructurar → borrador en el editor
    await page.evaluate(() => document.getElementById("metTraer").click());
    await page.waitForSelector(".met-scrim [data-cap-ta]", { timeout: 5000 });
    await page.fill(".met-scrim [data-cap-ta]", "llamo al cliente, le cotizo y le envío la propuesta");
    await page.evaluate(() => document.querySelector("[data-cap-go]").click());
    await page.waitForSelector(".ed-banner", { timeout: 5000 });
    const cap = await page.evaluate(() => {
      const m = window.__metodoEditor.getMethod();
      return { name: document.querySelector(".ed-name").value, n: m.steps.length, id: m.id || null,
        banner: document.querySelector(".ed-banner").textContent };
    });
    ok(cap.n === 2 && cap.name === "Cotización" && cap.id === null, "C · structure → borrador SIN id (se crea al guardar)", JSON.stringify(cap));
    ok(/Borrador estructurado por el cerebro/.test(cap.banner), "C · banner honesto: lo estructuró el cerebro, lo pules tú");
    ok(calls.some((c) => c.startsWith("POST /v1/methods/structure")), "C · el seam structure recibió el texto");

    // guardar el borrador → POST create
    await page.evaluate(() => document.querySelector("[data-ed-save]").click());
    await sleep(250);
    ok(calls.some((c) => c.startsWith("POST /v1/methods ") || c === "POST /v1/methods"), "C · guardar borrador → POST /v1/methods (create)");

    // conversar sobre M1: diff propuesto → aceptar/rechazar (la card por NOMBRE:
    // tras crear el borrador, el nuevo método quedó primero en la lista)
    await page.evaluate(() => [...document.querySelectorAll(".met-card")].find((c) => /Cierre de earnings/.test(c.textContent)).click());
    await page.waitForFunction(() => window.__metodoEditor && window.__metodoEditor.getMethod().id === "m-earnings", null, { timeout: 5000 });
    await page.fill("[data-conv-in]", "agrega un paso que valide el RUC antes de enviar");
    await page.evaluate(() => document.querySelector("[data-conv-go]").click());
    await page.waitForSelector(".ed-diff", { timeout: 5000 });
    const diff = await page.evaluate(() => ({
      add: document.querySelectorAll(".ed-diff .dr.add").length,
      mod: document.querySelectorAll(".ed-diff .dr.mod").length,
      del: document.querySelectorAll(".ed-diff .dr.del").length,
      sum: document.querySelector(".ed-diff .sum").textContent,
    }));
    ok(diff.add === 1 && diff.mod === 1 && diff.del === 1, "C · diff: +1 nuevo · ~1 cambia · −1 se quita", JSON.stringify(diff));
    ok(/RUC/.test(diff.sum), "C · el resumen del cerebro se muestra");

    // rechazar → nada cambia
    await page.evaluate(() => document.querySelector("[data-diff-no]").click());
    await sleep(100);
    const afterNo = await page.evaluate(() => ({ n: window.__metodoEditor.getMethod().steps.length, panel: !!document.querySelector(".ed-diff") }));
    ok(afterNo.n === 3 && !afterNo.panel, "C · Rechazar: el método queda intacto", JSON.stringify(afterNo));

    // proponer de nuevo → aceptar → el método adopta la propuesta
    await page.fill("[data-conv-in]", "agrega un paso que valide el RUC antes de enviar");
    await page.evaluate(() => document.querySelector("[data-conv-go]").click());
    await page.waitForSelector(".ed-diff", { timeout: 5000 });
    await page.evaluate(() => document.querySelector("[data-diff-ok]").click());
    await sleep(120);
    const afterOk = await page.evaluate(() => {
      const m = window.__metodoEditor.getMethod();
      return { ids: m.steps.map((s) => s.id).join(","), dirtyBtn: !document.querySelector("[data-ed-save]").disabled };
    });
    ok(afterOk.ids === "s1,s2,s9", "C · Aceptar: pasos = propuesta (s3 fuera, s9 dentro)", afterOk.ids);
    ok(afterOk.dirtyBtn, "C · aceptar deja el método editado SIN auto-guardar (persiste al Guardar)");

    ok(errors.length === 0, "C · 0 errores JS", errors.slice(0, 3).join(" | "));

    /* ══ C+ · fixes del review adversarial (probados, no razonados) ═════ */
    // renombrar HACIA una fase existente = FUSIONAR (no duplicar el grupo)
    await page.reload({ waitUntil: "load" });
    await page.waitForFunction(() => window.__metodo && window.__metodo.state.methods.length === 2, null, { timeout: 9000 });
    await page.evaluate(() => [...document.querySelectorAll(".met-card")].find((c) => /Cierre de earnings/.test(c.textContent)).click());
    await page.waitForFunction(() => window.__metodoEditor && window.__metodoEditor.getMethod().id === "m-earnings", null, { timeout: 5000 });
    await page.evaluate(() => {
      const inp = document.querySelector('.ph[data-phase="Recolectar"] [data-phname]');
      inp.value = "Analizar"; inp.dispatchEvent(new Event("change"));
    });
    await sleep(120);
    const merged = await page.evaluate(() => ({
      groups: [...document.querySelectorAll(".ph")].map((g) => g.getAttribute("data-phase")),
      s1ph: window.__metodoEditor.getMethod().steps.find((s) => s.id === "s1").phase,
      dupIds: document.querySelectorAll('.step[data-id="s1"]').length,
    }));
    ok(merged.groups.filter((g) => g === "Analizar").length === 1 && merged.s1ph === "Analizar" && merged.dupIds === 1,
      "C+ · renombrar a fase existente FUSIONA (sin grupos ni data-id duplicados)", JSON.stringify(merged));

    // doble click en Guardar con latencia → UN solo PUT (guard de vuelo)
    await page.unroute("**/v1/methods/m-earnings");
    let putsSlow = 0;
    await page.route("**/v1/methods/m-earnings", async (r) => {
      if (r.request().method() === "PUT") { putsSlow++; await sleep(350); }
      let b = {}; try { b = JSON.parse(r.request().postData() || "{}"); } catch (e) {}
      return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(Object.assign({ id: "m-earnings" }, b)) });
    });
    await page.evaluate(() => { const b = document.querySelector("[data-ed-save]"); b.click(); b.click(); });
    await sleep(700);
    ok(putsSlow === 1, "C+ · doble click en Guardar → UN solo PUT (guard de vuelo)", String(putsSlow));

    // 'constructor' como nombre de fase = contenido válido, no crashea (mapa sin prototipo)
    const proto = await page.evaluate(async () => {
      const api = await import("./metodo.api.js");
      const g = api.phasesOf({ steps: [{ id: "x", text: "t", phase: "constructor" }, { id: "y", text: "u", phase: "toString" }] });
      return g.map((p) => p.name).join(",");
    });
    ok(proto === "constructor,toString", "C+ · fase 'constructor'/'toString' no crashea (Object.create(null))", proto);

    // [REESCRITO · reforma·l] el tope 4–6 fases se medía "por la puerta JSON". Muerta esa
    // puerta, la regla se hace cumplir donde el usuario realmente crea fases: el botón.
    await page.evaluate(() => document.querySelector('[data-ed-sw] button[data-sw="pro"]').click());
    await sleep(80);
    const tope = await page.evaluate(() => {
      for (let i = 0; i < 10; i++) {
        const b = document.querySelector("[data-addph]");
        if (!b || b.disabled) break;
        b.click();
      }
      const b = document.querySelector("[data-addph]");
      return { disabled: !!(b && b.disabled), hint: (document.querySelector(".ed-addph .hint") || {}).textContent || "",
               fases: document.querySelectorAll(".ph").length };
    });
    ok(tope.disabled && /4–6 fases/.test(tope.hint),
       "C+ · pasadas las 6 fases el formulario NO deja seguir, y dice la regla", `${tope.fases} fases · ${tope.hint}`);

    await page.close();
  }
}
