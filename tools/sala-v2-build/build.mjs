// Build del bundle vendorizado de sala-v2.
//
// QUÉ HACE: toma el código de terceros que vive en `third_party/` (assistant-ui + AG-UI,
// importados enteros por paquete) y produce UN archivo servible por el sidecar:
//
//     product/app/design/sala-v2/vendor/assistant-ui.bundle.js   (+ su .sri)
//
// POR QUÉ EXISTE: Aleph no tiene bundler en runtime — el frontend es HTML plano + ESM
// nativo, y el sidecar sirve `product/app/design` como estáticos (main.py, _FrontendStatic).
// assistant-ui, en cambio, es TypeScript con JSX en un monorepo pnpm. El precedente del
// repo para esta clase de pieza ya existe y es exactamente éste: React, PixiJS, deep-chat,
// highlight, marked, purify, xlsx y three viven en `design/vendor/` como artefactos
// construidos afuera, servidos locales y verificados por integridad. Este script es lo que
// produce uno más, y lo hace DESDE LA FUENTE QUE VENDORIZAMOS, no desde npm: lo que se
// distribuye sale del código que está en `third_party/` y de ningún otro lado.
//
// QUÉ **NO** HACE: no toca ni una línea de código de Aleph. El código de sala-v2 es ESM
// plano escrito a mano (`h()` sobre React, igual que `support.js`), se sirve tal cual y no
// pasa por acá. Cambiar el comportamiento de la Sala nueva NO requiere correr este build.
// Sólo subir de versión a assistant-ui o a AG-UI lo requiere.
//
// CÓMO SE CORRE:
//     cd tools/sala-v2-build && npm install && npm run build
//
// React 19 va ADENTRO del bundle a propósito. `design/vendor/react.production.min.js` es
// 18.3.1 y assistant-ui usa `useEffectEvent`, que es API de React ≥19.2 — medido: 12
// errores de resolución al intentar bundlear contra el React vendorizado. Subir el React
// global tocaría las 9 pantallas que hoy corren sobre 18.3.1 vía `support.js`, y esta fase
// tiene prohibido moverlas. Como en Aleph cada pantalla es un DOCUMENTO APARTE (no hay
// router SPA — nav.js navega con location.href), los dos React jamás comparten realm:
// sala-v2 carga el suyo y nadie más lo ve.

import * as esbuild from "esbuild";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const HERE = path.dirname(new URL(import.meta.url).pathname);
const REPO = path.resolve(HERE, "..", "..");
const THIRD_PARTY = path.join(REPO, "third_party");
const OUT_DIR = path.join(REPO, "product/app/design/sala-v2/vendor");
const OUT_FILE = path.join(OUT_DIR, "assistant-ui.bundle.js");

// Las dos raíces de paquetes vendorizados. Cualquier import a un nombre de paquete que
// viva acá se resuelve contra su FUENTE, no contra node_modules.
const PACKAGE_ROOTS = [
  path.join(THIRD_PARTY, "assistant-ui/packages"),
  path.join(THIRD_PARTY, "ag-ui/sdks/typescript/packages"),
];

// ── mapa nombre-de-paquete → carpeta vendorizada ────────────────────────────────────────
const workspace = {};
for (const base of PACKAGE_ROOTS) {
  if (!fs.existsSync(base)) throw new Error(`falta la raíz vendorizada: ${base}`);
  for (const d of fs.readdirSync(base)) {
    const pj = path.join(base, d, "package.json");
    if (!fs.existsSync(pj)) continue;
    const pkg = JSON.parse(fs.readFileSync(pj, "utf8"));
    workspace[pkg.name] = { dir: path.join(base, d), pkg };
  }
}

const SOURCE_EXTS = [".ts", ".tsx", ".mts", ".js", ".jsx"];

