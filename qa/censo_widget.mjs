#!/usr/bin/env node
/**
 * censo_widget.mjs — EL WIDGET ÚNICO CONTRA TODAS LAS PIEZAS REALES.
 *
 *   node qa/censo_widget.mjs
 *
 * La prueba de fuego: si el widget deriva bien las 42 formas que hay hoy en el registro,
 * está listo para las 17.000 del catálogo público. Por eso el censo no es un test que
 * pasa o falla — es una TABLA que nombra, pieza por pieza, dónde se queda y de quién es la
 * razón.
 *
 * LA REGLA DEL VEREDICTO (sellada): «se queda esperando» es VÁLIDO sólo si lo que falta es
 * territorio del usuario —su llave, su app, su consentimiento—. Cualquier pieza trabada por
 * razón NUESTRA —ficha sin declarar, prosa sin link, estado no derivable, verbo que no
 * corrió— NO es un estado: es un bug, y sale con nombre.
 *
 * Y la ley de fondo que lo enmarca: **estar en el catálogo local es haber pasado por los 12
 * verbos.** Una pieza que no se puede escrutar completa no se muestra como si estuviera
 * bien; se nombra acá.
 */
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..");
const W = await import(join(RAIZ, "product/app/design/conectores/widget.js"));
const Sem = await import(join(RAIZ, "product/app/design/cuarto/cuarto.semaforo.js"));

const DB = join(process.env.HOME, "Library/Application Support/Aleph/aleph.db");

/** EL VAULT · qué llaves entregó ya el usuario. Segunda fuente de la verdad de una
 *  credencial, y la que faltaba: sin ella el censo pedía llaves ya pegadas. */
function vaultDelUsuario() {
  const user = execFileSync("sqlite3", [DB,
    "SELECT user_id FROM conexiones LIMIT 1;"], { encoding: "utf8" }).trim();
  const out = execFileSync("sqlite3", [DB,
    `SELECT provider FROM keys WHERE user_id='${user}';`], { encoding: "utf8" });
  return new Set(out.trim().split("\n").filter(Boolean));
}
const VAULT = vaultDelUsuario();

// ── los datos reales ────────────────────────────────────────────────────────────────
function filasDelRegistro() {
  const sql = `SELECT entity_id, nombre_visible,
      COALESCE(json_extract(conexion,'$.estado'),''),
      COALESCE(json_extract(conexion,'$.causa'),''),
      COALESCE(json_extract(conexion,'$.tool_usada'),''),
      COALESCE(json_extract(conexion,'$.ts'),''),
      REPLACE(REPLACE(COALESCE(json_extract(conexion,'$.evidencia'),''),char(10),' '),char(13),' '),
      COALESCE(json_extract(credencial,'$.estado'),''),
      COALESCE(credencial_ref,''),
      COALESCE(json_extract(credencial,'$.tool_prueba'),''),
      COALESCE(env_template,''),
      COALESCE(env_publico,''),
      COALESCE(ultimo_veredicto,''),
      COALESCE(estado_interno,''),
      COALESCE(bloqueo_interno,'')
    FROM conexiones ORDER BY entity_id;`;
  const out = execFileSync("sqlite3", ["-separator", "", DB, sql], { encoding: "utf8" });
  return out.trim().split("\n").filter(Boolean).map((l) => {
    const [id, nombre, cxE, cxC, tool, ts, cxEv, crE, ref, crTool, envT, envP, veredicto,
           estadoInterno, bloqueoInterno] =
      l.split("");
    const parse = (x) => { try { return JSON.parse(x || "{}") || {}; } catch (_) { return {}; } };
    return {
      entityId: id, nombre,
      medicion: {
        conexion: cxE ? { estado: cxE, causa: cxC || null, tool_usada: tool || null,
                          ts: ts || null,
                          // LA EVIDENCIA CRUDA · es donde viaja `causa_refinada`, que es lo
                          // que distingue un `arranque` genérico de un servidor incompatible.
                          evidencia: cxEv ? (() => { try { return JSON.parse(cxEv); }
                                                     catch (_) { return { detail: cxEv }; } })()
                                          : null } : null,
        credencial: crE ? { estado: crE, tool_prueba: crTool || null } : null,
      },
      credencial_ref: ref || null,
      // ENV DECLARADO · las dos mitades del reparto (referencias + nombres publicos). La
      // regla `env-declarado-o-bloqueo` pregunta contra esto, no contra el ambiente.
      env_declarado: Object.assign(parse(envT), parse(envP)),
      // ¿ESTA PIEZA ANDUVO ALGUNA VEZ? Es lo que distingue un primer boot en frio de un
      // server que ya estaba bajado y ahora falla.
      tuvo_verde_previo: veredicto === "probado" || cxE === "viva",
      // ESTRICTO, y no es lo mismo: `probado` exige haber invocado una tool. De él depende
      // la regla anti-yo-yo (regresión vs onboarding a medias).
      estuvo_completa: veredicto === "probado",
      // ⚠️ EL CENSO ES DONDE VIVE NUESTRA DEUDA A PARTIR DE AHORA. La UI no las ve —el
      // endpoint de las fuentes las filtra— pero acá SÍ, porque ésta es nuestra herramienta
      // y una deuda que nadie mira es una deuda que no se paga.
      estado_interno: estadoInterno || null,
      bloqueo_interno: bloqueoInterno || null,
    };
  });
}

