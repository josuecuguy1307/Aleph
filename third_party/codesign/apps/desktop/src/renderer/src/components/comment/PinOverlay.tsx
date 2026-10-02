import { useT } from '@open-codesign/i18n';
import type { CommentRect, CommentRow } from '@open-codesign/shared';

export interface PinOverlayProps {
  /** Comments filtered to the currently-viewed snapshot. */
  comments: CommentRow[];
  /** Zoom ratio (1 at 100%) applied to the preview so pin placement stays aligned. */
  zoom: number;
  /** Called when a pin is clicked; opens the CommentBubble anchored at its rect. */
  onPinClick: (comment: CommentRow) => void;
  /** Live, iframe-viewport-relative rects by selector. When present for a
   *  comment's selector, it overrides the stored rect — this is how pins
   *  stay glued to their element across iframe scroll/resize. Unscaled. */
  liveRects?: Record<string, CommentRect>;
}

export interface PinVariant {
  bg: string;
  border: string;
  text: string;
  ring: string;
}

/**
 * Visual variant for each pin — matches the three states described in the
 * Claude Design research: note (yellow filled), pending edit (orange filled),
 * applied edit (orange outlined, faded).
 */
export function variantFor(comment: CommentRow): PinVariant {
  if (comment.kind === 'note') {
    return {
      bg: 'bg-[var(--color-warning-soft,#fde68a)]',
      border: 'border-[var(--color-warning,#ca8a04)]',
      text: 'text-[var(--color-text-primary)]',
      ring: 'ring-[var(--color-warning,#ca8a04)]',
    };
  }
  if (comment.status === 'applied') {
    return {
      bg: 'bg-transparent',
      border: 'border-[var(--color-accent)]',
      text: 'text-[var(--color-accent)]',
      ring: 'ring-[var(--color-accent)]',
    };
  }
  return {
    bg: 'bg-[var(--color-accent)]',
    border: 'border-[var(--color-accent)]',
    text: 'text-white',
    ring: 'ring-[var(--color-accent)]',
  };
}

export function pinStyleFromRect(rect: CommentRect, zoom: number): { top: string; left: string } {
  const scale = zoom / 100;
  // Position pin at the outer top-right corner: half-overlapping the corner
  // so it reads as a "badge" attached to the element rather than floating
  // randomly. Pin is 20px, so offset by -10 = half outside.
  const top = rect.top * scale - 10;
  const left = rect.left * scale + rect.width * scale - 10;
  return { top: `${top}px`, left: `${left}px` };
}

export function PinOverlay({ comments, zoom, onPinClick, liveRects }: PinOverlayProps) {
  const t = useT();
  if (comments.length === 0) return null;
  return (
    <div className="pointer-events-none absolute inset-0 z-[5]">
      {comments.map((comment, index) => {
        const v = variantFor(comment);
        const rect = liveRects?.[comment.selector] ?? comment.rect;
        const pos = pinStyleFromRect(rect, zoom);
        const label =
          comment.kind === 'note'
            ? t('pinOverlay.note', { n: index + 1 })
            : t('pinOverlay.edit', { n: index + 1 });
        return (
          <button
            key={comment.id}
            type="button"
            title={comment.text}
            aria-label={label}
            onClick={() => onPinClick(comment)}
            style={pos}
            className={`pointer-events-auto absolute flex h-5 w-5 items-center justify-center rounded-full border-[1.5px] text-[10px] font-semibold leading-none tabular-nums shadow-[0_2px_6px_rgba(0,0,0,0.25)] transition-transform hover:scale-110 focus:outline-none focus:ring-2 focus:ring-offset-1 ${v.bg} ${v.border} ${v.text} ${v.ring}`}
          >
            {index + 1}
          </button>
        );
      })}
    </div>
  );
}
