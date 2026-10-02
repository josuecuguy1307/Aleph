const CUARTO_SCENE_SCHEMA_VERSION = "1.0.0";
function isoToScreen(gridX, gridY, grid, origin = { x: 0, y: 0 }) {
  return {
    x: (gridX - gridY) * (grid.tileWidth / 2) + origin.x,
    y: (gridX + gridY) * (grid.tileHeight / 2) + origin.y
  };
}
function isoDepth(gridX, gridY, z = 0) {
  return gridX + gridY + z;
}
function screenToIso(screenX, screenY, grid, origin = { x: 0, y: 0 }) {
  const x = screenX - origin.x;
  const y = screenY - origin.y;
  return {
    gridX: x / grid.tileWidth + y / grid.tileHeight,
    gridY: y / grid.tileHeight - x / grid.tileWidth
  };
}
function validateCuartoScene(scene) {
  const errors = [];
  const s = scene;
  if (!s || typeof s !== "object") {
    return { ok: false, errors: ["scene is not an object"] };
  }
  if (typeof s.schemaVersion !== "string") errors.push("missing schemaVersion");
  if (!s.grid || typeof s.grid !== "object") errors.push("missing grid");
  if (!s.atlas || typeof s.atlas !== "object" || !s.atlas.frames) {
    errors.push("missing atlas.frames");
  }
  for (const f of ["tiles", "props", "zones"]) {
    if (!Array.isArray(s[f])) errors.push(`${f} must be an array`);
  }
  const frames = s.atlas && s.atlas.frames || {};
  const known = new Set(Object.keys(frames));
  (s.tiles || []).forEach((t, i) => {
    if (!known.has(t.sprite)) errors.push(`tiles[${i}] sprite "${t.sprite}" not in atlas`);
  });
  (s.props || []).forEach((p, i) => {
    if (!known.has(p.sprite)) errors.push(`props[${i}] sprite "${p.sprite}" not in atlas`);
  });
  const dup = (xs, label) => {
    const seen = /* @__PURE__ */ new Set();
    xs.forEach((x) => {
      if (seen.has(x.id)) errors.push(`duplicate ${label} id "${x.id}"`);
      seen.add(x.id);
    });
  };
  dup(s.props || [], "prop");
  dup(s.zones || [], "zone");
  return { ok: errors.length === 0, errors };
}
export {
  CUARTO_SCENE_SCHEMA_VERSION,
  isoDepth,
  isoToScreen,
  screenToIso,
  validateCuartoScene
};