/** LOS ALIAS DEL CATÁLOGO · variable → provider. El MISMO archivo que lee el assembler
 *  para inyectar la credencial: si el censo usara otra tabla estaría midiendo un adaptador
 *  distinto del que corre. */
const ALIAS = (() => {
  const j = JSON.parse(readFileSync(join(RAIZ, "catalog/connectors/env-alias.json"), "utf8"));
  const out = {};
  for (const [prov, vars] of Object.entries(j.alias || {}))
    for (const v of vars) if (!out[v]) out[v] = prov;
  return out;
})();

/** LA CLASIFICACIÓN TEMPORAL/PERMANENTE SALE DE `repair_clasificar.py`, NO DE UNA COPIA.
 *
 * Es la pieza que hace posible la regla «arranque sin refinar es TEMPORAL» sin escribir
 * una segunda tabla de causas en JS. Se le pregunta a quien ya sabe: un subproceso, una
 * vez, con todas las causas de la corrida. Si Python no está disponible el censo sigue —
 * sin clasificación las reglas que dependen de ella simplemente no aplican, y eso se ve.
 */
function clasificarCausas(pares) {
  try {
    const py = `
import json, sys
sys.path.insert(0, ${JSON.stringify(join(RAIZ, "platform/inspection"))})
import repair_clasificar as RC
out = {}
for k, causa, ev in json.load(sys.stdin):
    v = RC.clasificar(causa, evidencia=ev or {})
    out[k] = {"clase": v.clase, "accion": v.accion, "boton": v.boton,
              "desempate": v.desempate, "razon": v.razon}
print(json.dumps(out))
`;
    const salida = execFileSync("python3", ["-c", py],
      { input: JSON.stringify(pares), encoding: "utf8" });
    return JSON.parse(salida);
  } catch (e) {
    console.error("  ⚠️  sin clasificación de repair: " + String(e && e.message || e).split("\n")[0]);
    return {};
  }
}

const FICHAS = {};
{
  const d = join(RAIZ, "catalog/connectors/onboarding");
  for (const f of readdirSync(d).filter((x) => x.endsWith(".json"))) {
    try { FICHAS[f.replace(/\.json$/, "")] = JSON.parse(readFileSync(join(d, f), "utf8")); }
    catch (_) { /* una ficha ilegible es su propio hallazgo; se ve como ficha ausente */ }
  }
}

const SERVIDORES = {};
{
  const stack = [join(RAIZ, "catalog")];
  while (stack.length) {
    const dir = stack.pop();
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, e.name);
      if (e.isDirectory()) stack.push(p);
      else if (e.name.endsWith(".mcp.json")) {
        try {
          const d = JSON.parse(readFileSync(p, "utf8"));
          for (const [srv, cfg] of Object.entries(d.mcpServers || {})) SERVIDORES[srv] = cfg;
        } catch (_) { /* idem */ }
      }
    }
  }
}

// ── el censo ────────────────────────────────────────────────────────────────────────
const filas = filasDelRegistro();
const CLASES = clasificarCausas(
  filas.filter((f) => (f.medicion.conexion || {}).causa)
       .map((f) => [f.entityId, f.medicion.conexion.causa, f.medicion.conexion.evidencia || {}]));
const resultados = filas.map((f) => {
  const ficha = FICHAS[f.entityId] || null;
  const servidorBelt = SERVIDORES[f.entityId] || null;
  const cx = f.medicion.conexion || {};
  const camino = Sem.caminoDe({ estado: cx.estado, causa: cx.causa });
  const m = W.derivar({ entityId: f.entityId, ficha, servidorBelt,
                        medicion: f.medicion, camino, credencialRef: f.credencial_ref,
                        vault: VAULT, alias: ALIAS,
                        clasificacion: CLASES[f.entityId] || null,
                        envDeclarado: f.env_declarado,
                        tuvoVerdePrevio: f.tuvo_verde_previo,
                        estuvoCompleta: f.estuvo_completa });
  return { ...f, ficha: !!ficha, belt: !!servidorBelt, modelo: m };
});

const ETIQUETA = {
  conectado: "✅ CONECTADO", esperando: "⏳ ESPERANDO", bloqueado: "🔴 BLOQUEADO",
};
const DONDE = {
  llave: "LLAVE", oauth: "AUTORIZAR", instalar: "INSTALAR", esperar: "midiendo",
  verify: "verify", null: "—",
};

