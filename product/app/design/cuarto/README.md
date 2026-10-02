# El Cuarto — isometric scene (Pixi-native)

El Cuarto is the **mapa vivo**: a deliberate isometric diorama (no generic decoration)
projected from the real `puppets.config` recipe. It is **inspección-as-core** — point at a
software, `POST /v1/inspect`, and the capability **is born** as a piece in its zone (gated if
it touches the outside, wired to the núcleo with its eco). It is also fully equippable
(**＋ Equipar** → drag any catalog atom), and pressing **▶ RUN** runs the agent for real
while the **eco** (the loop) animates back to the núcleo from live SSE events.

**Two ways to build (parity):** drag atoms from **＋ Equipar**, OR describe it and **✦ Armar**
(`POST /v1/forge` → places the proposed pieces). Both yield the same catalog atoms → same options.

**Key surfaces (usabilidad round):**
- **Equipar = closets**: the catalog is organised into collapsible armarios (Apps · Mundo ·
  Datos · Archivos · Saberes) with search-as-you-type + filters (zone / type / key-vs-free) and a
  group-by toggle. Searching auto-expands all closets.
- **Núcleo = el cerebro**: a **model picker** (real `models.py` aliases — Opus/brain, gpt-oss,
  llama, qwen, qwen-local, gemini — with honest availability: shim-dev / needs-key / local $0),
  plus identity (name/objetivo), memory (rag) and human instructions (framing). See `MODELS-CONTRACT.md`.
- **Piece = 4 depths**: **Chat** (decile qué cambiar) · **Opciones** (per-atom, from `requirements`) ·
  **Código** (live recipe slice + real handler) · **Salida** (what it produces). All compile to the
  **same** recipe.
- **Movable pieces** (drag a placed atom), **deliberate mesh** (＋ per zone on the floor — keeps each
  zone rectangular so iso rotation stays valid), **fit-all camera** (frames the 3 zones, no panning).
- **RUN** has its own task input (separate from inspect/forge), bounded to 45s with an **honest**
  status (surfaces the real backend error; the agent run is currently blocked on localhost by infra —
  no LLM key + belt MCP servers don't start — **not the Cuarto's lane**).

What's legible on the floor:
- **3 zonas** as bold iso diamonds — **Fuentes** (leer · verde) → **Mesa** (procesar · violeta)
  → **Entrega** (sacar · ámbar) — each self-labelled.
- **5 átomos** by SHAPE/colour (procedural, not sprites): **Núcleo** (cristal · the agent),
  **Tool** (chip), **Contexto/Memoria** (tambor), **Gate** (candado over a tool that touches
  the world), **Conexión** (puerta + llave). Plus dotted **cableado** + the **eco** return line.
- **Cámara movible**: pan (drag empty floor) · zoom (wheel / ＋－) · **rotar el plano** (iso
  4-way re-projection, pieces stay upright) · ⊙ recenter.
- **Mesh que CRECE (C5)**: una zona que se llena **se extiende** — auto-crece al soltar una
  pieza sin lugar, o manualmente con el ＋ de cada zona en la leyenda. La grilla crece
  **cuadrada** (preserva la rotación), las paredes se empujan hacia afuera y la cámara navega
  el cuarto más grande. **No** es infinito-plano: las 3 zonas se conservan y siguen legibles.
- **Click a piece → its 3 profundidades**: **Chat** (describí, el sistema escribe) →
  **Opciones** (perillas + switches: Autonomía→gate, Detalle→prompt, Pasos→loop) →
  **Código** (handler read-only, real `/v1/tools/{ref}/handler` or the synthesized one).

It is **alive by design** (idle motion, reactive hover/click, state-driven glow) and
**Pixi-native**: the shipped runtime is pure vanilla TypeScript/JS + PixiJS. There is **no
Godot, no WASM, no React, no bundler** — it mounts into the repo's existing vanilla frontend
(`product/app/design/*`) served by `product/app/serve.py` (`:8091`, which proxies `/v1` → `:8080`).

