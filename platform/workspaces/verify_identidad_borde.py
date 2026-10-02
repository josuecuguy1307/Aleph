#!/usr/bin/env python3
"""verify_identidad_borde.py — LA IDENTIDAD DEL WORKSPACE, CUANDO LA CABECERA NO VIENE.

QUÉ MIDE, Y POR QUÉ ESTA VARA EXISTE.

Diseño cruza el borde 5 veces por turno **sin `X-Aleph-Workspace`** (medido contra la
pantalla el 2026-08-22). Con el workspace vacío, el turno cae en un stack que no existe:
ninguna perilla por stack lo alcanza y su hilo de la casa se queda mudo. La casa igual
sabe quién es —porque es la casa la que reparte el `chat_id` en el `enter`—, así que la
identidad se RECUERDA en vez de perderse.

DOS PARTES, PORQUE SON DOS HECHOS DISTINTOS:

  A · EL REGISTRO (`pack.registrar_identidad` / `pack.workspace_de`) — unitaria, sin red.
      Incluye lo que un registro que sólo sabe decir que sí no probaría: la ambigüedad
      apaga la marca, una marca corta no se registra, y lo que nadie repartió no resuelve.

  B · EL BORDE EN VIVO — que el endpoint USE lo recordado. Un registro correcto que nadie
      consulta es exactamente el verde mudo que esta casa persigue, así que la parte B no
      lee código: manda un pedido REAL con `X-Aleph-Chat` y sin `X-Aleph-Workspace`, y
      pregunta qué workspace usó el borde.

CÓMO CORRERLA

    ALEPH_GRABAR_CABECERAS=<ruta.jsonl>   ← el sidecar tiene que estar levantado CON esto
    python3 platform/workspaces/verify_identidad_borde.py \\
        --base http://127.0.0.1:8934 --cabeceras <la misma ruta.jsonl>

Sin `--base` corre sólo la parte A y **lo dice**: la parte B queda `[no medible]`, nunca
verde. Una vara que se salta la mitad y devuelve 0 mide su propio comentario.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workspaces import pack                                          # noqa: E402

_ROJAS = 0
_NO_MEDIBLES = 0


def ok(cond: bool, titulo: str, detalle: str = "") -> None:
    global _ROJAS
    if not cond:
        _ROJAS += 1
    print(f"  {'✅' if cond else '❌'} {titulo}" + (f"   [{detalle}]" if detalle else ""))


def no_medible(titulo: str, motivo: str) -> None:
    global _NO_MEDIBLES
    _NO_MEDIBLES += 1
    print(f"  ⏳ [no medible] {titulo}   [{motivo}]")


# ── A · EL REGISTRO ──────────────────────────────────────────────────────────────────

def parte_a() -> None:
    print("\nA · EL REGISTRO — lo que la casa repartió, lo reconoce cuando vuelve")
    pack._IDENTIDAD.clear()

    puestas = pack.registrar_identidad(
        "diseno", chat_id="bf4f33d8-18c6-4777-ad46-4193a1c66698", space_id=None)
    ok(puestas == ["chat:bf4f33d8-18c6-4777-ad46-4193a1c66698"],
       "A1 · registrar devuelve LAS MARCAS puestas, no un booleano", str(puestas))

    ok(pack.workspace_de(chat_id="bf4f33d8-18c6-4777-ad46-4193a1c66698") == "diseno",
       "A2 · el hilo que la casa repartió devuelve su workspace")

    ok(pack.workspace_de(chat_id="00000000-0000-0000-0000-000000000000") == "",
       "A3 · un hilo que la casa NO repartió no resuelve nada")

    ok(pack.workspace_de(chat_id=None, space_id=None) == "",
       "A4 · sin ninguna marca, `''` — jamás un workspace por defecto")

    pack.registrar_identidad("ciencia", space_id="space-ws-propio-de-ciencia-1")
    ok(pack.workspace_de(space_id="space-ws-propio-de-ciencia-1") == "ciencia",
       "A5 · el espacio propio también es marca")

    # LA AMBIGÜEDAD APAGA. Es la mitad de la vara que un registro ingenuo no pasa: lo fácil
    # es que gane el último que escribió, y eso sería fabricar identidad.
    pack.registrar_identidad("finanzas", chat_id="bf4f33d8-18c6-4777-ad46-4193a1c66698")
    ok(pack.workspace_de(chat_id="bf4f33d8-18c6-4777-ad46-4193a1c66698") == "",
       "A6 · dos dueños para una marca la APAGAN (fail-closed), no se elige uno")

    pack._IDENTIDAD.clear()
    ok(pack.registrar_identidad("legal", chat_id="abc") == []
       and pack.workspace_de(chat_id="abc") == "",
       "A7 · una marca demasiado corta no se registra ni resuelve")

    ok(pack.registrar_identidad("", chat_id="hilo-largo-de-verdad") == [],
       "A8 · sin workspace no se anota nada")

    # EL ORDEN NO ES ESTÉTICO: el hilo es por workspace por construcción; el espacio puede
    # venir derivado del `sid`, que los seis comparten.
    pack._IDENTIDAD.clear()
    pack.registrar_identidad("diseno", chat_id="hilo-de-diseno-1234")
    pack.registrar_identidad("legal", space_id="espacio-de-legal-1234")
    ok(pack.workspace_de(chat_id="hilo-de-diseno-1234",
                         space_id="espacio-de-legal-1234") == "diseno",
       "A9 · con las dos marcas puestas manda el HILO, que es el que no se confunde")
    pack._IDENTIDAD.clear()


# ── B · EL BORDE EN VIVO ─────────────────────────────────────────────────────────────

def _pedir(url: str, cuerpo: dict, cab: dict) -> int:
    datos = json.dumps(cuerpo).encode("utf-8")
    req = urllib.request.Request(url, data=datos, method="POST",
                                 headers={"Content-Type": "application/json", **cab})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:                                             # noqa: BLE001
        return 0


def _pedir_json(url: str, cuerpo: dict, cab: dict) -> tuple[int, dict]:
    datos = json.dumps(cuerpo).encode("utf-8")
    req = urllib.request.Request(url, data=datos, method="POST",
                                 headers={"Content-Type": "application/json", **cab})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:                                         # noqa: BLE001
            return e.code, {}
    except Exception:                                             # noqa: BLE001
        return 0, {}


def parte_b(base: str, ruta_cab: str) -> None:
    """El borde, EN VIVO, por el camino de verdad.

    No se siembra el registro a mano: se ENTRA al workspace, que es lo que hace la casa
    cuando el usuario entra, y ahí es donde `levantar` anota la identidad. Sembrarlo por
    una puerta de vara probaría el registro y no el cable — y el cable es justamente la
    mitad que un verde mudo se saltea.
    """
    print("\nB · EL BORDE EN VIVO — que el endpoint USE lo recordado")
    if not base:
        no_medible("B · el borde honra el registro", "sin --base: no hay sidecar que medir")
        return
    if not ruta_cab:
        no_medible("B · el borde honra el registro",
                   "sin --cabeceras no hay con qué mirar qué workspace usó")
        return

    # La sesión la emite el propio pack por su puerta local: ni fixture ni storage ajeno.
    try:
        req = urllib.request.Request(base + "/v1/auth/local", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            sesion = json.loads(r.read())
    except Exception as exc:                                      # noqa: BLE001
        ok(False, "B0 · el sidecar contesta y emite sesión", f"{type(exc).__name__}: {exc}")
        return
    cab = {"Authorization": "Bearer " + sesion["session_token"]}

    def _hilo_nuevo() -> str:
        st, j = _pedir_json(base + "/v1/chats", {}, cab)
        return (j or {}).get("id") or ""

    def _ultimo_desde(pos: int) -> dict:
        filas = []
        try:
            with open(ruta_cab, "r", encoding="utf-8") as fh:
                fh.seek(pos)
                for linea in fh:
                    try:
                        filas.append(json.loads(linea))
                    except Exception:                             # noqa: BLE001
                        pass
        except OSError:
            return {}
        return filas[-1] if filas else {}

    def _tam() -> int:
        return os.path.getsize(ruta_cab) if os.path.isfile(ruta_cab) else 0

    cuerpo = {"model": "x", "messages": [{"role": "user", "content": "ping"}], "tools": []}
    borde = base + "/v1/workspaces/brain/openai/chat/completions"

    # ── B1 · EL ROJO QUE ESTA VARA TIENE QUE PODER DAR ───────────────────────────────
    # Un hilo REAL del dueño, que la casa nunca repartió a ningún workspace. Si el borde
    # inventara identidad —o si el registro respondiera de más— acá se vería.
    huerfano = _hilo_nuevo()
    if not huerfano:
        no_medible("B1 · sin registro el borde no inventa", "no se pudo crear el hilo")
        return
    pos = _tam()
    _pedir(borde, cuerpo, {**cab, "X-Aleph-Chat": huerfano})
    fila = _ultimo_desde(pos)
    ok(fila.get("ws_visto") == "?" and fila.get("ws_usado") == "",
       "B1 · sin cabecera y sin registro, el borde NO inventa workspace",
       f"visto={fila.get('ws_visto')!r} usado={fila.get('ws_usado')!r}")

    # ── B2 · EL CABLE ────────────────────────────────────────────────────────────────
    propio = _hilo_nuevo()
    st, _ = _pedir_json(base + "/v1/workspaces/diseno/enter",
                        {"user_id": sesion["id"], "chat_id": propio}, cab)
    if st != 200:
        no_medible("B2 · el borde usa lo recordado",
                   f"el `enter` de Diseño no llegó a 200 (HTTP {st})")
        return
    pos = _tam()
    _pedir(borde, cuerpo, {**cab, "X-Aleph-Chat": propio})
    fila = _ultimo_desde(pos)
    ok(fila.get("ws_visto") == "?" and fila.get("ws_usado") == "diseno",
       "B2 · con la identidad repartida por el `enter`, el borde la USA sin la cabecera",
       f"visto={fila.get('ws_visto')!r} recordado={fila.get('ws_recordado')!r}")

    # ── B3 · LA VÍA NORMAL NO SE TOCA ────────────────────────────────────────────────
    # El que SÍ manda su cabecera manda él, y el registro no puede pisarlo.
    pos = _tam()
    _pedir(borde, cuerpo, {**cab, "X-Aleph-Chat": propio, "X-Aleph-Workspace": "ciencia"})
    fila = _ultimo_desde(pos)
    ok(fila.get("ws_usado") == "ciencia" and fila.get("ws_recordado") == "",
       "B3 · la cabecera MANDA: el registro no se consulta cuando el stack ya dijo quién es",
       f"usado={fila.get('ws_usado')!r} recordado={fila.get('ws_recordado')!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("ALEPH_BASE", ""))
    ap.add_argument("--cabeceras", default=os.environ.get("ALEPH_GRABAR_CABECERAS", ""))
    args = ap.parse_args()
    print("═" * 78)
    print("LA IDENTIDAD DEL WORKSPACE CUANDO LA CABECERA NO VIENE")
    print("═" * 78)
    parte_a()
    parte_b(args.base, args.cabeceras)
    print("\n" + "─" * 78)
    print(f"ROJAS: {_ROJAS}   ·   NO MEDIBLES: {_NO_MEDIBLES}")
    return 1 if (_ROJAS or _NO_MEDIBLES) else 0


if __name__ == "__main__":
    raise SystemExit(main())
