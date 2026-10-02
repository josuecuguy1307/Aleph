import { createCodesignApi, type CodesignApi, type IpcTransport } from '../../preload/index';
import { invokeHttpIpc } from './http-ipc';

/**
 * EL TRANSPORTE DE LA WEBVIEW — Diseño corriendo DENTRO de Aleph.
 *
 * [Aleph · 2026-08-11] Antes, este archivo REPLICABA la fachada del preload: un `Proxy` que
 * traducía `snapshots.listDesigns()` a un nombre de canal con tres tablas escritas a mano
 * (`TOP_LEVEL_CHANNELS`, `SPECIAL_CHANNELS`, `EVENT_CHANNELS`) y un `kebab()`. Reproducía los
 * NOMBRES, pero no lo que la fachada real HACE con los argumentos, que es su trabajo
 * principal: de sus 105 invocaciones, 40 agregan el sobre `{ schemaVersion: 1 }` y 38
 * nombran argumentos posicionales (`createDesign(name)` → `{ name }`).
 *
 * El resultado se veía al abrir el workspace, y cada arreglo destapaba el siguiente error:
 *   1. `snapshots:v1:list-designs expects an object payload`   (faltaba el sobre)
 *   2. `snapshots:v1:create-design expects an object with name` (faltaba el sobre acá también)
 *   3. `name must be a non-empty string`                        (el sobre llegó, el name no)
 * Cada uno era la misma causa: una copia de la fachada que no puede mantenerse al día.
 *
 * Ahora no hay copia. `preload/index.ts` expone `createCodesignApi(transport)` y este archivo
 * le pasa el transporte de la webview. Lo único que cambia entre Electron y Aleph es POR DÓNDE
 * viaja el mensaje; QUÉ se manda lo decide un solo archivo. Un canal nuevo en el preload
 * funciona acá sin tocar nada.
 *
 * Las dos puntas ya existían del lado del main: `POST /.aleph/ipc/<canal>` enruta a los 110
 * `ipcMain.handle` capturados, y `/.aleph/events` publica por SSE lo que el main manda con
 * `webContents.send`. Ver `main/headless-bridge.ts`.
 */

type Listener = (event: unknown, payload: never) => void;

function crearTransporteHttp(): IpcTransport {
  // Un solo EventSource para toda la app: el main publica ahí todo lo que antes iba por
  // `webContents.send`, con el canal adentro del mensaje. Se abre perezosamente para no
  // pedirlo si nadie se suscribe.
  let events: EventSource | null = null;
  const porCanal = new Map<string, Set<Listener>>();

  function asegurarEventSource(): void {
    if (events) return;
    events = new EventSource('/.aleph/events');
    events.onmessage = (event) => {
      const mensaje = JSON.parse(event.data) as { channel?: string; payload?: unknown };
      if (!mensaje.channel) return;
      // La firma de Electron es `(event, payload)`; el primer argumento no se usa en este
      // camino, pero se respeta para que los listeners del preload no cambien de forma.
      for (const listener of porCanal.get(mensaje.channel) ?? []) {
        listener(undefined, mensaje.payload as never);
      }
    };
  }

  return {
    async invoke(channel: string, ...args: unknown[]): Promise<unknown> {
      return invokeHttpIpc(channel, args);
    },

    on(channel: string, listener: Listener): void {
      asegurarEventSource();
      const grupo = porCanal.get(channel) ?? new Set<Listener>();
      grupo.add(listener);
      porCanal.set(channel, grupo);
    },

    removeListener(channel: string, listener: Listener): void {
      const grupo = porCanal.get(channel);
      if (!grupo) return;
      grupo.delete(listener);
      if (grupo.size === 0) porCanal.delete(channel);
    },
  };
}

/**
 * Instala la fachada en `window.codesign`, con el mismo nombre y la misma forma que expone
 * `contextBridge` en Electron, para que el renderer no sepa por dónde está hablando.
 */
export function installWebBridge(): void {
  if (window.codesign) return;
  const api = createCodesignApi(crearTransporteHttp()) as CodesignApi;
  window.codesign = api;
  // `window.api.permission` es la otra puerta que el renderer usa (el diálogo de permisos).
  (window as unknown as { api?: { permission?: unknown } }).api = { permission: api.permission };
}
