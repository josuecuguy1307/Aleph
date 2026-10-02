#!/usr/bin/env python3
"""verify_b1_http.py — Step 2·B1 · GATE ANIDADO + FRONTERA POR TIER, VIVO (executor real +
Postgres real + belt MCP real). Cerebro stubeado (FakeBrain, keyed por prompt — la delegación
necesita guión por-agente), igual que A2 sección C: qwen no propone money/delegación a pedido,
así que el CEREBRO se guiona; TODO lo demás es el path de PROD.

Prueba el round-trip que resuelve el 'callejón sin salida':
  A. Padre DELEGA → hijo golpea MONEY (place_order) → el held del hijo SUBE (hoist) y se PERSISTE
     en Postgres con la RECETA DEL HIJO + contexto de árbol → approve-by-HTTP EJECUTA la tool del
     hijo re-armando SU belt, EXACTAMENTE-UNA-VEZ (idempotente) → anti-IDOR (otro usuario no puede).
  B. Piso MONEY vivo en el árbol: durante el run, la orden del hijo NUNCA corrió (needs_ok).
  C. FRONTERA por tier VIVA: un usuario FREE que delega en 2 → el runtime serializa (max_parallel=1)
     con aviso honesto (delegation_serialized), resuelto del tier del usuario (no de la receta).
  D. Anti-grift del árbol: ningún nodo (padre ni hijos) degradó en silencio.

Correr:  cd product/backend && PYTHONPATH=<wt>/platform:<wt>/product/backend \\
         PUPPET_DB_ENC_KEY=$(cat <wt>/platform/db/secrets/enc.key) \\
         <venv>/bin/python <wt>/qa/verify_b1_http.py
(o desde el worktree con el symlink .venv; usa la MISMA DB que :8090.)
"""
import sys
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "platform"))
sys.path.insert(0, str(REPO / "platform" / "assembler" / "deleg_fixtures"))
sys.path.insert(0, str(REPO / "product" / "backend"))

import verify_delegation_real as V        # FakeBrain + SCRIPTS
import verify_b1_multiagente as _B1        # extiende V.SCRIPTS con PARENT_MONEY/CHILD_MONEY/... (al importar)
_ = _B1
from app.phase1 import executor as EX
from app.phase1 import repo as DB

_FIX = REPO / "platform" / "assembler" / "deleg_fixtures"
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"  {'✓' if cond else '✗'} {name}" + (f"\n      {detail}" if detail else ""))
    return bool(cond)


def _load(name):
    return json.loads((_FIX / name).read_text(encoding="utf-8"))


def _walk(rec):
    yield rec
    for s in (rec.get("sub_runs") or []):
        yield from _walk(s)


