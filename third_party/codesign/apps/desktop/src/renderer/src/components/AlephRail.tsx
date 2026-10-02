/**
 * AlephRail.tsx — LA BARRA VERTICAL DE 260 px DE DISEÑO.
 * [rediseño · fase DISEÑO · pieza 11 · artboard 38c · archivo NUESTRO dentro de un árbol ajeno]
 *
 * QUÉ DICE EL DISEÑO, TEXTUAL: «la barra horizontal pasa al riel; sin las tres pastillas».
 * Una sola barra: Aleph · Diseño · ‹ Inicio · New design · Search ⌘⇧F · la etiqueta DISEÑO en
 * mono · Recientes · Todos · Ejemplos · Recursos · el pie con Settings y la cuenta.
 *
 * ⚠️ ESTO ES REUBICACIÓN, NO REESCRITURA. Cada fila de acá dispara EL MISMO handler que ya
 * existía; ninguno se reimplementó. Fila por fila, medido en el árbol:
 *
 *   Recientes/Todos/Ejemplos/Recursos → `setHubTab(tab)`, el mismo de `TopBar.tsx:83`. Viaja
 *       ACOMPAÑADO de `setView('hub')` porque el riel se ve desde las dos vistas y las
 *       pestañas sólo se dibujaban en el hub: sin eso, desde el lienzo el click cambiaría una
 *       pestaña que no está en pantalla. Los dos son acciones del store que ya existen; no se
 *       escribió lógica nueva, se compusieron dos que ya estaban.
 *   New design → `openNewDesignDialog()`, el mismo de la tarjeta «Comenzar un nuevo diseño»
 *       (`views/hub/RecentTab.tsx:33`). La tarjeta SIGUE donde está —el artboard 38c la dibuja
 *       en el cuerpo—, así que no se le sacó la puerta a nadie: se le agregó la del riel, que
 *       es la que el diseño pide.
 *   Search → `openDesignsView()` (`store/slices/designs.ts:435`), que abre `<DesignsView/>`:
 *       un overlay con buscador sobre los diseños, montado en `App.tsx` desde siempre.
 *
 * 🔴 LO QUE HAY QUE DECIR, Y ES LA REGLA DE ESTA TANDA: `Search` NO TENÍA CABLE. Su handler
 * está entero y su pantalla está montada, pero el ÚNICO que lo llamaba era `DesignSwitcher.tsx`,
 * un componente que **no se renderiza en ninguna parte** (medido: cero importadores). O sea que
 * la función existe —buscada por FUNCIÓN y no por nombre, «¿qué busca entre los diseños?» es
 * `DesignsView`— pero su disparador no existía en pantalla. Darle esta fila no es mover un
 * frontend: es darle un camino que no había. Queda declarado acá y en el reporte.
 * Lo mismo vale para el atajo `⌘⇧F` que el artboard imprime: hoy no está bindeado en ningún
 * lado (`useKeyboard` sólo tiene `mod+,`, `mod+n` y `escape`). Se agrega en `App.tsx`, porque
 * imprimir un atajo que no anda es peor que no imprimirlo.
 */
import { useT } from '@open-codesign/i18n';
import type { ReactNode } from 'react';
import { type HubTab, useCodesignStore } from '../store';
import { AlephFrameFooter, AlephFrameGrupo, AlephFrameHeader, useAlephFrame } from './aleph-frame';

/* Los glifos son los TRAZOS DEL ARTBOARD, no un ícono parecido de la librería. Se dibujan a
 * mano porque el artboard fija cada `path`: el reloj de Recientes, la grilla de Todos, las dos
 * chispas de Ejemplos y las capas de Recursos. `lucide` tiene equivalentes, pero «parecido» no
 * es el criterio de esta tanda. Todos comparten caja 20, trazo 1.5 y `currentColor`, así que el
 * estado activo los tiñe de índigo sin una regla por ícono. */
