/**
 * aleph-frame.tsx — EL FRAME DE ALEPH, ESCRITO EN EL COMPONENTE.
 * [rediseño · fase DISEÑO · Ley 6, tercera cirugía · archivo NUESTRO dentro de un árbol ajeno]
 *
 * QUINTA COPIA DEL MISMO PATRÓN. Ya existen en `vibetrading` (Finanzas), `dochaus`,
 * `openwork` y `deeptutor`, y se escribe igual a propósito: la regla «¿estoy adentro de
 * Aleph?» tiene que leerse igual en todos o se desincronizan.
 *
 * POR QUÉ ESTE ARCHIVO EXISTE. Hasta la fase 5 la cabecera de Aleph se INYECTABA por DOM
 * desde `aleph-piel.js`. En Diseño ni siquiera eso: su tabla de `ANCLAS` sólo tiene Oficina y
 * Educación, así que este stack nunca recibió cabecera inyectada — la barra de la casa era el
 * `aside.ws-riel` del PADRE, afuera del iframe. Resultado medido: DOS barras, la del padre y
 * la horizontal del stack. El diseño (pieza 11 · artboard 38c) pide UNA, vertical, de 260 px,
 * y la única que puede llevar los ítems del stack es la del stack.
 *
 * ⚠️ LO QUE ESTE ARCHIVO NO HACE: no toca un handler. Acá sólo viven las piezas que son de
 * Aleph y que antes no estaban en ningún lado: la marca, `‹ Inicio` y `⚙ Settings`.
 *
 * ⚠️ LOS DOS BOTONES DE ACÁ NO NAVEGAN: PIDEN. Corremos en un `<iframe>` de OTRO ORIGEN, así
 * que `parent.location` es inalcanzable y un `<a target="_top">` queda bloqueado. Se le pide
 * el destino a la cáscara por `postMessage` y ella —que sí conoce su ruta— resuelve. Los dos
 * contratos ya existían: `aleph-go-home` desde la fase 3 y `aleph-open-settings` desde agosto,
 * y `product/app/design/workspaces/diseno.html` ya tiene los dos listeners.
 */
import { useEffect, useState } from 'react';
import { useT } from '@open-codesign/i18n';

/** Los parámetros que la casa pasa en la URL del iframe. */
export interface AlephFrame {
  activo: boolean;
  espacio: string;
  etiqueta: string;
  usuario: string;
  rol: string;
}

/* ⚠️ SE LEEN UNA SOLA VEZ, AL CARGAR, Y ESTO ES LOAD-BEARING. El `aleph.ts` de este mismo
 * repo ya lo dejó escrito: «la casa los pasa en la URL del `<iframe>`, y en cuanto el router
 * de esta app navega, el `search` se pierde». Leerlos tarde daría «no estoy adentro de Aleph»
 * justo después del primer click. Se leen al importar el módulo y se guardan. */
const LEIDO: AlephFrame = (() => {
  const vacio: AlephFrame = { activo: false, espacio: '', etiqueta: '', usuario: '', rol: '' };
  if (typeof window === 'undefined') return vacio;
  try {
    const q = new URLSearchParams(window.location.search);
    const guardado = (k: string): string => {
      const v = q.get(k);
      if (v) {
        try {
          window.sessionStorage.setItem(`aleph.${k}`, v);
        } catch {
          /* modo privado */
        }
        return v;
      }
      try {
        return window.sessionStorage.getItem(`aleph.${k}`) || '';
      } catch {
        return '';
      }
    };
    const piel = guardado('aleph_piel');
    return {
      // El frame vive detrás del MISMO interruptor que la piel: con el flag apagado, esta
      // pantalla queda exactamente como estaba hoy —barra horizontal y tres pastillas—. Es la
      // condición que el dueño puso en la fase 1 y que no cambió desde entonces.
      activo: piel === 'v2' && window.parent !== window,
      espacio: guardado('aleph_ws'),
      etiqueta: guardado('aleph_label'),
      /* [la cuenta del pie] Quién sos lo sabe la casa, no este stack: llega por la misma URL
         que el resto y se guarda igual, porque el router borra el `search` al primer click.
         Es sólo el rótulo — ni id ni token. */
      usuario: guardado('aleph_user'),
      rol: guardado('aleph_rol'),
    };
  } catch {
    return vacio;
  }
})();

