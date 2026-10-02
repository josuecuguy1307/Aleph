"""
billing.py — METERING + QUOTA + CAP per-usuario · owner: T7-billing.

EL TRABAJO DE T7: consumir el COST-EVENT (§4.6) que PRODUCE T5/T4 y convertirlo en
  (1) un LEDGER por-call (billing_ledger)          — qué costó cada llamada,
  (2) un metering por-usuario (sum del ledger)     — cuánto lleva gastado un usuario,
  (3) un CAP de presupuesto que CORTA al usuario que se excede (no funde la cuenta).

NO tocamos el gateway de T5: sólo CONSUMIMOS sus cost-events (la forma congelada en
platform/assembler/CONTRACT-RECIPE-v1-FROZEN.md §5):

  { "type":"cost", "kind":"model"|"tool", "user_id":..., "run_id":...,
    "model": "..."|null, "tool": "..."|null,
    "tokens": {"prompt":N,"completion":N,"total":N}, "tokens_measured": bool,
    "usd": 0.0001557|null, "price_source": "..." }

INVARIANTE (AUTH §4.5): `user_id` scopea TODO. Ninguna métrica se lee sin scope.

Honestidad de plata:
  - usd se MIDE (lo trae el cost-event de T5: token medido × tarifa documentada). Si el
    modelo no tiene tarifa, el cost-event trae usd=null → acá NO se inventa: la fila del
    ledger guarda NULL y NO suma al gasto (no cobramos lo que no sabemos tarifar).
  - El cap acota el gasto TOTAL del usuario (créditos pre-pagos). Un run en vuelo puede
    sobrepasar el cap por su propio costo (chequeamos ANTES, cobramos DESPUÉS); el
    siguiente run ya queda cortado. Es metering pre-pago estándar; documentado, no oculto.

Stdlib + psycopg2 (vía repo.get_conn del caller). Decimal para la aritmética de plata.
"""

from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Optional

# ── CAP BASE POR TIER (config de producto · ajustable) ──────────────────────────
# El presupuesto que cada tier trae "de fábrica" (en USD). free = allowance chico para
# que la persona promedio pruebe sin fundir nada; los tiers pagos suben el techo. Esto
# es DEFAULT: el cap efectivo = base_tier + créditos comprados (Stripe), acotado por el
# self-limit del usuario (ver get_cap). Subir el techo de verdad = comprar créditos.
TIER_CAPS_USD: dict[str, float] = {
    "free":    1.00,
    "basico":  25.00,
    "tecnico": 100.00,
}
DEFAULT_CAP_USD = 1.00  # tier desconocido → trato como free (lado seguro)

_USD_Q = Decimal("0.00000001")  # 8 decimales (microcentavos) — igual precisión que el ledger


def _d(v: Any) -> Decimal:
    """A Decimal robusto (None/'' → 0)."""
    if v is None or v == "":
        return Decimal(0)
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def _money(v: Any) -> float:
    """Decimal/num → float redondeado a 8 decimales, para el borde JSON."""
    return float(_d(v).quantize(_USD_Q, rounding=ROUND_HALF_UP))


# ── SCHEMA ──────────────────────────────────────────────────────────────────────
_BILLING_SCHEMA = (
    Path(__file__).resolve().parents[4] / "platform" / "db" / "billing_schema.sql"
)


def apply_billing_schema(conn) -> None:
    """Aplica billing_schema.sql (idempotente). El caller pasa una conexión a puppet_ai."""
    ddl = _BILLING_SCHEMA.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()


# ── tier del usuario (para el cap base) ─────────────────────────────────────────

