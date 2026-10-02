"""
calentar_cinturon.py — al ABRIR el agente, no al primer mensaje (CONTRACT-CONEXION-v1 §6).

Hoy el cinturón se levanta DENTRO del run: el usuario escribe, y recién ahí paga el arranque
de sus servidores y descubre que uno está roto. Esto mueve el descubrimiento al momento de
ABRIR: por cada pieza habilitada se ejecuta su receta, se verifica, y el resultado queda en
el registro — así la card dice la verdad antes de que el usuario escriba una palabra.

⚠️ AHORA SÍ SOSTIENE — CON EL DUEÑO ENCENDIDO (D3). Este docstring decía que calentar NO
sostenía, y que hacerlo exigía «un dueño del ciclo de vida que hoy no existe: quién los
mata, qué pasa con N agentes abiertos, qué pasa si el sidecar reinicia, el techo de
memoria». Ese dueño existe: `inspection/dueno.py`, y responde las cuatro preguntas (el
cosechador, el refcount, el barrido de arranque, el techo con LRU).

Con `ALEPH_DUENO=on`, los servidores que este módulo levanta quedan VIVOS —la conexión se
sostiene por `OCIOSIDAD_S`— así que el primer mensaje ya no paga el spawn. Medido sobre las
6 piezas del agente real: la segunda pasada baja de **9.154 ms a 6.565 ms**, y quedan 5
conexiones sostenidas.

Con la perilla apagada (default) el comportamiento es el de siempre: se mide y se apaga. Lo
que se logra en los dos casos es lo mismo y sigue siendo lo que más dolía: **el fallo se ve
antes de escribir**.

⚠️ LA LÁPIDA MANDA. Una entidad con `habilitado = false` NO se levanta y NO se re-verifica:
el permiso del usuario gana sobre cualquier medición. Calentarla sería levantar justo lo que
pidió que no corriera.

⚠️ UPDATE, JAMÁS UPSERT (CLAUDE.md). Calentar mide sobre las piezas del agente; escribir en
el registro es otra cosa. Una pieza que el registro no conoce se reporta por nombre y no se
inventa la fila.

NO TOCA EL VERIFICADOR: lo llama. `verificar_uno` sigue siendo el único lugar donde se
decide si una conexión vive y si una credencial sirve.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

_RAIZ = Path(__file__).resolve().parents[4]
for _p in (_RAIZ / "platform", _RAIZ / "platform/db", _RAIZ / "platform/inspection",
           _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

#: Tope de piezas que se calientan por agente. Abrir no puede costar más que correr: si un
#: cinturón tiene cuarenta piezas, calentarlas todas al abrir convierte «abrir» en el nuevo
#: primer mensaje. Lo que sobra queda sin medir y el reporte lo dice por nombre.
MAX_PIEZAS = 12


def _repo():
    from app.phase1 import repo
    return repo


def _cr():
    from app.phase1 import conexiones_repo
    return conexiones_repo


def piezas_del_agente(conn, puppet_id: str) -> list:
    """`[(belt_ref, server)]` del agente, en el orden del belt. Sin duplicados."""
    import aleph_paths
    root = aleph_paths.resource_root()
    with conn.cursor() as cur:
        cur.execute("SELECT config FROM puppets WHERE id = %s", (puppet_id,))
        fila = cur.fetchone()
    if not fila:
        return []
    try:
        cfg = json.loads(fila[0]) if isinstance(fila[0], str) else (fila[0] or {})
    except (TypeError, ValueError):
        return []
    out, vistos = [], set()
    for ref in ((cfg.get("belt") or {}).get("belt_refs") or []):
        if not isinstance(ref, str) or not ref.endswith(".mcp.json"):
            continue
        p = (root / ref).resolve()
        if not p.exists():
            continue
        try:
            servers = json.loads(p.read_text(encoding="utf-8")).get("mcpServers") or {}
        except (OSError, ValueError):
            continue
        for n in servers:
            if n not in vistos:
                vistos.add(n)
                out.append((ref, n))
    return out


def calentar(puppet_id: str, *, owner: str, get_conn, max_piezas: int = MAX_PIEZAS) -> dict:
    """Levanta, verifica y persiste cada pieza HABILITADA del agente. Nunca levanta.

    Devuelve `{piezas: [...], apagadas: [...], sin_registro: [...], sin_medir: [...], ms}`.
    Un fallo de una pieza NO detiene a las demás ni impide abrir el agente: viaja en su
    propia entrada con su causa, y la card lo dice (FALLO VISIBLE, JAMÁS MUDO).
    """
    from app.phase1 import conexiones_verificador as V
    t0 = time.perf_counter()
    CR = _cr()
    salida: dict[str, Any] = {"piezas": [], "apagadas": [], "sin_registro": [],
                              "sin_medir": [], "ms": 0}

    conn = get_conn()
    try:
        objetivo = piezas_del_agente(conn, puppet_id)
        entidades = {e["entity_id"]: e for e in CR.listar_entidades(conn, owner)}
    finally:
        conn.close()

    pendientes = []
    for belt, srv in objetivo:
        e = entidades.get(srv)
        if e is None:
            salida["sin_registro"].append(srv)      # no se inventa la fila
            continue
        if not e.get("habilitado"):
            salida["apagadas"].append(srv)          # la lápida manda
            continue
        pendientes.append((belt, srv))

    if len(pendientes) > max_piezas:
        salida["sin_medir"] = [s for _, s in pendientes[max_piezas:]]
        pendientes = pendientes[:max_piezas]

    medidas = []
    for belt, srv in pendientes:
        try:
            f = V.verificar_uno(belt, srv, owner=owner, get_conn=get_conn)
        except Exception as e:                      # noqa: BLE001 — una pieza no tumba el abrir
            f = {"server": srv, "belt": belt, "arranca": False,
                 "conexion": {"estado": V.ROTA, "causa": V.C_ARRANQUE, "tool_usada": None,
                              "evidencia": f"{type(e).__name__}: {e}"[:200],
                              "ts": time.strftime("%Y-%m-%dT%H:%M:%S")},
                 "credencial": None, "tools_probadas": []}
        medidas.append(f)
        salida["piezas"].append({
            "server": srv,
            "conexion": (f.get("conexion") or {}).get("estado"),
            "causa": (f.get("conexion") or {}).get("causa"),
            "credencial": (f.get("credencial") or {}).get("estado"),
            "era": (f.get("conexion") or {}).get("era"),
            "tool": (f.get("conexion") or {}).get("tool_usada"),
        })

    if medidas:
        conn = get_conn()
        try:
            conocidas = {e["entity_id"] for e in CR.listar_entidades(conn, owner)}
            for f in medidas:
                if f["server"] not in conocidas:
                    continue
                campos = {"conexion": f.get("conexion"), "credencial": f.get("credencial")}
                cx = f.get("conexion") or {}
                # OBRA 2 · las dos columnas de protocolo dejan de estar vacías. `era` dice
                # QUÉ negociación habla el server; `version_negociada` dice con qué versión
                # cerró. Las dos salían de `_protocol_evidence`, que hasta ahora vivía en
                # memoria y moría con el proceso.
                if cx.get("era"):
                    campos["era"] = cx["era"]
                if cx.get("version_negociada"):
                    campos["version_negociada"] = cx["version_negociada"]
                try:
                    CR.upsert_entidad(conn, user_id=owner, entity_id=f["server"],
                                      commit=False, **campos)
                except Exception:                   # noqa: BLE001 — persistir no puede tumbar
                    pass
            conn.commit()
        finally:
            conn.close()

    # LO SOSTENIDO SE REPORTA POR NOMBRE. Un calentado que deja procesos vivos y no lo dice
    # convierte 113 MB por pieza en algo invisible; el §6.3 del diseño existe para que la
    # memoria sostenida tenga siempre un dueño con nombre y apellido.
    try:
        import dueno as _DU
        if _DU.encendido():
            _est = _DU.actual().estado()
            salida["sostenidas"] = sorted({v["entity_id"] for v in _est["vivas"]})
            salida["dueno"] = {"vivas": len(_est["vivas"]), "tope": _est["tope"],
                               "ociosidad_s": _est["ociosidad_s"]}
    except Exception:                                # noqa: BLE001 — reportar no puede fallar
        pass

    salida["ms"] = int((time.perf_counter() - t0) * 1000)
    return salida


__all__ = ["calentar", "piezas_del_agente", "MAX_PIEZAS"]
