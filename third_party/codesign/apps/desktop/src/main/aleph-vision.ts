export function selectedVisionCapability(raw: unknown): boolean {
  if (!raw || typeof raw !== 'object') throw new Error('No se pudo leer la capacidad visual del selector de Aleph.');
  const selector = raw as { seleccion_id?: string; modelos?: Array<{ picker_id?: string; model_use_capabilities?: string[] }> };
  const selected = selector.modelos?.find((model) => model.picker_id === selector.seleccion_id);
  if (!selected || !Array.isArray(selected.model_use_capabilities)) {
    throw new Error('El selector de Aleph no declaró las capacidades del modelo elegido.');
  }
  return selected.model_use_capabilities.includes('vision');
}

export async function alephPreviewVision(input: {
  provider: string;
  baseUrl?: string | undefined;
  httpHeaders?: Record<string, string> | undefined;
  requested: boolean;
}): Promise<boolean> {
  if (!input.requested || input.provider !== 'aleph-brain') return input.requested;
  const url = new URL(input.baseUrl ?? '');
  if (url.hostname !== '127.0.0.1' || !url.pathname.startsWith('/v1/workspaces/brain/openai')) {
    throw new Error('La capacidad visual de Aleph requiere su endpoint local registrado.');
  }
  url.pathname = '/v1/modelos/selector';
  url.search = '?contexto=sala';
  const response = await fetch(url, { headers: input.httpHeaders ?? {} });
  if (!response.ok) throw new Error(`No se pudo consultar el selector de Aleph (${response.status}).`);
  return selectedVisionCapability(await response.json());
}
