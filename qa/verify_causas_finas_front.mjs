/* verify_causas_finas_front.mjs — EL COPY de las cuatro causas finas.
 *
 * La corre `qa/verify_causas_finas.py`; imprime una línea JSON con los testigos. No se
 * invoca suelta: la vara es una sola, como manda la casa.
 *
 * LO QUE MIDE es lo que el usuario LEE. El backend ya no escribe prosa; el texto sale del
 * vocabulario compartido (`conectores/causas-catalogo.js`) y las dos superficies —la
 * sección y el HUD del Cuarto— tienen que contar el mismo fracaso con las mismas palabras.
 */
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..");
const D = join(RAIZ, "product/app/design");
const R = {};
const anotar = (n, ok, det = {}) => { R[n] = { ok: !!ok, ...det }; };

const V = await import(join(D, "conectores/causas-catalogo.js"));
const SC = await import(join(D, "conectores/superficie-catalogo.js"));

const CUATRO = ["servicio_inexistente", "servicio_no_responde",
                "credencial_no_declarada", "sin_herramientas"];

/* ── 1 · las cuatro existen, con copy ES y EN distintas ──────────────────────────────── */
const faltan = CUATRO.filter((c) => !V.CAUSAS_CATALOGO[c]);
const sinEN = CUATRO.filter((c) => {
  const m = V.CAUSAS_CATALOGO[c] || {};
  return !m.en || m.en === m.es;
});
anotar("5a_las_cuatro_tienen_copy_es_y_en", !faltan.length && !sinEN.length,
  { faltan, sin_en: sinEN });

/* ── 2 · ninguna sale provisional (es lo que separa «sellada» de «parcheada») ─────────── */
const provisionales = CUATRO.filter((c) => (V.causaDe(c) || {}).provisional !== false);
anotar("5b_ninguna_es_provisional", provisionales.length === 0, { provisionales });

/* ── NEGATIVO · el fallback SIGUE vivo. Si agregar causas hubiera roto el camino de la
 *   causa desconocida, la próxima llegaría muda — que es el fallo que la regla prohíbe. */
const inventada = V.causaDe("causa_que_todavia_no_existe");
anotar("5c_negativo_una_causa_desconocida_sale_provisional",
  !!inventada && !!inventada.texto && inventada.provisional === true, { inventada });

/* ── 3 · NADIE CULPA A LA FICHA SI LA FICHA ESTÁ BIEN ─────────────────────────────────
 * Éste es el defecto que originó la obra. Tres de las cuatro no tienen nada que ver con la
 * ficha —un dominio muerto, un servicio caído, un catálogo vacío— así que mencionarla sería
 * acusarla. La cuarta SÍ la nombra, y ahí es exacto: la ficha efectivamente no declara esa
 * llave. Se afirma en las dos direcciones para que el testigo pueda rojear de los dos lados. */
const acusaFicha = (c) => /ficha|listing/i.test(V.causaDe(c).texto + " " + V.CAUSAS_CATALOGO[c].en);
const noDebenAcusar = ["servicio_inexistente", "servicio_no_responde", "sin_herramientas"];
anotar("5d_no_culpan_a_la_ficha", noDebenAcusar.every((c) => !acusaFicha(c)),
  { acusan: noDebenAcusar.filter(acusaFicha) });
anotar("5d_y_la_que_si_la_nombra_es_porque_la_ficha_falta",
  acusaFicha("credencial_no_declarada"),
  { texto: V.causaDe("credencial_no_declarada").texto });

/* ── 4 · la frase que mentía se fue ───────────────────────────────────────────────────
 * `curacion_rechazo` decía «no respondió como su ficha dice que responde» para los cuatro
 * mundos. Ahora es el resto honesto y no puede seguir acusando. */
const resto = V.CAUSAS_CATALOGO.curacion_rechazo;
anotar("5e_el_resto_honesto_ya_no_acusa_a_la_ficha",
  !/ficha|listing/i.test(resto.es + " " + resto.en), { es: resto.es });
const fuenteVieja = readFileSync(join(D, "conectores/causas-catalogo.js"), "utf8");
anotar("5e_negativo_la_frase_de_antes_esta_documentada_como_lo_que_fue",
  fuenteVieja.includes("no respondió como su ficha dice que responde"),
  { nota: "la frase vieja sobrevive SÓLO en el comentario que explica por qué se fue" });

