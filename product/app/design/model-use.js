// Cliente único de model-use/v1 para las superficies sin bundler de Aleph.
// Sólo arma intención, scope y requisitos; jamás compila provider/model, URL o secretos.

function callId(prefix) {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function base({ id, idempotencyKey, workspaceId, callClass, context, selectionRef,
                selectionScope, policyRef, capabilities, input, tools, generation, stream }) {
  return {
    schema_version: "model-use/v1",
    call_id: id,
    idempotency_key: idempotencyKey || id,
    workspace_id: workspaceId,
    call_class: callClass,
    context: {
      session_id: context?.sessionId || null,
      task_id: context?.taskId || null,
      agent_id: context?.agentId || null,
      partner_id: context?.partnerId || null,
      entity_id: context?.entityId || null,
    },
    selection_ref: selectionRef || null,
    selection_scope: selectionScope,
    policy_ref: policyRef || null,
    capabilities: {
      required: capabilities?.required || [],
      preferred: capabilities?.preferred || [],
      optional: capabilities?.optional || [],
    },
    input: {
      messages: input?.messages || [],
      attachments: input?.attachments || [],
    },
    tools: {
      manifest_ref: tools?.manifestRef || null,
      definitions: tools?.definitions || [],
      required: Boolean(tools?.required),
    },
    generation: {
      temperature: generation?.temperature ?? null,
      max_output_tokens: generation?.maxOutputTokens ?? null,
      reasoning_effort: generation?.reasoningEffort || null,
      response_schema: generation?.responseSchema || null,
    },
    stream: stream !== false,
  };
}

export function rawModelUse({ workspaceId, callClass, selectionRef, sessionId, taskId,
                              entityId, messages, attachments, requiredCapabilities,
                              preferredCapabilities, stream = true, id, idempotencyKey }) {
  const cid = id || callId(workspaceId || "raw");
  return base({
    id: cid, idempotencyKey, workspaceId, callClass,
    context: { sessionId, taskId, entityId },
    selectionRef,
    selectionScope: sessionId ? "session" : (taskId ? "task" : "default"),
    capabilities: { required: requiredCapabilities, preferred: preferredCapabilities },
    input: { messages, attachments },
    tools: {}, generation: {}, stream,
  });
}

export function recipeV1ModelUse({ recipe, agentId, selectionRef, workspaceId, callClass,
                                   sessionId, taskId, messages, attachments,
                                   requiredCapabilities, preferredCapabilities,
                                   stream = true, id, idempotencyKey }) {
  if (recipe?.schema_version !== "v1") throw new Error("recipeV1ModelUse exige Recipe v1");
  if (!agentId) throw new Error("recipeV1ModelUse exige agentId");
  const cid = id || callId(workspaceId || "recipe");
  const beltRef = recipe?.belt?.belt_ref || null;
  return base({
    id: cid,
    idempotencyKey: idempotencyKey || `recipe:${agentId}:${cid}`,
    workspaceId,
    callClass,
    context: { sessionId, taskId, agentId },
    selectionRef,
    selectionScope: "agent",
    policyRef: `recipe:v1:${agentId}`,
    capabilities: { required: requiredCapabilities, preferred: preferredCapabilities },
    input: { messages, attachments },
    tools: { manifestRef: beltRef, required: Boolean(beltRef) },
    generation: {
      temperature: recipe?.model?.temperature,
      maxOutputTokens: recipe?.model?.max_tokens,
    },
    stream,
  });
}

const ROUTE_FIELDS = new Set([
  "primary", "base_url", "alias", "byok_ref", "brain_provider", "fallback",
  "key", "api_key", "secret", "token", "key_env",
]);

/**
 * Payload de persistencia del Cuarto. Conserva perillas y modelos auxiliares, pero el
 * routing del Núcleo no cruza la red: el backend lo reconstruye desde selection_ref.
 * Sin selectionRef cae al payload legacy para que un cliente viejo siga siendo editable.
 */
export function recipeV1SavePayload(recipe, selectionRef) {
  const ref = String(selectionRef || "").trim();
  if (!ref) return { config: recipe, model_selection_ref: null };
  const controls = Object.fromEntries(
    Object.entries(recipe?.model || {}).filter(([key]) => !ROUTE_FIELDS.has(key)),
  );
  return {
    config: { ...recipe, model: controls },
    model_selection_ref: ref,
  };
}

/**
 * Evita una ventana rota durante actualizaciones desktop: los HTML nuevos pueden quedar
 * delante de un backend anterior hasta el siguiente reinicio. Sólo usa el payload
 * secretless si ese backend publica model-use/v1; cualquier 404/fallo conserva el POST
 * legacy completo y no impide guardar el agente.
 */
export async function compatibleRecipeV1SavePayload(
  recipe, selectionRef, { headers, fetchImpl } = {},
) {
  const doFetch = fetchImpl || globalThis.fetch;
  try {
    const response = await doFetch("/v1/model-use/choices", {
      headers: { Accept: "application/json", ...(headers || {}) },
    });
    if (response.ok) return recipeV1SavePayload(recipe, selectionRef);
  } catch (_) {
    // Compatibilidad de despliegue: guardar por legacy es mejor que perder el trabajo.
  }
  return { config: recipe, model_selection_ref: null };
}

export async function shadowResolve(request, { headers, fetchImpl } = {}) {
  const doFetch = fetchImpl || globalThis.fetch;
  try {
    const response = await doFetch("/v1/model-use/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", ...(headers || {}) },
      body: JSON.stringify(request),
    });
    const data = await response.json().catch(() => null);
    return {
      ok: response.ok,
      call_id: request.call_id,
      selection_ref: request.selection_ref,
      detail: response.ok ? data : data?.detail || null,
    };
  } catch (error) {
    return {
      ok: false,
      call_id: request.call_id,
      selection_ref: request.selection_ref,
      detail: { error: "shadow_unreachable", detail: error?.message || "sin conexión" },
    };
  }
}
