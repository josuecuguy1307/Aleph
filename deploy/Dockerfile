# Plano de control de Aleph — Step 5 · Casa 1 · P11 (Render, free tier).
#
# QUÉ CORRE ACÁ (y sólo esto): lo que por diseño NO viaja a la máquina del usuario —
# el webhook del procesador de pagos, el check de tier, y el Motor B de construcción
# (server-side = la IP). El cliente (El Cuarto, La Sala) sigue siendo local.
#
# NO ES el build del producto: eso es Casa 2 y es otra cosa. Esto es el servidor.

FROM python:3.13-slim

# psycopg2-binary y las libs de export son ruedas puras (requirements lo eligió así a
# propósito), pero markitdown/pypdf tocan zlib/libjpeg en algunos formatos.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Capa de dependencias PRIMERO: cambia poco, y en el free tier de Render un rebuild
# completo por tocar una línea de código cuesta minutos de cold start.
COPY product/backend/requirements.txt /app/product/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/product/backend/requirements.txt

# Sólo lo que el servidor necesita. NADA de reports/, org/, qa/, .claude/, missions/ —
# la higiene del artefacto es regla del Step 5 (§3) y acá empieza: lo que no se copia
# no se puede filtrar.
COPY product/backend/app     /app/product/backend/app
COPY platform                /app/platform
COPY catalog                 /app/catalog
COPY product/belts           /app/product/belts

# `platform` no es un paquete instalado: el backend lo carga por ruta (mismo patrón que
# en dev). Sin esto, `from gates import tier_gate` y `from payments.base import ...`
# fallan — y los gates fallan CERRADO, así que el síntoma sería "todo es free".
ENV PYTHONPATH=/app/platform:/app/product/backend \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Los muros vienen ACTIVOS por default desde P7: no hace falta setear
# PUPPET_ENFORCE_* acá. Si alguien las pone en 0 en el panel de Render, apaga el moat —
# por eso NO se declaran en la imagen, para que aparecer en el panel sea una decisión.

EXPOSE 8000
# Render inyecta $PORT y exige bind a 0.0.0.0. Un bind a 127.0.0.1 pasa el build y
# falla el health check sin decir por qué.
CMD ["sh", "-c", "exec uvicorn app.main:app --app-dir /app/product/backend --host 0.0.0.0 --port ${PORT:-8000}"]