/* ── 5 · cada causa tiene su salida, y `nada` no ofrece un botón inútil ───────────────── */
const salidaDe = (c) => V.causaDe(c).accion;
anotar("5f_cada_causa_tiene_la_salida_sellada",
  salidaDe("servicio_inexistente") === "nada"
  && salidaDe("servicio_no_responde") === "reintentar"
  && salidaDe("credencial_no_declarada") === "llave"
  && salidaDe("sin_herramientas") === "nada",
  Object.fromEntries(CUATRO.map((c) => [c, salidaDe(c)])));

// El `pintarViaje` de la sección es quien materializa la salida. Se lo mira de verdad, no
// se confía en el nombre de la acción: un botón que aparece igual sería la mentira nueva.
//
// ⚠️ EL VIAJE VA CON SUS PASOS, y no es decorativo: `pintarViaje` sólo pinta la causa —y con
// ella la salida— colgada del paso ROTO. Con `pasos: []` no dibuja nada, así que este
// testigo salía verde por vacío. Lo cazó su propio discriminante.
const viaje = (causa, extra = {}) => SC.pintarViaje({
  cerrado: true, ok: false, causa, causaLiteral: null, siguiente: null,
  servidor: "com.ejemplo/mcp",
  pasos: [{ id: "resolver", estado: "hecho" },
          { id: "comprobar", estado: "roto" },
          { id: "traer", estado: "pendiente" }],
  ...extra,
});
// ⚠️ SE MIRA LA SALIDA, NO «UN BOTÓN CUALQUIERA». Esto decía `!/<button|cx-accion/` y
// rojeó al integrar C: desde «el final del viaje», TODO viaje cerrado —también el que
// falla— lleva su ✕, porque cerrar es del usuario. Ese botón es correcto y tiene que
// estar. Lo que estas dos causas no pueden tener es una SALIDA (`cx-accion`), que es la
// promesa de que hay algo que hacer. Prohibir «cualquier botón» medía de más y hacía que
// una mejora ajena se leyera como regresión propia.
const sinBoton = ["servicio_inexistente", "sin_herramientas"]
  .every((c) => !/cx-accion/.test(viaje(c)));
anotar("5g_las_que_no_tienen_salida_no_pintan_boton", sinBoton,
  { inexistente_tiene_salida: /cx-accion/.test(viaje("servicio_inexistente")) });

// …y la ✕ SÍ está: cerrar es del usuario también cuando el viaje terminó mal. Sin este
// testigo, `5g` se cumpliría con una superficie que no deja cerrar nada.
anotar("5g_pero_la_equis_de_cerrar_si_esta",
  ["servicio_inexistente", "sin_herramientas"]
    .every((c) => /data-cerrar-viaje/.test(viaje(c, { cerrado: true }))),
  { nota: "el fallo cerrado también se cierra con la ✕" });

// DISCRIMINANTE · las que SÍ tienen salida la pintan. Sin esto, `5g` saldría verde con un
// `pintarViaje` que no dibuja nada nunca.
anotar("5g_discriminante_las_que_si_tienen_salida_la_pintan",
  /data-reintentar-viaje/.test(viaje("servicio_no_responde"))
  && /data-traer-con-llave/.test(viaje("credencial_no_declarada")),
  { no_responde: /data-reintentar-viaje/.test(viaje("servicio_no_responde")),
    sin_llave: /data-traer-con-llave/.test(viaje("credencial_no_declarada")) });

/* ── 6 · las DOS superficies cuentan el mismo fracaso con las mismas palabras ─────────── */
anotar("5h_la_seccion_reexporta_el_mismo_vocabulario",
  SC.causaDe("servicio_inexistente").texto === V.causaDe("servicio_inexistente").texto
  && SC.CAUSAS_CATALOGO === V.CAUSAS_CATALOGO,
  { misma_tabla: SC.CAUSAS_CATALOGO === V.CAUSAS_CATALOGO });

const hud = readFileSync(join(D, "cuarto/catalog_equip.js"), "utf8");
anotar("5h_el_hud_del_cuarto_lee_la_causa_no_el_detail",
  hud.includes('from "../conectores/causas-catalogo.js"') && hud.includes("causaDe(ev.cause)"),
  { importa: hud.includes("causas-catalogo.js"), usa_causa: hud.includes("causaDe(ev.cause)") });

/* ── 7 · sin jerga: ninguna frase muestra el nombre técnico de su causa ───────────────── */
const conJerga = CUATRO.filter((c) => V.causaDe(c).texto.includes(c));
anotar("5i_ninguna_muestra_su_nombre_tecnico", conJerga.length === 0, { conJerga });

console.log(JSON.stringify(R));
