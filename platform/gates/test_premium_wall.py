#!/usr/bin/env python3
"""test_premium_wall.py — MURALLA PREMIUM · el gotcha del vocabulario, probado en TODAS las direcciones.

No basta "un free fue rechazado". Estos tests prueban las 4 exigencias (persona usuaria, pre-merge):

  1. free (CUENTA) → invocación DIRECTA por API a una superficie premium → RECHAZO
     (no una UI que oculta: el que NIEGA es el backend — el gate/enforcer, sin modelo).
  2. free que EDITA recipe.tier="premium" → IGUAL rechazo: el server IGNORA recipe.tier
     (display, editable por el cliente) y resuelve el tier desde la CUENTA.
  3. HIJO de un free (delegación multiagente) → HEREDA el tier free del padre → su gate
     premium TAMBIÉN rechaza, AUNQUE la receta hija diga tier="premium".
  4. FAIL-CLOSED: un tier desconocido/ambiguo/mal escrito ("free" crudo en vez de "average",
     "", "premiumm", "admin", None, basura, incluso la palabra "premium" como tier de cuenta)
     → NIEGA premium, NUNCA lo abre. Si el gate abriera premium por un tier ambiguo = SEV
     crítico. Preferimos premium bloqueado-por-error (molesto) a premium abierto-por-error
     (te vacían el moat).

Determinista (cero red, cero modelo): la decisión del gate/enforcer es pura. La superficie
premium end-to-end vía executor+DB ya la cubre qa/verify_shared_memoria_b2.py (check 6); acá
atacamos el NÚCLEO de la decisión (build_enforced_gate + ApprovalGate + tier_gate + delegación).

Corre:  PYTHONPATH=<wt>/platform python3 platform/gates/test_premium_wall.py   (o pytest)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
for _p in (str(_REPO_ROOT / "platform"),
           str(_REPO_ROOT / "platform" / "gates"),
           str(_REPO_ROOT / "platform" / "assembler")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from gates import recipe_enforcer as RE           # build_enforced_gate, recipe_to_matrix
from gates import tier_gate as TG                 # gate_tier_for_account, require_feature, ...
from gates.approval_gate import ApprovalGate, GateDecision
import delegation as DELEG                        # run_children (threading del tier al hijo)
import recipe_assembler as RA                     # assemble_and_run (candado B2 del bus)
from belt_resolver import ResolvedAgent


# ── fixtures ─────────────────────────────────────────────────────────────────────
def _blocked_base_matrix() -> dict:
    """base_matrix con UN level premium (blocked) + regla que matchea una tool inocua
    (ni money ni send, para que el candado 'blocked' sea lo único que la frene)."""
    return {
        "levels": {
            "premium-solo": {"blocked": True, "requires_ok": False,
                             "copy": "Función Premium: mejorá tu plan para usarla."},
        },
        "rules": [
            {"id": "gate-compose-memory",
             "match": {"server": "memory", "tools": ["compose_team_memory"]},
             "level": "premium-solo"},
        ],
    }


def _recipe(tier=None) -> dict:
    r = {"meta": {"name": "muro-test"}, "belt": {"belt_ref": "x"}}
    if tier is not None:
        r["tier"] = tier          # el "recipe.tier" editable por el cliente (display-only)
    return r


def _is_blocked(gate, server="memory", tool="compose_team_memory") -> bool:
    return gate.evaluate(server, tool, {}).action == GateDecision.BLOCKED


# valores de tier de CUENTA legítimamente PAGOS (los únicos que deben abrir premium).
_PAID = ["basico", "tecnico", "Basico", " tecnico ", "TECNICO", "  basico"]
# valores AMBIGUOS/BASURA — NINGUNO debe abrir premium (fail-closed). Incluye la palabra
# 'premium' (NO es un tier de cuenta: las cuentas son free/basico/tecnico) y 'average' (el
# centinela INTERNO del gate — jamás debe llegar como tier de cuenta y desbloquear por atajo).
_BOGUS = ["free", "premium", "PREMIUM", "Premium", "premiumm", "prem", "", "   ",
          "basicoo", "tecnicoo", "básico", None, "average", "admin", "root", "gratis",
          "pro", "plus", "vip", "enterprise", "0", "1", "true", "null", "undefined",
          "free ", "tier", "🤑", "basico;premium", "premium--", "unknown"]


# ════════════════════════════════════════════════════════════════════════════════
# TEST 1 · free (CUENTA) → superficie premium por API directa → RECHAZO
# ════════════════════════════════════════════════════════════════════════════════
def test_1_free_account_rejected_at_premium_surface():
    # 1a · feature premium-BINARIA (bus de memoria compartida) — el gate unificado NIEGA.
    events = []
    rej = TG.require_feature("shared_memory_bus", "free", on_event=events.append)
    assert rej is not None, "free NO fue rechazado en shared_memory_bus (superficie premium abierta)"
    assert rej.get("tier_gated") is True and rej.get("min_tier") == "basico"
    assert "Premium" in rej.get("error", ""), "el rechazo no es honesto (no menciona Premium)"
    assert events and events[0]["type"] == "shared_memory_bus_denied", "no se emitió el evento de denegación"

    # 1b · superficie 'blocked' del ApprovalGate (vía build_enforced_gate autoritativo).
    gate = RE.build_enforced_gate(_recipe(), base_matrix=_blocked_base_matrix(), account_tier="free")
    assert gate.tier == "average", f"free debió mapear a 'average', mapeó a {gate.tier!r}"
    assert _is_blocked(gate), "free NO fue bloqueado en un level premium (gate abierto)"

    # 1c · CONTRASTE (el muro no es 'bloquear a todos'): un tier PAGO real SÍ pasa.
    for paid in ("basico", "tecnico"):
        assert TG.require_feature("shared_memory_bus", paid) is None, f"{paid} pago fue rechazado (muro roto al revés)"
        g2 = RE.build_enforced_gate(_recipe(), base_matrix=_blocked_base_matrix(), account_tier=paid)
        assert g2.tier == "premium" and not _is_blocked(g2), f"{paid} pago no desbloqueó el level premium"


# ════════════════════════════════════════════════════════════════════════════════
# TEST 2 · free que EDITA recipe.tier="premium" → IGUAL rechazo (server ignora recipe)
# ════════════════════════════════════════════════════════════════════════════════
def test_2_recipe_tier_edit_is_ignored():
    # El agujero DOCUMENTADO: sin override, recipe_to_matrix cae a recipe.tier="premium".
    raw = RE.recipe_to_matrix(_recipe(tier="premium"), base_matrix=_blocked_base_matrix())
    assert raw["tier"] == "premium", "pre-condición: recipe_to_matrix propaga recipe.tier (el agujero)"

    # El CIERRE: build_enforced_gate con el tier de la CUENTA (free) IMPONE 'average' — recipe
    # miente 'premium' pero el server lo ignora y BLOQUEA igual.
    gate = RE.build_enforced_gate(_recipe(tier="premium"),
                                  base_matrix=_blocked_base_matrix(), account_tier="free")
    assert gate.tier == "average", f"recipe.tier='premium' se coló ({gate.tier!r}) — SEV: moat abierto"
    assert _is_blocked(gate), "free+recipe.tier='premium' NO fue bloqueado (server confió en el cliente)"

    # BIDIRECCIONAL: la CUENTA decide, no la receta. Misma receta mentirosa, cuenta paga → abre.
    gate_paid = RE.build_enforced_gate(_recipe(tier="premium"),
                                       base_matrix=_blocked_base_matrix(), account_tier="tecnico")
    assert gate_paid.tier == "premium" and not _is_blocked(gate_paid), "la cuenta paga no mandó sobre recipe.tier"
    # Y una cuenta paga con recipe.tier='free' (receta que se auto-degrada) igual abre: manda la cuenta.
    gate_paid2 = RE.build_enforced_gate(_recipe(tier="free"),
                                        base_matrix=_blocked_base_matrix(), account_tier="tecnico")
    assert gate_paid2.tier == "premium", "recipe.tier='free' pisó a una cuenta paga (la receta no debe mandar)"


# ════════════════════════════════════════════════════════════════════════════════
# TEST 3 · HIJO de un free hereda free → su gate premium rechaza, diga lo que diga su receta
# ════════════════════════════════════════════════════════════════════════════════
def test_3_child_inherits_free_tier():
    # 3a · THREADING REAL: run_children → _run_one_child → runner(child). El hijo DEBE recibir
    # account_tier='free' del padre, AUNQUE su receta declare tier='premium'.
    captured = {}

    def spy_runner(recipe, task, **kw):
        captured["account_tier"] = kw.get("account_tier")
        captured["recipe_tier"] = recipe.get("tier")
        return {"ok": True, "answer": "", "tool_calls": [], "gate_decisions": [],
                "gate_enforced": True, "sub_runs": []}

    child_recipe = {"meta": {"name": "hijo-mentiroso"}, "tier": "premium",
                    "memory": {"shared": True}, "belt": {"belt_ref": "x"}}
    resolved = ResolvedAgent(agent_ref="ref-hijo",
                             recipe_path=_HERE / "no-existe-hijo.json",
                             recipe=child_recipe, slug="hijo")
    DELEG.run_children(
        [("hijo_fn", {"task": "hacé algo"}, "call_0")],
        {"hijo_fn": resolved},
        runner=spy_runner, depth=0, deadline_abs=time.monotonic() + 60,
        agent_stack=(), parent_workdir=None, turn=0, repo_root=_REPO_ROOT,
        byok_resolver=None, user_id=None, run_id=None, parent_model_cfg={},
        policy="inherit", child_ceiling=None, account_tier="free",
    )
    assert captured.get("account_tier") == "free", (
        f"el hijo NO heredó el tier free del padre (recibió {captured.get('account_tier')!r})")
    assert captured.get("recipe_tier") == "premium", "pre-condición: la receta hija declara 'premium' (miente)"

    # 3b · el gate que el hijo CONSTRUIRÍA con el tier heredado (free) BLOQUEA su level premium,
    # aunque su receta diga 'premium'. (Es build_enforced_gate con el account_tier heredado.)
    child_gate = RE.build_enforced_gate(child_recipe, base_matrix=_blocked_base_matrix(),
                                        account_tier="free")
    assert child_gate.tier == "average", f"el gate del hijo abrió por recipe.tier ({child_gate.tier!r})"
    assert _is_blocked(child_gate), "el hijo de un free desbloqueó premium con su receta mentirosa"


# ════════════════════════════════════════════════════════════════════════════════
# TEST 4 · FAIL-CLOSED: tier ambiguo/desconocido/mal escrito → NIEGA premium, nunca lo abre
# ════════════════════════════════════════════════════════════════════════════════
def test_4_failclosed_unknown_tier_never_opens():
    # 4a · el traductor de vocabulario: SOLO los pagos conocidos → 'premium'; TODO lo demás → 'average'.
    for paid in _PAID:
        assert TG.gate_tier_for_account(paid) == "premium", f"{paid!r} pago no mapeó a premium"
    for bad in _BOGUS:
        got = TG.gate_tier_for_account(bad)
        assert got == "average", f"SEV: gate_tier_for_account({bad!r}) = {got!r} — abrió premium por tier ambiguo"

    # 4b · build_enforced_gate: cualquier account_tier basura → gate 'average' → level premium BLOQUEA.
    for bad in _BOGUS:
        g = RE.build_enforced_gate(_recipe(tier="premium"), base_matrix=_blocked_base_matrix(),
                                   account_tier=bad)
        assert g.tier == "average", f"SEV: account_tier={bad!r} produjo gate.tier={g.tier!r}"
        assert _is_blocked(g), f"SEV: account_tier={bad!r} desbloqueó un level premium"

    # 4c · EL GUARD MÁS PROFUNDO — ApprovalGate directo (vocabulario INTERNO del gate, donde
    # 'premium' es el centinela de desbloqueo): el ÚNICO string que abre un 'blocked' es EXACTAMENTE
    # 'premium'. Todo lo demás — incl. 'Premium'/'PREMIUM'/' premium '/'premium '/'free'/'average'/
    # None — BLOQUEA. Si CUALQUIER otro valor abriera, es fail-OPEN (SEV crítico). (_BOGUS ya incluye
    # 'premium' + sus near-misses; usamos un set para no depender del conteo.)
    bm = _blocked_base_matrix()
    matrix = {"levels": bm["levels"], "rules": bm["rules"]}
    unlockers = set()
    for t in _BOGUS + _PAID + [" premium ", "premium ", "\tpremium"]:
        g = ApprovalGate({**matrix, "tier": t})
        if not _is_blocked(g):
            unlockers.add(t)
    assert unlockers == {"premium"}, (
        f"SEV: un 'blocked' se abrió con tier(s) {sorted(map(repr, unlockers))} — SOLO 'premium' exacto debe abrir (fail-closed)")

    # 4d · el segundo candado del gate (tier_block/when_no_sandbox: correr código SIN caja) —
    # mismo fail-closed: sólo 'premium' exacto puede; desconocido/mal escrito NIEGA.
    tb_matrix = {
        "levels": {"auto-ejecuta": {"requires_ok": False}},
        "rules": [{"id": "exec-code", "match": {"server": "exec", "tools": ["run_code"]},
                   "level": "auto-ejecuta",
                   "tier_block": {"when_no_sandbox": True, "reason": "código sin caja"}}],
    }
    opened = set()
    for t in _BOGUS + _PAID:
        g = ApprovalGate({**tb_matrix, "tier": t}, sandbox_available=False)
        if g.evaluate("exec", "run_code", {}).action != GateDecision.BLOCKED:
            opened.add(t)
    assert opened == {"premium"}, (
        f"SEV: correr código sin caja se permitió con tier(s) {sorted(map(repr, opened))} — sólo 'premium' exacto (fail-closed)")

    # 4e · require_feature fail-closed: toda feature registrada niega a cualquier tier no-pago.
    for feat in TG.PREMIUM_FEATURES:
        for bad in ("free", "premium", "", None, "admin", "premiumm"):
            assert TG.require_feature(feat, bad) is not None, (
                f"SEV: require_feature({feat!r}, {bad!r}) devolvió None — abrió premium por tier ambiguo")


# ════════════════════════════════════════════════════════════════════════════════
# TEST 5 · FAIL-CLOSED ante capa de seguridad rota (hallazgo del review adversarial)
#   Un ImportError de la capa de gates dejaba _caps_ceiling=None, que se leía como PERMITIR en
#   las superficies por-clamp (bus B2, techos de loop, paralelismo) para free/anónimo. Cierre:
#   (a) el executor cae al piso FREE hardcodeado (== TIER_RUNTIME_CAPS['free']); (b) el candado
#   B2 NIEGA a un run AUTENTICADO que llegue sin tier y sin caps (no la afición CLI 'permitir').
# ════════════════════════════════════════════════════════════════════════════════
def test_5_failclosed_broken_security_layer():
    # 5a · CONTRATO del piso de fallback: el hardcode del executor DEBE seguir a free-caps. Si
    # alguien cambia TIER_RUNTIME_CAPS['free'], este pin obliga a actualizar el fallback del executor.
    free = RE.TIER_RUNTIME_CAPS["free"]
    assert free == {"max_turns": 8, "max_tool_calls": 40, "max_parallel": 1, "shared_bus": False}, (
        f"free-caps cambió a {free!r} — actualizá el fallback hardcodeado del executor (except ImportError)")
    assert free["shared_bus"] is False and free["max_parallel"] == 1, "el piso free debe negar bus y serializar"

    # 5b · el candado B2 NIEGA a un run AUTENTICADO (user_id) que llegó SIN account_tier y SIN caps
    # (estado de capa-de-seguridad-rota). Hermético: el candado retorna ANTES de bootear MCP o llamar
    # al modelo. Un belt keyless real (deleg) para que el belt_ref RESUELVA y se alcance el candado.
    recipe = {
        "schema_version": "v1",
        "meta": {"name": "muro-bus-auth"},
        "model": {"primary": "stub", "base_url": "stub://local", "temperature": 0,
                  "max_tokens": 64, "max_turns": 2},
        "belt": {"belt_ref": "platform/assembler/deleg_fixtures/belt-deleg.mcp.json",
                 "agent_refs": ["platform/assembler/deleg_fixtures/child_research.json"],
                 "tool_filters": {"deleg": ["read_data"]}},
        "memory": {"shared": True, "ref": "product/belts/memoria-compartida.mcp.json"},
        "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
    }
    rec = RA.assemble_and_run(recipe, "hola", repo_root=_REPO_ROOT,
                              user_id="auth-user-xyz",       # AUTENTICADO (prod)
                              account_tier=None,              # sin tier (capa rota)
                              _caps_ceiling=None,             # sin caps (capa rota)
                              deadline_s=20.0)
    assert "Premium" in (rec.get("error") or ""), (
        f"un run AUTENTICADO sin tier/caps NO fue negado en el bus (fail-OPEN): error={rec.get('error')!r}")
    assert (rec.get("upsell") or {}).get("feature") == "shared_memory_bus", "el rechazo no trae el upsell del bus"

    # 5c · CONTRASTE back-compat: el MISMO estado pero SIN user_id (CLI local, trusted) NO se niega
    # por el candado (la afición 'ambos ausentes = permitir' sigue viva para el CLI single-user).
    # No corremos el run entero (no hay modelo real); sólo verificamos que el candado NO produjo el
    # rechazo del bus — el _b2_deny quedó False y siguió de largo (cualquier error posterior es de
    # boot/modelo stub, NO el candado premium).
    rec_cli = RA.assemble_and_run(recipe, "hola", repo_root=_REPO_ROOT,
                                  user_id=None,               # CLI local (sin cliente no confiable)
                                  account_tier=None, _caps_ceiling=None, deadline_s=20.0)
    err_cli = rec_cli.get("error") or ""
    assert "Premium" not in err_cli, (
        f"el candado premium se disparó en el CLI local (rompió back-compat): {err_cli!r}")
    assert (rec_cli.get("upsell") or {}).get("feature") != "shared_memory_bus", "CLI recibió upsell de bus (no debía)"


def test_6_founder_is_a_BUILD_not_a_tier():
    """[Casa 2 · Fase 4 · 4.3] founder = BUILD (seguridad por AUSENCIA), NUNCA un tier. Aunque
    alguien pegue account_tier='founder', NO desbloquea: el gate sólo abre con 'premium' EXACTO,
    y las capacidades founder viven en un ARTEFACTO aparte (ALEPH_BUILD=founder, ver build_id.py),
    no en un string de tier viajable/flippable. Fija el principio founder=build en el gate."""
    bm = _blocked_base_matrix()
    matrix = {"levels": bm["levels"], "rules": bm["rules"]}
    for t in ("founder", "Founder", "FOUNDER", " founder ", "founder "):
        g = ApprovalGate({**matrix, "tier": t})
        assert _is_blocked(g), f"SEV: account_tier={t!r} desbloqueó — founder NO es un tier"
    assert TG.gate_tier_for_account("founder") == "average", "founder no mapea a premium"
    for feat in TG.PREMIUM_FEATURES:
        assert TG.require_feature(feat, "founder") is not None, f"SEV: founder abrió {feat!r}"


# ── runner standalone con veredicto (además de pytest) ───────────────────────────
def _main() -> int:
    tests = [
        ("1 · free → superficie premium por API → RECHAZO", test_1_free_account_rejected_at_premium_surface),
        ("2 · free+recipe.tier='premium' → IGUAL rechazo (server ignora recipe)", test_2_recipe_tier_edit_is_ignored),
        ("3 · HIJO de free hereda free → su gate premium RECHAZA", test_3_child_inherits_free_tier),
        ("4 · FAIL-CLOSED: tier ambiguo/basura → NIEGA premium, nunca abre", test_4_failclosed_unknown_tier_never_opens),
        ("5 · FAIL-CLOSED ante capa de seguridad rota (ImportError → free-caps)", test_5_failclosed_broken_security_layer),
        ("6 · founder = BUILD, NUNCA tier → account_tier='founder' NO abre", test_6_founder_is_a_BUILD_not_a_tier),
    ]
    print("═" * 80)
    print("  MURALLA PREMIUM · el gotcha del vocabulario en las 4 direcciones (fail-closed)")
    print("═" * 80)
    n_ok = 0
    for label, fn in tests:
        try:
            fn()
            print(f"  ✓ CIERRA  {label}")
            n_ok += 1
        except AssertionError as e:
            print(f"  ✗ ABIERTO {label}\n      → {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ ERROR   {label}\n      → {type(e).__name__}: {e}")
    print("─" * 80)
    verdict = "TODO VERDE — el muro es fail-closed en las 4 direcciones" if n_ok == len(tests) \
        else "MURO CON FUGA — revisar (posible SEV crítico)"
    print(f"  {n_ok}/{len(tests)} CIERRAN · VEREDICTO: {verdict}")
    print("═" * 80)
    return 0 if n_ok == len(tests) else 1


if __name__ == "__main__":
    raise SystemExit(_main())
