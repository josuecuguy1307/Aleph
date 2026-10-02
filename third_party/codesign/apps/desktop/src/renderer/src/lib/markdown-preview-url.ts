import { defaultUrlTransform } from 'react-markdown';

/** Only embedded PNG image sources bypass the default Markdown URL policy. */
export function markdownPreviewUrl(url: string, key: string): string {
  if (
    key === 'src' &&
    url.length <= 16 * 1024 * 1024 &&
    /^data:image\/png;base64,iVBORw0KGgo[A-Za-z0-9+/]*={0,2}$/u.test(url)
  ) return url;
  return defaultUrlTransform(url);
}
