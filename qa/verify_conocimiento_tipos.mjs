#!/usr/bin/env node
/**
 * verify_conocimiento_tipos.mjs — LA VARA DE LA TABLA DE CONOCIMIENTO POR TIPO.
 *
 *   node qa/verify_conocimiento_tipos.mjs
 *
 * persona usuaria dictó la tabla entera —oauth · llave · descarga · http · transversal— y la condición
 * fue explícita: **cada regla con su test**. Esta vara es esa condición hecha guard.
 *
 * Tres cosas se comprueban, y las tres fallan ruidosamente:
 *
 *   1 · COBERTURA — ninguna regla puede existir sin al menos un caso acá. Una regla sin test
 *       es una creencia: nadie sabe si sigue haciendo lo que dice cuando el código cambia.
 *   2 · GENERALIDAD — ninguna regla puede nombrar un conector. Se prueba contra los nombres
 *       reales del catálogo, no contra una lista escrita a mano. Es el mismo guard que ya
 *       protege `widget.js`, y por el mismo motivo: un `if` por conector muere en la pieza 29.
 *   3 · CONDUCTA — cada caso arma un contexto SINTÉTICO (nunca una pieza real, para que el
 *       test no dependa de qué está roto hoy) y verifica el efecto que la regla promete.
 *
 * Los datos son sintéticos A PROPÓSITO. Lo que se congela es la CAPACIDAD, no el ejemplar:
 * si mañana la pieza que motivó una regla se arregla, la regla tiene que seguir viva.
 */
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..");
const K = await import(join(RAIZ, "product/app/design/conectores/conocimiento.js"));

const FALLOS = [];
const ok = (c, t, d = "") => {
  console.log((c ? "  ✅ " : "  ❌ ") + t + (d ? ` · ${d}` : ""));
  if (!c) FALLOS.push(t);
  return c;
};

/** Los alias del CATÁLOGO — la misma tabla que inyecta el assembler. Si el adaptador
 *  usara otra, volveríamos a tener dos verdades sobre el mismo nombre de variable. */
const ALIAS = (() => {
  const j = JSON.parse(readFileSync(join(RAIZ, "catalog/connectors/env-alias.json"), "utf8"));
  const out = {};
  for (const [prov, vars] of Object.entries(j.alias || {}))
    for (const v of vars) if (!out[v]) out[v] = prov;   // primero gana, igual que en Python
  return out;
})();

/** Los nombres reales del catálogo, para el guard de generalidad. */
const NOMBRES = (() => {
  const out = new Set(); const stack = [join(RAIZ, "catalog")];
  while (stack.length) {
    const dir = stack.pop();
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, e.name);
      if (e.isDirectory()) stack.push(p);
      else if (e.name.endsWith(".mcp.json")) {
        try { for (const s of Object.keys(JSON.parse(readFileSync(p, "utf8")).mcpServers || {})) out.add(s); }
        catch (_) { /* ignora */ }
      }
    }
  }
  return Array.from(out).filter((s) => s.length > 4);
})();

const aplicar = (extra) => K.aplicar({ alias: ALIAS, ahora: 1000, ...extra });
const uso = (salida, id) => salida.aplicadas.includes(id);
const contra = (salida, tipo) => salida.contradicciones.find((c) => c.tipo === tipo);

