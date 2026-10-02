# Fresh-clone sandbox for doc.haus — full ./start.sh first-run simulation.
#
# Reproduces what a brand-new user gets: only the files git actually tracks,
# nothing from the working tree. run.sh feeds `git archive HEAD` (tracked
# files, no node_modules, no untracked manifests) in as fresh.tar, so this
# image starts from exactly what `git clone` would hand a stranger.
#
# Build runs stage 1 (install): the real start.sh install loop across all four
# workspaces. The image is then a fully-installed fresh clone; run.sh runs
# stage 2 (boot smoke) against it. If any manifest is untracked (issue #42),
# the matching --frozen-lockfile install fails and the build stops here.
FROM oven/bun:1.3.14

# Baseline a real dev machine already has, that the bare bun image lacks:
#   - python3 + build-essential: the opencode monorepo's root install compiles
#     native node-gyp modules (e.g. tree-sitter-*); macOS CLT / Linux
#     build-essential provide these, so requiring them matches a real user.
#   - lsof + procps: start.sh reaps stale port holders (lsof) and tears the
#     process tree down (pgrep/pkill) — install so the boot smoke exercises the
#     real teardown path, not a degraded one.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 build-essential lsof procps \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Tracked-files-only tarball produced by run.sh — a faithful fresh clone.
COPY fresh.tar /tmp/fresh.tar
RUN tar -xf /tmp/fresh.tar -C /app && rm /tmp/fresh.tar

COPY verify-install.sh verify-boot.sh /usr/local/bin/
RUN bash /usr/local/bin/verify-install.sh
