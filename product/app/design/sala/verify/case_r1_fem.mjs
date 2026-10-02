/* case_r1_fem.mjs — R1 · héroe INGENIERÍA: el loop FEM autónomo llega a la Sala.
 * Opus (shim) dimensiona la viga solo: run_fem_analysis (CalculiX REAL, headless) itera
 * von Mises vs límite 250 MPa → convergence.json → renderer convergence (it.N + PASA). */
import { runHero } from "./_hero.mjs";

export async function run(browser, state) {
  return runHero(browser, state, {
    title: "R1 FEM von Mises (héroe vivo)",
    puppetKey: "qa-hero-fem",
    prompt: "Dimensioná la viga en voladizo para que no falle (von Mises ≤ 250 MPa), iterando vos solo con run_fem_analysis hasta que PASE.",
    expectTools: ["run_fem_analysis"],
    obraType: "convergence",
    canvasClass: "sala-rich-convergence",
    uiMarker: "#canvas .ar-conv",
    snapName: "r1-fem",
    assertObra(chk, obra) {
      const its = (obra && obra.iterations) || [];
      chk.check("obra: ≥2 iteraciones reales del loop", its.length >= 2, "n=" + its.length);
      chk.check("obra: la última iteración PASA", !!(its.length && its[its.length - 1].passed),
        JSON.stringify(its.map((i) => ({ n: i.n, v: i.value, p: i.passed }))));
    },
  });
}