export function useAlephFrame(): AlephFrame {
  /* El valor no cambia en toda la vida de la página; el estado es para que React no lo
   * recalcule en cada render. */
  const [f] = useState(LEIDO);
  return f;
}

/** La mascota, la misma que la casa sirve en `/aleph-mascot-v2.png`, en SVG para no depender
 *  de una request que puede fallar y dejar la marca coja. Trazos exactos del artboard 38c. */
export function Mascota() {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      style={{ flex: 'none' }}
    >
      <ellipse cx="12" cy="12" rx="10.4" ry="4.4" stroke="#cdbcfa" strokeWidth="1.2" />
      <ellipse
        cx="12"
        cy="12"
        rx="10.4"
        ry="4.4"
        stroke="#cdbcfa"
        strokeWidth="1.2"
        transform="rotate(60 12 12)"
      />
      <ellipse
        cx="12"
        cy="12"
        rx="10.4"
        ry="4.4"
        stroke="#cdbcfa"
        strokeWidth="1.2"
        transform="rotate(120 12 12)"
      />
      <circle cx="12" cy="12" r="4.6" fill="#b39cf7" />
      <path
        d="M10.1 11.6c.35-.6.95-.6 1.3 0M12.6 11.6c.35-.6.95-.6 1.3 0"
        stroke="#2e2749"
        strokeWidth="1.05"
        strokeLinecap="round"
      />
    </svg>
  );
}

/**
 * La marca + el nombre del espacio + `‹ Inicio`, arriba de todo.
 * El diseño lo fija igual para los ocho espacios (pieza 11 · artboard 38c).
 *
 * ⚠️ SIN GLIFO DE PLEGAR, Y ES UN HUECO DECLARADO. El artboard 38c dibuja el rectángulo de
 * plegar a la derecha del nombre del espacio. En Finanzas ese botón se RELOCALIZÓ: existía en
 * el pie de su barra con su `setCollapsed(true)`. Acá NO existe: medido, `sidebarCollapsed` se
 * escribe en el store (`store.ts:790`) y **no lo lee nadie** —`App.tsx:44` y `Sidebar.tsx:100`
 * lo tienen con guion bajo, o sea sin usar—. Dibujarlo sería inventar un comportamiento
 * nuevo, no mover un frontend, y la regla de esta tanda dice que ahí se para y se avisa.
 * Cuando el plegado exista de verdad, se le pasa `onPlegar` y aparece.
 */
export function AlephFrameHeader({ onPlegar }: { onPlegar?: () => void }) {
  const t = useT();
  const f = useAlephFrame();

  /* ⚠️ LA MARCA QUE APAGA LA INYECCIÓN. Mientras exista este atributo en el documento,
   * `aleph-piel.js` NO monta su cabecera ni su pie. Es la forma de que no queden DOS caminos
   * haciendo lo mismo: uno de los dos terminaría mintiendo. Se declara acá —donde el frame
   * nativo de verdad se montó— y no en una lista de stacks que hay que acordarse de tocar. */
  useEffect(() => {
    if (!f.activo) return;
    document.documentElement.setAttribute('data-aleph-frame-nativo', '1');
  }, [f.activo]);

  if (!f.activo) return null;

  return (
    <div className="aleph-frame-cabecera">
      <div className="aleph-frame-marca">
        <Mascota />
        <span className="aleph-frame-wordmark">Aleph</span>
        {f.etiqueta ? <span className="aleph-frame-espacio">{f.etiqueta}</span> : null}
        {onPlegar ? (
          <button
            type="button"
            className="aleph-frame-plegar"
            onClick={onPlegar}
            title="Plegar la barra"
            aria-label="Plegar la barra"
          >
            <svg
              width="15"
              height="15"
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <rect x="3" y="4" width="14" height="12" rx="2" />
              <path d="M8 4v12" />
            </svg>
          </button>
        ) : null}
      </div>
      <button
        type="button"
        className="aleph-frame-fila"
        onClick={() => {
          try {
            window.parent.postMessage({ type: 'aleph-go-home' }, '*');
          } catch {
            /* nunca tumbar la barra */
          }
        }}
      >
        <span className="aleph-frame-fila-glifo" aria-hidden="true">
          <svg
            width="16"
            height="16"
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 5l-5 5 5 5" />
          </svg>
        </span>
        <span className="aleph-frame-fila-txt">{t('alephFrame.home')}</span>
      </button>
      <div className="aleph-frame-sep" />
    </div>
  );
}

