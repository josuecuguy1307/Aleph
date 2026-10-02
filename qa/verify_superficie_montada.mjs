#!/usr/bin/env node
/**
 * verify_superficie_montada.mjs — LOS SEIS TESTIGOS CONTRA LA SUPERFICIE, NO CONTRA EL
 * COMPONENTE SUELTO.
 *
 *   node qa/verify_superficie_montada.mjs
 *
 * La diferencia con `verify_widget_unico.mjs` es toda la diferencia: aquella prueba que el
 * MODELO se deriva bien; ésta prueba **el HTML que el usuario ve**. Un modelo correcto que
 * se pinta mal es un bug que el usuario sufre y que ninguna vara del modelo puede ver.
 *
 * Y se corre SIN NAVEGADOR a propósito. `superficie.js` son funciones puras que devuelven
 * strings, así que la vara pinta las 42 piezas reales y busca en la salida. Las varas de la
 * superficie vieja necesitaban levantar Chromium en un puerto fijo, y una vara que necesita
 * un navegador se corre una vez y se abandona — están todas en el árbol, todas verdes de
 * hace semanas, ninguna corriendo.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * LO QUE ESTA VARA HEREDA DE LAS QUE MURIERON CON LAS UIs VIEJAS.
 *
 * Al demoler `conectores.ui.js`, `wizard.js` y `registro.fila.js` murieron sus varas. Sus
 * testigos NO se perdieron: los que seguían siendo ciertos sobre la superficie nueva están
 * acá, marcados «[heredado de …]». Los que no están son los que probaban mecanismos que ya
 * no existen (el modal, el wizard de 4 tipos, la decoración de filas por MutationObserver).
 */
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..");
const D = join(RAIZ, "product/app/design");
const W = await import(join(D, "conectores/widget.js"));
const S = await import(join(D, "conectores/superficie.js"));
const M = await import(join(D, "conectores/montaje.js"));
const Sem = await import(join(D, "cuarto/cuarto.semaforo.js"));

const FALLOS = [];
const ok = (c, t, d = "") => {
  console.log((c ? "  ✅ " : "  ❌ ") + t + (d ? ` · ${d}` : ""));
  if (!c) FALLOS.push(t);
  return c;
};

/* ── las fuentes reales, igual que en producción ─────────────────────────────────── */
const ALIAS = (() => {
  const j = JSON.parse(readFileSync(join(RAIZ, "catalog/connectors/env-alias.json"), "utf8"));
  const out = {};
  for (const [prov, vars] of Object.entries(j.alias || {}))
    for (const v of vars) if (!out[v]) out[v] = prov;
  return out;
})();

const ficha = (n) => {
  try { return JSON.parse(readFileSync(join(RAIZ, `catalog/connectors/onboarding/${n}.json`), "utf8")); }
  catch (_) { return null; }
};

const SERVIDORES = (() => {
  const out = {}; const stack = [join(RAIZ, "catalog")];
  while (stack.length) {
    const dir = stack.pop();
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, e.name);
      if (e.isDirectory()) stack.push(p);
      else if (e.name.endsWith(".mcp.json")) {
        try { for (const [s, c] of Object.entries(JSON.parse(readFileSync(p, "utf8")).mcpServers || {})) out[s] = c; }
        catch (_) { /* ignora */ }
      }
    }
  }
  return out;
})();

/** El modelo tal como lo arma `fuentes.js` en el browser: mismas entradas, mismo camino. */
const modelo = (id, med, extra = {}) => {
  const cx = (med || {}).conexion || {};
  const m = W.derivar({
    entityId: id, ficha: ficha(id), servidorBelt: SERVIDORES[id] || null,
    medicion: med, alias: ALIAS,
    camino: Sem.caminoDe({ estado: cx.estado, causa: cx.causa }),
    ...extra,
  });
  m.nombre = extra.nombre || id;
  m.apagada = !!extra.apagada;
  return m;
};

/** Una pieza REAL de cada forma, elegida por lo que DECLARA y no por su nombre: así el
 *  testigo no se cae el día que esa pieza se arregle o se retire del catálogo. */
function primeraQue(predicado) {
  for (const [id, belt] of Object.entries(SERVIDORES)) {
    if (predicado(belt, ficha(id), id)) return id;
  }
  return null;
}
const _CRED = /(KEY|TOKEN|SECRET|APIKEY)/i;
const PIEZA_LLAVE = primeraQue((b, f) => f && f.auth_method === "personal_token" &&
                                         (f.credential_fields || []).length &&
                                         Object.keys(b.env || {}).some((k) => _CRED.test(k)));
const PIEZA_INSTALAR = primeraQue((b) => b.instalacion && b.instalacion.link);
const PIEZA_KEYLESS = primeraQue((b, f) => !f && !Object.keys(b.env || {}).some((k) => _CRED.test(k)));

const texto = (html) => String(html).replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

console.log("══ VARA DE LA SUPERFICIE MONTADA · los 6 testigos contra el HTML ══\n");
console.log(`   piezas testigo, elegidas por lo que DECLARAN: llave=${PIEZA_LLAVE} · ` +
            `instalar=${PIEZA_INSTALAR} · keyless=${PIEZA_KEYLESS}\n`);

