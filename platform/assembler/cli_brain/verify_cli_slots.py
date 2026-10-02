#!/usr/bin/env python3
"""verify_cli_slots.py — LA VARA DE F2b (Gate 2 · concurrencia del BYO-CLI).

Lo que esta vara exige que quede verde:

    dos requests SIMULTÁNEOS al mismo provider: uno corre, el otro recibe la causa TIPADA
    — no cuelga, no revienta, no spawnea un segundo CLI · evidencia `ps` de que JAMÁS hay
    dos `claude -p` vivos a la vez · tras un rate_limit con reset corto, el siguiente turno
    se rechaza TIPADO con su `retry_after_s` hasta la hora del reset, y después pasa ·
    con `PUPPET_CLI_PAUSA=0` el comportamiento vuelve a ser el de hoy · `verify_cli_streaming`
    y `verify_traductor` siguen verdes.

El muestreo de `ps` filtra por un MARCADOR único en el prompt, no por el nombre del binario:
la máquina que corre esta vara puede tener otras sesiones de `claude` abiertas (la del
propio operador, sin ir más lejos) y contarlas sería mentir.

UNA llamada al CLI real (la del par simultáneo; la segunda del par se rechaza sin spawnear).
Se saltea con `SIN_CLI=1`.

    product/backend/.venv/bin/python platform/assembler/cli_brain/verify_cli_slots.py
"""
from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_ASM = _AQUI.parent
_RAIZ = _ASM.parents[1]
for _p in (str(_ASM), str(_RAIZ / "platform")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

sys.path.insert(0, str(_RAIZ / "qa" / "lib"))

from cli_brain import base as B                       # noqa: E402
from cli_brain import detect as _detect               # noqa: E402
from cli_brain import slots as S                      # noqa: E402
from cli_brain.claude_cli import ClaudeCliProvider    # noqa: E402
from cli_brain.server import create_server            # noqa: E402
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


AHORA = 1_785_000_000.0

print("=" * 80)
print("VARA F2b · CONCURRENCIA DEL BYO-CLI")
print("=" * 80)

# ══ 1 · EL CONTADOR, SIN RED NI PROCESOS ═══════════════════════════════════════════
seccion("1 · SlotPool — techo global + serialización por provider")
sl = S.Slots(limite=2)
sl.pedir("claude_cli")
ok(sl.estado()["activos"] == 1, "el primer turno toma un slot")
try:
    sl.pedir("claude_cli")
    ok(False, "un SEGUNDO turno del MISMO provider se rechaza aunque sobre slot")
except S.SinSlot as e:
    ok(e.motivo == S.PROVIDER_OCUPADO,
       "un SEGUNDO turno del MISMO provider se rechaza aunque sobre slot", e.motivo)
    ok(sl.estado()["activos"] == 1, "y NO consumió un slot al rechazarlo")
sl.pedir("codex_cli")
ok(sl.estado()["activos"] == 2, "otro provider SÍ puede usar el slot libre")
try:
    sl.pedir("otro_cli")
    ok(False, "con el techo lleno, un tercer provider se rechaza por SIN_SLOTS")
except S.SinSlot as e:
    ok(e.motivo == S.SIN_SLOTS and e.limite == 2,
       "con el techo lleno, un tercer provider se rechaza por SIN_SLOTS",
       f"{e.motivo} {e.activos}/{e.limite}")
sl.soltar("claude_cli")
ok(sl.estado()["activos"] == 1, "soltar libera el slot")
sl.pedir("claude_cli")
ok(sl.estado()["en_vuelo"] == ["claude_cli", "codex_cli"], "y el provider vuelve a poder pedir")
sl.reiniciar()

with sl.turno("claude_cli"):
    ok(sl.estado()["activos"] == 1, "el context manager toma el turno")
ok(sl.estado()["activos"] == 0, "y lo suelta al salir")
try:
    with sl.turno("claude_cli"):
        raise ValueError("bum")
except ValueError:
    pass
ok(sl.estado()["activos"] == 0, "lo suelta TAMBIÉN si el turno revienta")
ok(S.MAX_TURNOS == 2, f"el techo por defecto es 2 (cada turno es un Node entero)", str(S.MAX_TURNOS))

# ══ 1.bis · EL TECHO POR PROVIDER ══════════════════════════════════════════════════
# [Ciencia obra 1] La capa 2 dejó de ser `pid in set` (techo implícito de uno) y pasó a ser
# un número por provider. Lo que se mide acá es que el número se mueva SÓLO donde se dijo:
# Codex a 3 porque su turno normal se pisaba a sí mismo, todo lo demás en uno.
seccion("1.bis · el techo por provider — Codex a 3, el resto sigue serializado")
sl.reiniciar()
ok(S.techo_de("codex_cli") == 3, "el techo de codex_cli es 3", str(S.techo_de("codex_cli")))
ok(S.techo_de("claude_cli") == 1, "el de claude_cli sigue en 1", str(S.techo_de("claude_cli")))
ok(S.techo_de("cualquier_otro") == 1, "y el de un provider no declarado también",
   str(S.techo_de("cualquier_otro")))

# LA FORMA DEL TURNO MEDIDO: la llamada 1 termina, y las 2 y 3 arrancan en el MISMO
# instante — pico real 2, no 3. Antes de esta obra la tercera rebotaba con
# `provider_ocupado` (medido: `activos:1, limite:2`) y el cascade la mandaba al OSS local.
sl.pedir("codex_cli")
sl.soltar("codex_cli")
sl.pedir("codex_cli")
sl.pedir("codex_cli")
ok(sl.estado()["activos"] == 2, "dos turnos de Codex a la vez YA no rebotan (el turno "
   "normal de un workspace se pisaba a sí mismo)", str(sl.estado()["por_provider"]))
ok(sl.estado()["por_provider"]["codex_cli"] == {"activos": 2, "techo": 3},
   "y el forense dice cuántos van contra qué techo", str(sl.estado()["por_provider"]))

# EL TECHO GLOBAL SIGUE MANDANDO. Subir el del provider a 3 no sube la concurrencia real a
# 3: `MAX_TURNOS` sigue en 2, así que el tercero rebota por SIN_SLOTS y no por el provider.
try:
    sl.pedir("codex_cli")
    ok(False, "el techo GLOBAL sigue frenando al tercero, aunque el del provider dé 3")
except S.SinSlot as e:
    ok(e.motivo == S.SIN_SLOTS and e.limite == 2,
       "el techo GLOBAL sigue frenando al tercero, aunque el del provider dé 3",
       f"{e.motivo} {e.activos}/{e.limite}")

# Y LOS NÚMEROS DEL RECHAZO SON LOS DEL PROVIDER, no los globales.
sl.reiniciar()
sl.pedir("claude_cli")
try:
    sl.pedir("claude_cli")
    ok(False, "un rechazo de provider informa el techo DE ESE PROVIDER")
except S.SinSlot as e:
    ok(e.activos == 1 and e.limite == 1,
       "un rechazo de provider informa el techo DE ESE PROVIDER (1/1, no 1/2)",
       f"{e.activos}/{e.limite}")
    c = S.causa_de(e, nombre_cli="Claude")
    ok(c is not None and "otro turno" in (c.get("detalle") or ""),
       "y con techo 1 la copy sigue siendo la de siempre",
       str(c and c.get("detalle")))

# LA COPY NO MIENTE CON TECHO > 1: «otro turno» diría uno cuando hay tres.
e3 = S.SinSlot(S.PROVIDER_OCUPADO, provider="codex_cli", activos=3, limite=3)
c3 = S.causa_de(e3, nombre_cli="Codex")
ok(c3 is not None and "3 turnos" in (c3.get("detalle") or ""),
   "y con techo >1 la copy dice el número en vez de «otro turno»",
   str(c3 and c3.get("detalle")))
sl.reiniciar()

# ══ 2 · LA PAUSA ═══════════════════════════════════════════════════════════════════
seccion("2 · pausa por ventana agotada — la capa que nadie del barrido tiene")
sl.reiniciar()
ok(sl.pausar("claude_cli", AHORA + 300, ahora=AHORA), "una pausa a futuro se acepta")
try:
    sl.pedir("claude_cli", ahora=AHORA)
    ok(False, "y bloquea los turnos de ESE provider")
except S.SinSlot as e:
    ok(e.motivo == S.EN_PAUSA, "y bloquea los turnos de ESE provider", e.motivo)
    ok(295 < (e.restante_s or 0) <= 300,
       f"informando cuánto falta ({e.restante_s:.0f} s)", str(e.restante_s))
sl.pedir("codex_cli", ahora=AHORA)
ok(True, "pero NO bloquea a los demás providers (la ventana es de una cuenta)")
sl.soltar("codex_cli")

try:
    sl.pedir("claude_cli", ahora=AHORA + 301)
    ok(True, "pasado el reset, el turno pasa solo (la pausa se limpia sola)")
    sl.soltar("claude_cli")
except S.SinSlot as e:
    ok(False, "pasado el reset, el turno pasa solo", e.motivo)

sl.reiniciar()
ok(sl.pausar("claude_cli", AHORA - 10, ahora=AHORA) is False,
   "un reset EN EL PASADO no se acepta (no se inventa una pausa)")
ok(sl.pausar("claude_cli", AHORA + 40 * 3600, ahora=AHORA) is False,
   "un reset a 40 h no se acepta: el CLI está diciendo cualquier cosa")
ok(sl.pausar("claude_cli", "no soy un número", ahora=AHORA) is False,
   "y basura tampoco levanta ni pausa")
ok(sl.pausar_segundos("claude_cli", 120, ahora=AHORA), "pausar_segundos toma el retry_after_s de F1")
ok(sl.pausa_de("claude_cli", ahora=AHORA) is not None, "y queda vigente")
ok(sl.pausar_segundos("claude_cli", None, ahora=AHORA) is False, "un retry_after None no pausa")
ok(sl.pausar_segundos("claude_cli", 0, ahora=AHORA) is False, "y un 0 tampoco (None jamás 0)")
sl.reiniciar()

# ══ 3 · LA PERILLA ═════════════════════════════════════════════════════════════════
seccion("3 · PUPPET_CLI_PAUSA=0 — por si el reset del CLI viniera mentiroso")
os.environ["PUPPET_CLI_PAUSA"] = "0"
sl.reiniciar()
ok(sl.pausar("claude_cli", AHORA + 300, ahora=AHORA) is False,
   "con la perilla apagada, `pausar` no pone nada")
sl.pedir("claude_cli", ahora=AHORA)
ok(True, "y los turnos pasan como hoy")
sl.soltar("claude_cli")
# incluso si la pausa ya estaba puesta de antes, apagar la perilla la ignora
os.environ["PUPPET_CLI_PAUSA"] = "1"
sl.pausar("claude_cli", AHORA + 300, ahora=AHORA)
os.environ["PUPPET_CLI_PAUSA"] = "0"
try:
    sl.pedir("claude_cli", ahora=AHORA)
    ok(True, "una pausa YA PUESTA se ignora al apagar la perilla")
    sl.soltar("claude_cli")
except S.SinSlot:
    ok(False, "una pausa YA PUESTA se ignora al apagar la perilla")
os.environ["PUPPET_CLI_PAUSA"] = "1"
sl.reiniciar()
ok(sl.estado()["pausa_activa"] is True, "y el estado reporta si la perilla está puesta")

# el techo NO se apaga con la perilla: es el límite de procesos
os.environ["PUPPET_CLI_PAUSA"] = "0"
sl2 = S.Slots(limite=1)
sl2.pedir("claude_cli")
try:
    sl2.pedir("claude_cli")
    ok(False, "la perilla NO apaga el techo ni la serialización (son el límite de procesos)")
except S.SinSlot as e:
    ok(e.motivo == S.PROVIDER_OCUPADO,
       "la perilla NO apaga el techo ni la serialización (son el límite de procesos)")
os.environ["PUPPET_CLI_PAUSA"] = "1"

# ══ 4 · LA CAUSA TIPADA DEL RECHAZO ════════════════════════════════════════════════
seccion("4 · el N+1 recibe una causa del vocabulario cerrado")
# F1c · CAMBIO DE VEREDICTO DECLARADO: los DOS rechazos que son NUESTRO techo pasaron de
# `rate_limit` a `cli_ocupado`, la causa que F2b pidió acá mismo. `en_pausa` NO se movió, y
# ésa es la línea: `en_pausa` es un rechazo local derivado de un `rate_limit` previo,
# no una afirmación de cuota agotada en este instante.
for motivo, origen, con_retry, causa_esperada in (
        (S.PROVIDER_OCUPADO, "aleph", False, E.CLI_OCUPADO),
        (S.SIN_SLOTS, "aleph", False, E.CLI_OCUPADO),
        (S.EN_PAUSA, "aleph", True, E.RATE_LIMIT)):
    e = S.SinSlot(motivo, provider="claude_cli", activos=2, limite=2,
                  restante_s=180.0 if con_retry else None)
    c = S.causa_de(e, nombre_cli="Claude Code")
    ok(c and c["causa"] == causa_esperada and c["causa"] in E.CAUSAS,
       f"{motivo} → `{causa_esperada}`, del vocabulario cerrado",
       str(c and c["causa"]))
    ok(c and c["estado"] == E.ROTO, f"{motivo} → estado roto (contrato de _resultado)")
    ok(c and c["reintentable"] is True, f"{motivo} es reintentable")
    ok(c and c["evidencia"]["origen"] == origen,
       f"{motivo} → origen `{origen}` (nuestro techo vs la ventana del proveedor)",
       str(c and c["evidencia"]))
    if con_retry:
        ok(c and c["retry_after_s"] == 180.0,
           f"{motivo} lleva retry_after_s porque SÍ sabe cuándo", str(c and c["retry_after_s"]))
    else:
        ok(c and c["retry_after_s"] is None,
           f"{motivo} lleva retry_after_s=None: no sabe cuándo, y no lo inventa (None jamás 0)",
           str(c and c["retry_after_s"]))
c = S.causa_de(S.SinSlot(S.PROVIDER_OCUPADO, provider="claude_cli"), nombre_cli="Claude Code")
ok("Claude Code" in c["detalle"], "el detalle nombra el CLI del usuario, no el provider_id",
   c["detalle"])

# ══ 5 · EL SERVER: DOS REQUESTS SIMULTÁNEOS ════════════════════════════════════════
seccion("5 · server — dos simultáneos: uno corre, el otro recibe la causa")


def _post(puerto, modelo, marcador="x", stream=False, timeout=60):
    conn = http.client.HTTPConnection("127.0.0.1", puerto, timeout=timeout)
    payload = {"model": modelo, "stream": stream,
               "messages": [{"role": "user", "content": marcador}]}
    conn.request("POST", "/v1/chat/completions", json.dumps(payload),
                 {"Content-Type": "application/json", "Host": f"127.0.0.1:{puerto}"})
    r = conn.getresponse()
    cuerpo = r.read().decode("utf-8", "replace")
    conn.close()
    try:
        return r.status, json.loads(cuerpo)
    except Exception:                                   # noqa: BLE001
        return r.status, {"_crudo": cuerpo[:200]}


class _ProviderLento:
    """Ocupa el turno 1.5 s sin spawnear nada. Prueba el TECHO, no el CLI."""
    provider_id, display_name, response_model_id = "claude_cli", "Claude Code", "lab-lento"

    def invoke(self, prompt, model=None, effort=None, on_evento=None, timeout=None,
               chunk_timeout=None):
        time.sleep(1.5)
        return B.BrainResult(ok=True, text="listo", model_final="lab-real",
                             model_final_source="cli-reported",
                             usage={"prompt_tokens": 1, "completion_tokens": 1})


srv = create_server(0)
puerto = srv.server_port
threading.Thread(target=srv.serve_forever, daemon=True).start()
_guardado = dict(_detect._BY_MODEL_ID)
_guardado_cache = dict(_detect._cache)
try:
    S.SLOTS.reiniciar()
    # [obra 2] EL RECHAZO SE SIGUE MIDIENDO, CON LA ESPERA EN CERO. Desde obra 2 el camino
    # de producción hace cola antes de rechazar, así que sin fijar esto el N+1 esperaría y
    # contestaría 200 — y todo el contrato del rechazo (HTTP, `error_kind`, `CausaModelo`,
    # `provider_ocupado`) se quedaría sin medir. La cola se mide aparte, más abajo.
    S.ESPERA_TURNO_S = 0.0
    _detect._BY_MODEL_ID["lab-lento"] = _ProviderLento()
    # El fake no debe depender de la autenticación/keychain local ni consultar el CLI.
    # La prueba mide el ciclo HTTP + Slots con una sesión sintética ya autenticada.
    _detect._cache["claude_cli"] = B.BrainStatus(
        "claude_cli", B.STATE_READY, checked_at=time.time())
    res = {}

    def _tirar(k):
        res[k] = _post(puerto, "lab-lento", marcador=k)

    h1 = threading.Thread(target=_tirar, args=("a",))
    h2 = threading.Thread(target=_tirar, args=("b",))
    t0 = time.monotonic()
    h1.start()
    time.sleep(0.25)          # el segundo entra con el primero YA en vuelo
    h2.start()
    h1.join(timeout=30)
    h2.join(timeout=30)
    dt = time.monotonic() - t0

    codigos = sorted(v[0] for v in res.values())
    ok(codigos == [200, 429], f"uno corrió (200) y el otro fue rechazado (429)", str(codigos))
    ok(dt < 5, f"el rechazado NO esperó a que el primero terminara ({dt:.1f}s total)",
       f"{dt:.2f}s")
    rechazado = [v for v in res.values() if v[0] == 429][0][1]
    ok(rechazado["error"]["error_kind"] == B.ERR_RATE_LIMIT,
       "con el error_kind de siempre (el mapa HTTP no cambió)", str(rechazado["error"])[:90])
    causa = rechazado["error"].get("causa") or {}
    # F1c · la CAUSA cambió a `cli_ocupado`; el HTTP **no**. 429 «Too Many Requests» sigue
    # siendo lo correcto en el cable —mandaste más pedidos simultáneos de los que
    # atendemos— y `error_kind` es el contrato que F2b selló. Lo que cambia es lo que se
    # le dice a la persona, no lo que se le dice al cliente HTTP.
    ok(causa.get("causa") == E.CLI_OCUPADO and causa.get("estado") == E.ROTO,
       "y la CausaModelo tipada en el cuerpo (F1c: `cli_ocupado`, era `rate_limit`)",
       str(causa)[:110])
    ok(causa.get("evidencia", {}).get("motivo") == S.PROVIDER_OCUPADO,
       "que dice EXACTAMENTE por qué: provider_ocupado", str(causa.get("evidencia")))
    ok(causa.get("evidencia", {}).get("origen") == "aleph",
       "y que el que frenó fue NUESTRO techo, no el proveedor")
    ok(S.SLOTS.estado()["activos"] == 0, "y al final no quedó ningún turno colgado",
       str(S.SLOTS.estado()))

    # ── [obra 2] LA COLA: el N+1 espera y corre, en vez de rebotar ────────────────
    # EL DEFECTO QUE CIERRA, medido en Ciencia (binario `363d7ceb…`, dos turnos): las
    # llamadas al cerebro DE UN MISMO TURNO se solapan de a dos —arrancan con 10 ms de
    # diferencia—, así que el turno se pisaba a sí mismo. El N+1 rebotaba con `cli_ocupado`,
    # que estaba en `_ESCALABLES`, y el cascade terminaba contestándole al usuario con un
    # `qwen3:8b` local. El CLI no estaba caído: estaba ocupado 1,5 s.
    seccion("5.bis · el N+1 hace cola y corre — no rebota, y NO se solapa")
    S.SLOTS.reiniciar()
    S.ESPERA_TURNO_S = 10.0
    cola = {}

    def _tirar_cola(k):
        cola[k] = _post(puerto, "lab-lento", marcador=k)

    c1 = threading.Thread(target=_tirar_cola, args=("a",))
    c2 = threading.Thread(target=_tirar_cola, args=("b",))
    tc0 = time.monotonic()
    c1.start()
    time.sleep(0.25)          # el segundo entra con el primero YA en vuelo
    c2.start()
    c1.join(timeout=40)
    c2.join(timeout=40)
    dtc = time.monotonic() - tc0

    ok(sorted(v[0] for v in cola.values()) == [200, 200],
       "los DOS turnos corren (antes: uno 200 y el otro 429)",
       str(sorted(v[0] for v in cola.values())))
    # EL NO-SOLAPE, POR RELOJ. El provider ocupa 1,5 s; si los dos hubieran corrido a la
    # vez el total sería ~1,5 s. Serializados no puede bajar de 3,0 s. Es la misma
    # evidencia que el `ps` de §6 da con procesos reales, hecha con el reloj — y es lo que
    # prueba que esperar NO aflojó el techo, sólo cambió el rechazo por una cola.
    ok(dtc >= 3.0, f"y NO se solapan: {dtc:.2f}s ≥ 3,0 s (2 × 1,5 s serializados)",
       f"{dtc:.2f}s")
    ok(S.SLOTS.estado()["activos"] == 0, "sin turnos colgados después de la cola",
       str(S.SLOTS.estado()))

    # Y CUANDO LA ESPERA SE CUMPLE, EL RECHAZO SIGUE SIENDO EL DE SIEMPRE: esperar cambia
    # cuándo se rechaza, no cómo. Con un tope más corto que el turno, el N+1 vuelve a 429.
    S.SLOTS.reiniciar()
    S.ESPERA_TURNO_S = 0.3
    corto = {}

    def _tirar_corto(k):
        corto[k] = _post(puerto, "lab-lento", marcador=k)

    d1 = threading.Thread(target=_tirar_corto, args=("a",))
    d2 = threading.Thread(target=_tirar_corto, args=("b",))
    d1.start()
    time.sleep(0.25)
    d2.start()
    d1.join(timeout=40)
    d2.join(timeout=40)
    ok(sorted(v[0] for v in corto.values()) == [200, 429],
       "con el tope cumplido, el N+1 vuelve a rechazarse con 429",
       str(sorted(v[0] for v in corto.values())))
    _r = [v for v in corto.values() if v[0] == 429]
    _cz = ((_r[0][1].get("error") or {}).get("causa") or {}) if _r else {}
    ok(_cz.get("causa") == E.CLI_OCUPADO
       and _cz.get("evidencia", {}).get("motivo") == S.PROVIDER_OCUPADO,
       "con la MISMA causa tipada de siempre (`cli_ocupado`/`provider_ocupado`)",
       str(_cz.get("evidencia")))
    S.ESPERA_TURNO_S = 0.0

    # ── la pausa, de punta a punta por HTTP ───────────────────────────────────────
    seccion("5b · pausa con reset corto: rechaza tipado, y después pasa")
    S.SLOTS.reiniciar()
    S.SLOTS.registrar_rate_limit("claude_cli", retry_after_s=2.0,
                                 reset_hint="2 min", motivo="five_hour")
    st, cuerpo = _post(puerto, "lab-lento")
    ok(st == 429, "durante la pausa, el turno se rechaza con 429", str(st))
    c = (cuerpo.get("error") or {}).get("causa") or {}
    ok(c.get("evidencia", {}).get("motivo") == S.EN_PAUSA,
       "con motivo `en_pausa`", str(c.get("evidencia")))
    ok(c.get("evidencia", {}).get("origen") == "aleph"
       and c.get("runtime_state") == "local_cooldown_from_previous_limit"
       and c.get("quota_availability") == "unknown",
       "y distingue el cooldown local de la cuota viva")
    ok(c.get("evidencia", {}).get("provider_event", {}).get("reset_hint") == "2 min",
       "conserva el reset original del evento del proveedor")
    ok(c.get("retry_after_s") and 0 < c["retry_after_s"] <= 2.0,
       f"llevando el retry_after_s real ({c.get('retry_after_s')})", str(c.get("retry_after_s")))
    ok(cuerpo["error"].get("reset_hint"), "y un reset_hint legible", str(cuerpo["error"].get("reset_hint")))
    time.sleep(2.2)
    st2, cuerpo2 = _post(puerto, "lab-lento")
    ok(st2 == 200, "pasado el reset, el MISMO request pasa sin tocar nada", str(st2))
    ok(S.SLOTS.pausa_de("claude_cli") is None, "y la pausa se limpió sola")
    runtime = S.SLOTS.estado_provider("claude_cli")
    ok(runtime.get("last_execution_state") == "execution_verified_after_limit",
       "la ejecución exitosa verifica y supera el límite anterior",
       str(runtime.get("last_execution_state")))

    # ── con la perilla apagada, el comportamiento de hoy ──────────────────────────
    seccion("5c · con PUPPET_CLI_PAUSA=0, la pausa no frena nada")
    S.SLOTS.reiniciar()
    os.environ["PUPPET_CLI_PAUSA"] = "0"
    S.SLOTS._pausa["claude_cli"] = (time.time() + 300, "five_hour")   # pausa puesta a mano
    st3, _ = _post(puerto, "lab-lento")
    ok(st3 == 200, "el turno pasa aunque haya una pausa vigente", str(st3))
    os.environ["PUPPET_CLI_PAUSA"] = "1"
    S.SLOTS.reiniciar()

    # ══ 6 · EL CLI REAL: EVIDENCIA ps ══════════════════════════════════════════════
    seccion("6 · CLI REAL — evidencia `ps` de que JAMÁS hay dos `claude -p` vivos")
    if os.environ.get("SIN_CLI"):
        saltear("el par simultáneo contra el CLI real", "SIN_CLI=1")
    else:
        prov = ClaudeCliProvider()
        if not prov.binary():
            saltear("el par simultáneo contra el CLI real", "`claude` no está instalado")
        elif prov.detect().state != B.STATE_READY:
            saltear("el par simultáneo contra el CLI real", f"detect() = {prov.detect().state}")
        else:
            MARCA = "VARA-F2B-" + uuid.uuid4().hex[:10]
            _detect._BY_MODEL_ID["claude-code-cli"] = prov
            S.SLOTS.reiniciar()
            muestras = []
            parar = threading.Event()

            def _vigia():
                """Cuenta SÓLO los procesos de ESTA vara (por el marcador del prompt).
                Contar todos los `claude` de la máquina incluiría la sesión del operador."""
                while not parar.is_set():
                    try:
                        out = subprocess.run(["ps", "-eo", "pid=,command="],
                                             capture_output=True, text=True, timeout=5).stdout
                        n = sum(1 for l in out.splitlines() if MARCA in l and " -p " in l)
                        muestras.append(n)
                    except Exception:                   # noqa: BLE001
                        pass
                    time.sleep(0.15)

            hv = threading.Thread(target=_vigia, daemon=True)
            hv.start()
            reales = {}

            def _real(k):
                reales[k] = _post(puerto, "claude-code-cli",
                                  marcador=f"{MARCA} Responde exactamente: OK", timeout=180)

            # [obra 2] ACÁ LA ESPERA VA EN CERO, A PROPÓSITO. Lo que esta sección certifica
            # con evidencia de `ps` es el techo contra el CLI REAL, y con cola el segundo
            # turno esperaría y correría — gastando otro turno de la suscripción del usuario
            # para medir algo que la §5.bis ya mide con el reloj y sin gastar nada.
            S.ESPERA_TURNO_S = 0.0
            os.environ["PUPPET_CLAUDE_CLI_MODEL"] = os.environ.get("VARA_CLI_MODELO", "haiku")
            r1 = threading.Thread(target=_real, args=("a",))
            r2 = threading.Thread(target=_real, args=("b",))
            r1.start()
            time.sleep(0.8)                             # el segundo entra con el primero en vuelo
            r2.start()
            r1.join(timeout=200)
            r2.join(timeout=200)
            parar.set()
            hv.join(timeout=3)

            codigos = sorted(v[0] for v in reales.values())
            ok(codigos == [200, 429],
               f"uno corrió contra el CLI real (200) y el otro fue rechazado (429)", str(codigos))
            pico = max(muestras) if muestras else -1
            ok(muestras and pico == 1,
               f"EVIDENCIA ps: el pico de procesos `claude -p` de esta vara fue {pico} "
               f"(en {len(muestras)} muestras) — JAMÁS dos",
               f"muestras={muestras[:30]}")
            ok(sum(1 for m in muestras if m > 0) >= 2,
               "y el vigía llegó a ver el proceso vivo (la medición no es vacía)",
               f"muestras>0: {sum(1 for m in muestras if m > 0)}")
            rech = [v for v in reales.values() if v[0] == 429]
            if rech:
                cz = (rech[0][1].get("error") or {}).get("causa") or {}
                ok(cz.get("evidencia", {}).get("motivo") == S.PROVIDER_OCUPADO,
                   "el rechazado trae `provider_ocupado` tipado", str(cz.get("evidencia")))
            buenos = [v for v in reales.values() if v[0] == 200]
            if buenos:
                ok((buenos[0][1].get("choices") or [{}])[0].get("message", {}).get("content"),
                   "y el que corrió devolvió su respuesta normal",
                   str(buenos[0][1].get("choices"))[:80])
            ok(S.SLOTS.estado()["activos"] == 0, "sin turnos colgados al final",
               str(S.SLOTS.estado()))
finally:
    _detect._BY_MODEL_ID.clear()
    _detect._BY_MODEL_ID.update(_guardado)
    _detect._cache.clear()
    _detect._cache.update(_guardado_cache)
    S.SLOTS.reiniciar()
    os.environ.pop("PUPPET_CLI_PAUSA", None)
    srv.shutdown()
    srv.server_close()

# ══ 7 · LAS VARAS DE F1 Y F2a SIGUEN VERDES ════════════════════════════════════════
seccion("7 · verify_traductor y verify_cli_streaming siguen verdes")
for nombre, ruta in (("verify_traductor", _ASM / "verify_traductor.py"),
                     ("verify_cli_streaming", _AQUI / "verify_cli_streaming.py")):
    env = dict(os.environ)
    if os.environ.get("SIN_CLI"):
        env["SIN_CLI"] = "1"
    r = subprocess.run([sys.executable, str(ruta)], capture_output=True, text=True,
                       timeout=600, env=env)
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
