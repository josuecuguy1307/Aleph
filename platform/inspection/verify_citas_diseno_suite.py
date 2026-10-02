#!/usr/bin/env python3
"""verify_citas_diseno_suite.py — LAS CITAS DEL DISEÑO DE LA SUITE SON VERIFICABLES.

Mismo molde y mismo motivo que `verify_citas_diseno_repair.py`: un número de línea envejece,
y un diseño con citas podridas es PEOR que uno sin citas — parece verificable y no lo es.
Pasó dos veces en la serie de repair (R1 movió 20, R3 movió 14) y las dos las cazó la vara.

Tolerancia de ±3 líneas a propósito: una cita apunta a un BLOQUE, no a un carácter.

    product/backend/.venv/bin/python platform/inspection/verify_citas_diseno_suite.py
"""
import json
from pathlib import Path
import sys

# ⚠️ CONTRA ESTE ARCHIVO, JAMÁS UNA RUTA LITERAL. Acá decía
# `Path("<repo>")`, y eso convirtió a esta vara en una que MIENTE:
# `aleph-main` es un worktree que quedó en otra rama, así que la vara daba 19/19 TODO VERDE
# midiendo un árbol que no era el que custodia — mientras las citas de onshape ya estaban
# podridas en `main`. Apuntada al árbol de verdad daba 4 malas. Es exactamente lo que
# CLAUDE.md prohíbe: «Jamás una ruta literal de una máquina: eso funciona en la del que la
# escribió y en ninguna otra».
R = Path(__file__).resolve().parents[2]
CITAS = [
 ("platform/inspection/CONTRACT-CONEXION-v1.md", 476, "LOS 12 VERBOS"),
 ("platform/inspection/CONTRACT-CONEXION-v1.md", 491, "7 existen"),
 ("platform/inspection/CONTRACT-CONEXION-v1.md", 489, "persist"),
 # onshape · las tres citas viejas decían `personal_token` + Basic + «nunca validado», y
 # las tres eran de un árbol donde el trabajo OAuth estaba sin commitear (§0.2, corregido).
 ("catalog/connectors/onboarding/onshape.json", 4, '"auth_method": "oauth"'),
 ("catalog/connectors/onboarding/onshape.json", 12, "oauth.onshape.com/oauth/authorize"),
 ("catalog/connectors/onboarding/onshape.json", 14, "localhost:8765/oauth/callback"),
 # §3 · la corrección de arquetipos: por qué google_drive sale y qué salvedad arrastra onshape
 ("catalog/connectors/onboarding/google_drive.json", 39, "GOOGLE_CLIENT_ID"),
 ("catalog/connectors/onboarding/google_drive.json", 26, "validated_with_test_key"),
 ("catalog/connectors/onboarding/onshape.json", 71, "loopback_ok"),
 ("platform/safety/guards.py", 58, "def guard_replay"),
 ("platform/inspection/dueno.py", 110, "def encendido"),
 ("platform/inspection/dueno.py", 150, "def huella"),
 ("platform/inspection/transporte.py", 127, "servidor_stdio"),
 ("product/backend/app/phase1/conexiones_verificador.py", 45, "clave-falsa-de-prueba-0000"),
 # ⚠️ Estas dos se movieron +78 líneas cuando el verificador aprendió a resolver una
 # credencial POR VARIABLE (el fix pre-cert de OAuth). La vara las cazó, que es su trabajo:
 # una cita que envejece en silencio convierte al §8 en decoración.
 ("product/backend/app/phase1/conexiones_verificador.py", 576, "def verificar_uno"),
 ("product/backend/app/phase1/conexiones_verificador.py", 589, "no cableado por este verificador"),
 # §4 · EL AGUJERO DEL BYO, AHORA CERRADO (S4). Las cuatro citas viejas apuntaban a las
 # líneas del BUG (`"headers": probe.get("headers")` yendo verbatim al manifest) y esas
 # líneas YA NO EXISTEN. No se borran las filas: se mueven al ARREGLO, porque el §4 sigue
 # siendo la sección que explica por qué esto importa y una cita a un bug muerto envejece
 # peor que ninguna. Esta vara se puso roja al arreglarlo, que es exactamente su trabajo.
 ("platform/inspection/byo_mcp.py", 493, "_headers_seguros(slug, crudos)"),
 ("platform/inspection/byo_mcp.py", 499, "_guardar_secreto(user_id"),
 ("platform/inspection/byo_mcp.py", 500, "manifest = {"),
 ("platform/inspection/byo_mcp.py", 512, "manifest_path.chmod(0o600)"),
 ("product/backend/app/phase1/conexiones_repo.py", 135, "def _sin_secretos"),
 ("reports/step-4.5-e2e/S0-preflight.md", 99, "intermitentemente lento"),
]
malas = 0
for arch, ln, sub in CITAS:
    p = R / arch
    if not p.exists():
        malas += 1
        print(f"  ✗ {arch} NO EXISTE")
        continue
    lineas = p.read_text(errors="replace").splitlines()
    if not any(sub in l for l in lineas[max(0, ln - 4):ln + 3]):
        malas += 1
        print(f"  ✗ {arch}:{ln} — no encuentro {sub!r}")
        print(f"      línea real: {lineas[ln-1][:100]!r}" if ln <= len(lineas) else "      (fuera de rango)")

# Las tres afirmaciones que NO son de archivo:línea sino de AUSENCIA. Una ausencia también
# envejece —alguien puede agregar el archivo mañana— y el diseño se apoya en las tres.
if (R / "infra/.env").exists():
    malas += 1
    print("  ✗ §0.3 dice que `infra/.env` NO existe, y ahora existe")
# §0.2 CORREGIDO · la afirmación se dio vuelta. Antes esto exigía que NO hubiera un MCP de
# onshape; hoy exige que SÍ lo haya, porque el §3 lo lista como el quinto arquetipo y un
# arquetipo sin pieza no se puede certificar. Si alguien lo borra, el diseño queda mintiendo.
if not (R / "product/belts/ingenieria/onshape_server.py").exists():
    malas += 1
    print("  ✗ §3 lista `onshape` como arquetipo y su servidor MCP no existe")
if not any("onshape" in p.read_text(errors="replace")
           for p in (R / "catalog").rglob("*.mcp.json")):
    malas += 1
    print("  ✗ §3 lista `onshape` y ningún belt del catálogo lo declara")
# §3 · google_drive sale porque NO tiene client_id. Si mañana aparece uno literal, la razón
# de la exclusión deja de valer y el documento queda mintiendo — así que también se vigila.
try:
    _gd = json.loads((R / "catalog/connectors/onboarding/google_drive.json").read_text())
    if (_gd.get("oauth") or {}).get("client_id"):
        malas += 1
        print("  ✗ §3 saca a google_drive por no tener client_id, y ahora tiene uno literal")
except Exception:
    malas += 1
    print("  ✗ no pude leer google_drive.json, que el §3 cita")

print(f"\n{len(CITAS) - malas}/{len(CITAS)} citas verifican"
      + (" · TODO VERDE" if not malas else f" · {malas} MALAS"))
sys.exit(0 if not malas else 1)
