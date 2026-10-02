"""test_multiagente.py — el contrato CADENA, medido. [MULTIAGENTE · F1]

Verde = efecto real sobre el módulo real. Cada rojo de acá es uno de los rechazos que
`docs/multiagente.md` §3 promete, y se asierta por CAUSA (el código estable), no por el
texto del mensaje.

Correr:  pytest platform/assembler/test_multiagente.py -v
    o:   python3 platform/assembler/test_multiagente.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))

import multiagente as ma  # noqa: E402


# ── fixtures en disco ───────────────────────────────────────────────────────────

def _hoja(nombre: str) -> dict:
    """Una receta v1 mínima y VÁLIDA (un aleph normal, sin modo)."""
    return {
        "schema_version": "v1",
        "meta": {"name": nombre, "nicho": "general"},
        "model": {"primary": "openai/gpt-oss-120b",
                  "base_url": "https://api.groq.com/openai/v1",
                  "temperature": 0, "max_tokens": 512, "max_turns": 4},
        "belt": {"belt_ref": "platform/assembler/fixtures/belt-calc.mcp.json",
                 "tool_filters": {"calc": ["add"]}},
        "rag": {"enabled": False},
    }


def _globo(slugs, *, modo="cadena", cables=None, tools=True) -> dict:
    belt: dict = {"agent_refs": [f"catalog/agents/{s}.config.json" for s in slugs]}
    belt["tool_filters"] = ({"calc": ["add"]} if tools else {})
    if tools:
        belt["belt_ref"] = "platform/assembler/fixtures/belt-calc.mcp.json"
    if cables is not None:
        belt["agent_links"] = cables
    r = {
        "schema_version": "v1",
        "meta": {"name": "globo", "nicho": "general"},
        "model": {"primary": "openai/gpt-oss-120b",
                  "base_url": "https://api.groq.com/openai/v1",
                  "temperature": 0, "max_tokens": 512, "max_turns": 4},
        "belt": belt,
        "rag": {"enabled": False},
    }
    if modo is not None:
        r["modo"] = modo
    return r


def _repo_con(agentes: dict) -> Path:
    """Un repo_root temporal con catalog/agents/<slug>.config.json escritos."""
    root = Path(tempfile.mkdtemp(prefix="ma-repo-"))
    d = root / "catalog" / "agents"
    d.mkdir(parents=True)
    for slug, receta in agentes.items():
        (d / f"{slug}.config.json").write_text(json.dumps(receta), encoding="utf-8")
    return root


def _causas(recipe) -> list:
    return [e["causa"] for e in ma.validar_forma(recipe)]


# ── 1 · lectura y proyección ────────────────────────────────────────────────────

def test_1_modo_ausente_es_none_y_no_valida_nada():
    """Ausente/null ⇒ el comportamiento de HOY. Cero validación multiagente."""
    r = _hoja("x")
    assert ma.modo_de(r) is None
    assert ma.validar_forma(r) == []
    r["modo"] = None
    assert ma.modo_de(r) is None
    assert ma.validar_forma(r) == []


def test_1b_proyeccion_piezas_aleph():
    """La proyección que la FASE 2 va a dibujar: una sola respuesta a «qué alephs tiene»."""
    r = _globo(["a", "b"])
    piezas = ma.piezas_aleph(r)
    assert [p["type"] for p in piezas] == ["aleph", "aleph"]
    assert [p["slug"] for p in piezas] == ["a", "b"]
    assert piezas[0]["ref"] == "catalog/agents/a.config.json"
    # una receta SIN alephs proyecta cero piezas (no explota)
    assert ma.piezas_aleph(_hoja("x")) == []


def test_1c_slug_uuid_del_exporter():
    """El slug real de producción sale de agent_catalog.agent_ref_for (UUID, no nombre)."""
    ref = "catalog/agents/agent-11111111-2222-4333-8444-555555555555.config.json"
    assert ma.slug_de(ref) == "agent-11111111-2222-4333-8444-555555555555"


# ── 2 · la cadena válida ────────────────────────────────────────────────────────

def test_2_cadena_de_tres_valida_por_orden_de_declaracion():
    assert ma.validar_forma(_globo(["a", "b", "c"])) == []


def test_2b_cadena_de_tres_valida_con_cables_declarados():
    cables = [{"from": "a", "to": "b", "tipo": "entregar"},
              {"from": "b", "to": "c", "tipo": "entregar"}]
    assert ma.validar_forma(_globo(["a", "b", "c"], cables=cables)) == []


def test_2c_MEZCLA_SELLADA_tools_y_sub_alephs_conviven():
    """INVARIANTE §1.2: herramientas Y sub-alephs en el mismo pieces[]."""
    r = _globo(["a", "b"], tools=True)
    assert r["belt"]["tool_filters"]            # tiene tools propias
    assert r["belt"]["agent_refs"]              # y sub-alephs
    assert ma.validar_forma(r) == []


def test_2d_globo_de_uno():
    """«Un Aleph solo es un globo de uno»: cadena de 1 es válida."""
    assert ma.validar_forma(_globo(["a"])) == []


# ── 3 · los rechazos de §3, por CAUSA ───────────────────────────────────────────

def test_3_modo_no_implementado_es_visible():
    for modo in ("orquesta", "oficina", "abanico"):
        errs = ma.validar_forma(_globo(["a", "b"], modo=modo))
        assert [e["causa"] for e in errs] == ["modo_no_implementado"], modo
        assert "todavía no corre" in errs[0]["detalle"]
        assert errs[0]["modo"] == modo


def test_3b_modo_fuera_del_enum():
    assert _causas(_globo(["a"], modo="turbo")) == ["modo_invalido"]


def test_3c_bucle():
    cables = [{"from": "a", "to": "b", "tipo": "entregar"},
              {"from": "b", "to": "a", "tipo": "entregar"}]
    errs = ma.validar_forma(_globo(["a", "b"], cables=cables))
    assert [e["causa"] for e in errs] == ["cadena_ciclo"]
    assert "BUCLE" in errs[0]["detalle"]


def test_3c2_bucle_de_uno():
    cables = [{"from": "a", "to": "a", "tipo": "entregar"}]
    assert "cadena_ciclo" in _causas(_globo(["a"], cables=cables))


def test_3d_bifurcacion():
    cables = [{"from": "a", "to": "b", "tipo": "entregar"},
              {"from": "a", "to": "c", "tipo": "entregar"}]
    errs = ma.validar_forma(_globo(["a", "b", "c"], cables=cables))
    assert [e["causa"] for e in errs] == ["cadena_bifurcacion"]
    assert errs[0]["slug"] == "a" and errs[0]["salidas"] == ["b", "c"]


def test_3d2_bifurcacion_de_entrada():
    cables = [{"from": "a", "to": "c", "tipo": "entregar"},
              {"from": "b", "to": "c", "tipo": "entregar"}]
    errs = ma.validar_forma(_globo(["a", "b", "c"], cables=cables))
    assert [e["causa"] for e in errs] == ["cadena_bifurcacion"]
    assert errs[0]["entradas"] == ["a", "b"]


def test_3e_el_mismo_aleph_dos_veces():
    r = _globo(["a", "b"])
    r["belt"]["agent_refs"].append("catalog/agents/a.config.json")
    errs = ma.validar_forma(r)
    assert [e["causa"] for e in errs] == ["cadena_aleph_repetido"]
    assert errs[0]["repetidos"] == ["a"]


def test_3f_delegar_no_es_un_eslabon_de_cadena():
    cables = [{"from": "a", "to": "b", "tipo": "delegar"}]
    errs = ma.validar_forma(_globo(["a", "b"], cables=cables))
    assert [e["causa"] for e in errs] == ["cadena_tipo_invalido"]


def test_3g_cable_con_clave_extra_el_cierre_es_PORTANTE():
    """Que el set sea cerrado es lo que impide declarar a mano lo que el motor DERIVA."""
    cables = [{"from": "a", "to": "b", "tipo": "entregar", "nucleo": False}]
    assert "cable_clave_no_permitida" in _causas(_globo(["a", "b"], cables=cables))


def test_3h_cable_a_un_aleph_no_declarado():
    cables = [{"from": "a", "to": "fantasma", "tipo": "entregar"}]
    assert "cable_extremo_desconocido" in _causas(_globo(["a", "b"], cables=cables))


def test_3i_desconectada():
    cables = [{"from": "a", "to": "b", "tipo": "entregar"}]   # 'c' queda suelto
    errs = ma.validar_forma(_globo(["a", "b", "c"], cables=cables))
    assert [e["causa"] for e in errs] == ["cadena_desconectada"]


def test_3j_cadena_vacia():
    r = _globo([])
    assert _causas(r) == ["cadena_vacia"]


def test_3k_el_nucleo_no_es_un_eslabon():
    cables = [{"from": ma.NUCLEO, "to": "a", "tipo": "entregar"},
              {"from": "a", "to": "b", "tipo": "entregar"}]
    assert "cadena_nucleo_en_cable" in _causas(_globo(["a", "b"], cables=cables))


def test_3l_tipo_de_cable_invalido():
    cables = [{"from": "a", "to": "b", "tipo": "empujar"}]
    assert "cable_tipo_invalido" in _causas(_globo(["a", "b"], cables=cables))


# ── 4 · el plan: orden + DERIVACIÓN del núcleo ──────────────────────────────────

def test_4_plan_deriva_nucleo_y_entrega():
    root = _repo_con({"a": _hoja("A"), "b": _hoja("B"), "c": _hoja("C")})
    plan = ma.planificar(_globo(["a", "b", "c"]), root)
    assert [e.slug for e in plan.eslabones] == ["a", "b", "c"]
    assert [e.nucleo for e in plan.eslabones] == [True, False, True]   # el del MEDIO no
    assert [e.entrega for e in plan.eslabones] == [False, False, True]
    assert plan.cables_derivados is True
    assert plan.cables == [{"from": "a", "to": "b", "tipo": "entregar"},
                           {"from": "b", "to": "c", "tipo": "entregar"}]


def test_4b_los_cables_MANDAN_sobre_el_orden_de_declaracion():
    root = _repo_con({"a": _hoja("A"), "b": _hoja("B"), "c": _hoja("C")})
    cables = [{"from": "c", "to": "a", "tipo": "entregar"},
              {"from": "a", "to": "b", "tipo": "entregar"}]
    plan = ma.planificar(_globo(["a", "b", "c"], cables=cables), root)
    assert [e.slug for e in plan.eslabones] == ["c", "a", "b"]
    assert [e.nucleo for e in plan.eslabones] == [True, False, True]
    assert plan.cables_derivados is False


def test_4c_globo_de_uno_es_primero_y_ultimo():
    root = _repo_con({"a": _hoja("A")})
    plan = ma.planificar(_globo(["a"]), root)
    assert [(e.nucleo, e.entrega) for e in plan.eslabones] == [(True, True)]


def test_4d_eslabon_que_no_resuelve():
    root = _repo_con({"a": _hoja("A")})
    try:
        ma.planificar(_globo(["a", "b"]), root)
    except ma.CadenaInvalida as exc:
        assert exc.causa == "aleph_no_resuelve"
    else:
        raise AssertionError("un agent_ref inexistente tiene que fallar VISIBLE")


def test_4e_planificar_rechaza_modo_no_implementado():
    root = _repo_con({"a": _hoja("A")})
    try:
        ma.planificar(_globo(["a"], modo="oficina"), root)
    except ma.ModoNoImplementado as exc:
        assert exc.as_dict()["modo"] == "oficina"
        assert "todavía no corre" in exc.detalle
    else:
        raise AssertionError("'oficina' no puede planificar")


# ── 5 · anidamiento FRACTAL y su guard ──────────────────────────────────────────

def test_5_anidamiento_fractal_planifica_el_subplan():
    """Un globo dentro de un globo: el eslabón 'b' ES otra cadena."""
    root = _repo_con({"a": _hoja("A"), "b": _globo(["x", "y"]),
                      "x": _hoja("X"), "y": _hoja("Y")})
    plan = ma.planificar(_globo(["a", "b"]), root)
    assert plan.eslabones[0].subplan is None
    assert plan.eslabones[1].subplan is not None
    assert [e.slug for e in plan.eslabones[1].subplan.eslabones] == ["x", "y"]
    assert plan.eslabones[1].subplan.profundidad == 1


def test_5b_guard_de_PROFUNDIDAD():
    """MAX_PROFUNDIDAD=3 ⇒ el 4º nivel dispara el guard, ANTES de gastar un token."""
    root = _repo_con({
        "n0": _globo(["n1"]), "n1": _globo(["n2"]), "n2": _globo(["n3"]),
        "n3": _globo(["n4"]), "n4": _hoja("N4"),
    })
    try:
        ma.planificar(_globo(["n0"]), root)
    except ma.RecursionExcedida as exc:
        assert exc.causa == "multiagente_profundidad"
        assert str(ma.MAX_PROFUNDIDAD) in exc.detalle
    else:
        raise AssertionError("el guard de profundidad tiene que disparar")


def test_5c_guard_de_CICLO_de_alephs():
    """A contiene B, B contiene A: un globo no puede contenerse a sí mismo."""
    root = _repo_con({"a": _globo(["b"]), "b": _globo(["a"])})
    try:
        ma.planificar(_globo(["a"]), root)
    except ma.RecursionExcedida as exc:
        assert exc.causa == "multiagente_ciclo_de_alephs"
        assert "CIRCULAR" in exc.detalle
    else:
        raise AssertionError("el guard de ciclos tiene que disparar")


def test_5d_dos_agentes_DISTINTOS_con_el_mismo_nombre_NO_son_un_ciclo():
    """La huella es el PATH CANÓNICO, no el meta.name (el bug del spike)."""
    root = _repo_con({"a": _globo(["b"]), "b": _hoja("Research"), "c": _hoja("Research")})
    plan = ma.planificar(_globo(["a", "c"]), root)
    assert [e.slug for e in plan.eslabones] == ["a", "c"]


# ── 6 · LA CORRIDA: entrega-y-suelta + latencia medida ──────────────────────────

def _runner_falso(registro: list, *, falla_en=None):
    def runner(recipe, prompt, eslabon):
        registro.append({"slug": eslabon.slug, "prompt": prompt})
        if falla_en is not None and eslabon.slug == falla_en:
            return {"ok": False, "answer": "", "run_id": f"run-{eslabon.slug}",
                    "error": "explotó"}
        return {"ok": True, "answer": f"{prompt}|{eslabon.slug}",
                "run_id": f"run-{eslabon.slug}", "error": None}
    return runner


def test_6_la_cadena_corre_y_ENTREGA_lo_del_ultimo():
    root = _repo_con({"a": _hoja("A"), "b": _hoja("B"), "c": _hoja("C")})
    reg = []
    out = ma.correr_cadena(_globo(["a", "b", "c"]), "pedido",
                           runner=_runner_falso(reg), repo_root=root)
    assert out["ok"] is True
    # el pedido entra por el PRIMERO; cada uno recibe la SALIDA del anterior, verbatim
    assert [r["prompt"] for r in reg] == ["pedido", "pedido|a", "pedido|a|b"]
    # el ÚLTIMO entrega: su salida ES la respuesta de la cadena
    assert out["respuesta"] == "pedido|a|b|c"
    assert len(out["saltos"]) == 3
    assert [s["run_id"] for s in out["saltos"]] == ["run-a", "run-b", "run-c"]
    assert [s["nucleo"] for s in out["saltos"]] == [True, False, True]
    assert [s["entrega"] for s in out["saltos"]] == [False, False, True]


def test_6b_LATENCIA_POR_SALTO_medida_y_sellada():
    root = _repo_con({"a": _hoja("A"), "b": _hoja("B"), "c": _hoja("C")})
    out = ma.correr_cadena(_globo(["a", "b", "c"]), "p",
                           runner=_runner_falso([]), repo_root=root)
    lats = [s["latencia_ms"] for s in out["saltos"]]
    assert all(isinstance(x, int) and x >= 0 for x in lats), lats
    # el total cubre los tres saltos (no es una suma inventada: se mide aparte)
    assert out["latencia_total_ms"] >= sum(lats) - 1


def test_6c_el_ENLACE_POR_CAMPO_se_estampa_por_salto():
    root = _repo_con({"a": _hoja("A"), "b": _hoja("B")})
    enlaces = []
    ma.correr_cadena(_globo(["a", "b"]), "p", runner=_runner_falso([]), repo_root=root,
                     enlazar=lambda **kw: enlaces.append(kw))
    assert [e["orden"] for e in enlaces] == [0, 1]
    assert [e["run_id"] for e in enlaces] == ["run-a", "run-b"]
    assert all(isinstance(e["latencia_ms"], int) for e in enlaces)


def test_6d_un_eslabon_roto_CORTA_la_cadena():
    """Seguir sería entregarle basura al siguiente y devolver algo que nadie produjo."""
    root = _repo_con({"a": _hoja("A"), "b": _hoja("B"), "c": _hoja("C")})
    reg = []
    out = ma.correr_cadena(_globo(["a", "b", "c"]), "p",
                           runner=_runner_falso(reg, falla_en="b"), repo_root=root)
    assert out["ok"] is False
    assert out["respuesta"] == ""
    assert out["error"]["causa"] == "cadena_eslabon_fallido"
    assert out["error"]["slug"] == "b"
    assert [r["slug"] for r in reg] == ["a", "b"]     # 'c' NUNCA corrió
    assert len(out["saltos"]) == 2


def test_6e_la_cadena_anidada_corre_fractal():
    root = _repo_con({"a": _hoja("A"), "b": _globo(["x", "y"]),
                      "x": _hoja("X"), "y": _hoja("Y")})
    reg = []
    out = ma.correr_cadena(_globo(["a", "b"]), "p",
                           runner=_runner_falso(reg), repo_root=root)
    assert out["ok"] is True
    assert [r["slug"] for r in reg] == ["a", "x", "y"]   # 'b' no corre: 'b' ES x→y
    assert out["respuesta"] == "p|a|x|y"
    assert out["saltos"][1]["anidado"] is True
    assert len(out["saltos"][1]["sub_cadena"]["saltos"]) == 2


def _run_all():
    fallos = 0
    for nombre, fn in sorted(globals().items()):
        if not nombre.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  ✓ {nombre}")
        except Exception as exc:  # noqa: BLE001
            fallos += 1
            print(f"  ✗ {nombre}: {type(exc).__name__}: {exc}")
    print(f"\n{'✓ TODO VERDE' if not fallos else f'✗ {fallos} ROJO(S)'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(_run_all())
