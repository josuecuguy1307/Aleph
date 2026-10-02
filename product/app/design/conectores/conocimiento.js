/* conocimiento.js — LA TABLA DE CONOCIMIENTO POR TIPO.
 *
 * Lo que el adaptador SABE sobre cada clase de pieza. No es un catálogo de conectores: es
 * un catálogo de **tipos**, y por eso escala. Una pieza nueva no agrega una fila acá — cae
 * en el tipo que le corresponde y hereda todo lo que ya se aprendió de ese tipo.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * POR QUÉ ESTE ARCHIVO EXISTE, Y POR QUÉ SEPARADO DE `widget.js`.
 *
 * `widget.js` DERIVA: mira las fuentes y arma el modelo. Este archivo JUZGA: sabe que un
 * `sin_tools` sobre un OAuth no es lo mismo que sobre un stdio, que un `timeout` sin
 * evidencia de muerte no es un rojo, que un server de descarga que publica tools todavía
 * no probó nada. Ese conocimiento se pagó con bugs reales y estaba disperso en la cabeza
 * de quien los vivió; acá queda escrito, con su fuente y su test.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * LA FORMA DE UNA REGLA, y por qué es esta.
 *
 *   { id, tipo, dice, porque, aplica(ctx), efecto(ctx) }
 *
 *   · `tipo`   — a qué clase de pieza le habla. `*` es transversal.
 *   · `dice`   — la regla en una línea, en castellano.
 *   · `porque` — el bug o la medición que la pidió. Sin esto una regla es una opinión.
 *   · `aplica` — PURA y sobre datos DECLARADOS. Jamás sobre el nombre de la pieza.
 *   · `efecto` — qué cambia: un paso, una contradicción, un ajuste del veredicto, una nota.
 *
 * `qa/verify_conocimiento_tipos.mjs` exige que **cada regla tenga su test** y que ninguna
 * mencione un conector por nombre. Una regla sin test es una creencia; una regla con el
 * nombre de una pieza adentro es el `if` por conector con otro disfraz.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * LO QUE ESTE ARCHIVO **NO** HACE, a propósito:
 *
 *   · NO clasifica causas en temporal/permanente. Eso ya lo hace `repair_clasificar.py`
 *     y llega en la fuente como `clasificacion`. Duplicar esa tabla en JS sería tener dos
 *     verdades sobre la misma causa, que es exactamente el bug que el adaptador vino a
 *     matar (belt vs ficha vs registro). Acá se escribe la CONSECUENCIA de ser temporal,
 *     no la decisión de que lo sea.
 *   · NO mapea provider→variable por proveedor. Los alias viven en
 *     `catalog/connectors/env-alias.json`, que es el catálogo, y llegan como dato.
 *     Lo único que se resuelve acá son los SUFIJOS, que son convención universal.
 */

/** Los tipos. Cerrado a propósito: agregar uno es una decisión de producto. Una pieza
 *  puede ser VARIOS a la vez —un OAuth que además exige instalar algo— y por eso
 *  `tiposDe` devuelve una lista y no un valor. */
export const T_OAUTH = "oauth";
export const T_LLAVE = "llave";
export const T_DESCARGA = "descarga";
export const T_HTTP = "http";
export const T_TRANSVERSAL = "*";

/** Los ROLES de una variable de credencial. Tres, y NO son intercambiables: es la
 *  distinción que la regla `oauth/roles-distintos` protege. */
export const ROL_ACCESO = "acceso";        // el bearer con el que se llama a la API
export const ROL_COMPANION = "companion";  // el sobre cifrado (refresh, expiración, scopes)
export const ROL_LLAVE = "llave";          // una API key de toda la vida

/** UN SERVER MCP SON DOS PROCESOS.
 *
 * ⚠️ POR QUÉ ES UNA CONSTANTE Y NO UN COMENTARIO. Un server stdio arranca el proceso que
 * habla el protocolo **y** el que ejecuta (el intérprete y su hijo, o el lanzador y el
 * paquete). Contar procesos y encontrar uno solo NO es evidencia de que no arrancó, y
 * encontrar dos no es evidencia de que haya dos servers. Cualquier superficie que muestre
 * un conteo de procesos lo divide por esto antes de mostrarlo, y **ninguna** lo usa como
 * señal de salud: para eso está `verify`, que pregunta por MCP y no por la tabla de
 * procesos del sistema operativo.
 */
export const PROCESOS_POR_SERVER = 2;

const _CRED = /(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|BEARER|APIKEY)/i;
const _NUESTRAS = /^(PUPPET_|ALEPH_)/;

/** UN INSTANTE, VENGA COMO VENGA. Devuelve segundos epoch, o `0` si no hay fecha.
 *
 * ⚠️ ESTO NO ES UNA COMODIDAD: ES UN BUG MEDIDO. El registro guarda sus `ts` en ISO
 * (`"2026-07-31T21:40:38"`) y el adaptador los leía con `Number(ts)`, que sobre un ISO da
 * `NaN` y colapsa a `0`. O sea: **`medicionRancia` respondía «sin medición previa» sobre
 * las 42 filas del registro real** y la ley que dice que una medición vieja no manda nunca
 * llegó a aplicarse a nadie. Pasaba desapercibido porque los tests usaban enteros.
 *
 * Se acepta lo que las fuentes emiten hoy —ISO del registro, epoch de los eventos— y se
 * normaliza en UN lugar. Una fecha que no se puede leer devuelve `0`, que significa «no
 * hay fecha»: es lo que la regla `veredicto-con-fecha` necesita para negarse a pintar rojo.
 */
export function instanteDe(valor) {
  if (valor == null || valor === "") return 0;
  if (typeof valor === "number") return Number.isFinite(valor) ? Math.floor(valor) : 0;
  const n = Number(valor);
  if (Number.isFinite(n) && String(valor).trim() !== "") return Math.floor(n);
  const t = Date.parse(String(valor));
  return Number.isFinite(t) ? Math.floor(t / 1000) : 0;
}

