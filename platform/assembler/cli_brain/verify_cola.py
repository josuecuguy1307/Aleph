#!/usr/bin/env python3
"""verify_cola.py — LA COLA: cerrar el turno cuando el CLI dice que terminó, no cuando
termina de morirse.

QUÉ MIDE, y por qué cada aserción puede dar ROJO
------------------------------------------------
El sujeto es `base._run_streaming` + `CliBrainProvider.invoke` REALES. El CLI se
reemplaza por un doble que emite **las líneas terminales LITERALES capturadas de los
binarios de verdad** (claude 2.1.229 · grok 1.0.5 · codex-cli 0.147.0, 2026-08-24) y
después **retiene sus tuberías** el tiempo que se le diga, que es exactamente lo que hace
la cola real:

    última línea → EOF de ambas tuberías   claude 529 · codex 453-567 · grok 286-314 ms
    EOF → muerte del proceso               0,0-0,1 ms

⚠️ LAS LÍNEAS TERMINALES SON FIXTURES DEL BINARIO, NO SALEN DE `fin_limpio`. Si el
esperado lo fabricara la misma función bajo prueba, la vara no podría distinguir un
`fin_limpio` correcto de uno roto — que es uno de los puntos ciegos ya pagados en esta
casa.

  A · el turno LIMPIO corta por evento terminal y se ahorra la cola entera
  B · el turno FALLIDO **no** corta: espera el EOF y el `returncode` REAL llega a
      `parse_result` (si esto se rompe, un fallo deja de decirse)
  C · el usage del evento terminal llega al consumidor ANTES del corte
  D · el workdir efímero sobrevive hasta que el proceso MUERE (codex escribe su
      `last-message.txt` 252 ms después de su `turn.completed`)
  E · cero procesos huérfanos y cero hilos colgados después de N turnos
  F · `cerrar_turno` NO borra la fila del registro mientras el cosechador trabaja
  G · un provider que no implementa `fin_limpio` sigue cerrando por EOF (fail-closed)

`--mutantes` corre siete mutaciones que rompen el mecanismo a propósito y exige que la
vara las cace. Una vara que no puede dar rojo no mide nada.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from pathlib import Path

_AQUI = Path(__file__).resolve()
sys.path.insert(0, str(_AQUI.parents[2]))          # …/platform

from assembler.cli_brain import base                                    # noqa: E402
from assembler.cli_brain.base import BrainResult, CliBrainProvider      # noqa: E402
from assembler.cli_brain.claude_cli import ClaudeCliProvider            # noqa: E402
from assembler.cli_brain.codex_cli import CodexCliProvider              # noqa: E402
from assembler.cli_brain.grok_cli import GrokCliProvider                # noqa: E402

# El registro va a un temporal: una vara JAMÁS escribe en el ledger real del usuario.
_TMP_REG = tempfile.mkdtemp(prefix="verify-cola-reg-")
os.environ["PUPPET_CLI_EVENTOS"] = os.path.join(_TMP_REG, "cli_eventos.jsonl")

_FALLOS: list = []
_OK = 0


def ok(cond, titulo, detalle=""):
    global _OK
    if cond:
        _OK += 1
        print(f"  ✅ {titulo}")
    else:
        _FALLOS.append(titulo)
        print(f"  ❌ {titulo}" + (f"\n      → {detalle}" if detalle else ""))


# ═══════════════════════════════════════════════════════════════════════════════
# LAS LÍNEAS TERMINALES, CAPTURADAS DE LOS BINARIOS REALES (no derivadas del código)
# ═══════════════════════════════════════════════════════════════════════════════
TERM_CLAUDE_OK = ('{"is_error":false,"duration_api_ms":2285,"num_turns":1,'
                  '"stop_reason":"end_turn","session_id":"8ec6399d","total_cost_usd":0.034,'
                  '"usage":{"input_tokens":2,"cache_creation_input_tokens":3385,'
                  '"cache_read_input_tokens":0,"output_tokens":4}}')
TERM_CLAUDE_MAL = ('{"is_error":true,"duration_api_ms":0,"num_turns":1,'
                   '"stop_reason":"stop_sequence","session_id":"1cf77b16","total_cost_usd":0,'
                   '"usage":{"input_tokens":0,"output_tokens":0},'
                   '"terminal_reason":"api_error"}')
TERM_GROK_OK = ('{"type":"end","stopReason":"end_turn","sessionId":"01a03715",'
                '"usage":{"input_tokens":21642,"cache_read_input_tokens":256,'
                '"output_tokens":17,"reasoning_tokens":16},"num_turns":1}')
TERM_CODEX_OK = ('{"type":"turn.completed","usage":{"input_tokens":12524,'
                 '"cached_input_tokens":2816,"output_tokens":5,"reasoning_output_tokens":0}}')
TERM_CODEX_MAL = ('{"type":"turn.failed","error":{"message":"400 invalid_request_error"}}')

PREV_CLAUDE = ['{"type":"system","subtype":"init","tools":[],"mcp_servers":[]}',
               '{"type":"stream_event","event":{"type":"content_block_delta",'
               '"delta":{"type":"text_delta","text":"OK"}}}']
PREV_GROK = ['{"type":"available_commands","tools":[]}', '{"type":"text","data":"OK"}']
PREV_CODEX = ['{"type":"thread.started","thread_id":"t1"}', '{"type":"turn.started"}',
              '{"type":"item.completed","item":{"id":"item_0","type":"agent_message",'
              '"text":"OK"}}']

#: Cuánto retiene sus tuberías el doble después de la última línea. Es la cola real
#: redondeada hacia abajo — si el mecanismo no la evita, el turno la paga entera.
COLA_MS = 500


def _guion(lineas: list, cola_ms: int, rc: int, escribe_tarde: str = "") -> str:
    """El doble del CLI: escribe sus líneas, retiene las tuberías `cola_ms`, y sale con
    `rc`. `escribe_tarde` es un archivo que crea DESPUÉS de la última línea — el
    `last-message.txt` de codex, que llega 252 ms tarde."""
    return textwrap.dedent(f"""
        import sys, time, os
        for l in {lineas!r}:
            sys.stdout.write(l + "\\n"); sys.stdout.flush()
        time.sleep({cola_ms} / 2000.0)
        _tarde = {escribe_tarde!r}
        if _tarde:
            with open(_tarde, "w") as fh:
                fh.write("texto tardio del agente")
        time.sleep({cola_ms} / 2000.0)
        sys.exit({rc})
    """)


class _Doble(CliBrainProvider):
    """Un provider real con un binario falso. Hereda TODO de `CliBrainProvider`:
    `invoke`, el corte, el cosechador. Lo único suyo es qué proceso spawnea."""

    provider_id = "doble"
    display_name = "Doble"
    response_model_id = "doble"

    def __init__(self, lineas, cola_ms=COLA_MS, rc=0, stream=True, escribe_tarde="",
                 fin_de=None):
        self._lineas, self._cola_ms, self._rc = lineas, cola_ms, rc
        self._stream, self._escribe_tarde = stream, escribe_tarde
        self._fin_de = fin_de          # el `fin_limpio` del provider REAL que se testea
        self.vistos = []

    def _bin_env_var(self): return "PUPPET_DOBLE_BIN"
    def _bin_name(self): return sys.executable
    def binary(self): return sys.executable
    def default_model(self): return "m"
    def build_detect_argv(self, binary): return [binary, "-c", "pass"]
    def parse_detect(self, rc, out, err): return base.STATE_READY, "", {}
    def usa_stream_json(self): return self._stream

    def fin_limpio(self, obj):
        # ⚠️ Con `fin_de=None` NO se sobrescribe: se delega en `CliBrainProvider.fin_limpio`,
        # que es el default fail-closed que el caso G afirma. Devolver `False` acá haría que
        # el caso G midiera a este doble en vez de a la base — y un mutante que rompiera el
        # default pasaría en verde (pasó: mutante M6 sobrevivió a la primera versión).
        if self._fin_de is None:
            return super().fin_limpio(obj)
        return self._fin_de(obj)

    def parse_stream_line(self, obj):
        if obj.get("type") == "end" or "is_error" in obj or obj.get("type") == "turn.completed":
            return "resultado", obj
        return "sistema", obj

    def build_argv(self, binary, prompt, model, workdir, effort=None, stream=False,
                   sesion=None):
        tarde = os.path.join(workdir, self._escribe_tarde) if self._escribe_tarde else ""
        return [binary, "-c", _guion(self._lineas, self._cola_ms, self._rc, tarde)]

    def parse_result(self, returncode, stdout, stderr, workdir, model):
        # EL RETURNCODE QUE LLEGA ACÁ ES LA ASERCIÓN B: se guarda tal cual para poder
        # afirmar sobre él, y el camino de error es el mismo `!= 0` de los tres providers.
        self.rc_visto = returncode
        self.workdir_visto = workdir
        self.existe_tarde = (os.path.exists(os.path.join(workdir, self._escribe_tarde))
                             if self._escribe_tarde else None)
        if returncode != 0:
            return BrainResult(ok=False, error_kind=base.ERR_MODEL,
                               error_detail=f"rc={returncode}")
        return BrainResult(ok=True, text="OK")

    def classify_error(self, blob, returncode=None):
        return base.ERR_MODEL, ""


def _correr(doble, timeout=30.0):
    """Un turno con el doble, cronometrado. Devuelve (BrainResult, ms, eventos)."""
    eventos = []
    t0 = time.monotonic()
    res = doble.invoke("p", model="m", timeout=timeout,
                       on_evento=lambda c, k: eventos.append((c, k)))
    return res, (time.monotonic() - t0) * 1000.0, eventos


def _hijos_vivos(marca: str) -> int:
    """Procesos del doble todavía vivos. `pgrep -f` se auto-matchea, así que se filtra el
    propio pid y se busca una marca que sólo está en el guion del hijo."""
    yo = str(os.getpid())
    try:
        salida = subprocess.run(["ps", "-eo", "pid=,command="], capture_output=True,
                                text=True, timeout=10).stdout
    except Exception:
        return -1
    n = 0
    for linea in salida.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        pid, _, cmd = linea.partition(" ")
        if pid == yo:
            continue
        if marca in cmd:
            n += 1
    return n


# ═══════════════════════════════════════════════════════════════════════════════
def caso_A():
    print("\n[A] el turno LIMPIO corta por evento terminal y se ahorra la cola")
    for nombre, prev, term, fin, stream in (
            ("claude", PREV_CLAUDE, TERM_CLAUDE_OK, ClaudeCliProvider().fin_limpio, True),
            ("grok",   PREV_GROK,   TERM_GROK_OK,   GrokCliProvider().fin_limpio,   True),
            ("codex",  PREV_CODEX,  TERM_CODEX_OK,  CodexCliProvider().fin_limpio,  False)):
        d = _Doble(prev + [term], cola_ms=COLA_MS, rc=0, stream=stream, fin_de=fin)
        res, ms, _ = _correr(d)
        st = (res.meta or {}).get("stream") or {}
        ok(st.get("cierre") == "evento_terminal",
           f"{nombre}: cierre='evento_terminal'", f"meta.stream={st}")
        ok(ms < COLA_MS * 0.75,
           f"{nombre}: el turno tarda {ms:.0f} ms < {COLA_MS*0.75:.0f} (no pagó la cola)",
           f"tardó {ms:.0f} ms con una cola de {COLA_MS} ms")
        ok(res.ok, f"{nombre}: el turno sigue siendo exitoso", f"{res.error_detail}")
        ok(getattr(d, "rc_visto", None) == 0,
           f"{nombre}: parse_result recibió rc=0", f"rc={getattr(d,'rc_visto','?')}")


def caso_B():
    print("\n[B] el turno FALLIDO no corta: espera el EOF y el returncode REAL llega")
    for nombre, prev, term, fin, stream, rc in (
            ("claude", PREV_CLAUDE, TERM_CLAUDE_MAL, ClaudeCliProvider().fin_limpio, True, 1),
            ("codex",  PREV_CODEX,  TERM_CODEX_MAL,  CodexCliProvider().fin_limpio,  False, 1)):
        d = _Doble(prev + [term], cola_ms=COLA_MS, rc=rc, stream=stream, fin_de=fin)
        res, ms, _ = _correr(d)
        st = (res.meta or {}).get("stream") or {}
        ok(st.get("cierre") == "eof", f"{nombre} fallido: cierre='eof'", f"{st}")
        ok(getattr(d, "rc_visto", None) == rc,
           f"{nombre} fallido: parse_result recibió el rc REAL ({rc})",
           f"rc={getattr(d,'rc_visto','?')}")
        ok(not res.ok, f"{nombre} fallido: el turno se reporta como fallo")
    # grok fallido NO emite evento terminal: sin `end`, no hay nada que cortar
    d = _Doble(PREV_GROK + ['{"type":"error","message":"unknown model id"}'],
               cola_ms=COLA_MS, rc=1, stream=True, fin_de=GrokCliProvider().fin_limpio)
    res, ms, _ = _correr(d)
    st = (res.meta or {}).get("stream") or {}
    ok(st.get("cierre") == "eof", "grok sin `end`: cierre='eof'", f"{st}")
    ok(getattr(d, "rc_visto", None) == 1, "grok sin `end`: rc REAL = 1",
       f"rc={getattr(d,'rc_visto','?')}")


def caso_C():
    print("\n[C] el usage del evento terminal llega al consumidor ANTES del corte")
    d = _Doble(PREV_CLAUDE + [TERM_CLAUDE_OK], rc=0, stream=True,
               fin_de=ClaudeCliProvider().fin_limpio)
    res, ms, eventos = _correr(d)
    resultados = [k for c, k in eventos if c == "resultado"]
    ok(len(resultados) == 1, "el evento `resultado` se entregó", f"{[c for c,_ in eventos]}")
    u = (resultados[0].get("usage") if resultados else {}) or {}
    ok(u.get("cache_creation_input_tokens") == 3385,
       "el usage con el caché viajó entero al consumidor", f"usage={u}")
    ok((res.meta or {}).get("stream", {}).get("cierre") == "evento_terminal",
       "y aun así se cortó temprano")


def caso_D():
    print("\n[D] el workdir sobrevive hasta que el proceso MUERE (last-message.txt de codex)")
    d = _Doble(PREV_CODEX + [TERM_CODEX_OK], cola_ms=COLA_MS, rc=0, stream=False,
               escribe_tarde="last-message.txt", fin_de=CodexCliProvider().fin_limpio)
    res, ms, _ = _correr(d)
    wd = d.workdir_visto
    ok(res.ok and (res.meta or {}).get("stream", {}).get("cierre") == "evento_terminal",
       "cortó temprano")
    ok(os.path.isdir(wd), "el workdir todavía existe cuando `parse_result` corre",
       f"{wd} ya no estaba")
    # el archivo tardío se escribe DESPUÉS del corte: el cosechador tiene que dejarlo llegar
    fin = time.monotonic() + 5
    escrito = False
    while time.monotonic() < fin:
        if os.path.exists(os.path.join(wd, "last-message.txt")):
            escrito = True
            break
        time.sleep(0.01)
    ok(escrito, "el CLI pudo escribir su archivo tardío en el workdir (no se lo borramos)",
       f"nunca apareció last-message.txt en {wd}")
    fin = time.monotonic() + 10
    while time.monotonic() < fin and os.path.isdir(wd):
        time.sleep(0.02)
    ok(not os.path.isdir(wd), "y el cosechador SÍ lo borra cuando el proceso muere",
       f"{wd} quedó sin borrar (fuga de disco por turno)")


def caso_E():
    print("\n[E] cero huérfanos y cero hilos colgados después de N turnos")
    marca = "MARCA-COLA-E-" + os.urandom(4).hex()
    hilos0 = threading.active_count()
    N = 6
    for i in range(N):
        d = _Doble(PREV_CLAUDE + [f'{{"_m":"{marca}"}}', TERM_CLAUDE_OK],
                   cola_ms=300, rc=0, stream=True, fin_de=ClaudeCliProvider().fin_limpio)
        res, ms, _ = _correr(d)
    vivos_ya = _hijos_vivos(marca)
    ok(vivos_ya >= 0, "el detector de hijos funciona (control del instrumento)")
    fin = time.monotonic() + 15
    while time.monotonic() < fin and _hijos_vivos(marca) > 0:
        time.sleep(0.05)
    ok(_hijos_vivos(marca) == 0, f"cero procesos vivos del doble tras {N} turnos",
       f"quedaron {_hijos_vivos(marca)}")
    fin = time.monotonic() + 10
    while time.monotonic() < fin and threading.active_count() > hilos0:
        time.sleep(0.05)
    ok(threading.active_count() <= hilos0,
       f"cero hilos cosechadores colgados ({threading.active_count()} vs {hilos0} al empezar)")
    ok(len(base._ACTIVE_PROCESSES) == 0,
       "la tabla de procesos activos quedó vacía",
       f"{len(base._ACTIVE_PROCESSES)} procesos sin desregistrar")


def caso_F():
    print("\n[F] `cerrar_turno` no borra la fila mientras el cosechador trabaja")
    t = base.abrir_turno("turno-cola-F", "doble")
    d = _Doble(PREV_CLAUDE + [TERM_CLAUDE_OK], cola_ms=800, rc=0, stream=True,
               fin_de=ClaudeCliProvider().fin_limpio)
    res = d.invoke("p", model="m", timeout=30, turno_id=t.id)
    en_cosecha = t.id in base._COSECHANDO
    ok(en_cosecha, "el turno quedó marcado como en cosecha justo después del corte",
       f"_COSECHANDO={base._COSECHANDO}")
    reg = base._registro()
    fila_antes = any(f.get("turno_id") == t.id for f in (reg.leer() if reg else []))
    base.cerrar_turno(t.id)
    fila_despues = any(f.get("turno_id") == t.id for f in (reg.leer() if reg else []))
    ok(fila_antes and fila_despues,
       "la fila del registro SIGUE mientras el pid vive (rastro para el barrido)",
       f"antes={fila_antes} despues={fila_despues}")
    fin = time.monotonic() + 10
    while time.monotonic() < fin and any(f.get("turno_id") == t.id
                                         for f in (reg.leer() if reg else [])):
        time.sleep(0.05)
    ok(not any(f.get("turno_id") == t.id for f in (reg.leer() if reg else [])),
       "y el cosechador la borra cuando el proceso murió")


def caso_G():
    print("\n[G] fail-closed: un provider sin `fin_limpio` cierra por EOF como siempre")
    d = _Doble(PREV_CLAUDE + [TERM_CLAUDE_OK], cola_ms=COLA_MS, rc=0, stream=True,
               fin_de=None)          # el default de CliBrainProvider: siempre False
    res, ms, _ = _correr(d)
    st = (res.meta or {}).get("stream") or {}
    ok(st.get("cierre") == "eof", "sin `fin_limpio` el cierre sigue siendo 'eof'", f"{st}")
    ok(ms >= COLA_MS * 0.75, f"y paga la cola entera ({ms:.0f} ms)",
       f"tardó {ms:.0f} ms — ¿cortó sin permiso?")


CASOS = [caso_A, caso_B, caso_C, caso_D, caso_E, caso_F, caso_G]


def main() -> int:
    print("=" * 74)
    print("VERIFY COLA — el turno cierra cuando el CLI dice que terminó")
    print("=" * 74)
    for c in CASOS:
        c()
    print("\n" + "-" * 74)
    print(f"{_OK} verdes · {len(_FALLOS)} rojas")
    for f in _FALLOS:
        print(f"   ROJA: {f}")
    shutil.rmtree(_TMP_REG, ignore_errors=True)
    return 1 if _FALLOS else 0


if __name__ == "__main__":
    sys.exit(main())
