#!/usr/bin/env python3
"""verify_vocabulario.py — SUITE DE CONFORMIDAD de la forma `aleph.broker/1`.

Pura: sin red, sin disco, sin subprocess. Lo que asserta es que la FORMA sostiene las
decisiones que el pool toma con ella — no que los campos existan.

    python3 -m assembler.cli_brain.broker.verify_vocabulario
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from assembler.cli_brain.broker.vocabulario import (   # noqa: E402
    FORMA, Capabilities, Discovery, Harness, Session, DUENO_DESCONOCIDO,
    dueno_de_clave, huella_de_config)

_FALLOS, _OK = [], 0


def ok(c, t, d=""):
    global _OK
    if c:
        _OK += 1
        print(f"  ✅ {t}")
    else:
        _FALLOS.append(t)
        print(f"  ❌ {t}" + (f"\n      → {d}" if d else ""))


def c1_el_dueno_sale_de_la_clave():
    print("\n[C1] el dueño sale de la clave del borde, y sin clave NO se comparte")
    # EL FORMATO ES EL REAL: `router._clave_de_conversacion` arma "<ws>:<user>:<peldaño>:<v>"
    ok(dueno_de_clave("ciencia:u-42:chat:abc#h1") == "u-42",
       "clave con forma de borde → el usuario del campo 2",
       dueno_de_clave("ciencia:u-42:chat:abc#h1"))
    ok(dueno_de_clave("cualquier-cosa") == "cualquier-cosa",
       "clave con otra forma → la clave ENTERA (comparte sólo consigo misma)")
    ok(dueno_de_clave("ws:-:chat:x") == "ws:-:chat:x",
       "usuario '-' (el placeholder del borde) NO es un dueño: cae a la clave entera")
    a = dueno_de_clave("", semilla="turno-A")
    b = dueno_de_clave("", semilla="turno-B")
    ok(a != b and DUENO_DESCONOCIDO in a,
       "sin clave → dueño IRREPETIBLE por turno (dos anónimos no comparten)", f"{a} vs {b}")


def c2_la_clave_del_pool_separa():
    print("\n[C2] la clave del pool separa por dueño, por CLI y por config")
    h = huella_de_config({"cli": "x", "modelo": "m"})
    base = Harness("grok_cli", "ana", h)
    otro_dueno = Harness("grok_cli", "beto", h)
    otro_cli = Harness("codex_cli", "ana", h)
    otra_cfg = Harness("grok_cli", "ana", huella_de_config({"cli": "x", "modelo": "OTRO"}))
    k = base.clave_de_pool("chat1", True)
    ok(k != otro_dueno.clave_de_pool("chat1", True), "dueño distinto ⇒ clave distinta")
    ok(k != otro_cli.clave_de_pool("chat1", True), "CLI distinto ⇒ clave distinta")
    ok(k != otra_cfg.clave_de_pool("chat1", True), "config distinta ⇒ clave distinta")
    ok(k == base.clave_de_pool("chat2", True),
       "harness que MULTIPLEXA: dos charlas comparten proceso")
    ok(base.clave_de_pool("chat1", False) != base.clave_de_pool("chat2", False),
       "harness que NO multiplexa: cada charla su proceso")


def c3_la_huella_distingue_lo_que_debe():
    print("\n[C3] la huella distingue lo que se ARRASTRA — las tres cosas medidas")
    # 1 · la jaula de codex
    con = huella_de_config({"cli": "codex", "sandbox": "read-only"})
    sin = huella_de_config({"cli": "codex"})
    vacio = huella_de_config({"cli": "codex", "sandbox": None})
    ok(con != sin, "codex: con `sandbox` y sin `sandbox` son procesos distintos")
    ok(sin != vacio,
       "«no lo pasé» y «lo pasé en None» hashean DISTINTO (son dos jaulas distintas)")
    # 2 · el perfil de grok
    ok(huella_de_config({"cli": "grok", "perfil": "/a/aleph-zero.md"})
       != huella_de_config({"cli": "grok", "perfil": ""}),
       "grok: con perfil y sin perfil son procesos distintos (21,7k vs 32,9k tokens)")
    # 3 · los MCP de codex
    ok(huella_de_config({"cli": "codex", "mcp_apagados": ["a", "b"]})
       != huella_de_config({"cli": "codex", "mcp_apagados": ["a"]}),
       "codex: distinta lista de MCP apagados ⇒ proceso distinto")
    ok(huella_de_config({"m": 1, "n": 2}) == huella_de_config({"n": 2, "m": 1}),
       "el ORDEN de las claves no cambia la huella (si no, cada turno sería un proceso)")


def c4_capabilities_deciden_sin_nombres():
    print("\n[C4] las capacidades alcanzan para decidir SIN mirar el provider_id")
    from assembler.cli_brain.broker.capa import ADAPTADORES
    faltan = []
    for pid, cls in ADAPTADORES.items():
        c = cls.CAPS
        if not isinstance(c, Capabilities):
            faltan.append(f"{pid}: CAPS no es Capabilities")
        if c.reporta_usage and not c.campo_cache_lectura:
            faltan.append(f"{pid}: dice reportar usage y no nombra su campo de caché")
    ok(not faltan, "los tres adaptadores declaran capacidades completas", "; ".join(faltan))
    # el campo de caché NO puede ser el mismo inventado para todos: fundirlos fue el defecto
    campos = {cls.CAPS.campo_cache_lectura for cls in ADAPTADORES.values()}
    ok("cached_input_tokens" in campos and "cache_read_input_tokens" in campos,
       "el campo de caché es el de CADA proveedor, no uno inventado", str(campos))
    multi = {pid: cls.CAPS.multiplexa_sesiones for pid, cls in ADAPTADORES.items()}
    ok(multi.get("claude_cli") is False,
       "claude declara que NO multiplexa (un stdin = una conversación)", str(multi))
    ok(multi.get("grok_cli") is True and multi.get("codex_cli") is True,
       "grok y codex declaran que SÍ (session/new · thread/start)", str(multi))


def c5_discovery_describe_sin_spawnear():
    print("\n[C5] Discovery describe y NO spawnea")
    d = Discovery()
    ok(d.soporta("grok_cli") is False, "un Discovery vacío no soporta nada")
    d.registrar("grok_cli", Capabilities(True, True, False, True, "x", "y"))
    ok(d.soporta("grok_cli") and d.capacidades("grok_cli").campo_cache_lectura == "x",
       "registrar y consultar")
    ok(d.como_dict()["forma"] == FORMA, "el censo declara la FORMA")
    from assembler.cli_brain.broker.capa import DESCUBRIMIENTO
    ok(set(DESCUBRIMIENTO.harnesses) == {"grok_cli", "codex_cli", "claude_cli"},
       "el censo real trae los tres", str(list(DESCUBRIMIENTO.harnesses)))


def c6_la_session_no_filtra_al_dueno():
    print("\n[C6] la Session lleva dueño y NO lo publica")
    s = Session("chat1", "ana", "grok_cli")
    d = s.como_dict()
    ok("dueno" not in d, "el dueño NO sale en `como_dict` (es identidad, no telemetría)",
       str(d))
    ok(d.get("tiene_dueno") is True, "pero se puede saber que lo tiene")


CASOS = [c1_el_dueno_sale_de_la_clave, c2_la_clave_del_pool_separa,
         c3_la_huella_distingue_lo_que_debe, c4_capabilities_deciden_sin_nombres,
         c5_discovery_describe_sin_spawnear, c6_la_session_no_filtra_al_dueno]


def main() -> int:
    print("=" * 74)
    print(f"CONFORMIDAD · {FORMA}")
    print("=" * 74)
    for c in CASOS:
        c()
    print("\n" + "-" * 74)
    print(f"{_OK} verdes · {len(_FALLOS)} rojas")
    for f in _FALLOS:
        print(f"   ROJA: {f}")
    return 1 if _FALLOS else 0


if __name__ == "__main__":
    sys.exit(main())
