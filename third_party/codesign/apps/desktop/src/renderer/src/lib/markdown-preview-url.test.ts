import { describe, expect, it } from 'vitest';
import { markdownPreviewUrl } from './markdown-preview-url';

describe('embedded export image URLs', () => {
  const png = 'data:image/png;base64,iVBORw0KGgo=';
  it('preserves an embedded PNG in an image, but not in a link', () => {
    expect(markdownPreviewUrl(png, 'src')).toBe(png);
    expect(markdownPreviewUrl(png, 'href')).toBe('');
  });
  it('keeps the default policy for unsafe schemes and ordinary links', () => {
    expect(markdownPreviewUrl('javascript:alert(1)', 'src')).toBe('');
    expect(markdownPreviewUrl('data:text/html;base64,PHNjcmlwdD4=', 'src')).toBe('');
    expect(markdownPreviewUrl('https://example.com/image.png', 'src')).toBe('https://example.com/image.png');
  });
});
