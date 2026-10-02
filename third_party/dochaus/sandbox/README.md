# Fresh-clone sandbox

Verifies that someone who `git clone`s doc.haus and runs `./start.sh` gets a
working first run — with no leftover working-tree state masking missing files.

```sh
./sandbox/run.sh              # full: install + boot smoke at HEAD
REF=<commit> ./sandbox/run.sh # test any ref
SKIP_BOOT=1 ./sandbox/run.sh  # install proof only
```

`run.sh` feeds `git archive <ref>` (tracked files only — a faithful fresh
clone) into a clean `oven/bun` container and runs two stages:

1. **Install** (in the image build): the exact `start.sh` loop —
   `bun install --frozen-lockfile` in `.`, `dochaus`, `services/ingest`,
   `apps/web` — then asserts the dochaus config-layer deps
   (`@xenova/transformers`, `docxodus` + its patch, `mammoth`, `unpdf`)
   resolve. A missing/untracked manifest fails the frozen install here.
2. **Boot smoke**: launches the real `start.sh` (`SKIP_INSTALL=1 NO_OPEN=1`,
   no provider creds) and asserts engine (4096), ingest (4500) and web (5173)
   all bind, then tears the stack down.

No provider credential is set on purpose: a first-time user has none and picks
a provider in the UI, so boot must not require one. The boot smoke confirms the
processes start and listen; it does not exercise a model call (that needs
Google Vertex ADC). Doubles as the fresh-clone base for the Docker image (#23).
