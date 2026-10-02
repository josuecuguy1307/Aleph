#!/usr/bin/env bash
# preparar_arbol.sh — arma el ÁRBOL DE DEPLOY del plano de control. Step 5 · P11.
#
# Copia SÓLO lo que el servidor necesita a un directorio aparte, listo para ser un
# repo privado con UN commit huérfano. El repo de desarrollo no se toca.
#
# POR QUÉ HISTORIAL LIMPIO Y NO UN MIRROR: el repo de dev tiene 601 commits y al menos
# dos claves de Stripe con forma real en su historia. Escanear 601 commits es el bloque
# de safeguards (más adelante en la cola); no llevar historia lo hace innecesario acá.
#
#   bash deploy/preparar_arbol.sh [destino]     (default: ../aleph-deploy)
set -euo pipefail
cd "$(dirname "$0")/.."
ORIGEN="$(pwd)"
DESTINO="${1:-$(cd .. && pwd)/aleph-deploy}"

echo "origen  : $ORIGEN"
echo "destino : $DESTINO"
# PRESERVAR el .git: este script se corre MUCHAS veces (cada cambio del backend se
# regenera y se pushea). Un `rm -rf` del destino entero se lleva el repo y con él el
# remote y la historia del deploy — pasó una vez, no vuelve a pasar.
if [ -d "$DESTINO/.git" ]; then
  echo "(preservando .git existente)"
  find "$DESTINO" -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +
else
  rm -rf "$DESTINO"
  mkdir -p "$DESTINO"
fi

# ── LO QUE VIAJA ───────────────────────────────────────────────────────────────
# Exactamente lo que el Dockerfile copia, más el propio deploy/.
copiar() {
  local ruta="$1"
  [ -e "$ORIGEN/$ruta" ] || { echo "  ⚠ no existe, salteado: $ruta"; return; }
  mkdir -p "$DESTINO/$(dirname "$ruta")"
  # ⛔ 'secrets/' y '*.key': la clave Fernet de DEV (platform/db/secrets/enc.key) viajaba
  # al artefacto, quedaba COMMITEADA en ALEPH-PROD y el Dockerfile la horneaba en una capa
  # de imagen. Nunca se usó — PUPPET_DB_ENC_KEY está en el panel de Render y gana — pero
  # un artefacto no tiene por qué contener la clave con la que dev cifra sus BYOK.
  rsync -a --quiet \
    --exclude '__pycache__/' --exclude '*.pyc' --exclude '.pytest_cache/' \
    --exclude '.venv/' --exclude 'node_modules/' --exclude '.DS_Store' \
    --exclude 'data/' --exclude 'secrets/' --exclude '*.key' \
    "$ORIGEN/$ruta" "$DESTINO/$(dirname "$ruta")/"
  echo "  ✓ $ruta"
}

echo "── copiando lo que el servidor necesita ──"
copiar product/backend/app
copiar product/backend/requirements.txt
copiar platform
copiar catalog
copiar product/belts
copiar deploy

# ── LO QUE NO VIAJA (explícito, para que se vea la decisión) ───────────────────
# reports/ org/ qa/ missions/ eval/ audit/ .claude/ backups/ onboarding/ infra/
# i18n/ product/app/ product/workshop/ product/recipes/ product/tutor-stem/
# + los ~30 .md internos de la raíz + telegram_chatbot.py + voice_assistant.py
#
# product/app NO viaja: es el CLIENTE (El Cuarto, La Sala), que corre local. Que el
# plano de control no lo tenga es la frontera del negocio hecha filesystem.

# ── tests fuera del artefacto ──────────────────────────────────────────────────
# El servidor no corre tests; los de platform/ viajarían de contrabando dentro del
# paquete. Se sacan del árbol de deploy (siguen en el repo de dev, intactos).
# 'test*' (no 'test_*'): existe tests_gates.py en plural, y el filtro angosto lo
# dejaba pasar con sus fixtures de claves FALSAS adentro — el scan las marcó y con
# razón: un artefacto no tiene por qué contener strings con forma de credencial.
find "$DESTINO" -name 'test*.py' -delete
find "$DESTINO" -name 'selftest*.py' -delete
find "$DESTINO" -name 'verify*.py' -delete
find "$DESTINO" -name 'verify*.mjs' -delete
find "$DESTINO" -name 'probe_*.py' -delete
find "$DESTINO" -name 'sonda_*.py' -delete
find "$DESTINO" -type d -name 'fixtures' -prune -exec rm -rf {} + 2>/dev/null || true

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

cat > "$DESTINO/README.md" <<'EOF'
# aleph-control-plane

Plano de control de Aleph: webhook de pagos, check de tier y Motor B (construcción).
**Repo PRIVADO** — contiene el motor, que es la IP del producto.

Generado desde el árbol de desarrollo con `deploy/preparar_arbol.sh`. No se edita a
mano: los cambios se hacen en el repo de desarrollo y se regenera.

Deploy: Render (Docker, `deploy/Dockerfile`, health check `/health`).
Los secretos van por el panel de Render, jamás en este repo.
EOF

echo
echo "── tamaño del árbol de deploy ──"
du -sh "$DESTINO"
echo "archivos: $(find "$DESTINO" -type f | wc -l | tr -d ' ')"
