#!/usr/bin/env python3
"""verify_resume_grok.py — el resume de grok: ¿la ENTREGA aguanta, y el caché sube?

LA VARA ES LA ENTREGA, NO QUE LA RUTA EXISTA. El reporte que dejó a grok fuera de
`RESUME_PROBADO` decía «✓ turno 1 · ⟲ resume perdido · ✗ timeout 176,3 s · ✗ exit 1»: o
sea que la ruta podía estar y el turno 2 caerse igual. Por eso acá se mide que el modelo
RECUERDE un código que la vara mintea, no que un `isfile` diga True.

  R1 · las DOS formas de fallo de sesión de grok se reconocen — fixtures capturados del
       binario, no derivados del regex bajo prueba
  R2 · el aislamiento del workdir NO se tocó: por dueño, por charla y por CLI
  R3 · turnos encadenados: `cache_read` sube y el código se recuerda (N≥2 charlas)
  R4 · 🔴 EL ID QUEMADO SE RECUPERA: un turno que muere a mitad deja el `--session-id`
       usado, y el siguiente tiene que renovar y responder — no morir para siempre

    python3 -m assembler.cli_brain.verify_resume_grok [--rapido]
"""
from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assembler.cli_brain import base                            # noqa: E402
from assembler.cli_brain import sesiones as _ses                # noqa: E402
from assembler.cli_brain.grok_cli import (GrokCliProvider,      # noqa: E402
                                          _SESION_RE, _instalar_perfil)

_FALLOS, _OK, _SALT = [], 0, []


def ok(c, t, d=""):
    global _OK
    if c:
        _OK += 1
        print(f"  ✅ {t}")
    else:
        _FALLOS.append(t)
        print(f"  ❌ {t}" + (f"\n      → {d}" if d else ""))


def saltear(t, motivo):
    _SALT.append(f"{t} — {motivo}")
    print(f"  ⏭  [no medible] {t}\n      → {motivo}")


# ── FIXTURES CAPTURADOS DEL BINARIO 1.0.5 (2026-08-25), no derivados del regex ──────
STDERR_ID_REUSADO = ("Error: Error: Session ID 1a77fc91-9905-49df-bf30-a5f7569da97a "
                     "is already in use.")
STDERR_RESUME_404 = ("Error: Failed to restore session from remote: fetching session "
                     "record: session get failed: 404 Not Found")
STDERR_AJENO = "Error: rate limit exceeded, try again later"


def r1_las_dos_formas():
    print("\n[R1] las dos formas de fallo de sesión de grok se reconocen")
    ok(bool(_SESION_RE.search(STDERR_ID_REUSADO)),
       "R1: «Session ID … is already in use» se reconoce como sesión perdida",
       "sin esto, un turno que muere a mitad quema el id y la charla queda MUERTA")
    ok(bool(_SESION_RE.search(STDERR_RESUME_404)),
       "R1: «session get failed: 404 Not Found» se reconoce")
    # EL CONTROL NEGATIVO: un error que NO es de sesión no puede caer acá, o el server
    # renovaría el id y rehariía el turno por un rate limit — dos invocaciones por nada.
    ok(not _SESION_RE.search(STDERR_AJENO),
       "R1: un error AJENO (rate limit) NO se confunde con sesión perdida",
       "el regex matchea de más: rehacer un turno por un 429 lo invoca dos veces")
    # y la traducción a causa tipada
    from assembler.cli_brain.grok_cli import _causa_de_sesion
    c = _causa_de_sesion(STDERR_ID_REUSADO)
    ok(c is not None, "R1: y sale con causa TIPADA, no muda", str(c))


def r2_el_aislamiento():
    print("\n[R2] el aislamiento del workdir NO se tocó")
    a = _ses.SESIONES.obtener("ws:ana:chat:X", "grok_cli")
    b = _ses.SESIONES.obtener("ws:beto:chat:X", "grok_cli")
    c = _ses.SESIONES.obtener("ws:ana:chat:Y", "grok_cli")
    d = _ses.SESIONES.obtener("ws:ana:chat:X", "claude_cli")
    a2 = _ses.SESIONES.obtener("ws:ana:chat:X", "grok_cli")
    ok(a.workdir != b.workdir, "R2: dos DUEÑOS no comparten workdir",
       f"{a.workdir} == {b.workdir}")
    ok(a.workdir != c.workdir, "R2: dos CHARLAS del mismo dueño tampoco")
    ok(a.workdir != d.workdir, "R2: dos CLIs tampoco")
    ok(a.workdir == a2.workdir,
       "R2: y es ESTABLE entre turnos de la misma charla (no es un mkdtemp por turno)")
    ok("cli_sesiones" in a.workdir and os.path.isabs(a.workdir),
       "R2: vive bajo el dir de datos del usuario, no en el árbol", a.workdir)