/** UNA RUTA A UNA CREDENCIAL NO ES UNA CREDENCIAL.
 *
 * ⚠️ MEDIDO EN EL CENSO. Un belt declaraba `*_OAUTH_PATH` y `*_CREDENTIALS_PATH` — dos
 * RUTAS a archivos— y el adaptador las tomó por llaves porque «OAUTH» y «CREDENTIAL» están
 * adentro del nombre. Resultado: una pieza sana marcada bloqueada porque «nadie sabe bajo
 * qué nombre buscar esas credenciales en el vault». No hay nada que buscar: es config.
 *
 * Es la misma familia que `FREECADCMD` (una ruta) y `CAD_TIMEOUT` (un número), que ya
 * habían obligado a decidir por NOMBRE en vez de por prosa. El sufijo dice el TIPO del
 * valor, y una ruta, un archivo, un directorio o una URL no se guardan en un llavero.
 */
const _RUTA = /_(PATH|FILE|DIR|DIRECTORY|FOLDER|URL|URI|ENDPOINT|BASE|HOME|CONFIG)$/i;

/** ¿Este nombre de variable nombra una credencial del usuario?
 *
 * Por NOMBRE, que es lo único afirmable sin mirar el valor — el mismo criterio que el
 * grabador usa para decidir qué redactar. `FREECADCMD` es una ruta y `CAD_TIMEOUT` un
 * número: tratarlas como llave mandaba a esas piezas a pedir una credencial que no existe.
 */
export function esVariableDeCredencial(nombre) {
  const n = String(nombre || "");
  return !_NUESTRAS.test(n) && _CRED.test(n) && !_RUTA.test(n);
}

/** UNA CREDENCIAL PUEDE LLEGAR COMO ARCHIVO, y eso sigue siendo un trámite.
 *
 * La contracara de `_RUTA`. Excluir los `*_CREDENTIALS_PATH` del llavero es correcto —no
 * hay valor que guardar— pero tratarlos como si la pieza no pidiera nada es el error
 * opuesto, y también se midió: una pieza cuya ficha declara OAuth y cuyo belt sólo declara
 * rutas quedaba marcada «la ficha declara un trámite que el belt no pide». El belt SÍ lo
 * pide: pide que el trámite deje un archivo donde él lo va a leer.
 *
 * Lo que cambia entre las dos formas es el TRANSPORTE de la credencial, no su existencia.
 */
export function rutasDeCredencial(servidorBelt) {
  const belt = servidorBelt || {};
  return Object.keys(belt.env || {})
    .filter((k) => !_NUESTRAS.test(k) && _CRED.test(k) && _RUTA.test(k));
}

/** LOS SUFIJOS SON CONVENCIÓN, NO CONECTORES. Es la mitad de la regla `llave/sufijos` que
 *  se puede afirmar sin catálogo: `ACME_API_KEY` → provider `acme`, `ACME_ACCESS_TOKEN` →
 *  provider `acme`, `ACME_OAUTH_META` → provider `acme__oauth`. La otra mitad —los alias
 *  que no siguen la convención— llega como DATO en `alias`, del catálogo. */
const _SUFIJOS = [
  { sufijo: "_OAUTH_META", rol: ROL_COMPANION, cola: "__oauth" },
  { sufijo: "_ACCESS_TOKEN", rol: ROL_ACCESO, cola: "" },
  { sufijo: "_API_KEY", rol: ROL_LLAVE, cola: "" },
];

/** Variable declarada → { provider, rol } · o `null` si no se puede afirmar.
 *
 * `null` es una respuesta legítima y es la honesta: una variable de credencial cuyo
 * provider no se puede resolver ni por alias ni por convención es un hueco DECLARADO, y
 * el adaptador lo nombra (`credencial_sin_provider`) en vez de adivinar uno. Adivinar
 * mandaría a buscar en el vault bajo un nombre inventado y devolvería «falta tu llave»
 * sobre una llave que sí está.
 */
export function providerDeVariable(variable, alias) {
  const v = String(variable || "").toUpperCase();
  const porAlias = alias && (alias[v] || alias[variable]);
  if (porAlias) {
    return { provider: String(porAlias), rol: ROL_LLAVE, fuente: `catálogo · env-alias[${v}]` };
  }
  for (const s of _SUFIJOS) {
    if (v.endsWith(s.sufijo) && v.length > s.sufijo.length) {
      const base = v.slice(0, -s.sufijo.length).toLowerCase();
      return { provider: base + s.cola, rol: s.rol, fuente: `convención · ${s.sufijo}` };
    }
  }
  return null;
}

/** LAS CREDENCIALES QUE UNA PIEZA PIDE, UNA FILA POR VARIABLE.
 *
 * ⚠️ POR QUÉ UNA FILA POR VARIABLE Y NO UN BOOLEANO. Porque `ONSHAPE_ACCESS_TOKEN` y
 * `ONSHAPE_OAUTH_META` son DOS credenciales con DOS entradas distintas en el vault
 * (`onshape` y `onshape__oauth`) y DOS roles distintos: una es el bearer con el que se
 * llama a la API, la otra es el sobre cifrado con el refresh y la expiración. Un booleano
 * «¿pide credencial?» las funde, y lo que sigue a fundirlas es **copiar un valor en las
 * dos variables** — que es el bug que esta función existe para hacer imposible.
 *
 * Y por eso además incluye los HEADERS: en un server HTTP el `Authorization` es tan
 * credencial como una env var. Mirar sólo `env` dejaba a las piezas HTTP con llave
 * pareciendo keyless.
 */