/* ══ LOS CASOS · uno o más por regla, con datos sintéticos ═══════════════════════════ */
const CASOS = {

  "oauth/roles-distintos": [{
    nombre: "dos variables de roles distintos que caen en el MISMO provider → contradicción",
    correr: () => {
      // `ACME_ACCESS_TOKEN` → provider `acme` (rol acceso). Un alias del catálogo que
      // mandara `ACME_OAUTH_META` al mismo `acme` sería la fusión que la regla prohíbe.
      const s = K.aplicar({
        alias: { ACME_OAUTH_META: "acme" }, ahora: 1000,
        servidorBelt: { env: { ACME_ACCESS_TOKEN: "${ACME_ACCESS_TOKEN}",
                               ACME_OAUTH_META: "${ACME_OAUTH_META}" } },
        medicion: { conexion: { estado: "viva", ts: 900 } },
      });
      ok(uso(s, "oauth/roles-distintos"), "la regla se aplica");
      ok(!!contra(s, "dos_roles_de_credencial_sobre_el_mismo_provider"),
         "y delata la fusión de roles",
         (contra(s, "dos_roles_de_credencial_sobre_el_mismo_provider") || {}).fuente);
    },
  }, {
    nombre: "las MISMAS dos variables, bien resueltas, dan dos providers distintos",
    correr: () => {
      const c = K.credencialesQuePide({
        servidorBelt: { env: { ACME_ACCESS_TOKEN: "x", ACME_OAUTH_META: "y" } }, alias: ALIAS });
      const porVar = Object.fromEntries(c.map((x) => [x.variable, x]));
      ok(porVar.ACME_ACCESS_TOKEN.provider === "acme" &&
         porVar.ACME_ACCESS_TOKEN.rol === K.ROL_ACCESO,
         "`_ACCESS_TOKEN` → provider base, rol acceso", porVar.ACME_ACCESS_TOKEN.provider);
      ok(porVar.ACME_OAUTH_META.provider === "acme__oauth" &&
         porVar.ACME_OAUTH_META.rol === K.ROL_COMPANION,
         "`_OAUTH_META` → provider companion, rol companion", porVar.ACME_OAUTH_META.provider);
      ok(porVar.ACME_ACCESS_TOKEN.provider !== porVar.ACME_OAUTH_META.provider,
         "y son DOS entradas del vault, no una copiada en las dos");
    },
  }],

  "oauth/superficie-por-scopes": [{
    nombre: "`sin_tools` con scopes sin conceder → falta autorizar, no roto",
    correr: () => {
      const s = aplicar({
        ficha: { auth_method: "oauth",
                 oauth: { scopes: [{ id: "Leer", requested: true }, { id: "Escribir", requested: true }] } },
        servidorBelt: { env: { ACME_ACCESS_TOKEN: "${ACME_ACCESS_TOKEN}" } },
        medicion: { conexion: { estado: "rota", causa: "sin_tools", ts: 900 } },
        scopesConcedidos: ["Leer"],
      });
      ok(uso(s, "oauth/superficie-por-scopes"), "la regla se aplica");
      ok(s.ajuste && s.ajuste.estado === "esperando" && s.ajuste.bloqueo === "usuario",
         "el veredicto pasa a esperando al USUARIO", s.ajuste && s.ajuste.motivo);
      const paso = s.pasos.find((p) => p.tipo === "oauth");
      ok(paso && paso.scopes_faltantes.join(",") === "Escribir",
         "y nombra el scope que falta conceder", paso && paso.scopes_faltantes.join(","));
    },
  }, {
    nombre: "con TODOS los scopes concedidos, la regla no inventa un paso",
    correr: () => {
      const s = aplicar({
        ficha: { auth_method: "oauth", oauth: { scopes: [{ id: "Leer", requested: true }] } },
        servidorBelt: { env: { ACME_ACCESS_TOKEN: "x" } },
        medicion: { conexion: { estado: "rota", causa: "sin_tools", ts: 900 } },
        scopesConcedidos: ["Leer"],
      });
      ok(!uso(s, "oauth/superficie-por-scopes"),
         "cero tools con todo concedido es otra cosa: la regla se calla");
    },
  }],

  "oauth/expira-recalculado": [{
    nombre: "un verde cuya credencial expiró ya no es verde",
    correr: () => {
      const s = aplicar({
        ficha: { auth_method: "oauth" },
        servidorBelt: { env: { ACME_ACCESS_TOKEN: "x" } },
        medicion: { conexion: { estado: "viva", ts: 500 },
                    credencial: { estado: "verde", expira_en: 800 } },
        ahora: 1000,
      });
      ok(uso(s, "oauth/expira-recalculado"), "la regla se aplica");
      ok(s.ajuste && s.ajuste.motivo === "la sesión venció",
         "y dice que venció la SESIÓN, no que la llave sea inválida", s.ajuste && s.ajuste.fuente);
      // ⚠️ Y EL MATIZ LLEGA HASTA LA CARD. Que el veredicto lo sepa no alcanza: si el paso
      // no lo declara, la superficie pinta el rótulo genérico del tipo («falta autorizar tu
      // cuenta») y se pierde justo el dato que le ahorra al usuario salir a buscar una llave
      // que ya tiene. Fue una regresión real de esta tanda, cazada por las citas del diseño.
      const paso = s.pasos.find((p) => p.tipo === "oauth");
      ok(paso && paso.pide === "sesion_vencida" && paso.reconectar === true,
         "y el PASO declara el matiz, para que la card no diga sólo «falta autorizar»",
         paso && paso.pide);
    },
  }, {
    nombre: "un verde con la credencial todavía vigente no se toca",
    correr: () => {
      const s = aplicar({
        ficha: { auth_method: "oauth" }, servidorBelt: { env: { ACME_ACCESS_TOKEN: "x" } },
        medicion: { conexion: { estado: "viva", ts: 500 },
                    credencial: { estado: "verde", expira_en: 5000, prueba_real: true,
                                  basura_rechazada: true } },
        ahora: 1000,
      });
      ok(!s.ajuste, "sin ajuste: la medición sigue valiendo");
    },
  }],

  "oauth/invalid-grant-es-reconectar": [{
    nombre: "grant revocado → reconectar, y PROHIBIDO pedir una llave",
    correr: () => {
      const s = aplicar({
        ficha: { auth_method: "oauth" }, servidorBelt: { env: { ACME_ACCESS_TOKEN: "x" } },
        medicion: { conexion: { estado: "rota", causa: "oauth_revocado", ts: 900 } },
      });
      ok(uso(s, "oauth/invalid-grant-es-reconectar"), "la regla se aplica");
      ok(s.pasos.some((p) => p.tipo === "oauth" && p.reconectar), "el paso es reconectar");
      ok(s.prohibidos.includes("llave"),
         "y la pieza NO puede pedir una llave: la que tiene está perfecta");
    },
  }],

  "oauth/client-secret-con-pkce": [{
    nombre: "PKCE que además exige client_secret es salvedad declarada, no bug",
    correr: () => {
      const s = aplicar({
        ficha: { auth_method: "oauth", oauth: { pkce: true, client_secret_required: true } },
        servidorBelt: { env: { ACME_ACCESS_TOKEN: "x" } },
        medicion: { conexion: { estado: "viva", ts: 900 } },
      });
      ok(uso(s, "oauth/client-secret-con-pkce"), "la regla se aplica");
      ok(s.contradicciones.length === 0, "cero contradicciones: es una salvedad, no un error");
      ok(s.notas.some((n) => n.que === "pkce_con_client_secret"),
         "y queda anotada para no volver a reportarla como hallazgo");
    },
  }],

  "transversal/credencial-por-archivo": [{
    nombre: "una ruta a credencial no va al llavero PERO tampoco niega el trámite",
    correr: () => {
      const s = aplicar({
        ficha: { auth_method: "oauth" },
        servidorBelt: { command: "python3",
                        env: { ACME_CREDENTIALS_PATH: "${ACME_CREDENTIALS_PATH}" } },
        medicion: { conexion: { estado: "viva", ts: 900 } },
      });
      ok(uso(s, "transversal/credencial-por-archivo"), "la regla se aplica");
      ok(K.credencialesQuePide({
        servidorBelt: { env: { ACME_CREDENTIALS_PATH: "x" } }, alias: ALIAS }).length === 0,
         "la ruta NO se pide como llave: no hay valor que guardar");
      ok(s.absueltos.includes("la_ficha_declara_tramite_que_el_belt_no_pide"),
         "pero la ficha que declara el trámite deja de ser una contradicción");
      ok(s.contradicciones.length === 0, "cero contradicciones sobre una pieza sana");
    },
  }],

  "llave/la-doble-siempre": [{
    nombre: "un verde que no dice con qué tool se certificó no acredita: se re-mide",
    correr: () => {
      const s = aplicar({
        ficha: { auth_method: "personal_token" },
        servidorBelt: { env: { ACME_API_KEY: "x" } },
        medicion: { conexion: { estado: "viva", ts: 900 },
                    credencial: { estado: "verde", tool_prueba: null } },
      });
      ok(uso(s, "llave/la-doble-siempre"), "la regla se aplica");
      ok(s.ajuste && /con qué tool/.test(s.ajuste.motivo),
         "un verde sin evidencia no existe", s.ajuste && s.ajuste.fuente);
      ok(s.notas.some((n) => n.que === "verify_pendiente"), "y verify queda pendiente");
    },
  }, {
    nombre: "el verde COMO LO ESCRIBE EL VERIFICADOR —con su tool— sí acredita",
    correr: () => {
      // Ésta es la forma real del registro: el verificador sólo escribe `verde` cuando la
      // doble completó, y deja la tool que la certificó. La regla no re-litiga eso.
      const s = aplicar({
        ficha: { auth_method: "personal_token" }, servidorBelt: { env: { ACME_API_KEY: "x" } },
        medicion: { conexion: { estado: "viva", ts: 900 },
                    credencial: { estado: "verde", tool_prueba: "buscar_algo",
                                  evidencia: "dio dato con tu llave y rechazo con basura" } },
      });
      ok(!uso(s, "llave/la-doble-siempre"), "la regla se calla: la prueba dejó rastro");
    },
  }],

  "llave/sin-verificar-es-nuestro": [{
    nombre: "llave guardada sin medir → paso NUESTRO, sin botón, y prohibido pedirla",
    correr: () => {
      const s = aplicar({
        ficha: { auth_method: "personal_token" }, servidorBelt: { env: { ACME_API_KEY: "x" } },
        medicion: { conexion: { estado: "viva", ts: 900 }, credencial: { estado: "sin_medir" } },
        credencialEnVault: true,
      });
      ok(uso(s, "llave/sin-verificar-es-nuestro"), "la regla se aplica");
      const paso = s.pasos.find((p) => p.tipo === "esperar");
      ok(paso && paso.territorio === "ninguno" && paso.accion === null,
         "el paso no es del usuario y no tiene acción");
      ok(s.prohibidos.includes("llave"),
         "«falta tu llave» con la llave en el vault queda imposible por construcción");
    },
  }],

  "llave/sufijos-resuelven-provider": [{
    nombre: "una variable de credencial sin provider resoluble se delata",
    correr: () => {
      const s = aplicar({
        servidorBelt: { env: { WEIRD_CREDENTIAL: "${WEIRD_CREDENTIAL}" } },
        medicion: { conexion: { estado: "viva", ts: 900 } },
      });
      ok(uso(s, "llave/sufijos-resuelven-provider"), "la regla se aplica");
      ok(!!contra(s, "credencial_sin_provider_resoluble"),
         "nadie sabe bajo qué nombre buscarla, y eso se dice",
         (contra(s, "credencial_sin_provider_resoluble") || {}).fuente);
    },
  }, {
    nombre: "un alias del catálogo resuelve el provider aunque el nombre no siga la convención",
    correr: () => {
      const p = K.providerDeVariable("HF_TOKEN", ALIAS);
      ok(p && p.provider === "huggingface",
         "`HF_TOKEN` → provider `huggingface`, desde el catálogo", p && p.fuente);
      const s = aplicar({
        servidorBelt: { env: { HF_TOKEN: "${HF_TOKEN}" } },
        medicion: { conexion: { estado: "viva", ts: 900 } },
      });
      ok(!contra(s, "credencial_sin_provider_resoluble"),
         "y por eso NO se reporta como huérfana");
    },
  }],

  "descarga/publicar-tools-no-prueba-nada": [{
    nombre: "canal establecido sobre una pieza que necesita un programa NO acredita",
    correr: () => {
      const s = aplicar({
        servidorBelt: { command: "python3",
                        instalacion: { que: "El programa", link: "https://example.com" } },
        medicion: { conexion: { estado: "sin_sondear", ts: 900 } },
      });
      ok(uso(s, "descarga/publicar-tools-no-prueba-nada"), "la regla se aplica");
      ok(s.ajuste && s.ajuste.estado === "esperando" && s.ajuste.donde === "instalar",
         "queda esperando la instalación, no verde", s.ajuste && s.ajuste.fuente);
    },
  }, {
    nombre: "la MISMA medición sobre una pieza que no baja nada sí queda conectada",
    correr: () => {
      const s = aplicar({
        servidorBelt: { command: "python3" },
        medicion: { conexion: { estado: "sin_sondear", ts: 900 } },
      });
      ok(!uso(s, "descarga/publicar-tools-no-prueba-nada"),
         "sin `instalacion` ni `requiere_app` la regla no aplica: el canal alcanza");
    },
  }],

  "descarga/instalar-es-link-mas-verificar": [{
    nombre: "prosa sin link estructurado es ficha incompleta, no un paso",
    correr: () => {
      const s = aplicar({
        servidorBelt: { command: "python3", requiere_app: "Hay que bajar el programa" },
        medicion: { conexion: { estado: "rota", causa: "cli_no_instalado", ts: 900 } },
      });
      ok(uso(s, "descarga/instalar-es-link-mas-verificar"), "la regla se aplica");
      ok(!!contra(s, "ficha_sin_link_de_instalacion"),
         "y nombra el hueco: no hay a dónde mandar al usuario");
    },
  }],

  "http/keyless-legitimo-existe": [{
    nombre: "un server HTTP sin credenciales es keyless legítimo, no una ficha faltante",
    correr: () => {
      const s = aplicar({
        ficha: null, servidorBelt: { url: "https://example.com/mcp" },
        medicion: { conexion: { estado: "viva", ts: 900 } },
      });
      ok(uso(s, "http/keyless-legitimo-existe"), "la regla se aplica");
      ok(s.absueltos.includes("pide_credencial_y_no_tiene_ficha"),
         "y absuelve el bug falso de «sin ficha»");
      ok(s.contradicciones.length === 0, "cero contradicciones sobre una pieza sana");
    },
  }],

  "http/headers-byo-son-secretos": [{
    nombre: "un header de credencial con VALOR literal en el manifest es un secreto en claro",
    correr: () => {
      const s = aplicar({
        servidorBelt: { url: "https://example.com/mcp", headers: { Authorization: "Bearer abc123" } },
        medicion: { conexion: { estado: "viva", ts: 900 } },
      });
      ok(uso(s, "http/headers-byo-son-secretos"), "la regla se aplica");
      ok(!!contra(s, "secreto_en_claro_en_el_manifest"),
         "y lo delata", (contra(s, "secreto_en_claro_en_el_manifest") || {}).fuente);
    },
  }, {
    nombre: "el mismo header por referencia es correcto Y cuenta como credencial pedida",
    correr: () => {
      const s = aplicar({
        servidorBelt: { url: "https://example.com/mcp",
                        headers: { ACME_AUTH_TOKEN: "${ACME_AUTH_TOKEN}" } },
        medicion: { conexion: { estado: "viva", ts: 900 } },
      });
      ok(!contra(s, "secreto_en_claro_en_el_manifest"), "sin contradicción: es una referencia");
      const c = K.credencialesQuePide({
        servidorBelt: { headers: { ACME_AUTH_TOKEN: "${ACME_AUTH_TOKEN}" } }, alias: ALIAS });
      ok(c.length === 1 && c[0].donde === "headers",
         "y el header cuenta como credencial: un token en un header es tan secreto como en una env");
    },
  }],

  "http/timeout-no-es-roto": [{
    nombre: "timeout sin desempate no es roto: se vuelve a medir",
    correr: () => {
      const s = aplicar({
        servidorBelt: { url: "https://example.com/mcp" },
        medicion: { conexion: { estado: "rota", causa: "timeout", ts: 900 } },
        clasificacion: { clase: "TEMPORAL", desempate: null },
      });
      ok(uso(s, "http/timeout-no-es-roto"), "la regla se aplica");
      ok(s.ajuste && s.ajuste.bloqueo === "ninguno", "no bloquea a nadie", s.ajuste && s.ajuste.fuente);
    },
  }, {
    nombre: "timeout CON desempate: manda repair, no esta regla",
    correr: () => {
      const s = aplicar({
        servidorBelt: { url: "https://example.com/mcp" },
        medicion: { conexion: { estado: "rota", causa: "timeout", ts: 900 } },
        clasificacion: { clase: "TEMPORAL", desempate: "murio" },
      });
      ok(!uso(s, "http/timeout-no-es-roto"),
         "con `murio` la regla se calla: el veredicto de repair manda");
    },
  }],

  "transversal/veredicto-con-fecha": [{
    nombre: "un rojo SIN fecha no pinta rojo",
    correr: () => {
      const s = aplicar({
        servidorBelt: { command: "python3" },
        medicion: { conexion: { estado: "rota", causa: "arranque", ts: null } },
      });
      ok(uso(s, "transversal/veredicto-con-fecha"), "la regla se aplica");
      ok(s.ajuste && s.ajuste.bloqueo === "ninguno",
         "una medición sin cuándo no manda", s.ajuste && s.ajuste.fuente);
    },
  }],

  "transversal/arranque-sin-refinar-es-temporal": [{
    nombre: "una causa que repair clasificó TEMPORAL no pinta rojo: se re-mide sola",
    correr: () => {
      const s = aplicar({
        servidorBelt: { command: "python3" },
        medicion: { conexion: { estado: "rota", causa: "arranque", ts: 900 } },
        clasificacion: { clase: "TEMPORAL", desempate: null },
      });
      ok(uso(s, "transversal/arranque-sin-refinar-es-temporal"), "la regla se aplica");
      ok(s.ajuste && s.ajuste.bloqueo === "ninguno", "cero bloqueo", s.ajuste && s.ajuste.fuente);
      ok(s.notas.some((n) => n.que === "verify_pendiente"), "y verify vuelve a correr solo");
    },
  }, {
    nombre: "una causa PERMANENTE sí se respeta",
    correr: () => {
      const s = aplicar({
        servidorBelt: { command: "python3" },
        medicion: { conexion: { estado: "rota", causa: "cli_no_instalado", ts: 900 } },
        clasificacion: { clase: "PERMANENTE", desempate: "causa_refinada" },
      });
      ok(!uso(s, "transversal/arranque-sin-refinar-es-temporal"),
         "la regla no toca lo que repair dio por permanente");
    },
  }],

  "transversal/servidor-incompatible-lo-arregla-repair": [{
    nombre: "servidor_incompatible sin auto-ajuste previo → lo arregla repair, sin botón",
    correr: () => {
      const s = aplicar({
        servidorBelt: { command: "python3" },
        medicion: { conexion: { estado: "rota", causa: "arranque", ts: 900,
                                evidencia: { causa_refinada: "servidor_incompatible" } } },
      });
      ok(uso(s, "transversal/servidor-incompatible-lo-arregla-repair"), "la regla se aplica");
      ok(s.ajuste && s.ajuste.bloqueo === "ninguno" && /ajustando/.test(s.ajuste.motivo),
         "la receta es nuestra: se ajusta sola", s.ajuste && s.ajuste.fuente);
      ok(s.prohibidos.includes("llave") && s.prohibidos.includes("instalar"),
         "y no se le pide NADA al usuario");
    },
  }, {
    nombre: "con el auto-ajuste ya intentado, recién ahí es un bloqueo — y aun así sin botón",
    correr: () => {
      const s = aplicar({
        servidorBelt: { command: "python3" },
        medicion: { conexion: { estado: "rota", causa: "servidor_incompatible", ts: 900,
                                evidencia: { autoajuste_intentado: true } } },
      });
      ok(s.ajuste && s.ajuste.estado === "bloqueado" && s.ajuste.bloqueo === "nuestro",
         "bloqueo NUESTRO", s.ajuste && s.ajuste.fuente);
      ok(s.prohibidos.includes("oauth"), "sigue sin haber trámite que pedirle a nadie");
    },
  }],

  "transversal/primer-boot-frio-no-es-roto": [{
    nombre: "el primer arranque de un lanzador que baja el paquete no es un server roto",
    correr: () => {
      const s = aplicar({
        servidorBelt: { command: "npx", args: ["-y", "algun-paquete"] },
        medicion: { conexion: { estado: "rota", causa: "timeout", ts: 900 } },
        tuvoVerdePrevio: false,
      });
      ok(uso(s, "transversal/primer-boot-frio-no-es-roto"), "la regla se aplica");
      ok(s.ajuste && s.ajuste.bloqueo === "ninguno", "se vuelve a medir con paciencia",
         s.ajuste && s.ajuste.fuente);
    },
  }, {
    nombre: "con un verde previo, el mismo timeout SÍ cuenta",
    correr: () => {
      const s = aplicar({
        servidorBelt: { command: "npx", args: ["-y", "algun-paquete"] },
        medicion: { conexion: { estado: "rota", causa: "timeout", ts: 900 } },
        tuvoVerdePrevio: true,
      });
      ok(!uso(s, "transversal/primer-boot-frio-no-es-roto"),
         "el paquete ya estaba bajado: la excusa del frío se terminó");
    },
  }],

  "transversal/env-declarado-o-bloqueo": [{
    nombre: "una variable que el server pide y el registro no declara es bloqueo con nombre",
    correr: () => {
      const s = aplicar({
        servidorBelt: { env: { ACME_API_KEY: "${ACME_API_KEY}", OTRO_API_KEY: "${OTRO_API_KEY}" } },
        medicion: { conexion: { estado: "viva", ts: 900 } },
        envDeclarado: { ACME_API_KEY: "keys:acme" },
      });
      ok(uso(s, "transversal/env-declarado-o-bloqueo"), "la regla se aplica");
      const c = contra(s, "env_que_el_server_pide_y_el_registro_no_declara");
      ok(c && c.pide.join(",") === "OTRO_API_KEY", "y nombra la que falta", c && c.fuente);
    },
  }],

  "transversal/residuo-no-es-rota": [{
    nombre: "una entidad sin fila de conexión es residuo, no una pieza rota",
    correr: () => {
      const s = aplicar({ servidorBelt: { command: "python3" }, medicion: null });
      ok(uso(s, "transversal/residuo-no-es-rota"), "la regla se aplica");
      ok(s.ajuste && s.ajuste.motivo.startsWith("residuo"),
         "el veredicto es residuo", s.ajuste && s.ajuste.fuente);
      ok(s.notas.some((n) => n.que === "ofrecer_limpiar"), "y se ofrece limpiar");
    },
  }],

  "transversal/placeholder-sin-expandir": [{
    nombre: "un command con placeholder sin expandir nunca va a arrancar, y se dice",
    correr: () => {
      const s = aplicar({
        servidorBelt: { command: "<mcp-install>/algo/server.py", args: [] },
        medicion: { conexion: { estado: "rota", causa: "arranque", ts: 900 } },
      });
      ok(uso(s, "transversal/placeholder-sin-expandir"), "la regla se aplica");
      ok(!!contra(s, "receta_con_placeholder_sin_expandir"),
         "es un bug de receta, no un server caído",
         (contra(s, "receta_con_placeholder_sin_expandir") || {}).fuente);
    },
  }, {
    nombre: "una ruta resuelta de verdad no dispara nada",
    correr: () => {
      const s = aplicar({
        servidorBelt: { command: "python3", args: ["${PUPPET_BELTS}/x/server.py"] },
        medicion: { conexion: { estado: "viva", ts: 900 } },
      });
      ok(!uso(s, "transversal/placeholder-sin-expandir"),
         "`${PUPPET_BELTS}` es territorio propio y se resuelve en runtime: no es un placeholder muerto");
    },
  }],

  "transversal/dos-procesos-por-server": [{
    nombre: "el conteo de procesos se divide por dos antes de mostrarse",
    correr: () => {
      const s = aplicar({
        servidorBelt: { command: "python3" },
        medicion: { conexion: { estado: "viva", ts: 900, evidencia: { procesos: 4 } } },
      });
      ok(uso(s, "transversal/dos-procesos-por-server"), "la regla se aplica");
      const n = s.notas.find((x) => x.que === "procesos");
      ok(n && n.valor === 2, "4 procesos = 2 servers", n && n.fuente);
      ok(!s.ajuste, "y el conteo NO decide el estado: la salud la dice verify");
    },
  }],
};

