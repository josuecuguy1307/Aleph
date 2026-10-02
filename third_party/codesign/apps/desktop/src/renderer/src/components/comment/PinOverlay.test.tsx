import type { CommentRow } from '@open-codesign/shared';
import { describe, expect, it } from 'vitest';
import { pinStyleFromRect, variantFor } from './PinOverlay';

function comment(overrides: Partial<CommentRow> = {}): CommentRow {
  return {
    schemaVersion: 1,
    id: overrides.id ?? 'c1',
    designId: overrides.designId ?? 'd1',
    snapshotId: overrides.snapshotId ?? 's1',
    kind: overrides.kind ?? 'note',
    selector: overrides.selector ?? 'h1',
    tag: overrides.tag ?? 'h1',
    outerHTML: overrides.outerHTML ?? '<h1/>',
    rect: overrides.rect ?? { top: 100, left: 200, width: 50, height: 20 },
    text: overrides.text ?? 'hi',
    status: overrides.status ?? 'pending',
    createdAt: overrides.createdAt ?? '2026-04-20T00:00:00Z',
    appliedInSnapshotId: overrides.appliedInSnapshotId ?? null,
  };
}

describe('variantFor', () => {
  it('uses note styling for kind=note', () => {
    expect(variantFor(comment({ kind: 'note' })).text).toContain('text-primary');
  });

  it('uses filled accent for pending edits', () => {
    const v = variantFor(comment({ kind: 'edit', status: 'pending' }));
    expect(v.bg).toContain('bg-[var(--color-accent)]');
    expect(v.text).toBe('text-white');
  });

  it('uses outlined accent for applied edits', () => {
    const v = variantFor(comment({ kind: 'edit', status: 'applied' }));
    expect(v.bg).toBe('bg-transparent');
    expect(v.text).toContain('text-[var(--color-accent)]');
  });
});

describe('pinStyleFromRect', () => {
  it('anchors to the top-right corner of the rect, offset by 10px', () => {
    const pos = pinStyleFromRect({ top: 100, left: 50, width: 80, height: 40 }, 100);
    // top = 100 - 10 = 90; left = 50 + 80 - 10 = 120
    expect(pos).toEqual({ top: '90px', left: '120px' });
  });

  it('scales with zoom', () => {
    const pos = pinStyleFromRect({ top: 100, left: 50, width: 80, height: 40 }, 50);
    // scale = 0.5; top = 100*0.5 - 10 = 40; left = 50*0.5 + 80*0.5 - 10 = 55
    expect(pos).toEqual({ top: '40px', left: '55px' });
  });

  it('takes a rect argument so the overlay can substitute a live rect', () => {
    // PinOverlay calls this with liveRects[selector] ?? stored — what keeps
    // the badge glued to the element after iframe scroll.
    const live = pinStyleFromRect({ top: 10, left: 5, width: 80, height: 40 }, 100);
    expect(live).toEqual({ top: '0px', left: '75px' });
  });
});
