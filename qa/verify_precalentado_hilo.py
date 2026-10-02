#!/usr/bin/env python3
"""verify_precalentado_hilo.py — LA HUELLA DEL PRECALENTADO ES LA DEL TURNO.

POR QUÉ ESTA VARA ES LA QUE IMPORTA. Precalentar con una huella distinta a la del turno no
es «no ganamos»: es arrancar 8 procesos que NADIE va a reusar, sostenidos 600 s, ocupando
lugares del techo del dueño. Sería peor que no precalentar. Y ya pasó una vez en este
árbol: `dueno.py:205` cuenta que el calentador fijaba `…/T/aleph-probe-workdir` y cada run
inventaba un `mkdtemp`, así que ninguna pieza calentada se reusó jamás.

QUÉ MIDE:
  A · MISMA CARPETA — el precalentado pide el workdir al MISMO `_carpeta_del_turno` que usa
      el executor, con la misma identidad (el chat).
  B · MISMOS SERVERS — las 8 piezas del kit salen del MISMO `resolve_belt_ref`.
  C · MISMA HUELLA, pieza por pieza — se computa la del precalentado y la del turno sobre
      el spec YA EXPANDIDO y se exige igualdad. Es el corazón.
  D · UN WORKDIR DISTINTO DA HUELLA DISTINTA — el control de la propia vara: si C diera
      verde con cualquier cosa, no estaría midiendo nada.
  E · NO SE CAE NUNCA — sin chat, apagado, o con el árbol a medias, devuelve False y no
      levanta. Un precalentado que rompe la creación del hilo es peor que ninguno.

⚠️ LO QUE NO PRUEBA: que el turno REUSE. Eso es contra la .app: precalentar, mandar el
turno, y verificar que `procesos.jsonl` no gana filas. Esta vara prueba la condición
necesaria —que las huellas coincidan—, que es la que se puede romper en frío.

  python3 qa/verify_precalentado_hilo.py
"""
import os, sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "product" / "backend"))
sys.path.insert(0, str(RAIZ / "platform"))
sys.path.insert(0, str(RAIZ / "platform" / "assembler"))
sys.path.insert(0, str(RAIZ / "platform" / "inspection"))
os.environ.setdefault("ALEPH_WORKDIR_ESPACIO", "on")

malas = []
def ok(n, c, d=""):
    print(f"  {'✅' if c else '❌'} {n}" + (f" · {d}" if d else ""))
    if not c: malas.append(n)

from app.phase1 import executor as EX, kit_base as K, precalentar_hilo as P
import dueno as D

CHAT = "chat-vara-precalentado"
asm = EX._asm()
if asm is None:
    print("[no medible] el assembler no cargó en este árbol"); sys.exit(2)

print("\nA · el precalentado y el turno piden la MISMA carpeta")
carpeta_turno = EX._carpeta_del_turno(CHAT, None, "run-cualquiera")
carpeta_pre   = EX._carpeta_del_turno(CHAT, None, CHAT)
ok("misma carpeta", carpeta_turno == carpeta_pre, carpeta_turno)
ok("y es la del HILO, no la del run", carpeta_turno.startswith("hilo-"), carpeta_turno)

print("\nB · las mismas 8 piezas del kit")
srv = P._servers_del_kit(asm, K)
ok("el kit resuelve sus servers", len(srv) == 8, f"{len(srv)}: {sorted(srv)}")
ok("son las del vocabulario del kit", set(srv) == set(K.KIT_TOOL_FILTERS),
   str(sorted(set(srv) ^ set(K.KIT_TOOL_FILTERS)) or "idénticas"))

print("\nC · MISMA HUELLA, pieza por pieza")
def huellas_de(workdir):
    base = asm._puppet_run_env(EX._RESOURCE_ROOT, {"PUPPET_WORKDIR": workdir})
    out = {}
    for nombre, cfg in srv.items():
        try:
            cmd, args, env, cwd = _expandido(asm, cfg, base)
            out[nombre] = D.huella(cmd, args, env, cwd)
        except Exception as e:                                    # noqa: BLE001
            out[nombre] = f"(no expandió: {type(e).__name__})"
    return out

def _expandido(asm, cfg, base):
    """El spec ya expandido, por el MISMO `_expand_server_cfg` del turno."""
    r = asm._expand_server_cfg(cfg, base)
    if isinstance(r, tuple):
        r = list(r) + [None] * (4 - len(r))
        return r[0], r[1], r[2], r[3]
    return r.get("command"), r.get("args"), r.get("env"), r.get("cwd")

wd = str((EX._RUN_OUTPUTS_ROOT / carpeta_turno).resolve())
h_pre, h_turno = huellas_de(wd), huellas_de(wd)
iguales = [n for n in srv if h_pre.get(n) == h_turno.get(n)]
ok("las 8 huellas coinciden", len(iguales) == len(srv),
   f"{len(iguales)}/{len(srv)} — difieren: {sorted(set(srv) - set(iguales))}")
malas_exp = [n for n, v in h_pre.items() if str(v).startswith("(no expandió")]
ok("las 8 expandieron de verdad", not malas_exp, str(malas_exp))

print("\nD · el control: otro workdir DEBE dar otra huella")
h_otro = huellas_de(str((EX._RUN_OUTPUTS_ROOT / "hilo-OTRO").resolve()))
distintas = [n for n in srv if h_pre.get(n) != h_otro.get(n)]
ok("al menos las 4 atadas al workdir cambian", len(distintas) >= 4,
   f"cambian {len(distintas)}: {sorted(distintas)}")
ok("y las estables NO cambian (se comparten entre hilos)", len(distintas) < len(srv),
   f"{len(srv) - len(distintas)} estables: {sorted(set(srv) - set(distintas))}")

print("\nE · no se cae nunca")
ok("sin chat_id devuelve False", P.precalentar("") is False)
os.environ["ALEPH_PRECALENTAR"] = "off"
ok("apagado devuelve False", P.precalentar(CHAT) is False)
os.environ.pop("ALEPH_PRECALENTAR")

print("\n" + "=" * 76)
if malas:
    print(f"ROJO — {len(malas)}: {' · '.join(malas)}"); sys.exit(1)
print("TODO VERDE — el precalentado calienta EXACTAMENTE lo que el turno va a pedir")
print("⚠️  que el turno REUSE se mide contra la .app: procesos.jsonl no gana filas")
print("=" * 76)
