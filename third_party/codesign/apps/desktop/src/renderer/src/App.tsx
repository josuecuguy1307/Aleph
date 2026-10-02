import { useT } from '@open-codesign/i18n';
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { AlephRail } from './components/AlephRail';
import { useAlephFrame } from './components/aleph-frame';
import { CommentsPanel } from './components/comment/CommentsPanel';
import { DeleteDesignDialog } from './components/DeleteDesignDialog';
import { DesignsView } from './components/DesignsView';
import { ReportEventDialog } from './components/diagnostics/ReportEventDialog';
import { NewDesignDialog } from './components/NewDesignDialog';
import { PermissionDialog } from './components/PermissionDialog';
import { RebindWorkspaceDialog } from './components/RebindWorkspaceDialog';
import { RenameDesignDialog } from './components/RenameDesignDialog';
import { Sidebar } from './components/Sidebar';
import { ToastViewport } from './components/Toast';
import { TopBar } from './components/TopBar';
import { useAgentStream } from './hooks/useAgentStream';
import { useKeyboard } from './hooks/useKeyboard';

const PreviewPane = lazy(() =>
  import('./components/PreviewPane').then((m) => ({ default: m.PreviewPane })),
);
/* [rediseño · fase DISEÑO · el destino del «68»] `<Settings/>` NO SE RENDERIZABA EN NINGÚN
 * LADO, y ésa era la causa del bug abierto desde `aed4ec16` (2026-08-28): «el contador rojo
 * abre Ajustes y la pantalla queda COMPLETAMENTE VACÍA». Medido: su único importador era
 * `Settings.test.ts`. Cuatro caminos ponían `view:'settings'` y los cuatro caían en blanco —
 * `⌘,`, el contador de errores, la acción de arreglo de una generación fallida
 * (`store/slices/generation.ts:558`) y el toast de `:746`.
 *
 * Va PEREZOSO por la misma razón que `PreviewPane` —es la convención de este archivo y la
 * regla de su CLAUDE.md: «Lazy-load heavy features»—: arrastra cuatro paneles (Storage,
 * Memory, Diagnostics, Advanced) que la mayoría de las sesiones no abre nunca. */
const Settings = lazy(() => import('./components/Settings').then((m) => ({ default: m.Settings })));

import { useCodesignStore } from './store';
import { HubView } from './views/HubView';

