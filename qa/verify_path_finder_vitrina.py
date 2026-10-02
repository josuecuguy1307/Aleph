"""verify_path_finder_vitrina.py — el PATH de Finder ya no vacía la vitrina.

GAP §Tauri-b (reports/step5/GAP-DEV-DESKTOP.md): una .app lanzada desde Finder hereda el
PATH mínimo de launchd (`/usr/bin:/bin:/usr/sbin:/sbin`). El sidecar lo hereda (lib.rs no
setea env al spawnear), así que `shutil.which("npx"|"uvx"|"node"|"docker")` da None y la
vitrina honesta (atoms_router.server_runtime → estado_honesto) degrada 31/54 piezas a
"Corre en tu máquina". Medición del GAP en la .app instalada:

    shell  = local  9 · ready 31 · connectable 14   (54)
    Finder = local 40 · ready 11 · connectable  3   (54)   ← 31 piezas degradadas

El fix vive en el BOOT del sidecar (deploy/fase4/sidecar_serve.py::ensure_user_path):
resuelve el PATH real del usuario UNA vez (login-shell + dirs estándar + shims nvm/pyenv)
y lo funde en os.environ["PATH"], de modo que `shutil.which` —y por lo tanto la vitrina—
clasifiquen IGUAL que en un shell.

Este test corre el CÓDIGO REAL de las dos puntas (el clasificador `collect_atoms` y el
resolvedor `ensure_user_path`) contra el árbol real, simulando el entorno de Finder
vaciando el PATH a lo que hereda una GUI app. Sin mocks: si el fix desaparece o el
clasificador cambia, este test se entera.

    ./product/backend/.venv/bin/python qa/verify_path_finder_vitrina.py
"""
from __future__ import annotations

import os
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "platform"))
sys.path.insert(0, str(ROOT / "product" / "backend"))
sys.path.insert(0, str(ROOT / "deploy" / "fase4"))

from app.phase1.atoms_router import collect_atoms  # noqa: E402
import sidecar_serve as S  # noqa: E402  (el boot del sidecar; trae ensure_user_path)

# el PATH que hereda CUALQUIER .app lanzada desde Finder (launchd), medido en el GAP.
FINDER_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {label}")
    else:
        fail += 1
        print(f"  ✗ {label}  {detail}")


def _states() -> Counter:
    """La clasificación de la vitrina AHORA (lee os.environ['PATH'] en vivo vía shutil.which)."""
    return Counter(a["state"] for a in collect_atoms())


