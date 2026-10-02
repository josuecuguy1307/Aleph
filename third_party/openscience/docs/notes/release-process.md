# Release process

OpenScience ships as native binaries and an npm package
(`@synsci/openscience`). Releases are cut from `main` — never from a feature
branch.

## Cutting a release

1. Make sure `main` is green (the required checks are Typecheck, Test, and
   Build (web)).
2. Trigger the `publish` workflow with a bump level:

   ```bash
   gh workflow run publish.yml --ref main -f bump=patch   # or minor / major
   ```

   The next version is derived from the current npm `latest`, so there is no
   manual version editing in `package.json` and no risk of a tag collision.

3. The workflow then, in order: computes the version and opens a draft GitHub
   release → builds the platform binaries → publishes to npm (with provenance)
   and updates the Homebrew tap → records an npm deployment.

## Conventions

- The repo bundles features into **patch** bumps unless a change is breaking —
  a feature release does not automatically imply a minor bump here.
- `bump` accepts `patch`, `minor`, or `major`; a `version` input can override
  the computed value explicitly.
- The tag (`vX.Y.Z`) points at the exact tree that was published.

## Verifying a release

```bash
npm view @synsci/openscience version     # equals the new version once npm propagates
gh release view vX.Y.Z --json assets     # binaries + checksums.txt attached
```

See [verification.md](verification.md) for the local gates to run before you
push to `main`.

## Isolated npm test installs

Every npm test build must use separate binary, config, data, cache, and state
roots. Use the exact prerelease version being validated; do not rely on a
moving dist-tag after installation.

```bash
export OPENSCIENCE_TEST_ROOT="/tmp/openscience-npm-2.0.2-test.N"
mkdir -p "$OPENSCIENCE_TEST_ROOT/home"
: >"$OPENSCIENCE_TEST_ROOT/npmrc"

export HOME="$OPENSCIENCE_TEST_ROOT/home"
export OPENSCIENCE_TEST_HOME="$HOME"
export OPENSCIENCE_CONFIG_DIR="$OPENSCIENCE_TEST_ROOT/config"
export OPENSCIENCE_DATA_DIR="$OPENSCIENCE_TEST_ROOT/data"
export XDG_CONFIG_HOME="$OPENSCIENCE_TEST_ROOT/xdg-config"
export XDG_DATA_HOME="$OPENSCIENCE_TEST_ROOT/xdg-data"
export XDG_CACHE_HOME="$OPENSCIENCE_TEST_ROOT/cache"
export XDG_STATE_HOME="$OPENSCIENCE_TEST_ROOT/state"
export NPM_CONFIG_PREFIX="$OPENSCIENCE_TEST_ROOT/npm"
export NPM_CONFIG_CACHE="$OPENSCIENCE_TEST_ROOT/npm-cache"
export NPM_CONFIG_USERCONFIG="$OPENSCIENCE_TEST_ROOT/npmrc"

npm install -g @synsci/openscience@2.0.2-test.N synsci@2.0.2-test.N
export PATH="$OPENSCIENCE_TEST_ROOT/npm/bin:$PATH"

openscience --version
synsci --version
openscience doctor
```

`OPENSCIENCE_CONFIG_DIR` is the authoritative OpenScience config directory,
and `OPENSCIENCE_DATA_DIR` is the authoritative application data directory.
When the config override is set, OpenScience does not also discover
`~/.openscience` or the normal XDG config directory. Config discovery is
dependency-passive: it does not create a package manifest, lockfile,
`node_modules`, or run dependency installation. A plugin named explicitly by
trusted config may still be installed when that plugin is actually loaded.

Removing the npm prefix does not remove the config or data roots. Retain them
for upgrade/uninstall validation, or remove the whole test root only after the
test record no longer needs it.
