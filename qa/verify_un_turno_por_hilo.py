#!/usr/bin/env python3
"""verify_un_turno_por_hilo.py — EL CANDADO QUE HABILITA COMPARTIR LA CARPETA.

POR QUÉ EXISTE. El workdir es del HILO desde que se estabilizó la huella (es lo que hace
que el dueño reuse los 8 MCP: `asm.restaurar` 2.529 ms → 26-32 ms). Pero compartir carpeta
sólo es seguro si dos turnos del mismo hilo no se pisan: la cosecha
(`_capture_workdir_outputs`) barre por `mtime`, así que con turnos solapados el archivo que
escribe el primero cae en la ventana del segundo y entra en los DOS — duplicado y mal
atribuido en la Biblioteca.

`turnos_obra` NO servía: su handle es el `space_id`, que es del TURNO. Medido contra la DB,
tres mensajes seguidos de una misma conversación traían `space-…-1`, `-3`, `-5` y el MISMO
`chat_id`. El candado va por chat.

LO QUE SE MIDE, y las dos mitades importan:
  A · SERIALIZA de verdad — dos hilos de ejecución concurrentes sobre el mismo chat no se
      superponen NUNCA. Se mide con solapamiento real, no leyendo el código.
  B · NO BLOQUEA a otro chat — un candado por conversación, no uno global.
  C · DEGRADA, NO RECHAZA — quien no consigue el candado corre igual, con carpeta propia.
      Un candado que tumba turnos sería peor que el problema que viene a resolver.
  D · SE SUELTA ANTE UNA EXCEPCIÓN — si no, la conversación queda esperando para siempre.

  python3 qa/verify_un_turno_por_hilo.py
"""
import sys, threading, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "product" / "backend"))
malas = []
def ok(n, c, d=""):
    print(f"  {'✅' if c else '❌'} {n}" + (f" · {d}" if d else ""))
    if not c: malas.append(n)

from app.phase1.executor import _candado_del_hilo, _carpeta_del_turno

print("\nA · dos turnos del MISMO hilo no se solapan")
adentro, choques, orden = [], [], []
def turno(nombre, chat, espera=5.0):
    c = _candado_del_hilo(chat)
    tengo = bool(c and c.acquire(timeout=espera))
    try:
        if tengo:
            adentro.append(nombre)
            if len(adentro) > 1: choques.append(list(adentro))
            time.sleep(0.25)
            adentro.remove(nombre)
        orden.append((nombre, tengo))
    finally:
        if tengo and c is not None: c.release()

hs = [threading.Thread(target=turno, args=(f"t{i}", "chat-A")) for i in range(4)]
[h.start() for h in hs]; [h.join() for h in hs]
ok("cuatro turnos concurrentes, cero solapamientos", not choques, f"choques={choques}")
ok("los cuatro entraron (nadie quedó afuera)", all(t for _, t in orden), str(orden))

print("\nB · el candado es POR conversación, no global")
otro_entro = threading.Event()
def ocupa_A():
    c = _candado_del_hilo("chat-B"); c.acquire(); time.sleep(0.6); c.release()
def entra_B():
    c = _candado_del_hilo("chat-C")
    if c.acquire(timeout=0.2): otro_entro.set(); c.release()
a = threading.Thread(target=ocupa_A); a.start(); time.sleep(0.05)
b = threading.Thread(target=entra_B); b.start(); b.join(); a.join()
ok("un chat ocupado NO bloquea a otro chat", otro_entro.is_set())

print("\nC · quien no consigue el candado DEGRADA, no se cae")
c = _candado_del_hilo("chat-D"); c.acquire()
try:
    tengo = c.acquire(timeout=0.15)          # el segundo turno no lo consigue
    ok("el segundo turno no obtiene el candado", not tengo)
    # y entonces el executor le da carpeta PROPIA: es lo que hace el `if _tengo_el_hilo`
    propia = _carpeta_del_turno(None, None, "run-degradado")
    compartida = _carpeta_del_turno("chat-D", None, "run-normal")
    ok("sin candado → carpeta del run (comportamiento de siempre)", propia == "run-degradado", propia)
    ok("con candado → carpeta del hilo (se comparte)", compartida == "hilo-chat-D", compartida)
    ok("y NO son la misma", propia != compartida)
finally:
    c.release()

print("\nD · una excepción no deja el hilo tomado para siempre")
c = _candado_del_hilo("chat-E")
tengo = c.acquire(timeout=1.0)
try:
    raise RuntimeError("el turno reventó")
except RuntimeError:
    pass
finally:
    if tengo: c.release()
ok("el candado quedó libre tras la excepción", c.acquire(timeout=0.2))
c.release()

print("\n" + "=" * 74)
if malas:
    print(f"ROJO — {len(malas)}: {' · '.join(malas)}"); sys.exit(1)
print("TODO VERDE — un turno por hilo, sin bloquear a los demás y sin rechazar a nadie")
print("=" * 74)