# ── LA FRONTERA DE BILLING EN EL CLIENTE [Casa 2 · Fase 2 · 2.2b] ─────────────────
# Las 4 tablas de este módulo (billing_quota, billing_ledger, billing_runs_ingested,
# billing_stripe_events) son de `TABLAS_CONTROL` en role.py: NUNCA salen del plano de
# control. Pero `billing_router` no es el único que llega hasta acá — `router.py:1622`,
# `:1664` y `:1929` llaman preflight/record_run_cost en el camino caliente de CADA run, y
# `router.py` se monta SIEMPRE (main.py:508). El corte del 2.0 sacó el router y dejó el
# módulo colgado del run.
#
# Sin esta guarda, el cliente con el schema de 2.1 muere con "no such table:
# billing_quota" en cada run medido. Con ella, aplica D1: **el muro real es server-side**
# (construir re-verifica contra el Motor B), así que localmente no hay presupuesto que
# medir ni cortar. No es un atajo — es la decisión ya tomada, hecha código.
#
# ⚠️ Lo que NO se hace: mover billing_* al schema del cliente. Serían la autoridad de
# plata viviendo en un archivo que el usuario puede editar con cualquier visor de SQLite.


def _es_cliente() -> bool:
    """El rol, vía la capa canónica — una sola fuente de verdad (platform/db/db.py)."""
    try:
        from app.phase1 import repo
        return bool(repo._dbmod().es_cliente())
    except Exception:                                  # noqa: BLE001
        return False                                   # ante la duda, comportamiento previo


def _sin_metering_local(fn: str) -> None:
    """Para lo que NO tiene equivalente local: se dice, no se devuelve un número inventado.

    `set_self_limit` y `add_credit` sólo los llama `billing_router`, que es control-only
    (main.py:639). Si algún día alguien los cablea al camino compartido, esto avisa en vez
    de escribir en una tabla que no existe.
    """
    if _es_cliente():
        raise RuntimeError(
            f"billing.{fn}() no existe en el cliente: el presupuesto y los créditos son "
            f"del plano de control (role.TABLAS_CONTROL). El muro local es server-side (D1).")


def _user_tier(conn, user_id: str) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT tier FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
    return (row[0] if row and row[0] else "free")


def base_cap_for_tier(tier: Optional[str]) -> Decimal:
    return _d(TIER_CAPS_USD.get((tier or "").lower(), DEFAULT_CAP_USD))


# ── QUOTA / CAP ──────────────────────────────────────────────────────────────────

