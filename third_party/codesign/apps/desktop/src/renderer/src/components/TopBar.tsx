import { useT } from '@open-codesign/i18n';
import { Wordmark } from '@open-codesign/ui';
import { AlertCircle, ArrowLeft, FolderOpen } from 'lucide-react';
import { type CSSProperties, useEffect } from 'react';
import { type HubTab, useCodesignStore } from '../store';
import { LanguageToggle } from './LanguageToggle';
import { ThemeToggle } from './ThemeToggle';

export const TOPBAR_DRAG_SPACER_TEST_ID = 'topbar-drag-spacer';

export const dragStyle = { WebkitAppRegion: 'drag' } as CSSProperties;
export const noDragStyle = { WebkitAppRegion: 'no-drag' } as CSSProperties;

const HUB_TABS: HubTab[] = ['recent', 'all', 'examples', 'resources'];

const topbarButtonClass =
  'inline-flex h-9 items-center rounded-[var(--radius-sm)] px-[var(--space-2_5)] text-[var(--text-sm)] leading-none whitespace-nowrap transition-colors duration-[var(--duration-faster)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-focus-ring)]';

export function TopBar() {
  const t = useT();
  const setView = useCodesignStore((s) => s.setView);
  const view = useCodesignStore((s) => s.view);
  const previousView = useCodesignStore((s) => s.previousView);
  const currentDesignId = useCodesignStore((s) => s.currentDesignId);
  const designs = useCodesignStore((s) => s.designs);
  const currentDesign = designs.find((d) => d.id === currentDesignId);
  const hubTab = useCodesignStore((s) => s.hubTab);
  const setHubTab = useCodesignStore((s) => s.setHubTab);
  const unreadErrorCount = useCodesignStore((s) => s.unreadErrorCount);
  const refreshDiagnosticEvents = useCodesignStore((s) => s.refreshDiagnosticEvents);
  const openSettingsTab = useCodesignStore((s) => s.openSettingsTab);

  // Pull-based: refresh the diagnostic counter on mount so a page reload
  // surfaces errors recorded while the window was closed. No polling.
  // biome-ignore lint/correctness/useExhaustiveDependencies: mount-only effect
  useEffect(() => {
    void refreshDiagnosticEvents();
  }, []);

  return (
    <header
      className="h-[var(--size-titlebar-height)] shrink-0 flex items-center gap-[var(--space-3)] pr-[var(--space-5)] select-none"
      style={{
        ...dragStyle,
        paddingLeft: 'var(--size-titlebar-pad-left)',
        borderBottom: '1px solid var(--color-border-subtle)',
        background: 'var(--color-background)',
      }}
    >
      {/* [Aleph] `aleph-topbar-nav` la deja ENCOGERSE y deslizarse en vez de desbordar.
          Sin eso, en una ventana angosta esta zona empujaba y las acciones de la derecha
          —que son `shrink-0`— le quedaban ENCIMA: el contador de errores se veía pisando
          «Resources». El gesto es el de la pista del sistema (`.ds-track` en aleph-ds.css):
          se desliza, y la barra de scroll no se muestra. */}
      <div className="aleph-topbar-nav flex items-center gap-[var(--space-6)] min-w-0 h-full">
        <div className="shrink-0">
          {/* [Aleph] SIN NÚMERO DE VERSIÓN. El `v0.2.1` que iba acá es la versión del STACK
              IMPORTADO, no la de Aleph: adentro del lienzo es un dato de otro producto
              anunciándose con versionado propio. Es el mismo corte que se le hizo al
              `v1.5.11` de Educación. El componente conserva su prop `badge` —no se toca su
              contrato— y simplemente no se la pasamos. */}
          <Wordmark size="titlebar" />
        </div>

        {view === 'settings' ? (
          <div className="flex items-center gap-[var(--space-2)] min-w-0">
            <span style={{ color: 'var(--color-text-muted)' }}>/</span>
            <button
              type="button"
              onClick={() => setView(previousView === 'settings' ? 'hub' : previousView)}
              aria-label={t('topbar.closeSettings')}
              className={`${topbarButtonClass} gap-[6px] text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text-primary)]`}
              style={{
                ...noDragStyle,
              }}
            >
              <ArrowLeft className="w-4 h-4 shrink-0" aria-hidden />
              <span className="truncate">{t('topbar.settingsLabel')}</span>
            </button>
          </div>
        ) : view === 'hub' ? (
          <nav
            className="flex h-full min-w-max items-center gap-[var(--space-1)]"
            aria-label={t('hub.tabs.all')}
          >
            {HUB_TABS.map((tab) => {
              const active = tab === hubTab;
              return (
                <button
                  key={tab}
                  type="button"
                  onClick={() => setHubTab(tab)}
                  aria-current={active ? 'page' : undefined}
                  className={`${topbarButtonClass} relative font-medium`}
                  style={{
                    ...noDragStyle,
                    color: active ? 'var(--color-text-primary)' : 'var(--color-text-muted)',
                    background: active ? 'var(--color-accent-tint)' : 'transparent',
                  }}
                  onMouseEnter={(e) => {
                    if (!active) e.currentTarget.style.color = 'var(--color-text-secondary)';
                  }}
                  onMouseLeave={(e) => {
                    if (!active) e.currentTarget.style.color = 'var(--color-text-muted)';
                  }}
                >
                  {t(`hub.tabs.${tab}`)}
                  {active ? (
                    <span
                      aria-hidden
                      className="absolute left-[var(--space-2_5)] right-[var(--space-2_5)] bottom-[-18px] h-[2px] rounded-full"
                      style={{ background: 'var(--color-accent)' }}
                    />
                  ) : null}
                </button>
              );
            })}
          </nav>
        ) : (
          <div className="flex items-center gap-[var(--space-2)] min-w-0">
            <span style={{ color: 'var(--color-text-muted)' }}>/</span>
            <button
              type="button"
              onClick={() => setView('hub')}
              aria-label={t('topbar.openMyDesigns')}
              className={`${topbarButtonClass} max-w-[520px] gap-[6px] text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text-primary)]`}
              style={{
                ...noDragStyle,
              }}
            >
              <FolderOpen className="w-4 h-4 shrink-0" aria-hidden />
              <span className="truncate" title={currentDesign?.name ?? ''}>
                {currentDesign?.name ?? t('sidebar.noDesign')}
              </span>
            </button>
          </div>
        )}
      </div>

      <div
        data-testid={TOPBAR_DRAG_SPACER_TEST_ID}
        /* `min-w-0`, no 24px: cuando falta ancho este espaciador tiene que poder
           desaparecer del todo antes de que algo se solape. */
        className="min-w-0 flex-1 self-stretch"
        style={dragStyle}
      />

      <div className="flex shrink-0 items-center gap-[var(--space-2)]">
        {unreadErrorCount > 0 ? (
          <button
            type="button"
            onClick={() => openSettingsTab('diagnostics')}
            aria-label={t('topbar.unreadErrors', { count: unreadErrorCount })}
            title={t('topbar.unreadErrors', { count: unreadErrorCount })}
            className="inline-flex h-10 items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--color-error)]/30 bg-[var(--color-surface)] px-[var(--space-2_5)] text-[var(--color-error)] whitespace-nowrap transition-colors hover:bg-[var(--color-error)]/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-focus-ring)]"
            style={noDragStyle}
          >
            <AlertCircle className="w-3.5 h-3.5" aria-hidden />
            <span className="text-[var(--text-xs)] font-semibold tabular-nums">
              {unreadErrorCount > 99 ? '99+' : unreadErrorCount}
            </span>
          </button>
        ) : null}
        <div className="flex items-center gap-[var(--space-1)]" style={noDragStyle}>
          <LanguageToggle />
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
