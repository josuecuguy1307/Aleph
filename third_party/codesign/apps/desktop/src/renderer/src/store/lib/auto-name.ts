export function autoNameFromPrompt(prompt: string): string {
  const condensed = prompt.replace(/\s+/g, ' ').trim();
  if (condensed.length === 0) return 'Untitled design';
  return condensed.length > 40 ? `${condensed.slice(0, 40).trimEnd()}…` : condensed;
}

export function isDefaultDesignName(name: string): boolean {
  return name === 'Untitled design' || /^Untitled design \d+$/.test(name);
}