def _quota_row(conn, user_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT user_id, credits_usd, self_limit_usd, stripe_customer_id "
            "FROM billing_quota WHERE user_id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [c[0] for c in cur.description]
    return dict(zip(cols, row))


def get_cap(conn, user_id: str) -> Decimal:
    """Cap EFECTIVO (USD) del usuario:  min(base_tier + créditos, self_limit ?? ∞).

    El base sale del tier ACTUAL (refleja upgrades solo); los créditos comprados y el
    self-limit son deltas por usuario (billing_quota). Sin fila de quota → sólo el tier.
    """
    base = base_cap_for_tier(_user_tier(conn, user_id))
    q = _quota_row(conn, user_id)
    credits = _d(q["credits_usd"]) if q else Decimal(0)
    ceiling = base + credits
    if q and q.get("self_limit_usd") is not None:
        self_limit = _d(q["self_limit_usd"])
        return self_limit if self_limit < ceiling else ceiling
    return ceiling


def spent_usd(conn, user_id: str) -> Decimal:
    """Lo GASTADO por el usuario (suma del ledger; usd NULL no suma — no se inventa)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(usd), 0) FROM billing_ledger WHERE user_id = %s",
            (user_id,),
        )
        return _d(cur.fetchone()[0])


def get_meter(conn, user_id: str) -> dict[str, Any]:
    """La VERDAD de metering del usuario: gastado, cap, restante, ¿sobre el cap?, tier."""
    tier = _user_tier(conn, user_id)
    cap = get_cap(conn, user_id)
    spent = spent_usd(conn, user_id)
    remaining = cap - spent
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*), COALESCE(SUM(total_tokens),0) FROM billing_ledger WHERE user_id = %s",
            (user_id,),
        )
        n_events, tot_tokens = cur.fetchone()
    return {
        "user_id": str(user_id),
        "tier": tier,
        "spent_usd": _money(spent),
        "cap_usd": _money(cap),
        "remaining_usd": _money(remaining),
        "over_cap": spent >= cap,
        "events": int(n_events or 0),
        "total_tokens": int(tot_tokens or 0),
    }


def preflight(conn, user_id: Optional[str]) -> dict[str, Any]:
    """EL CORTE: ¿el usuario puede arrancar un run? Bloquea si ya no le queda presupuesto.

    Recurso ANÓNIMO (user_id None) → allowed (no hay a quién medir/facturar; honest).
    Usuario con remaining <= 0 → allowed=False, reason='over_budget' (el run NO arranca).
    EN EL CLIENTE → allowed, sin consultar (ver `_sin_metering_local`).
    """
    if _es_cliente():
        return {"allowed": True, "reason": "client_local", "user_id":
                str(user_id) if user_id else None}
    if not user_id:
        return {"allowed": True, "reason": "anonymous", "user_id": None}
    m = get_meter(conn, user_id)
    allowed = _d(m["remaining_usd"]) > 0
    return {
        "allowed": allowed,
        "reason": None if allowed else "over_budget",
        "user_id": str(user_id),
        "tier": m["tier"],
        "spent_usd": m["spent_usd"],
        "cap_usd": m["cap_usd"],
        "remaining_usd": m["remaining_usd"],
    }


def set_self_limit(conn, user_id: str, self_limit_usd: Optional[float]) -> dict[str, Any]:
    """El usuario se pone (o quita, con None) un TOPE de gasto. Autocontrol: sólo BAJA el
    cap efectivo (el techo real lo da tier+créditos). Devuelve el meter actualizado."""
    _sin_metering_local("set_self_limit")
    if self_limit_usd is not None and _d(self_limit_usd) < 0:
        raise ValueError("self_limit_negativo")
    val = None if self_limit_usd is None else str(_d(self_limit_usd))
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO billing_quota (user_id, self_limit_usd, updated_at)
            VALUES (%s, %s, now())
            ON CONFLICT (user_id)
            DO UPDATE SET self_limit_usd = EXCLUDED.self_limit_usd, updated_at = now()
            """,
            (user_id, val),
        )
    conn.commit()
    return get_meter(conn, user_id)


