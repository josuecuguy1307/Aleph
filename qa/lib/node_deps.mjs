/* node_deps.mjs — RESOLVER `playwright` DESDE CUALQUIER WORKTREE.
 *
 * `node_modules/` no está en git: vive sólo en el árbol principal, y `git worktree add` no
 * lo copia. Una vara `.mjs` corrida desde un worktree muere con ERR_MODULE_NOT_FOUND —un
 * stack trace de Node, que NO es un veredicto— antes de medir nada.
 *
 * Acá se busca en dos lugares, en orden: el árbol propio, y el principal que
 * `git rev-parse --git-common-dir` sabe ubicar desde cualquier worktree. Si no está en
 * ninguno, el error lo DICE en castellano con la orden que lo arregla, en vez de dejar
 * caer el stack de Node.
 *
 *     import { requerir } from "<...>/qa/lib/node_deps.mjs";
 *     const { webkit } = requerir("playwright");
 */
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const AQUI = dirname(fileURLToPath(import.meta.url));
const ARBOL = dirname(dirname(AQUI));           // qa/lib → qa → raíz del worktree

function arbolPrincipal() {
  try {
    const común = execFileSync(
      "git", ["rev-parse", "--path-format=absolute", "--git-common-dir"],
      { cwd: ARBOL, encoding: "utf-8" },
    ).trim();
    return común.endsWith("/.git") ? común.slice(0, -"/.git".length) : null;
  } catch {
    return null;
  }
}

export function raicesDeDeps() {
  const raíces = [ARBOL];
  const principal = arbolPrincipal();
  if (principal && principal !== ARBOL) raíces.push(principal);
  return raíces.filter((r) => existsSync(join(r, "node_modules")));
}

/** [H5b] El `python` del backend que SÍ existe: el del árbol propio, si no el del
 *  principal. `product/backend/.venv` es local y no viaja a un worktree — exactamente el
 *  mismo agujero que `node_modules`, y por eso vive en el mismo módulo. Espejo de
 *  `qa/lib/arbol.py:venv_python` para el lado de Node. */
export function pythonDelBackend(raizPropia = ARBOL) {
  const relativo = "product/backend/.venv/bin/python";
  const candidatos = [join(raizPropia, relativo)];
  const principal = arbolPrincipal();
  if (principal) candidatos.push(join(principal, relativo));
  return candidatos.find((p) => existsSync(p)) || candidatos[0];
}

export function requerir(paquete) {
  const raíces = raicesDeDeps();
  for (const raíz of raíces) {
    try {
      return createRequire(join(raíz, "node_modules", "/"))(paquete);
    } catch { /* probamos la siguiente */ }
  }
  throw new Error(
    `no se pudo resolver '${paquete}' desde ${ARBOL}.\n` +
    `  node_modules no está en git y este worktree no lo tiene.\n` +
    `  Arreglo:  product/backend/.venv/bin/python qa/lib/deps_node.py`,
  );
}
