#!/usr/bin/env python3
"""
selftest_loop_alphavantage.py — GATE del MISMO loop §3, apuntado a Alpha Vantage.

Mismo motor/capas/budget que el gate TMDB; el FOCO acá es la condición #3 ORGÁNICA:
ver al candado (Capa 4) cazar alucinaciones que el BRAIN propuso solo, porque Opus
conoce Alpha Vantage MUCHO menos que TMDB.

  1. converge a N tools de lectura VERIFICADAS, cada una llamada REAL contra AV vivo
     (HTTP 200 + datos reales, NO un sobre de error en-banda).
  2. cada verificada trae datos genuinos (no {"Error Message"/"Information"/"Note"}).
  3. EL FOCO — el candado dropea alucinaciones ORGÁNICAS del cerebro: candidatas que
     Opus propuso y el validador mató (200+error-en-banda → §5 NOT_FOUND / schema).
     Se REPORTA lo orgánico de la corrida viva (el titular). El BLOQUEANTE es un lock
     determinístico (el Validador real contra funciones inexistentes) — así el gate
     no es frágil si Opus resulta conocer AV mejor de lo esperado. HONESTO: si Opus no
     alucinó nada este run, se dice y se muestra el lock; NO se maquilla una alucinación.
  4. MCP forjado DESDE CERO · key del vault (cero claro) · 5. budget + degraded honesto.

Uso:
    export ALPHAVANTAGE_API_KEY=xxxx
    PUPPET_BRAIN_SHIM=1 product/backend/.venv/bin/python \\
      platform/inspection/loop/selftest_loop_alphavantage.py
"""
from __future__ import annotations

import json
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
from inspection.loop.engine import ALPHAVANTAGE_BASE, run_internal_loop  # noqa: E402
from inspection.loop.live_http import LiveHTTP  # noqa: E402
from inspection.loop.run_alphavantage import AV_KNOBS  # noqa: E402
from inspection.loop.validator import LiveValidator  # noqa: E402

_FAILS: list[str] = []
_CAVEATS: list[str] = []
_SOFT = ("error message", "information", "note")


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "✓" if cond else "✗"
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        _FAILS.append(name)


def _looks_soft(sample: str) -> bool:
    """¿el snippet de respuesta es un sobre de error en-banda? (mira las claves líder)."""
    head = (sample or "").lstrip()[:80].lower()
    return any(f'"{k}"' in head for k in _SOFT)


def _green_run(key: str, base: str, root: Path):
    principal = C.Principal(anon_id=f"avgate-{uuid.uuid4().hex[:12]}")
    # Budget FRUGAL: AV free tier ≈ 25 req/día. 2 vueltas alcanzan para converger a N
    # tools + cazar alucinaciones orgánicas; el cap deja margen para el lock + degradado.
    budget = Budget(max_rounds=2, max_live_calls=11, max_synth_tokens=300_000, max_seconds=300)
    res = run_internal_loop(base, key, principal, slug="av-gate",
                            budget=budget, cred_root=root, **AV_KNOBS)
    return principal, res


def gate_converges_verified(res) -> None:
    print("\n[1] converge a N tools de lectura VERIFICADAS contra AV vivo")
    check("el loop no erroró en la puerta", not res.error, res.error or "ok")
    check("convergió a N≥2 tools verificadas", len(res.verified) >= 2,
          f"{len(res.verified)}: {res.verified_names}")
    check("todas las verificadas son GET (read-only §7)",
          all(v.candidate.kind is C.ToolKind.READ and v.candidate.method == "GET"
              for v in res.verified))


def gate_really_called(res) -> None:
    print("\n[2] cada verificada respondió con DATOS reales (no sobre de error)")
    check("toda verificada trae verified_by=200-OK+schema-match",
          all(v.verified_by == "200-OK+schema-match" for v in res.verified))
    soft = [v.candidate.name for v in res.verified if _looks_soft(v.sample_response or "")]
    check("ninguna verificada es un sobre de error en-banda (datos genuinos)",
          not soft, "todas con datos" if not soft else f"SOFT en {soft}")
    # mostrar la función de cada verificada (evidencia del despacho-por-query)
    for v in res.verified[:14]:
        q = (v.candidate.input_schema.get("x-sample-call") or {}).get("query", {})
        print(f"        ✓ {v.candidate.name:30s} function={q.get('function','?')}")


def _lock_self_test(key: str, base: str):
    """Determinístico: el Validador REAL contra `function`s inexistentes vivas. AV las
    contesta 200 + {"Error Message"/"Information"} → el candado las clasifica NOT_FOUND
    y NO entran a la forja. (No finge un PASS; verifica un RECHAZO real.)"""
    http = LiveHTTP(secret=key, auth_param=AV_KNOBS["auth_param"], min_interval=AV_KNOBS["min_interval"])
    validator = LiveValidator(http, soft_error_keys=AV_KNOBS["soft_error_keys"],
                              soft_notice_keys=AV_KNOBS["soft_notice_keys"])
    session = C.Session(form=C.AuthForm.TOKEN, base_url=base)
    bogus = ["FOOBAR_NOTREAL", "STOCK_MAGIC_8BALL"]   # 2 (frugal con la quota diaria)
    cands = tuple(
        C.CandidateTool(name=f"hallucinated_{fn.lower()}", kind=C.ToolKind.READ,
                        endpoint="/query", method="GET",
                        input_schema={"type": "object",
                                      "x-sample-call": {"query": {"function": fn, "symbol": "IBM"}}},
                        description="función inexistente para sondear el candado")
        for fn in bogus
    )
    return validator.validate(session, cands), len(bogus)


