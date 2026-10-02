/* case_r2_quant.mjs — R2 · héroe FINANZAS: el backtest loop llega a la Sala.
 * Opus (shim) optimiza la cartera solo: backtest_portfolio (precios Yahoo REALES) itera
 * Sharpe vs objetivo 1.2 → convergence.json (curvas de equity) → renderer convergence. */
import { runHero } from "./_hero.mjs";

export async function run(browser, state) {
  return runHero(browser, state, {
    title: "R2 Quant Sharpe (héroe vivo)",
    puppetKey: "qa-hero-quant",
    prompt: "Optimizá la cartera para maximizar el Sharpe (objetivo ≥ 1.2), iterando vos solo con backtest_portfolio hasta converger.",
    expectTools: ["backtest_portfolio"],
    obraType: "convergence",
    canvasClass: "sala-rich-convergence",
    uiMarker: "#canvas .ar-conv",
    snapName: "r2-quant",
    assertObra(chk, obra) {
      const its = (obra && obra.iterations) || [];
      chk.check("obra: ≥2 iteraciones reales del loop", its.length >= 2, "n=" + its.length);
      chk.check("obra: Sharpe final ≥ inicial (el loop mejoró de verdad)",
        its.length >= 2 && its[its.length - 1].value >= its[0].value,
        JSON.stringify(its.map((i) => ({ n: i.n, v: i.value, p: i.passed }))));
    },
  });
}