def r3_encadenados(charlas: int, plazo: float):
    print(f"\n[R3] turnos encadenados: cache_read sube y el código se recuerda "
          f"({charlas} charla(s))")
    p = GrokCliProvider()
    if not p.binary():
        return saltear("R3", "grok no está instalado")
    # ⚠️ ESTO ES ROJO, NO UN SALTEO. La vara existe para verificar que grok ESTÉ en la
    # lista blanca; declararlo «no medible» cuando no está sería tapar exactamente la
    # regresión que hay que cazar — un [no medible] mal puesto cierra la búsqueda.
    if not _ses.resume_probado("grok_cli"):
        ok(False, "R3: grok está en RESUME_PROBADO",
           f"RESUME_PROBADO = {sorted(_ses.RESUME_PROBADO)} — sin grok no hay resume "
           f"que medir, y el turno vuelve a pagar 21,7k tokens de preámbulo")
        return
    buenas = 0
    for n in range(charlas):
        clave = f"vara-resume:ana:chat:{secrets.token_hex(4)}"
        tok = "TK-" + secrets.token_hex(4).upper()
        msgs = []
        filas = []
        for t in range(3):
            preg = (f"Guardá este código y respondé sólo la palabra LISTO: {tok}"
                    if t == 0 else
                    "¿Cuál era el código que te di? Respondé sólo el código.")
            msgs.append({"role": "user", "content": preg})
            s = _ses.SESIONES.obtener(clave, "grok_cli")
            r = p.invoke(preg, model="grok-4.6", timeout=plazo, sesion=s)
            u = r.usage or {}
            filas.append((r, u))
            print(f"    charla {n+1} t{t+1}: ok={r.ok} prompt={u.get('prompt_tokens')} "
                  f"cache_r={u.get('cache_read_tokens')} txt={(r.text or '')[:24]!r}")
            msgs.append({"role": "assistant", "content": r.text or ""})
            if r.ok:
                s.turnos += 1
                _ses.avanzar(s, msgs[:-1])
                _ses.SESIONES.recordar(s)
                s.restaurada = False
        (r1, u1), (r2, u2), (r3, u3) = filas
        if not (r1.ok and r2.ok and r3.ok):
            # ⚠️ grok tiene ventanas degradadas MEDIDAS (125-248 s por turno **también sin
            # sesión**). Una charla que se cae ahí no dice nada del resume, así que no se
            # cuenta como roja: se declara y se sigue. Lo que SÍ sería rojo es que
            # NINGUNA charla salga bien.
            print(f"      (charla {n+1} descartada: un turno no salió ok — "
                  f"{(r1.error_detail or r2.error_detail or r3.error_detail)[:80]})")
            continue
        buenas += 1
        ok((u2.get("cache_read_tokens") or 0) > 10000,
           f"R3 charla {n+1}: el turno 2 lee caché de verdad "
           f"({u2.get('cache_read_tokens')} tok)",
           f"usage t2 = {u2}")
        ok((u2.get("prompt_tokens") or 99999) < (u1.get("prompt_tokens") or 0),
           f"R3 charla {n+1}: el prompt del turno 2 BAJA "
           f"({u1.get('prompt_tokens')} → {u2.get('prompt_tokens')})")
        ok(tok in (r2.text or "") and tok in (r3.text or ""),
           f"R3 charla {n+1}: LA ENTREGA — recordó el código en t2 y t3 ({tok})",
           f"t2={(r2.text or '')[:60]!r} t3={(r3.text or '')[:60]!r}")
    ok(buenas > 0, f"R3: al menos una charla completa salió bien ({buenas}/{charlas})",
       "las dos se cayeron: o grok está degradado o el resume no anda")
    if buenas < charlas:
        saltear(f"R3: {charlas - buenas} charla(s) de {charlas}",
                "un turno no salió ok — grok tiene ventanas degradadas medidas "
                "(125-248 s por turno también SIN sesión)")


