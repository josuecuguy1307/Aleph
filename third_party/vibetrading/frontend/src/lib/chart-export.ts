/** Attach the anchor so native download bridges can observe the click. */
export function downloadChartImage(url: string, filename: string): void {
  const encoded = url.match(/^data:(image\/\w+);base64,(.*)$/s);
  if (!encoded) throw new Error("El gráfico no produjo una imagen válida.");
  const bytes = Uint8Array.from(atob(encoded[2]), character => character.charCodeAt(0));
  const blobUrl = URL.createObjectURL(new Blob([bytes], { type: encoded[1] }));
  const anchor = document.createElement("a");
  anchor.href = blobUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(blobUrl);
}

export function chartImageTool(chart: { getConnectedDataURL: (options: { type: "png"; pixelRatio: number; backgroundColor: string; connectedBackgroundColor: string; excludeComponents: string[] }) => string }, filename: string, backgroundColor: string) {
  return {
    show: true,
    title: "Descargar PNG",
    icon: "path://M4.7,22.9L29.3,45.5L54.7,23.4M4.6,43.6L4.6,58L53.8,58L53.8,43.6M29.2,45.1L29.2,0",
    onclick: () => downloadChartImage(chart.getConnectedDataURL({ type: "png", pixelRatio: 2, backgroundColor, connectedBackgroundColor: backgroundColor, excludeComponents: ["toolbox"] }), filename),
  };
}
