// Superficie del bundle vendorizado de sala-v2.
//
// Esto es lo ÚNICO que el código de Aleph puede importar del árbol de terceros. Todo lo
// que sala-v2 use tiene que salir de acá, de modo que la frontera con `third_party/` sea
// un archivo legible y no un puñado de rutas profundas repartidas por la pantalla.
//
// Ojo con la ley 2 del plan (se hereda la superficie, JAMÁS su agente): de assistant-ui
// se exportan PRIMITIVAS DE UI y el runtime del hilo. No se exporta —ni se configura—
// nada de `assistant-cloud` (su servicio hospedado), ni `useLocalRuntime` (su loop de
// modelo propio), ni adaptadores de proveedor. El cerebro es siempre Aleph, y llega por
// el adaptador AG-UI de `product/app/design/sala-v2/agui/`.

// React 19 viaja adentro del bundle. Ver el porqué en build.mjs.
import * as ReactNS from "react";
import * as ReactDOMClientNS from "react-dom/client";
export const React = ReactNS;
export const ReactDOMClient = ReactDOMClientNS;

// ── assistant-ui: la superficie ─────────────────────────────────────────────────────────
export {
  AssistantRuntimeProvider,
  ThreadPrimitive,
  ComposerPrimitive,
  MessagePrimitive,
  MessagePartPrimitive,
  ActionBarPrimitive,
  BranchPickerPrimitive,
  ErrorPrimitive,
  ChainOfThoughtPrimitive,
  AttachmentPrimitive,
  ThreadListPrimitive,
  ThreadListItemPrimitive,
} from "@assistant-ui/react";

// Lectura del estado del hilo. `useAuiState` es el hook canónico del store de assistant-ui
// —es el que usan sus propias primitivas por dentro (`react/src/primitives/thread/ThreadIf.ts:16`)—
// y da acceso tipado a `s.thread.isRunning`, `s.thread.isEmpty`, etc.
export { useAuiState } from "@assistant-ui/store";

// ── el puente AG-UI → assistant-ui (la costura que declara el propio repo) ───────────────
export { useAgUiRuntime } from "@assistant-ui/react-ag-ui";

// ── AG-UI: el protocolo ─────────────────────────────────────────────────────────────────
// `AbstractAgent` es el punto de extensión: el adaptador de Aleph lo hereda y traduce el
// sobre de Gate 3 a estos eventos. `EventType` es el vocabulario cerrado de la traducción.
export { AbstractAgent } from "@ag-ui/client";
export { EventType } from "@ag-ui/core";

// `AbstractAgent.run()` devuelve un `Observable<BaseEvent>` de rxjs. rxjs ya viaja en el
// bundle (es dependencia de `@ag-ui/client`); se re-exporta para que el adaptador de Aleph
// —que es ESM plano servido tal cual— pueda construir el suyo sin un segundo rxjs suelto.
export { Observable } from "rxjs";