/* ══ 1 · FALTA LA LLAVE → CAMPO INLINE + [Guardar y probar] ══════════════════════════ */
console.log("1 · falta la llave → campo INLINE en la fila, jamás una pantalla nueva");
{
  const m = modelo(PIEZA_LLAVE, { conexion: { estado: "rota", causa: "falta_key", ts: "2026-08-04T09:00:00" },
                                  credencial: { estado: "sin_medir" } });
  const card = S.pintarCard(m);
  const panel = S.pintarPanel(m);

  ok(/data-estado="esperando"/.test(card), "la card dice que espera algo del usuario");
  ok(/Falta tu llave/.test(texto(card)), "y QUÉ espera, con palabras suyas", texto(card).slice(0, 70));
  ok(/<input[^>]+type="password"/.test(panel), "el panel trae el campo, INLINE");
  ok(/name="[^"]+"/.test(panel), "con el nombre que declara la ficha",
     (panel.match(/name="([^"]+)"/) || [])[1]);
  ok(/class="cx-btn cx-guardar"/.test(panel) && /Guardar y probar/.test(texto(panel)),
     "y UN botón para las dos cosas: guardar y probar");
  ok(/cx-link[^>]*href="https:\/\//.test(panel), "con DÓNDE conseguirla, si el catálogo lo declara");
  // [heredado de verify_una_tarjeta_contract] · UNA superficie por pieza, no tres.
  ok(!/role="dialog"|class="modal"|location\.href\s*=\s*"Conectar/.test(panel),
     "y CERO modal, cero navegación: el trámite ocurre donde el usuario está");
}

/* ══ 2 · AL GUARDAR LA LLAVE, `verify` CORRE SOLO ════════════════════════════════════ */
console.log("\n2 · guardar la llave dispara `verify` SOLO — sin [Probar de nuevo]");
{
  // Esto es una SECUENCIA y no se puede ver en el HTML. Se ejercita el verbo de verdad, con
  // los dos de `fuentes.js` sustituidos por espías: es la costura `VERBOS` de `montaje.js`.
  const orden = [];
  const original = { ...M.VERBOS };
  M.VERBOS.guardarLlave = async (prov, secreto) => { orden.push(`guardar:${prov}`); return { guardada: true }; };
  M.VERBOS.medir = async (id) => { orden.push(`medir:${id}`); return true; };
  M.VERBOS.cargar = async () => { orden.push("recargar"); return { modelos: [], vault: {}, leido: true }; };

  const m = modelo(PIEZA_LLAVE, { conexion: { estado: "rota", causa: "falta_key", ts: "2026-08-04T09:00:00" },
                                  credencial: { estado: "sin_medir" } });
  const campo = (m.conocimiento.credenciales[0] || {}).variable || "X_API_KEY";
  // Un DOM mínimo: lo único que `guardar` toca es el panel y sus inputs.
  const input = { name: campo, value: "una-llave-de-prueba" };
  const panelFalso = { querySelectorAll: () => [input] };
  const boton = { closest: () => panelFalso };
  // `montaje` guarda contra su propio ESTADO: se le pone el modelo que va a tocar.
  M.ESTADO.modelos = [m];

  await M.guardar(m.entityId, boton);
  const original_orden = orden.join(" → ");
  ok(orden.some((o) => o.startsWith("guardar:")), "la llave se guarda", original_orden);
  ok(orden.indexOf(orden.find((o) => o.startsWith("medir:"))) >
     orden.indexOf(orden.find((o) => o.startsWith("guardar:"))),
     "y `verify` corre DESPUÉS, solo: nadie tiene que apretar [Probar de nuevo]");
  ok(input.value === "", "el campo se limpia: la llave no queda en el DOM");
  const provider = (orden.find((o) => o.startsWith("guardar:")) || "").slice(8);
  ok(provider === (m.conocimiento.credenciales[0] || {}).provider,
     "y se guarda bajo el PROVIDER que resuelve la variable, no bajo el nombre de la pieza",
     provider);

  Object.assign(M.VERBOS, original);
  M.ESTADO.modelos = [];
}

/* ══ 3 · REQUIERE APP → LINK OFICIAL + [Ya lo instalé · verificar] ═══════════════════ */
console.log("\n3 · requiere app → link oficial declarado, jamás «no encontré cómo instalar»");
{
  const m = modelo(PIEZA_INSTALAR, { conexion: { estado: "rota", causa: "cli_no_instalado",
                                                 ts: "2026-08-04T09:00:00" },
                                     credencial: { estado: "no_aplica" } });
  const panel = S.pintarPanel(m);
  ok(/data-paso="instalar"/.test(panel), "hay un paso de instalación");
  ok(/cx-link[^>]*href="https:\/\//.test(panel), "con LINK OFICIAL, del belt",
     (panel.match(/href="(https:\/\/[^"]+)"/) || [])[1]);
  ok(/class="cx-btn cx-verificar"/.test(panel), "y el botón que cierra el trámite");
  ok(/Ya lo instalé · verificar/.test(texto(panel)),
     "con el rótulo que declara el catálogo, no uno escrito en la superficie");
  ok(/data-estado="esperando"/.test(S.pintarCard(m)), "y la card lo dice desde la lista");
}

/* ══ 4 · EL RESUMEN Y LAS CARDS SON LA MISMA CUENTA ══════════════════════════════════ */
console.log("\n4 · el resumen NO puede diferir de las cards: es la misma lista contada");
{
  // [heredado de verify_connector_entity_ui] · el bug original: el resumen decía «1 conexión
  // activa» encima de una lista llena de ✅ Conectado. Ninguno mentía por su cuenta.
  const modelos = Object.keys(SERVIDORES).slice(0, 30).map((id, i) =>
    modelo(id, { conexion: { estado: i % 3 === 0 ? "viva" : i % 3 === 1 ? "rota" : "sin_sondear",
                             causa: i % 3 === 1 ? "falta_key" : null,
                             tool_usada: "algo", ts: "2026-08-04T09:00:00" },
                 credencial: null }));
  const resumen = S.pintarResumen(modelos);
  const cards = modelos.map((m) => S.pintarCard(m)).join("");
  const delResumen = Number((resumen.match(/data-connected="(\d+)"/) || [])[1]);
  const enCards = (cards.match(/data-estado="conectado"/g) || []).length;
  ok(delResumen === enCards, "el número del resumen == las cards conectadas",
     `${delResumen} vs ${enCards}`);
  const total = Number((resumen.match(/data-total="(\d+)"/) || [])[1]);
  ok(total === modelos.length, "y el total == las filas pintadas", `${total} vs ${modelos.length}`);
  // Y el guard estructural: el resumen sólo puede contar los modelos que recibe.
  const fuente = readFileSync(join(D, "conectores/superficie.js"), "utf8");
  ok(/export function pintarResumen\(modelos\)[\s\S]{0,200}modelos\.filter/.test(fuente),
     "por construcción: `pintarResumen` cuenta la lista, no consulta otra fuente");
}

/* ══ 5 · SIN MEDIR → SIN MEDIR. JAMÁS UN CERO QUE NADIE CONTÓ ═══════════════════════ */
console.log("\n5 · sin medir → «midiendo»; nunca un cero, nunca un rojo inventado");
{
  const m = modelo(PIEZA_KEYLESS, { conexion: { estado: "sin_sondear", ts: "2026-08-04T09:00:00" },
                                    credencial: null });
  const card = S.pintarCard(m);
  const panel = S.pintarPanel(m);
  ok(!/\b0\s*(de|of|tools|herramientas)/i.test(texto(card)),
     "la card no muestra un cero que nadie contó", texto(card).slice(0, 60));
  ok(!/cx-accion/.test(card), "y no ofrece botón: medir es NUESTRO trabajo");
  ok(/data-paso="midiendo"/.test(panel) || !/data-paso="llave"/.test(panel),
     "el panel dice que se está midiendo, sin pedirle nada a nadie");

  // Una pieza SIN FILA no es una pieza rota: es residuo, y se dice.
  const residuo = modelo(PIEZA_KEYLESS, null);
  ok(/residuo/.test(residuo.veredicto.motivo),
     "y una entidad sin fila es residuo, no una conexión caída", residuo.veredicto.motivo);

  // [heredado de verify_linea_estado] · el veredicto llega CON SU FECHA. Un rojo viejo y uno
  // falso son indistinguibles si nadie mira su edad — era el bug de los tres rojos falsos.
  const conFecha = modelo(PIEZA_KEYLESS, { conexion: { estado: "viva", tool_usada: "x",
                                                       ts: "2026-08-04T09:00:00" } });
  ok(/class="cx-cuando"/.test(S.pintarCard(conFecha)),
     "y todo veredicto se pinta con su fecha");
}

/* ══ 6 · CERO CONFESIONES, EN EL HTML QUE SE VE ═════════════════════════════════════ */
console.log("\n6 · cero confesiones y cero jerga en TODO lo que se pinta");
{
  // La ley: el usuario jamás lee «no sé», «no pude», «defecto nuestro» ni jerga interna.
  // Eso vive en el registro y en el [?], que es donde sirve para arreglar.
  const PROHIBIDO =
    /(no s[ée] qu|no pude|no encontr|defecto nuestro|culpa nuestra|servidor MCP|el backend|stdio|traceback|undefined|\[object)/i;
  const sucios = [];
  let n = 0;
  for (const id of Object.keys(SERVIDORES)) {
    for (const est of ["viva", "rota", "sin_sondear"]) {
      const m = modelo(id, { conexion: { estado: est, causa: "falta_key", tool_usada: "x",
                                         ts: "2026-08-04T09:00:00" },
                             credencial: { estado: "sin_medir" } });
      for (const html of [S.pintarCard(m), S.pintarPanel(m)]) {
        n++;
        const t = texto(html);
        if (PROHIBIDO.test(t)) sucios.push(`${id}/${est}: ${t.slice(0, 80)}`);
      }
    }
  }
  ok(sucios.length === 0, `cero confesiones en ${n} superficies pintadas`,
     sucios.slice(0, 2).join(" | "));

  // Y LA CONTRACARA: la jerga NO desaparece, se muda al [?]. Si desapareciera del todo, el
  // escrutinio se perdería — y la ley de fondo exige poder auditar cada verde.
  const m = modelo(PIEZA_KEYLESS, { conexion: { estado: "viva", tool_usada: "una_tool",
                                                ts: "2026-08-04T09:00:00" } });
  const det = texto(S.pintarDetalle(m));
  ok(/una_tool/.test(det), "el [?] SÍ dice con qué tool se midió", det.slice(0, 80));
  ok(/deriva de|derived from/.test(det), "y de dónde salió cada cosa");
}

/* ══ 6b · LA DEFINICIÓN DE «CONECTADO» (sellada) ═════════════════════════════════════ */
console.log("\n6b · ✅ se GANA: pendiente-del-usuario DOMINA sobre canal-ok");
{
  // ⚠️ EL CASO ÍNDICE, y por qué no es una sutileza. Una pieza cuyo índice local responde
  // SIN credencial se mide con esa tool: el verificador escribe `conexion: viva` y la card
  // decía ✅ sobre algo que no podía hacer una sola llamada real. Las dos mitades eran
  // ciertas por separado —el canal vivía, la llave faltaba—; lo falso era el verde.
  //
  // La regla: ✅ Conectado = usable END-TO-END en la Sala YA, con CERO pendientes del
  // usuario. El canal que arranca y habla MCP es detalle del [?], jamás el estado.
  const m = modelo(PIEZA_LLAVE, { conexion: { estado: "viva", causa: null,
                                              tool_usada: "una_que_no_pide_llave",
                                              ts: "2026-08-04T09:00:00" },
                                  credencial: { estado: "sin_medir" } });
  ok(m.veredicto.estado === "esperando" && m.veredicto.bloqueo === "usuario",
     "canal VIVO + llave que falta → 🟡, no ✅", m.veredicto.motivo);
  const card = S.pintarCard(m);
  ok(/data-estado="esperando"/.test(card) && /Falta tu llave/.test(texto(card)),
     "y la card muestra EL PENDIENTE como estado visible", texto(card).slice(0, 60));
  ok(!/✅/.test(card), "cero verde sobre una pieza que no se puede usar todavía");

  // Y la contracara: sin pendientes, el verde se gana.
  const sano = modelo(PIEZA_KEYLESS, { conexion: { estado: "viva", tool_usada: "x",
                                                   ts: "2026-08-04T09:00:00" } });
  ok(sano.veredicto.estado === "conectado" && /✅/.test(S.pintarCard(sano)),
     "sin nada pendiente, el verde SE GANA", sano.veredicto.motivo);
}

/* ══ 6c · EL ESTADO 🔴 · un solo botón, cero causas técnicas ═════════════════════════ */
console.log("\n6c · 🔴 = «No disponible por ahora» + [Reintentar conexión], nada más");
{
  // ⚠️ EL TESTIGO CAMBIÓ DE SUJETO, y el cambio ES la ley nueva. Antes usaba un residuo —una
  // entidad sin fila—, pero con la ley del catálogo local un residuo YA NO ES DEL LOCAL: se
  // va a la aduana, y ahí [Reintentar] sería exactamente el teatro que el acta prohíbe.
  //
  // El 🔴 del local es otra cosa y es la que importa: una pieza COMPLETA —instalada, con su
  // llave— que hoy no contesta. Ésa sí tiene un reintento que puede cambiar el resultado.
  const m = W.derivar({
    entityId: "acme", alias: ALIAS, vault: ["acme"],
    ficha: { auth_method: "personal_token", credential_fields: [{ id: "key" }] },
    servidorBelt: { command: "python3", env: { ACME_API_KEY: "${ACME_API_KEY}" } },
    medicion: { conexion: { estado: "rota", causa: "sin_respuesta", ts: "2026-08-04T09:00:00" },
                credencial: { estado: "verde", tool_prueba: "x" } },
    clasificacion: { clase: "PERMANENTE", desempate: "murio" },
    camino: Sem.caminoDe({ estado: "rota", causa: "sin_respuesta" }) });
  m.nombre = "acme";
  ok(m.pertenencia.local === true, "es una pieza DEL LOCAL que hoy falla", m.pertenencia.fuente);
  const card = S.pintarCard(m);
  ok(/data-estado="bloqueado"/.test(card), "la card está en rojo");
  ok(/No disponible por ahora/.test(texto(card)),
     "y dice exactamente eso, sin la causa técnica", texto(card).slice(0, 70));

  const botones = (card.match(/<button/g) || []).length;
  ok(botones === 2, "DOS elementos clickeables y no más: el botón y el [?]", String(botones));
  ok(/class="cx-btn cx-reintentar"/.test(card) && /Reintentar conexión/.test(texto(card)),
     "y el único botón es [Reintentar conexión]");
  // CERO MENÚ: nada de [Ver error] / [Instalarlo] / [Ver planes] sobre un rojo.
  ok(!/Ver error|Instalarlo|Ver planes|Actualizarlo|Dar permisos/.test(texto(card)),
     "cero menú de causas: en rojo no se elige, se reintenta");
  // CERO JERGA: la causa vive en el [?], no en la card.
  ok(!/sin_respuesta|arranque|placeholder|entity|belt/i.test(texto(card)),
     "cero causa técnica visible", texto(card));
  ok(/sin_respuesta/.test(texto(S.pintarDetalle(m))), "…que SÍ está entera en el [?]");

  // El botón tiene que estar cableado a un verbo que relance el ciclo COMPLETO —no a
  // `medir`, que produce el veredicto del motor y no reescribe las dos columnas que esta
  // superficie lee. Un botón cableado al verbo equivocado repinta el mismo estado.
  const fuentes = readFileSync(join(D, "conectores/fuentes.js"), "utf8");
  ok(/reintentarConexion[\s\S]{0,400}\/reintentar/.test(fuentes),
     "y el verbo pega contra `/v1/conexiones/{id}/reintentar` (verificar_uno)");
}

/* ══ 6d · EL ORDEN DE LA LISTA · grid fijo y fecha siempre ══════════════════════════ */
console.log("\n6d · la lista es un GRID FIJO y toda fila lleva su fecha");
{
  const casos = [
    ["verde",  modelo(PIEZA_KEYLESS, { conexion: { estado: "viva", tool_usada: "x", ts: "2026-08-04T09:00:00" } })],
    ["ambar",  modelo(PIEZA_LLAVE,   { conexion: { estado: "viva", tool_usada: "x", ts: "2026-08-04T09:00:00" },
                                       credencial: { estado: "sin_medir" } })],
    ["rojo",   modelo(PIEZA_KEYLESS, null)],
  ];
  // LAS SEIS CELDAS, SIEMPRE. Si una fila omite una, su vecina se corre y la lista se lee
  // como una escalera — que es exactamente lo que se vio en pantalla.
  for (const [nombre, m] of casos) {
    const card = S.pintarCard(m);
    const celdas = ["cx-face", "cx-nombre", "cx-estado", "cx-cuando", "cx-actions", "cx-detalle"];
    const faltan = celdas.filter((c) => !new RegExp(`class="[^"]*${c}`).test(card));
    ok(faltan.length === 0, `${nombre}: emite las seis celdas del grid`, faltan.join(", "));
  }
  // FECHA SIEMPRE, incluso sin medición: un veredicto sin su cuándo es afirmar de memoria.
  for (const [nombre, m] of casos) {
    const card = S.pintarCard(m);
    const celda = (card.match(/class="cx-cuando">([^<]*)</) || [])[1] || "";
    ok(celda.trim().length > 0, `${nombre}: la celda de fecha nunca queda vacía`, `«${celda}»`);
  }
  const sinMedir = S.pintarCard(modelo(PIEZA_KEYLESS, null));
  ok(/class="cx-cuando">sin medir</.test(sinMedir),
     "y sin medición dice «sin medir» — que ES el cuándo: nunca");

  // EL ANCHO LO FIJA EL CSS, no el contenido. Columnas `auto` = cada fila negocia su ancho
  // con su texto, y los estados dejan de arrancar en la misma x.
  const html = readFileSync(join(D, "Conectores.dc.html"), "utf8");
  const cols = (html.match(/\.cx-card\{[^}]*grid-template-columns:([^;]+);/) || [])[1] || "";
  ok(/\d+px/.test(cols) && !/\bauto\b/.test(cols),
     "las columnas de estado/fecha/acción son FIJAS, no `auto`", cols.trim());
  ok(/\.cx-card\{[^}]*min-height:\s*\d+px/.test(html),
     "y la fila cerrada tiene alto uniforme (`min-height`, para que la expandida crezca)");
}

/* ══ 6e · LA LEY DEL CATÁLOGO LOCAL + EL PASO 2.5 ═══════════════════════════════════ */
console.log("\n6e · el local sólo tiene COMPLETAS; lo previo vive en la aduana");
{
  // Piezas sintéticas: lo que se congela es la LEY, no qué está roto hoy.
  const belt = { command: "python3", env: { ACME_API_KEY: "${ACME_API_KEY}" } };
  const fichaLlave = { auth_method: "personal_token",
                       credential_fields: [{ id: "key", label: "Tu llave" }],
                       deep_link: "https://example.com/keys" };
  const beltApp = { command: "python3",
                    instalacion: { que: "El programa", link: "https://example.com/dl",
                                   rotulo: "Ya lo instalé · verificar" } };
  const viva = { conexion: { estado: "viva", tool_usada: "x", ts: "2026-08-04T09:00:00" } };
  const arma = (extra) => W.derivar({ entityId: "acme", alias: ALIAS,
    camino: Sem.caminoDe({ estado: "viva" }), ...extra });

  //: El registro REAL siempre trae su columna de credencial. Sin ella, «el belt pide y el
  //: registro no dice nada» es una contradicción legítima — y el fixture estaría probando
  //: otra cosa que la que dice probar.
  const sinLlave = arma({ ficha: fichaLlave, servidorBelt: belt, vault: [],
    medicion: { conexion: viva.conexion, credencial: { estado: "sin_medir" } } });
  const conLlave = arma({ ficha: fichaLlave, servidorBelt: belt, vault: ["acme"],
    medicion: { conexion: viva.conexion,
                credencial: { estado: "verde", tool_prueba: "x" } } });
  const sinApp = arma({ servidorBelt: beltApp, vault: [],
    medicion: { conexion: { estado: "sin_sondear", ts: "2026-08-04T09:00:00" } } });

  ok(sinLlave.pertenencia.local === false && conLlave.pertenencia.local === true,
     "sin la llave NO es del local; con la llave y verde, SÍ",
     `${sinLlave.pertenencia.motivo} → ${conLlave.pertenencia.fuente}`);
  ok(sinApp.pertenencia.local === false && sinApp.pertenencia.faltan.includes("instalar"),
     "sin el programa tampoco es del local", sinApp.pertenencia.motivo);

  // GUARD · «falta llave» y «falta instalar» NO EXISTEN en la vista local.
  const localHTML = [conLlave].map((m) => S.pintarCard(m)).join("");
  ok(!/Falta tu llave|Falta instalarlo/.test(texto(localHTML)),
     "el render del local no contiene «falta llave» ni «falta instalar»");

  // GUARD · ningún [Reintentar] sobre una pieza no-completa. Es teatro: reintentar no
  // consigue una llave ni instala un programa.
  for (const [nombre, m] of [["sin llave", sinLlave], ["sin app", sinApp]]) {
    ok(!/cx-reintentar/.test(S.pintarCard(m)),
       `${nombre}: cero [Reintentar] sobre una pieza que no está completa`);
  }

  // GUARD · la aduana la agrupa por TIPO de trámite, con SU camino abierto.
  const aduana = S.pintarAduana([sinLlave, sinApp]);
  ok(/data-grupo="llave"/.test(aduana) && /data-grupo="instalar"/.test(aduana),
     "la aduana agrupa por tipo de trámite (Llave · Descarga)");
  ok(/<input[^>]+type="password"/.test(aduana) && /cx-guardar/.test(aduana),
     "el campo de llave inline + [Guardar y probar] está EN la aduana — el mismo ladrillo");
  ok(/cx-verificar/.test(aduana) && /example\.com\/dl/.test(aduana),
     "y el link de instalación con su botón, también");

  // GUARD · una pieza que completa TODO aparece en el local sin acción manual.
  ok(conLlave.pertenencia.local === true && !/data-lista="aduana"/.test(S.pintarCard(conLlave)),
     "al completarse, la pieza es del local sola: no hay botón «mover»");

  // GUARD · un bloqueo NUESTRO va a la aduana con su razón y SIN botón de teatro.
  const contradice = arma({ ficha: { auth_method: "oauth" },
                            servidorBelt: { command: "python3" }, medicion: viva, vault: [] });
  ok(contradice.pertenencia.faltan.includes("escrutinio"),
     "una contradicción ficha-vs-belt es bloqueo NUESTRO", contradice.pertenencia.motivo);
  // ⚠️ EL TESTIGO SE DIO VUELTA POR ORDEN DE PERSONA USUARIA (2026-08-04). Antes congelaba que la fila
  // de un bloqueo nuestro se mostrara con su razón y sin botón. Ahora congela que **no se
  // muestre en absoluto**: decirle al usuario «esto es deuda nuestra» le entrega un problema
  // que no contrajo y sobre el que no puede hacer nada. Una fila que sólo se puede mirar no
  // es información, es una lápida.
  ok(!/data-grupo="escrutinio"/.test(S.pintarAduana([contradice])),
     "y NO se pinta en la aduana: la deuda nuestra no se le muestra a nadie");
  ok(S.pintarAduana([contradice]).includes("cx-aduana-vacia"),
     "una aduana que sólo tiene deuda nuestra se ve VACÍA para el usuario");
}

/* ══ 6f · §7 · LA PERTENENCIA CADUCA · anti-yo-yo ═══════════════════════════════════ */
console.log("\n6f · §7 · verde viejo no existe, y lo que se rompe NO sale del local");
{
  const beltApp = { command: "python3",
                    instalacion: { que: "El programa", link: "https://example.com/dl" } };
  const rota = { conexion: { estado: "rota", causa: "cli_no_instalado",
                             ts: "2026-08-04T09:00:00" } };
  const arma = (extra) => W.derivar({ entityId: "acme", servidorBelt: beltApp, alias: ALIAS,
    camino: Sem.caminoDe({ estado: "rota", causa: "cli_no_instalado" }), ...extra });

  // El caso del acta: binario borrado de una pieza que ANDABA.
  const regres = arma({ medicion: rota, vault: [], estuvoCompleta: true });
  const nunca = arma({ medicion: rota, vault: [], estuvoCompleta: false });

  ok(regres.pertenencia.local === true && regres.pertenencia.regresion === true,
     "una pieza que ANDUVO y perdió su programa SIGUE en el local", regres.pertenencia.fuente);
  ok(nunca.pertenencia.local === false,
     "y una que nunca estuvo completa se queda en la aduana: no es regresión, es onboarding");

  const card = S.pintarCard(regres);
  ok(/Ya no está instalado/.test(texto(card)),
     "la card dice la causa operativa con nombre", texto(card).slice(0, 70));
  ok(/Reinstalar/.test(texto(card)) && !/cx-reintentar/.test(card),
     "con [Reinstalar] y JAMÁS [Reintentar] a secas: reintentar no instala nada");
  ok(/cx-panel-host/.test(card), "y su camino se despliega INLINE, el mismo ladrillo");

  // GUARD · una llave que dejó de servir → [Rotar llave], y tampoco sale del local.
  const revocada = W.derivar({ entityId: "acme", alias: ALIAS, vault: ["acme"],
    ficha: { auth_method: "personal_token", credential_fields: [{ id: "key" }] },
    servidorBelt: { command: "python3", env: { ACME_API_KEY: "${ACME_API_KEY}" } },
    medicion: { conexion: { estado: "viva", tool_usada: "x", ts: "2026-08-04T09:00:00" },
                credencial: { estado: "rechazada", tool_prueba: "x" } },
    camino: Sem.caminoDe({ estado: "viva" }) });
  ok(revocada.pertenencia.local === true && revocada.pertenencia.rotar === true,
     "la llave está aunque no sirva: la pieza NO vuelve a la aduana");
  ok(/Rotar llave/.test(texto(S.pintarCard(revocada))), "y su botón es [Rotar llave]");

  // GUARD · una medición RANCIA no pinta verde sin re-medir, y además DISPARA la medición.
  const F = await import(join(D, "conectores/fuentes.js"));
  const ranciaM = W.derivar({ entityId: "acme", alias: ALIAS, vault: [],
    servidorBelt: { command: "python3" },
    medicion: { conexion: { estado: "viva", tool_usada: "x", ts: "2026-08-04T09:00:00" } },
    insumos: [{ que: "llave:acme", ts: "2026-08-04T14:51:00" }],
    camino: null });
  ok(ranciaM.veredicto.rancia === true && !/verify verde/.test(ranciaM.veredicto.motivo),
     "un insumo posterior a la medición la vuelve rancia", ranciaM.veredicto.motivo);
  ok(F.hayQueMedir(ranciaM) === true,
     "y la rancia DISPARA la medición: es un gatillo, no una etiqueta");

  // GUARD · el barrido del arranque es BARATO. La mitad cara (la prueba doble) no corre.
  const verificador = readFileSync(
    join(RAIZ, "product/backend/app/phase1/conexiones_verificador.py"), "utf8");
  ok(/solo_conexion: bool = False/.test(verificador) &&
     /if solo_conexion:\s*\n\s*return fila/.test(verificador),
     "`verificar_uno` tiene una mitad barata que se saltea el segundo spawn");
  const centro = readFileSync(
    join(RAIZ, "product/backend/app/phase1/centro_conexiones.py"), "utf8");
  ok(/def re_verificar_local[\s\S]{0,3000}solo_conexion: bool = True/.test(centro),
     "y el barrido del local la usa por default");
  ok(/ThreadPoolExecutor[\s\S]{0,400}BARRIDO_PARALELO/.test(centro),
     "en paralelo acotado: el arranque no puede tardar minutos por 42 piezas");
  const main = readFileSync(join(RAIZ, "product/backend/app/main.py"), "utf8");
  ok(/barrido-local/.test(main) && /re_verificar_local/.test(main),
     "y el sidecar lo dispara al arrancar, en un hilo (el boot no espera)");
}

/* ══ 6g · A · ACCIONES OPERATIVAS EN LAS COMPLETAS (acta §3) ════════════════════════ */
console.log("\n6g · ninguna pieza completa sin acción operativa; jamás [Reintentar] sobre una sana");
{
  const conCred = { auth_method: "personal_token", credential_fields: [{ id: "key" }] };
  const belt = { command: "python3", env: { ACME_API_KEY: "${ACME_API_KEY}" } };
  const arma = (med, extra = {}) => W.derivar({ entityId: "acme", alias: ALIAS,
    vault: ["acme"], ficha: conCred, servidorBelt: belt, medicion: med,
    camino: Sem.caminoDe({ estado: (med.conexion || {}).estado,
                           causa: (med.conexion || {}).causa }), ...extra });

  const sana = arma({ conexion: { estado: "viva", tool_usada: "x", ts: "2026-08-04T09:00:00" },
                      credencial: { estado: "verde", tool_prueba: "x" } });
  const transit = arma({ conexion: { estado: "rota", causa: "timeout", ts: "2026-08-04T09:00:00" },
                         credencial: { estado: "verde", tool_prueba: "x" } },
                       { clasificacion: { clase: "temporal" } });
  const perm = arma({ conexion: { estado: "rota", causa: "cli_no_instalado",
                                  ts: "2026-08-04T09:00:00" },
                      credencial: { estado: "verde", tool_prueba: "x" } },
                    { clasificacion: { clase: "permanente" } });

  const acc = (m) => texto(S.pintarAccionesOperativas(m));
  ok(/Desconectar/.test(acc(sana)), "una pieza SANA tiene [Desconectar] — siempre alcanzable");
  ok(/Rotar llave/.test(acc(sana)),
     "y [Rotar llave]: rotar es voluntario, nadie espera a que una llave falle");
  ok(!/Reintentar/.test(acc(sana)),
     "y JAMÁS [Reintentar] sobre una sana: no resuelve nada y sugiere que algo anda mal");
  ok(/Reintentar/.test(acc(transit)),
     "un fallo TRANSITORIO sí ofrece [Reintentar]: ahí el reintento puede cambiar el resultado");
  ok(!/Reintentar/.test(acc(perm)),
     "y uno PERMANENTE no: devolvería el mismo rojo");
  const apagada = arma({ conexion: { estado: "viva", tool_usada: "x", ts: "2026-08-04T09:00:00" },
                         credencial: { estado: "verde", tool_prueba: "x" } });
  apagada.apagada = true;
  ok(/Reconectar/.test(acc(apagada)) && !/Desconectar/.test(acc(apagada)),
     "y una apagada ofrece [Reconectar], no [Desconectar]");
  // NINGUNA COMPLETA SIN ACCIÓN ALCANZABLE — el hueco que esto cerró: una verde sólo tenía [?].
  for (const [n, m] of [["sana", sana], ["transitoria", transit], ["permanente", perm]])
    ok(/<button/.test(S.pintarAccionesOperativas(m)), `${n}: tiene acción operativa alcanzable`);
  ok(/cx-operativas/.test(S.pintarDetalle(sana)),
     "y las acciones viven en el DETALLE, que toda card puede abrir (acta: «siempre disponible en el detalle»)");
}

/* ══ 6g-bis · ALCANZABILIDAD · el botón que nadie puede apretar no existe ═══════════ */
console.log("\n6g-bis · toda acción operativa tiene que ser ALCANZABLE desde la card");
{
  // ⚠️ EL GUARD QUE FALTABA, Y EL BUG QUE SE ESCAPÓ POR NO TENERLO.
  //
  // [Desconectar] estaba escrito, viajaba en el bundle, y en la app instalada NO APARECÍA.
  // La causa: las acciones viven en `pintarPanel`, y el panel se abría sólo desde el botón
  // de repair o desde un paso pendiente. Una pieza SANA no tiene ninguno de los dos
  // —`caminoDe` devuelve null para una conexión viva, y no hay trámite— así que su card
  // quedaba con sólo el [?], que abre la evidencia técnica. Ningún click llegaba.
  //
  // La vara vieja probaba `pintarAccionesOperativas` y `pintarPanel` EN AISLAMIENTO y por
  // eso no lo vio: los dos devolvían el HTML correcto. Lo que no existía era el CAMINO.
  //
  // Esto lo ata: se leen del MONTAJE los atributos que de verdad abren el panel, y se exige
  // que la card emita al menos uno. Si mañana alguien renombra el handler, esto se cae.
  // QUÉ ATRIBUTO ABRE LO QUE CONTIENE LAS ACCIONES. Se lee del MONTAJE, no se supone: si
  // mañana alguien renombra el handler, esto se cae en vez de pasar por inercia.
  const montaje = readFileSync(join(D, "conectores/montaje.js"), "utf8");
  const abren = Array.from(montaje.matchAll(
    /if \(d\.(\w+)(?: && d\.entity)?\)[^\n]*desplegar\(d\.\w+, "detalle"\)/g)).map((m) => m[1]);
  ok(abren.length > 0, "el montaje declara qué control abre el detalle",
     abren.map((a) => "data-" + a).join(", "));

  const conCred = { auth_method: "personal_token", credential_fields: [{ id: "key" }] };
  const belt = { command: "python3", env: { ACME_API_KEY: "${ACME_API_KEY}" } };
  const casos = {
    sana:        [{ conexion: { estado: "viva", tool_usada: "x", ts: "2026-08-04T09:00:00" },
                    credencial: { estado: "verde", tool_prueba: "x" } }, {}],
    keyless:     [{ conexion: { estado: "viva", tool_usada: "x", ts: "2026-08-04T09:00:00" } },
                  { ficha: null, servidorBelt: { command: "uvx", args: ["x"] }, vault: [] }],
    transitoria: [{ conexion: { estado: "rota", causa: "timeout", ts: "2026-08-04T09:00:00" },
                    credencial: { estado: "verde", tool_prueba: "x" } },
                  { clasificacion: { clase: "temporal" } }],
    midiendo:    [{ conexion: { estado: "sin_sondear", ts: "2026-08-04T09:00:00" },
                    credencial: { estado: "verde", tool_prueba: "x" } }, {}],
  };
  for (const [nombre, [med, extra]] of Object.entries(casos)) {
    const m = W.derivar({ entityId: "acme", alias: ALIAS, vault: ["acme"], ficha: conCred,
      servidorBelt: belt, medicion: med,
      camino: Sem.caminoDe({ estado: (med.conexion || {}).estado,
                             causa: (med.conexion || {}).causa }), ...extra });
    m.nombre = "acme";
    if (!m.pertenencia.local) continue;      // las de la aduana tienen su propio camino
    const card = S.pintarCard(m);
    const puerta = abren.find((a) => card.includes("data-" + a + "="));
    ok(!!puerta, nombre + ": su card tiene el control que abre sus acciones",
       puerta ? "data-" + puerta
              : "SOLO: " + [...card.matchAll(/data-(\w+)=/g)].map((x) => x[1]).join(", "));
    // Y LO QUE SE ABRE TIENE QUE TRAERLAS: una puerta a un cuarto vacío tampoco sirve, y es
    // la mitad que la vara vieja no miraba.
    const abierto = texto(S.pintarDetalle(m));
    ok(/Desconectar|Reconectar/.test(abierto),
       nombre + ": y lo que abre trae sus acciones operativas", abierto.slice(0, 48));
  }
}


/* ══ 6h · B · EL CHECKLIST VIVO DE RECONEXIÓN ═══════════════════════════════════════ */
console.log("\n6h · los verbos completándose en vivo, no un spinner mudo");
{
  // LOS VERBOS SON LOS REALES del sistema (`spec → handshake → tools → credencial`), no una
  // secuencia inventada para la pantalla.
  const centro = readFileSync(
    join(RAIZ, "product/backend/app/phase1/centro_conexiones.py"), "utf8");
  const ids = (centro.match(/REQUISITOS_MCP = \[([\s\S]*?)\n\]/) || [])[1] || "";
  const verbos = Array.from(ids.matchAll(/\("(\w+)",/g)).map((m) => m[1]);
  ok(verbos.join(" → ") === "spec → handshake → tools → credencial",
     "la secuencia sale del backend, no de la superficie", verbos.join(" → "));

  const paso = (id, titulo, estado, causa) => ({ id, titulo, estado, causa });
  // FALLA EN EL VERBO 2 → exactamente 1 check, la causa en el 2, y los siguientes SIN correr.
  const html = S.pintarChecklist({ verbos: [
    paso("spec", "La pieza declara cómo conectarse", "hecho"),
    paso("handshake", "El servidor MCP responde el saludo", "roto", "timeout"),
    paso("tools", "Sirve herramientas de verdad", "pendiente"),
    paso("credencial", "Tu credencial sirve de verdad", "pendiente"),
  ] });
  const checks = (html.match(/data-estado="hecho"/g) || []).length;
  const rotos = (html.match(/data-estado="roto"/g) || []).length;
  ok(checks === 1, "falla en el verbo 2 → exactamente 1 check", String(checks));
  ok(rotos === 1 && /El servidor tardó demasiado/.test(texto(html)),
     "la causa TIPADA va junto al verbo culpable", texto(html).slice(-60));
  ok(!/data-estado="hecho"[\s\S]*data-estado="roto"[\s\S]*data-estado="hecho"/.test(html),
     "jamás un verde después del rojo: lo que no corrió no se pinta como si hubiera corrido");
  ok((html.match(/data-estado="pendiente"/g) || []).length === 2,
     "y los dos siguientes quedan sin correr, que es la verdad");

  // El reductor del montaje fuerza esa regla aunque el backend emita resultados de más.
  const montaje = readFileSync(join(D, "conectores/montaje.js"), "utf8");
  ok(/yaRoto[\s\S]{0,120}"pendiente"/.test(montaje),
     "el reductor degrada a «no corrió» todo lo que venga después de un roto");
  ok(/checklistEnVivo/.test(montaje) && /fila\.inicio/.test(montaje),
     "y se alimenta del SSE que ya existía: cero telemetría nueva");
}

/* ══ 6i · LA DEUDA NUESTRA NO SE MUESTRA (orden 2026-08-04) ═════════════════════════ */
console.log("\n6i · ninguna pieza `pendiente_ingesta` llega a una superficie de usuario");
{
  // EL GUARD DURO ES EL FILTRO EN LA FUENTE, no un `if` de render: filtrar al pintar deja la
  // pieza al alcance de cualquier vista nueva que se olvide del `if`; filtrarla en la única
  // fuente la hace invisible para TODAS, incluidas las que no existen todavía.
  const centro = readFileSync(
    join(RAIZ, "product/backend/app/phase1/centro_conexiones.py"), "utf8");
  ok(/estado_interno"\) == "pendiente_ingesta":\s*\n\s*continue/.test(centro),
     "el endpoint de las fuentes NO manda las retenidas");

  // Y la sección que las mostraba está muerta, no escondida.
  const sup = readFileSync(join(D, "conectores/superficie.js"), "utf8");
  const cuerpo = sup.split("\n").filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l)).join("\n");
  ok(!/Nos toca a nosotros|On us/.test(cuerpo),
     "la sección «Nos toca a nosotros» no existe en el render");
  ok(!/escrutinio/.test(cuerpo.split("export function pintarAduana")[1] || ""),
     "y la aduana ya no tiene grupo para la deuda nuestra");

  // El censo SÍ las ve: es nuestra herramienta, y una deuda que nadie mira no se paga.
  const censo = readFileSync(join(RAIZ, "qa/censo_widget.mjs"), "utf8");
  ok(/pendiente_ingesta/.test(censo) && /bloqueo_interno/.test(censo),
     "el censo las reporta con su bloqueo nombrado");
}

/* ══ 7 · LOS GUARDS ESTRUCTURALES ════════════════════════════════════════════════════ */
console.log("\n7 · los guards que hacen que esto escale a 17.000");
{
  const nombres = Object.keys(SERVIDORES).filter((s) => s.length > 4);
  for (const archivo of ["conectores/superficie.js", "conectores/montaje.js",
                         "conectores/fuentes.js"]) {
    const src = readFileSync(join(D, archivo), "utf8");
    const cuerpo = src.split("\n").filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l)).join("\n");
    const hard = nombres.filter((s) => new RegExp(`["'\`]${s}["'\`]`).test(cuerpo));
    ok(hard.length === 0, `${archivo}: cero nombres de conector`,
       hard.length ? `HARDCODEADOS: ${hard.join(", ")}` : `(probado contra ${nombres.length})`);
  }

  // MONTAJE NO ESCRIBE TEXTO. Si un rótulo se escribe ahí, hay dos lugares que dicen lo
  // mismo y un día dirán cosas distintas.
  const montaje = readFileSync(join(D, "conectores/montaje.js"), "utf8")
    .split("\n").filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l)).join("\n");
  const textos = (montaje.match(/["'][A-ZÁÉÍÓÚÑ][a-záéíóúñ]{3,}[^"']*["']/g) || [])
    .filter((s) => !/^["'](Content-Type|Bearer|POST|DELETE|Accept|Authorization)/.test(s));
  ok(textos.length === 0, "montaje.js no escribe un solo texto de usuario",
     textos.slice(0, 3).join(" · "));

  // LAS UIs VIEJAS ESTÁN MUERTAS, no comentadas ni renombradas.
  const { existsSync } = await import("node:fs");
  const muertas = ["conectores/conectores.ui.js", "diagnostico/wizard.js",
                   "conectores/registro.fila.js"];
  const vivas = muertas.filter((f) => existsSync(join(D, f)));
  ok(vivas.length === 0, "las tres UIs viejas ya no existen en el árbol",
     vivas.length ? `TODAVÍA VIVAS: ${vivas.join(", ")}` : "");

  // Y NADIE LAS IMPORTA. Un import a un archivo borrado es una pantalla en blanco.
  // La prosa PUEDE nombrarlas —el comentario de la pantalla cuenta qué reemplazó— pero
  // ninguna REFERENCIA puede sobrevivir: un import a un archivo borrado es una pantalla en
  // blanco, y un `src` a uno borrado es un 404 mudo.
  const html = readFileSync(join(D, "Conectores.dc.html"), "utf8");
  const refs = (html.match(/(?:src|href)="[^"]*"|from\s+"[^"]*"/g) || [])
    .filter((r) => /conectores\.ui\.js|wizard\.js|registro\.fila\.js/.test(r));
  ok(refs.length === 0, "y la pantalla no las carga", refs.join(" · "));
  ok(/conectores\/montaje\.js/.test(html), "monta el adaptador");
}

console.log("\n" + (FALLOS.length === 0
  ? "══ ✅ LA SUPERFICIE MONTADA CUMPLE · los 6 testigos, contra el HTML que se ve ══"
  : `══ ❌ ${FALLOS.length} FALLO(S): ${JSON.stringify(FALLOS)} ══`));
process.exit(FALLOS.length ? 1 : 0);
