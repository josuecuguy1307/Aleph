import { useT } from '@open-codesign/i18n';
import { IconButton, Tooltip } from '@open-codesign/ui';
import { FolderOpen, Layers, Link2, Paperclip, Plus } from 'lucide-react';
import {
  type KeyboardEvent as ReactKeyboardEvent,
  useEffect,
  useId,
  useRef,
  useState,
} from 'react';
import { useAlephFrame } from '../aleph-frame';

export interface AddMenuProps {
  onAttachFiles: () => void;
  onLinkDesignSystem: () => void;
  referenceUrl: string;
  onReferenceUrlChange: (value: string) => void;
  hasDesignSystem: boolean;
  disabled?: boolean;
  /** When provided, renders a "Decompose to UI Kit" item that asks the agent
   *  to emit a ui_kits/<slug>/ folder for downstream coding-agent handoff.
   *  Hidden when undefined. The parent decides whether the action is meaningful
   *  for the current design (requires a generated artifact). */
  onDecomposeToUiKit?: (() => void) | undefined;
  canDecompose?: boolean | undefined;
}

/**
 * Compact `+` button that opens a three-item popover: attach local files,
 * link/refresh design system repo, reference URL. Replaces the former inline
 * button row so the composer area stays quiet until the user wants context.
 *
 * Lightweight popover (no Radix dep) — closes on outside click or Escape.
 */