/* ══ 1 · COBERTURA ═══════════════════════════════════════════════════════════════════ */
console.log("══ VARA DE LA TABLA DE CONOCIMIENTO POR TIPO ══\n");
console.log(`1 · COBERTURA · las ${K.REGLAS.length} reglas tienen que tener test`);
{
  const sinTest = K.REGLAS.filter((r) => !(CASOS[r.id] || []).length).map((r) => r.id);
  ok(sinTest.length === 0, `las ${K.REGLAS.length} reglas tienen al menos un caso`,
     sinTest.length ? `SIN TEST: ${sinTest.join(", ")}` : "");
  const huerfanos = Object.keys(CASOS).filter((id) => !K.REGLAS.some((r) => r.id === id));
  ok(huerfanos.length === 0, "y no hay tests de reglas que ya no existen",
     huerfanos.join(", "));
  const sinPorque = K.REGLAS.filter((r) => !r.dice || !r.porque).map((r) => r.id);
  ok(sinPorque.length === 0, "cada regla declara QUÉ dice y POR QUÉ existe",
     sinPorque.join(", "));
  const tiposOk = K.REGLAS.every((r) =>
    [K.T_OAUTH, K.T_LLAVE, K.T_DESCARGA, K.T_HTTP, K.T_TRANSVERSAL].includes(r.tipo));
  ok(tiposOk, "y todas caen en un tipo declarado");
}

