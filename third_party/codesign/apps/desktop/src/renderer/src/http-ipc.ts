/** Long engine operations use short loopback requests so the webview cannot time out the run. */
export async function invokeHttpIpc(channel: string, args: unknown[]): Promise<unknown> {
  let response = await fetch(`/.aleph/ipc/${encodeURIComponent(channel)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ args }),
  });
  let result = await response.json() as { ok?: boolean; value?: unknown; error?: string; jobId?: string };
  if (response.status === 202 && result.jobId) {
    const path = `/.aleph/jobs/${encodeURIComponent(result.jobId)}`;
    do {
      await new Promise<void>((resolve) => setTimeout(resolve, 1000));
      response = await fetch(path, { headers: { 'Cache-Control': 'no-store' } });
      result = await response.json() as typeof result;
    } while (response.status === 202);
  }
  if (!response.ok || !result.ok) throw new Error(result.error || `Falló ${channel}`);
  return result.value;
}
