"""verify_vitrina_honesta.py — la vitrina no miente, y lo que no puede correr no entra al run.

Cubre las DOS capas del fix, porque arreglar una sola no se ve:

  BACKEND  · `estado_honesto()` es la ÚNICA fuente: los dos endpoints que sirven cards
             (/v1/atoms/catalog y /v1/belts/cards) tienen que dar el MISMO estado para el
             mismo server. Estaba duplicado, y la copia que consume El Cuarto era la que
             seguía diciendo "Ya funciona · sin llave".
  FRONT    · `cardFilters()` de Cuarto.dc.html NO manda al run un átomo `local`: forzar un
             server que este entorno no puede lanzar sólo logra arrancar con un server
             muerto adentro (mismo precedente ya probado de "BYOK sin llave no entra":
             91s ok:False vs 5s ok:True).

El front se verifica ejecutando el CÓDIGO REAL extraído del HTML, no una copia: si alguien
cambia la línea, este test se entera. Y se comprueba aparte que el run siga LLAMÁNDOLO
(un predicado correcto que nadie invoca no sirve de nada).

    ./product/backend/.venv/bin/python qa/verify_vitrina_honesta.py
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "platform"))
sys.path.insert(0, str(ROOT / "product" / "backend"))

from app.phase1.atoms_router import estado_honesto, server_runtime  # noqa: E402

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {label}")
    else:
        fail += 1
        print(f"  ✗ {label}  {detail}")


# ── 1 · BACKEND: clasificación honesta ────────────────────────────────────────────
def bloque_backend():
    print("\n[1] BACKEND · dónde corre cada pieza")

    # un handler que SÍ existe en este árbol (no se inventa una ruta: se busca uno real)
    real = next((p for p in (ROOT / "product" / "belts").rglob("*_server.py")), None)
    assert real is not None, "no hay ni un *_server.py en product/belts — árbol inesperado"
    rel = "${PUPPET_BELTS}/" + str(real.relative_to(ROOT / "product" / "belts"))

    casos = [
        ("handler presente → server",
         {"command": "python3", "args": [rel]}, {}, "server"),
        ("handler que NO viaja al servidor → local",
         {"command": "python3", "args": ["${PUPPET_BELTS}/no/existe_server.py"]}, {}, "local"),
        ("ruta absoluta de otra máquina → local",
         {"command": "python3", "args": ["/Users/quien-sea/x_server.py"]}, {}, "local"),
        # FALSO VERDE REAL (kicad-sch): el `command` es una RUTA a un venv que no existe,
        # pero termina en "python" — y python SÍ está en la imagen. Mirar sólo el basename
        # lo pintaba "Listo · server". Lo cazó comparar prod contra la simulación.
        ("intérprete que es una RUTA inexistente, aunque el basename exista en el PATH",
         {"command": "<mcp-install>/loquesea/.venv/bin/python", "args": ["-m", "algo"]}, {}, "local"),
        ("  … y con ruta absoluta inexistente, igual",
         {"command": "/no/existe/.venv/bin/python3", "args": ["-m", "algo"]}, {}, "local"),
        ("requiere_app declarado → local AUNQUE el .py exista",
         {"command": "python3", "args": [rel], "requiere_app": "FreeCAD 1.1.1"}, {}, "local"),
    ]
    for label, cfg, card, esperado in casos:
        rt, req, det = server_runtime(cfg, card)
        check(label, rt == esperado, f"dio {rt!r} (requires={req}, detalle={det!r})")

    # ── LA HONESTIDAD ES UNA MEDICIÓN, NO UNA CONSTANTE ───────────────────────────
    # El MISMO server tiene que dar veredictos DISTINTOS en entornos distintos: en el
    # contenedor (sin node/uv) es "corre en tu máquina"; en la máquina del usuario que sí
    # los tiene, es "listo". Se prueba las dos puntas vaciando el PATH y restaurándolo —
    # que es exactamente la diferencia entre el contenedor y esta laptop.
    import os as _os
    pkg = {"command": "npx", "args": ["-y", "algo-mcp"]}
    path_real = _os.environ.get("PATH", "")
    try:
        _os.environ["PATH"] = ""          # simula el contenedor: python:3.13-slim + libpq5
        rt_sin, req_sin, _ = server_runtime(pkg)
    finally:
        _os.environ["PATH"] = path_real
    rt_con, _, _ = server_runtime(pkg)

    check("npx SIN el binario en el PATH → local (el caso del contenedor)",
          rt_sin == "local", f"dio {rt_sin!r}")
    check("  → y le dice al usuario QUÉ instalar, en su idioma",
          req_sin == ["Node.js"], f"requires={req_sin}")
    check("npx CON el binario presente → server (el caso de tu máquina)",
          rt_con == "server" if shutil.which("npx") else rt_con == "local",
          f"dio {rt_con!r} (npx={'sí' if shutil.which('npx') else 'no'} está en este PATH)")

    # el badge que ve el usuario no puede tener jerga nuestra
    _, _, _ = server_runtime({"command": "python3", "args": ["${PUPPET_BELTS}/no/existe.py"]})
    e = estado_honesto({"command": "python3", "args": ["${PUPPET_BELTS}/no/existe_server.py"]},
                       {}, auth="keyless", connector=None, connected=set(), partial=set())
    check("badge sin jerga interna (ni rutas, ni ${VAR}, ni 'handler')",
          not any(x in e["badge"] for x in ("${", "/", "handler", "PATH")),
          f"badge={e['badge']!r}")
    check("  → y el detalle técnico SÍ queda, pero aparte del badge",
          bool(e.get("runtime_detail")), f"runtime_detail={e.get('runtime_detail')!r}")

    # el falso verde histórico: keyless NO alcanza para prometer que funciona
    check("keyless + server no lanzable → NO dice 'Ya funciona'",
          e["state"] == "local" and "Ya funciona" not in e["badge"],
          f"state={e['state']} badge={e['badge']!r}")

    # y la pieza NO se oculta: sigue teniendo estado y badge, nunca desaparece
    check("  → pero la pieza NO se oculta (conserva state+badge, se ofrece igual)",
          bool(e.get("state")) and bool(e.get("badge")))


# ── 2 · BACKEND: los dos endpoints coinciden ──────────────────────────────────────
def bloque_paridad_endpoints():
    print("\n[2] BACKEND · /v1/atoms/catalog y /v1/belts/cards dicen LO MISMO")
    from app.phase1.atoms_router import collect_atoms

    atomos = {a["id"]: a for a in collect_atoms()}
    check("el catálogo devuelve átomos", len(atomos) > 0, f"n={len(atomos)}")

    # se re-derivan las cards belt por belt, como hace /v1/belts/cards, y se comparan
    difs, comparados = [], 0
    for belt_path in (ROOT / "catalog" / "templates").rglob("*.mcp.json"):
        belt = json.loads(belt_path.read_text(encoding="utf-8"))
        servers = belt.get("mcpServers") or {}
        for c in ((belt.get("_meta") or {}).get("cards") or []):
            backed = c.get("backed_by")
            if backed not in servers or c.get("id") not in atomos:
                continue
            e = estado_honesto(servers[backed], c, auth=c.get("auth", "keyless"),
                               connector=c.get("connector"), connected=set(), partial=set())
            comparados += 1
            if e["state"] != atomos[c["id"]]["state"]:
                difs.append(f"{c['id']}: belts={e['state']} vs atoms={atomos[c['id']]['state']}")
    check(f"mismo estado en ambos caminos ({comparados} cards comparadas)",
          not difs, "; ".join(difs[:4]))


# ── 3 · FRONT: el código real de cardFilters ──────────────────────────────────────
def bloque_front():
    print("\n[3] FRONT · cardFilters() no manda al run lo que no puede correr")
    html = (ROOT / "product" / "app" / "design" / "Cuarto.dc.html").read_text(encoding="utf-8")

    m = re.search(r"\n  cardFilters\(\)\{(.*?)\n  \}\n", html, re.S)
    check("se encontró cardFilters() en el HTML", bool(m),
          "cambió de forma → este test dejó de cubrir el front, arreglalo")
    if not m:
        return

    # se comprueba que el run SIGA usándolo (predicado correcto que nadie llama = inútil)
    check("el armado del run sigue llamando a this.cardFilters()",
          "this.cardFilters()" in html)

    node = shutil.which("node")
    check("node disponible para ejecutar el código real", bool(node))
    if not node:
        return

    cuerpo = m.group(1)
    cards = [
        {"id": "a", "auth": "keyless", "state": "ready",       "backed_by": "srv_ready", "tools": ["t1"]},
        {"id": "b", "auth": "keyless", "state": "local",       "backed_by": "srv_local", "tools": ["t2"]},
        {"id": "c", "auth": "token",   "state": "connected",   "backed_by": "srv_conn",  "tools": ["t3"]},
        {"id": "d", "auth": "token",   "state": "connectable", "backed_by": "srv_sinkey","tools": ["t4"]},
        {"id": "e", "auth": "token",   "state": "local",       "backed_by": "srv_lock",  "tools": ["t5"]},
    ]
    js = (
        "const state={nicheCards:" + json.dumps(cards) + ","
        "nicheActive:{a:true,b:true,c:true,d:true,e:true}};\n"
        "const self={state};\n"
        "function cardFilters(){" + cuerpo.replace("this.state", "self.state") + "}\n"
        "console.log(JSON.stringify(cardFilters()));\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as f:
        f.write(js); tmp = f.name
    try:
        out = subprocess.run([node, tmp], capture_output=True, text=True, timeout=30)
        tf = json.loads(out.stdout.strip() or "{}")
    except Exception as exc:                                    # noqa: BLE001
        check("cardFilters() ejecutable", False, f"{exc}: {out.stderr[:200] if 'out' in dir() else ''}")
        return
    finally:
        Path(tmp).unlink(missing_ok=True)

    check("entra la keyless que SÍ corre acá",            "srv_ready" in tf, f"tf={tf}")
    check("entra la BYOK CONECTADA",                      "srv_conn" in tf, f"tf={tf}")
    check("NO entra la keyless 'corre en tu máquina'",    "srv_local" not in tf, f"tf={tf}")
    check("NO entra la BYOK 'corre en tu máquina'",       "srv_lock" not in tf, f"tf={tf}")
    check("NO entra la BYOK sin llave (regla previa intacta)", "srv_sinkey" not in tf, f"tf={tf}")


def main():
    bloque_backend()
    bloque_paridad_endpoints()
    bloque_front()
    print(f"\n{ok}/{ok + fail} verdes")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