export function App() {
  const t = useT();
  const config = useCodesignStore((s) => s.config);
  const configLoaded = useCodesignStore((s) => s.configLoaded);
  const loadConfig = useCodesignStore((s) => s.loadConfig);
  const loadDesigns = useCodesignStore((s) => s.loadDesigns);
  const syncGenerationStatus = useCodesignStore((s) => s.syncGenerationStatus);
  const switchDesign = useCodesignStore((s) => s.switchDesign);
  const setView = useCodesignStore((s) => s.setView);
  const view = useCodesignStore((s) => s.view);
  const previousView = useCodesignStore((s) => s.previousView);
  const designsViewOpen = useCodesignStore((s) => s.designsViewOpen);
  const closeDesignsView = useCodesignStore((s) => s.closeDesignsView);
  const openDesignsView = useCodesignStore((s) => s.openDesignsView);
  const createNewDesign = useCodesignStore((s) => s.createNewDesign);
  const designToDelete = useCodesignStore((s) => s.designToDelete);
  const designToRename = useCodesignStore((s) => s.designToRename);
  const requestDeleteDesign = useCodesignStore((s) => s.requestDeleteDesign);
  const requestRenameDesign = useCodesignStore((s) => s.requestRenameDesign);
  const interactionMode = useCodesignStore((s) => s.interactionMode);
  const setInteractionMode = useCodesignStore((s) => s.setInteractionMode);
  const _sidebarCollapsed = useCodesignStore((s) => s.sidebarCollapsed);
  const activeReportLocalId = useCodesignStore((s) => s.activeReportLocalId);
  const closeReportDialog = useCodesignStore((s) => s.closeReportDialog);

  /* [rediseño · fase DISEÑO · pieza 11] ¿ESTÁ PUESTO EL FRAME DE ALEPH? Detrás del mismo
     interruptor que la piel (`?aleph_piel=v2`). Apagado, esta pantalla queda EXACTAMENTE
     como estaba: barra horizontal arriba con sus cuatro pestañas y sus tres pastillas. */
  const alephFrame = useAlephFrame();

  const [prefillPrompt, setPrefillPrompt] = useState<{ id: number; text: string } | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(() =>
    Math.max(320, Math.round(window.innerWidth * 0.25)),
  );
  const [isResizing, setIsResizing] = useState(false);

  useAgentStream();

  // Once the user has visited Hub we keep HubView mounted (toggled via
  // `hidden`) so going Workspace → Hub doesn't tear down the design-card
  // iframes and pay the srcDoc parse cost again.
  const [hubMounted, setHubMounted] = useState(view === 'hub');
  useEffect(() => {
    if (view === 'hub') setHubMounted(true);
  }, [view]);
  // Same trick for workspace — once visited, keep PreviewPane mounted so the
  // iframe pool survives Workspace ↔ Hub round trips. Without this, the pool
  // rebuilds 5 iframes from srcDoc every time you come back (2-3s of parse).
  const [workspaceMounted, setWorkspaceMounted] = useState(view === 'workspace');
  useEffect(() => {
    if (view === 'workspace') setWorkspaceMounted(true);
  }, [view]);

  const onResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);

    const onMove = (ev: MouseEvent) => {
      const maxW = Math.round(window.innerWidth * 0.55);
      const clamped = Math.min(Math.max(ev.clientX, 280), maxW);
      setSidebarWidth(clamped);
    };
    const onUp = () => {
      setIsResizing(false);
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }, []);

  useEffect(() => {
    async function bootstrap(): Promise<void> {
      await Promise.all([loadConfig(), loadDesigns()]);
      await syncGenerationStatus();
      const state = useCodesignStore.getState();
      if (state.currentDesignId === null && state.designs.length > 0) {
        const runningDesignId = Object.keys(state.generationByDesign)[0];
        const initialDesign =
          state.designs.find((design) => design.id === runningDesignId) ?? state.designs[0];
        if (initialDesign) await switchDesign(initialDesign.id);
      }
    }
    void bootstrap();
  }, [loadConfig, loadDesigns, switchDesign, syncGenerationStatus]);

  const ready = configLoaded && config?.hasKey;
  const prefillComposer = useCallback((text: string) => {
    setPrefillPrompt((prev) => ({ id: (prev?.id ?? 0) + 1, text }));
  }, []);

  const bindings = useMemo(
    () => [
      {
        combo: 'mod+,',
        handler: () => {
          if (!ready) return;
          setView('settings');
        },
      },
      {
        combo: 'mod+n',
        handler: () => {
          if (!ready) return;
          void createNewDesign();
        },
      },
      /* [rediseño · fase DISEÑO] `⌘⇧F`, EL ATAJO QUE EL ARTBOARD IMPRIME Y QUE NO EXISTÍA.
         La fila `Search` del riel lo muestra al lado del rótulo, así que tiene que andar:
         imprimir un atajo muerto es peor que no imprimirlo. Llama al MISMO
         `openDesignsView()` que la fila — no hay una segunda implementación de buscar. */
      {
        combo: 'mod+shift+f',
        /* ⚠️ SIN LA GUARDA DE `ready`, Y ES A PROPÓSITO. Los otros dos atajos la tienen porque
           abren Ajustes o crean un diseño, y sin credencial eso no lleva a ningún lado. Buscar
           entre los diseños que YA EXISTEN no necesita ningún modelo: es un overlay local que
           lee el estado del store. Y la FILA `Search` del riel no está gateada, así que con la
           guarda puesta el atajo que esa misma fila imprime al lado quedaría muerto justo en
           el caso en que el pack no levantó — dos puertas al mismo cuarto, una abierta y otra
           no.

           ⚠️ RETIRO POR ESCRITO UNA MEDICIÓN MÍA QUE ERA FALSA. Primero anoté acá que lo había
           «medido en el lienzo real sin llave». No es cierto: el lienzo de la vara SÍ tiene
           llave —`onboarding.getState()` devuelve `hasKey:true`, porque el `config.toml` que
           escribe el lanzador declara el proveedor `aleph-brain` como keyless—, así que la
           guarda nunca se disparó y lo que vi fue otra cosa (el evento de teclado sin foco
           adentro del iframe). El corte se sostiene por el argumento de arriba, no por esa
           medición. */
        handler: () => {
          openDesignsView();
        },
      },
      {
        combo: 'escape',
        handler: () => {
          if (designToDelete) {
            requestDeleteDesign(null);
            return;
          }
          if (designToRename) {
            requestRenameDesign(null);
            return;
          }
          if (designsViewOpen) {
            closeDesignsView();
            return;
          }
          if (interactionMode !== 'default') {
            setInteractionMode('default');
            return;
          }
          if (view === 'settings') {
            setView(previousView === 'settings' ? 'hub' : previousView);
          }
        },
        preventDefault: false,
      },
    ],
    [
      ready,
      view,
      previousView,
      designsViewOpen,
      designToDelete,
      designToRename,
      interactionMode,
      setInteractionMode,
      setView,
      closeDesignsView,
      openDesignsView,
      createNewDesign,
      requestDeleteDesign,
      requestRenameDesign,
    ],
  );
  useKeyboard(bindings);

  if (!configLoaded) {
    return (
      <div className="h-full flex items-center justify-center bg-[var(--color-background)] text-[var(--text-sm)] text-[var(--color-text-muted)]">
        {t('common.loading')}
      </div>
    );
  }

  return (
    <div className="h-full overflow-hidden flex flex-col bg-[var(--color-background)]">
      {/* [rediseño · fase DISEÑO · pieza 11] UNA SOLA BARRA, Y ES EL RIEL.
          Con el frame puesto, `<TopBar/>` NO SE RENDERIZA: con ella se van las cuatro
          pestañas —que suben al riel con su mismo `setHubTab`— y las tres pastillas.

          ⚠️ CONTADAS ANTES Y DESPUÉS, que es la regla que Finanzas aprendió a los golpes.
          La barra horizontal mostraba SEIS cosas: (1) el wordmark, (2) la miga —pestañas en
          el hub, nombre del diseño en el lienzo, «Configuración» en ajustes—, (3) el contador
          rojo de errores, (4) el globo del idioma, (5) la luna del tema, (6) la zona de
          arrastre de la ventana. Después: (1) y (2) están en el riel —marca arriba, pestañas
          en la sección DISEÑO—; (4) y (5) viven en Appearance del Settings único, que es la
          decisión ya tomada, y el idioma además CRUZA por `?aleph_lang` (ver `main.tsx`);
          (6) no aplica adentro de un iframe: la ventana la dibuja la casa. Queda (3).

          (3) EL «68» ERA UN BOTÓN A UNA PANTALLA EN BLANCO, y ya no lo es. Su destino
          —`openSettingsTab('diagnostics')` → `view:'settings'`— no se dibujaba porque
          `<Settings/>` no se renderizaba en ningún lado; está arreglado abajo, y con él los
          otros tres caminos que caían en el mismo pozo. El contador en sí se va con la barra:
          es un INDICADOR, y su cuenta vive en el panel de Diagnósticos, que ahora sí abre.
          ⚠️ Con el frame puesto, `Diagnósticos` se alcanza por `⌘,` y por la acción de una
          generación fallida; el riel no le pone fila porque la pieza 06 manda el `⚙` al
          Settings ÚNICO de la casa, y dos puertas a dos Settings distintos en la misma barra
          es justo lo que este rediseño saca. */}
      <div className="flex-1 min-h-0 flex">
        {alephFrame.activo ? <AlephRail /> : null}
        <div className="flex-1 min-w-0 min-h-0 flex flex-col">
          {alephFrame.activo ? null : <TopBar />}
          <div className="flex-1 min-h-0 relative">
            {/* [el destino del «68»] AJUSTES DEL STACK, EN EL PANEL DERECHO.
                Ocupa sólo esta columna: con el frame puesto el riel queda a la izquierda, que
                es lo que la pieza 12 pide para cualquier pantalla que no se entre por él.
                `hub` y `workspace` se esconden con `hidden` para no desmontar sus iframes, así
                que acá alcanza con montarlo cuando toca — es barato y no tiene estado que
                perder. */}
            {view === 'settings' ? (
              <div className="aleph-panel-ajustes h-full min-h-0 flex flex-col">
                {/* ⚠️ EL «VOLVER» VIAJA CON SU HANDLER, Y SIN ÉL ESTA PANTALLA SERÍA UNA
                    TRAMPA. Con el frame puesto no se dibuja `<TopBar/>`, y ahí vivía el único
                    botón para salir de Ajustes (`topbar.closeSettings`). Quedaba sólo la tecla
                    `Escape`. Es EL MISMO botón: mismo rótulo, mismo `setView(previousView…)`,
                    movido de la barra de arriba a la cabecera del panel. Sin frame sigue
                    arriba, intacto. */}
                {alephFrame.activo ? (
                  <div className="aleph-panel-cabecera">
                    <button
                      type="button"
                      onClick={() => setView(previousView === 'settings' ? 'hub' : previousView)}
                      aria-label={t('topbar.closeSettings')}
                      className="aleph-panel-volver"
                    >
                      <span aria-hidden>‹</span>
                      {/* El rótulo dice LA ACCIÓN, no dónde estás. Primero puse
                          `topbar.settingsLabel` —«Configuración»— copiando la miga de la barra
                          vieja, y ahí tenía sentido porque venía después de un «/»: era el
                          rastro. Suelto en la cabecera del panel se lee «ir a Configuración»
                          estando ya adentro. `topbar.closeSettings` es la clave que ya
                          describe lo que el botón hace, existe en los cuatro idiomas, y es la
                          misma que su `aria-label` — así lo que se ve y lo que se lee coinciden. */}
                      <span>{t('topbar.closeSettings')}</span>
                    </button>
                  </div>
                ) : null}
                <div className="flex-1 min-h-0">
                  <Suspense fallback={null}>
                    <Settings />
                  </Suspense>
                </div>
              </div>
            ) : null}
            {hubMounted ? (
              <div hidden={view !== 'hub'} className="h-full">
                <HubView
                  onUseExamplePrompt={async (p) => {
                    // Clicking an example is an explicit "start a new thing"
                    // intent — always create a fresh design and preload the
                    // prompt into IT, never into whatever design the user was
                    // last on. If createNewDesign fails (e.g. another run is in
                    // flight) it surfaces a toast; we bail so the example prompt
                    // doesn't quietly land in the current design's input box.
                    const created = await createNewDesign();
                    if (!created) return;
                    prefillComposer(p);
                    setView('workspace');
                  }}
                />
              </div>
            ) : null}
            {workspaceMounted ? (
              <div
                hidden={view !== 'workspace'}
                className="h-full min-w-0 overflow-hidden flex flex-col"
              >
                <div className="flex-1 min-h-0 min-w-0 overflow-hidden flex relative">
                  {isResizing && <div className="absolute inset-0 z-20 cursor-col-resize" />}
                  <div className="relative shrink-0" style={{ width: sidebarWidth }}>
                    <Sidebar prefillPrompt={prefillPrompt} />
                    <div
                      role="separator"
                      aria-orientation="vertical"
                      onMouseDown={onResizeStart}
                      className="absolute top-0 right-0 w-[5px] h-full cursor-col-resize z-10 hover:bg-[var(--color-accent)]/15 active:bg-[var(--color-accent)]/25 transition-colors duration-100"
                      style={{ transform: 'translateX(50%)' }}
                    />
                  </div>
                  <main className="flex flex-col min-h-0 flex-1 min-w-0">
                    <Suspense fallback={null}>
                      <PreviewPane onPickStarter={prefillComposer} />
                    </Suspense>
                  </main>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>
      <DesignsView />
      <RenameDesignDialog />
      <DeleteDesignDialog />
      <RebindWorkspaceDialog />
      <NewDesignDialog />
      <ToastViewport />
      <CommentsPanel />
      <PermissionDialog />
      <ReportEventDialog localId={activeReportLocalId} onClose={closeReportDialog} />
    </div>
  );
}