export function credencialesQuePide({ servidorBelt, alias } = {}) {
  const out = [];
  const belt = servidorBelt || {};
  const visto = new Set();
  const agregar = (variable, donde) => {
    // EL CATÁLOGO GANA SOBRE LA CONVENCIÓN. Si un alias declara que esta variable ES la
    // credencial de un provider, lo es — aunque su nombre parezca una ruta. Hay proveedores
    // cuya credencial ES un archivo, y el catálogo es quien tiene autoridad para decirlo.
    const declarada = !!(alias && (alias[String(variable).toUpperCase()] || alias[variable]));
    if (!declarada && !esVariableDeCredencial(variable)) return;
    const k = `${donde}:${variable}`;
    if (visto.has(k)) return;
    visto.add(k);
    const p = providerDeVariable(variable, alias);
    out.push({
      variable,
      donde,
      provider: p ? p.provider : null,
      rol: p ? p.rol : null,
      fuente: p ? `belt.${donde}[${variable}] → ${p.fuente}` : `belt.${donde}[${variable}]`,
    });
  };
  /* ── [OBRA 6b · #4] UN HEADER QUE RENDERIZA OTRA CREDENCIAL NO ES UNA CREDENCIAL ──────
   *
   * `Authorization: Bearer ${RESOLVER_X_API_KEY}` no pide una llave: pide LA MISMA llave
   * que la variable que interpola, y esa variable ya está contada (el backend la proyecta
   * dentro de `env`). Contarlo aparte inventaba una segunda credencial cuyo nombre
   * —«Authorization»— no resuelve a ningún provider, y esa huérfana disparaba
   * `credencial_sin_provider_resoluble` → bloqueo NUESTRO → la pieza se caía del local y de
   * la aduana a la vez. Medido: la pieza con llave no aparecía en ninguna parte y su
   * trámite era imposible de hacer.
   *
   * De dónde sale la referencia, en este orden: `headers_ref` (nombres, lo que manda el
   * backend — el valor está tapado a propósito) y, si no está, el valor mismo, que es lo
   * que trae un belt del catálogo. Dos fuentes para el mismo hecho porque hay dos orígenes
   * de belt, no porque haya dos verdades. */
  const REF = /\$\{([A-Za-z_][A-Za-z0-9_]*)(?::[^}]*)?\}/g;
  const referenciasDe = (header) => {
    const declaradas = (belt.headers_ref || {})[header];
    if (Array.isArray(declaradas)) return declaradas;
    const valor = (belt.headers || {})[header];
    return typeof valor === "string"
      ? Array.from(valor.matchAll(REF), (m) => m[1])
      : [];
  };

  for (const k of Object.keys(belt.env || {})) agregar(k, "env");
  const yaContadas = new Set(out.map((c) => c.variable));
  for (const k of Object.keys(belt.headers || {})) {
    const refs = referenciasDe(k);
    // Sólo se omite cuando TODAS sus referencias ya están contadas. Si apunta a una
    // variable que nadie declaró, el header es el único que la lleva y sigue contando:
    // callarlo ahí escondería una credencial de verdad.
    if (refs.length && refs.every((v) => yaContadas.has(v))) continue;
    agregar(k, "headers");
  }
  return out;
}

/** ¿DE QUÉ TIPO ES ESTA PIEZA? Sale de lo que DECLARA, nunca de cómo se llama.
 *
 * Una pieza puede ser varios tipos: un OAuth que además baja un programa es `oauth` y
 * `descarga`, y le aplican las reglas de los dos. Es la diferencia entre una taxonomía y
 * una lista de casos.
 */
export function tiposDe({ ficha, servidorBelt, alias } = {}) {
  const tipos = new Set([T_TRANSVERSAL]);
  const belt = servidorBelt || {};
  const auth = (ficha || {}).auth_method || null;
  const pide = credencialesQuePide({ servidorBelt: belt, alias });

  if (auth === "oauth" || auth === "admin_oauth" ||
      pide.some((c) => c.rol === ROL_ACCESO || c.rol === ROL_COMPANION)) tipos.add(T_OAUTH);
  if (auth === "personal_token" ||
      pide.some((c) => c.rol === ROL_LLAVE || c.rol === null)) tipos.add(T_LLAVE);
  // DESCARGA: la pieza necesita algo INSTALADO en la máquina del usuario. La señal es el
  // campo estructurado `instalacion`; `requiere_app` es la prosa histórica y cuenta igual
  // para el TIPO (la pieza sí necesita la app) aunque no alcance para armar el PASO.
  if (belt.instalacion || belt.requiere_app) tipos.add(T_DESCARGA);
  // HTTP: el server vive del otro lado de una URL. No hay proceso que arrancar, así que
  // media tabla transversal (npx frío, dos procesos, arranque) no le aplica.
  if (belt.url || belt.transport === "http" || belt.transport === "sse" ||
      belt.type === "http" || belt.type === "sse") tipos.add(T_HTTP);
  return Array.from(tipos);
}

/* ══════════════════════════════════════════════════════════════════════════════════════
 * LA TABLA
 * ════════════════════════════════════════════════════════════════════════════════════ */

const _cx = (ctx) => (ctx.medicion && ctx.medicion.conexion) || {};
const _cr = (ctx) => (ctx.medicion && ctx.medicion.credencial) || {};
const _ev = (ctx) => _cx(ctx).evidencia || {};
/** La clase que dio repair, NORMALIZADA. `repair_clasificar` la emite en minúscula
 *  (`"temporal"`); comparar contra `"TEMPORAL"` hacía que la regla de lo temporal no se
 *  aplicara NUNCA — silenciosamente, que es la peor forma. Se normaliza en un solo lugar. */
const _clase = (ctx) => {
  const c = (ctx.clasificacion || {}).clase;
  return c ? String(c).toUpperCase() : null;
};

/** Un ajuste del veredicto. Se declara con la regla que lo produjo para que el [?] pueda
 *  decir POR QUÉ una pieza no está pintada como su estado crudo sugeriría. */
const ajuste = (regla, campos) => Object.assign({ regla }, campos);

