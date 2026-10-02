import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

declare global {
  namespace NodeJS {
    interface Process {
      resourcesPath?: string;
    }
  }
}

function resourcesPathFromAppAsarPath(path: string): string | null {
  const match = /[\\/]app\.asar(?:[\\/]|$)/.exec(path);
  return match ? path.slice(0, match.index) : null;
}

export function openworkPluginPath(name: string, here?: string): string {
  const pluginDir = process.env.OPENWORK_EXTENSIONS_PLUGIN_DIR;
  if (pluginDir) {
    return join(pluginDir, `${name}.js`);
  }

  here = here ?? dirname(fileURLToPath(import.meta.url));
  const resourcesPath = resourcesPathFromAppAsarPath(here);
  if (resourcesPath) {
    const electronResourcesPath = process.resourcesPath?.includes("app.asar") ? resourcesPath : process.resourcesPath?.trim();
    return join(electronResourcesPath || resourcesPath, "opencode-plugins", `${name}.js`);
  }

  const extension = basename(here) === "dist" ? "js" : "ts";
  return join(here, "opencode-plugins", `${name}.${extension}`);
}

export const openworkAnthropicAdaptiveThinkingPluginPath = () => openworkPluginPath("openwork-anthropic-adaptive-thinking");
export const openworkAnthropicToolSchemaPluginPath = () => openworkPluginPath("openwork-anthropic-tool-schema");
export const openworkOfficeAttachmentsPluginPath = () => openworkPluginPath("openwork-office-attachments");

/** [Aleph] Atajo con nombre para el plugin de vista previa de extensiones.
 *
 * `workspace-init.test.ts` lo importa desde siempre y este módulo no lo exportaba —quedó
 * suelto cuando la amputación reordenó este archivo—, así que el typecheck no pasaba:
 * «has no exported member 'openworkExtensionsPreviewPluginPath'».
 *
 * No es lógica nueva: delega en `openworkPluginPath()` con el nombre que el propio test
 * afirma (`opencode-plugins/openwork-extensions-preview.ts`), así que sigue respetando
 * `OPENWORK_EXTENSIONS_PLUGIN_DIR` y la resolución de recursos de Electron empaquetado. */
export function openworkExtensionsPreviewPluginPath(here?: string): string {
  return openworkPluginPath("openwork-extensions-preview", here);
}
