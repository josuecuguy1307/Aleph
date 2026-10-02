#!/usr/bin/env python3
"""
validate_recipes.py — Valida las recetas config.json del Product contra el
SCHEMA v1 ANIDADO aprobado A+A+C (platform/assembler/RECIPE-SCHEMA.md §2/§3).

Es el validador de FORMA del contrato (carril Product). El validador PLANO de
Backend (config_validator.py) fue RETIRADO en la migración a fuente única
(2026-06-15); el validador canónico de Backend es el ANIDADO
(product/backend/app/phase1/recipe_validator.py), que comparte ESTE mismo schema
v1: requeridos del §3.1 y la INVARIANTE de gates §3.5.

Reglas verificadas (RECIPE-SCHEMA.md §3):
  R1  schema_version == "v1"
  R2  Requeridos: meta.name, meta.nicho,
                  model.{primary,base_url,temperature,max_tokens,max_turns},
                  belt.belt_ref, belt.tool_filters,
                  rag.enabled (+ rag.mode si enabled)
  R3  belt.belt_ref es slug de catalogo (NO path absoluto del host) — portabilidad (decision B)
  R4  belt.tool_filters: dict server->lista-de-tools, no vacio (subset curado)
  R5  keys.<p>.byok_ref por referencia (jamas valor en claro): no aparecen claves
      sospechosas de secreto (api_key/secret/token con valor literal)
  R6  INVARIANTE §3.5: si la receta declara gates, money_touch/send solo pueden
      ser "off" o "needs_ok". La omision NO desactiva (el motor los fuerza); poner
      "off" es legal en la receta pero el motor lo ignora para tools clasificadas.
  R7  Nicho-agnostico: ninguna clave de primer/segundo nivel es de un nicho
      (no hay claves tipo "finanzas"/"stata"/"sympy" como CLAVE de schema; lo
      especifico vive en VALORES como tool_filters/meta.nicho).
  R8  Rangos: temperature in [0,2]; max_tokens, max_turns enteros positivos.

Salida: por receta OK/FAIL con detalle. Exit 0 solo si TODAS pasan.
"""
import json
import sys
from pathlib import Path

RECIPES_DIR = Path(__file__).resolve().parent
REPO_ROOT = RECIPES_DIR.parent.parent

# Claves de schema permitidas (forma anidada v1). Cualquier otra clave de schema
# que sea nombre-de-nicho violaria R7.
TOP_LEVEL = {"schema_version", "meta", "model", "belt", "framing", "rag", "keys", "gates"}
SUSPECT_SECRET_KEYS = {"api_key", "apikey", "secret", "password", "token"}


def _err(msg, errors):
    errors.append(msg)