function Glifo({ children }: { children: ReactNode }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

const ICONO: Record<HubTab, ReactNode> = {
  recent: (
    <Glifo>
      <circle cx="10" cy="10" r="6.6" />
      <path d="M10 6.4V10l2.6 1.6" />
    </Glifo>
  ),
  all: (
    <Glifo>
      <rect x="3" y="3" width="6" height="6" rx="1.4" />
      <rect x="11" y="3" width="6" height="6" rx="1.4" />
      <rect x="3" y="11" width="6" height="6" rx="1.4" />
      <rect x="11" y="11" width="6" height="6" rx="1.4" />
    </Glifo>
  ),
  examples: (
    <Glifo>
      <path d="M7 3.2l1.3 3.1 3.1 1.3-3.1 1.3L7 12l-1.3-3.1L2.6 7.6l3.1-1.3z" />
      <path d="M14 11l.8 1.9 1.9.8-1.9.8-.8 1.9-.8-1.9-1.9-.8 1.9-.8z" />
    </Glifo>
  ),
  resources: (
    <Glifo>
      <path d="M10 3 3 6.6l7 3.6 7-3.6z" />
      <path d="M3 10.4l7 3.6 7-3.6" />
    </Glifo>
  ),
};

const TABS: HubTab[] = ['recent', 'all', 'examples', 'resources'];

function Fila({
  glifo,
  texto,
  atajo,
  activa,
  onClick,
  titulo,
}: {
  glifo: ReactNode;
  texto: string;
  atajo?: string;
  activa?: boolean;
  onClick: () => void;
  titulo?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={activa ? 'page' : undefined}
      title={titulo ?? texto}
      className={`aleph-frame-fila${activa ? ' aleph-frame-fila-activa' : ''}`}
    >
      <span className="aleph-frame-fila-glifo">{glifo}</span>
      <span className="aleph-frame-fila-txt">{texto}</span>
      {atajo ? <span className="aleph-frame-fila-atajo">{atajo}</span> : null}
    </button>
  );
}

export function AlephRail() {
  const t = useT();
  const f = useAlephFrame();
  const view = useCodesignStore((s) => s.view);
  const hubTab = useCodesignStore((s) => s.hubTab);
  const setHubTab = useCodesignStore((s) => s.setHubTab);
  const setView = useCodesignStore((s) => s.setView);
  const openNewDesignDialog = useCodesignStore((s) => s.openNewDesignDialog);
  const openDesignsView = useCodesignStore((s) => s.openDesignsView);

  if (!f.activo) return null;

  return (
    <aside className="aleph-riel" aria-label="Aleph">
      <AlephFrameHeader />

      {/* EL BLOQUE ESTÁNDAR. La hoja del estándar lo fija: «New chat · Search (⌘⇧F) · Library
          — Library solo donde existe; en Diseño la primera fila es New design».
          ⚠️ LIBRARY, MEDIDO POR FUNCIÓN Y NO POR NOMBRE. La pregunta es «¿qué lista las obras
          que produjo el espacio?», y en Diseño la respuesta es la pestaña **Todos**
          (`YourDesignsTab`): la grilla de todos los diseños del usuario. Eso ES Library, y ya
          tiene su lugar en el diseño, adentro de la sección DISEÑO. Dibujar además una fila
          «Library» sería una segunda puerta al mismo cuarto — el defecto que este rediseño
          vino a sacar, no uno nuevo que agregar. */}
      <nav className="aleph-riel-bloque" aria-label="Aleph">
        <Fila
          glifo={
            <Glifo>
              <path d="M10 4v12M4 10h12" />
            </Glifo>
          }
          texto={t('alephFrame.newDesign')}
          titulo={t('hub.newDesign')}
          onClick={() => openNewDesignDialog()}
        />
        <Fila
          glifo={
            <Glifo>
              <circle cx="9" cy="9" r="5.5" />
              <path d="M13.2 13.2 17 17" />
            </Glifo>
          }
          texto={t('alephFrame.search')}
          atajo="⌘⇧F"
          titulo={t('projects.view.search')}
          onClick={() => openDesignsView()}
        />
      </nav>

      <div className="aleph-frame-sep aleph-frame-sep-bloque" />

      {/* LA SECCIÓN DEL ESPACIO. Las cuatro pestañas que vivían en la barra horizontal
          (`TopBar.tsx:78-113`), con su mismo `setHubTab` y su mismo estado activo. */}
      <nav className="aleph-riel-bloque" aria-label={f.etiqueta || 'Diseño'}>
        <AlephFrameGrupo texto={(f.etiqueta || 'Diseño').toUpperCase()} />
        {TABS.map((tab) => (
          <Fila
            key={tab}
            glifo={ICONO[tab]}
            texto={t(`hub.tabs.${tab}`)}
            activa={view === 'hub' && hubTab === tab}
            onClick={() => {
              setHubTab(tab);
              setView('hub');
            }}
          />
        ))}
      </nav>

      <div className="aleph-riel-relleno" />
      <AlephFrameFooter />
    </aside>
  );
}
