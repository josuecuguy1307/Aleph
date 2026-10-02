/* [Aleph] Stub de `electron` para el bundle del RENDERER.
 *
 * El renderer importa `createCodesignApi` de `preload/index.ts` para reusar la fachada en
 * vez de copiarla (ver el comentario grande de ese archivo). Ese módulo importa `electron`
 * en su cabecera porque también se compila como preload de verdad; en el navegador no hay
 * tal módulo, así que el alias de `electron.vite.config.ts` lo trae acá.
 *
 * Los dos símbolos existen para que el import resuelva y NADA MÁS: por el camino web, la
 * fachada recibe su transporte HTTP por parámetro y `contextBridge` no se usa. Si alguna vez
 * alguien los llama de verdad, es un error de cableado y tiene que doler, no degradar en
 * silencio — de ahí que tiren en vez de devolver undefined. */
export const contextBridge = {
  /** Marca que este `electron` es el stub del navegador, no el módulo real. La lee
   *  `preload/index.ts` para NO ejecutar su efecto de módulo cuando lo importa el renderer. */
  __alephStub: true,
  exposeInMainWorld(): never {
    throw new Error('contextBridge no existe en la webview de Aleph: la fachada se instala con createCodesignApi()');
  },
};

export const ipcRenderer = {
  invoke(): never {
    throw new Error('ipcRenderer no existe en la webview de Aleph: el transporte es HTTP (/.aleph/ipc/)');
  },
  on(): never {
    throw new Error('ipcRenderer no existe en la webview de Aleph: los eventos llegan por SSE (/.aleph/events)');
  },
  removeListener(): never {
    throw new Error('ipcRenderer no existe en la webview de Aleph: los eventos llegan por SSE (/.aleph/events)');
  },
};
