/* servidor_cuarto.mjs — EL PISO MÍNIMO PARA MEDIR EL CUARTO SIN BACKEND.
 * [Gate 4 · Fase 4 · obra O4]
 *
 * POR QUÉ EXISTE
 * --------------
 * Las cuatro varas del morph (`verify_fractal_{zoom,panel,colocar,frontera}.mjs`) servían
 * `product/app/design` con `python3 -m http.server` y manejaban el Cuarto por
 * `window.__cuarto`. Eso alcanzaba cuando la receta se compilaba sola. **Hoy ya no**, y las
 * cuatro estaban ROJAS —medido también contra `main @ 8bc42e43`, así que no es de esta
 * fase—: colocar una pieza dispara `syncRecipe → tilesToRecipe → compileModel`, y
 * `compileModel` tira `No hay un modelo conectado para compilar` cuando el selector del
 * sidecar no contestó (`cuarto.models.js:354`; sin `data.modelos`, `_mergeSelector` devuelve
 * `[]`, así que `byId` queda vacío). Dos de las cuatro varas ya lo reportaban como
 * `HARNESS ERROR`: el arnés reconocía que el hueco era suyo.
 *
 * Esto es ese hueco, tapado en UN lugar: estáticos + el endpoint del selector con UN modelo
 * conectado. No es un mock del producto —el Cuarto sigue corriendo entero, con su motor y
 * su receta de verdad—: es el piso que un navegador sin backend no tiene.
 *
 * QUÉ NO HACE: inventar comportamiento. Sirve la lista mínima que el selector define en su
 * contrato (`_mergeSelector`) y nada más; quien necesite otra cosa la declara.
 *
 *     import { servirCuarto } from "../../qa/lib/servidor_cuarto.mjs"
 *     const srv = await servirCuarto({ puerto: 8103 })
 *     …
 *     await srv.cerrar()
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const DESIGN = path.resolve(AQUI, "../../product/app/design");

const TIPOS = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".woff2": "font/woff2",
  ".ico": "image/x-icon",
};

/** El modelo que el Cuarto necesita tener «conectado» para poder compilar una receta. */
export const MODELO_DE_VARA = {
  picker_id: "vara/cerebro",
  slug: "vara-cerebro",
  label: "Cerebro de la vara",
  model: "vara/cerebro",
  base_url: "http://127.0.0.1:1/v1",
  conectado: true,
  default: true,
  tier: "vara",
};

/**
 * Sirve `product/app/design` y el mínimo de `/v1` que el Cuarto necesita.
 *
 * @param {{puerto:number, rutas?:Record<string,(req)=>any>}} opts
 *   `rutas` agrega o PISA endpoints `/v1/...` para una vara concreta (por ejemplo el grafo
 *   de agentes que necesita la guardia de ciclos). El valor devuelto se serializa a JSON.
 */
export async function servirCuarto({ puerto, rutas = {}, sustituir = {} } = {}) {
  const base = {
    "/v1/modelos/selector": () => ({ modelos: [MODELO_DE_VARA], default: MODELO_DE_VARA.slug }),
    "/v1/brains/status": () => ({ providers: [] }),
    ...rutas,
  };

  const srv = http.createServer((req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    const manejador = base[url.pathname];
    if (manejador) {
      const cuerpo = JSON.stringify(manejador(req) ?? null);
      res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
      return res.end(cuerpo);
    }
    if (url.pathname.startsWith("/v1/")) {
      // Un `/v1` no declarado contesta vacío en vez de 404: el 404 ensucia la consola y la
      // vara que mide «cero errores» empieza a medir el arnés en vez del producto.
      res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
      return res.end("{}");
    }
    // SUSTITUCIÓN — sirve OTRO contenido para una ruta. Existe para una sola cosa y vale la
    // pena decirla: probar una vara CAYENDO contra el archivo que de verdad tenía el defecto
    // (`git show HEAD:…`), en vez de contra una perilla de sabotaje metida en producción. Una
    // perilla así vive para siempre en el código del usuario; esto vive sólo en la corrida.
    if (Object.prototype.hasOwnProperty.call(sustituir, url.pathname)) {
      const cuerpo = sustituir[url.pathname];
      res.writeHead(200, { "Content-Type": TIPOS[path.extname(url.pathname)] || "text/html; charset=utf-8" });
      return res.end(cuerpo);
    }
    // ESTÁTICOS. La ruta se resuelve y se COMPRUEBA que caiga adentro del árbol servido:
    // un `..%2f` en la URL de una vara no puede leer el disco de la máquina.
    const rel = decodeURIComponent(url.pathname).replace(/^\/+/, "");
    const destino = path.resolve(DESIGN, rel);
    if (!destino.startsWith(DESIGN)) {
      res.writeHead(403);
      return res.end("fuera del árbol servido");
    }
    fs.readFile(destino, (err, datos) => {
      if (err) {
        res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
        return res.end("no está: " + rel);
      }
      res.writeHead(200, { "Content-Type": TIPOS[path.extname(destino)] || "application/octet-stream" });
      res.end(datos);
    });
  });

  await new Promise((r) => srv.listen(puerto, "127.0.0.1", r));
  return {
    puerto,
    base: `http://127.0.0.1:${puerto}`,
    cerrar: () => new Promise((r) => srv.close(r)),
  };
}

/**
 * Espera a que el Cuarto esté REALMENTE listo para que le toquen las piezas.
 *
 * No alcanza con `window.__cuarto`: el catálogo de modelos se pide por HTTP y, hasta que
 * contesta, `compileModel` no tiene de dónde sacar el modelo y `syncRecipe` —que corre en
 * CADA colocación— tira. Medido: con el piso puesto pero sin esta espera, la vara sigue
 * muriendo; con la espera, `placeTile` devuelve limpio.
 *
 * Degrada a propósito: si el catálogo nunca contesta se sigue igual, porque hay varas que
 * no tocan piezas y no tienen por qué esperar 15 s por nada.
 */
export async function cuartoListo(page, { timeout = 15000 } = {}) {
  await page.waitForFunction(() => window.__cuarto && window.Projection, null, { timeout: 30000 });
  try {
    await page.waitForResponse((r) => r.url().includes("/v1/modelos/selector"), { timeout });
  } catch {
    /* sin catálogo la vara sigue: sólo caerán las que de verdad lo necesitaban */
  }
  await page.waitForTimeout(600);
}
