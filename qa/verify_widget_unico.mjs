#!/usr/bin/env node
/**
 * verify_widget_unico.mjs — LA VARA DEL WIDGET ÚNICO.
 *
 *   node qa/verify_widget_unico.mjs
 *
 * Los seis casos son LOS BUGS QUE PERSONA USUARIA REPORTÓ, congelados como prueba. No son ejemplos
 * inventados: cada uno es algo que se vio roto en la app y que no puede volver.
 *
 * Y el séptimo guard es el que hace que esto escale a 17.000 piezas: **GENERATIVO**. No
 * comprueba textos, comprueba que CADA elemento que el widget produce se trace a un campo
 * declarado o a un verbo. Un paso sin fuente es contenido hardcodeado por conector, y eso
 * muere en el conector 29.
 */
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..");
const W = await import(join(RAIZ, "product/app/design/conectores/widget.js"));
const Sem = await import(join(RAIZ, "product/app/design/cuarto/cuarto.semaforo.js"));

const FALLOS = [];
const ok = (c, t, d = "") => {
  console.log((c ? "  ✅ " : "  ❌ ") + t + (d ? ` · ${d}` : ""));
  if (!c) FALLOS.push(t);
  return c;
};
const ficha = (n) => {
  try { return JSON.parse(readFileSync(join(RAIZ, `catalog/connectors/onboarding/${n}.json`), "utf8")); }
  catch (_) { return null; }
};
const servidores = (() => {
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
/** LOS ALIAS DEL CATÁLOGO · variable → provider para los nombres que no siguen la
 *  convención. Es el MISMO archivo que lee el assembler para inyectar la credencial; si la
 *  vara usara otro, estaría probando un adaptador que no es el que corre en producción. */
const ALIAS = (() => {
  const j = JSON.parse(readFileSync(join(RAIZ, "catalog/connectors/env-alias.json"), "utf8"));
  const out = {};
  for (const [prov, vars] of Object.entries(j.alias || {}))
    for (const v of vars) if (!out[v]) out[v] = prov;   // primero gana, igual que en Python
  return out;
})();

//: EL VAULT ES PARTE DEL FIXTURE, no un opcional. Una pieza con la credencial `verde` tiene
//: su llave guardada — el verificador sólo escribe verde tras la prueba doble, y la prueba
//: doble necesita la llave real. Un testigo que declara verde y no pone la llave describe un
//: mundo que no existe, y desde que **pendiente-del-usuario domina sobre canal-ok** eso ya
//: no pasa desapercibido: la pieza sale 🟡 «falta tu llave», que es lo correcto para ese
//: fixture y no lo que el testigo quería probar.
const modelo = (id, med, vault) => W.derivar({
  entityId: id, ficha: ficha(id), servidorBelt: servidores[id] || null, medicion: med,
  alias: ALIAS, vault: vault || [],
  camino: Sem.caminoDe({ estado: (med.conexion || {}).estado, causa: (med.conexion || {}).causa }),
});

console.log("══ VARA DEL WIDGET ÚNICO · los 6 bugs reportados, congelados ══\n");

// ── 1 · FALTA LA LLAVE → campo inline, jamás «error del proveedor» ────────────────────
console.log("1 · falta la llave → campo inline + guardar, jamás «error del proveedor»");
{
  // El testigo se arma con una pieza REAL que pide llave. `maad` resultó ser keyless (su
  // único env es `PUPPET_WORKDIR`) y el servidor con las dos llaves —`maritime`— no está
  // equipado; se deja anotado en el reporte. Se prueba con `huggingface`, que sí la pide.
  const m = modelo("huggingface", { conexion: { estado: "rota", causa: "falta_key", ts: 1 },
                                    credencial: { estado: "sin_medir" } });
  const paso = m.pasos.find((p) => p.tipo === W.PASO_LLAVE);
  ok(!!paso, "hay un paso de llave");
  ok(paso && paso.campos.length > 0, "con sus campos, derivados de la ficha",
     paso && paso.campos.map((c) => c.key).join(", "));
  ok(paso && !!paso.link, "y con DÓNDE conseguirla (deep_link declarado)", paso && paso.link);
  ok(paso && paso.territorio === W.USUARIO, "el territorio es del usuario: esperar es válido");
  ok(m.boton && m.boton.accion === "credencial" && m.boton.inline === true,
     "el botón sale de repair y es INLINE", m.boton && m.boton.es);
  ok(m.veredicto.estado === "esperando" && m.veredicto.bloqueo === W.USUARIO,
     "veredicto: esperando al usuario, no «error del proveedor»", m.veredicto.motivo);
}

// ── 2 · CREDENCIAL GUARDADA → verify solo, header nuevo, sin [Probar de nuevo] ────────
console.log("\n2 · credencial guardada → verify SOLO, el header viejo no sobrevive");
{
  const viejo = modelo("huggingface", { conexion: { estado: "rota", causa: "falta_key", ts: 100 },
                                        credencial: { estado: "sin_medir" } });
  // El verde llega COMO LO ESCRIBE EL VERIFICADOR: con la tool que lo certificó. Un verde
  // sin `tool_prueba` es un verde sin evidencia, y la tabla de conocimiento lo degrada a
  // «midiendo» a propósito — así que el testigo usa la forma real, no una abreviada.
  const nuevo = modelo("huggingface", { conexion: { estado: "viva", causa: null, ts: 200,
                                                    tool_usada: "search_models" },
                                        credencial: { estado: "verde",
                                                      tool_prueba: "search_models" } },
                       ["huggingface"]);
  ok(viejo.header.estado === "rota" && nuevo.header.estado === "viva",
     "el header se deriva de la medición que se pinta, no de una caché");
  ok(viejo.header.ts !== nuevo.header.ts, "y trae su CUÁNDO, así un header viejo se nota",
     `${viejo.header.ts} → ${nuevo.header.ts}`);
  ok(nuevo.boton === null, "conectado no ofrece botón: no hay [Probar de nuevo]");
  ok(Sem.necesitaMedicionInterna({ estado: "viva" }, { estado: "sin_medir" }) === true,
     "y con la llave recién puesta, verify se dispara SOLO");
  ok(nuevo.veredicto.estado === "conectado" && !!nuevo.evidencia.tool_usada,
     "el verde llega CON la tool que lo midió", nuevo.evidencia.tool_usada);
  ok(nuevo.pasos.every((p) => p.territorio !== W.USUARIO),
     "y el verde se GANÓ: cero pendientes del usuario");

  //: LA CONTRACARA, congelada acá porque es la regla que más fácil se pierde: si la llave se
  //: va del vault, el MISMO registro verde deja de valer como conectado. El canal sigue
  //: vivo; lo que ya no está es lo que hace usable la pieza.
  const sinLlave = modelo("huggingface", { conexion: { estado: "viva", causa: null, ts: 200,
                                                       tool_usada: "search_models" },
                                           credencial: { estado: "verde",
                                                         tool_prueba: "search_models" } }, []);
  ok(sinLlave.veredicto.estado === "esperando" && sinLlave.veredicto.bloqueo === W.USUARIO,
     "sin la llave en el vault, el canal vivo NO alcanza para el verde",
     sinLlave.veredicto.motivo);
}

// ── 3 · REQUIERE APP → link oficial + [Ya lo instalé · verificar] ─────────────────────
console.log("\n3 · requiere app → link oficial, jamás «no encontré cómo instalar»");
{
  const m = modelo("freecad", { conexion: { estado: "rota", causa: "cli_no_instalado", ts: 1 },
                                credencial: { estado: "no_aplica" } });
  const paso = m.pasos.find((p) => p.tipo === W.PASO_INSTALAR);
  ok(!!paso, "hay un paso de instalación");
  ok(paso && /^https:\/\//.test(paso.link || ""), "con LINK OFICIAL declarado en el belt",
     paso && paso.link);
  ok(paso && !!paso.que, "y con QUÉ hay que instalar", paso && paso.que);
  ok(paso && paso.rotulo === "Ya lo instalé · verificar",
     "y el rótulo sale del catálogo, no del widget", paso && paso.rotulo);
  ok(paso && paso.territorio === W.USUARIO, "instalar es territorio del usuario");
}

// ── 4 · EL RESUMEN Y LAS CARDS NO PUEDEN DIFERIR ─────────────────────────────────────
console.log("\n4 · el resumen y las cards no pueden diferir: es la misma lista contada");
{
  // ⚠️ ESTE TESTIGO CAMBIÓ DE FORMA PORQUE EL BUG DEJÓ DE SER POSIBLE.
  //
  // Congelaba que `conexionActiva` y `resumenDe` de `conectores.ui.js` leyeran la misma
  // coordenada — una regla que alguien tenía que respetar, sobre dos funciones que podían
  // separarse. Medido entonces: el resumen decía «1 conexión activa» encima de una lista
  // llena de ✅ Conectado, porque una contaba con el vocabulario del motor y la otra con el
  // del registro.
  //
  // Con el adaptador no hay dos funciones que puedan separarse: hay UNA lista de modelos,
  // el resumen la cuenta y las cards la pintan. La coincidencia dejó de ser una disciplina y
  // pasó a ser aritmética. La comprobación numérica sobre el HTML vive en
  // `qa/verify_superficie_montada.mjs`; acá queda el guard de que la fuente sigue siendo
  // una sola.
  const src = readFileSync(join(RAIZ, "product/app/design/conectores/superficie.js"), "utf8");
  ok(/export function pintarResumen\(modelos\)/.test(src),
     "`pintarResumen` recibe LA lista de modelos, no una consulta propia");
  ok(/modelos\.filter\(\(m\) => m\.veredicto\.estado === "conectado"/.test(src),
     "y cuenta el MISMO veredicto que pinta cada card");
  ok(!/probado/.test(src),
     "y en ninguna parte cae al vocabulario del motor");
}

// ── 5 · SIN MEDIR → «sin medir», null, jamás ceros ────────────────────────────────────
console.log("\n5 · sin medir → sin medir; nunca un cero que nadie contó");
{
  const entry = { service: "x", id: "x", servers: [{ name: "x", tools: ["a", "b"], belt_ref: "b" }] };
  const e = (Sem.agregarEstadoEntidad(entry, [{ server: entry.servers[0], estado: null }], true)).evidencia;
  ok(e.disponibles === null, "`disponibles` es null, no 0", JSON.stringify(e.disponibles));
  ok(e.nombres_tools_comprobados === false, "`nombres_tools_comprobados` es false");
  ok(e.sin_medir === true && /sin medir/.test(e.detail), "y lo dice", `«${e.detail}»`);
  const m = modelo("huggingface", { conexion: { estado: "sin_sondear", ts: 1 }, credencial: null });
  ok(m.pasos.some((p) => p.tipo === W.PASO_ESPERAR), "y el paso es ESPERAR, sin botón");
  ok(m.boton === null, "sin_sondear no ofrece botón al usuario");
}

// ── 6 · CERO CONFESIONES ──────────────────────────────────────────────────────────────
console.log("\n6 · cero confesiones en lo que el widget produce");
{
  const PROHIBIDO = /(no s[ée] qu|no pude|no encontr|defecto nuestro|culpa nuestra|servidor MCP|el backend)/i;
  const textos = [];
  for (const id of Object.keys(servidores).slice(0, 60)) {
    for (const est of ["viva", "rota", "sin_sondear"]) {
      const m = modelo(id, { conexion: { estado: est, causa: "falta_key", ts: 1 }, credencial: null });
      textos.push(JSON.stringify({ h: m.header, p: m.pasos, b: m.boton, v: m.veredicto }));
    }
  }
  const sucios = textos.filter((t) => PROHIBIDO.test(t));
  ok(sucios.length === 0, `cero confesiones en ${textos.length} modelos derivados`,
     sucios.length ? sucios[0].slice(0, 90) : "");
}

// ── 6b · CRUZAR DECLARACIONES Y DELATAR LA CONTRADICCIÓN ─────────────────────────────
console.log("\n6b · el adaptador cruza belt vs ficha vs registro y delata la diferencia");
{
  // Capacidad GENERAL, no un caso: se prueba con datos sintéticos para que no dependa de
  // qué piezas están rotas hoy. Lo que se congela es la habilidad, no el ejemplar.
  const beltPide = { env: { ACME_API_KEY: "${ACME_API_KEY}" } };
  const c1 = W.contradicciones({ ficha: null, servidorBelt: beltPide,
                                 medicion: { credencial: { estado: "no_aplica" } } });
  ok(c1.length === 1 && /no_hace_falta_llave_y_el_belt_pide/.test(c1[0].tipo),
     "belt pide llave + registro dice `no_aplica` → contradicción", c1[0] && c1[0].tipo);
  ok(c1[0] && c1[0].pide.includes("ACME_API_KEY"),
     "y nombra QUÉ variable pide, con su fuente", c1[0] && c1[0].fuente);

  const c2 = W.contradicciones({ ficha: { auth_method: "keyless" }, servidorBelt: beltPide,
                                 medicion: {} });
  ok(c2.some((x) => x.tipo === "la_ficha_dice_keyless_y_el_belt_pide_llave"),
     "ficha keyless + belt que pide llave → contradicción");

  const c3 = W.contradicciones({ ficha: null, servidorBelt: { env: {} },
                                 medicion: {}, credencialRef: "acme" });
  ok(c3.some((x) => x.tipo === "hay_llave_guardada_para_algo_que_no_la_usa"),
     "llave guardada para algo que no la pide → contradicción");

  const sano = W.contradicciones({ ficha: { auth_method: "personal_token" },
                                   servidorBelt: beltPide,
                                   medicion: { credencial: { estado: "verde" } } });
  ok(sano.length === 0, "y una pieza coherente NO genera ruido");

  // Y lo que la ley de fondo exige: una contradicción GANA sobre el verde.
  const v = W.veredictoDe({ ficha: null, servidorBelt: beltPide,
                            medicion: { conexion: { estado: "viva" },
                                        credencial: { estado: "no_aplica" } } });
  ok(v.bloqueo === W.NUESTRO,
     "una pieza contradictoria NO luce verde aunque el canal esté vivo", v.motivo);
}

// ── 7 · EL GUARD GENERATIVO · todo se traza a un campo declarado o a un verbo ─────────
console.log("\n7 · GENERATIVO · cada elemento se traza a un campo declarado o a un verbo");
{
  //: Las fuentes legítimas. Cualquier otra cosa es contenido inventado por el widget.
  const LEGITIMAS = [
    /^ficha\./, /^belt\./, /^registro\./, /^verify\b/, /^repair\b/, /^\(ninguna:/,
  ];
  const sinFuente = [];
  const inventadas = [];
  let n = 0;
  for (const id of Object.keys(servidores)) {
    const m = modelo(id, { conexion: { estado: "rota", causa: "falta_key", ts: 1 },
                           credencial: { estado: "sin_medir" } });
    for (const p of m.pasos) {
      n++;
      if (!p.fuente) { sinFuente.push(`${id}:${p.tipo}`); continue; }
      if (!LEGITIMAS.some((re) => re.test(p.fuente))) inventadas.push(`${id}:${p.tipo} ← ${p.fuente}`);
    }
  }
  ok(sinFuente.length === 0, `los ${n} pasos derivados declaran su fuente`,
     sinFuente.length ? sinFuente.slice(0, 5).join(", ") : "");
  ok(inventadas.length === 0, "y ninguna fuente está fuera del catálogo o los verbos",
     inventadas.length ? inventadas.slice(0, 3).join(" · ") : "");

  //: Y el guard duro: CERO nombres de conector en el código del widget. Es lo que hace que
  //: la pieza 17.000 funcione sin tocarlo.
  const src = readFileSync(join(RAIZ, "product/app/design/conectores/widget.js"), "utf8");
  const cuerpo = src.split("\n")
    .filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l))   // la prosa puede nombrar ejemplos
    .join("\n");
  const nombres = Object.keys(servidores).filter((s) => s.length > 4);
  const hardcodeados = nombres.filter((s) => new RegExp(`["'\`]${s}["'\`]`).test(cuerpo));
  ok(hardcodeados.length === 0,
     `cero nombres de conector en el código (probado contra los ${nombres.length} del catálogo)`,
     hardcodeados.length ? `HARDCODEADOS: ${hardcodeados.join(", ")}` : "");
}

console.log("\n" + (FALLOS.length === 0
  ? "══ ✅ EL WIDGET ÚNICO CUMPLE · deriva todo, no hardcodea nada ══"
  : `══ ❌ ${FALLOS.length} FALLO(S): ${JSON.stringify(FALLOS)} ══`));
process.exit(FALLOS.length ? 1 : 0);
