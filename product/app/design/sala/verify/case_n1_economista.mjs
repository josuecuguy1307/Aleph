/* case_n1_economista.mjs — N1 · nicho nuevo FINANZAS/MACRO: economista con datos reales.
 * worldbank_series (keyless, World Bank Open Data REAL) trae la serie del PIB y emite
 * *.linechart.json al workdir → _capture_rich_obra la surfacea → renderer linechart
 * (serie temporal dedicada, DONE-BAR tipo #11) con procedencia visible. */
import { runHero } from "./_hero.mjs";

export async function run(browser, state) {
  return runHero(browser, state, {
    title: "N1 Economista worldbank→linechart (vivo)",
    puppetKey: "qa-n1-economista",
    prompt: "Tráeme la serie del PIB de Ecuador 2017-2023 del Banco Mundial (US$ a precios actuales) y muéstramela como serie temporal.",
    expectTools: ["worldbank_series"],
    obraType: "linechart",
    canvasClass: "sala-rich-linechart",
    uiMarker: "#canvas .ar-chart-fig.ar-linechart",
    snapName: "n1-economista",
    assertObra(chk, obra) {
      const labels = (obra && obra.labels) || [];
      const data = ((obra && obra.series) || [{}])[0].data || [];
      chk.check("obra: serie real (≥5 años, datos 1:1 con labels)",
        labels.length >= 5 && data.length === labels.length,
        "labels=" + labels.length + " data=" + data.length);
      chk.check("obra: procedencia World Bank en la fuente",
        /World Bank/.test((obra && obra.source) || ""), (obra && obra.source || "").slice(0, 120));
    },
  });
}