def main():
    asm = EX._asm()
    orig = asm._route_chat
    conn = None
    try:
        conn = DB.get_conn()
        uid = DB.get_or_create_user(conn, email="b1-deleg@puppet.local", tier="tecnico")["id"]
        uid_free = DB.get_or_create_user(conn, email="b1-free@puppet.local", tier="free")["id"]
        uid_otro = DB.get_or_create_user(conn, email="b1-otro@puppet.local", tier="free")["id"]

        # ── A · GATE ANIDADO: padre delega → hijo money → held HOISTEADO persistido con receta del hijo ──
        print("\n── A · GATE ANIDADO round-trip (persist con receta del HIJO → approve ejecuta su belt) ──")
        asm._route_chat = V.FakeBrain(V.SCRIPTS).route
        out = EX.run_puppet_e2e(_load("parent_money.json"), "PARENT_MONEY",
                                user_id=uid, conn=conn, approve=None)
        held = out.get("held_actions", []) or []
        po = next((h for h in held if h.get("tool") == "place_order"), None)
        check("A.1 held del HIJO SUBIÓ y se persistió con approval_id",
              bool(po and po.get("approval_id")), f"held={[h.get('tool') for h in held]}")
        check("A.2 held trae contexto de árbol (agent_path=[cajero_sub] + via_delegation)",
              bool(po) and po.get("agent_path") == ["cajero_sub"] and po.get("via_delegation") is True,
              f"path={po.get('agent_path') if po else None}, via={po.get('via_delegation') if po else None}")

        row = DB.get_held_action(conn, po["approval_id"]) if po else None
        stored = row.get("recipe") if row else None
        if isinstance(stored, str):
            stored = json.loads(stored)
        check("A.3 la receta PERSISTIDA es la del HIJO (cajero_sub), no la del padre",
              (stored or {}).get("meta", {}).get("name") == "cajero_sub",
              f"recipe.meta.name={(stored or {}).get('meta', {}).get('name')}")

        # durante el run, la orden del hijo NO corrió (piso money vivo, en el nivel del hijo)
        rec = out.get("record") or {}
        child = next((n for n in _walk(rec) if n is not rec
                      and any(g.get("tool") == "place_order" for g in (n.get("gate_decisions") or []))), {})
        cgd = [g for g in (child.get("gate_decisions") or []) if g.get("tool") == "place_order"]
        check("B.1 piso MONEY vivo: durante el run place_order del hijo quedó needs_ok (no ejecutó)",
              bool(cgd) and cgd[0].get("action") == "needs_ok",
              f"gate={cgd[0] if cgd else None}")

        # APPROVE → ejecuta la place_order del HIJO re-armando SU belt (deleg_server) exactamente-una-vez
        ap = EX.approve_held_action(po["approval_id"], ok=True, user_id=uid, conn=conn)
        check("A.4 approve EJECUTA la orden del HIJO (belt del hijo re-armado)",
              ap.get("executed") is True and "ORDEN COLOCADA" in str(ap.get("result", "")),
              f"executed={ap.get('executed')} result={str(ap.get('result'))[:60]}")
        ap2 = EX.approve_held_action(po["approval_id"], ok=True, user_id=uid, conn=conn)
        check("A.5 idempotente: re-approve → already_decided (exactamente-una-vez)",
              ap2.get("already_decided") is True, f"ap2={ap2}")

        # anti-IDOR: un held nuevo, otro usuario NO puede aprobarlo
        asm._route_chat = V.FakeBrain(V.SCRIPTS).route
        out_idor = EX.run_puppet_e2e(_load("parent_money.json"), "PARENT_MONEY",
                                     user_id=uid, conn=conn, approve=None)
        po_idor = next((h for h in (out_idor.get("held_actions") or []) if h.get("tool") == "place_order"), None)
        idor = EX.approve_held_action(po_idor["approval_id"], ok=True, user_id=uid_otro, conn=conn) if po_idor else {}
        check("A.6 anti-IDOR: otro usuario NO puede aprobar el held de un árbol ajeno",
              idor.get("executed") is not True and idor.get("authorized") is False,
              f"idor={idor}")

        # ── C · FRONTERA POR TIER VIVA: FREE que delega en 2 → serializado (del tier, no la receta) ──
        print("\n── C · FRONTERA por tier VIVA (usuario FREE → max_parallel=1 → serializa con aviso) ──")
        events = []
        asm._route_chat = V.FakeBrain(V.SCRIPTS).route
        out_free = EX.run_puppet_e2e(_load("parent_two.json"), "PARENT_TWO",
                                     user_id=uid_free, conn=conn, approve=None,
                                     on_event=lambda e: events.append(e))
        ser = [e for e in events if e.get("type") == "delegation_serialized"]
        subs = (out_free.get("record") or {}).get("sub_runs") or []
        both_ok = len(subs) == 2 and all(s.get("ok") for s in subs)
        check("C.1 FREE + 2 sub-agentes → evento delegation_serialized (max_parallel=1, resuelto del tier)",
              bool(ser) and ser[0].get("max_parallel") == 1 and ser[0].get("requested") == 2,
              f"serialized={ser[0] if ser else None}")
        check("C.2 serializado pero AMBOS sub-agentes corrieron (fila, no descarte)",
              both_ok, f"sub_runs={len(subs)} ok={[s.get('ok') for s in subs]}")

        # ── D · ANTI-GRIFT del árbol: ningún nodo degradó en silencio ──
        print("\n── D · ANTI-GRIFT del árbol (ningún nodo degrada silencioso) ──")
        nodes = list(_walk(rec)) + list(_walk(out_free.get("record") or {}))
        graft = [n.get("meta_name") or "root" for n in nodes if n.get("degraded") not in (None,)]
        check("D.1 todo nodo del árbol tiene degraded==null (padre + hijos, en ambos árboles)",
              not graft, f"nodos degradados={graft or 'ninguno'} sobre {len(nodes)} nodos")

    except Exception as exc:
        import traceback
        traceback.print_exc()
        check("harness corrió (setup vivo)", False, f"excepción: {type(exc).__name__}: {exc}")
    finally:
        asm._route_chat = orig
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass

    ok = sum(1 for _, p in results if p)
    total = len(results)
    print(f"\n  {ok}/{total} VERDE — " +
          ("B1 gate anidado + frontera por tier VIVO cierra" if ok == total
           else "ALGO NO CIERRA — revisar"))
    return 0 if ok == total and total > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
