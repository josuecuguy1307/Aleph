#!/usr/bin/env bash
# preparar_cliente.sh — arma el ÁRBOL DEL CLIENTE (el .exe local-first). Casa 2 · Fase 4 · 4.2.b
#
# INVERSO de preparar_arbol.sh (que arma el plano de control). Copia una ALLOWLIST a un árbol
# limpio (NO excluye de uno sucio). La frontera NO es una lista a mano: DERIVA de código —
#   · el MOAT que NO viaja = `zones.stays()` (FORGE de platform/inspection/zones.py)
#   · el control-plane que NO viaja = las tablas `TABLAS_CONTROL` de platform/role.py
#     (billing/subscriptions) → sus dueños (billing, platform/payments) + los routers Motor B.
# Principio D-A: el moat se retiene por AUSENCIA, no por flag.
#
#   bash deploy/preparar_cliente.sh [destino]     (default: ../aleph-client)
set -euo pipefail
cd "$(dirname "$0")/.."
ORIGEN="$(pwd)"
DESTINO="${1:-$(cd .. && pwd)/aleph-client}"
VENV_PY="${PUPPET_PY:-$ORIGEN/product/backend/.venv/bin/python}"

echo "origen  : $ORIGEN"
echo "destino : $DESTINO"
if [ -d "$DESTINO/.git" ]; then
  echo "(preservando .git existente)"
  find "$DESTINO" -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +
else
  rm -rf "$DESTINO"
  mkdir -p "$DESTINO"
fi

# ── LO QUE VIAJA (el cliente local-first: UI + núcleo + Capa 0) ────────────────────
copiar() {
  local ruta="$1"
  [ -e "$ORIGEN/$ruta" ] || { echo "  ⚠ no existe, salteado: $ruta"; return; }
  mkdir -p "$DESTINO/$(dirname "$ruta")"
  rsync -a --quiet \
    --exclude '__pycache__/' --exclude '*.pyc' --exclude '.pytest_cache/' \
    --exclude '.venv/' --exclude 'node_modules/' --exclude '.DS_Store' \
    --exclude 'data/' --exclude 'secrets/' --exclude '*.key' --exclude '.git/' \
    "$ORIGEN/$ruta" "$DESTINO/$(dirname "$ruta")/"
  echo "  ✓ $ruta"
}

echo "── copiando la allowlist del cliente ──"
copiar product/app                      # UI: El Cuarto, La Sala, serve.py + Capa 0 (design/vendor)
copiar product/backend/app              # backend local-first
copiar product/backend/requirements.txt
copiar platform                         # role, aleph_paths, db, assembler, gates, connectors, safety, flywheel, inspection
copiar catalog
copiar product/belts

# ── [4.4.3] LOS 3 BUILDS por ALEPH_BUILD ──────────────────────────────────────────
# public/dev → ships() (el MOAT no viaja: seguridad por AUSENCIA). founder → ships()+stays()
# (el MOAT viaja + Motor B HTTP local). billing/payments = CONTROL-PLANE, jamás en el cliente.
ALEPH_BUILD="${ALEPH_BUILD:-public}"
case "$ALEPH_BUILD" in
  public|founder|dev) ;;
  *) echo "✗ ALEPH_BUILD inválido: '$ALEPH_BUILD' (esperado: public|founder|dev)"; exit 1 ;;
esac
echo "── ALEPH_BUILD=$ALEPH_BUILD ──"

if [ "$ALEPH_BUILD" = "founder" ]; then
  echo "── founder: el MOAT VIAJA (ships()+stays()) — Motor B LOCAL ──"
else
  # ── EL MOAT NO VIAJA: inspection.stays() (FORGE) — DERIVADO de zones, no lista a mano ──
  echo "── excluyendo el moat (zones.stays()) ──"
  PYTHONPATH="$ORIGEN/platform" "$VENV_PY" - "$DESTINO" <<'PY'