---

## The contract (start here)

Everything crosses one boundary: **`cuarto.scene.json`** (the room) conforming to the
TypeScript type in **`cuarto.scene.schema.ts`**. The scene describes the **stage** — floor,
walls, fixed props, the núcleo pedestal, and interaction **zones**. It does **not** contain
the user-placed tool tiles; those are dynamic runtime state (rendered on top, serialized to
the recipe — see *Recipe wiring* below).

The schema also owns the canonical iso math (the single source of truth for both placement
and snapping, so projection bugs can't drift):

```
screenX = (gridX - gridY) * (tileWidth  / 2) + origin.x      // isoToScreen
screenY = (gridX + gridY) * (tileHeight / 2) + origin.y
depth   = (gridX + gridY) + z                                 // isoDepth (y-sort)
screenToIso = exact inverse of isoToScreen                    // drag snap-to-grid
```

`validateCuartoScene(scene)` runs on load and **fails loud** (catches the #1 break: a sprite
name not present in the atlas).

---

## Files

| File | Role | Generated? |
|---|---|---|
| `cuarto.scene.schema.ts` | **the contract** — types + iso math + validator (source of truth) | source |
| `cuarto.scene.schema.js` | browser ESM the renderer imports | **generated** from `.ts` |
| `cuarto.scene.json` | the room shell (49 tiles, props, 4 zones, atlas frames) | **generated** |
| `atlas.png` | one PNG atlas (floor, wall, pedestal, orb, plant, door, slot, tile) | **generated** |
| `build_cuarto_assets.py` | the "studio": PIL draws the atlas + emits the scene | source |
| `cuarto.render.js` | the Pixi runtime: load+validate, render, alive, drag/place, eco | source |
| `cuarto.catalog.js` | **live** atom loader — `GET /v1/atoms/catalog` (real, multi-belt) | source |
| `cuarto.recipe.js` | bridge: placed tiles ⇄ `projection.js` ⇄ `puppets.config` | source |
| `cuarto.pixi.html` | the page: palette, live recipe panel, ▶ Correr | source |
| `projection.js` | canvas ⇄ recipe v1 (shared with the DOM `cuarto.html`) | source |
| `vendor/pixi.min.js` | PixiJS v8 global build (runtime dep) | downloaded |
| `screenshot_cuarto.mjs` | headless verification (Playwright) | dev-only |
| `screenshots/` | verification output | dev-only / regenerable |

> `cuarto.html` (no `.pixi`) is the **older DOM diorama** (Fase 1) — left untouched.

---

## View it

```bash
# the real path (serve.py running on :8091, backend on :8080):
open http://localhost:8091/cuarto/cuarto.pixi.html

# or standalone (no backend → recipe validation + ▶ Correr degrade gracefully):
cd product/app/design/cuarto && python3 -m http.server 8099
open http://localhost:8099/cuarto.pixi.html
```

Drag a chip into its zone → the tile snaps to the grid and lights its zone, and the
**Receta** panel serializes it live and validates against the backend. Press **▶ Correr**
to run the agent and watch the eco.

---

## Re-run the export (when the room or sprites change)

The atlas, anchors, and layout are authored **together** in one script so they can't drift:

```bash
cd product/app/design/cuarto
python3 build_cuarto_assets.py          # → atlas.png + cuarto.scene.json
```

Edit sprites in the `make_*()` factories or the room layout in `build_scene()`, then re-run.

When you change the **contract** (`cuarto.scene.schema.ts`), regenerate the browser ESM:

```bash
npx -y esbuild@0.23.0 cuarto.scene.schema.ts --format=esm --outfile=cuarto.scene.schema.js
```

(`vendor/pixi.min.js` was fetched once from `https://pixijs.download/release/pixi.min.js`.)

---

## Mount the renderer

```js
import { mountCuarto } from "./cuarto.render.js";   // needs global PIXI (vendor/pixi.min.js)

const cuarto = await mountCuarto(canvasEl, {
  sceneUrl: "./cuarto.scene.json",
  onZoneClick(id, zone) { /* … */ },
  onPropClick(id, data) { /* … */ },
  onTilePlaced(id, gx, gy, role) { /* … */ },
});
```

Host-facing API (state lives in the host; nothing global, no localStorage):

- **drag/place** — `beginDrag(tool)` · `updateDrag(x,y)` · `endDrag()` · `placeTile(tool,gx,gy)` · `removeTile(id)` · `placedTiles()`
- **state juice** — `setWired(id,on)` · `setZoneActive(role,on)` · `pulse(id)`
- **eco** — `setRunning(b)` · `ecoFire(tileId)` · `ecoReturn(tileId)` · `ecoFinal()` · `playEco(order?)` (inferred fallback)

---

## Recipe wiring

`cuarto.recipe.js` maps placed tiles → the `ST` block shape `projection.js` expects, calls
`Projection.canvasToRecipe` → a v1 recipe, and back via `Projection.recipeToCanvas` to
rehydrate. The iso coords persist as `config.canvas.blocks[].gridX/gridY` (additive; the
engine ignores `canvas`).

**Multi-belt catalog (C1, Fase 1):** the palette is loaded **live** from `GET /v1/atoms/catalog`
(`cuarto.catalog.js::loadAtoms` — no demo, no hardcode). Each placed piece carries its own
`belt_ref`; `projection.js` unions them into `belt.belt_refs[]` and the backend validator
**accepts the multi-belt recipe** (verified green against `:8080`). The `server fantasma`
rule still holds per-belt; composition across belts is allowed.

## ▶ Correr (the eco, cabled to real events)

1. Serialize the recipe, generate a `space_id`, fire **`POST /v1/puppets/run`** (real run).
2. Open **`GET /v1/spaces/{space_id}/stream`** (SSE) and listen to the **named** events
   (`tool_call_started/finished`, `gate_waiting`, `final`).
3. Each real `tool_call` → `ecoFire(tile)` + `ecoReturn(tile)` (token rides the link back to
   the núcleo, which pulses). Mapped by server (e.g. `filesystem` → "Guardar archivo").
4. `final` → flourish. If the run used **no** tools, fall back to the inferred loop
   (read→process→deliver) so the button always shows the loop.

---

## Verify

```bash
cd product/app/design/cuarto
node screenshot_cuarto.mjs                 # idle, drag→place, live recipe+validate, ▶ run eco, rehydrate
CUARTO_PERSIST=1 node screenshot_cuarto.mjs # also POSTs a puppet to confirm config.canvas persists (creates a DB row)
```

Prints: backend validation badge, `belt_refs`/`tool_filters`, round-trip stability, live
`tool_call` count, and page errors. Screenshots land in `screenshots/`.

> The persistence check is **off by default** so the test leaves no DB rows. With keys absent,
> a research run typically calls 1 tool (`write_file`) — real agent behavior, faithfully shown.

---

## Known limits / next

- `started`/`finished` events are paired loosely (last-fired); fine for the visual.
- Multi-belt recipes validate green (C1); rehydration of two atoms that share one MCP server
  resolves by `server` (the distinct-server case round-trips exactly).
- Iso rotation assumes a **square** grid; the mesh (C5) grows the grid **square** (`N×N`) so
  rotation keeps working after a zone extends. Zones grow **downward** (more rows). The live
  recon card enters in screen space and travels to the cell via `api.viewPoint` (camera-aware),
  so pan/zoom mid-recon stay correct.
- The 3-depths **Chat** + the behaviour **switches** are wired to the scene (Autonomía=Siempre
  frena drops a real gate padlock) but don't yet persist back to the recipe — v1 read-only by
  default, as designed. Persisting the switch→recipe compile is the next step.
- Backlog: per-tile remove from the canvas, fractal drill-in (open piece = its own Cuarto),
  bring-your-own-MCP paste in **＋ Equipar**.