def add_credit(conn, user_id: str, usd: float, *, stripe_customer_id: Optional[str] = None) -> dict[str, Any]:
    """Acredita presupuesto COMPRADO (Stripe top-up): sube credits_usd → sube el cap.
    Usado por el webhook de Stripe tras un pago confirmado. Devuelve el meter actualizado."""
    _sin_metering_local("add_credit")
    amt = _d(usd)
    if amt <= 0:
        raise ValueError("credito_no_positivo")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO billing_quota (user_id, credits_usd, stripe_customer_id, updated_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (user_id)
            DO UPDATE SET credits_usd = billing_quota.credits_usd + EXCLUDED.credits_usd,
                          stripe_customer_id = COALESCE(EXCLUDED.stripe_customer_id, billing_quota.stripe_customer_id),
                          updated_at = now()
            """,
            (user_id, str(amt), stripe_customer_id),
        )
    conn.commit()
    return get_meter(conn, user_id)


# ── INGEST de COST-EVENTS (§4.6) — el corazón del consumo ────────────────────────

def _ledger_row_from_event(evt: dict) -> Optional[dict[str, Any]]:
    """Normaliza UN cost-event (§4.6) a la fila del ledger. Defensivo: un evento que no
    sea de costo se ignora (None). NO inventa usd (lo deja NULL si el evento lo trae null)."""
    if not isinstance(evt, dict) or evt.get("type") != "cost":
        return None
    kind = evt.get("kind")
    if kind not in ("model", "tool"):
        return None
    toks = evt.get("tokens") or {}
    try:
        pt = int(toks.get("prompt") or 0)
        ct = int(toks.get("completion") or 0)
        tt = int(toks.get("total") if toks.get("total") is not None else (pt + ct))
    except (TypeError, ValueError):
        pt = ct = tt = 0
    usd = evt.get("usd")  # puede ser None (modelo sin tarifa) o 0.0 (tool local) — se respeta
    return {
        "kind": kind,
        "model": evt.get("model"),
        "tool": evt.get("tool"),
        "server": evt.get("server"),
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "total_tokens": tt,
        "usd": (None if usd is None else str(_d(usd))),
        "tokens_measured": bool(evt.get("tokens_measured")),
        "price_source": evt.get("price_source"),
    }


def record_run_cost(
    conn,
    *,
    run_id: Optional[str],
    user_id: Optional[str],
    cost_events: Optional[list[dict]],
) -> dict[str, Any]:
    """
    INGESTA los cost-events de UN run al ledger + actualiza el metering. IDEMPOTENTE por
    run_id: re-ingestar el mismo run (retry, doble-emisión) NO duplica el cobro.

    - Recurso anónimo (user_id None): los eventos NO se facturan a nadie (no hay dueño);
      devolvemos {ingested:0, reason:'anonymous'} sin tocar el ledger del usuario.
    - usd NULL (modelo sin tarifa) se guarda como NULL y NO suma al gasto (no se inventa).
    - El user_id del run SCOPEA todo (AUTH §4.5): no mezclamos costo entre usuarios.

    Devuelve {ingested, usd_total, already, run_id}.
    EN EL CLIENTE no ingesta nada (ver `_sin_metering_local`).
    """
    if _es_cliente():
        return {"ingested": 0, "usd_total": 0.0, "already": False,
                "reason": "client_local", "run_id": str(run_id) if run_id else None}
    events = cost_events or []
    if not user_id:
        return {"ingested": 0, "usd_total": 0.0, "already": False,
                "reason": "anonymous", "run_id": run_id}

    # IDEMPOTENCIA: claim atómico del run. Si ya estaba ingestado → no re-cobramos.
    rid = str(run_id) if run_id else None
    if rid:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT events, usd_total FROM billing_runs_ingested WHERE run_id = %s",
                (rid,),
            )
            prev = cur.fetchone()
        if prev is not None:
            return {"ingested": int(prev[0] or 0), "usd_total": _money(prev[1]),
                    "already": True, "run_id": rid}

    rows = [r for r in (_ledger_row_from_event(e) for e in events) if r is not None]
    usd_total = sum((_d(r["usd"]) for r in rows if r["usd"] is not None), Decimal(0))

    with conn.cursor() as cur:
        for seq, r in enumerate(rows):
            cur.execute(
                """
                INSERT INTO billing_ledger
                  (user_id, run_id, seq, kind, model, tool, server,
                   prompt_tokens, completion_tokens, total_tokens,
                   usd, tokens_measured, price_source)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (user_id, rid, seq, r["kind"], r["model"], r["tool"], r["server"],
                 r["prompt_tokens"], r["completion_tokens"], r["total_tokens"],
                 r["usd"], r["tokens_measured"], r["price_source"]),
            )
        if rid:
            # marca de idempotencia (PK run_id). ON CONFLICT por si dos hilos corrieron a la par.
            cur.execute(
                """
                INSERT INTO billing_runs_ingested (run_id, user_id, events, usd_total)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (run_id) DO NOTHING
                """,
                (rid, user_id, len(rows), str(usd_total)),
            )
    conn.commit()
    return {"ingested": len(rows), "usd_total": _money(usd_total),
            "already": False, "run_id": rid}


__all__ = [
    "TIER_CAPS_USD", "DEFAULT_CAP_USD",
    "apply_billing_schema", "base_cap_for_tier",
    "get_cap", "spent_usd", "get_meter", "preflight",
    "set_self_limit", "add_credit", "record_run_cost",
]
