/* verify_obra6b_front.mjs — la mitad de superficie de la Obra 6b (#4b y #5).
 *
 * La corre `qa/verify_obra6b.py`; imprime una línea JSON con los testigos. No se invoca
 * suelta: la vara es una sola, como manda la casa.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { instalarDOM, host } from "./dom_minimo.mjs";

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..");
const D = join(RAIZ, "product/app/design");
instalarDOM();
globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
globalThis.sessionStorage = globalThis.localStorage;

const K = await import(join(D, "conectores/conocimiento.js"));
const S = await import(join(D, "conectores/superficie.js"));
const M = await import(join(D, "conectores/montaje.js"));

const R = {};

/* ══ #4b · UN HEADER QUE RENDERIZA OTRA CREDENCIAL NO ES UNA CREDENCIAL ═══════════════
 *
 * Tres entradas a la MISMA función, con tres desenlaces distintos. Eso es lo que prueba que
 * discrimina en vez de callarse siempre — un filtro que omite todo saldría verde en el caso
 * bueno y estaría rompiendo los otros dos.
 */
const ALIAS = { RESOLVER_X_API_KEY: "resolver_x" };

// (a) POSITIVO — el backend dice a qué apunta el header, y la variable ya está contada.
const conRef = K.credencialesQuePide({
  servidorBelt: {
    env: { RESOLVER_X_API_KEY: "${RESOLVER_X_API_KEY}" },
    headers: { Authorization: "«valor literal»" },
    headers_ref: { Authorization: ["RESOLVER_X_API_KEY"] },
  },
  alias: ALIAS,
});
R["4b_header_que_renderiza_no_cuenta"] = {
  ok: conRef.length === 1 && conRef[0].variable === "RESOLVER_X_API_KEY"
      && !!conRef[0].provider,
  variables: conRef.map((c) => `${c.variable}(${c.donde})→${c.provider}`),
};

// (b) NEGATIVO — sin `headers_ref` y con el valor tapado, no sabemos a qué apunta: el
//     header SIGUE contando. Es el mundo de hoy, y tiene que seguir siendo así: callarlo
//     por las dudas escondería una credencial de verdad.
const sinRef = K.credencialesQuePide({
  servidorBelt: {
    env: { RESOLVER_X_API_KEY: "${RESOLVER_X_API_KEY}" },
    headers: { Authorization: "«valor literal»" },
  },
  alias: ALIAS,
});
R["4b_negativo_sin_referencia_sigue_contando"] = {
  ok: sinRef.some((c) => c.variable === "Authorization"),
  variables: sinRef.map((c) => `${c.variable}(${c.donde})`),
};

// (c) NEGATIVO 2 — apunta a una variable que NADIE declaró: el header es el único que la
//     lleva, así que no se omite.
const refHuerfana = K.credencialesQuePide({
  servidorBelt: {
    env: {},
    headers: { Authorization: "«valor literal»" },
    headers_ref: { Authorization: ["NO_DECLARADA_API_KEY"] },
  },
  alias: ALIAS,
});
R["4b_negativo_referencia_no_contada_sigue_contando"] = {
  ok: refHuerfana.some((c) => c.variable === "Authorization"),
  variables: refHuerfana.map((c) => `${c.variable}(${c.donde})`),
};

// (d) el valor CRUDO también sirve de fuente (belt de catálogo, sin tapar)
const porValor = K.credencialesQuePide({
  servidorBelt: {
    env: { RESOLVER_X_API_KEY: "${RESOLVER_X_API_KEY}" },
    headers: { Authorization: "Bearer ${RESOLVER_X_API_KEY}" },
  },
  alias: ALIAS,
});
R["4b_el_valor_crudo_tambien_sirve"] = {
  ok: !porValor.some((c) => c.variable === "Authorization"),
  variables: porValor.map((c) => `${c.variable}(${c.donde})`),
};

/* ══ #5 · LA RESERVA TIENE UN CLICK ═══════════════════════════════════════════════════
 *
 * No alcanza con que el HTML exista: el bug que esto arregla era exactamente ése. Se monta
 * la pantalla, se aprieta el `[?]` de la fila REAL que la superficie emitió, y se mira si
 * la reserva aparece adentro del panel que ese click abrió.
 */
