#!/usr/bin/env python3
"""verify_cli_usage.py — LA VARA DE F2c (Gate 2 · usage honesto en la vía CLI).

Lo que esta vara exige que quede verde:

    un turno REAL exitoso trae los números del CLI y `tokens_medidos: true` · un `result`
    con `is_error` trae usage en None + la causa tipada, JAMÁS ceros presentados como
    medidos · un CLI que no reporta `usage` da None de punta a punta y el annex lo dice ·
    COMPAT: un consumidor que lee los campos de hoy no revienta · y —lo que da sentido a
    todo— ese usage llega a `_accumulate_usage` de `recipe_assembler` como NO MEDIBLE, no
    como cero, SIN haber tocado ese archivo.

Los CLIs falsos son binarios de verdad (scripts Python ejecutables apuntados con
`PUPPET_CLAUDE_BIN`), no mocks del provider: así el camino que se prueba es el mismo que
corre en producción, desde el spawn hasta el annex.

UNA llamada al CLI real (el caso 1). Se saltea con `SIN_CLI=1`.

    product/backend/.venv/bin/python platform/assembler/cli_brain/verify_cli_usage.py
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_ASM = _AQUI.parent
_RAIZ = _ASM.parents[1]
for _p in (str(_ASM), str(_RAIZ / "platform")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

sys.path.insert(0, str(_RAIZ / "qa" / "lib"))

from cli_brain import base as B                       # noqa: E402
from cli_brain.base import tokens_o_none, usage_del_cli  # noqa: E402
from cli_brain.claude_cli import ClaudeCliProvider    # noqa: E402
from cli_brain.codex_cli import CodexCliProvider      # noqa: E402
import errores_modelo as E                            # noqa: E402
import higiene_store as _HIG                          # noqa: E402
import veredicto as _V                                # noqa: E402

# [H1] El `mkdtemp` de `base.invoke` se borra solo; el ESPEJO que el CLI crea en
# `~/.claude/projects/` no. Barrido al salir, y sólo de lo que apareció acá.
_HIG.vigilar()

_fallos = 0
_salteados = 0


def ok(cond, nombre, detalle=""):
    global _fallos
    if cond:
        print(f"  ✓ {nombre}")
    else:
        _fallos += 1
        print(f"  ✗ {nombre}" + (f"  →  {detalle}" if detalle else ""))


def saltear(nombre, motivo):
    global _salteados
    _salteados += 1
    print(f"  ⊘ {nombre}  →  SALTEADO: {motivo}")


def seccion(t):
    print(f"\n── {t} " + "─" * max(0, 74 - len(t)))


def cli_falso(lineas_jsonl: list[str], *, rc: int = 0) -> str:
    """Un binario ejecutable que escupe el stream-json que le pidamos. Es un CLI de
    verdad para todo lo que nos importa: se spawnea, se lee por líneas y se parsea."""
    d = tempfile.mkdtemp(prefix="vara-usage-cli-")
    p = os.path.join(d, "claude")
    cuerpo = "\n".join(json.dumps(json.loads(l)) if l.strip().startswith("{") else l
                       for l in lineas_jsonl)
    with open(p, "w") as f:
        f.write(textwrap.dedent(f"""\
            #!{sys.executable}
            import sys
            sys.stdout.write({cuerpo!r} + "\\n")
            sys.stdout.flush()
            sys.exit({rc})
            """))
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return p


def _result(**campos) -> str:
    base = {"type": "result", "subtype": "success", "is_error": False,
            "num_turns": 1, "duration_ms": 100, "session_id": "s-1",
            "result": "OK", "modelUsage": {"claude-haiku-4-5-20251001": {"inputTokens": 10}}}
    base.update(campos)
    return json.dumps(base)


print("=" * 80)
print("VARA F2c · USAGE HONESTO EN LA VÍA CLI")
print("=" * 80)

# ══ 1 · LA GUARDA DE TIPO ══════════════════════════════════════════════════════════
seccion("1 · tokens_o_none — un entero es un entero; lo demás es AUSENCIA, no cero")
for entrada, esperado, por_que in (
        (10, 10, "un int es el int"),
        (0, 0, "un CERO REAL del CLI se conserva (medir 0 no es no medir)"),
        (None, None, "None es None"),
        ("7", 7, "un string numérico se acepta"),
        ("", None, "un string vacío es ausencia"),
        ("catorce", None, "un string basura es ausencia"),
        (-3, None, "un negativo es imposible → ausencia"),
        (True, None, "un bool NO es 1 (en Python es int, y acá sería un dato corrupto)"),
        (False, None, "y False no es 0"),
        (3.0, 3, "un float entero se acepta"),
        (3.7, None, "un float con decimales no es un conteo de tokens"),
        ([], None, "una lista es ausencia"),
        ({}, None, "un dict es ausencia")):
    ok(tokens_o_none(entrada) == esperado, f"{entrada!r:>12} → {esperado!r:<6} · {por_que}",
       f"dio {tokens_o_none(entrada)!r}")

seccion("1b · usage_del_cli — el dict + si SE MIDIÓ")
u, m = usage_del_cli({"input_tokens": 10, "output_tokens": 39})
ok(u == {"prompt_tokens": 10, "completion_tokens": 39} and m is True,
   "con datos: los números del CLI y medido=True", f"{u} {m}")
u, m = usage_del_cli({})
ok(u == {"prompt_tokens": None, "completion_tokens": None} and m is False,
   "sin datos: None en los dos campos y medido=False — JAMÁS 0", f"{u} {m}")
u, m = usage_del_cli({"input_tokens": 0, "output_tokens": 0})
ok(u == {"prompt_tokens": 0, "completion_tokens": 0} and m is True,
   "un CERO REPORTADO por el CLI sí es medido (0 medido ≠ no medido)", f"{u} {m}")
u, m = usage_del_cli({"input_tokens": 0, "output_tokens": 0}, medido=False)
ok(u == {"prompt_tokens": None, "completion_tokens": None} and m is False,
   "pero el mismo cero con medido=False (turno que NO corrió) es ausencia", f"{u} {m}")
u, m = usage_del_cli({"input_tokens": 10})
ok(u["prompt_tokens"] == 10 and u["completion_tokens"] is None and m is True,
   "medido parcial: lo que hay es dato, lo que falta es None", f"{u} {m}")

# ══ 2 · EL PROVIDER: parse_result sin ceros inventados ═════════════════════════════
seccion("2 · claude_cli.parse_result — el cero inventado ya no existe")
p = ClaudeCliProvider()
r = p.parse_result(0, _result(usage={"input_tokens": 10, "output_tokens": 39}), "", "/tmp", "haiku")
ok(r.ok and r.usage == {"prompt_tokens": 10, "completion_tokens": 39} and r.tokens_medidos,
   "turno sano CON usage → los números del CLI, tokens_medidos=True", f"{r.usage} {r.tokens_medidos}")
r = p.parse_result(0, _result(), "", "/tmp", "haiku")     # sin campo usage
ok(r.ok and r.usage == {"prompt_tokens": None, "completion_tokens": None}
   and r.tokens_medidos is False,
   "turno sano SIN usage → None y tokens_medidos=False (antes: 0 y 0)",
   f"{r.usage} {r.tokens_medidos}")
r = p.parse_result(0, _result(is_error=True, api_error_status=401,
                              terminal_reason="api_error",
                              usage={"input_tokens": 0, "output_tokens": 0},
                              modelUsage={}), "", "/tmp", "haiku")
ok(r.ok is False, "un result con is_error NO se devuelve como turno bueno")
ok(r.usage in ({}, {"prompt_tokens": None, "completion_tokens": None}),
   "y su usage en ceros NO viaja como medido", str(r.usage))
ok(r.tokens_medidos is False, "tokens_medidos=False en el camino de error", str(r.tokens_medidos))
# el caso patológico: is_error con usage REAL adentro
r = p.parse_result(0, _result(is_error=True, api_error_status=500,
                              usage={"input_tokens": 5, "output_tokens": 7}), "", "/tmp", "haiku")
ok(r.tokens_medidos is False,
   "ni siquiera un usage con números viaja como medido si el turno declaró is_error",
   str(r.tokens_medidos))

seccion("2b · codex_cli — el mismo no-inventar-cero")
c = CodexCliProvider()
rc_ = c.parse_result(0, json.dumps({"type": "item.completed",
                                    "item": {"type": "agent_message", "text": "hola"}})
                     + "\n" + json.dumps({"type": "turn.completed"}), "", "/tmp", "gpt-5")
ok(rc_.usage == {"prompt_tokens": None, "completion_tokens": None} and rc_.tokens_medidos is False,
   "turn.completed SIN usage → None, no 0", f"{rc_.usage} {rc_.tokens_medidos}")
rc_ = c.parse_result(0, json.dumps({"type": "item.completed",
                                    "item": {"type": "agent_message", "text": "hola"}})
                     + "\n" + json.dumps({"type": "turn.completed",
                                          "usage": {"input_tokens": 3, "output_tokens": 4}}),
                     "", "/tmp", "gpt-5")
ok(rc_.usage == {"prompt_tokens": 3, "completion_tokens": 4} and rc_.tokens_medidos is True,
   "turn.completed CON usage → los números y medido=True", f"{rc_.usage} {rc_.tokens_medidos}")

# ══ 3 · DE PUNTA A PUNTA: UN CLI FALSO, PERO UN SPAWN REAL ═════════════════════════
seccion("3 · spawn real de un CLI que NO reporta usage → None hasta el annex")
_guardado_bin = os.environ.get("PUPPET_CLAUDE_BIN")
try:
    os.environ["PUPPET_CLAUDE_BIN"] = cli_falso([
        json.dumps({"type": "system", "subtype": "init", "model": "modelo-falso"}),
        json.dumps({"type": "stream_event", "event": {
            "type": "content_block_delta", "delta": {"type": "text_delta", "text": "OK"}}}),
        _result(),                                    # sin `usage`
    ])
    prov = ClaudeCliProvider()
    res = prov.invoke("hola", model="haiku")
    ok(res.ok, "el turno del CLI falso salió bien", f"{res.error_kind}: {res.error_detail[:70]}")
    ok(res.usage == {"prompt_tokens": None, "completion_tokens": None},
       "usage None de punta a punta (spawn → parser → BrainResult)", str(res.usage))
    ok(res.tokens_medidos is False, "y tokens_medidos=False", str(res.tokens_medidos))
    ok(res.text == "OK", "el texto sí llegó (no se rompió nada por el usage ausente)", res.text)

    seccion("3b · el mismo CLI, ahora SÍ reportando usage")
    os.environ["PUPPET_CLAUDE_BIN"] = cli_falso([
        _result(usage={"input_tokens": 11, "output_tokens": 22}),
    ])
    res2 = ClaudeCliProvider().invoke("hola", model="haiku")
    ok(res2.usage == {"prompt_tokens": 11, "completion_tokens": 22} and res2.tokens_medidos,
       "los números del CLI llegan intactos y medidos", f"{res2.usage} {res2.tokens_medidos}")

    seccion("3c · un CLI que no reporta modelUsage → model_final None, sin fabricar")
    os.environ["PUPPET_CLAUDE_BIN"] = cli_falso([
        _result(modelUsage={}, usage={"input_tokens": 1, "output_tokens": 2}),
    ])
    res3 = ClaudeCliProvider().invoke("hola", model="haiku")
    ok(res3.model_final is None and res3.model_final_source == "",
       "sin modelUsage NO se fabrica un model_final (contrato viejo, intacto)",
       f"{res3.model_final!r} / {res3.model_final_source!r}")
    ok(res3.tokens_medidos is True, "y el usage sigue siendo medido: son cosas distintas")
finally:
    if _guardado_bin is None:
        os.environ.pop("PUPPET_CLAUDE_BIN", None)
    else:
        os.environ["PUPPET_CLAUDE_BIN"] = _guardado_bin

# ══ 4 · EL SERVER: el None sobrevive hasta el annex ════════════════════════════════
seccion("4 · server — el None llega al annex, y el annex lo declara")
import http.client                                     # noqa: E402
import threading                                       # noqa: E402

from cli_brain import detect as _detect                # noqa: E402
from cli_brain import slots as _slots                  # noqa: E402
from cli_brain.server import create_server             # noqa: E402


class _ProviderConUsage:
    provider_id, display_name, response_model_id = "claude_cli", "Claude Code", "lab-usage"

    def __init__(self, usage, medidos):
        self._u, self._m = usage, medidos

    def invoke(self, prompt, model=None, effort=None, on_evento=None, timeout=None,
               chunk_timeout=None):
        return B.BrainResult(ok=True, text="hola", model_final="lab-real",
                             model_final_source="cli-reported",
                             usage=self._u, tokens_medidos=self._m)


def _post(puerto, modelo):
    conn = http.client.HTTPConnection("127.0.0.1", puerto, timeout=30)
    conn.request("POST", "/v1/chat/completions",
                 json.dumps({"model": modelo, "messages": [{"role": "user", "content": "hi"}]}),
                 {"Content-Type": "application/json", "Host": f"127.0.0.1:{puerto}"})
    r = conn.getresponse()
    cuerpo = json.loads(r.read().decode())
    conn.close()
    return r.status, cuerpo


srv = create_server(0)
puerto = srv.server_port
threading.Thread(target=srv.serve_forever, daemon=True).start()
_g = dict(_detect._BY_MODEL_ID)
respuesta_sin = None
try:
    _slots.SLOTS.reiniciar()
    _detect._BY_MODEL_ID["lab-sin"] = _ProviderConUsage(
        {"prompt_tokens": None, "completion_tokens": None}, False)
    _detect._BY_MODEL_ID["lab-con"] = _ProviderConUsage(
        {"prompt_tokens": 11, "completion_tokens": 22}, True)

    st, respuesta_sin = _post(puerto, "lab-sin")
    u = respuesta_sin["usage"]
    ok(st == 200, "el turno sin usage responde 200 igual", str(st))
    ok(set(u) == {"prompt_tokens", "completion_tokens", "total_tokens"},
       "COMPAT: las TRES claves de siempre siguen estando", str(sorted(u)))
    ok(u["prompt_tokens"] is None and u["completion_tokens"] is None and u["total_tokens"] is None,
       "y sus valores son null — el cero inventado desapareció del cable", str(u))
    ok(respuesta_sin["aleph_cli_brain"]["tokens_medidos"] is False,
       "el annex lo DECLARA: tokens_medidos=false",
       str(respuesta_sin["aleph_cli_brain"].get("tokens_medidos")))
    for k in ("brain_provider", "provider_name", "model_final_source", "exec_events",
              "requested_model", "effort"):
        ok(k in respuesta_sin["aleph_cli_brain"], f"COMPAT: el annex conserva `{k}`")

    st, con = _post(puerto, "lab-con")
    ok(con["usage"] == {"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33},
       "con usage: los números y el total, como siempre", str(con["usage"]))
    ok(con["aleph_cli_brain"]["tokens_medidos"] is True, "y tokens_medidos=true")
finally:
    _detect._BY_MODEL_ID.clear()
    _detect._BY_MODEL_ID.update(_g)
    _slots.SLOTS.reiniciar()
    srv.shutdown()
    srv.server_close()

seccion("4b · COMPAT — un consumidor de HOY no revienta con el null")
u = respuesta_sin["usage"]
ok(int(u.get("prompt_tokens") or 0) == 0,
   "`int(usage.get('prompt_tokens') or 0)` — el patrón viejo — sigue dando 0 sin romper")
ok((u.get("total_tokens") or 0) == 0, "y `total_tokens or 0` también")
try:
    _ = u["prompt_tokens"]
    ok(True, "acceder por clave no levanta KeyError (la clave existe, vale null)")
except KeyError:
    ok(False, "acceder por clave no levanta KeyError")
ok(json.loads(json.dumps(respuesta_sin)) == respuesta_sin,
   "y la respuesta entera sigue siendo JSON serializable")

# ══ 5 · LO QUE DA SENTIDO A TODO: llega a _accumulate_usage como NO MEDIBLE ════════
seccion("5 · río abajo — `recipe_assembler` lo lee como no-medible, y no se tocó")
try:
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("vara_ra", _ASM / "recipe_assembler.py")
    _ra = _ilu.module_from_spec(_spec)
    sys.modules["vara_ra"] = _ra
    _spec.loader.exec_module(_ra)

    acc = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
           "calls": 0, "calls_no_usage": 0}
    _ra._accumulate_usage(acc, respuesta_sin["usage"])
    ok(acc["calls_no_usage"] == 1 and acc["calls"] == 0,
       "un usage con los dos campos en None cae en `calls_no_usage` — NO suma una llamada medida",
       str(acc))
    ok(acc["total_tokens"] == 0 and acc["prompt_tokens"] == 0,
       "y no suma tokens fantasma al acumulador", str(acc))

    acc2 = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "calls": 0, "calls_no_usage": 0}
    _ra._accumulate_usage(acc2, {"prompt_tokens": 11, "completion_tokens": 22})
    ok(acc2["calls"] == 1 and acc2["total_tokens"] == 33,
       "y con números reales sí suma como medido (el camino bueno no cambió)", str(acc2))

    # EL CONTRASTE: lo que hacía el cero inventado
    acc3 = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "calls": 0, "calls_no_usage": 0}
    _ra._accumulate_usage(acc3, {"prompt_tokens": 0, "completion_tokens": 0})
    ok(acc3["calls"] == 1 and acc3["calls_no_usage"] == 0,
       "EL CONTRASTE: el cero inventado de antes contaba como llamada MEDIDA de 0 tokens",
       str(acc3))

    # y el cost-event: sin datos → tokens_measured False y usd None
    rec = {"cost_events": [], "model_route": [{"model": "x"}], "model_alias": "brain"}
    _ra._emit_model_cost_event(rec, None, user_id=None, run_id=None, model="claude-code-cli",
                              tier="primary", usage=respuesta_sin["usage"])
    ev = rec["cost_events"][-1]
    ok(ev["tokens_measured"] is False,
       "`_emit_model_cost_event` lo marca `tokens_measured: false`", str(ev)[:110])
    ok(ev["usd"] is None, "y deja el usd en None: no se inventa un costo sobre un no-dato",
       str(ev.get("usd")))
    ok(ev["tokens"] == {"prompt": 0, "completion": 0, "total": 0},
       "los tokens del evento son 0 pero la BANDERA dice que no fueron medidos "
       "(el ledger sabe distinguir)", str(ev["tokens"]))
except Exception as exc:                                # noqa: BLE001
    ok(False, "se pudo cargar recipe_assembler para verificar río abajo",
       f"{type(exc).__name__}: {exc}")

# ══ 6 · EL CLI REAL ════════════════════════════════════════════════════════════════
seccion("6 · CLI REAL — un turno exitoso trae los números del CLI")
if os.environ.get("SIN_CLI"):
    saltear("el turno contra el CLI real", "SIN_CLI=1")
else:
    prov = ClaudeCliProvider()
    if not prov.binary():
        saltear("el turno contra el CLI real", "`claude` no está instalado")
    elif prov.detect().state != B.STATE_READY:
        saltear("el turno contra el CLI real", f"detect() = {prov.detect().state}")
    else:
        r = prov.invoke("Responde exactamente: OK",
                        model=os.environ.get("VARA_CLI_MODELO", "haiku"))
        ok(r.ok, "el turno real salió bien", f"{r.error_kind}: {r.error_detail[:80]}")
        ok(r.tokens_medidos is True, "tokens_medidos=True", str(r.tokens_medidos))
        pt, ct = r.usage.get("prompt_tokens"), r.usage.get("completion_tokens")
        ok(isinstance(pt, int) and isinstance(ct, int),
           f"y los tokens son enteros REALES del CLI: prompt={pt} completion={ct}",
           str(r.usage))
        ok((pt or 0) > 0 or (ct or 0) > 0, "con al menos uno distinto de cero", str(r.usage))
        ok(r.model_final and r.model_final_source == "cli-reported",
           f"y el model_final sigue saliendo de modelUsage ({r.model_final})")
        print(f"      · usage real del CLI: {r.usage}")

# ══ 7 · LAS VARAS ANTERIORES SIGUEN VERDES ═════════════════════════════════════════
seccion("7 · verify_traductor · verify_cli_streaming · verify_cli_slots")
for nombre, ruta in (("verify_traductor", _ASM / "verify_traductor.py"),
                     ("verify_cli_streaming", _AQUI / "verify_cli_streaming.py"),
                     ("verify_cli_slots", _AQUI / "verify_cli_slots.py")):
    r = subprocess.run([sys.executable, str(ruta)], capture_output=True, text=True,
                       timeout=900, env=dict(os.environ))
    ok(r.returncode == 0, f"{nombre}.py sale con exit 0",
       (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else "")
    # [H4a] `"TODO VERDE" in stdout` daba True también con `TODO VERDE (con 3 salteo(s)…)`:
    # el verde barato de la hija se propagaba al padre sin que nadie lo viera. `es_verde_limpio`
    # pide la línea ENTERA — verde sin salteos, o no es verde.
    ok(_V.es_verde_limpio(r.stdout),
       f"y dice TODO VERDE, SIN salteos ({r.stdout.count('✓')} aserciones)",
       (r.stdout.strip().splitlines() or [""])[-1])

# [H4a] El cierre pasa por `qa/lib/veredicto.py`: con salteos declarados la última
# línea ya NO es el string pelado `TODO VERDE`. La regla vive en un solo lugar.
print(f"\n{_V.texto(_fallos, _salteados)}")
sys.exit(0 if _fallos == 0 else 1)