import os, sys
from inspection import zones
insp = os.path.join(sys.argv[1], "platform", "inspection")
n = 0
for m in sorted(zones.stays()):
    p = os.path.join(insp, m + ".py")
    if os.path.exists(p):
        os.remove(p); n += 1
# subdirs enteramente-forge quedan vacíos (o con __pycache__) → limpiar los que quedaron sin .py
for root, dirs, files in os.walk(insp, topdown=False):
    if root == insp:
        continue
    if not any(f.endswith(".py") for f in files):
        # sólo si NO quedó ningún .py (todo el subdir era FORGE)
        import shutil
        if not any(os.path.exists(os.path.join(root, x)) and x.endswith(".py") for x in os.listdir(root)):
            shutil.rmtree(root, ignore_errors=True)
print(f"  ⊘ {n} módulos FORGE removidos (zones.stays())")
PY
fi

# ── Motor B HTTP: viaja SÓLO en founder (forja local); control-plane (billing) NUNCA ──
echo "── excluyendo routers según build ──"
if [ "$ALEPH_BUILD" != "founder" ]; then
  for f in forge_router inspect_router session_router mesa_router; do
    rm -f "$DESTINO/product/backend/app/phase1/$f.py" && echo "  ⊘ phase1/$f.py (Motor B HTTP)"
  done
fi
for f in billing_router billing; do
  rm -f "$DESTINO/product/backend/app/phase1/$f.py" && echo "  ⊘ phase1/$f.py (control-plane)"
done
rm -rf "$DESTINO/platform/payments" && echo "  ⊘ platform/payments/ (procesador de cobros)"

# ── HARNESS / PROBE / PASSWORD fuera (higiene del artefacto) ───────────────────────
echo "── higiene (harness/probe/password fuera) ──"
find "$DESTINO" -name 'test*.py' -delete
find "$DESTINO" -name 'selftest*.py' -delete
find "$DESTINO" -name 'verify*.py' -delete
find "$DESTINO" -name 'verify*.mjs' -delete
find "$DESTINO" -name 'probe_*.py' -delete
find "$DESTINO" -name 'sonda_*.py' -delete
find "$DESTINO" -name '__probe_*.html' -delete
find "$DESTINO" -type d -name 'fixtures' -prune -exec rm -rf {} + 2>/dev/null || true
find "$DESTINO" -type d -name '_exploraciones' -prune -exec rm -rf {} + 2>/dev/null || true

# ── [Casa 2 · Fase 4 · 4.3+4.4.3] BAKE la identidad de build (public|founder|dev) ──
# build_id.py lee aleph_build_id.ALEPH_BUILD y GANA sobre la env → el usuario NO puede degradar
# el build a dev y regalarse el premium-local (S3: gating en compilación, no en runtime). El
# founder lleva el moat + muro OFF; el public jamás debe hornearse founder (lo garantiza el input).
cat > "$DESTINO/platform/aleph_build_id.py" <<EOF
# GENERADO por preparar_cliente.sh — NO editar. El build type HORNEADO en el artefacto.
ALEPH_BUILD = "$ALEPH_BUILD"
EOF
echo "  ✓ platform/aleph_build_id.py (ALEPH_BUILD=$ALEPH_BUILD, baked)"

cat > "$DESTINO/.gitignore" <<'EOF'
.env
*.enc
*.key
secrets/
__pycache__/
*.pyc
.venv/
data/
EOF

echo
echo "── tamaño del árbol del cliente ──"
du -sh "$DESTINO"
echo "archivos: $(find "$DESTINO" -type f | wc -l | tr -d ' ')"
echo "verify_*.mjs restantes: $(find "$DESTINO" -name 'verify_*.mjs' | wc -l | tr -d ' ')  (debe ser 0)"
echo "forge modules restantes: $(find "$DESTINO/platform/inspection" -name '*.py' 2>/dev/null | wc -l | tr -d ' ') archivos en inspection/"
