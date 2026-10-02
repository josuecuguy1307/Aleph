#!/usr/bin/env python3
"""
verify_frontera_d4.py — la EVIDENCIA de D4 (muro-frontera VIVO con eventos REALES del motor).

Prueba el ALMA anti-grift de D4: el recinto del hijo se enciende con los eventos ESTRUCTURALES que
emite el MOTOR REAL (recipe_assembler.assemble_and_run con el branch de delegación cableado), NO con
una animación in-page sin run detrás (§7e = grift). Reusa EXACTAMENTE el patrón de
verify_delegation_real.py: motor REAL + cerebro FakeBrain (monkeypatch de _route_chat). Lo ÚNICO
guionado es el token-output del LLM; los eventos que encienden el muro salen del motor genuino.

Corre TRES delegaciones padre→hijo reales y captura su on_event:
  • CLEAN    — hijo SOLO-LECTURA (read_data) → termina LIMPIO: status=ok, held=0, RESULTADO cruzó.
               model_final='fake-brain', degraded=None (honesto: NO es opus, es fake).
  • HELD     — hijo que escribe (write_note) → el gate lo RETIENE (needs_ok) y el hijo NO hereda el OK
               del padre (RIEL#1) → status=gate, held=1 ("espera tu OK"). Estado held REAL, no simulado.
  • DEGRADED — el cerebro cae a tier 'fallback' → el motor computa degraded=True y emite el notice/cost
               degradado GENUINO. model_final='qwen-2.5-oss' (honesto: OSS de red de seguridad, NO opus).

Asserta sobre los eventos REALES + vuelca los tres streams a frontera_d4_events.json → el harness
Playwright (verify_fractal_frontera.mjs) los REPLAYEA en el front y prueba que el muro se enciende.

Uso:  python3 verify_frontera_d4.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ASM_DIR = _HERE.parent
_REPO_ROOT = _HERE.parents[2]
for _p in (str(_ASM_DIR), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import recipe_assembler as RA                                    # noqa: E402
# Reusamos el patrón PROBADO (motor real + FakeBrain) tal cual — cero re-invención.
from verify_delegation_real import FakeBrain, SCRIPTS, _Patched, _load, _wd  # noqa: E402

#: El fixture COMMITEADO que `verify_fractal_frontera.mjs` replaya. Lo lee el consumidor;
#: no lo escribe esta vara salvo que se lo pidan.
_FIXTURE = _REPO_ROOT / "product" / "app" / "design" / "cuarto" / "frontera_d4_events.json"

# ══ [H2] LA VARA NO ESCRIBE EN EL ÁRBOL ════════════════════════════════════════════════
# MEDIDO (2026-08-08, sobre main @ 1242dba): correr esta vara dejaba `frontera_d4_events.json`
# modificado. El diff era UNA línea — `"wall_s": 0.00068…` → `0.00056…`, el reloj de la
# corrida. Nada de contenido: puro ruido no determinista que ensuciaba el `git status` de
# todos los worktrees y se revirtió a mano cuatro veces en una sesión.
#
# (Se revisó además la sospecha de que el fixture guardara un path absoluto sin scrubbear:
#  `grep -oE '/(Users|private|var|tmp)…'` sobre el archivo commiteado da **cero**. Esa parte
#  no estaba viva; no hay nada que regenerar por el scrub de la obra 3.)
#
# El destino por defecto pasa a ser un temporal. Regenerar el fixture es ahora un acto
# EXPLÍCITO —`--regenerar-fixture`— porque cambiar lo que el front replaya es una decisión,
# no un efecto secundario de haber corrido una vara.
_REGENERAR = "--regenerar-fixture" in sys.argv
_EVENTS_OUT = _FIXTURE if _REGENERAR else \
    Path(tempfile.gettempdir()) / f"frontera_d4_events-{os.getpid()}.json"

# Guiones D4: el hijo SOLO-LECTURA (read_data → final) no toca el mundo → termina sin held.
SCRIPTS_D4 = {
    **SCRIPTS,
    "PARENT_D4": [
        {"tool_calls": [("readonly_sub", {"task": "CHILD_D4"})]},
        {"final": "El padre integró el resultado del sub-agente solo-lectura."},
    ],
    "CHILD_D4": [
        {"tool_calls": [("read_data", {"q": "dato X"})]},
        {"final": "RESULTADO-DEL-HIJO: el dato X = 42"},
    ],
}

fails: list[str] = []


def ok(cond, label, extra=""):
    print(f"{'✓' if cond else '✗'} {label}" + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(label)


class DegradedBrain(FakeBrain):
    """Igual que FakeBrain pero el cerebro CAE a un tier de red de seguridad ('fallback'): reporta en
    el route_log un intento primary FALLIDO + una respuesta 'fallback' de un OSS. El motor computa
    degraded=True de VERDAD (_emit_model_cost_event lee route[-1].tier) y emite el notice/cost degradado
    GENUINO. model_final honesto = 'qwen-2.5-oss' (NO se afirma opus jamás)."""

    FALLBACK_MODEL = "qwen-2.5-oss"

    def route(self, messages, tools, *, base_url, primary, fallback, api_key,
              max_tokens, temperature, route_log, on_tier_error=None, **_kw):  # (BYO-CLI D4 + annex cli_model: absorbe kwargs aditivos de _route_chat)
        key = self._first_user(messages)
        idx = sum(1 for m in messages if m.get("role") == "assistant")
        with self.lock:
            self.calls.append({"key": key, "primary": primary, "base_url": base_url})
            self.tool_msgs_seen[key] = [str(m.get("content", ""))
                                        for m in messages if m.get("role") == "tool"]
        route_log.append({"model": primary, "tier": "primary", "ok": False, "error": "simulated primary outage"})
        route_log.append({"model": self.FALLBACK_MODEL, "tier": "fallback", "ok": True})
        if not tools:
            return self._final("[degraded-brain: cierre]"), self.FALLBACK_MODEL
        script = self.scripts.get(key)
        if not script or idx >= len(script):
            return self._final(f"[degraded-brain: sin guión para {key!r} @idx{idx}]"), self.FALLBACK_MODEL
        turn = script[idx]
        if "final" in turn:
            return self._final(turn["final"]), self.FALLBACK_MODEL
        return self._tool_calls(turn["tool_calls"]), self.FALLBACK_MODEL


def _drive(brain, recipe_name, prompt, tag, approve=None):
    """Corre una receta padre con `brain`, capturando el on_event REAL. (rec, eventos)."""
    events: list = []
    with _Patched(brain):
        rec = RA.assemble_and_run(
            _load(recipe_name), prompt,
            repo_root=_REPO_ROOT, deadline_s=180.0, workdir=_wd(f"frontera-{tag}"),
            approve=approve, on_event=lambda e: events.append(e), run_id=f"frontera-{tag}")
    return rec, events


def _ev(events, typ):
    return [e for e in events if e.get("type") == typ]


def main():
    print("═" * 78)
    print("  D4 · MURO-FRONTERA VIVO — eventos ESTRUCTURALES REALES del motor (anti-grift)")
    print("═" * 78)

    # ── (1) CLEAN — hijo solo-lectura → termina LIMPIO (running → off + crossed) ─────────────────
    print("\n── RUN CLEAN (hijo solo-lectura, FakeBrain tier=primary) ────────────────────────────")
    rec, ev_clean = _drive(FakeBrain(SCRIPTS_D4), "parent_d4.json", "PARENT_D4", "clean")
    started = _ev(ev_clean, "sub_agent_started")
    finished = _ev(ev_clean, "sub_agent_finished")
    child = (rec.get("sub_runs") or [{}])[0]
    deleg = [t for t in rec.get("tool_calls", []) if t.get("delegated")]
    print(f"  padre ok={rec.get('ok')}  model_final={rec.get('model_final')!r}  degraded={rec.get('degraded')!r}")
    print(f"  started={len(started)} slug={started[0].get('slug') if started else None!r} depth={started[0].get('depth') if started else None}")
    print(f"  finished={len(finished)} status={finished[0].get('status') if finished else None!r} held={finished[0].get('held') if finished else None}")

    ok(len(started) == 1 and started[0].get("slug") == "child_readonly_d4" and started[0].get("depth") == 1,
       "REAL · sub_agent_started emitido por el MOTOR (slug=child_readonly_d4, depth=1) → enciende el recinto",
       json.dumps({"slug": started[0].get("slug"), "depth": started[0].get("depth")}) if started else "—")
    ok(len(finished) == 1 and finished[0].get("slug") == "child_readonly_d4"
       and finished[0].get("status") == "ok" and (finished[0].get("held") or 0) == 0,
       "REAL · sub_agent_finished status=ok held=0 (hijo limpio) → el recinto se apaga",
       json.dumps({"status": finished[0].get("status"), "held": finished[0].get("held")}) if finished else "—")

    child_tcs = child.get("tool_calls") or []
    ok(len(child_tcs) >= 1 and any(t.get("tool") == "read_data" for t in child_tcs),
       "REAL · el hijo ejecutó tool_calls>0 REALES (read_data) — viven en el LOG sub_runs",
       f"n={len(child_tcs)} tools={[t.get('tool') for t in child_tcs]}")

    try:
        crossed_ev = json.loads(finished[0].get("result") or "{}") if finished else {}
    except Exception:
        crossed_ev = {}
    bridge_keys_ok = set(crossed_ev.keys()) <= {"sub_agente", "ok", "resultado", "truncado", "error"} \
        and "sub_agente" in crossed_ev and "resultado" in crossed_ev
    result_crossed = "RESULTADO-DEL-HIJO" in (crossed_ev.get("resultado") or "")
    parent_consumed = bool(deleg) and "RESULTADO-DEL-HIJO" in (deleg[0].get("result") or "")
    ok(bridge_keys_ok and result_crossed and parent_consumed,
       "REAL · el RESULTADO bridged CRUZÓ al padre (sub_agent_finished.result = {sub_agente,ok,resultado,...})",
       json.dumps({"keys": sorted(crossed_ev.keys()), "consumido_por_padre": parent_consumed}, ensure_ascii=False))

    # RIEL#5 · los pasos INTERNOS del hijo (el output crudo de read_data) NO cruzaron al CEREBRO del padre.
    # El bridge (RESULTADO-DEL-HIJO) SÍ cruza — es el resultado, no el interior. Marcadores de FUGA =
    # el output crudo de la tool del hijo ("datos[dato X]"), jamás el resultado bridged.
    brain_obs = FakeBrain(SCRIPTS_D4)
    _drive(brain_obs, "parent_d4.json", "PARENT_D4", "clean-obs")
    seen = brain_obs.tool_msgs_seen.get("PARENT_D4", [])
    leaked = any("datos[dato X]" in s or "NOTA-DEL-HIJO" in s for s in seen)
    ok(not leaked and len(child_tcs) >= 1,
       "REAL · RIEL#5 · el INTERIOR del hijo (output crudo de sus tools) NO cruzó al cerebro del padre (log ≠ contexto)",
       f"cerebro del padre vio role:tool={seen} → filtró_interior={leaked} (debe ser False)")

    mf = str(rec.get("model_final"))
    ok("fake" in mf.lower() and rec.get("degraded") in (None, False),
       "ANTI-GRIFT · CLEAN HONESTO: model_final='fake-brain' (NO opus) + degraded ausente",
       json.dumps({"model_final": rec.get("model_final"), "degraded": rec.get("degraded")}))
    final_clean = _ev(ev_clean, "final")
    ok(bool(final_clean) and not final_clean[-1].get("degraded"),
       "ANTI-GRIFT · el evento final del run CLEAN trae degraded falsy (limpio)",
       json.dumps({"final.degraded": final_clean[-1].get("degraded") if final_clean else "—"}))

    # ── (2) HELD — el hijo escribe → gate needs_ok, NO hereda el OK del padre (RIEL#1) → held ────
    print("\n── RUN HELD (hijo escribe → gate lo retiene; RIEL#1: no hereda el OK del padre) ──────")
    rec_h, ev_held = _drive(FakeBrain(SCRIPTS), "parent.json", "PARENT_COORD", "held",
                            approve=lambda *a: True)   # el PADRE aprueba TODO; el hijo NO lo hereda
    finished_h = _ev(ev_held, "sub_agent_finished")
    child_h = (rec_h.get("sub_runs") or [{}])[0]
    gd = [g for g in child_h.get("gate_decisions", []) if g.get("action") == "needs_ok"]
    print(f"  finished status={finished_h[0].get('status') if finished_h else None!r} held={finished_h[0].get('held') if finished_h else None}"
          f"  gate_needs_ok={[g.get('tool') for g in gd]}")
    ok(len(finished_h) == 1 and finished_h[0].get("status") == "gate" and (finished_h[0].get("held") or 0) >= 1,
       "REAL · sub_agent_finished status='gate' held>0 (el hijo dejó una acción retenida) → recinto 'espera tu OK'",
       json.dumps({"status": finished_h[0].get("status"), "held": finished_h[0].get("held")}) if finished_h else "—")
    note_written = (Path(child_h.get("workdir", "/nope")) / "note.txt").exists()
    ok(bool(gd) and not note_written,
       "REAL · el gate del hijo REALMENTE retuvo (write_note→needs_ok, note.txt NO escrita), pese al approve=True del padre (RIEL#1)",
       json.dumps({"held_tools": [g.get('tool') for g in gd], "note_escrita": note_written}))

    # ── (3) DEGRADED — el cerebro cae a fallback → el motor computa degraded REAL ────────────────
    print("\n── RUN DEGRADED (cerebro cae a tier=fallback) ──────────────────────────────────────")
    rec_d, ev_deg = _drive(DegradedBrain(SCRIPTS_D4), "parent_d4.json", "PARENT_D4", "degraded")
    notice_deg = [e for e in ev_deg if e.get("type") == "notice" and e.get("kind") == "degraded"]
    cost_deg = [e for e in ev_deg if e.get("type") == "cost" and e.get("degraded")]
    final_deg = _ev(ev_deg, "final")
    started_d = _ev(ev_deg, "sub_agent_started")
    finished_d = _ev(ev_deg, "sub_agent_finished")
    print(f"  padre ok={rec_d.get('ok')}  model_final={rec_d.get('model_final')!r}  degraded={rec_d.get('degraded')!r}")
    print(f"  notice(degraded)={len(notice_deg)}  cost(degraded)={len(cost_deg)}  final.degraded={final_deg[-1].get('degraded') if final_deg else None!r}")

    ok(len(notice_deg) >= 1 or len(cost_deg) >= 1,
       "ANTI-GRIFT · el MOTOR emitió la degradación REAL (notice/cost degraded computado por _emit_model_cost_event)",
       json.dumps({"notice": len(notice_deg), "cost": len(cost_deg)}))
    ok(bool(final_deg) and bool(final_deg[-1].get("degraded")),
       "ANTI-GRIFT · el evento final del run DEGRADED trae degraded POBLADO (no es el cerebro real)",
       json.dumps(final_deg[-1].get("degraded")) if final_deg else "—")
    mfd = str(rec_d.get("model_final"))
    ok("opus" not in mfd.lower() and ("qwen" in mfd.lower() or "oss" in mfd.lower()),
       "ANTI-GRIFT · DEGRADED HONESTO: model_final es el OSS de fallback (NO opus)",
       json.dumps({"model_final": rec_d.get("model_final")}))
    ok(len(started_d) == 1 and len(finished_d) == 1,
       "REAL · con cerebro degradado la delegación IGUAL emite sub_agent_started/finished (árbol estructural)",
       json.dumps({"started": len(started_d), "finished": len(finished_d)}))

    ok((rec.get("degraded") in (None, False)) and bool(rec_d.get("degraded")),
       "ANTI-GRIFT · DISCRIMINACIÓN: degraded FLIPEA null(clean) → poblado(degraded) (keyeado en el CAMPO, no en el modelo)",
       json.dumps({"clean": rec.get("degraded"), "degraded": bool(rec_d.get("degraded"))}))

    # ── DUMP de los tres streams REALES para el replay del front ─────────────────────────────────
    payload = {
        "meta": {
            "source": "verify_frontera_d4.py — FakeBrain-over-real-motor (recipe_assembler.assemble_and_run)",
            "honest": "REAL structural engine events; only LLM token-output scripted; model_final NEVER claimed as opus",
            "clean_slug": "child_readonly_d4", "held_slug": "child_research",
            "clean_model_final": rec.get("model_final"),
            "degraded_model_final": rec_d.get("model_final"),
        },
        "clean": ev_clean, "held": ev_held, "degraded": ev_deg,
    }
    _EVENTS_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    _donde = _EVENTS_OUT.relative_to(_REPO_ROOT) if _REGENERAR else _EVENTS_OUT
    print(f"\n  ▸ eventos REALES volcados a {_donde}  "
          f"(clean={len(ev_clean)}, held={len(ev_held)}, degraded={len(ev_deg)})"
          + ("  [FIXTURE DEL ÁRBOL REGENERADO]" if _REGENERAR else
             "  [temporal — el fixture commiteado no se toca; usá --regenerar-fixture]"))
    ok(_EVENTS_OUT.exists() and len(ev_clean) and len(ev_held) and len(ev_deg),
       "DUMP · frontera_d4_events.json escrito con los TRES streams de eventos REALES (para el replay del front)")

    # [H3] La regla del cierre: la ÚLTIMA línea es el veredicto. La barra decorativa va
    # ANTES, no después — un `tail -1` que lee `═══` no sabe si el merge puede pasar.
    print("\n" + "═" * 78)
    if fails:
        for f in fails:
            print(f"   - {f}")
        print(f"  RESULTADO: ROJO ({len(fails)})")
    else:
        print("  RESULTADO: VERDE — el muro-frontera se enciende con eventos REALES del motor; "
              "anti-grift honesto (fake-brain≠opus; degraded FLIPEA); held real; RIEL#5 intacto")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
