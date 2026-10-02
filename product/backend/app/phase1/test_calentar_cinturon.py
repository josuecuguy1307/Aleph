"""test_calentar_cinturon.py — abrir el agente mide, y respeta lo que el usuario decidió.

Escritos contra los fallos que importan:
  1. la LÁPIDA manda: una pieza apagada no se levanta NI se re-verifica
  2. un fallo de una pieza no impide abrir el agente ni frena a las demás
  3. UPDATE jamás upsert: no se inventan filas para lo que el registro no conoce
  4. calienta, NO sostiene: no queda ningún proceso vivo después

Correr: pytest product/backend/app/phase1/test_calentar_cinturon.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parents[4]
for _p in (_RAIZ / "platform", _RAIZ / "platform/db", _RAIZ / "product/backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.phase1 import calentar_cinturon as CAL  # noqa: E402


class _Cursor:
    def __init__(s, filas): s._f = filas
    def __enter__(s): return s
    def __exit__(s, *a): return False
    def execute(s, *a, **k): pass
    def fetchone(s): return s._f
    def fetchall(s): return []


class _Conn:
    def __init__(s, config=None): s._c = config
    def cursor(s): return _Cursor(s._c)
    def close(s): pass
    def commit(s): pass


def _fake(monkeypatch, *, entidades, piezas, resultados, escritas):
    """Doble mínimo. Se parchea la FUNCIÓN del módulo real, no se swapea el módulo:
    `from app.phase1 import X` resuelve por ATRIBUTO DEL PAQUETE una vez que está cargado,
    así que un parche de `sys.modules` no lo intercepta — medido, los tests pasaban solos
    y el doble no entraba corriendo con el resto de la suite. Además así los veredictos
    usan las constantes REALES del verificador y no una copia que puede quedar vieja."""
    from app.phase1 import conexiones_verificador as V

    class _CR:
        @staticmethod
        def listar_entidades(conn, owner): return list(entidades)
        @staticmethod
        def upsert_entidad(conn, *, user_id, entity_id, commit=True, **campos):
            escritas.append((entity_id, campos))

    llamadas: list = []

    def _verificar(belt, server, *, owner, get_conn):
        llamadas.append(server)
        r = resultados.get(server)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(CAL, "_cr", lambda: _CR)
    monkeypatch.setattr(CAL, "piezas_del_agente", lambda conn, pid: list(piezas))
    monkeypatch.setattr(V, "verificar_uno", _verificar)

    class _Espia:
        pass
    _Espia.llamadas = llamadas
    return _Espia


def _ok(server):
    return {"server": server, "belt": "b.mcp.json", "arranca": True,
            "conexion": {"estado": "viva", "causa": None, "tool_usada": "t",
                         "era": "handshake", "version_negociada": "2024-11-05"},
            "credencial": {"estado": "no_aplica"}, "tools_probadas": ["t"]}


def test_la_lapida_manda_no_se_levanta_ni_se_reverifica(monkeypatch):
    """El permiso del usuario gana sobre cualquier medición. Calentar una pieza apagada
    sería levantar justo lo que pidió que no corriera."""
    escritas = []
    V = _fake(monkeypatch,
              entidades=[{"entity_id": "vive", "habilitado": True},
                         {"entity_id": "apagada", "habilitado": False}],
              piezas=[("b.mcp.json", "vive"), ("b.mcp.json", "apagada")],
              resultados={"vive": _ok("vive")}, escritas=escritas)
    r = CAL.calentar("p", owner="u", get_conn=lambda: _Conn())
    assert r["apagadas"] == ["apagada"]
    assert V.llamadas == ["vive"], "no se verificó la apagada"
    assert [e for e, _ in escritas] == ["vive"], "no se escribió sobre la apagada"


def test_una_pieza_que_revienta_no_frena_a_las_demas(monkeypatch):
    """FALLO VISIBLE, JAMÁS MUDO: la que falla viaja con su causa, el resto sigue."""
    escritas = []
    _fake(monkeypatch,
          entidades=[{"entity_id": "a", "habilitado": True},
                     {"entity_id": "b", "habilitado": True},
                     {"entity_id": "c", "habilitado": True}],
          piezas=[("x", "a"), ("x", "b"), ("x", "c")],
          resultados={"a": _ok("a"), "b": RuntimeError("explotó"), "c": _ok("c")},
          escritas=escritas)
    r = CAL.calentar("p", owner="u", get_conn=lambda: _Conn())
    estados = {p["server"]: p["conexion"] for p in r["piezas"]}
    assert estados == {"a": "viva", "b": "rota", "c": "viva"}
    rota = next(p for p in r["piezas"] if p["server"] == "b")
    assert rota["causa"] == "arranque"
    assert len(escritas) == 3, "las tres se persisten, incluida la que falló"


def test_no_se_inventan_filas_para_lo_que_el_registro_no_conoce(monkeypatch):
    """UPDATE jamás upsert. Se reporta por nombre, no se fabrica la fila."""
    escritas = []
    V = _fake(monkeypatch, entidades=[{"entity_id": "conocida", "habilitado": True}],
              piezas=[("x", "conocida"), ("x", "ajena")],
              resultados={"conocida": _ok("conocida")}, escritas=escritas)
    r = CAL.calentar("p", owner="u", get_conn=lambda: _Conn())
    assert r["sin_registro"] == ["ajena"]
    assert V.llamadas == ["conocida"], "ni se la mide"


def test_las_dos_columnas_de_protocolo_se_persisten(monkeypatch):
    escritas = []
    _fake(monkeypatch, entidades=[{"entity_id": "a", "habilitado": True}],
          piezas=[("x", "a")], resultados={"a": _ok("a")}, escritas=escritas)
    CAL.calentar("p", owner="u", get_conn=lambda: _Conn())
    campos = escritas[0][1]
    assert campos["era"] == "handshake"
    assert campos["version_negociada"] == "2024-11-05"


def test_hay_tope_y_lo_que_sobra_se_dice_por_nombre(monkeypatch):
    """Abrir no puede costar más que correr. Lo que no se mide se NOMBRA — un tope
    silencioso se lee como «lo revisé todo» cuando no."""
    ents = [{"entity_id": f"s{i}", "habilitado": True} for i in range(5)]
    escritas = []
    _fake(monkeypatch, entidades=ents, piezas=[("x", f"s{i}") for i in range(5)],
          resultados={f"s{i}": _ok(f"s{i}") for i in range(5)}, escritas=escritas)
    r = CAL.calentar("p", owner="u", get_conn=lambda: _Conn(), max_piezas=2)
    assert [p["server"] for p in r["piezas"]] == ["s0", "s1"]
    assert r["sin_medir"] == ["s2", "s3", "s4"]


def test_sin_piezas_no_explota(monkeypatch):
    _fake(monkeypatch, entidades=[], piezas=[], resultados={}, escritas=[])
    r = CAL.calentar("p", owner="u", get_conn=lambda: _Conn())
    assert r["piezas"] == [] and r["ms"] >= 0
