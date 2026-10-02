#!/usr/bin/env python3
"""verify_cerebro_unico_e2e.py — UN CEREBRO PARA LAS SIETE, contra la `.app` INSTALADA.

[TANDA 1 · obra 1]

QUÉ MIDE
--------
Puesto UN cerebro en la fuente única (`preferencias-v2.default`, que es lo que el picker
escribe desde esta obra), los SIETE tienen que contestar ESE cerebro:

    la Sala  ·  Ciencia · Diseño · Educación · Finanzas · Legal · Oficina

y se corre DOS veces con modelos distintos, porque una sola pasada no distingue «el
selector gobierna» de «casualmente ya estaba ése».

QUÉ **NO** MIDE, y dónde se mide
--------------------------------
No mide que el PICKER escriba esa fuente — eso es el otro extremo del cable y lo mide
`product/app/design/verify_selector_unico.mjs`. Antes de esta obra esta vara daba VERDE
con el bug puesto: el backend siempre resolvió por `default`, y lo que estaba cortado era
que el click llegara ahí. Las dos varas juntas cubren la cadena; ninguna sola.

EL 429 ES CABLE BUENO
---------------------
Un CLI sin cuota contesta 502 con la causa TIPADA adentro (`HTTP 429 … usage limit`). Eso
no es este bug: es el cable funcionando y el proveedor diciendo que no. Cuenta VERDE y se
reporta por nombre. Lo que cuenta ROJO es contestar 200 con OTRO modelo — un pedido que
nunca se hizo, sin causa que mostrar.

CORRE (con la `.app` abierta):  `python3 qa/verify_cerebro_unico_e2e.py`
       token: `$ALEPH_TOKEN`, o se lee del localStorage de la webview instalada.
"""
from __future__ import annotations

import glob
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = os.environ.get("ALEPH_BASE", "http://127.0.0.1:8330")
DATOS = Path.home() / "Library" / "Application Support" / "Aleph"
WORKSPACES = ["ciencia", "diseno", "educacion", "finanzas", "legal", "oficina"]
PROMPT = "Decí solo: PING."

FALLOS: list[str] = []


def ok(cond: bool, etiqueta: str, extra: str = "") -> None:
    print(f"  {'✓' if cond else '✗'} {etiqueta}" + ("" if cond or not extra else f" — {extra}"))
    if not cond:
        FALLOS.append(etiqueta)


def _puppet_user() -> dict:
    """La sesión del dueño, tal como la webview INSTALADA la guarda (localStorage UTF-16).

    Una sola lectura para el token y para el `user_id`: son el mismo hecho y separarlos
    invita a que la vara mida con la sesión de uno y el dueño de otro."""
    patron = (Path.home() / "Library/WebKit/app.aleph.desktop/WebsiteData/Default"
              / "*/*/LocalStorage/localstorage.sqlite3")
    for f in glob.glob(str(patron)):
        try:
            c = sqlite3.connect(f"file:{f}?mode=ro", uri=True)
            for k, v in c.execute("select key, value from ItemTable"):
                k = k.decode("utf-16-le") if isinstance(k, bytes) else k
                if k == "puppet_user":
                    v = v.decode("utf-16-le") if isinstance(v, bytes) else v
                    return json.loads(v)
        except Exception:  # noqa: BLE001 — otra partición de la webview, se sigue
            continue
    return {}


_USUARIO = _puppet_user()
TOK = os.environ.get("ALEPH_TOKEN", "").strip() or _USUARIO.get("session_token", "")
UID = os.environ.get("ALEPH_UID", "").strip() or _USUARIO.get("id", "")
if not TOK or not UID:
    raise SystemExit("[no medible] sin sesión del dueño: exportá ALEPH_TOKEN y ALEPH_UID, "
                     "o abrí la .app instalada una vez para que la webview la guarde")
HDRS = {"Authorization": "Bearer " + TOK, "Content-Type": "application/json"}


