/**
 * cuarto.scene.schema.ts — THE CONTRACT (Phase 0)
 * ================================================
 *
 * One artifact crosses the Godot → app boundary: `cuarto.scene.json` + `atlas.png`.
 * This file is the TypeScript type of that JSON. BOTH sides MUST conform to it:
 *
 *   - the Godot exporter  (Phase 2)  EMITS  a value of type `CuartoScene`
 *   - the Pixi importer   (Phase 3)  LOADS  a value of type `CuartoScene`
 *
 * ARCHITECTURE RULE (non-negotiable): Godot is a DESIGN + VALIDATION tool only.
 * Nothing Godot-specific (node paths, GDScript, .tscn internals, WASM) may leak
 * into this type. This descriptor captures *everything the Pixi runtime needs and
 * nothing else*. The shipped bundle is pure TypeScript + PixiJS.
 *
 * WHAT THIS DESCRIBES — the STAGE, not the ACTORS.
 * `cuarto.scene.json` is the static isometric room: floor, walls, fixed props, the
 * núcleo pedestal, and the interaction *zones* where capability tiles get slotted.
 * The user-placed tool blocks at runtime are dynamic and live in React state /
 * the recipe `config.canvas` (see ../projection.js) — they are NOT baked here.
 * Scene = the room; recipe canvas = what the user arranges inside it.
 *
 * ISO PROJECTION — the canonical formula (the bug always hides here).
 * Grid coordinates are integers; screen coordinates are px. Both sides use this:
 *
 *     screenX = (gridX - gridY) * (tileWidth  / 2) + origin.x
 *     screenY = (gridX + gridY) * (tileHeight / 2) + origin.y
 *
 * Depth (y-sort) for correct iso layering:  depth = (gridX + gridY) + z
 * Use `isoToScreen` / `isoDepth` below as the single source of truth so the Godot
 * render and the Pixi render agree pixel-for-pixel (Phase 4 parity check).
 */

export const CUARTO_SCENE_SCHEMA_VERSION = "1.0.0" as const;

// ───────────────────────────────────────────────────────────────────────────
// Atlas — one PNG, frame rects in px.
// ───────────────────────────────────────────────────────────────────────────

/** A frame name is a key into the atlas (e.g. "floor_a", "wall_n", "core_pedestal"). */
export type FrameName = string;