def bloque_vitrina():
    print("\n[1] VITRINA · Finder no degrada el catálogo (boot resuelve el PATH real)")
    path_real = os.environ.get("PATH", "")
    try:
        # ── BASELINE: como se ve en un shell (el PATH del test tiene las herramientas) ──
        baseline = _states()
        total = sum(baseline.values())
        check(f"la vitrina devuelve piezas ({total} átomos)", total > 0, f"total={total}")

        # ── FINDER, SIN FIX: se vacía (npx/uvx/node/docker desaparecen del PATH) ──
        os.environ["PATH"] = FINDER_PATH
        S.resolve_user_path.cache_clear()
        finder_raw = _states()

        degrada = finder_raw.get("local", 0) > baseline.get("local", 0)
        if degrada:
            check("bug reproducido: en Finder degradan piezas a 'local' (corre en tu máquina)",
                  finder_raw.get("ready", 0) < baseline.get("ready", 0),
                  f"shell={dict(baseline)} finder={dict(finder_raw)}")
            print(f"      → {finder_raw.get('local',0)-baseline.get('local',0)}/{total} "
                  f"piezas se degradaban sin el fix")
        else:
            # entorno sin runners de paquete fuera del PATH mínimo (p.ej. CI pelado):
            # no hay degradación que reproducir, pero la paridad del fix se prueba igual.
            print("      • nota: este entorno no tiene npx/uvx/etc. fuera del PATH mínimo; "
                  "no se puede reproducir la degradación acá (la paridad del fix se prueba igual)")

        # ── FINDER + FIX: el boot resuelve el PATH real → clasifica IGUAL que el shell ──
        S.resolve_user_path.cache_clear()
        applied = S.ensure_user_path()
        finder_fixed = _states()

        check("con el fix, la vitrina clasifica IGUAL que en shell (misma composición)",
              finder_fixed == baseline,
              f"shell={dict(baseline)} finder+fix={dict(finder_fixed)}")
        check("  → ni una pieza queda degradada de más",
              finder_fixed.get("local", 0) == baseline.get("local", 0),
              f"local shell={baseline.get('local',0)} vs fix={finder_fixed.get('local',0)}")

        # concreto: los runners que Finder esconde vuelven a resolverse tras el fix
        for tool in ("npx", "uvx"):
            # sólo se exige si la herramienta EXISTE en la máquina (fuera del PATH mínimo)
            en_finder = shutil.which(tool, path=FINDER_PATH)
            if en_finder:
                continue  # ya estaba en el PATH mínimo → nada que recuperar
            resuelto = bool(shutil.which(tool))
            existe = _tool_existe(tool)
            if existe:
                check(f"tras el fix, `{tool}` vuelve a resolverse (estaba escondido por Finder)",
                      resuelto, f"which({tool})={shutil.which(tool)!r}")

        # el fix SÓLO AGREGA: nunca puede sacar los dirs del sistema (no regresiona nada)
        dirs = applied.split(os.pathsep)
        check("el PATH resuelto conserva los dirs del sistema (/usr/bin:/bin) — sólo agrega",
              "/usr/bin" in dirs and "/bin" in dirs, f"applied={applied[:120]}…")
    finally:
        os.environ["PATH"] = path_real
        S.resolve_user_path.cache_clear()


def _tool_existe(tool: str) -> bool:
    """¿La herramienta existe en ALGÚN lado de la máquina (fuera del PATH mínimo)? Se
    consulta al PATH real del usuario, no al del proceso (que estamos manipulando)."""
    S.resolve_user_path.cache_clear()
    real = S.resolve_user_path()
    return bool(shutil.which(tool, path=real))


def bloque_cacheado():
    print("\n[2] RESOLUCIÓN · cacheada (una vez por boot, no por request)")
    S.resolve_user_path.cache_clear()
    a = S.resolve_user_path()
    b = S.resolve_user_path()
    info = S.resolve_user_path.cache_info()
    check("resolve_user_path está cacheada (el subproceso al shell corre UNA vez)",
          info.hits >= 1 and info.misses == 1, f"cache_info={info}")
    check("  → y da el mismo resultado estable", a == b)


def bloque_idempotente():
    print("\n[3] APLICAR · idempotente y aditivo")
    path_real = os.environ.get("PATH", "")
    try:
        os.environ["PATH"] = FINDER_PATH
        S.resolve_user_path.cache_clear()
        p1 = S.ensure_user_path()
        p2 = S.ensure_user_path()
        check("ensure_user_path es idempotente (llamarlo 2 veces no cambia el PATH)", p1 == p2)
        check("  → y el resultado incluye el PATH mínimo heredado (no lo pierde)",
              "/usr/bin" in p2.split(os.pathsep))
    finally:
        os.environ["PATH"] = path_real
        S.resolve_user_path.cache_clear()


def bloque_boot_lo_llama():
    print("\n[4] BOOT · el sidecar realmente lo invoca (predicado que nadie llama = inútil)")
    src = Path(S.__file__).read_text(encoding="utf-8")
    # main() tiene que llamar ensure_user_path() ANTES de importar la app.
    idx_call = src.find("ensure_user_path()")
    idx_app = src.find("from app.main import app")
    check("main() invoca ensure_user_path()", idx_call != -1)
    check("  → y lo hace ANTES de importar la app (para que la vitrina ya vea el PATH bueno)",
          idx_call != -1 and idx_app != -1 and idx_call < idx_app,
          f"call@{idx_call} vs import@{idx_app}")


def main():
    bloque_vitrina()
    bloque_cacheado()
    bloque_idempotente()
    bloque_boot_lo_llama()
    print(f"\n{ok}/{ok + fail} verdes")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