export function AddMenu({
  onAttachFiles,
  onLinkDesignSystem,
  referenceUrl,
  onReferenceUrlChange,
  hasDesignSystem,
  disabled,
  onDecomposeToUiKit,
  canDecompose,
}: AddMenuProps) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    function handleDown(e: MouseEvent): void {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    function handleKey(e: globalThis.KeyboardEvent): void {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', handleDown);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleDown);
      document.removeEventListener('keydown', handleKey);
    };
  }, [open]);

  function handleItem(run: () => void) {
    return () => {
      run();
      setOpen(false);
    };
  }

  function handleUrlKey(e: ReactKeyboardEvent<HTMLInputElement>): void {
    if (e.key === 'Enter') {
      e.preventDefault();
      setOpen(false);
    }
  }

  /* [rediseño · fase DISEÑO · piezas 07 y 09] DOS SÍMBOLOS, Y NADA MÁS.
     La hoja del estándar lo fija sin vueltas: «Dos símbolos en todos los espacios y nada
     más: el clip —que en algunos aparecía como “+” o como enchufe— y los dos palitos», con
     el clip para adjuntar y NADA más («dispara el buscador de archivos del sistema, sin
     submenú») y los dos palitos para todas las opciones de la sesión.

     Acá había UNO —el «+»— con las cuatro cosas mezcladas: adjuntar archivos junto al
     sistema de diseño, la URL de referencia y «Decompose to UI Kit». El adjuntar sale de ese
     menú y se convierte en el clip; el menú se queda con las TRES que sí son de sesión y pasa
     a colgar de los dos palitos.

     ⚠️ CONTADAS ANTES Y DESPUÉS: 1 botón con 4 ítems → 2 botones con 1 + 3. Cuatro y cuatro.
     Ningún handler se reescribe al mudarse: el clip hereda literalmente el `onAttachFiles`
     que tenía su fila, y los otros tres siguen dentro del mismo menú con el mismo `onClick`. */
  const alephFrame = useAlephFrame();

  if (alephFrame.activo) {
    return (
      <div ref={wrapRef} className="aleph-barrita-simbolos">
        <button
          type="button"
          onClick={() => onAttachFiles()}
          disabled={disabled}
          title={t('sidebar.attachLocalFiles')}
          aria-label={t('sidebar.attachLocalFiles')}
          className="aleph-barrita-simbolo"
        >
          {/* El clip del artboard, trazo por trazo (pieza 07). */}
          <svg
            width="18"
            height="18"
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            aria-hidden
          >
            <path d="M12.6 7.7 8 12.3a2.4 2.4 0 0 0 3.4 3.4l5.1-5.1a4 4 0 0 0-5.7-5.7l-5.5 5.5a5.6 5.6 0 0 0 7.9 7.9" />
          </svg>
        </button>
        <div className="relative">
          <button
            type="button"
            aria-haspopup="menu"
            aria-expanded={open}
            aria-controls={menuId}
            onClick={() => setOpen((v) => !v)}
            disabled={disabled}
            title={t('sidebar.chat.addMenu.trigger')}
            aria-label={t('sidebar.chat.addMenu.trigger')}
            className="aleph-barrita-simbolo aleph-barrita-simbolo-opciones"
          >
            {/* Los dos palitos del artboard, trazo por trazo (pieza 07). */}
            <svg
              width="17"
              height="17"
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              aria-hidden
            >
              <path d="M3 6h9M15 6h2M3 14h4M10 14h7" />
              <circle cx="13.5" cy="6" r="1.8" />
              <circle cx="8.5" cy="14" r="1.8" />
            </svg>
          </button>
          {open ? (
            <div id={menuId} role="menu" className="aleph-barrita-menu">
              <button
                type="button"
                role="menuitem"
                onClick={handleItem(onLinkDesignSystem)}
                className="aleph-barrita-menu-item"
              >
                <FolderOpen className="w-4 h-4 shrink-0" aria-hidden />
                <span className="truncate">
                  {hasDesignSystem
                    ? t('sidebar.refreshDesignSystemRepo')
                    : t('sidebar.linkDesignSystemRepo')}
                </span>
              </button>
              <div className="aleph-barrita-menu-url">
                <Link2 className="w-4 h-4 shrink-0" aria-hidden />
                <input
                  type="url"
                  value={referenceUrl}
                  onChange={(e) => onReferenceUrlChange(e.target.value)}
                  onKeyDown={handleUrlKey}
                  placeholder={t('sidebar.referenceUrl')}
                  aria-label={t('sidebar.referenceUrl')}
                />
              </div>
              {onDecomposeToUiKit ? (
                <button
                  type="button"
                  role="menuitem"
                  onClick={handleItem(onDecomposeToUiKit)}
                  disabled={!canDecompose}
                  className="aleph-barrita-menu-item"
                  title={canDecompose ? undefined : t('sidebar.decomposeToUiKitDisabled')}
                >
                  <Layers className="w-4 h-4 shrink-0" aria-hidden />
                  <span className="truncate">{t('sidebar.decomposeToUiKit')}</span>
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <div ref={wrapRef} className="relative">
      <Tooltip label={t('sidebar.chat.addMenu.trigger')} side="top">
        <IconButton
          size="sm"
          type="button"
          label={t('sidebar.chat.addMenu.trigger')}
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls={menuId}
          onClick={() => setOpen((v) => !v)}
          disabled={disabled}
          className="text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]"
        >
          <Plus className="w-[var(--size-icon-md)] h-[var(--size-icon-md)]" strokeWidth={2} />
        </IconButton>
      </Tooltip>
      {open ? (
        <div
          id={menuId}
          role="menu"
          className="absolute bottom-full left-0 mb-[var(--space-2)] z-20 min-w-[240px] rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-[var(--space-1)]"
        >
          <button
            type="button"
            role="menuitem"
            onClick={handleItem(onAttachFiles)}
            className="flex w-full items-center gap-[var(--space-2)] rounded-[var(--radius-sm)] px-[var(--space-2_5)] py-[var(--space-2)] text-left text-[var(--text-sm)] text-[var(--color-text-primary)] hover:bg-[var(--color-surface-hover)] transition-colors"
          >
            <Paperclip
              className="w-[var(--size-icon-sm)] h-[var(--size-icon-sm)] text-[var(--color-text-secondary)]"
              aria-hidden
            />
            <span className="truncate">{t('sidebar.attachLocalFiles')}</span>
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={handleItem(onLinkDesignSystem)}
            className="flex w-full items-center gap-[var(--space-2)] rounded-[var(--radius-sm)] px-[var(--space-2_5)] py-[var(--space-2)] text-left text-[var(--text-sm)] text-[var(--color-text-primary)] hover:bg-[var(--color-surface-hover)] transition-colors"
          >
            <FolderOpen
              className="w-[var(--size-icon-sm)] h-[var(--size-icon-sm)] text-[var(--color-text-secondary)]"
              aria-hidden
            />
            <span className="truncate">
              {hasDesignSystem
                ? t('sidebar.refreshDesignSystemRepo')
                : t('sidebar.linkDesignSystemRepo')}
            </span>
          </button>
          <div className="flex items-center gap-[var(--space-2)] px-[var(--space-2_5)] py-[var(--space-2)]">
            <Link2
              className="w-[var(--size-icon-sm)] h-[var(--size-icon-sm)] text-[var(--color-text-secondary)] shrink-0"
              aria-hidden
            />
            <input
              type="url"
              value={referenceUrl}
              onChange={(e) => onReferenceUrlChange(e.target.value)}
              onKeyDown={handleUrlKey}
              placeholder={t('sidebar.referenceUrl')}
              aria-label={t('sidebar.referenceUrl')}
              className="flex-1 min-w-0 bg-transparent text-[var(--text-xs)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:outline-none"
            />
          </div>
          {onDecomposeToUiKit ? (
            <button
              type="button"
              role="menuitem"
              onClick={handleItem(onDecomposeToUiKit)}
              disabled={!canDecompose}
              className="flex w-full items-center gap-[var(--space-2)] rounded-[var(--radius-sm)] px-[var(--space-2_5)] py-[var(--space-2)] text-left text-[var(--text-sm)] text-[var(--color-text-primary)] hover:bg-[var(--color-surface-hover)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title={canDecompose ? undefined : t('sidebar.decomposeToUiKitDisabled')}
            >
              <Layers
                className="w-[var(--size-icon-sm)] h-[var(--size-icon-sm)] text-[var(--color-text-secondary)]"
                aria-hidden
              />
              <span className="truncate">{t('sidebar.decomposeToUiKit')}</span>
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