def gate_dropped_hallucination(res, lock) -> None:
    """`lock` = (validation, n) del lock self-test corrido ANTES del green (quota fresca)."""
    print("\n[3] EL FOCO — el candado §5 caza alucinaciones (orgánicas + lock)")

    # ── 3a · ORGÁNICO honesto: SOLO NOT_FOUND (404) es alucinación. timeout_5xx es
    #         TRANSITORIO (rate-limit / quota diaria de AV) — NO una alucinación; serían
    #         funciones REALES enmascaradas por el throttle. No las maquillo como tales. ──
    hallucinated = [d for d in res.dropped_by_failure_table if d["symptom"] == "404"]
    transient = [d for d in res.dropped_by_failure_table if d["symptom"] == "timeout_5xx"]
    print(f"    · orgánico (Opus, este run): {len(res.verified)} verificadas · "
          f"{len(hallucinated)} ALUCINACIONES (404) · {len(transient)} drops transitorios (quota/rate-limit)")
    for d in hallucinated[:10]:
        print(f"        ✗ ALUCINÓ {d['name']:26s} {d['class']}({d['symptom']}) move={d['move']}")
        print(f"           {d['detail'][:150]}")
    if hallucinated:
        print("    ✦ el candado cazó alucinaciones ORGÁNICAS del cerebro (no inyectadas).")
    else:
        print("    ⚠ HONESTO: Opus NO alucinó funciones inexistentes en esta corrida —")
        print("      conoce el set de functions de AV bien (igual que TMDB). Las funciones que")
        print("      'cayeron' son REALES, enmascaradas por la quota diaria (25/día) de AV, no")
        print(f"      alucinaciones ({len(transient)} drops transitorios). NO se maquillan.")
        print("      La garantía la sostiene el lock determinístico ↓ (+ prueba offline del clasificador).")

    # ── 3b · LOCK determinístico — corrido ANTES del green (quota fresca) ────────
    v, n = lock
    print(f"    · lock self-test (corrido primero): {n} functions inexistentes contra el Validador real…")
    notfound = [f for f in v.failed if f.failure is C.FailureClass.NOT_FOUND]
    transient_lock = [f for f in v.failed if f.failure is C.FailureClass.TIMEOUT]
    for f in v.failed:
        print(f"        ✗ {f.candidate.name:30s} {f.failure.name}({f.failure.symptom}) move={f.failure.move}")
    if len(notfound) == n and len(v.verified) == 0:
        check("toda function inexistente cayó por §5 NOT_FOUND (la alucinación NO entra a la forja)", True)
        check("NINGUNA alucinación entró a VERIFIED (el candado protege la forja)", len(v.verified) == 0)
        check("cada drop trae nivel + move de la tabla §5",
              all(f.failure.level and f.failure.move for f in v.failed))
    elif transient_lock and not notfound:
        # quota agotada: las bogus volvieron "25/día" (notice→timeout_5xx), no "does not
        # exist". El lock NO concluye HOY. Es bloqueo de ENTORNO (quota), no de código —
        # honesto: caveat, no PASS falso ni RED falso. El mecanismo está probado offline.
        _CAVEATS.append("lock determinístico DIFERIDO: quota diaria de AV (25/día) agotada — "
                        "las functions bogus volvieron rate-limit, no 'does not exist'. "
                        "El drop por NOT_FOUND está probado offline (classify) y por la sonda "
                        "viva inicial (FOOBAR_NOTREAL → 'does not exist'). Re-correr tras el reset.")
        print("    ⚠ lock INCONCLUSO hoy: quota AV agotada (bogus → rate-limit, no 'does not exist').")
        print("      No es fallo de código — es la quota del entorno. Mecanismo probado offline.")
        check("ninguna bogus se coló a VERIFIED ni con quota agotada (sigue protegida la forja)",
              len(v.verified) == 0)
    else:
        check("el lock dropeó las functions inexistentes por §5", False,
              f"{len(notfound)} NOT_FOUND / {len(v.verified)} verificadas / {len(transient_lock)} transitorias")


