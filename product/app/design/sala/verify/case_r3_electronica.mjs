/* case_r3_electronica.mjs — R3 · héroe ELECTRÓNICA: Bode + DRC llegan a la Sala.
 * Opus (shim) dimensiona el filtro RC solo: ac_sweep (ngspice REAL) itera el corte -3 dB
 * vs spec 1 kHz → convergence.json; el diseño final se verifica con run_erc (kicad). */
import { runHero } from "./_hero.mjs";

export async function run(browser, state) {
  return runHero(browser, state, {
    title: "R3 Electrónica Bode+DRC (héroe vivo)",
    puppetKey: "qa-hero-elec",
    prompt: "Diseñá el filtro RC pasa-bajos para la spec de 1000 Hz iterando vos solo con ac_sweep hasta que quede in_spec, y verificá el diseño final con build_filter_schematic + run_erc.",
    expectTools: ["ac_sweep", "run_erc"],
    obraType: "convergence",
    canvasClass: "sala-rich-convergence",
    uiMarker: "#canvas .ar-conv",
    snapName: "r3-electronica",
    assertObra(chk, obra) {
      const its = (obra && obra.iterations) || [];
      chk.check("obra: ≥2 iteraciones reales del loop", its.length >= 2, "n=" + its.length);
    },
  });
}
