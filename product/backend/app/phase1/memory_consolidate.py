"""memory_consolidate.py — CONSOLIDACIÓN (patrón MemOS, mínimo viable · fix 26).

Un job INVOCABLE (no cron todavía) que limpia lo ya engordado por la captura vieja:
  (a) FUNDE near-duplicados: de un cluster de memorias casi-idénticas (Jaccard de tokens
      salientes ≥ umbral) conserva la MÁS RECIENTE y borra las demás. Mata las N copias.
  (b) DEGRADA meta: las memorias que son meta-observaciones del comportamiento (heurística
      léxica del read-path) se etiquetan kind='meta' → fuera del budget de dominio (el recall
      ya demota lo meta; acá lo persistimos explícito y auditable).

Determinista, idempotente (correrlo dos veces no cambia el resultado), fail-safe por-id. Reusa
las MISMAS heurísticas que memory_recall (una sola fuente de verdad del tokenizado/jaccard/meta).
NO toca: gate o5, bus B2, memoria de cuenta, kinds skill/episodica de lo que NO es dup ni meta.
"""
from __future__ import annotations
from typing import Any

from app.phase1 import repo
from app.phase1 import memory_recall as _mrec


def consolidate_agent(conn, puppet_id: str, *, dedup_thresh: float = 0.72,
                      dry_run: bool = False) -> dict[str, Any]:
    """Consolida la memoria de UN agente. Devuelve stats {before, fused, meta_degraded, after}.
    dry_run=True calcula sin escribir (para inspección antes de operar sobre 273+)."""
    mems = repo.list_memories(conn, puppet_id)   # created_at DESC (más reciente primero)
    kept_tok: list[set] = []
    to_delete: list[str] = []       # near-dups (los más viejos del cluster)
    to_meta: list[str] = []         # metas conservadas → etiquetar kind='meta'
    for m in mems:
        mid = m.get("id")
        content = m.get("content", "")
        tk = _mrec._salient_tokens(content)
        # cluster de near-dup ya conservado (más reciente) → este es un duplicado viejo
        if tk and any(_mrec._jaccard(tk, kt) >= dedup_thresh for kt in kept_tok):
            if mid:
                to_delete.append(mid)
            continue
        kept_tok.append(tk)
        # entre los CONSERVADOS: si es meta y no está ya tagueada, degradar a kind='meta'
        if _mrec._is_meta(content) and ((m.get("meta") or {}).get("kind") != "meta") and mid:
            to_meta.append(mid)
    stats = {"before": len(mems), "fused": len(to_delete),
             "meta_degraded": len(to_meta), "after": len(mems) - len(to_delete)}
    if dry_run:
        return stats
    # [Casa 2 · 2.4] `jsonb_set` lo rechaza el dialecto (JSONB binario en SQLite); el
    # equivalente exacto es `json_set` (ver repo.reclassify_memory). El literal JSON
    # '"meta"' pasa a texto plano 'meta' porque json_set ya cita el valor. `ANY(%s::uuid[])`
    # sí lo traduce el dialecto → sólo diverge la función JSON.
    if repo._dbmod().es_cliente():
        set_meta = ("UPDATE agent_memories SET meta = json_set(coalesce(meta, '{}'), "
                    "'$.kind', 'meta') WHERE id = ANY(%s::uuid[])")
    else:
        set_meta = ("UPDATE agent_memories SET meta = jsonb_set(coalesce(meta, '{}'::jsonb), "
                    "'{kind}', '\"meta\"') WHERE id = ANY(%s::uuid[])")
    with conn.cursor() as cur:
        if to_delete:
            cur.execute("DELETE FROM agent_memories WHERE id = ANY(%s::uuid[])", (to_delete,))
        if to_meta:
            cur.execute(set_meta, (to_meta,))
    conn.commit()
    return stats