function modelo({ reserva = null, evidencia = null } = {}) {
  return {
    entityId: "pieza-x", nombre: "pieza-x", slug: "pieza-x",
    estado: "viva", apagada: false, estuvoCompleta: false,
    veredicto: { estado: "conectado", bloqueo: "ninguno", fuente: "verify", motivo: null,
                 contradicciones: [] },
    header: { estado: "viva", ts: "2026-08-06T19:00:00" },
    evidencia: { estado: "viva", ts: "2026-08-06T19:00:00", tool_usada: "t", causa: null,
                 evidencia },
    pasos: [], boton: null, credencial: { estado: "no_hace_falta" },
    conocimiento: { tipos: [], credenciales: [], reglas: [] },
    pertenencia: { local: true, faltan: [] }, trazas: [],
    reserva,
  };
}

const RESERVA = { texto_1linea: "No se pudo confirmar la identidad del namespace.",
                  detalle: "Señal del matcher: 0.538." };
const CITA = "404: belt no encontrado · Te avisamos al traerla: No se pudo confirmar…";

// (a) el testigo de ALCANZABILIDAD: click real sobre el nodo que la superficie emitió
Object.assign(M.ESTADO, { modelos: [], vault: {}, vista: "conectores", leido: false,
                          abierto: null, detalle: null, q: "" });
M.ESTADO.midiendo.clear();
const hosts = {
  lista: host("localRows"), resumen: host("cxSummary"), conteo: host("localCount"),
  aduana: host("aduanaRows"), conteoAduana: host("aduanaCount"),
  seccionAduana: host("aduanaSection"), llavero: host("keyringRows"),
  conteoLlavero: host("keyringCount"), panelConectores: host("connectorsView"),
  panelLlavero: host("keyringView"), cabecera: host("cxHead"), tabs: host("cxTabs"),
};
M.VERBOS.cargar = async () => ({
  modelos: [modelo({ reserva: RESERVA, evidencia: CITA })], vault: {}, leido: true, alias: {} });
M.VERBOS.barrerLocal = async () => false;
M.VERBOS.medir = async () => false;
await M.montar(hosts);
await new Promise((r) => setTimeout(r, 30));

const boton = hosts.lista.querySelector('[data-detalle="pieza-x"]');
if (boton) await boton.click();
const panel = hosts.lista.querySelector('[data-panel="pieza-x"]');
const html = panel ? (panel.innerHTML || "") : "";
R["5_la_reserva_tiene_un_click"] = {
  ok: !!boton && !!panel && html.includes("cx-reserva")
      && html.includes('data-reserva="pieza-x"'),
  hay_boton: !!boton, hay_panel: !!panel, bytes: html.length,
};
R["5_la_evidencia_se_ve"] = { ok: html.includes("Te avisamos al traerla") };

// (b) NEGATIVO — una pieza SIN reserva no pinta el bloque (si lo pintara siempre, el
//     positivo no probaría nada).
const sin = S.pintarDetalle(modelo({ reserva: null, evidencia: null }));
R["5_negativo_sin_reserva_no_hay_bloque"] = {
  ok: !sin.includes("cx-reserva") && !sin.includes("Te avisamos"),
};

// (c) la reserva sigue estando en el panel de trámite (no se mudó: se sumó)
const conPanel = S.pintarPanel(modelo({ reserva: RESERVA }));
R["5_el_panel_de_tramite_la_conserva"] = { ok: conPanel.includes("cx-reserva") };

/* ══ #4 · EL TESTIGO END-TO-END: LA PIEZA CON LLAVE DEJA DE ESTAR TRABADA ═════════════
 *
 * No es un fixture: el belt entra por argv y lo derivó el BACKEND REAL
 * (`centro_conexiones._belt_derivado_de_fila`) sobre una fila REAL del registro del usuario.
 * Acá se corre la cadena que decidía su destino: credenciales → contradicción. Si la
 * contradicción `credencial_sin_provider_resoluble` sigue viva, `escrutable_ok` cae, el
 * grupo pasa a ser «escrutinio» —deuda NUESTRA, que no se pinta— y la pieza desaparece del
 * local Y de la aduana a la vez. Ése era el trámite que nadie podía hacer.
 */