/** A sub-rectangle of the atlas PNG, in pixels (top-left origin). */
export interface AtlasFrame {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface CuartoAtlas {
  /** Path to the single PNG, relative to `cuarto.scene.json` (e.g. "atlas.png"). */
  image: string;
  /** Every sprite referenced by tiles/props MUST exist here. */
  frames: Record<FrameName, AtlasFrame>;
}

// ───────────────────────────────────────────────────────────────────────────
// Grid — iso tile size.
// ───────────────────────────────────────────────────────────────────────────

export interface CuartoGrid {
  /** Number of cells along the X axis. */
  cols: number;
  /** Number of cells along the Y axis. */
  rows: number;
  /** Full diamond width of one iso tile, in px. */
  tileWidth: number;
  /** Full diamond height of one iso tile, in px (typically tileWidth / 2). */
  tileHeight: number;
}

// ───────────────────────────────────────────────────────────────────────────
// Tiles — the floor and walls of the room (static, non-interactive).
// ───────────────────────────────────────────────────────────────────────────

export interface CuartoTile {
  gridX: number;
  gridY: number;
  /** Frame name in `atlas.frames`. */
  sprite: FrameName;
  /**
   * Optional depth BIAS added on top of the computed iso depth (gridX + gridY).
   * Use for stacked layers at the same cell (e.g. a wall above its floor tile).
   * Default 0. This is how Godot's y-sort is reproduced deterministically.
   */
  z?: number;
}

// ───────────────────────────────────────────────────────────────────────────
// Zones — interaction regions. The runtime fires a React callback on click.
// ───────────────────────────────────────────────────────────────────────────

/**
 * Roles map to the real Cuarto domain (see AUDIT-CUARTO.md / PLAN-CUARTO.md):
 *   - the 3 work zones: fuentes (read) · mesa (process) · entrega (write/send)
 *   - "nucleo"    → the agent core pedestal
 *   - "mcp-door"  → a Conexión: opening it drops that app's tools onto the floor
 *   - "tool-slot" → a single placeable slot for one tool tile
 *   - "contexto"  → context/memory drop area
 * The `(string & {})` keeps autocomplete for the known roles while still allowing
 * a studio author to introduce a new role without editing this file.
 */
export type ZoneRole =
  | "fuentes"
  | "mesa"
  | "entrega"
  | "nucleo"
  | "mcp-door"
  | "tool-slot"
  | "contexto"
  | (string & {});

export interface CuartoZone {
  /** Stable id passed to `onZoneClick(id)`. Unique within the scene. */
  id: string;
  /** Top-left cell of the zone rectangle. */
  gridX: number;
  gridY: number;
  /** Zone size in grid cells. */
  w: number;
  h: number;
  role: ZoneRole;
}

// ───────────────────────────────────────────────────────────────────────────
// Props — sprites placed in the room (decor + interactive fixtures).
// ───────────────────────────────────────────────────────────────────────────

export interface CuartoProp {
  /** Stable id passed to `onPropClick(id)` when `interactive`. Unique in scene. */
  id: string;
  sprite: FrameName;
  gridX: number;
  gridY: number;
  /**
   * Normalized anchor within the sprite (0..1). Where the sprite "sits" on its
   * cell. Typically anchorX = 0.5 (horizontal center) and anchorY ≈ 1.0 so the
   * base of a tall prop rests on the tile rather than floating.
   */
  anchorX: number;
  anchorY: number;
  /** Optional depth bias (see CuartoTile.z). Default 0. */
  z?: number;
  /** If true, clicking this prop fires `onPropClick(id)`. Default false. */
  interactive?: boolean;
}

// ───────────────────────────────────────────────────────────────────────────
// Scene — the top-level descriptor (= shape of cuarto.scene.json).
// ───────────────────────────────────────────────────────────────────────────

export interface CuartoSceneMeta {
  /** Human label for the room (debug/parity only). */
  name?: string;
  /**
   * Optional explicit stage size + iso origin so the Pixi render lines up
   * pixel-for-pixel with the Godot reference (Phase 4). If omitted, the runtime
   * computes a bounding box from the tiles and centers the room itself.
   */
  canvasWidth?: number;
  canvasHeight?: number;
  /** Screen px where grid cell (0,0) is drawn. Defaults to runtime-computed. */
  origin?: { x: number; y: number };
  /** Optional background fill, e.g. "#10131a". */
  background?: string;
}

export interface CuartoScene {
  /** Equals CUARTO_SCENE_SCHEMA_VERSION at export time. */
  schemaVersion: string;
  meta: CuartoSceneMeta;
  grid: CuartoGrid;
  /** Floor + walls, painted back-to-front by iso depth. */
  tiles: CuartoTile[];
  /** Decor + interactive fixtures (núcleo pedestal, doors, slots…). */
  props: CuartoProp[];
  /** Interaction regions. */
  zones: CuartoZone[];
  atlas: CuartoAtlas;
}

// ───────────────────────────────────────────────────────────────────────────
// Runtime interaction contract (Phase 3) — kept here so the whole boundary is
// described in one place. The Pixi runtime mounts into the existing vanilla
// frontend (cuarto.html) and exposes these callbacks; the host (cuarto.html /
// projection.js) owns state. No globals, no localStorage — interaction flows
// out through these handlers, in through a re-mount with new data.
// ───────────────────────────────────────────────────────────────────────────

export interface CuartoInteractionHandlers {
  /** Fired when an interaction zone is clicked. */
  onZoneClick?: (zoneId: string, zone: CuartoZone) => void;
  /** Fired when an interactive prop is clicked. */
  onPropClick?: (propId: string, prop: CuartoProp) => void;
}

// ───────────────────────────────────────────────────────────────────────────
// Canonical iso math — the SINGLE implementation both sides import.
// Exporter (Phase 2) uses these to sanity-check Godot positions; importer
// (Phase 3) uses them to render. One implementation ⇒ no iso drift.
// ───────────────────────────────────────────────────────────────────────────

export interface ScreenPoint {
  x: number;
  y: number;
}

/** grid (gridX, gridY) → screen px, including optional origin offset. */
export function isoToScreen(
  gridX: number,
  gridY: number,
  grid: Pick<CuartoGrid, "tileWidth" | "tileHeight">,
  origin: ScreenPoint = { x: 0, y: 0 },
): ScreenPoint {
  return {
    x: (gridX - gridY) * (grid.tileWidth / 2) + origin.x,
    y: (gridX + gridY) * (grid.tileHeight / 2) + origin.y,
  };
}

/** Depth key for back-to-front (y-sort) painting. Higher = nearer the camera. */
export function isoDepth(gridX: number, gridY: number, z: number = 0): number {
  return gridX + gridY + z;
}

/**
 * Inverse of `isoToScreen`: screen px → fractional grid coords. The exact inverse
 * (same origin/tile size) so a drag-drop snaps to the cell the cursor is over.
 * Round the result to land on a cell. Drag/place (Phase: tool tiles) lives or
 * dies on this being the true inverse — keep them as a pair.
 */
export function screenToIso(
  screenX: number,
  screenY: number,
  grid: Pick<CuartoGrid, "tileWidth" | "tileHeight">,
  origin: ScreenPoint = { x: 0, y: 0 },
): { gridX: number; gridY: number } {
  const x = screenX - origin.x;
  const y = screenY - origin.y;
  return {
    gridX: x / grid.tileWidth + y / grid.tileHeight,
    gridY: y / grid.tileHeight - x / grid.tileWidth,
  };
}

// ───────────────────────────────────────────────────────────────────────────
// Lightweight validator — verify-before-trust. The importer should run this on
// load and fail LOUD rather than render a silently-broken room. Pure, no deps.
// ───────────────────────────────────────────────────────────────────────────

export interface SceneValidationResult {
  ok: boolean;
  errors: string[];
}

export function validateCuartoScene(scene: unknown): SceneValidationResult {
  const errors: string[] = [];
  const s = scene as Partial<CuartoScene> | null | undefined;

  if (!s || typeof s !== "object") {
    return { ok: false, errors: ["scene is not an object"] };
  }
  if (typeof s.schemaVersion !== "string") errors.push("missing schemaVersion");
  if (!s.grid || typeof s.grid !== "object") errors.push("missing grid");
  if (!s.atlas || typeof s.atlas !== "object" || !s.atlas.frames) {
    errors.push("missing atlas.frames");
  }
  for (const f of ["tiles", "props", "zones"] as const) {
    if (!Array.isArray(s[f])) errors.push(`${f} must be an array`);
  }

  // Every referenced sprite must exist in the atlas — the #1 silent break.
  const frames = (s.atlas && s.atlas.frames) || {};
  const known = new Set(Object.keys(frames));
  (s.tiles || []).forEach((t, i) => {
    if (!known.has(t.sprite)) errors.push(`tiles[${i}] sprite "${t.sprite}" not in atlas`);
  });
  (s.props || []).forEach((p, i) => {
    if (!known.has(p.sprite)) errors.push(`props[${i}] sprite "${p.sprite}" not in atlas`);
  });

  // Ids unique within their collection.
  const dup = (xs: Array<{ id: string }>, label: string) => {
    const seen = new Set<string>();
    xs.forEach((x) => {
      if (seen.has(x.id)) errors.push(`duplicate ${label} id "${x.id}"`);
      seen.add(x.id);
    });
  };
  dup((s.props || []) as Array<{ id: string }>, "prop");
  dup((s.zones || []) as Array<{ id: string }>, "zone");

  return { ok: errors.length === 0, errors };
}
