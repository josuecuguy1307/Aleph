// [Aleph] Los archivos que el asistente menciona EN CASTELLANO tienen que abrirse.
//
// La puerta original tenía trece palabras y las trece en inglés, así que en una casa que
// contesta en castellano el archivo no entraba en `openTargets`, `resolveArtifacts` no lo
// veía, y el clic no hacía nada — sin error en consola. Estas varas son los mensajes REALES
// con los que se midió el defecto en Oficina.
import { describe, expect, test } from "bun:test";
import { deriveOpenTargets } from "./open-target";

function mensajeDelAsistente(text: string) {
  return [{ id: "m1", role: "assistant", parts: [{ type: "text", text }] }] as never;
}

const archivos = (text: string) =>
  deriveOpenTargets(mensajeDelAsistente(text))
    .filter((t) => t.kind === "file")
    .map((t) => t.value);

describe("menciones de archivo en castellano", () => {
  test("«Creé el archivo …» — el caso exacto que se vio en pantalla", () => {
    expect(archivos("Listo. Creé el archivo con 20 gastos familiares ficticios de octubre: gastos_hogar_octubre.csv"))
      .toContain("gastos_hogar_octubre.csv");
  });

  test("«creé el documento Word …» — el otro archivo de la misma conversación", () => {
    expect(archivos("Listo: creé el documento Word con el cronograma: cronograma_lanzamiento_tienda_online.docx"))
      .toContain("cronograma_lanzamiento_tienda_online.docx");
  });

  test("una palabra con tilde encaja igual", () => {
    expect(archivos("Armé la presentación: charla.pptx")).toContain("charla.pptx");
    expect(archivos("Ya guardé la planilla: ventas.xlsx")).toContain("ventas.xlsx");
  });

  test("el inglés sigue funcionando: no se cambió una lengua por otra", () => {
    expect(archivos("Created the file report.pdf for you")).toContain("report.pdf");
  });

  test("prosa sin ninguna señal de archivo no dispara el escaneo", () => {
    expect(archivos("Te resumo la reunión: se decidió seguir con el plan.")).toHaveLength(0);
  });
});


describe("enlaces explícitos sin prosa adicional", () => {
  test("un enlace relativo solo sigue siendo un candidato verificable", () => {
    const targets = deriveOpenTargets(mensajeDelAsistente("[Abrir Excel Legal](ws_5a4462fc5a62/certificacion-e2e-20260912/legal-exports/revision.xlsx)"));
    expect(targets).toHaveLength(1);
    expect(targets[0]).toMatchObject({kind: "file", value: "ws_5a4462fc5a62/certificacion-e2e-20260912/legal-exports/revision.xlsx", preview: "sheet"});
    expect(targets[0].exists).toBeUndefined();
  });
  test("file URL con espacios se decodifica; esquemas ejecutables no son archivos", () => {
    expect(archivos("[Abrir](file:///tmp/Application%20Support/revision.xlsx)")).toEqual(["/tmp/Application Support/revision.xlsx"]);
    expect(archivos("[Abrir](javascript:revision.xlsx)")).toHaveLength(0);
  });
});