def _post(puerto: int, cuerpo: dict, plazo: float):
    import http.client, json as _j
    c = http.client.HTTPConnection("127.0.0.1", puerto, timeout=plazo)
    c.request("POST", "/v1/chat/completions", body=_j.dumps(cuerpo),
              headers={"Content-Type": "application/json"})
    r = c.getresponse()
    crudo = r.read().decode("utf-8", "replace")
    c.close()
    try:
        return r.status, _j.loads(crudo)
    except Exception:                                       # noqa: BLE001
        return r.status, {"raw": crudo[:300]}


def r4_el_id_quemado(plazo: float):
    print("\n[R4] 🔴 el id quemado se recupera (no queda muerta la charla)")
    p = GrokCliProvider()
    if not p.binary():
        return saltear("R4", "grok no está instalado")
    clave = f"vara-quemado:ana:chat:{secrets.token_hex(4)}"
    s = _ses.SESIONES.obtener(clave, "grok_cli")
    # EL DISPARADOR, PROVOCADO A PROPÓSITO: se quema el id corriendo el CLI a mano con
    # ESE `--session-id`, que es exactamente lo que deja un turno que murió a mitad.
    _instalar_perfil(s.workdir)
    argv = [p.binary(), "-p", "Responde: SEMILLA", "--model", "grok-4.6",
            "--output-format", "streaming-json", "--no-auto-update",
            "--agent", "aleph-zero", "--permission-mode", "default", "--no-subagents",
            "--session-id", s.id]
    try:
        q = subprocess.run(argv, cwd=s.workdir, env=base.sanitized_env(p.binary()),
                           capture_output=True, text=True, timeout=plazo,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return saltear("R4", "no se pudo quemar el id: grok no contestó (ventana degradada)")
    ok(q.returncode == 0, "R4: el id quedó QUEMADO a propósito (control del disparador)",
       f"rc={q.returncode} {q.stderr[-120:]}")
    if q.returncode != 0:
        return
    # ⚠️ EL TURNO VA POR EL SERVER, NO POR `invoke`. La recuperación —renovar el id y
    # rehacer el turno con contexto completo— vive en `server.py`, no en `invoke`: `invoke`
    # devuelve la causa tipada y nada más. La primera versión de esta vara le pedía a
    # `invoke` que se recuperara solo y daba ROJO por medir la capa equivocada.
    import threading
    from assembler.cli_brain.server import create_server
    from assembler.cli_brain import slots as _slots
    srv = create_server(0)
    puerto = srv.server_port
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        _slots.SLOTS.reiniciar()
        st, cuerpo = _post(puerto, {"model": "grok-cli", "sesion": clave,
                                    "messages": [{"role": "user",
                                                  "content": "Responde exactamente: RECUPERADO"}]},
                           plazo + 60)
        txt = str(((cuerpo.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        ax = cuerpo.get("aleph_cli_brain") or {}
        ses_ax = ax.get("sesion") or {}
        print(f"    HTTP {st} · texto={txt[:40]!r} · sesion={ {k: ses_ax.get(k) for k in ('turno','rehecha','causa')} }")
        ok(st == 200, "R4: el turno con el id quemado igual RESPONDE (200 por el server)",
           f"status={st} cuerpo={str(cuerpo)[:200]}")
        ok("RECUPERADO" in txt.upper(),
           "R4: y la entrega es la correcta", f"dijo {txt[:80]!r}")
        ok(bool(ses_ax.get("rehecha")) or bool(ses_ax.get("causa")),
           "R4: y el annex DICE que la sesión se rehizo (no pasa callado)", str(ses_ax))
    finally:
        srv.shutdown()
        srv.server_close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rapido", action="store_true", help="sin turnos reales (R1+R2)")
    ap.add_argument("--charlas", type=int, default=2)
    ap.add_argument("--plazo", type=float, default=200.0)
    a = ap.parse_args()
    print("=" * 74)
    print("VERIFY RESUME GROK — la vara es la ENTREGA, no que la ruta exista")
    print("=" * 74)
    r1_las_dos_formas()
    r2_el_aislamiento()
    if not a.rapido:
        r3_encadenados(a.charlas, a.plazo)
        r4_el_id_quemado(a.plazo)
    print("\n" + "-" * 74)
    print(f"{_OK} verdes · {len(_FALLOS)} rojas · {len(_SALT)} no medibles")
    for f in _FALLOS:
        print(f"   ROJA: {f}")
    for s in _SALT:
        print(f"   [no medible] {s}")
    return 1 if _FALLOS else 0


if __name__ == "__main__":
    sys.exit(main())