def validate_recipe(cfg: dict) -> list[str]:
    errors: list[str] = []

    # R1
    if cfg.get("schema_version") != "v1":
        _err(f"R1 schema_version debe ser 'v1', es {cfg.get('schema_version')!r}", errors)

    # R7 — ninguna clave de primer nivel fuera del set (atrapa claves de nicho)
    for k in cfg:
        if k not in TOP_LEVEL:
            _err(f"R7 clave de primer nivel no permitida (no nicho-agnostica?): '{k}'", errors)

    # R2 — meta
    meta = cfg.get("meta") or {}
    if not meta.get("name"):
        _err("R2 falta meta.name", errors)
    if not meta.get("nicho"):
        _err("R2 falta meta.nicho", errors)

    # R2 — model
    model = cfg.get("model") or {}
    for f in ("primary", "base_url", "temperature", "max_tokens", "max_turns"):
        if f not in model or model[f] is None:
            _err(f"R2 falta model.{f}", errors)

    # R8 — rangos
    if isinstance(model.get("temperature"), (int, float)):
        if not (0.0 <= model["temperature"] <= 2.0):
            _err(f"R8 model.temperature fuera de [0,2]: {model['temperature']}", errors)
    for f in ("max_tokens", "max_turns"):
        v = model.get(f)
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            _err(f"R8 model.{f} debe ser entero positivo: {v!r}", errors)

    # R2/R3/R4 — belt
    belt = cfg.get("belt") or {}
    belt_ref = belt.get("belt_ref")
    if not belt_ref:
        _err("R2 falta belt.belt_ref", errors)
    else:
        # R3 portabilidad: slug de catalogo, no path absoluto del host
        if belt_ref.startswith("/") or ":\\" in belt_ref or belt_ref.startswith("~"):
            _err(f"R3 belt.belt_ref no debe ser path absoluto del host (portabilidad): {belt_ref!r}", errors)
        if not belt_ref.startswith("catalog/belts/"):
            _err(f"R3 belt.belt_ref debe ser slug de catalogo 'catalog/belts/<nicho>.md': {belt_ref!r}", errors)
    tf = belt.get("tool_filters")
    if not isinstance(tf, dict) or not tf:
        _err("R4 belt.tool_filters debe ser dict no vacio (subset curado)", errors)
    else:
        for srv, tools in tf.items():
            if not isinstance(tools, list) or not tools:
                _err(f"R4 belt.tool_filters['{srv}'] debe ser lista no vacia", errors)

    # R2 — rag
    rag = cfg.get("rag") or {}
    if "enabled" not in rag:
        _err("R2 falta rag.enabled", errors)
    elif rag["enabled"] and not rag.get("mode"):
        _err("R2 rag.enabled=true requiere rag.mode", errors)

    # R5 — BYOK por referencia, jamas valor en claro
    keys = cfg.get("keys") or {}
    for provider, spec in keys.items():
        if not isinstance(spec, dict) or "byok_ref" not in spec:
            _err(f"R5 keys['{provider}'] debe ser {{byok_ref: 'keys:...'}}", errors)
        else:
            ref = spec["byok_ref"]
            if not isinstance(ref, str) or not ref.startswith("keys:"):
                _err(f"R5 keys['{provider}'].byok_ref debe apuntar a 'keys:<provider>': {ref!r}", errors)
        # ninguna clave de secreto literal dentro del spec
        if isinstance(spec, dict):
            for sk in spec:
                if sk.lower() in SUSPECT_SECRET_KEYS:
                    _err(f"R5 keys['{provider}'] no debe contener secreto literal '{sk}'", errors)

    # R6 — INVARIANTE de gates §3.5
    gates = cfg.get("gates") or {}
    for g in ("money_touch", "send"):
        if g in gates and gates[g] not in ("off", "needs_ok"):
            _err(f"R6 gates.{g} debe ser 'off' o 'needs_ok': {gates[g]!r}", errors)

    return errors


def main() -> int:
    recipes = sorted(RECIPES_DIR.glob("*.config.json"))
    if not recipes:
        print("No se encontraron recetas *.config.json", file=sys.stderr)
        return 2

    all_ok = True
    print(f"Validando {len(recipes)} recetas contra el SCHEMA v1 anidado (A+A+C)\n")
    for path in recipes:
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"FAIL  {path.name}: JSON invalido — {e}")
            all_ok = False
            continue
        errors = validate_recipe(cfg)
        nicho = (cfg.get("meta") or {}).get("nicho", "?")
        belt_ref = (cfg.get("belt") or {}).get("belt_ref", "?")
        n_servers = len((cfg.get("belt") or {}).get("tool_filters", {}))
        if errors:
            print(f"FAIL  {path.name}  (nicho={nicho})")
            for e in errors:
                print(f"        - {e}")
            all_ok = False
        else:
            print(f"OK    {path.name}  nicho={nicho:13s} belt_ref={belt_ref:28s} servers={n_servers}")

    print()
    if all_ok:
        print(f"RESULTADO: las {len(recipes)} recetas son VALIDAS contra el schema v1 anidado.")
        return 0
    print("RESULTADO: hay recetas invalidas (ver FAIL arriba).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
