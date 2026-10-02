#!/usr/bin/env python3
"""
selftest_loop_internal.py — GATE VERDE del LOOP INTERNO (§3) · verify-from-environment.

Corre el loop REAL contra TMDB vivo y asierta la TESIS, contra el entorno, sin mocks:

  1. desde URL+key CRUDAS, el loop converge a N≥2 tools de lectura VERIFICADAS;
  2. cada tool verificada fue REALMENTE llamada contra TMDB y respondió (2xx + cuerpo
     con forma · sample_response presente);
  3. ≥1 candidata ALUCINADA fue dropeada vía la tabla §5 (verificable en el log:
     una FailedTool con su FailureClass por un síntoma de llamada real);
  4. el MCP emitido es REAL y forjado DESDE CERO (los 3 artefactos existen en disco,
     en un dir recién creado — no salió de ningún config previo) y NO contiene el
     secreto en claro;
  5. budget cap respetado (gasto ≤ topes) Y degraded:true aparece si se fuerza la
     caída del cerebro (sub-corrida con el shim apuntado a un puerto muerto).

Uso:
    TMDB_API_KEY=xxxxxxxx PUPPET_BRAIN_SHIM=1 \\
      product/backend/.venv/bin/python platform/inspection/loop/selftest_loop_internal.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402
from inspection.loop.budget import Budget  # noqa: E402
from inspection.loop.engine import TMDB_BASE, run_internal_loop  # noqa: E402
from inspection.loop.live_http import LiveHTTP  # noqa: E402
from inspection.loop.validator import LiveValidator  # noqa: E402

_FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "✓" if cond else "✗"
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        _FAILS.append(name)


def _green_run(key: str, base: str, root: Path):
    principal = C.Principal(anon_id=f"gate-{uuid.uuid4().hex[:12]}")
    # techo de tokens alto: el shim (proxy Claude Code) inyecta ~12k tok de contexto por
    # llamada; medimos el cap por rounds/calls/tiempo. El cap igual se audita (≤ techo).
    budget = Budget(max_rounds=6, max_live_calls=60, max_synth_tokens=300_000, max_seconds=300)
    res = run_internal_loop(base, key, principal, slug="tmdb-gate",
                            budget=budget, cred_root=root)
    return principal, res


def gate_converges_verified(res) -> None:
    print("\n[1] converge a N tools de lectura VERIFICADAS")
    check("el loop no erroró en la puerta", not res.error, res.error or "ok")
    check("convergió a N≥2 tools verificadas", len(res.verified) >= 2,
          f"{len(res.verified)}: {res.verified_names}")
    check("todas las verificadas son GET (read-only §7)",
          all(v.candidate.kind is C.ToolKind.READ and v.candidate.method == "GET"
              for v in res.verified))


def gate_really_called(res) -> None:
    print("\n[2] cada verificada fue REALMENTE llamada y respondió")
    check("toda verificada trae verified_by=200-OK+schema-match",
          all(v.verified_by == "200-OK+schema-match" for v in res.verified))
    check("toda verificada trae sample_response real (cuerpo vivo)",
          all(bool(v.sample_response) and len(v.sample_response) > 2 for v in res.verified),
          f"{[len(v.sample_response or '') for v in res.verified]}")


# endpoints PLAUSIBLES que NO existen en TMDB (verificado: 404 status_code 34, no 401).
# Son la forma de una alucinación típica: suenan reales, no existen. NO son tools fingidas
# que pasan — son candidatas que el candado debe RECHAZAR contra el target vivo.
_HALLUCINATED = [
    ("get_movie_box_office", "/movie/{movie_id}/box_office", {"movie_id": 550}),
    ("get_movie_awards", "/movie/{movie_id}/awards", {"movie_id": 550}),
    ("get_person_awards", "/person/{person_id}/awards", {"person_id": 287}),
]


def _lock_self_test(key: str, base: str):
    """Determinístico: el Validador REAL (Capa 4) contra endpoints inexistentes vivos.
    Prueba que el candado §5 dispara contra el entorno SIEMPRE — la candidata 404ea de
    verdad y NO entra a la forja. (No finge un PASS; verifica un RECHAZO real.)"""
    http = LiveHTTP(secret=key, auth_param="api_key")
    validator = LiveValidator(http)
    session = C.Session(form=C.AuthForm.TOKEN, base_url=base)
    cands = tuple(
        C.CandidateTool(name=name, kind=C.ToolKind.READ, endpoint=ep, method="GET",
                        input_schema={"type": "object", "x-sample-call": {"path_params": pp}},
                        description="alucinación plausible para sondear el candado")
        for name, ep, pp in _HALLUCINATED
    )
    return validator.validate(session, cands)


def gate_dropped_hallucination(opus_res, key: str, base: str, root: Path) -> None:
    print("\n[3] el candado §5 dropea alucinaciones en vivo (protege la forja)")

    # ── 3a · LOCK SELF-TEST determinístico (el bloqueante) ─────────────────────
    print("    · lock self-test: el Validador real contra endpoints inexistentes (404 vivo)…")
    v = _lock_self_test(key, base)
    dropped = {f.candidate.endpoint: f for f in v.failed}
    all_dropped = all(ep in dropped for _, ep, _ in _HALLUCINATED)
    all_notfound = all(f.failure is C.FailureClass.NOT_FOUND for f in v.failed)
    for f in v.failed:
        print(f"        ✗ {f.candidate.endpoint:42s} {f.failure.name}({f.failure.symptom}) "
              f"{f.failure.level.value} move={f.failure.move}")
    check("toda alucinación pegó 404 vivo y la tabla §5 la dropeó (NOT_FOUND)",
          all_dropped and all_notfound and len(v.failed) == len(_HALLUCINATED),
          f"{len(v.failed)}/{len(_HALLUCINATED)} dropeadas")
    check("NINGUNA alucinación entró a VERIFIED (el candado protege la forja)",
          len(v.verified) == 0)
    check("cada drop trae nivel + move de la tabla §5",
          all(f.failure.level and f.failure.move for f in v.failed))

    # ── 3b · ORGÁNICO (informativo, no bloqueante) ─────────────────────────────
    # El candado TAMBIÉN dispara orgánicamente cuando el cerebro de turno propone algo
    # inexistente o fuera del alcance de la credencial. Es ESTOCÁSTICO (Opus conoce TMDB
    # casi perfecto → alucina ≈0%; a veces propone un endpoint que exige sesión → 401/403).
    # Lo reportamos como contexto; el bloqueante es el self-test determinístico de arriba.
    call_syms = {"404", "200_schema", "401_403", "timeout_5xx"}
    opus_real = [d for d in opus_res.dropped_by_failure_table if d["symptom"] in call_syms]
    print(f"    · orgánico (Opus, este run): {len(opus_res.verified)} verificadas, "
          f"{len(opus_real)} drops de llamada real "
          f"(alucinación de Opus en TMDB ≈ 0%; cuando cae suele ser auth-scoped 401/403).")
    for d in opus_real[:6]:
        print(f"        ✗ {d['endpoint']:42s} {d['class']}({d['symptom']}) move={d['move']}")


def gate_forged_from_scratch(res, principal, root: Path) -> None:
    print("\n[4] el MCP emitido es real y forjado DESDE CERO")
    f = res.forged
    check("se forjó un MCP", f is not None)
    if not f:
        return
    # SCOPEAR al dir del run VERDE (Opus): el root es compartido con la sub-corrida OSS,
    # que tiene su propio vault — no contamos globalmente, miramos el dir de este run.
    green_dir = C.credential_dir(principal, "tmdb-gate", root=root)
    belt_file = green_dir / "belt-tmdb-gate.mcp.json"
    forge_spec = green_dir / "tmdb-gate.forge.json"
    cred_file = green_dir / "credentials.enc"
    check("belt-<slug>.mcp.json existe en disco", belt_file.exists(), str(belt_file))
    check("<slug>.forge.json existe (spec del MCP)", forge_spec.exists(), str(forge_spec))
    check("credentials.enc existe (key cifrada en vault)", cred_file.exists(), str(cred_file))
    check("nació de cero (root tmp recién creado, sin config previo)", root.exists())
    check("el MCP expone las N tools verificadas", len(f.tools) == len(res.verified),
          f"{len(f.tools)} tools / {len(res.verified)} verified")
    # el secreto NO aparece en claro en NINGÚN artefacto
    leaked = []
    secret = os.environ.get("TMDB_API_KEY", "")
    if secret:
        for p in root.rglob("*"):
            if p.is_file() and p.name != "credentials.enc":
                if secret.encode() in p.read_bytes():
                    leaked.append(str(p.relative_to(root)))
    check("la api_key NUNCA aparece en claro en el manifest/spec", not leaked,
          "limpio" if not leaked else f"FILTRADA en {leaked}")


def gate_budget_and_degraded(res, key: str, base: str, root: Path) -> None:
    print("\n[5] budget cap respetado + degraded honesto")
    b = res.budget
    caps = b.get("caps", {})
    check("rounds ≤ cap", b["rounds"] <= caps.get("max_rounds", 1e9))
    check("live_calls ≤ cap", b["live_calls"] <= caps.get("max_live_calls", 1e9),
          f"{b['live_calls']}/{caps.get('max_live_calls')}")
    check("synth_tokens ≤ cap", b["synth_tokens"] <= caps.get("max_synth_tokens", 1e9))
    check("la corrida verde NO está degradada", res.degraded is False)

    # sub-corrida: cerebro caído (shim a un puerto muerto) → degraded:true honesto.
    print("    · sub-corrida degradada (shim → puerto muerto)…")
    old = os.environ.get("PUPPET_BRAIN_SHIM_BASE_URL")
    os.environ["PUPPET_BRAIN_SHIM_BASE_URL"] = "http://127.0.0.1:1/v1"
    os.environ["PUPPET_BRAIN_SHIM"] = "1"
    try:
        # importante: re-importar models para que tome el base muerto.
        import importlib
        from assembler import models as _m
        importlib.reload(_m)
        from inspection.loop import synth as _s
        importlib.reload(_s)
        from inspection.loop import engine as _e
        importlib.reload(_e)
        principal = C.Principal(anon_id=f"gate-degraded-{uuid.uuid4().hex[:8]}")
        dres = _e.run_internal_loop(base, key, principal, slug="tmdb-degraded",
                                    budget=Budget(max_rounds=2, max_live_calls=10),
                                    cred_root=root, forge=False)
        had_degraded_event = any(ev.get("type") == "synth" and ev.get("degraded")
                                 for ev in dres.events)
        check("con el cerebro caído, degraded:true aparece en el evento", had_degraded_event)
        check("la sesión IGUAL se validó viva (verify-from-env aún en degradado)",
              not dres.error, dres.error or "sesión viva")
    finally:
        if old is None:
            os.environ.pop("PUPPET_BRAIN_SHIM_BASE_URL", None)
        else:
            os.environ["PUPPET_BRAIN_SHIM_BASE_URL"] = old


def main() -> int:
    key = os.environ.get("TMDB_API_KEY", "")
    base = os.environ.get("TMDB_BASE", TMDB_BASE)
    print("═" * 72)
    print("  GATE VERDE · LOOP INTERNO §3 · verify-from-environment (TMDB vivo)")
    print("═" * 72)
    if not key:
        print("\n  ⚠️  SIN TMDB_API_KEY — el gate es verify-from-ENVIRONMENT: necesita la key viva.")
        print("      Conseguila gratis (API Key v3): https://www.themoviedb.org/settings/api")
        print("      Luego: TMDB_API_KEY=xxxx PUPPET_BRAIN_SHIM=1 <python> este_archivo.py")
        return 2

    root = Path(tempfile.mkdtemp(prefix="loop-gate-"))
    principal, res = _green_run(key, base, root)

    # log del working set (auditable §3)
    print("\n  ── working set por vuelta (§3) ──")
    for r in res.rounds_log:
        print(f"   v{r['round']}: CONFIRMED={r['CONFIRMED_total']} "
              f"VERIFIED+={r['VERIFIED_nuevas']} FAILED+={r['FAILED_nuevas']} "
              f"FRONTIER={r['FRONTIER_size']} calls={r['budget']['live_calls']}")

    gate_converges_verified(res)
    gate_really_called(res)
    gate_dropped_hallucination(res, key, base, root)
    gate_forged_from_scratch(res, principal, root)
    gate_budget_and_degraded(res, key, base, root)   # último: recarga módulos para el degradado

    print("\n" + "═" * 72)
    if _FAILS:
        print(f"  ROJO — {len(_FAILS)} check(s) fallaron: {_FAILS}")
        return 1
    print("  VERDE — la tesis del loop interno queda verificada contra el entorno vivo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