const W = await import(join(D, "conectores/widget.js"));
const rutaBelt = process.argv[2];
if (rutaBelt) {
  const { belt, alias, entityId, ficha, medicion, credencialRef } =
    JSON.parse(readFileSync(rutaBelt, "utf8"));
  const conArreglo = K.credencialesQuePide({ servidorBelt: belt, alias });
  const sinBelt = { ...belt };
  delete sinBelt.headers_ref;                    // el mundo de antes: el header opaco solo
  const sinArreglo = K.credencialesQuePide({ servidorBelt: sinBelt, alias });

  // La cadena REAL: `contradicciones` recalcula las credenciales desde el belt, así que la
  // diferencia se hace variando el BELT, no la lista. Vault vacío = la pieza aún no tiene
  // su llave, que es exactamente su estado.
  const contra = (b) => (W.contradicciones({
    ficha, servidorBelt: b, medicion: medicion || {}, vault: new Set(),
    entityId, alias, scopesConcedidos: [], envDeclarado: {}, credencialRef,
  }) || []).map((c) => c.tipo);

  const tiposCon = contra(belt);
  const tiposSin = contra(sinBelt);
  const MENTIRAS = ["credencial_sin_provider_resoluble", "secreto_en_claro_en_el_manifest"];
  R["4_e2e_la_pieza_con_llave_se_destraba"] = {
    ok: !MENTIRAS.some((t) => tiposCon.includes(t)),
    entityId, credenciales: conArreglo.map((c) => `${c.variable}(${c.donde})→${c.provider}`),
    contradicciones: tiposCon,
  };
  R["4_e2e_negativo_sin_el_arreglo_seguia_trabada"] = {
    ok: MENTIRAS.every((t) => tiposSin.includes(t)),
    credenciales: sinArreglo.map((c) => `${c.variable}(${c.donde})`),
    contradicciones: tiposSin,
  };

  /* ¿Y SE DESTRABA DE VERDAD? Las contradicciones son el medio; lo que decide el destino de
   * la pieza es `veredicto.bloqueo`: si sigue siendo NUESTRO, `escrutable_ok` cae, el grupo
   * es «escrutinio» —que no se pinta— y la pieza sigue sin superficie. Este testigo mira el
   * final del camino, no el intermedio. */
  const veredicto = (b) => W.veredictoDe({
    ficha, servidorBelt: b, medicion: medicion || {}, vault: new Set(),
    entityId, alias, scopesConcedidos: [], envDeclarado: {}, credencialRef,
  }) || {};
  const vCon = veredicto(belt);
  const vSin = veredicto(sinBelt);
  R["4_e2e_el_bloqueo_nuestro_desaparece"] = {
    ok: vCon.bloqueo !== "nuestro",
    bloqueo_con_arreglo: vCon.bloqueo, motivo: vCon.motivo,
    bloqueo_sin_arreglo: vSin.bloqueo, motivo_sin: vSin.motivo,
  };
} else {
  R["4_e2e_la_pieza_con_llave_se_destraba"] = { ok: null, motivo: "sin fila real que mirar" };
  R["4_e2e_negativo_sin_el_arreglo_seguia_trabada"] = { ok: null, motivo: "sin fila real" };
}

/* ══ #6 · TRAER ≠ EQUIPAR · la sección no manda puppet_id ═════════════════════════════ */
const fuente = readFileSync(join(D, "conectores/montaje.js"), "utf8");
const cuerpoViaje = (fuente.match(/async function correrViaje[\s\S]*?\n}/) || [""])[0];
R["6_traer_no_equipa_en_ningun_agente"] = {
  ok: !!cuerpoViaje && !/puppetId|puppet_id/.test(cuerpoViaje),
  detalle: cuerpoViaje ? "correrViaje no menciona puppetId" : "no encontré correrViaje",
};

console.log("__JSON__" + JSON.stringify(R));