/**
 * La etiqueta de grupo en mono, tal como el diseño la fija (`DISEÑO`). Es presentación pura:
 * el número —cuando lo hay— se lo pasa quien lo tiene, no se calcula acá.
 */
export function AlephFrameGrupo({ texto, cuenta }: { texto: string; cuenta?: number }) {
  return (
    <div className="aleph-frame-grupo">
      <span className="aleph-frame-grupo-txt">{texto}</span>
      {typeof cuenta === 'number' ? <span className="aleph-frame-grupo-num">{cuenta}</span> : null}
    </div>
  );
}



/**
 * El pie: `⚙ Settings` y la cuenta.
 *
 * [pieza 06 · opción a] CONVERGE LA PUERTA, NO LAS CREDENCIALES. Este botón no abre el
 * Settings de este stack: le pide a la casa que abra EL SUYO, que es el único. El Settings
 * propio sigue existiendo detrás de `⌘,` —no se le saca un cable a nadie—, pero deja de tener
 * puerta en la barra, que es exactamente lo que la pieza 06 pide.
 */
/* ⚠️ [integración · corrección del dueño] ACÁ VIVIÓ UN CENSO DEL PIE Y NO VA.
 * Esta sesión lo agregó para darle disparador a `Ir a…` y a `Conectores`, los dos botones de
 * la casa que se quedaron sin riel. Se vio en pantalla y el dueño lo cortó: **el pie del
 * diseño son DOS filas y nada más**. La hoja del estándar lo fija así, y el artboard 38a de
 * Legal termina exactamente ahí:
 *
 *     ──────────────────────────────
 *     ⚙ Settings
 *     ○ <Nombre> · <Rol>
 *
 * Los once destinos de la casa —Conectores entre ellos— se alcanzan por `‹ Inicio`, que es
 * el primer ítem del raíz y está en los seis. El camino existe; lo que sobraba eran dos filas
 * que el diseño no dibuja. La plomería de la cáscara se queda (el riel BORRADO con su pie
 * mudado al ancla, y `Conectores` montándose de verdad): esos eran defectos reales y siguen
 * arreglados, sólo que su puerta es Inicio y no esta barra. */
export function AlephFrameFooter() {
  const t = useT();
  const f = useAlephFrame();
  if (!f.activo) return null;
  return (
    <div className="aleph-frame-pie">
      <button
        type="button"
        className="aleph-frame-pie-item"
        onClick={() => {
          /* `aleph-open-settings` ya existía y la cáscara ya resuelve sección y espacio
           * (`diseno.html`, el listener de la fase 6). No se inventa un contrato nuevo para
           * algo que la casa sabe hacer. */
          try {
            window.parent.postMessage({ type: 'aleph-open-settings', section: 'perfil' }, '*');
          } catch {
            /* idem */
          }
        }}
      >
        <span className="aleph-frame-pie-glifo" aria-hidden="true">
          <svg
            width="16"
            height="16"
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="10" cy="10" r="2.9" />
            <circle cx="10" cy="10" r="6.1" />
            <path d="M10 2.6v1.9M10 15.5v1.9M2.6 10h1.9M15.5 10h1.9" />
          </svg>
        </span>
        <span className="aleph-frame-fila-txt">{t('alephFrame.settings')}</span>
      </button>
      {/* El artboard cierra la barra con Settings Y la cuenta. El nombre y el rol los manda la
          casa; si no vinieron —sin sesión todavía— no se dibuja una fila con un avatar mudo:
          se dibuja nada. */}
      {f.usuario ? (
        <div className="aleph-frame-cuenta">
          <span className="aleph-frame-cuenta-ava" aria-hidden="true" />
          <span className="aleph-frame-cuenta-txt">
            <span className="aleph-frame-cuenta-nom">{f.usuario}</span>
            {f.rol ? <span className="aleph-frame-cuenta-rol">{f.rol}</span> : null}
          </span>
        </div>
      ) : null}
    </div>
  );
}