export const REGLAS = [
  // ══ OAUTH ══════════════════════════════════════════════════════════════════════════
  {
    id: "oauth/roles-distintos",
    tipo: T_OAUTH,
    dice: "`_ACCESS_TOKEN` y `_OAUTH_META` son dos credenciales con roles distintos: " +
          "jamás se rellena una con el valor de la otra.",
    porque: "Son dos entradas separadas del vault (`x` y `x__oauth`). Copiar el bearer en " +
            "el companion deja al refresh sin sobre y la sesión muere en silencio a la hora.",
    aplica: (ctx) => ctx.credenciales.length > 1,
    efecto: (ctx) => {
      // Dos variables de ROLES distintos que resuelven al MISMO provider sólo puede
      // significar que alguien las fundió. Es una contradicción, no una preferencia.
      const porProvider = new Map();
      for (const c of ctx.credenciales) {
        if (!c.provider) continue;
        const previo = porProvider.get(c.provider);
        if (previo && previo.rol !== c.rol) {
          return {
            contradiccion: {
              tipo: "dos_roles_de_credencial_sobre_el_mismo_provider",
              pide: [previo.variable, c.variable], dice: c.provider,
              fuente: `${previo.fuente} y ${c.fuente} caen en el mismo provider ` +
                      `«${c.provider}» con roles ${previo.rol}/${c.rol}`,
            },
          };
        }
        porProvider.set(c.provider, c);
      }
      return null;
    },
  },
  {
    id: "oauth/superficie-por-scopes",
    tipo: T_OAUTH,
    dice: "La superficie de un OAuth nace de los SCOPES CONCEDIDOS. Cero tools no es roto: " +
          "es que el usuario no concedió (todavía) lo que hace falta.",
    porque: "El belt lo dice explícito: «si un scope no está en el token_response.scope, su " +
            "tool no aparece en tools/list». Pintar eso `rota · sin_tools` manda a arreglar " +
            "un servidor que está perfecto.",
    aplica: (ctx) => _cx(ctx).causa === "sin_tools" && ctx.scopesDeclarados.length > 0,
    efecto: (ctx) => {
      const faltan = ctx.scopesDeclarados.filter((s) => !ctx.scopesConcedidos.includes(s));
      if (!faltan.length) return null;   // los concedió todos: el sin_tools es otra cosa
      return {
        paso: {
          tipo: "oauth", accion: "credencial", territorio: "usuario",
          scopes_faltantes: faltan,
          fuente: `ficha.oauth.scopes[] vs registro.scopes — faltan ${faltan.join(", ")}`,
        },
        ajuste: ajuste("oauth/superficie-por-scopes", {
          estado: "esperando", donde: "oauth", bloqueo: "usuario",
          motivo: "falta autorizar",
          fuente: `sin_tools con ${faltan.length} scope(s) sin conceder`,
        }),
      };
    },
  },
  {
    id: "oauth/expira-recalculado",
    tipo: T_OAUTH,
    dice: "Un veredicto verde deja de valer cuando su credencial expira. `expira_en` " +
          "recalculado vence la medición, aunque nadie haya medido de nuevo.",
    porque: "Un OAuth verde medido a las 10:00 con un token que expiraba a las 10:30 se " +
            "sigue viendo verde a las 14:00. La medición no miente: caducó.",
    aplica: (ctx) => instanteDe(_cr(ctx).expira_en) > 0,
    efecto: (ctx) => {
      const expira = instanteDe(_cr(ctx).expira_en);
      if (expira > ctx.ahora) return null;
      return {
        // ⚠️ «LA SESIÓN VENCIÓ» NO ES «TU LLAVE FUE RECHAZADA», y la diferencia es cara: la
        // primera se arregla reconectando —el usuario no tiene que conseguir nada nuevo— y
        // la segunda lo manda a buscar otra credencial. Decirle «rechazada» a un token que
        // simplemente caducó lo manda a buscar una llave que ya tiene.
        //
        // Por eso el paso declara su propio `pide`: el rótulo genérico del tipo («falta
        // autorizar tu cuenta») es cierto pero pierde justo el dato que ahorra el viaje.
        paso: {
          tipo: "oauth", accion: "credencial", territorio: "usuario", reconectar: true,
          pide: "sesion_vencida",
          fuente: `registro.credencial.expira_en=${expira} ya pasó (ahora=${ctx.ahora})`,
        },
        ajuste: ajuste("oauth/expira-recalculado", {
          estado: "esperando", donde: "oauth", bloqueo: "usuario",
          motivo: "la sesión venció",
          fuente: `registro.credencial.expira_en=${expira} ya pasó (ahora=${ctx.ahora})`,
        }),
        // El refresh es NUESTRO y corre solo; el paso de usuario aparece sólo si el
        // refresh ya falló (causa `oauth_revocado`, que tiene su propia regla).
        nota: { que: "refresh_pendiente", fuente: "credencial.expira_en vencido" },
      };
    },
  },
  {
    id: "oauth/invalid-grant-es-reconectar",
    tipo: T_OAUTH,
    dice: "`invalid_grant` / grant revocado se resuelve RECONECTANDO. Jamás «revisa tu llave».",
    porque: "La llave está perfecta: lo que se cayó es el consentimiento del lado del " +
            "proveedor. Mandarlo a conseguir una credencial nueva es mandarlo a buscar algo " +
            "que ya tiene.",
    aplica: (ctx) => _cx(ctx).causa === "oauth_revocado" ||
                     /invalid_grant/i.test(String(_ev(ctx).detail || _cx(ctx).evidencia || "")),
    efecto: () => ({
      paso: {
        tipo: "oauth", accion: "credencial", territorio: "usuario", reconectar: true,
        fuente: "registro.conexion.causa=oauth_revocado",
      },
      ajuste: ajuste("oauth/invalid-grant-es-reconectar", {
        estado: "esperando", donde: "oauth", bloqueo: "usuario",
        motivo: "falta autorizar",
        fuente: "el grant se revocó del lado del proveedor: se vuelve a consentir",
      }),
      prohibe: ["llave"],   // ← el guard: esta pieza NO puede pedir una llave.
    }),
  },
  {
    id: "oauth/client-secret-con-pkce",
    tipo: T_OAUTH,
    dice: "Que un proveedor exija `client_secret` aun con PKCE es una SALVEDAD declarada, " +
          "no un error de configuración.",
    porque: "PKCE nació para no necesitar secreto, pero varios proveedores lo piden igual. " +
            "Marcarlo como contradicción llenaba el censo de bugs falsos sobre piezas sanas.",
    aplica: (ctx) => !!(ctx.oauth && ctx.oauth.pkce && ctx.oauth.client_secret_required),
    efecto: () => ({
      // Explícitamente NADA de usuario: es una nota interna que sirve para no volver a
      // reportarlo como hallazgo.
      nota: { que: "pkce_con_client_secret", fuente: "ficha.oauth.pkce + client_secret_required" },
      absuelve: ["la_ficha_declara_tramite_que_el_belt_no_pide"],
    }),
  },

  {
    id: "transversal/credencial-por-archivo",
    tipo: T_TRANSVERSAL,
    dice: "Una RUTA a credencial (`*_CREDENTIALS_PATH`, `*_OAUTH_PATH`) declara que la " +
          "credencial llega como ARCHIVO. El trámite existe; lo que cambia es el transporte.",
    porque: "Medido en el censo, y es el error espejo del anterior: excluir esas rutas del " +
            "llavero es correcto —no hay valor que guardar— pero concluir que la pieza no " +
            "pide credencial marcaba como contradicción una ficha que estaba bien.",
    aplica: (ctx) => rutasDeCredencial(ctx.belt).length > 0,
    efecto: (ctx) => ({
      nota: {
        que: "credencial_por_archivo",
        valor: rutasDeCredencial(ctx.belt).join(", "),
        fuente: `belt.env declara rutas de credencial: el trámite deja un archivo, no un valor`,
      },
      // El trámite SÍ existe: la ficha no se contradice con el belt.
      absuelve: ["la_ficha_declara_tramite_que_el_belt_no_pide"],
    }),
  },

  // ══ LLAVE ══════════════════════════════════════════════════════════════════════════
  {
    id: "llave/la-doble-siempre",
    tipo: T_LLAVE,
    dice: "El verde de una llave sale de la prueba DOBLE: la real devuelve un dato tuyo Y " +
          "la basura es rechazada. Con una sola mitad no hay verde.",
    porque: "Un server que contesta 200 a cualquier cosa —o que ignora la credencial— pasa " +
            "la mitad real y falla la de basura. Acreditar con media prueba es exactamente " +
            "el verde sin evidencia que la ley de fondo prohíbe.",
    // ⚠️ LO QUE ESTA REGLA MIRA ES LA EVIDENCIA, NO EL ESTADO — y la distinción se pagó
    // leyendo el registro real. El verificador **sólo escribe `verde` cuando la doble
    // completó** (`conexiones_verificador.py`: «real da dato Y basura da rechazo»), así que
    // re-litigar el estado sería poner a este archivo a dudar de quien sí midió: la segunda
    // verdad sobre la misma pieza que el adaptador existe para eliminar.
    //
    // Lo que sí es asunto de esta regla es el ESCRUTINIO: un `verde` que no dice CON QUÉ
    // TOOL se certificó es un verde sin evidencia, y por la ley de fondo eso no existe —
    // venga del verificador o de cualquier otra cosa que haya escrito esa fila.
    aplica: (ctx) => _cr(ctx).estado === "verde",
    efecto: (ctx) => {
      const cr = _cr(ctx);
      if (cr.tool_prueba) return null;
      return {
        ajuste: ajuste("llave/la-doble-siempre", {
          estado: "conectado", donde: null, bloqueo: "ninguno",
          motivo: "midiendo · el verde no dice con qué tool se certificó",
          fuente: "registro.credencial=verde sin `tool_prueba`: la prueba doble no dejó rastro",
        }),
        nota: { que: "verify_pendiente", fuente: "verde sin evidencia de la tool" },
      };
    },
  },
  {
    id: "llave/sin-verificar-es-nuestro",
    tipo: T_LLAVE,
    dice: "«Sin verificar» es tarea NUESTRA: nunca un botón, nunca una duda devuelta al usuario.",
    porque: "`candidata` y `sin_medir` significan que no la medimos todavía, no que la llave " +
            "tenga algo. La card decía «llave sin verificar» y le entregaba nuestra duda para " +
            "que se preocupara por algo que no puede resolver.",
    aplica: (ctx) => ["sin_medir", "candidata"].includes(_cr(ctx).estado || "") &&
                     ctx.credencialEnVault,
    efecto: () => ({
      paso: {
        tipo: "esperar", accion: null, territorio: "ninguno",
        fuente: "vault (la llave está) · verify pendiente, corre solo",
      },
      prohibe: ["llave"],
      nota: { que: "verify_pendiente", fuente: "credencial guardada sin medir" },
    }),
  },
  {
    id: "llave/sufijos-resuelven-provider",
    tipo: T_LLAVE,
    dice: "El vault se consulta POR PROVIDER de cada variable —resuelto por alias del " +
          "catálogo o por sufijo— nunca por el nombre de la pieza.",
    // ⚠️ El `porque` NO nombra la pieza que lo destapó, y no es pudor: el guard de
    // generalidad lee estos strings como código, y con razón — una regla que necesita
    // nombrar una pieza para explicarse es una regla que todavía no se generalizó.
    porque: "Una pieza cuya variable no sigue la convención guarda su llave bajo el " +
            "provider que declara el alias del catálogo. Buscarla por el nombre de la " +
            "entidad devolvía «falta tu llave» con la llave pegada ese mismo día.",
    aplica: (ctx) => ctx.credenciales.length > 0,
    efecto: (ctx) => {
      const huerfanas = ctx.credenciales.filter((c) => !c.provider);
      if (!huerfanas.length) return null;
      return {
        contradiccion: {
          tipo: "credencial_sin_provider_resoluble",
          pide: huerfanas.map((c) => c.variable), dice: "(ninguno)",
          fuente: `${huerfanas.map((c) => c.variable).join(", ")} no matchean alias del ` +
                  `catálogo ni convención de sufijo: nadie sabe bajo qué nombre buscarlas`,
        },
      };
    },
  },

  // ══ DESCARGA ═══════════════════════════════════════════════════════════════════════
  {
    id: "descarga/publicar-tools-no-prueba-nada",
    tipo: T_DESCARGA,
    dice: "Un server de descarga BOOTEA CON LA APP CERRADA: saluda, publica tools y revienta " +
          "en la primera llamada. «Publica tools» no acredita nada; hay que mirar la máquina.",
    porque: "Medido: un canal `sin_sondear` sobre una pieza que necesita un programa local se " +
            "veía ✅ Conectado, y la primera vez que el agente la usaba fallaba. El canal MCP " +
            "y el programa instalado son dos hechos distintos.",
    aplica: (ctx) => _cx(ctx).estado === "sin_sondear",
    efecto: (ctx) => ({
      ajuste: ajuste("descarga/publicar-tools-no-prueba-nada", {
        estado: "esperando", donde: "instalar", bloqueo: "usuario",
        motivo: "falta la app",
        fuente: `canal establecido sin tool ejercitada sobre una pieza que declara ` +
                `${ctx.belt.instalacion ? "belt.instalacion" : "belt.requiere_app"}: ` +
                `publicar tools no prueba que el programa esté`,
      }),
    }),
  },
  {
    id: "descarga/instalar-es-link-mas-verificar",
    tipo: T_DESCARGA,
    dice: "El paso de instalación es LINK ESTRUCTURADO + [Ya lo instalé · verificar]. " +
          "Prosa sin link no es un paso.",
    porque: "No se puede poner un link en un párrafo. Una pieza con `requiere_app` y sin " +
            "`instalacion` deja al usuario buscando solo, que es el dead-end que la ley prohíbe.",
    aplica: (ctx) => !!ctx.belt.requiere_app && !(ctx.belt.instalacion || {}).link,
    efecto: () => ({
      contradiccion: {
        tipo: "ficha_sin_link_de_instalacion",
        pide: [], dice: "requiere_app (prosa)",
        fuente: "belt.requiere_app sin `instalacion.link`: no hay a dónde mandar al usuario",
      },
    }),
  },

  // ══ HTTP ═══════════════════════════════════════════════════════════════════════════
  {
    id: "http/keyless-legitimo-existe",
    tipo: T_HTTP,
    dice: "Un server HTTP sin credenciales es keyless LEGÍTIMO. Ausencia declarada, no ficha faltante.",
    porque: "La primera versión del censo marcaba 30 piezas como bug porque no tenían ficha " +
            "de onboarding. No hay trámite que describir: no hay trámite.",
    aplica: (ctx) => ctx.credenciales.length === 0 && !ctx.ficha,
    efecto: () => ({
      nota: { que: "keyless_declarado", fuente: "belt http sin env ni headers de credencial" },
      absuelve: ["pide_credencial_y_no_tiene_ficha"],
    }),
  },
  {
    id: "http/headers-byo-son-secretos",
    tipo: T_HTTP,
    dice: "Un header BYO es tan secreto como una env var: va al llavero por referencia y el " +
          "manifest lleva SÓLO el nombre.",
    porque: "Un `Authorization: Bearer <valor>` literal en un `.mcp.json` es una credencial " +
            "en claro en un archivo versionado. El mismo guard que ya cubre `env_template` " +
            "cubre `headers_template`: un token en un header es tan secreto como en una env.",
    aplica: (ctx) => Object.keys(ctx.belt.headers || {}).length > 0,
    efecto: (ctx) => {
      // [OBRA 6b · #4] UN HEADER QUE REFERENCIA UNA VARIABLE NO ES UN SECRETO EN CLARO,
      // aunque su valor no llegue. Este filtro miraba SÓLO el valor con un regex anclado
      // (`^${VAR}$`), y fallaba dos veces sobre lo mismo: `Bearer ${VAR}` no matchea por el
      // prefijo, y encima el valor real ni siquiera cruza la API —viaja tapado como
      // «valor literal», que es lo correcto—. Resultado medido: TODA pieza HTTP con header
      // de plantilla era denunciada por llevar su token en claro cuando lleva un nombre.
      // La referencia declarada (`headers_ref`) es la fuente que faltaba; el valor crudo
      // sigue valiendo para los belts del catálogo, que sí lo traen.
      const referencia = (k) => {
        const declaradas = (ctx.belt.headers_ref || {})[k];
        if (Array.isArray(declaradas) && declaradas.length) return true;
        return /\$\{[A-Za-z_][A-Za-z0-9_]*(?::[^}]*)?\}/.test(
          String((ctx.belt.headers || {})[k]));
      };
      const enClaro = Object.entries(ctx.belt.headers || {})
        .filter(([k]) => esVariableDeCredencial(k) && !referencia(k))
        .map(([k]) => k);
      if (!enClaro.length) return null;
      return {
        contradiccion: {
          tipo: "secreto_en_claro_en_el_manifest",
          pide: enClaro, dice: "valor literal",
          fuente: `belt.headers[${enClaro.join(", ")}] trae un valor donde va un ` +
                  `\${PLACEHOLDER}: el manifest sólo puede llevar nombres`,
        },
      };
    },
  },
  {
    id: "http/timeout-no-es-roto",
    tipo: T_HTTP,
    dice: "Un `timeout` NO es roto mientras no haya desempate. Sin `murio` ni reloj vencido, " +
          "lo único cierto es que hay que volver a medir.",
    porque: "El desempate ya existe y es de repair: `murio` (el proceso se fue) o `reloj` " +
            "(venció de verdad). Sin ninguno de los dos, declarar roto manda a alguien a " +
            "arreglar un hipo de red.",
    aplica: (ctx) => _cx(ctx).causa === "timeout",
    efecto: (ctx) => {
      const d = (ctx.clasificacion || {}).desempate || null;
      if (d) return null;              // repair desempató: su veredicto manda, no éste
      return {
        ajuste: ajuste("http/timeout-no-es-roto", {
          estado: "conectado", donde: null, bloqueo: "ninguno",
          motivo: "midiendo · timeout sin desempate",
          fuente: "registro.conexion.causa=timeout sin `murio` ni reloj vencido",
        }),
        nota: { que: "verify_pendiente", fuente: "timeout sin desempate" },
      };
    },
  },

  // ══ TRANSVERSAL ════════════════════════════════════════════════════════════════════
  {
    id: "transversal/veredicto-con-fecha",
    tipo: T_TRANSVERSAL,
    dice: "Un veredicto SIN FECHA no es un veredicto. No puede pintar un rojo.",
    porque: "Un rojo viejo y uno falso son indistinguibles si nadie mira su edad. Los tres " +
            "rojos falsos del censo —piezas que arrancaban y publicaban tools— eran " +
            "mediciones sin nadie que preguntara de cuándo eran.",
    aplica: (ctx) => _cx(ctx).estado === "rota" && !instanteDe(_cx(ctx).ts),
    efecto: () => ({
      ajuste: ajuste("transversal/veredicto-con-fecha", {
        estado: "conectado", donde: null, bloqueo: "ninguno",
        motivo: "midiendo · el veredicto no tiene fecha",
        fuente: "registro.conexion.ts vacío: una medición sin cuándo no manda",
      }),
      nota: { que: "verify_pendiente", fuente: "veredicto sin fecha" },
    }),
  },
  {
    id: "transversal/arranque-sin-refinar-es-temporal",
    tipo: T_TRANSVERSAL,
    dice: "`arranque` sin causa refinada es TEMPORAL: se re-mide sola y no pinta rojo.",
    porque: "COSTO ASIMÉTRICO. Equivocarse hacia temporal cuesta una medición; equivocarse " +
            "hacia permanente manda a una persona a arreglar un problema que no existe. Es " +
            "la causa de dos de los tres rojos falsos medidos.",
    aplica: (ctx) => _cx(ctx).estado === "rota" && _clase(ctx) === "TEMPORAL",
    efecto: (ctx) => ({
      ajuste: ajuste("transversal/arranque-sin-refinar-es-temporal", {
        estado: "conectado", donde: null, bloqueo: "ninguno",
        motivo: "midiendo · causa temporal",
        fuente: `repair clasificó «${_cx(ctx).causa || "sin causa"}» como TEMPORAL: ` +
                `se reintenta acotado antes de mandar a nadie a arreglar nada`,
      }),
      nota: { que: "verify_pendiente", fuente: "causa temporal" },
    }),
  },
  {
    id: "transversal/servidor-incompatible-lo-arregla-repair",
    tipo: T_TRANSVERSAL,
    dice: "`servidor_incompatible` es territorio de Aleph: repair vuelve solo a la última " +
          "versión que anduvo. Sin botón y sin pedirle permiso a nadie.",
    porque: "La receta es nuestra. Pedirle al usuario que fije una versión de un paquete es " +
            "mandarle un trámite por un problema que no creó. Sólo si el auto-ajuste falla " +
            "—un intento, sin loops— la pieza llega a «no disponible».",
    aplica: (ctx) => (_cx(ctx).causa === "servidor_incompatible" ||
                      _ev(ctx).causa_refinada === "servidor_incompatible"),
    efecto: (ctx) => {
      const yaIntento = !!(_ev(ctx).autoajuste_intentado);
      if (yaIntento) {
        // El auto-ajuste ya corrió y no alcanzó: recién AHORA es un bloqueo, y aun así sin
        // botón — no hay acción del usuario que sirva.
        return {
          ajuste: ajuste("transversal/servidor-incompatible-lo-arregla-repair", {
            estado: "bloqueado", donde: "verify", bloqueo: "nuestro",
            motivo: "no disponible por ahora",
            fuente: "el auto-ajuste de versión ya se intentó y no alcanzó (§5 · escalada)",
          }),
          prohibe: ["llave", "instalar", "oauth"],
        };
      }
      return {
        paso: {
          tipo: "esperar", accion: null, territorio: "ninguno",
          fuente: "repair · auto-ajuste de versión (R5), corre solo",
        },
        ajuste: ajuste("transversal/servidor-incompatible-lo-arregla-repair", {
          estado: "conectado", donde: null, bloqueo: "ninguno",
          motivo: "ajustando · la receta es nuestra",
          fuente: "repair vuelve solo a la última versión que anduvo (R5)",
        }),
        prohibe: ["llave", "instalar", "oauth"],
      };
    },
  },
  {
    id: "transversal/primer-boot-frio-no-es-roto",
    tipo: T_TRANSVERSAL,
    dice: "El PRIMER boot de un lanzador que baja el paquete (`npx`/`uvx`/`bunx`) es lento " +
          "por diseño. Un timeout ahí no es un server roto.",
    porque: "La primera vez el lanzador descarga el paquete entero antes de hablar MCP. " +
            "Medirlo con la misma paciencia que a un server ya instalado da rojo sobre " +
            "piezas que andan perfecto a partir del segundo arranque.",
    aplica: (ctx) => {
      const cmd = String(ctx.belt.command || "");
      const frio = /(^|\/)(npx|uvx|bunx|pipx)$/.test(cmd);
      return frio && ["timeout", "arranque", "sin_respuesta"].includes(_cx(ctx).causa || "") &&
             !ctx.tuvoVerdePrevio;
    },
    efecto: (ctx) => ({
      ajuste: ajuste("transversal/primer-boot-frio-no-es-roto", {
        estado: "conectado", donde: null, bloqueo: "ninguno",
        motivo: "midiendo · primer arranque en frío",
        fuente: `belt.command=${ctx.belt.command} baja el paquete la primera vez y todavía ` +
                `no hubo un verde previo: se vuelve a medir con paciencia`,
      }),
      nota: { que: "verify_pendiente", fuente: "primer boot en frío" },
    }),
  },
  {
    id: "transversal/env-declarado-o-bloqueo",
    tipo: T_TRANSVERSAL,
    dice: "Una variable que el server necesita y el registro no declara es un BLOQUEO " +
          "NUESTRO con nombre. No se inventa, no se hereda del ambiente.",
    porque: "Heredar del ambiente hace que ande en la máquina del que la exportó y en " +
            "ninguna otra, y que la huella de la conexión mienta. Declarada o bloqueo: no " +
            "hay tercera opción.",
    aplica: (ctx) => ctx.credenciales.length > 0 && !!ctx.envDeclarado,
    efecto: (ctx) => {
      const declaradas = new Set(Object.keys(ctx.envDeclarado || {}));
      // ⚠️ DECLARAR TIENE DOS FORMAS, Y LA SEGUNDA CASI PRODUCE UN HALLAZGO FALSO. El
      // registro declara una credencial por VARIABLE (`env_template`) **o** por PROVIDER
      // (`credencial_ref`), y en el segundo caso el assembler completa las variables desde
      // el manifest al armar la receta. Mirar sólo `env_template` marcaba como «heredaría
      // del ambiente» a una pieza cuya llave estaba perfectamente referenciada.
      const porRef = String(ctx.credencialRef || "").toLowerCase();
      const faltan = ctx.credenciales
        .filter((c) => c.donde === "env" && !declaradas.has(c.variable) &&
                       !(porRef && String(c.provider || "").toLowerCase() === porRef))
        .map((c) => c.variable);
      if (!faltan.length) return null;
      return {
        contradiccion: {
          tipo: "env_que_el_server_pide_y_el_registro_no_declara",
          pide: faltan, dice: "(no declarada)",
          fuente: `belt.env=[${faltan.join(", ")}] sin entrada en registro.env_template ` +
                  `ni env_publico: correría heredando del ambiente`,
        },
      };
    },
  },
  {
    id: "transversal/residuo-no-es-rota",
    tipo: T_TRANSVERSAL,
    dice: "Una entidad SIN FILA en el registro es RESIDUO —se ofrece limpiar—, no una pieza rota.",
    porque: "Basura de pruebas quedaba contada como conexión caída y ensuciaba el conteo. " +
            "Nunca se midió: no hay veredicto que dar.",
    aplica: (ctx) => !ctx.medicion || (!ctx.medicion.conexion && !ctx.medicion.credencial),
    efecto: () => ({
      ajuste: ajuste("transversal/residuo-no-es-rota", {
        estado: "bloqueado", donde: "residuo", bloqueo: "nuestro",
        motivo: "residuo · entidad sin fila de conexión",
        fuente: "no hay fila en el registro: nunca se midió, no hay veredicto que dar",
      }),
      prohibe: ["llave", "instalar", "oauth"],
      nota: { que: "ofrecer_limpiar", fuente: "entidad sin fila" },
    }),
  },
  {
    id: "transversal/placeholder-sin-expandir",
    tipo: T_TRANSVERSAL,
    dice: "Un `command`/`args` con un `<placeholder>` sin expandir NUNCA va a arrancar. " +
          "Es un bug de receta, no un server caído.",
    porque: "Medido: una fila del registro traía `<mcp-install>/…` literal. Reintentarla " +
            "cuesta un arranque fallido cada vez y el usuario ve un rojo que ninguna acción " +
            "suya puede mover.",
    aplica: (ctx) => {
      const partes = [ctx.belt.command, ...(ctx.belt.args || [])].map(String);
      return partes.some((p) => /<[a-z][a-z0-9._-]*>/i.test(p));
    },
    efecto: (ctx) => {
      const partes = [ctx.belt.command, ...(ctx.belt.args || [])].map(String);
      const sucias = partes.filter((p) => /<[a-z][a-z0-9._-]*>/i.test(p));
      return {
        contradiccion: {
          tipo: "receta_con_placeholder_sin_expandir",
          pide: sucias, dice: "(sin expandir)",
          fuente: `belt.command/args traen ${sucias.join(", ")}: la receta nunca se resolvió`,
        },
      };
    },
  },
  {
    id: "transversal/dos-procesos-por-server",
    tipo: T_TRANSVERSAL,
    dice: "Un server MCP son DOS procesos. El conteo se divide antes de mostrarse y no se " +
          "usa jamás como señal de salud.",
    porque: "Contar procesos y encontrar uno no prueba que no arrancó; encontrar dos no " +
            "prueba que haya dos servers. La salud la dice `verify`, que pregunta por MCP.",
    aplica: (ctx) => Number(_ev(ctx).procesos || 0) > 0,
    efecto: (ctx) => ({
      nota: {
        que: "procesos",
        valor: Math.round(Number(_ev(ctx).procesos) / PROCESOS_POR_SERVER),
        fuente: `evidencia.procesos=${_ev(ctx).procesos} ÷ ${PROCESOS_POR_SERVER}`,
      },
    }),
  },
];