console.log("═".repeat(112));
console.log("CENSO DEL WIDGET ÚNICO · " + filas.length + " piezas del registro");
console.log("═".repeat(112));
console.log(
  "conector".padEnd(20) + "estado final".padEnd(15) + "dónde se queda".padEnd(14) +
  "territorio".padEnd(11) + "por qué (dato real)");
console.log("─".repeat(112));

const porBloqueo = { usuario: [], nuestro: [], ninguno: [] };
//: LA LEY DEL CATÁLOGO LOCAL, como juez del censo: cada pieza cae en UNA de tres listas.
const porLista = { local: [], aduana: [], bloqueadas: [], retenidas: [] };
for (const r of resultados.sort((a, b) => a.entityId.localeCompare(b.entityId))) {
  const v = r.modelo.veredicto;
  porBloqueo[v.bloqueo].push(r);
  const per = r.modelo.pertenencia || {};
  (r.estado_interno === "pendiente_ingesta" ? porLista.retenidas
   : per.local ? porLista.local
   : (per.faltan || []).includes("escrutinio") ? porLista.bloqueadas
   : porLista.aduana).push(r);
  console.log(
    r.entityId.slice(0, 19).padEnd(20) +
    (ETIQUETA[v.estado] || v.estado).padEnd(15) +
    (DONDE[v.donde] || v.donde || "—").padEnd(14) +
    (v.bloqueo === "nuestro" ? "NUESTRO" : v.bloqueo === "usuario" ? "usuario" : "—").padEnd(11) +
    String(v.motivo || "").slice(0, 46));
}

console.log("─".repeat(112));
console.log(`  🏠 EN EL LOCAL (usables YA): ${porLista.local.length}` +
            `   📦 EN LA ADUANA (paso 2.5): ${porLista.aduana.length}` +
            `   🔒 PENDIENTE_INGESTA (deuda NUESTRA, invisible al usuario): ${porLista.retenidas.length}` +
            (porLista.bloqueadas.length ? `   🔴 SIN RETENER: ${porLista.bloqueadas.length}` : ""));
for (const r of porLista.retenidas)
  console.log(`     🔒 ${r.entityId.padEnd(20)} ${r.bloqueo_interno}`);
if (porLista.aduana.length) {
  const grupos = {};
  for (const r of porLista.aduana) {
    const k = (r.modelo.pertenencia.faltan || [])[0] || "?";
    (grupos[k] = grupos[k] || []).push(r.entityId);
  }
  for (const [k, ids] of Object.entries(grupos))
    console.log(`     · ${k.padEnd(10)} ${ids.join(" · ")}`);
}
if (porLista.bloqueadas.length)
  for (const r of porLista.bloqueadas)
    console.log(`     · ${r.entityId.padEnd(20)} ${r.modelo.pertenencia.motivo}`);
console.log("─".repeat(112));
console.log(`  ✅ conectadas: ${porBloqueo.ninguno.length}` +
            `   ⏳ esperando al usuario (VÁLIDO): ${porBloqueo.usuario.length}` +
            `   🔴 bloqueadas por NOSOTROS: ${porBloqueo.nuestro.length}`);

if (porBloqueo.nuestro.length) {
  console.log("\n" + "═".repeat(112));
  console.log("LOS HALLAZGOS · piezas trabadas por razón NUESTRA (cada una es un bug con nombre)");
  console.log("═".repeat(112));
  const agrup = {};
  for (const r of porBloqueo.nuestro) {
    const k = r.modelo.veredicto.motivo;
    (agrup[k] = agrup[k] || []).push(r.entityId);
  }
  for (const [motivo, ids] of Object.entries(agrup).sort((a, b) => b[1].length - a[1].length)) {
    console.log(`\n  ▸ ${motivo}  (${ids.length})`);
    console.log(`    ${ids.join(" · ")}`);
    const ej = porBloqueo.nuestro.find((r) => r.modelo.veredicto.motivo === motivo);
    console.log(`    fuente: ${ej.modelo.veredicto.fuente}`);
  }
}

// LA LEY DE FONDO · verde exige evidencia. Un ✅ sin verbo que lo respalde no existe.
console.log("\n" + "═".repeat(112));
console.log("ESCRUTINIO · ningún verde sin la evidencia del verbo que lo midió");
console.log("═".repeat(112));
const verdesSinEvidencia = porBloqueo.ninguno.filter((r) => {
  const e = r.modelo.evidencia;
  return !e || !e.ts || (!e.tool_usada && e.estado === "viva");
});
console.log(`  verdes: ${porBloqueo.ninguno.length} · sin evidencia completa: ${verdesSinEvidencia.length}`);
if (verdesSinEvidencia.length) {
  for (const r of verdesSinEvidencia.slice(0, 12)) {
    const e = r.modelo.evidencia || {};
    console.log(`    ${r.entityId.padEnd(20)} estado=${e.estado || "—"} tool_usada=${e.tool_usada || "—"} ts=${e.ts || "—"}`);
  }
  if (verdesSinEvidencia.length > 12) console.log(`    … y ${verdesSinEvidencia.length - 12} más`);
}
