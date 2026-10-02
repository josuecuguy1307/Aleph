import { useT } from '@open-codesign/i18n';
import { Tooltip } from '@open-codesign/ui';
import { ArrowUp, Square } from 'lucide-react';
import {
  type ClipboardEvent,
  type DragEvent,
  type FormEvent,
  forwardRef,
  type KeyboardEvent,
  type ReactNode,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react';
import type {
  WorkspaceImportBlobInput,
  WorkspaceImportFileInput,
  WorkspaceImportSource,
} from '../../../../preload';
import {
  clipboardFilesToWorkspaceBlobs,
  dataTransferFilesToWorkspaceFiles,
} from '../../lib/file-ingest';
import { useCodesignStore } from '../../store';
import { useAlephFrame } from '../aleph-frame';

const MAX_TEXTAREA_ROWS = 6;

export interface PromptKeyInput {
  key: string;
  shiftKey?: boolean;
  metaKey?: boolean;
  ctrlKey?: boolean;
  isComposing?: boolean;
  nativeIsComposing?: boolean;
  keyCode?: number;
  nativeKeyCode?: number;
}

export function shouldSubmitPromptKey(input: PromptKeyInput, compositionActive = false): boolean {
  if (input.key !== 'Enter') return false;
  if (
    compositionActive ||
    input.isComposing === true ||
    input.nativeIsComposing === true ||
    input.keyCode === 229 ||
    input.nativeKeyCode === 229
  ) {
    return false;
  }
  if (input.shiftKey === true) return false;
  return true;
}

export function getTextareaLineHeight(el: HTMLTextAreaElement): number {
  const styles = getComputedStyle(el);
  const lineHeight = Number.parseFloat(styles.lineHeight);
  if (Number.isFinite(lineHeight) && lineHeight > 0) return lineHeight;
  const fontSize = Number.parseFloat(styles.fontSize);
  const leading = Number.parseFloat(styles.getPropertyValue('--leading-body'));
  if (!Number.isFinite(fontSize) || fontSize <= 0 || !Number.isFinite(leading) || leading <= 0) {
    throw new Error('Textarea sizing tokens (--leading-body / fontSize) are missing or invalid');
  }
  return fontSize * leading;
}

export function getTextareaVerticalPadding(el: HTMLTextAreaElement): number {
  const styles = getComputedStyle(el);
  const top = Number.parseFloat(styles.paddingTop);
  const bottom = Number.parseFloat(styles.paddingBottom);
  return (Number.isFinite(top) ? top : 0) + (Number.isFinite(bottom) ? bottom : 0);
}

export function elapsedSecondsSince(
  startedAt: number | null | undefined,
  now = Date.now(),
): number {
  if (startedAt === null || startedAt === undefined) return 0;
  return Math.max(0, Math.floor((now - startedAt) / 1000));
}

export function formatElapsedSeconds(elapsedSec: number): string {
  return elapsedSec < 60
    ? `${elapsedSec}s`
    : `${Math.floor(elapsedSec / 60)}:${String(elapsedSec % 60).padStart(2, '0')}`;
}

function resizeTextarea(el: HTMLTextAreaElement): void {
  const rowHeight = getTextareaLineHeight(el);
  const verticalPadding = getTextareaVerticalPadding(el);
  const maxHeight = rowHeight * MAX_TEXTAREA_ROWS + verticalPadding;
  el.style.height = 'auto';
  el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
  el.style.overflowY = el.scrollHeight > maxHeight ? 'auto' : 'hidden';
}

export interface PromptInputProps {
  onSubmit: (prompt: string) => void;
  onCancel: () => void;
  isGenerating: boolean;
  /** Optional content rendered above the textarea, inside the composer card. */
  contextSummary?: ReactNode;
  /** Optional element rendered inside the textarea container, bottom-left. */
  leadingAction?: ReactNode;
  /* [rediseño · fase DISEÑO · pieza 07] EL CHIP DEL CEREBRO Y EL CONTADOR DE TOKENS.
     Los dos vivían en una fila DEBAJO del composer (`Sidebar.tsx`). El artboard pone el chip
     ADENTRO de la barrita, pegado al botón de enviar, y deja debajo una sola línea de apoyo.
     Bajan como nodos y no como datos: el chip es el ancla de `aleph-picker-unico.js` —el
     `<span data-aleph-modelo="rotulo">`— y quien lo tiene es quien lo arma. */
  modelSlot?: ReactNode;
  footerRight?: ReactNode;
  onImportFiles?: (input: {
    source: WorkspaceImportSource;
    files?: WorkspaceImportFileInput[];
    blobs?: WorkspaceImportBlobInput[];
  }) => Promise<void>;
}

export interface PromptInputHandle {
  focus: () => void;
  setPrompt: (value: string) => void;
}

/**
 * Prompt textarea + send/stop button. Extracted from Sidebar.tsx so the
 * chat pane can be rewritten without disturbing the send-path keybindings.
 *
 * Keybindings:
 *   Enter           — submit (unless Shift/Meta/Ctrl held)
 *   Meta/Ctrl+Enter — submit (power-user muscle memory)
 *   Shift+Enter     — newline
 */
export const PromptInput = forwardRef<PromptInputHandle, PromptInputProps>(function PromptInput(
  {
    onSubmit,
    onCancel,
    isGenerating,
    contextSummary,
    leadingAction,
    modelSlot,
    footerRight,
    onImportFiles,
  },
  ref,
) {
  const t = useT();
  const alephFrame = useAlephFrame();
  const taRef = useRef<HTMLTextAreaElement>(null);
  const compositionActiveRef = useRef(false);
  const [prompt, setPrompt] = useState('');
  const generationStage = useCodesignStore((s) => s.generationStage);
  const generationStartedAt = useCodesignStore((s) => {
    const currentDesignId = s.currentDesignId;
    return currentDesignId === null
      ? null
      : (s.generationByDesign[currentDesignId]?.startedAt ?? null);
  });

  const runningLabel = isGenerating
    ? (() => {
        switch (generationStage) {
          case 'sending':
            return t('loading.stage.sending');
          case 'thinking':
            return t('loading.stage.thinking');
          case 'streaming':
            return t('loading.stage.streaming');
          case 'parsing':
            return t('loading.stage.parsing');
          case 'rendering':
            return t('loading.stage.rendering');
          default:
            return t('loading.stage.thinking');
        }
      })()
    : null;

  // Elapsed timer — reassures users that long agent runs are still alive.
  // Only ticks while isGenerating; resets to 0 on each new run.
  const [elapsedSec, setElapsedSec] = useState(0);
  useEffect(() => {
    if (!isGenerating) {
      setElapsedSec(0);
      return;
    }
    const start = generationStartedAt ?? Date.now();
    setElapsedSec(elapsedSecondsSince(start));
    const id = setInterval(() => {
      setElapsedSec(elapsedSecondsSince(start));
    }, 500);
    return () => clearInterval(id);
  }, [generationStartedAt, isGenerating]);

  const elapsedText = formatElapsedSeconds(elapsedSec);

  useEffect(() => {
    if (taRef.current) resizeTextarea(taRef.current);
  });

  useImperativeHandle(ref, () => ({
    focus: () => {
      taRef.current?.focus();
    },
    setPrompt: (value) => {
      setPrompt(value);
      requestAnimationFrame(() => {
        if (taRef.current) resizeTextarea(taRef.current);
      });
    },
  }));

  function handleSubmit(e: FormEvent): void {
    e.preventDefault();
    if (!prompt.trim() || isGenerating) return;
    onSubmit(prompt.trim());
    setPrompt('');
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>): void {
    const native = e.nativeEvent as KeyboardEvent['nativeEvent'] & {
      isComposing?: boolean;
      keyCode?: number;
    };
    const isSendCombo = shouldSubmitPromptKey(
      {
        key: e.key,
        shiftKey: e.shiftKey,
        metaKey: e.metaKey,
        ctrlKey: e.ctrlKey,
        nativeIsComposing: native.isComposing,
        keyCode: e.keyCode,
        nativeKeyCode: native.keyCode,
      },
      compositionActiveRef.current,
    );
    if (isSendCombo) {
      e.preventDefault();
      handleSubmit(e);
    }
  }

  async function handleDrop(e: DragEvent<HTMLFormElement>): Promise<void> {
    const files = dataTransferFilesToWorkspaceFiles(e.dataTransfer);
    if (files.length === 0 || !onImportFiles || isGenerating) return;
    e.preventDefault();
    await onImportFiles({ source: 'composer', files });
  }

  async function handlePaste(e: ClipboardEvent<HTMLTextAreaElement>): Promise<void> {
    if (!onImportFiles || isGenerating || e.clipboardData.files.length === 0) return;
    e.preventDefault();
    const payload = await clipboardFilesToWorkspaceBlobs(e.clipboardData);
    await onImportFiles({ source: 'clipboard', ...payload });
  }

  const canSend = prompt.trim().length > 0 && !isGenerating;
  const sendDisabledReason = isGenerating
    ? t('disabledReason.generatingInProgress')
    : t('disabledReason.typePromptToSend');
  const composerFrameClass = [
    'relative rounded-[12px] border bg-[var(--color-surface)] shadow-[var(--shadow-soft)] transition-[border-color,box-shadow,background-color] duration-150 ease-out',
    isGenerating
      ? 'border-[var(--color-border-muted)] bg-[color-mix(in_srgb,var(--color-surface)_94%,var(--color-background-secondary))]'
      : 'border-[var(--color-border-muted)] focus-within:border-[var(--color-border-strong)] focus-within:shadow-[0_0_0_2px_var(--color-accent-soft),var(--shadow-soft)]',
  ].join(' ');

  /* El campo es EL MISMO en las dos caras: mismos handlers, mismo `ref`, mismo `resize`.
     Lo único que cambia es su clase, porque el artboard lo pone en su propio renglón arriba
     de los símbolos y no al lado de ellos. Duplicar el `<textarea>` habría duplicado seis
     handlers de teclado y composición — la forma más barata de que uno se quede atrás.

     ⚠️ EL PLACEHOLDER SIGUE SIENDO EL DEL STACK, Y LA REGLA ESTÁ MEDIDA, NO ELEGIDA.
     El frame estandariza CÓMO SE VE el placeholder, no QUÉ DICE. Quien lo fijó fue la fase de
     Oficina, que llegó antes: su `editor.tsx:1284` marca el nodo con `aleph-composer-ph` para
     que la hoja le ponga `300 15px/1.5` en `--al-etiqueta` —«acá sólo se marca, para no clavar
     medidas de Aleph adentro de un componente ajeno»— y deja pasar su `props.placeholder`
     intacto. Finanzas conserva el suyo, que además es DINÁMICO (cambia con el turno en curso,
     con Research Goal y con el seguimiento); Ciencia conserva sus ejemplos rotativos. Cambiar
     el texto acá rompería esa coherencia, no la crearía.
     La hoja del estándar respalda el corte para la barrita entera: «Lo estandarizado es el
     símbolo, el botón, la caja del menú y la fila. Las opciones de adentro son las de cada
     espacio».
     Y los dos mocks no coinciden entre sí: la pieza 07 dibuja «Pregunta cualquier cosa…» y la
     09 «Preguntá lo que quieras…», dos cadenas distintas para el mismo hueco en los cinco
     espacios — o sea relleno de mock, no especificación. Lo que sí es especificación es la
     tipografía, y ésa se cumple: medido en el lienzo, `300 15px` Poppins con el placeholder en
     `--al-etiqueta`, el MISMO contrato que Oficina. */
  const campo = (
    <textarea
      ref={taRef}
      value={prompt}
      onChange={(e) => {
        setPrompt(e.target.value);
        resizeTextarea(e.currentTarget);
      }}
      onKeyDown={handleKeyDown}
      onCompositionStart={() => {
        compositionActiveRef.current = true;
      }}
      onCompositionEnd={() => {
        compositionActiveRef.current = false;
      }}
      onPaste={(e) => void handlePaste(e)}
      placeholder={t('chat.placeholderRich')}
      rows={1}
      className={
        alephFrame.activo
          ? 'codesign-prompt-textarea aleph-barrita-campo'
          : 'codesign-prompt-textarea block min-h-[30px] min-w-0 flex-1 resize-none appearance-none border-0 bg-transparent px-[2px] py-[5px] text-[13.5px] leading-[1.55] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] shadow-none outline-none focus:outline-none focus:ring-0'
      }
      style={alephFrame.activo ? undefined : { fontFamily: 'var(--font-sans)' }}
    />
  );

  /* [rediseño · fase DISEÑO · pieza 07] LA BARRITA, COMO ESTÁ EN EL ARTBOARD.
     Tarjeta blanca de radio 22 con hairline, el campo en su propio renglón arriba y debajo la
     fila de controles: clip · dos palitos · hueco · chip del cerebro · enviar en círculo
     negro de 38. Y afuera de la tarjeta, la línea de apoyo.

     ⚠️ LA LÍNEA DE APOYO VA, Y ESTO CORRIGE A FINANZAS. Allá se la sacó con el frame puesto
     escribiendo que «no está en el artboard». Sí está: la pieza 07 la dibuja, textual,
     `font:300 11.5px 'Poppins'` en `#6b6b64`, debajo de la tarjeta — «Enter para enviar ·
     Shift+Enter para salto de línea». Fui a mirar el artboard en vez de fiarme del código de
     al lado.

     ⚠️ Y NADA SE PIERDE EN ESA LÍNEA. El renglón de estado que ya existía (la etapa del turno
     y el cronómetro) y el contador de tokens que vivía debajo del composer entran en el MISMO
     renglón: mientras corre un turno manda el estado, y en reposo la instrucción del atajo.
     Contadas antes y después, las dos siguen estando. */
  if (alephFrame.activo) {
    return (
      <form
        onSubmit={handleSubmit}
        onDrop={(e) => void handleDrop(e)}
        onDragOver={(e) => e.preventDefault()}
      >
        <div className="aleph-barrita">
          {contextSummary ? <div className="aleph-barrita-contexto">{contextSummary}</div> : null}
          {campo}
          <div className="aleph-barrita-fila">
            {leadingAction}
            <span className="aleph-barrita-hueco" />
            {modelSlot}
            {isGenerating ? (
              <button
                type="button"
                onClick={onCancel}
                aria-label={t('chat.stop')}
                title={t('chat.stop')}
                className="aleph-barrita-enviar aleph-barrita-parar"
              >
                <Square className="w-[11px] h-[11px]" strokeWidth={0} fill="currentColor" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!canSend}
                aria-label={t('chat.send')}
                title={!canSend ? sendDisabledReason : t('chat.send')}
                className="aleph-barrita-enviar"
              >
                {/* La flecha del artboard: caja 20, trazo 1.8, `M10 16V5m0 0 5 5m-5-5-5 5`. */}
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 20 20"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  aria-hidden
                >
                  <path d="M10 16V5m0 0 5 5m-5-5-5 5" />
                </svg>
              </button>
            )}
          </div>
        </div>
        <div className="aleph-barrita-pie" aria-live="polite">
          {runningLabel ? (
            <span className="aleph-barrita-pie-estado">
              <span aria-hidden className="aleph-barrita-pulso" />
              <span className="truncate">{runningLabel}</span>
            </span>
          ) : (
            <span className="aleph-barrita-pie-atajo">{t('chat.inputHint')}</span>
          )}
          {runningLabel ? (
            <span className="aleph-barrita-pie-num">{elapsedText}</span>
          ) : (
            footerRight
          )}
        </div>
      </form>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      onDrop={(e) => void handleDrop(e)}
      onDragOver={(e) => e.preventDefault()}
    >
      <div className={composerFrameClass}>
        {contextSummary ? (
          <div className="border-b border-[var(--color-border-subtle)] px-[12px] py-[10px]">
            {contextSummary}
          </div>
        ) : null}
        <div className="flex items-end gap-[var(--space-2)] px-[var(--space-2)] py-[var(--space-2)]">
          {leadingAction ? <div className="shrink-0 pb-[1px]">{leadingAction}</div> : null}
          {campo}

          <div className="shrink-0 pb-[1px]">
            {isGenerating ? (
              <button
                type="button"
                onClick={onCancel}
                aria-label={t('chat.stop')}
                className="inline-flex h-[30px] w-[30px] items-center justify-center rounded-[var(--radius-md)] border border-[var(--color-border-muted)] bg-[var(--color-surface-hover)] text-[var(--color-error)] shadow-[var(--shadow-soft)] transition-[background-color,border-color,color,transform] duration-150 hover:border-[var(--color-error)]/40 hover:bg-[var(--color-surface-active)] active:scale-[0.94]"
              >
                <Square className="w-[9px] h-[9px]" strokeWidth={0} fill="currentColor" />
              </button>
            ) : (
              <Tooltip label={!canSend ? sendDisabledReason : undefined} side="top">
                <button
                  type="submit"
                  disabled={!canSend}
                  aria-label={t('chat.send')}
                  className="inline-flex h-[30px] w-[30px] items-center justify-center rounded-[var(--radius-md)] bg-[var(--color-accent)] text-white shadow-[var(--shadow-soft)] transition-[background-color,box-shadow,transform] duration-150 hover:bg-[var(--color-accent-hover)] hover:shadow-[var(--shadow-card)] active:scale-[0.94] disabled:cursor-not-allowed disabled:opacity-25 disabled:shadow-none"
                >
                  <ArrowUp className="w-[15px] h-[15px]" strokeWidth={2.5} />
                </button>
              </Tooltip>
            )}
          </div>
        </div>
      </div>
      {runningLabel ? (
        <div
          aria-live="polite"
          className="mt-[var(--space-2)] flex min-h-[18px] items-center justify-between gap-[var(--space-2)] px-[var(--space-1)] text-[11px] text-[var(--color-text-muted)]"
        >
          <div className="inline-flex min-w-0 items-center gap-[var(--space-1_5)]">
            <span
              aria-hidden
              className="inline-block h-[6px] w-[6px] shrink-0 rounded-full bg-[var(--color-accent)] opacity-75 animate-pulse"
            />
            <span className="truncate">{runningLabel}</span>
          </div>
          <span
            className="shrink-0 tabular-nums"
            style={{ fontFamily: 'var(--font-mono)', fontFeatureSettings: "'tnum'" }}
          >
            {elapsedText}
          </span>
        </div>
      ) : null}
    </form>
  );
});
