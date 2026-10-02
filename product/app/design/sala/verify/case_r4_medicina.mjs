/* case_r4_medicina.mjs — R4 · héroe MEDICINA: DICOM → volumen 3D rotable en la Sala.
 * Opus (shim) opera el visor READ-ONLY: render_volume_3d corre marching cubes sobre la
 * máscara REAL del CT (Orthanc local) → *.volume3d.json → renderer volume3d (three.js).
 * PRE-REQUISITO de infra: Orthanc en :8042 con la serie CT de prueba cargada. */
import { runHero } from "./_hero.mjs";

export async function run(browser, state) {
  return runHero(browser, state, {
    title: "R4 Medicina DICOM 3D (héroe vivo)",
    puppetKey: "qa-hero-med",
    prompt: "Generá el volumen 3D rotable del pulmón con render_volume_3d (y aclarará que es dev/test, no diagnóstico).",
    expectTools: ["render_volume_3d"],
    obraType: "volume3d",
    canvasClass: "sala-rich-volume3d",
    uiMarker: "#canvas iframe, #canvas .aleph-render",
    snapName: "r4-medicina",
    assertObra(chk, obra) {
      chk.check("obra: mesh real (vertices+faces b64)",
        !!(obra && obra.vertices_b64 && obra.faces_b64 && (obra.n_triangles || 0) > 0),
        "n_triangles=" + (obra && obra.n_triangles));
    },
  });
}
