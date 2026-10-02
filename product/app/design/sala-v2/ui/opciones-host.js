/* opciones-host.js — EL ADAPTADOR: la interfaz de `aleph-chat.js` sobre el hilo de React.
 * [T2.3 · los widgets del turno llegan a la Sala]
 *
 * EL MOTOR NO SE TOCA, Y ESE ES TODO EL PUNTO. `../chat/opciones.js` (954 líneas, 5
 * familias) y `../chat/conexion-inline.js` (669, la credencial en el chat) están enteros y
 * probados, con su transporte backend completo (`client_tools` → `client_calls`). Tenían UN
 * consumidor: el Guía. No lo tenían por falta de ganas — lo pedían por una interfaz de chat
 * vainilla (deep-chat) que la Sala, siendo React, no tiene.
 *
 * Esto es esa interfaz, y nada más. Ocho métodos:
 *
 *     bind(cb) -> id     el id viaja en `data-ac-id` y el click lo despacha esta isla
 *     card(html)         una tarjeta de HTML crudo en el hilo
 *     slot(node)         un nodo DOM ya armado (lo usa conexion-inline)
 *     vitals(t)          la línea de «haciendo…» · clearVitals() la borra
 *     user(t)            la burbuja del humano
 *     errorCard(c, o)    el fallo con su causa y, si la hay, su salida
 *     scrollDown()       llevar la vista al final
 *
 * POR QUÉ UNA ISLA DE DOM Y NO COMPONENTES REACT. El motor emite HTML como STRING —así
 * están escritas las 5 familias y así las valida su schema— y reescribirlo en JSX sería
 * reescribir el motor: la segunda opinión que este archivo existe para evitar. La isla vive
 * DENTRO del viewport del hilo, así que hereda su scroll y su ancho.
 *
 * ⚠️ UN SOLO LISTENER, DELEGADO. Un `addEventListener` por botón se acumularía con cada
 * tarjeta y mantendría vivos los handlers de opciones ya contestadas. Acá el click sube por
 * delegación, se busca el `data-ac-id` más cercano y se despacha. Cerrar la Sala saca ese
 * único listener y el mapa entero.
 *
 * ⚠️ LA REGLA SELLADA DEL MOTOR SIGUE MANDANDO, y no se implementa acá: «una opción sin
 * handler cableado NO SE PINTA — se dice honesto». La decide `opciones.js` mirando sus
 * `destinos`; este adaptador sólo le da dónde dibujar. Si un destino falta, el motor pinta
 * texto y no un botón, exactamente como en el Guía.
 */

const NS = "svopt";

/**
 * Crea el chat-adaptador sobre un contenedor.
 * @param {HTMLElement} host      el nodo donde se dibujan las tarjetas (vive en el hilo)
 * @param {() => void}  scrollFin lleva el viewport al final (lo sabe la Sala, no esto)
 */
export function crearChatAdaptador(host, scrollFin) {
  const handlers = new Map();
  let seq = 0;
  let vitalsNode = null;

  const onClick = (ev) => {
    const btn = ev.target && ev.target.closest ? ev.target.closest("[data-ac-id]") : null;
    if (!btn || !host.contains(btn)) return;
    const cb = handlers.get(btn.getAttribute("data-ac-id"));
    if (!cb) return;                       // handler ya soltado: no se inventa una acción
    ev.preventDefault();
    try {
      cb(btn);
    } catch (e) {
      // El handler es de la superficie. Que explote NO puede llevarse la pantalla: se
      // reporta y el hilo sigue. (Fallo visible, jamás mudo.)
      console.error("[opciones] el handler de una opción falló:", e);
    }
  };
  host.addEventListener("click", onClick);

  const nodo = (cls, html) => {
    const d = document.createElement("div");
    d.className = cls;
    if (html != null) d.innerHTML = String(html);
    return d;
  };

  const alFinal = () => { try { scrollFin && scrollFin(); } catch (e) {} };

  const api = {
    bind(cb) {
      const id = `${NS}-${seq++}`;
      handlers.set(id, cb);
      return id;
    },
    card(html) {
      host.appendChild(nodo("sv-opt-card", html));
      alFinal();
    },
    slot(node) {
      // `conexion-inline` arma su propio nodo (con su formulario y su estado). Se ADOPTA
      // tal cual: envolverlo o clonarlo le rompería los listeners que ya trae puestos.
      if (node && node.nodeType === 1) {
        host.appendChild(node);
        alFinal();
      }
    },
    user(texto) {
      const d = nodo("sv-opt-user");
      d.textContent = String(texto == null ? "" : texto);
      host.appendChild(d);
      alFinal();
    },
    vitals(texto) {
      // UNA sola línea de latido por vez: dos tools seguidas no dejan dos «haciendo…»
      // colgados, que es cómo una pantalla empieza a mentir sobre lo que está pasando.
      api.clearVitals();
      vitalsNode = nodo("sv-opt-vitals");
      vitalsNode.textContent = String(texto == null ? "" : texto);
      host.appendChild(vitalsNode);
      alFinal();
    },
    clearVitals() {
      if (vitalsNode && vitalsNode.parentNode) vitalsNode.parentNode.removeChild(vitalsNode);
      vitalsNode = null;
    },
    errorCard(causa, opts) {
      const d = nodo("sv-opt-card sv-opt-error");
      const p = document.createElement("p");
      p.textContent = String(causa == null ? "" : causa);
      d.appendChild(p);
      // `actions` viene del motor con la SALIDA que la superficie declaró. Si no hay,
      // queda la causa sola — que es honesto: un error sin camino no se disfraza de botón.
      const acciones = (opts && opts.actions) || null;
      if (acciones) d.insertAdjacentHTML("beforeend", String(acciones));
      host.appendChild(d);
      alFinal();
    },
    scrollDown: alFinal,

    /** Suelta TODO: el listener y el mapa. Lo llama el desmontaje de la Sala. */
    destruir() {
      host.removeEventListener("click", onClick);
      handlers.clear();
      api.clearVitals();
      host.replaceChildren();
    },
  };
  return api;
}