/* ══ 2 · GENERALIDAD ═════════════════════════════════════════════════════════════════ */
console.log("\n2 · GENERALIDAD · cero nombres de conector en la tabla");
{
  const src = readFileSync(join(RAIZ, "product/app/design/conectores/conocimiento.js"), "utf8");
  const cuerpo = src.split("\n").filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l)).join("\n");
  const hard = NOMBRES.filter((s) => new RegExp(`["'\`]${s}["'\`]`).test(cuerpo));
  ok(hard.length === 0,
     `cero nombres de conector en el código (probado contra los ${NOMBRES.length} del catálogo)`,
     hard.length ? `HARDCODEADOS: ${hard.join(", ")}` : "");
  //: Y el guard de la otra mitad: la tabla de alias NO puede vivir en el código. Si alguien
  //: la vuelve a escribir en JS, esto lo agarra.
  ok(!/HF_TOKEN|GDRIVE_TOKEN|SLACK_BOT_TOKEN/.test(cuerpo),
     "los alias por proveedor viven en el catálogo, no en el código");
}

/* ══ 3 · CONDUCTA ════════════════════════════════════════════════════════════════════ */
console.log("\n3 · CONDUCTA · cada regla hace lo que promete");
for (const regla of K.REGLAS) {
  console.log(`\n  ▸ ${regla.id}`);
  console.log(`    «${regla.dice}»`);
  for (const caso of CASOS[regla.id] || []) {
    console.log(`    · ${caso.nombre}`);
    try { caso.correr(); }
    catch (e) { ok(false, `${regla.id} · el caso reventó`, String(e && e.message || e)); }
  }
}