// Los paquetes declaran sus entradas apuntando a `dist/` (el build que npm publica y que
// nosotros NO tenemos, porque vendorizamos fuente). Traducimos dist→src.
function resolveSource(dir, distRel) {
  const rel = distRel
    .replace(/^\.\//, "")
    .replace(/^dist\//, "")
    .replace(/\.(js|mjs|cjs)$/, "");
  const base = path.join(dir, "src", rel);
  for (const e of SOURCE_EXTS) if (fs.existsSync(base + e)) return base + e;
  for (const e of SOURCE_EXTS) {
    const idx = path.join(base, "index" + e);
    if (fs.existsSync(idx)) return idx;
  }
  return null;
}

// FALLO VISIBLE, JAMÁS MUDO: si un paquete vendorizado gana una dependencia interna nueva
// al subir de versión, o si un subpath deja de existir, el build PARA con el nombre exacto.
// Nunca cae en silencio a node_modules, porque eso distribuiría código que no vendorizamos.
const vendoredSourcePlugin = {
  name: "vendored-source",
  setup(build) {
    const names = Object.keys(workspace).sort((a, b) => b.length - a.length);
    build.onResolve({ filter: /.*/ }, (args) => {
      const hit = names.find((n) => args.path === n || args.path.startsWith(n + "/"));
      if (!hit) return null;
      const { dir, pkg } = workspace[hit];
      const sub = args.path === hit ? "." : "." + args.path.slice(hit.length);
      const exp = pkg.exports?.[sub];
      const dist = typeof exp === "string" ? exp : exp?.default || exp?.import;
      if (!dist) {
        return {
          errors: [
            {
              text: `"${hit}" no declara el subpath "${sub}" en sus exports. Lo pidió ${args.importer}.`,
            },
          ],
        };
      }
      const src = resolveSource(dir, dist);
      if (!src) {
        return {
          errors: [
            {
              text: `"${hit}${sub}" apunta a "${dist}" y no hay fuente para eso en ${dir}/src. Lo pidió ${args.importer}.`,
            },
          ],
        };
      }
      return { path: src };
    });
  },
};

fs.mkdirSync(OUT_DIR, { recursive: true });

const result = await esbuild.build({
  entryPoints: [path.join(HERE, "entry.ts")],
  bundle: true,
  format: "esm",
  platform: "browser",
  target: ["es2022"],
  jsx: "automatic",
  minify: true,
  sourcemap: false,
  metafile: true,
  outfile: OUT_FILE,
  plugins: [vendoredSourcePlugin],
  // node_modules vive acá, no junto a la fuente vendorizada: hay que decírselo a esbuild.
  nodePaths: [path.join(HERE, "node_modules")],
  define: { "process.env.NODE_ENV": '"production"' },
  banner: {
    js: `/* GENERADO por tools/sala-v2-build/build.mjs — NO EDITAR A MANO.
   Fuente: third_party/assistant-ui + third_party/ag-ui (ver sus IMPORT.md y ATTRIBUTIONS.md).
   Para regenerarlo: cd tools/sala-v2-build && npm install && npm run build */`,
  },
  logLevel: "info",
});

// ── GUARD: todo lo que entry.ts promete, el bundle lo tiene que entregar ─────────────────
// Medido el 2026-08-08: `entry.ts` re-exportaba `useThread`, que NO existe en
// `@assistant-ui/react`. esbuild NO falló —el paquete tiene `export * from "./context"` y a
// través de un star re-export no puede probar estáticamente que un nombre falta— así que el
// bundle salió verde y la pantalla reventó recién en el navegador con
// «Importing binding name 'useThread' is not found». Un build que miente es peor que un
// build que rompe: acá se comprueba contra el artefacto REAL, importándolo.
// Se lee el bloque `export { … }` del artefacto en vez de importarlo: el bundle es código
// de navegador (toca `document` al cargar) y ejecutarlo en Node probaría otra cosa.
{
  const salida = fs.readFileSync(OUT_FILE, "utf8");
  const bloques = [...salida.matchAll(/\bexport\s*\{([^}]*)\}\s*;/g)];
  const entregados = new Set(
    (bloques.at(-1)?.[1] || "")
      .split(",")
      .map((s) => s.trim().split(/\s+as\s+/).pop().trim())
      .filter(Boolean),
  );
  const prometidos = [
    ...fs.readFileSync(path.join(HERE, "entry.ts"), "utf8").matchAll(/^export\s*(?:const\s+(\w+)|\{([^}]*)\})/gms),
  ]
    .flatMap((m) => (m[1] ? [m[1]] : m[2].split(",")))
    .map((s) => s.trim().split(/\s+as\s+/).pop().trim())
    .filter((s) => s && !s.startsWith("type "));

  const faltan = prometidos.filter((n) => !entregados.has(n));
  if (faltan.length) {
    console.error(`\n  ✗ el bundle NO entrega lo que entry.ts promete: ${faltan.join(", ")}`);
    console.error(`    Los nombres reales están en third_party/*/packages/*/src/index.ts.`);
    process.exit(1);
  }
  console.log(`  guard: ${prometidos.length}/${prometidos.length} exports prometidos, entregados`);
}

// ── integridad: mismo trato que el React vendorizado (support.js:1445-1447) ──────────────
const bytes = fs.readFileSync(OUT_FILE);
const sri = "sha384-" + crypto.createHash("sha384").update(bytes).digest("base64");
fs.writeFileSync(path.join(OUT_DIR, "assistant-ui.bundle.js.sri"), sri + "\n");

// ── qué entró de node_modules, para que ATTRIBUTIONS no se escriba de memoria ────────────
// Las rutas del metafile son relativas al cwd; se absolutizan para poder compararlas
// contra las carpetas vendorizadas.
const inputsAbs = Object.keys(result.metafile.inputs).map((i) => path.resolve(process.cwd(), i));
const externals = new Set();
for (const inp of Object.keys(result.metafile.inputs)) {
  const m = inp.match(/node_modules\/((?:@[^/]+\/)?[^/]+)\//);
  if (m) externals.add(m[1]);
}
const manifest = {
  generado_por: "tools/sala-v2-build/build.mjs",
  bytes: bytes.length,
  sri,
  vendorizado: Object.fromEntries(
    Object.entries(workspace)
      .filter(([, v]) => inputsAbs.some((i) => i.startsWith(v.dir + path.sep)))
      .map(([k, v]) => [k, v.pkg.version]),
  ),
  npm_embebido: Object.fromEntries(
    [...externals].sort().map((n) => {
      const pj = path.join(HERE, "node_modules", n, "package.json");
      const p = JSON.parse(fs.readFileSync(pj, "utf8"));
      return [n, { version: p.version, license: p.license || "?" }];
    }),
  ),
};
fs.writeFileSync(
  path.join(OUT_DIR, "assistant-ui.bundle.manifest.json"),
  JSON.stringify(manifest, null, 2) + "\n",
);

console.log(`\n  ${path.relative(REPO, OUT_FILE)}  ${(bytes.length / 1024).toFixed(1)} KB`);
console.log(`  SRI: ${sri}`);
console.log(`  vendorizados: ${Object.keys(manifest.vendorizado).length}`);
console.log(`  npm embebidos: ${Object.keys(manifest.npm_embebido).length}`);
