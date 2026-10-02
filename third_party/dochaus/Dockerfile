# One-command self-host: builds a fully-installed image, then `./start.sh` runs
# the three processes (engine + ingest + web) exactly as a local run does. This
# is the same base the fresh-clone sandbox proves (sandbox/Dockerfile) — install
# at build, boot at run — so `docker compose up` is the dev path in a box.
FROM oven/bun:1.3.14

# Baseline a real dev machine already has, that the bare bun image lacks:
#   - python3 + build-essential: the opencode monorepo's root install compiles
#     native node-gyp modules (e.g. tree-sitter-*).
#   - lsof + procps: start.sh reaps stale port holders (lsof) and tears the
#     process tree down (pgrep) on exit.
#   - poppler-utils + tesseract-ocr + markitdown: PDF and scanned-document
#     ingestion. services/ingest shells out to markitdown (PDF -> Markdown) and
#     to pdftoppm + tesseract (OCR for flat scans) when they are on PATH, so the
#     self-host image bakes them in.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip build-essential lsof procps \
    poppler-utils tesseract-ocr \
  && rm -rf /var/lib/apt/lists/* \
  && pip3 install --no-cache-dir --break-system-packages "markitdown[pdf]"

WORKDIR /app
COPY . .

# Byte-for-byte the install loop start.sh runs on a fresh clone (start.sh:39-42):
# each workspace carries its own lockfile, so each needs its own frozen install.
RUN for dir in . dochaus services/ingest apps/web; do \
      echo "doc.haus: installing dependencies ($dir)" && \
      (cd "$dir" && bun install --frozen-lockfile); \
    done

# engine, ingest, web.
EXPOSE 4096 4500 5173

# Deps are baked in (SKIP_INSTALL); no browser to open inside the container
# (NO_OPEN). start.sh's loopback defaults are overridden to 0.0.0.0 by compose so
# the published ports are reachable from the host browser.
ENV SKIP_INSTALL=1 NO_OPEN=1
CMD ["./start.sh"]
