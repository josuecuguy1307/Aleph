#!/usr/bin/env python3
"""verify_destino_y_memoria.py — EL APLICADOR ÚNICO Y LA MEMORIA POR-WORKSPACE.
[Gate 4 · Fase 4 · obra O5 · obras 4.4 y 4.5 · ley 6 · ley 5 · ley técnica 4]

QUÉ AFIRMA — la vara de la fase, literal
----------------------------------------
«Las tres señales (cinturón · artefacto · preferencia) terminan en el MISMO aplicador» y
«volver a un workspace lo devuelve como quedó (memoria por-workspace de deltas, clave de
dominio)».

  A · **Un solo aplicador, y la precedencia de la ley 6**: la preferencia manda sobre el
      artefacto · el artefacto elige cuando lo reclama uno solo · dos que lo reclaman es
      AMBIGÜEDAD, y la ambigüedad se resuelve con **una línea en el chat**, jamás con una
      galería · lo que nadie reclama **cae al suelo** (La Sala), que no es un estado roto.
  B · **El cinturón SUGIERE, jamás condiciona**: cambia el ORDEN de los candidatos y nunca
      el conjunto. Se mide con el mismo caso, con y sin sugerencia.
  C · **Clave de dominio, no de UI**: DOS cuentas en la MISMA máquina no se ven la memoria.
      Lo que había era `localStorage["aleph_ws_chat_ciencia"]` — la deuda D1 — y compartía
      el hilo entre cuentas.
  D · **Volver devuelve como quedó**, y guardar es un MERGE: una pantalla que sólo sabe el
      hilo no puede borrarle la sesión de obras a otra que sólo sabe eso.
  E · **Fail-closed**: sin sesión no hay memoria de nadie (401), y la de otro es 403.

Se mide en los dos planos a propósito: el aplicador **por tabla** (es una decisión pura, y
probarla con casos es más fuerte que levantar medio producto para cada rama) y la memoria
**por HTTP con dos cuentas reales**, porque el aislamiento entre dueños sólo vale si se
mide donde de verdad ocurre.

PROBADA CAYENDO
---------------
  --caer sin-preferencia  → el aplicador ignora la preferencia grabada: cae A.
  --caer cinturon-filtra  → el cinturón saca candidatos en vez de ordenarlos: cae B.
  --caer memoria-global   → la memoria se guarda sin dueño (como el localStorage viejo):
                            cae C.

    python3 qa/verify_destino_y_memoria.py
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "platform"))

CAER = ""
for i, a in enumerate(sys.argv):
    if a == "--caer" and i + 1 < len(sys.argv):
        CAER = sys.argv[i + 1]

fallos: list[str] = []


def ok(cond: bool, etiqueta: str, extra: str = "") -> None:
    print(f"{'✓' if cond else '✗'} {etiqueta}{('  ' + extra) if extra else ''}", flush=True)
    if not cond:
        fallos.append(etiqueta)


def puerto_libre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = int(s.getsockname()[1])
    s.close()
    return p


def python_del_backend() -> str:
    for c in [RAIZ / "product/backend/.venv/bin/python"]:
        if c.is_file():
            return str(c)
    print("✗ no encontré el venv del backend", file=sys.stderr)
    sys.exit(2)


def pedir(url, metodo="GET", cuerpo=None, token=None, timeout=30.0):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    cab = {"Content-Type": "application/json"}
    if token:
        cab["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=datos, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:                                   # noqa: BLE001
            return e.code, None


# ── PARTE A/B · EL APLICADOR, POR TABLA ─────────────────────────────────────────────

def parte_aplicador() -> None:
    from workspaces import destino as D

    CIENCIA = {"id": "ciencia", "label": "Ciencia", "accepts": ["informe", "imagen", "planilla"]}
    OFICINA = {"id": "oficina", "label": "Oficina", "accepts": ["informe", "planilla"]}
    prefs = {"informe": "oficina"}
    if CAER == "sin-preferencia":
        prefs = {}

    print("\n── A · la precedencia de la ley 6 ──")
    r = D.decidir(disponibles=[CIENCIA, OFICINA], tipo="informe", preferencias=prefs)
    ok(r["destino"] == "oficina" and r["motivo"] == "preferencia",
       "LA PREFERENCIA MANDA sobre el artefacto (4.5: grabada → auto)",
       f"{r['destino']} · {r['motivo']}")
    ok(bool(r["copy"]) and "Oficina" in r["copy"],
       "y viene con su copy ya redactado, no con un código", r["copy"])

    r = D.decidir(disponibles=[CIENCIA, OFICINA], tipo="imagen", preferencias=prefs)
    ok(r["destino"] == "ciencia" and r["motivo"] == "artefacto",
       "un tipo que reclama UNO SOLO decide sin preguntar", f"{r['destino']} · {r['motivo']}")

    r = D.decidir(disponibles=[CIENCIA, OFICINA], tipo="planilla", preferencias={})
    ok(r["destino"] is None and r["motivo"] == "ambiguo",
       "dos que lo reclaman y sin preferencia = AMBIGÜEDAD, no una elección nuestra")
    ok(isinstance(r["pregunta"], str) and "?" in r["pregunta"] and len(r["pregunta"]) < 160,
       "la ambigüedad se resuelve con UNA LÍNEA en el chat, jamás con una galería",
       f"«{r['pregunta']}»")
    ok(len(r["candidatos"]) == 2 and all(c.get("por_que") for c in r["candidatos"]),
       "y cada candidato dice POR QUÉ está en la lista")

    r = D.decidir(disponibles=[CIENCIA, OFICINA], tipo="cad", preferencias={})
    ok(r["destino"] is None and r["motivo"] == "nadie_lo_reclama",
       "lo que nadie reclama CAE AL SUELO (ley 4), no a un error", r["motivo"])

    r = D.decidir(disponibles=[], tipo="informe", preferencias={})
    ok(r["destino"] is None and r["motivo"] == "sin_workspaces",
       "sin workspaces instalados lo dice, no inventa uno")

    r = D.decidir(disponibles=[CIENCIA], tipo=None, preferencias={})
    ok(r["destino"] == "ciencia" and r["motivo"] == "unico_disponible",
       "con uno solo instalado y sin artefacto, la respuesta es obvia y se da")

    print("\n── B · el cinturón sugiere, jamás condiciona ──")
    sin = D.decidir(disponibles=[CIENCIA, OFICINA], tipo="planilla", preferencias={})
    con = D.decidir(disponibles=[CIENCIA, OFICINA], tipo="planilla", preferencias={},
                    sugerencias=(["ciencia"] if CAER != "cinturon-filtra" else []))
    if CAER == "cinturon-filtra":
        # El sabotaje: el cinturón FILTRA (deja sólo lo sugerido) en vez de ordenar.
        con = D.decidir(disponibles=[CIENCIA], tipo="planilla", preferencias={})
    ids_sin = sorted(c["id"] for c in sin["candidatos"])
    ids_con = sorted(c["id"] for c in con["candidatos"])
    ok(ids_sin == ids_con,
       "el cinturón NO cambia el conjunto de candidatos", f"{ids_sin} vs {ids_con}")
    ok(con["candidatos"][0]["id"] == "ciencia" if ids_con == ids_sin else False,
       "pero SÍ los ordena: lo que el cinturón ya trabaja va primero",
       json.dumps([c["id"] for c in con["candidatos"]]))


# ── PARTE C/D/E · LA MEMORIA, POR HTTP, CON DOS CUENTAS REALES ──────────────────────

def parte_memoria() -> None:
    datos = Path(tempfile.mkdtemp(prefix="f4-memoria-"))
    puerto = puerto_libre()
    base = f"http://127.0.0.1:{puerto}"
    proc = subprocess.Popen(
        [python_del_backend(), "-m", "uvicorn", "app.main:app",
         "--app-dir", str(RAIZ / "product/backend"),
         "--host", "127.0.0.1", "--port", str(puerto)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        env={**os.environ, "ALEPH_DATA_DIR": str(datos), "ALEPH_ROLE": "client",
             "ALEPH_ENV": "dev", "PUPPET_ALLOW_PASSWORD_AUTH": "1"})
    try:
        vivo = False
        for _ in range(60):
            time.sleep(1)
            try:
                urllib.request.urlopen(base + "/health", timeout=2)
                vivo = True
                break
            except Exception:                               # noqa: BLE001
                pass
        print("\n── C/D/E · la memoria, con dos cuentas en la misma máquina ──")
        ok(vivo, "el backend real está en pie", base)
        if not vivo:
            return

        def registrar(tag):
            st, u = pedir(base + "/v1/auth/register", "POST", {
                "email": f"f4-{tag}-{uuid.uuid4().hex[:8]}@puppet.local",
                "password": "vara-f4-memoria", "display_name": f"F4 {tag}"})
            assert st == 201 and u and u.get("session_token"), f"register {tag}: {st}"
            return u

        ana, beto = registrar("ana"), registrar("beto")
        ok(ana["id"] != beto["id"], "hay dos cuentas distintas en la misma instalación")

        # ── E · FAIL-CLOSED, ANTES QUE NADA ──────────────────────────────────────────
        st, _ = pedir(f"{base}/v1/workspaces/ciencia/memoria?user_id={ana['id']}")
        ok(st == 401, "sin sesión, la memoria de un workspace NO se lee", f"({st})")
        st, _ = pedir(f"{base}/v1/workspaces/ciencia/memoria?user_id={beto['id']}",
                      token=ana["session_token"])
        ok(st == 403, "y la memoria de OTRA cuenta tampoco", f"({st})")

        # ── C · CLAVE DE DOMINIO ─────────────────────────────────────────────────────
        st, r = pedir(f"{base}/v1/workspaces/ciencia/memoria", "PUT",
                      {"user_id": ana["id"], "chat_id": "chat-de-ana", "sid": "sid-de-ana"},
                      token=ana["session_token"])
        ok(st == 200 and r["memoria"]["chat_id"] == "chat-de-ana",
           "Ana entra a Ciencia y su hilo queda guardado", json.dumps(r.get("memoria")))

        st, r = pedir(f"{base}/v1/workspaces/ciencia/memoria?user_id={beto['id']}",
                      token=beto["session_token"])
        vista_beto = (r or {}).get("memoria") or {}
        if CAER == "memoria-global":
            # EL SABOTAJE ES LA CLAVE VIEJA, ESCRIBIENDO Y LEYENDO. La primera versión de
            # esta falsificación sólo LEÍA con una clave de instalación con la que nadie
            # había escrito: daba `{}` y la vara pasaba «probando» que el aislamiento existe.
            # Para reproducir el `localStorage["aleph_ws_chat_ciencia"]` hay que guardar
            # ahí también — que es exactamente lo que hacía la pantalla vieja.
            from workspaces import memoria as M
            M.recordar("la-instalacion", "ciencia", chat_id="chat-de-ana")
            vista_beto = M.como_quedo("la-instalacion", "ciencia") or {}
        ok(st == 200 and vista_beto == {},
           "BETO NO VE EL HILO DE ANA — la clave es de dominio, no de la máquina",
           json.dumps(vista_beto))

        # ── D · VOLVER DEVUELVE COMO QUEDÓ, Y GUARDAR ES UN MERGE ────────────────────
        st, r = pedir(f"{base}/v1/workspaces/ciencia/memoria?user_id={ana['id']}",
                      token=ana["session_token"])
        ok(r["memoria"].get("chat_id") == "chat-de-ana" and r["memoria"].get("sid") == "sid-de-ana",
           "Ana vuelve y encuentra su workspace como lo dejó", json.dumps(r["memoria"]))

        st, r = pedir(f"{base}/v1/workspaces/ciencia/memoria", "PUT",
                      {"user_id": ana["id"], "deltas": {"panel": "abierto"}},
                      token=ana["session_token"])
        m = r["memoria"]
        ok(m.get("chat_id") == "chat-de-ana" and m.get("deltas", {}).get("panel") == "abierto",
           "guardar un delta NO borra lo que otra pantalla había guardado (es MERGE)",
           json.dumps(m))

        # ── LA PREFERENCIA, Y QUE EL APLICADOR LA LEA POR HTTP ───────────────────────
        st, r = pedir(f"{base}/v1/workspaces/preferencia", "PUT",
                      {"user_id": ana["id"], "tipo": "informe", "workspace": "ciencia"},
                      token=ana["session_token"])
        ok(st == 200 and r["preferencias"].get("informe") == "ciencia",
           "la preferencia se graba", json.dumps(r.get("preferencias")))
        st, d = pedir(f"{base}/v1/workspaces/destino?tipo=informe&user_id={ana['id']}",
                      token=ana["session_token"])
        ok(st == 200 and d.get("motivo") == "preferencia" and d.get("destino") == "ciencia",
           "y el APLICADOR la usa: una sola respuesta para el selector, la tarjeta y el agente",
           json.dumps({k: d.get(k) for k in ("destino", "motivo")}))
        st, d2 = pedir(f"{base}/v1/workspaces/destino?tipo=informe&user_id={beto['id']}",
                       token=beto["session_token"])
        ok(d2.get("motivo") != "preferencia",
           "la preferencia de Ana NO decide por Beto", json.dumps({"motivo": d2.get("motivo")}))
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), 15)
            proc.wait(timeout=8)
        except Exception:                                   # noqa: BLE001
            pass
        shutil.rmtree(datos, ignore_errors=True)


def main() -> int:
    parte_aplicador()
    parte_memoria()
    print(f"\n{'VERDE' if not fallos else 'ROJAS: ' + ', '.join(fallos)}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