/* ══ 4 · UNA PIEZA SANA NO GENERA RUIDO ══════════════════════════════════════════════ */
console.log("\n4 · una pieza coherente no dispara ninguna regla");
{
  const s = aplicar({
    ficha: { auth_method: "personal_token" },
    servidorBelt: { command: "python3", args: ["${PUPPET_BELTS}/x/server.py"],
                    env: { ACME_API_KEY: "${ACME_API_KEY}" } },
    medicion: { conexion: { estado: "viva", ts: "2026-08-04T10:00:00", tool_usada: "algo" },
                credencial: { estado: "verde", tool_prueba: "algo" } },
    envDeclarado: { ACME_API_KEY: "keys:acme" },
    credencialEnVault: true,
  });
  ok(s.aplicadas.length === 0, "cero reglas aplicadas sobre una pieza sana",
     s.aplicadas.join(", "));
  ok(s.contradicciones.length === 0 && !s.ajuste, "cero contradicciones y cero ajustes");
  ok(s.tipos.includes(K.T_LLAVE) && s.tipos.includes(K.T_TRANSVERSAL),
     "y su tipo se derivó igual", s.tipos.join("+"));
}

/* ══ 5 · LAS FECHAS DEL REGISTRO SON ISO ═════════════════════════════════════════════ */
console.log("\n5 · una fecha se lee venga como venga (el registro las guarda en ISO)");
{
  // ⚠️ ESTE CASO ES UN BUG MEDIDO, NO UNA PRECAUCIÓN. El adaptador leía los `ts` con
  // `Number()`, que sobre el ISO del registro da `NaN`: la ley «una medición vieja no
  // manda» respondía «sin medición previa» sobre las 42 filas reales y nunca se aplicó a
  // nadie. Los tests no lo veían porque usaban enteros.
  ok(K.instanteDe("2026-07-31T21:40:38") > 0,
     "un ISO del registro se lee como instante", String(K.instanteDe("2026-07-31T21:40:38")));
  ok(K.instanteDe(1754300000) === 1754300000, "un epoch se lee tal cual");
  ok(K.instanteDe(null) === 0 && K.instanteDe("") === 0 && K.instanteDe("ayer") === 0,
     "y lo que no es fecha da 0, que es lo que la regla de la fecha necesita");
  const s = aplicar({
    servidorBelt: { command: "python3" },
    medicion: { conexion: { estado: "rota", causa: "arranque", ts: "2026-07-31T21:40:38" } },
    clasificacion: { clase: "PERMANENTE" },
  });
  ok(!uso(s, "transversal/veredicto-con-fecha"),
     "un rojo CON fecha ISO no se confunde con uno sin fecha");
}

console.log("\n" + (FALLOS.length === 0
  ? `══ ✅ LA TABLA CUMPLE · ${K.REGLAS.length} reglas, todas con test y ninguna por conector ══`
  : `══ ❌ ${FALLOS.length} FALLO(S): ${JSON.stringify(FALLOS)} ══`));
process.exit(FALLOS.length ? 1 : 0);
