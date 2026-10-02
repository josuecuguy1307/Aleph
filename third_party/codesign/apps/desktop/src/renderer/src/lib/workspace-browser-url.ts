export function workspaceBrowserUrl(protocolUrl: string): string {
  if (typeof window === 'undefined' || !window.location ||
      !['http:', 'https:'].includes(window.location.protocol) ||
      !['127.0.0.1', 'localhost', '[::1]'].includes(window.location.hostname)) return protocolUrl;
  const url = new URL(protocolUrl);
  if (url.protocol !== 'workspace:') return protocolUrl;
  return `${window.location.origin}/.aleph/workspace/${url.hostname}${url.pathname}`;
}