/** APLICAR LA TABLA · el contexto entra, el efecto acumulado sale.
 *
 * El orden de las reglas NO decide: cada una declara su efecto y `aplicar` los junta. El
 * único desempate es el de los ajustes, y es explícito: **el que bloquea gana sobre el que
 * libera**, porque la ley de fondo dice que lo que no se puede escrutar completo no se
 * muestra como si estuviera bien.
 */
export function aplicar(entrada = {}) {
  const belt = entrada.servidorBelt || {};
  const oauth = (entrada.ficha || {}).oauth || null;
  const ctx = {
    ...entrada,
    belt,
    oauth,
    ahora: Number(entrada.ahora || 0) || Math.floor(Date.now() / 1000),
    credenciales: credencialesQuePide({ servidorBelt: belt, alias: entrada.alias }),
    scopesDeclarados: ((oauth || {}).scopes || [])
      .filter((s) => s && s.requested !== false).map((s) => s.id || s).filter(Boolean),
    scopesConcedidos: (entrada.scopesConcedidos || []).map(String),
    credencialEnVault: !!entrada.credencialEnVault,
    tuvoVerdePrevio: !!entrada.tuvoVerdePrevio,
    envDeclarado: entrada.envDeclarado || null,
    credencialRef: entrada.credencialRef || null,
    clasificacion: entrada.clasificacion || null,
  };
  const tipos = tiposDe({ ficha: ctx.ficha, servidorBelt: belt, alias: ctx.alias });

  const salida = {
    tipos, aplicadas: [], pasos: [], contradicciones: [], notas: [],
    ajuste: null, prohibidos: new Set(), absueltos: new Set(),
  };

  for (const regla of REGLAS) {
    if (regla.tipo !== T_TRANSVERSAL && !tipos.includes(regla.tipo)) continue;
    let efecto = null;
    try { efecto = regla.aplica(ctx) ? regla.efecto(ctx) : null; }
    catch (_) { efecto = null; }        // una regla que revienta no puede tumbar la card
    if (!efecto) continue;
    salida.aplicadas.push(regla.id);
    if (efecto.paso) salida.pasos.push({ ...efecto.paso, regla: regla.id });
    if (efecto.contradiccion)
      salida.contradicciones.push({ ...efecto.contradiccion, regla: regla.id });
    if (efecto.nota) salida.notas.push({ ...efecto.nota, regla: regla.id });
    for (const p of efecto.prohibe || []) salida.prohibidos.add(p);
    for (const a of efecto.absuelve || []) salida.absueltos.add(a);
    if (efecto.ajuste) {
      // EL QUE BLOQUEA GANA. Dos reglas que ajustan el mismo veredicto no se pisan por
      // orden de tabla: se resuelven por severidad, que es la ley de fondo escrita como
      // desempate. `esperando` gana sobre `conectado` porque hay algo del usuario; y
      // `bloqueado` gana sobre todo porque la pieza no se pudo escrutar completa.
      const peso = { conectado: 0, esperando: 1, bloqueado: 2 };
      const actual = salida.ajuste;
      if (!actual || (peso[efecto.ajuste.estado] || 0) > (peso[actual.estado] || 0))
        salida.ajuste = efecto.ajuste;
    }
  }
  salida.prohibidos = Array.from(salida.prohibidos);
  salida.absueltos = Array.from(salida.absueltos);
  return salida;
}
