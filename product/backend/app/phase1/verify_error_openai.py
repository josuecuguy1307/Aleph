#!/usr/bin/env python3
"""verify_error_openai.py — EL FALLO DEL BORDE TIENE QUE HABLAR, Y NO HACERSE REINTENTAR.

    python3 product/backend/app/phase1/verify_error_openai.py --base http://127.0.0.1:PUERTO

QUÉ MIDE, y por qué son DOS cosas y no una. Medido el 2026-08-23 en el log del pack de
Diseño, una línea por cada imagen que manda su `preview(vision: true)`:

    409 status code (no body)      ×3

  1 · «no body» era FALSO: el cuerpo viajaba entero, pero anidado en `detail.error`
      porque se devolvía dentro de un `HTTPException`. Un cliente OpenAI lee `body.error`.
      La causa estaba y no la leía nadie.
  2 · los ×3 son EL STATUS: el SDK de OpenAI reintenta 408/409/429/5xx con `maxRetries: 2`.
      12 de 43 cruces (28 %) de una conversación real eran reintentos de algo que no podía
      mejorar — el modelo no declara `vision` y no la va a declarar en el intento 3.

ESTA VARA CORRE CONTRA EL BORDE DE VERDAD, con el disparador real (un `image_url`) y su
CONTROL (el mismo pedido sin imagen). Sin `--base` no mide: lo dice y sale distinto de 0.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

_ROJAS = 0
_NO_MEDIBLES = 0

#: 1×1 px transparente. Alcanza para disparar la modalidad: lo que se mide es la NEGATIVA
#: del borde, no la imagen.
_PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
       "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def ok(cond, titulo, detalle=""):
    global _ROJAS
    if not cond:
        _ROJAS += 1
    print(f"  {'✅' if cond else '❌'} {titulo}" + (f"   [{detalle}]" if detalle else ""))


def no_medible(titulo, motivo):
    global _NO_MEDIBLES
    _NO_MEDIBLES += 1
    print(f"  ⏳ [no medible] {titulo}   [{motivo}]")


def _post(url, cuerpo, cab=None):
    req = urllib.request.Request(
        url, data=json.dumps(cuerpo).encode(), method="POST",
        headers={"Content-Type": "application/json", **(cab or {})})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        crudo = e.read() or b""
        try:
            return e.code, json.loads(crudo)
        except Exception:                                  # noqa: BLE001
            return e.code, {"__crudo__": crudo.decode("utf-8", "replace")[:400]}
    except Exception as exc:                               # noqa: BLE001
        return 0, {"__falla__": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="")
    a = ap.parse_args()
    print("═" * 78)
    print("EL FALLO DEL BORDE HABLA, Y NO SE HACE REINTENTAR")
    print("═" * 78)

    if not a.base:
        no_medible("todo", "sin --base no hay borde que medir")
        print(f"\nROJAS: {_ROJAS} · NO MEDIBLES: {_NO_MEDIBLES}")
        return 1

    st, ses = _post(a.base + "/v1/auth/local", {})
    if st != 200 or not ses.get("session_token"):
        ok(False, "0 · el sidecar contesta y emite sesión", str(ses)[:120])
        return 1
    cab = {"Authorization": "Bearer " + ses["session_token"]}

    con_imagen = {"model": "x", "tools": [], "messages": [{"role": "user", "content": [
        {"type": "text", "text": "que ves"},
        {"type": "image_url", "image_url": {"url": _PX}}]}]}
    sin_imagen = {"model": "x", "tools": [],
                  "messages": [{"role": "user", "content": "que ves"}]}

    # ── A · EL CONTROL, PRIMERO ──────────────────────────────────────────────────────
    # Un 400 sin disparador no probaría nada: hay que ver que el MISMO pedido sin imagen
    # pasa. Es la diferencia entre medir la negativa y medir que el borde está roto.
    print("\nA · el control — el mismo pedido SIN imagen")
    st_ok, _ = _post(a.base + "/v1/workspaces/brain/openai/chat/completions", sin_imagen, cab)
    ok(st_ok == 200, "A1 · sin imagen el borde atiende (200)", f"HTTP {st_ok}")
    if st_ok != 200:
        print("\n  ⚠️ sin control válido lo de abajo no significa nada")

    # ── B · EL DISPARADOR ────────────────────────────────────────────────────────────
    print("\nB · con imagen, contra un cerebro que no declara `vision`")
    st_img, cuerpo = _post(a.base + "/v1/workspaces/brain/openai/chat/completions",
                           con_imagen, cab)
    if st_img == 200:
        no_medible("B · la negativa del borde",
                   "el cerebro equipado SÍ declara `vision`: no hay negativa que medir")
        print(f"\nROJAS: {_ROJAS} · NO MEDIBLES: {_NO_MEDIBLES}")
        return 1 if (_ROJAS or _NO_MEDIBLES) else 0

    err = cuerpo.get("error") if isinstance(cuerpo, dict) else None
    ok(isinstance(err, dict),
       "B1 · el error va donde el contrato de OpenAI dice: `body.error`, no `body.detail`",
       "claves: " + ",".join(sorted(cuerpo)) if isinstance(cuerpo, dict) else str(cuerpo)[:80])
    ok(isinstance(err, dict) and bool((err or {}).get("message", "").strip()),
       "B2 · y trae un mensaje legible — no un cuerpo vacío",
       ((err or {}).get("message") or "")[:70])
    ok(isinstance(err, dict) and (err or {}).get("type") == "capability_unavailable",
       "B3 · con la causa TIPADA de la casa", str((err or {}).get("type")))
    ok(isinstance(err, dict) and (err or {}).get("code"),
       "B4 · y `code` con un dato, no `null`", str((err or {}).get("code")))
    ok(isinstance(err, dict) and "vision" in json.dumps((err or {}).get("aleph") or {}),
       "B5 · y dice QUÉ capacidad falta, que es lo accionable",
       json.dumps(((err or {}).get("aleph") or {}).get("missing")))

    # ── C · Y NO SE HACE REINTENTAR ──────────────────────────────────────────────────
    print("\nC · el status — lo que decide si el SDK reintenta solo")
    ok(st_img not in (408, 409, 429) and 400 <= st_img < 500,
       "C1 · NO es uno de los que el SDK reintenta (408/409/429); es un 4xx definitivo",
       f"HTTP {st_img}")
    ok(st_img == 400, "C2 · concretamente 400", f"HTTP {st_img}")

    print("\n" + "─" * 78)
    print(f"ROJAS: {_ROJAS}   ·   NO MEDIBLES: {_NO_MEDIBLES}")
    return 1 if (_ROJAS or _NO_MEDIBLES) else 0


if __name__ == "__main__":
    raise SystemExit(main())
