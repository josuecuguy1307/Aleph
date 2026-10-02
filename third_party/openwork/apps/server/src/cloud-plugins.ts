/** Aleph Office does not fetch or install remote plugin marketplaces. */
const disabled = () => new Error("Remote plugin marketplaces are disabled in Aleph Office");

/** [Aleph] La FORMA de un plugin ya resuelto. `claude-plugin-bundle.ts` la importa para
 *  traducir un bundle de Claude a «la forma CloudPluginResolved existente» y reusar el
 *  camino de instalación. El catálogo de la nube no está, pero el tipo sí tiene que existir:
 *  es el contrato entre el traductor y el instalador, y sin él ese archivo no compila. */
export type CloudPluginMembership = {
  configObjectId: string;
  configObject: {
    id: string;
    objectType: string;
    title: string;
    description: string | null;
    currentRelativePath: string | null;
    status: string;
    updatedAt: string | null;
    latestVersion: {
      id: string;
      rawSourceText: string | null;
      normalizedPayloadJson: Record<string, unknown> | null;
    };
  };
};

export type CloudPluginResolved = {
  plugin: {
    id: string;
    name: string;
    description: string | null;
    updatedAt: string | null;
  };
  memberships: CloudPluginMembership[];
};

/** [Aleph] La forma la fijan sus dos consumidores, y no era la que el stub devolvía:
 *  `workspace-kv-store.test.ts:130` afirma `{ skills, providers, marketplaces, plugins }`
 *  —cuatro claves, todas OBJETOS— y `runtime-db.test.ts:142` indexa
 *  `.plugins.plugin_runtime?.name`, o sea un mapa por id, no un arreglo. El stub devolvía
 *  dos arreglos vacíos, y por eso esos dos tests no compilaban. Sigue estando vacío —no hay
 *  catálogo de nube que leer— pero con la forma correcta. */
export type InstalledCloudPlugins = {
  skills: Record<string, unknown>;
  providers: Record<string, unknown>;
  marketplaces: Record<string, unknown>;
  plugins: Record<string, { name?: string } & Record<string, unknown>>;
};

export async function readInstalledCloudPlugins(
  _config: unknown,
  _workspaceId: string,
): Promise<InstalledCloudPlugins> {
  return { skills: {}, providers: {}, marketplaces: {}, plugins: {} };
}

/* [Aleph] LOS TRES DEVUELVEN SU TIPO, aunque en runtime tiren.
 *
 * Estaban declarados `: never` porque lanzan siempre. Es cierto en runtime, pero le dice a
 * TypeScript que después de llamarlos no hay valor: por eso `server.ts` no podía leer
 * `resolved.plugin.name` ni `result.warnings` —«Property 'plugin' does not exist on type
 * never»— y salían 8 errores de golpe.
 *
 * El contrato de tipos tiene que seguir siendo el del catálogo aunque el catálogo no esté:
 * quien llama sigue escribiendo el mismo código, y lo que cambia es que en tiempo de
 * ejecución recibe una excepción con causa en vez de datos. Es la misma idea que en el
 * puente de Diseño: la forma se conserva, el transporte no. */
export function readCloudPluginResolved(_input: unknown): CloudPluginResolved {
  throw disabled();
}

/** Un archivo tocado por una instalación: `server.ts` recorre `files` y decide por
 *  `objectType` qué evento de recarga emitir (mcp · skills · agents · commands · config). */
export type CloudPluginFile = {
  objectType: string;
  /** `server.ts` lo usa como nombre legible del archivo al emitir el evento de recarga. */
  title: string;
  path?: string;
};

export type CloudPluginInstalled = {
  name: string;
  files: CloudPluginFile[];
};

export type CloudPluginInstallResult = {
  item: CloudPluginInstalled;
  warnings: string[];
};

export async function installCloudPlugin(_input: unknown): Promise<CloudPluginInstallResult> {
  throw disabled();
}

export async function removeCloudPlugin(_input: unknown): Promise<CloudPluginInstalled> {
  throw disabled();
}