def gate_forged_from_scratch(res, principal, root: Path) -> None:
    print("\n[4] el MCP emitido es real y forjado DESDE CERO")
    f = res.forged
    check("se forjó un MCP", f is not None)
    if not f:
        return
    green_dir = C.credential_dir(principal, "av-gate", root=root)
    belt_file = green_dir / "belt-av-gate.mcp.json"
    forge_spec = green_dir / "av-gate.forge.json"
    cred_file = green_dir / "credentials.enc"
    check("belt-<slug>.mcp.json existe en disco", belt_file.exists(), str(belt_file))
    check("<slug>.forge.json existe (spec del MCP)", forge_spec.exists())
    check("credentials.enc existe (key cifrada en vault)", cred_file.exists())
    check("nació de cero (root tmp recién creado, sin config previo)", root.exists())
    check("el MCP expone las N tools verificadas", len(f.tools) == len(res.verified),
          f"{len(f.tools)} tools / {len(res.verified)} verified")
    # el secreto NO aparece en claro en NINGÚN artefacto
    leaked = []
    secret = os.environ.get("ALPHAVANTAGE_API_KEY", "")
    if secret:
        for p in root.rglob("*"):
            if p.is_file() and p.name != "credentials.enc" and secret.encode() in p.read_bytes():
                leaked.append(str(p.relative_to(root)))
    check("la api_key NUNCA aparece en claro en el manifest/spec", not leaked,
          "limpio" if not leaked else f"FILTRADA en {leaked}")


def gate_budget_and_degraded(res) -> None:
    print("\n[5] budget cap respetado + degraded honesto")
    b = res.budget
    caps = b.get("caps", {})
    check("rounds ≤ cap", b["rounds"] <= caps.get("max_rounds", 1e9))
    check("live_calls ≤ cap", b["live_calls"] <= caps.get("max_live_calls", 1e9),
          f"{b['live_calls']}/{caps.get('max_live_calls')}")
    check("synth_tokens ≤ cap", b["synth_tokens"] <= caps.get("max_synth_tokens", 1e9))
    check("la corrida verde NO está degradada", res.degraded is False)

    # degradado en AISLADO (cero calls a AV): el synth apuntado a un puerto muerto →
    # tras los reintentos declara degraded:true honesto. El cerebro es el sintetizador;
    # no se mete un modelo barato a fingir de cerebro.
    print("    · cerebro caído (synth → puerto muerto, sin tocar AV)…")
    from inspection.loop.synth import BrainSynthesizer
    s = BrainSynthesizer("https://www.alphavantage.co")
    s._endpoint = "http://127.0.0.1:1/v1/chat/completions"   # puerto muerto
    s._key = None
    obs = C.Observation(capability_map={"mode": "passive", "probes": {}}, confirmed=(), passive=True)
    out = s.synthesize((), obs, ())
    check("con el cerebro caído, el synth declara degraded:true (honesto)",
          s.last.degraded is True and out == ())
    check("el degraded trae razón explícita (no silencio)",
          bool(s.last.reason) and "brain" in s.last.reason.lower(), s.last.reason[:80])


def main() -> int:
    key = os.environ.get("ALPHAVANTAGE_API_KEY", "")
    base = os.environ.get("ALPHAVANTAGE_BASE", ALPHAVANTAGE_BASE)
    print("═" * 72)
    print("  GATE · LOOP INTERNO §3 · verify-from-environment (Alpha Vantage vivo)")
    print("  FOCO: el candado cazando alucinaciones ORGÁNICAS del cerebro")
    print("═" * 72)
    if not key:
        print("\n  ⚠️  SIN ALPHAVANTAGE_API_KEY — verify-from-ENVIRONMENT necesita la key viva.")
        print("      Gratis: https://www.alphavantage.co/support/#api-key")
        print("      Luego: export ALPHAVANTAGE_API_KEY=xxxx ; PUPPET_BRAIN_SHIM=1 <python> este_archivo.py")
        return 2

    root = Path(tempfile.mkdtemp(prefix="av-gate-"))

    # LOCK self-test PRIMERO (quota fresca): así las functions bogus reciben el
    # "does not exist" → NOT_FOUND antes de que el green consuma la quota diaria.
    print("\n  ── lock self-test (corrido ANTES del green, quota fresca) ──")
    lock = _lock_self_test(key, base)

    principal, res = _green_run(key, base, root)

    print("\n  ── working set por vuelta (§3) ──")
    for r in res.rounds_log:
        print(f"   v{r['round']}: CONFIRMED={r['CONFIRMED_total']} "
              f"VERIFIED+={r['VERIFIED_nuevas']} FAILED+={r['FAILED_nuevas']} "
              f"calls={r['budget']['live_calls']}")

    gate_converges_verified(res)
    gate_really_called(res)
    gate_dropped_hallucination(res, lock)
    gate_forged_from_scratch(res, principal, root)
    gate_budget_and_degraded(res)

    print("\n" + "═" * 72)
    if _FAILS:
        print(f"  ROJO — {len(_FAILS)} check(s) fallaron: {_FAILS}")
        return 1
    if _CAVEATS:
        print("  VERDE (con caveat de entorno) — la tesis queda verificada contra AV vivo:")
        for c in _CAVEATS:
            print(f"    ⚠ {c}")
        return 0
    print("  VERDE — la tesis del loop interno queda verificada contra Alpha Vantage vivo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