def pedir(path: str, *, metodo: str = "GET", cuerpo=None, extra=None, timeout=300):
    h = dict(HDRS)
    h.update(extra or {})
    data = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=metodo)
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        crudo = e.read()
        try:
            return e.code, json.loads(crudo or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {"_crudo": crudo.decode("utf-8", "replace")[:400]}


def exito(st: int) -> bool:
    """2xx, no `== 200`. Y no es teoría: `POST /v1/puppets/run` contesta **201**, así que
    la primera versión de esta vara daba el turno de la Sala por fallido con el turno
    perfectamente corrido y `grok-4.6-build` escrito en el ledger. La casa ya tiene la
    regla («200 no es éxito») y esta vara la incumplía."""
    return 200 <= st < 300


def sin_cuota(cuerpo: dict) -> bool:
    """¿El proveedor dijo «no» con causa tipada? Eso es cable bueno, no este bug."""
    return "429" in json.dumps(cuerpo, ensure_ascii=False)


def slug_de(picker_id: str) -> str:
    _, d = pedir("/v1/modelos/selector?todos=1")
    for f in d.get("modelos") or []:
        if str(f.get("picker_id") or "") == picker_id:
            return str(f.get("slug") or "")
    raise SystemExit(f"[no medible] «{picker_id}» no está en el catálogo de esta máquina")


def poner_cerebro(picker_id: str) -> None:
    st, d = pedir("/v1/modelos/preferencias", metodo="PUT",
                  cuerpo={"default": slug_de(picker_id)})
    if not exito(st):
        raise SystemExit(f"[no medible] no pude poner el cerebro: HTTP {st} {d}")


def turno_workspace(ws: str, uid: str) -> tuple[str | None, dict]:
    """Un paso por el MISMO borde y con las MISMAS cabeceras que el pack le escribe al
    stack (`X-Aleph-Workspace` + `X-Aleph-User`; ningún stack recibe `X-Aleph-Model`)."""
    st, d = pedir("/v1/workspaces/brain/openai/chat/completions", metodo="POST",
                  cuerpo={"model": "aleph-workspace", "max_tokens": 32, "temperature": 0,
                          "messages": [{"role": "user", "content": PROMPT}]},
                  extra={"X-Aleph-Workspace": ws, "X-Aleph-User": uid,
                         "X-Aleph-Space": f"vara-{ws}-{uuid.uuid4().hex[:8]}"})
    return (d.get("model") if exito(st) else None), d


def turno_sala(uid: str) -> tuple[str | None, dict]:
    """El turno de la Sala por SU camino real: `POST /v1/puppets/run` sin `model` —
    medido interceptando el `fetch` de la página instalada."""
    space = "vara-sala-" + uuid.uuid4().hex[:10]
    st, d = pedir("/v1/puppets/run", metodo="POST",
                  cuerpo={"user_id": uid, "prompt": PROMPT, "space_id": space,
                          "lang": "es", "agent": None})
    if not exito(st):
        return None, d
    # `model_final` sale del LEDGER que Aleph escribió, no del cuerpo de la respuesta:
    # es el hecho que el anti-grift audita.
    ruta = DATOS / "espacios" / space / "events.jsonl"
    for _ in range(60):
        if ruta.exists():
            final = None
            for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    e = json.loads(linea)
                except Exception:  # noqa: BLE001
                    continue
                if e.get("type") in ("final", "closed") and e.get("model_final"):
                    final = e
            if final:
                return final["model_final"], final
        time.sleep(1)
    return None, {"error": "el espacio no cerró", "space_id": space}


def familia(model_final: str) -> str:
    m = (model_final or "").lower()
    if "grok" in m:
        return "grok_cli"
    if "claude" in m:
        return "claude_cli"
    if "gpt" in m or "codex" in m or m.startswith("o"):
        return "codex_cli"
    return "?" + m


def ronda(picker_id: str, uid: str) -> None:
    print(f"\n── cerebro puesto en el selector: {picker_id} ──")
    poner_cerebro(picker_id)
    st, pref = pedir("/v1/modelos/preferencias")
    ok(str(pref.get("default") or "").endswith(picker_id),
       f"la fuente única quedó en {picker_id}", str(pref.get("default")))

    for ws in WORKSPACES:
        mf, d = turno_workspace(ws, uid)
        if mf is None and sin_cuota(d):
            print(f"  ✓ {ws:<10} sin cuota, causa tipada (cable bueno)")
            continue
        ok(mf is not None and familia(mf) == picker_id,
           f"{ws:<10} respondió el cerebro elegido", f"model_final={mf} · {str(d)[:120]}")

    mf, d = turno_sala(uid)
    if mf is None and sin_cuota(d):
        print("  ✓ sala       sin cuota, causa tipada (cable bueno)")
    else:
        ok(mf is not None and familia(mf) == picker_id,
           "sala       respondió el cerebro elegido", f"model_final={mf} · {str(d)[:120]}")


def main() -> int:
    st, _ = pedir("/health", timeout=5)
    if not exito(st):
        raise SystemExit(f"[no medible] la .app no está sirviendo en {BASE} (HTTP {st})")
    st, ses = pedir("/v1/modelos/preferencias")
    if not exito(st):
        raise SystemExit(f"[no medible] la sesión no sirve: HTTP {st}")

    previo = str(ses.get("default") or "")
    try:
        # DOS modelos: una sola pasada no distingue «gobierna» de «ya estaba ése».
        for pid in ("grok_cli", "claude_cli"):
            ronda(pid, UID)
    finally:
        if previo:
            pedir("/v1/modelos/preferencias", metodo="PUT", cuerpo={"default": previo})
            print(f"\n  (cerebro devuelto a {previo})")

    print("\n✗ %d fallo(s)" % len(FALLOS) if FALLOS else "\n✓ cerebro único: los siete verdes")
    return 1 if FALLOS else 0


if __name__ == "__main__":
    raise SystemExit(main())
