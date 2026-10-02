import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { ColorSwatch, toNativeColorInputValue } from './TweakPanel.inputs';

describe('toNativeColorInputValue', () => {
  it('normalizes native color input values', () => {
    expect(toNativeColorInputValue('#fff')).toBe('#ffffff');
    expect(toNativeColorInputValue('#F97316')).toBe('#f97316');
    expect(toNativeColorInputValue('rgb(14, 165, 233)')).toBe('#0ea5e9');
    expect(toNativeColorInputValue('rgba(255, 255, 255, 0.42)')).toBe('#ffffff');
    expect(toNativeColorInputValue('rgb(100% 0% 50% / 0.5)')).toBe('#ff0080');
  });

  it('returns null for CSS colors that cannot be represented as native sRGB hex', () => {
    expect(toNativeColorInputValue('oklch(15% 0.01 260)')).toBeNull();
    expect(toNativeColorInputValue('white')).toBeNull();
  });
});

describe('ColorSwatch', () => {
  it('keeps non-hex CSS colors clickable by rendering a native color input', () => {
    const html = renderToStaticMarkup(
      <ColorSwatch value="oklch(15% 0.01 260)" onChange={vi.fn()} pickColorLabel="Pick color" />,
    );

    expect(html).toContain('type="color"');
    expect(html).toContain('value="#000000"');
    expect(html).toContain('aria-label="Pick color"');
  });

  it('uses a normalized picker value while preserving the visible token text', () => {
    const html = renderToStaticMarkup(
      <ColorSwatch value="rgba(255, 255, 255, 0.42)" onChange={vi.fn()} pickColorLabel="Pick" />,
    );

    expect(html).toContain('type="color"');
    expect(html).toContain('value="#ffffff"');
    expect(html).toContain('value="rgba(255, 255, 255, 0.42)"');
  });
});
