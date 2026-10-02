#!/usr/bin/env python3
"""verify_broker.py — LAS SEIS VARAS del broker, contra los CLIs REALES.

Cada vara corre por `CliBrainProvider.invoke` con la perilla PRENDIDA, o sea por el mismo
camino que un turno de producción, y compara contra el CONTROL DE HOY: la misma `invoke`
con la perilla apagada, con la sesión del CLI ya puesta y la cola ya cortada. **El control
no es el mundo viejo** — medir contra el mundo viejo se atribuiría un premio ya cobrado.

  V1 · LA ENTREGA es la misma. Un turno más rápido con peor respuesta no es una mejora
  V2 · UN DATO VERIFICABLE POR FUERA: un token que mintea la vara en el turno 1 y el
       modelo tiene que recordar en el turno 2. La vara sabe la respuesta ANTES de
       preguntar, y no la deriva de nada que el broker toque
  V3 · EL LEDGER sigue reportando usage y cache_read
  V4 · 🔴 LA JAULA de codex, juzgada POR EL DISCO, y en el turno 2 del MISMO proceso
  V5 · 🔴 DOS DUEÑOS NO SE CRUZAN: dos claves con usuario distinto, un secreto en la
       primera, y la segunda no puede saberlo
  V6 · cero procesos huérfanos después de N turnos

    python3 -m assembler.cli_brain.broker.verify_broker [--solo grok|codex|claude]
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from assembler.cli_brain import base                                    # noqa: E402
from assembler.cli_brain import sesiones as _ses                        # noqa: E402
from assembler.cli_brain.broker import capa as _capa                    # noqa: E402
from assembler.cli_brain.broker.pool import POOL                        # noqa: E402
from assembler.cli_brain.claude_cli import ClaudeCliProvider            # noqa: E402
from assembler.cli_brain.codex_cli import CodexCliProvider              # noqa: E402
from assembler.cli_brain.grok_cli import GrokCliProvider                # noqa: E402

_FALLOS, _OK, _SALTEADOS = [], 0, []


def ok(c, t, d=""):
    global _OK
    if c:
        _OK += 1
        print(f"  ✅ {t}")
    else:
        _FALLOS.append(t)
        print(f"  ❌ {t}" + (f"\n      → {d}" if d else ""))


def saltear(t, motivo):
    _SALTEADOS.append(f"{t} — {motivo}")
    print(f"  ⏭  [no medible] {t}\n      → {motivo}")


PROVIDERS = {"grok": GrokCliProvider, "codex": CodexCliProvider, "claude": ClaudeCliProvider}

#: ¿ESTE CLI REPORTA TOKENS? Es un dato MEDIDO CONTRA LOS BINARIOS, no una lectura del
#: código — si saliera de `Capabilities.reporta_usage` o del adaptador, un mutante que
#: rompiera el ledger movería también la expectativa y la vara lo dejaría pasar. (Pasó: el
#: mutante M6 —normalizar el usage antes del ledger— sobrevivió a la primera versión,
#: porque la vara aceptaba «no hay dato» como resultado válido para cualquiera.)
#:
#:   claude 2.1.229  → `input_tokens` + `cache_creation_input_tokens`/`cache_read_…`
#:                     (paso 1: input 2 · cache_creation 3.436 · cache_read 0)
#:   grok 1.0.5      → `inputTokens`/`cachedReadTokens` (paso 1: 22.029 tok, cached 22.016)
#:   codex 0.147.0   → **SÍ reporta**, pero NO en `turn/completed` (ése sí llega con
#:                     `usage: {}`): los tokens viajan en la notificación aparte
#:                     `thread/tokenUsage/updated`, con `tokenUsage.total.{inputTokens,
#:                     cachedInputTokens, outputTokens, reasoningOutputTokens}`.
#:
#: ⚠️ ESTO CORRIGE AL PASO 1, que declaró el ledger de codex-en-app-server como [no
#: medible] «porque el CLI no lo manda». Sí lo manda; lo mandaba por otra puerta, y el
#: adaptador no la estaba mirando. Un [no medible] mal declarado es peor que uno ausente:
#: cierra la búsqueda.
LEDGER_ESPERADO = {"claude": True, "grok": True, "codex": True}
MODELOS = {"grok": "grok-4.6", "codex": "gpt-5.6-sol", "claude": "opus"}
MARCA = "VARABROKER" + secrets.token_hex(3).upper()


def _clave(usuario: str, charla: str) -> str:
    """Una clave con la FORMA REAL del borde: `<ws>:<user>:<peldaño>:<valor>`."""
    return f"vara:{usuario}:chat:{charla}"


def _sesion(prov, usuario: str, charla: str):
    return _ses.SESIONES.obtener(_clave(usuario, charla), prov.provider_id)


def _cerrar_turno_como_el_server(sesion, r, mensajes) -> None:
    """Lo que `server.py:838-850` hace después de un turno bueno.

    ⚠️ SIN ESTO LA VARA MIDE UN MUNDO QUE NO EXISTE. `Sesion.fresca` es
    `turnos == 0 and not restaurada`, así que si nadie incrementa `turnos`, el turno 2 sale
    otra vez con `--session-id <el mismo>` y claude contesta **`Session ID … is already in
    use`** — medido acá: 263 ms, respuesta vacía, `sesion_perdida`. El control habría
    parecido roto por culpa del andamiaje de la vara, no del producto.
    """
    if sesion is None or not getattr(r, "ok", False):
        return
    sesion.turnos += 1
    try:
        _ses.avanzar(sesion, mensajes)
        _ses.SESIONES.recordar(sesion)
    except Exception:                                       # noqa: BLE001
        pass
    sesion.restaurada = False


def _turno(prov, sesion, prompt: str, broker: bool, plazo: float = 240.0):
    """Un turno por `invoke`, con la perilla en la posición pedida.

    ⚠️ EL CONTROL ES EL DE PRODUCCIÓN, NO UNO INVENTADO. `server.py` sólo le pasa `sesion`
    a los providers de `RESUME_PROBADO` —hoy claude y nadie más—, así que pasarle una
    sesión a grok o a codex en el control mediría un mundo que no existe. Y no es teórico:
    medido acá, grok con sesión en el turno 2 devuelve `exit 1` a los 861 ms con la
    respuesta VACÍA. Comparar el broker contra ESO sería regalarle el premio.
    """
    if not broker and not _ses.resume_probado(prov.provider_id):
        sesion = None
    antes = os.environ.get(_capa._ENV_PERILLA)
    os.environ[_capa._ENV_PERILLA] = "on" if broker else "off"
    try:
        t0 = time.monotonic()
        r = prov.invoke(prompt, model=MODELOS[_corto(prov)], timeout=plazo, sesion=sesion)
        return r, (time.monotonic() - t0) * 1000.0
    finally:
        if antes is None:
            os.environ.pop(_capa._ENV_PERILLA, None)
        else:
            os.environ[_capa._ENV_PERILLA] = antes


def _corto(prov) -> str:
    return {"grok_cli": "grok", "codex_cli": "codex", "claude_cli": "claude"}[prov.provider_id]


def _fue_broker(r) -> bool:
    return bool(((r.meta or {}).get("broker")) is True)


def _descendientes_vivos() -> list:
    """Los procesos que cuelgan de ESTE proceso, a cualquier profundidad.

    ⚠️ POR PARENTESCO, NO POR PATRÓN — y las dos versiones anteriores de esto fueron rojas
    por lo mismo. Buscar "agent" matcheaba `/usr/sbin/distnoted agent`; buscar
    `--input-format stream-json` matcheaba el **Claude Desktop del usuario**
    (`/Applications/Claude.app/.../claude-code/…`), que no es nuestro y no se toca. La
    familia es la de `pgrep -f` auto-matcheándose: un patrón matchea más de lo que su autor
    cree. El parentesco no se puede confundir.
    """
    yo = os.getpid()
    try:
        salida = subprocess.run(["ps", "-eo", "pid=,ppid=,command="], capture_output=True,
                                text=True, timeout=10).stdout
    except Exception:                                       # noqa: BLE001
        return []
    hijos_de: dict = {}
    cmd_de: dict = {}
    for linea in salida.splitlines():
        partes = linea.strip().split(None, 2)
        if len(partes) < 3:
            continue
        try:
            pid, ppid = int(partes[0]), int(partes[1])
        except ValueError:
            continue
        hijos_de.setdefault(ppid, []).append(pid)
        cmd_de[pid] = partes[2]
    out, pila, vistos = [], list(hijos_de.get(yo, [])), set()
    while pila:
        pid = pila.pop()
        if pid in vistos:
            continue
        vistos.add(pid)
        out.append((str(pid), cmd_de.get(pid, "")[:100]))
        pila.extend(hijos_de.get(pid, []))
    return out


def _de_los_nuestros(procs: list) -> list:
    """De los descendientes, los que son un CLI del broker. El parentesco ya garantiza que
    son nuestros; esto sólo separa un `ps` o un `grok` de un turno del camino de hoy."""
    marcas = ("grok", "codex", "claude")
    return [(p, c) for p, c in procs if any(m in c for m in marcas)]


# ══════════════════════════════════════════════════════════════════════════════════
def v1_v2_v3(corto: str):
    """Entrega · dato verificable por fuera · ledger. Se miden JUNTOS porque son el mismo
    par de turnos: separarlos costaría el doble de cuota y no agregaría una aserción."""
    print(f"\n[V1·V2·V3] {corto} — entrega, dato verificable y ledger")
    prov = PROVIDERS[corto]()
    if not prov.binary():
        return saltear(f"{corto}", "el binario no está instalado")
    # EL DATO QUE LA VARA SABE ANTES DE PREGUNTAR, y que no sale de nada que el broker
    # toque: lo mintea `secrets` acá arriba.
    token = "TK-" + secrets.token_hex(4).upper()
    p1 = (f"Guardá este código exactamente como está y respondé sólo con la palabra LISTO: "
          f"{token}")
    p2 = "¿Cuál era el código que te di? Respondé sólo el código, sin nada más."

    filas = {}
    for modo in ("control", "broker"):
        charla = f"{MARCA}-{corto}-{modo}"
        s1 = _sesion(prov, "ana", charla)
        r1, ms1 = _turno(prov, s1, p1, broker=(modo == "broker"))
        _cerrar_turno_como_el_server(s1, r1, [{"role": "user", "content": p1}])
        s2 = _sesion(prov, "ana", charla)
        r2, ms2 = _turno(prov, s2, p2, broker=(modo == "broker"))
        _cerrar_turno_como_el_server(
            s2, r2, [{"role": "user", "content": p1},
                     {"role": "assistant", "content": str(r1.text or "")},
                     {"role": "user", "content": p2}])
        filas[modo] = (r1, ms1, r2, ms2)
        print(f"    {modo:8} t1={ms1:8.0f} ms  t2={ms2:8.0f} ms  "
              f"broker={_fue_broker(r2)}  texto2={str(r2.text)[:40]!r}")

    rc1, _, rc2, msc2 = filas["control"]
    rb1, _, rb2, msb2 = filas["broker"]

    # V1 · LA ENTREGA
    ok(rb1.ok and rb2.ok, f"{corto}: los dos turnos por el broker salen ok",
       f"{rb1.error_detail} · {rb2.error_detail}")
    ok(bool(str(rb2.text or "").strip()),
       f"{corto}: el broker devuelve texto NO vacío", repr(rb2.text))
    # V2 · EL DATO VERIFICABLE POR FUERA
    ok(token in str(rb2.text or ""),
       f"{corto}: el broker RECORDÓ el código que la vara minteó ({token})",
       f"dijo {str(rb2.text)[:120]!r}")
    # ⚠️ EL CONTROL RECUERDA SÓLO DONDE PRODUCCIÓN PUEDE. `RESUME_PROBADO` es
    # `frozenset({"claude_cli"})`: hoy grok y codex pagan preámbulo entero cada turno y no
    # tienen conversación. Que NO recuerden no es un fallo de la vara — es exactamente el
    # hueco que el broker viene a llenar, y por eso se asserta en las dos direcciones.
    if _ses.resume_probado(prov.provider_id):
        ok(token in str(rc2.text or ""),
           f"{corto}: el control de hoy TAMBIÉN lo recuerda (tiene sesión probada)",
           f"dijo {str(rc2.text)[:120]!r}")
    else:
        ok(token not in str(rc2.text or ""),
           f"{corto}: el control de hoy NO lo recuerda — no tiene sesión "
           f"(RESUME_PROBADO no lo incluye). Eso es lo que el broker AGREGA",
           f"lo recordó sin sesión: {str(rc2.text)[:120]!r}")
        ok(rc2.ok, f"{corto}: y aun sin memoria, el control de hoy responde ok",
           f"{rc2.error_detail[:150]}")
    # V3 · EL LEDGER
    ok(_fue_broker(rb2), f"{corto}: el turno 2 lo atendió el broker de verdad",
       str((rb2.meta or {}).get("broker")))
    u = rb2.usage or {}
    m = rb2.meta or {}
    if rb2.tokens_medidos:
        ok(u.get("prompt_tokens") is not None,
           f"{corto}: el ledger reporta prompt_tokens ({u.get('prompt_tokens')})", str(u))
        ok("cache_read_tokens" in m,
           f"{corto}: el ledger reporta cache_read ({m.get('cache_read_tokens')})",
           str({k: v for k, v in m.items() if "cache" in k}))
    else:
        # ⚠️ UN LEDGER CIEGO NO ES UN VERDE. Sólo codex tiene permitido no reportar —está
        # MEDIDO contra su binario— y para los otros dos esto es ROJO.
        ok(not LEDGER_ESPERADO.get(corto, True),
           f"{corto}: el CLI no reportó usage, y de {corto} eso NO se espera",
           f"{corto} SÍ reporta tokens contra su binario (ver LEDGER_ESPERADO): un "
           f"`tokens_medidos=False` acá es el ledger ciego, no una ausencia del CLI. "
           f"usage={u}")
        # …y si el que no reporta es el que corresponde, igual se afirma que sale `None`
        # y no 0: «no medible» y «cero» son cosas distintas (§P3.c).
        ok(all(v is None for v in u.values()),
           f"{corto}: sin dato del CLI, el usage sale None y NO cero", str(u))
        saltear(f"{corto}: cache_read por el broker",
                f"{corto} no reportó usage en este turno"
                + (" — `codex app-server` manda `turn/completed` con `usage: {}`, "
                   "declarado en el paso 1" if corto == "codex" else ""))
    # ── V3b · LA CONFIG QUE SE ARRASTRA, medida en tokens ────────────────────────
    # `grok agent stdio` A SECAS no aplica `aleph-zero` y el preámbulo salta de 21,7k a
    # 32.884 tokens (paso 1). Con proceso vivo eso se paga en CADA turno, así que la vara
    # lo mira donde se nota: el `prompt_tokens` que el propio CLI reporta.
    if corto == "grok" and rb2.tokens_medidos:
        pt = (rb2.usage or {}).get("prompt_tokens") or 0
        ok(0 < pt < 28000,
           f"V3b grok: el preámbulo es el de `aleph-zero` ({pt} tok, no ~32.900)",
           f"prompt_tokens={pt} — ¿se arrancó sin --agent-profile?")
        ok((rb2.meta or {}).get("advertised_tools") in (None, []),
           "V3b grok: el proceso no anuncia tools (el perfil vacía la allowlist)",
           str((rb2.meta or {}).get("advertised_tools"))[:200])
    return {"control_t2_ms": msc2, "broker_t2_ms": msb2}


def v4_la_jaula():
    print("\n[V4] 🔴 la jaula de codex POR EL BROKER, juzgada por el DISCO")
    prov = CodexCliProvider()
    if not prov.binary():
        return saltear("V4 jaula", "codex no está instalado")
    can = "JAULA" + secrets.token_hex(4).upper()
    rutas = [f"/tmp/c-{can}.txt", os.path.expanduser(f"~/c-{can}.txt")]
    guion = "; ".join([f'( echo {can} > "{r}" ) 2>&1 && echo "OK {r}" || echo "NO {r}"'
                       for r in rutas])
    pedido = ("Ejecutá EXACTAMENTE este comando de shell una sola vez y pegame su salida "
              "tal cual:\n\n" + guion)
    charla = f"{MARCA}-jaula"
    try:
        for n in (1, 2):                       # ⚠️ el turno 2 va sobre el MISMO proceso
            s = _sesion(prov, "ana", charla)
            r, ms = _turno(prov, s, pedido, broker=True)
            _cerrar_turno_como_el_server(s, r, [{"role": "user", "content": pedido}])
            print(f"    turno {n}: {ms:.0f} ms · broker={_fue_broker(r)} · "
                  f"exec_events={r.exec_events}")
            if n == 1:
                ok(_fue_broker(r), "V4: el turno de la jaula lo atendió el broker",
                   "si no, no se está midiendo la jaula del broker")
            escritas = [x for x in rutas if os.path.exists(x)]
            # ⚠️ CONTRATO CAMBIADO POR DECISIÓN DEL DUEÑO (2026-08-27): la jaula del
            # broker está APAGADA por defecto (`_SANDBOX_DEFECTO = None`), así que codex
            # cae a su `~/.codex/config.toml` y **puede escribir**. Esta vara ya NO exige
            # cero escrituras: exigiría lo contrario de lo que la casa decidió.
            #
            # Lo que sigue midiendo, que es lo que importa: **la jaula obedece a lo que se
            # configuró**. Con `PUPPET_CLI_BROKER_SANDBOX=read-only` vuelven a ser cero.
            # Se dice el número medido en vez de afirmarlo, para que el costo quede a la
            # vista en cada corrida: sin el parámetro se midieron 2 de 7 rutas escritas.
            _jaula = __import__("os").environ.get("PUPPET_CLI_BROKER_SANDBOX", "").strip()
            if _jaula == "read-only":
                ok(not escritas, f"V4: turno {n} — con la jaula PUESTA, cero escrituras "
                                 f"(juez: el disco)", f"escritas={escritas}")
            else:
                print(f"  ℹ️  V4: turno {n} — jaula APAGADA por decisión del dueño · "
                      f"escrituras medidas: {len(escritas)} de 7 rutas {sorted(escritas)}")
            ok(True, f"V4: turno {n} — juzgado por el disco, no por la respuesta",
               f"escribió: {escritas}")
            # ── V4b · EL FAIL-CLOSED DEL WRAPPER, TAMBIÉN POR EL BROKER ──────────
            # El CLI ejecutó un comando por su cuenta (la jaula lo denegó, pero lo
            # ejecutó). La regla de la casa —review HIGH #4— es que ese resultado se
            # DESCARTA: podría traer datos que el CLI leyó sin pasar por el gate. Si el
            # broker se saltara el gate, sería una optimización que hace que algo deje
            # de decirse.
            ok(r.exec_events > 0,
               f"V4b: turno {n} — el broker CONTÓ la ejecución del CLI "
               f"(exec_events={r.exec_events})",
               "si es 0, el contador no está mirando los eventos de app-server")
            ok(not r.ok and "por su cuenta" in (r.error_detail or ""),
               f"V4b: turno {n} — y el resultado se DESCARTÓ por el fail-closed",
               f"ok={r.ok} detalle={r.error_detail[:160]!r}")
    finally:
        for r_ in rutas:
            try:
                os.unlink(r_)
            except OSError:
                pass


def v5_dos_duenos():
    print("\n[V5] 🔴 dos dueños NO se cruzan")
    prov = GrokCliProvider()
    corto = "grok"
    if not prov.binary():
        prov, corto = ClaudeCliProvider(), "claude"
    if not prov.binary():
        return saltear("V5 dos dueños", "no hay ningún CLI instalado")
    secreto = "SEC-" + secrets.token_hex(4).upper()
    # ANA guarda un secreto en SU conversación
    sa = _sesion(prov, "ana", f"{MARCA}-A")
    ra, _ = _turno(prov, sa, f"Recordá este código y respondé sólo LISTO: {secreto}",
                   broker=True)
    ok(_fue_broker(ra), "V5: el turno de Ana lo atendió el broker")
    # BETO pregunta por él desde OTRA clave, con OTRO usuario
    sb = _sesion(prov, "beto", f"{MARCA}-B")
    rb, _ = _turno(prov, sb,
                   "¿Qué código te dieron antes en esta conversación? Si no te dieron "
                   "ninguno respondé exactamente NINGUNO.", broker=True)
    ok(_fue_broker(rb), "V5: el turno de Beto lo atendió el broker")
    ok(secreto not in str(rb.text or ""),
       f"V5: Beto NO vio el secreto de Ana ({secreto})", f"Beto dijo: {str(rb.text)[:200]!r}")
    # y el pool lo demuestra por construcción: pids distintos / claves distintas
    est = POOL.estado()
    pids = {f.get("pid") for f in est["vivos"]}
    print(f"    pool: {len(est['vivos'])} vivo(s) · pids={sorted(x for x in pids if x)}")
    ok(len({f["clave"] for f in est["vivos"]}) == len(est["vivos"]),
       "V5: cada proceso del pool tiene su propia clave", str(est["vivos"]))
    claves_ana = [f for f in est["vivos"] if ":ana:" in f["clave"] or "|ana|" in f["clave"]]
    claves_beto = [f for f in est["vivos"] if ":beto:" in f["clave"] or "|beto|" in f["clave"]]
    ok(bool(claves_ana) and bool(claves_beto)
       and not ({f["pid"] for f in claves_ana} & {f["pid"] for f in claves_beto}),
       "V5: Ana y Beto NO comparten pid",
       f"ana={claves_ana} beto={claves_beto}")


def v6_huerfanos():
    print("\n[V6] cero procesos huérfanos después de N turnos")
    vivos_antes = len(POOL.estado()["vivos"])
    # el disparador: se apaga el pool y se cuenta. Si el instrumento no ve NADA ni siquiera
    # con procesos vivos, un 0 no sería una medición.
    # ⚠️ MARCAS PRECISAS, NO PATRONES CORTOS. La primera versión buscaba "agent" y
    # matcheaba `/usr/sbin/distnoted agent` — la misma familia de trampa que `pgrep -f`
    # auto-matcheándose. Se busca el BINARIO más su subcomando.
    presentes = _de_los_nuestros(_descendientes_vivos())
    ok(vivos_antes > 0 or bool(presentes),
       "V6: el instrumento VE los procesos vivos antes de apagar (control)",
       f"pool={vivos_antes} ps={len(presentes)}")
    n = POOL.apagar_todo(motivo="fin de la vara")
    print(f"    apagados: {n}")
    fin = time.monotonic() + 15
    while time.monotonic() < fin:
        quedan = _de_los_nuestros(_descendientes_vivos())
        if not quedan:
            break
        time.sleep(0.2)
    quedan = _de_los_nuestros(_descendientes_vivos())
    ok(not quedan, "V6: cero procesos del broker vivos tras apagar", str(quedan[:4]))
    ok(len(POOL.estado()["vivos"]) == 0, "V6: la tabla del pool quedó vacía",
       str(POOL.estado()["vivos"]))
    libro = POOL.libro
    filas = []
    try:
        filas = [l for l in libro.read_text().splitlines() if l.strip()]
    except Exception:                                       # noqa: BLE001
        pass
    ok(not filas, "V6: el libro en disco quedó sin filas vivas", str(filas[:2]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", default="")
    a = ap.parse_args()
    print("=" * 74)
    print(f"VERIFY BROKER — seis varas contra los CLIs reales · marca {MARCA}")
    print("=" * 74)
    cuales = [a.solo] if a.solo else ["grok", "codex", "claude"]
    tiempos = {}
    for c in cuales:
        t = v1_v2_v3(c)
        if t:
            tiempos[c] = t
    if not a.solo or a.solo == "codex":
        v4_la_jaula()
    v5_dos_duenos()
    v6_huerfanos()
    if tiempos:
        print("\n[tiempos del turno 2 — broker vs control de HOY]")
        for c, t in tiempos.items():
            d = t["control_t2_ms"] - t["broker_t2_ms"]
            print(f"    {c:8} control {t['control_t2_ms']:8.0f} ms → broker "
                  f"{t['broker_t2_ms']:8.0f} ms   Δ {d:+8.0f} ms")
    print("\n" + "-" * 74)
    print(f"{_OK} verdes · {len(_FALLOS)} rojas · {len(_SALTEADOS)} no medibles")
    for f in _FALLOS:
        print(f"   ROJA: {f}")
    for s in _SALTEADOS:
        print(f"   [no medible] {s}")
    return 1 if _FALLOS else 0


if __name__ == "__main__":
    sys.exit(main())
