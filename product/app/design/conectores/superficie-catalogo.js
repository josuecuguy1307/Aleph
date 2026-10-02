/* superficie-catalogo.js — LA CARA DEL CATÁLOGO PÚBLICO. Funciones puras, y todo el texto.
 *
 * Hermana de `superficie.js`, con la misma ley y por la misma razón: devuelve STRINGS y no
 * toca el DOM, así la vara prueba **lo que el usuario ve** sin levantar un navegador. Una
 * vara que necesita browser se corre una vez y se abandona — el árbol ya tiene varias así.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * ESTE ES EL ÚNICO ARCHIVO DE LA SECCIÓN QUE ESCRIBE PALABRAS.
 *
 * `catalogo.js` deriva estructura (`aviso.escriben` es un booleano); acá se convierte en
 * frase. Y ninguna frase nombra un conector: las 17.000 piezas del registro pasan por estas
 * funciones, y un rótulo escrito para una es un rótulo equivocado para las otras 16.999.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * LA REGLA SELLADA QUE ESTE ARCHIVO TIENE QUE CUMPLIR: **ninguna causa llega a una
 * superficie sin copy.** Si el backend empieza a emitir una causa que `CAUSAS_CATALOGO` no
 * conoce, NO se pinta su nombre técnico crudo ni se calla: se deriva un texto provisional y
 * se marca como provisional, para que la falta se vea y se arregle. Callarla sería un fallo
 * mudo; mostrar `curacion_rechazo` en pantalla sería jerga.
 */
import * as C from "./catalogo.js";
import { CAUSAS_CATALOGO, causaDe, L, lang } from "./causas-catalogo.js";

// EL VOCABULARIO DE CAUSAS SE MUDÓ a `causas-catalogo.js` y esta superficie dejó de ser su
// dueña: el HUD del Cuarto pinta el mismo fracaso y necesita las mismas palabras. Se
// re-exporta para no romper a nadie que hoy lo importe de acá (la vara, entre otros).
export { CAUSAS_CATALOGO, causaDe };

const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ── LO QUE PIDE UNA PIEZA · por TIPO, jamás por conector ────────────────────────────── */

const REQUISITO = () => ({
  llave:    { icono: "🔑", corto: L("Llave", "Key"),
              largo: L("Pide tu llave", "Needs your key"),
              copy: L("La pegas después de traerla, en En preparación.",
                      "You paste it after bringing it, in In preparation.") },
  descarga: { icono: "↓", corto: L("Descarga", "Download"),
              largo: L("Pide una descarga", "Needs a download"),
              copy: L("Corre en tu equipo: hay que instalarlo una vez.",
                      "It runs on your machine: install it once.") },
  click:    { icono: "↗", corto: L("Click", "Click"),
              largo: L("Pide un click", "Needs a click"),
              copy: L("Autorizas en el sitio del servicio y vuelves.",
                      "You authorize on the service's site and come back.") },
  ninguno:  { icono: "·", corto: L("No pide nada", "Needs nothing"),
              largo: L("No pide nada", "Needs nothing"),
              copy: L("Queda lista para usar apenas llega.",
                      "It's ready to use as soon as it arrives.") },
});

const reqDe = (fila) => REQUISITO()[fila.requisito] || REQUISITO().ninguno;

/** QUÉ AVISA, en una frase. Se arma con los verbos que el manifest declaró — no hay una
 *  entrada por conector, hay una por combinación de verbos, que es lo que escala. */
export function avisoTexto(aviso) {
  if (!aviso || !aviso.declara)
    return L("No declara qué hace — se sabrá al conectar.",
             "It doesn't declare what it does — you'll find out on connecting.");
  const verbos = [];
  if (aviso.escriben) verbos.push(L("escriben", "write"));
  if (aviso.envian) verbos.push(L("envían", "send"));
  if (aviso.borran) verbos.push(L("borran", "delete"));
  if (!verbos.length)
    return L(`Declara ${aviso.cuantas} herramientas: ninguna escribe, envía ni borra.`,
             `Declares ${aviso.cuantas} tools: none write, send or delete.`);
  const y = L(" y ", " and ");
  const lista = verbos.length === 1 ? verbos[0]
              : verbos.slice(0, -1).join(", ") + y + verbos[verbos.length - 1];
  return L(`Declara herramientas que ${lista} en tu cuenta.`,
           `Declares tools that ${lista} in your account.`);
}

/** La barra de confianza: cuatro tramos. Es la MISMA cuenta que el número de al lado, así
 *  que no pueden decir cosas distintas. */
function barra(confianza) {
  if (typeof confianza !== "number") return "";
  const llenos = Math.max(0, Math.min(4, Math.round(confianza * 4)));
  let h = `<span class="cat-barra" aria-hidden="true">`;
  for (let i = 0; i < 4; i++) h += `<i class="${i < llenos ? "on" : ""}"></i>`;
  return h + `</span>`;
}

/** La fecha de un sello de tiempo. Igual que en la card: nunca se inventa un formato. */
function cuando(ts) {
  const t = ts == null ? NaN : Date.parse(String(ts));
  if (!Number.isFinite(t)) return null;
  try {
    return new Intl.DateTimeFormat(lang() === "en" ? "en" : "es",
      { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(t));
  } catch (_) { return String(ts); }
}

/** La cara del servicio. La misma que las 41: Brandface, o iniciales deterministas. */
function cara(fila) {
  try {
    if (typeof window !== "undefined" && window.AlephBrand)
      return AlephBrand.faceHTML({ connector: null, server: fila.servidor,
                                   name: fila.servidor, label: fila.nombre },
                                 { size: 34, cls: "cx-logo" });
  } catch (_) { /* la cara nunca puede tumbar la fila */ }
  return `<span class="cx-logo-fallback" aria-hidden="true">` +
         `${esc(String(fila.nombre || "?").slice(0, 2).toUpperCase())}</span>`;
}

/* ══════════════════════════════════════════════════════════════════════════════════════
 * LA LISTA
 * ════════════════════════════════════════════════════════════════════════════════════ */

/** Los nombres de los requisitos filtrados, en la lengua de la casa: «llave» · «llave o un
 *  click». Se usa en el borde del filtro vacío para decir QUÉ se pidió, no un código. */
function nombresDe(filtro) {
  const R = REQUISITO();
  const n = (filtro || []).map((r) => (R[r] || R.ninguno).corto.toLowerCase());
  if (n.length <= 1) return n[0] || "";
  return n.slice(0, -1).join(", ") + L(" ni ", " nor ") + n[n.length - 1];
}

/** EL FILTRO POR REQUISITO · chips DERIVADOS de lo que llegó, con su conteo.
 *
 * ⚠️ NO ES UN COMPONENTE NUEVO: cada chip es el mismo par icono + `corto` que la fila ya
 * pinta a la derecha (`REQUISITO()`). Si inventara otro rótulo, la lista y su filtro dirían
 * la misma cosa de dos maneras y un día dirían dos cosas distintas.
 *
 * Los conteos salen de `vista.opciones`, que el modelo derivó del universo COMPLETO: no se
 * mueven al filtrar, así que se puede sumar un segundo requisito sin quedar encerrado.
 * `aria-pressed` es el estado, no una clase: el filtro tiene que poder usarse sin ver.
 */
export function pintarFiltro(vista) {
  const ops = vista.opciones || [];
  // Con un solo requisito PRESENTE no se ofrece nada: filtrar no separaría a nadie de nadie,
  // y una barra que no puede cambiar la lista es ruido. Se mira cuántos tienen cuenta > 0,
  // no cuántas opciones hay — las cuatro están siempre.
  if (ops.filter((o) => o.cuenta > 0).length < 2) return "";
  const R = REQUISITO();
  const puestos = vista.filtro || [];
  return `<div class="cat-filtro" role="group" data-filtro-host="1"` +
    ` aria-label="${esc(L("Filtrar por lo que pide", "Filter by what it needs"))}">` +
    `<span class="cat-filtro-tit">${esc(L("Pide:", "Needs:"))}</span>` +
    ops.map((o) => {
      const r = R[o.req] || R.ninguno;
      const on = puestos.includes(o.req);
      // el chip en cero se ofrece igual, atenuado: dice «ninguna pide esto», que es un dato,
      // y es el único camino al estado vacío del filtro.
      return `<button class="cat-chip${on ? " on" : ""}${o.cuenta ? "" : " vacio"}"` +
        ` data-filtro="${esc(o.req)}" data-cuenta="${o.cuenta}"` +
        ` aria-pressed="${on ? "true" : "false"}">` +
        `<span aria-hidden="true">${esc(r.icono)}</span> ${esc(r.corto)}` +
        `<span class="cat-chip-n">${o.cuenta}</span></button>`;
    }).join("") +
    (puestos.length
      ? `<button class="cat-chip-limpiar" data-filtro-limpiar="1">` +
        `${esc(L("Quitar filtro", "Clear filter"))}</button>`
      : "") +
    `</div>`;
}

/** UNA FILA DEL REGISTRO · nombre, voz, requisito, confianza, sello — y el aviso ABAJO,
 *  en una franja de ancho completo.
 *
 * ⚠️ EL AVISO NO SE ESCONDE DETRÁS DE UN CLICK, y por eso tiene su propia franja en vez de
 * ser una celda más. Es lo único que puede cambiar la decisión de alguien ANTES de traer
 * una pieza; meterlo en el [?] sería ponerlo donde sólo lo ve quien ya decidió. */
export function pintarFila(fila, { seleccionada = false } = {}) {
  const r = reqDe(fila);
  const s = fila.sello;
  return `<li class="cat-fila${seleccionada ? " on" : ""}" data-pieza="${esc(fila.id)}"` +
    ` data-verificada="${s.verificado ? "true" : "false"}"` +
    ` data-requisito="${esc(fila.requisito)}">` +
    `<button class="cat-fila-btn" data-elegir="${esc(fila.id)}"` +
    ` aria-pressed="${seleccionada ? "true" : "false"}">` +
      `<span class="cat-face">${cara(fila)}</span>` +
      `<span class="cat-copy">` +
        `<span class="cat-nombre">${esc(fila.nombre)}` +
          // EL ✓ SÓLO CON PIN. Lo demás identifica al publicador y no lleva sello: el
          // badge ya viene decidido por el backend, acá sólo se elige cómo se ve.
          (s.etiqueta ? `<span class="cat-sello${s.verificado ? " ok" : ""}">` +
                        `${esc(s.etiqueta)}</span>` : "") +
        `</span>` +
        (fila.voz ? `<span class="cat-voz">${esc(fila.voz)}</span>` : "") +
      `</span>` +
      `<span class="cat-req">${esc(r.icono)} ${esc(r.largo)}</span>` +
      `<span class="cat-conf">` +
        (fila.confianza == null ? "" :
          `<b>${esc(fila.confianza.toFixed(2))}</b>` +
          `<small>${esc(L("confianza", "confidence"))}</small>${barra(fila.confianza)}`) +
      `</span>` +
      `<span class="cat-chev" aria-hidden="true">›</span>` +
    `</button>` +
    `<p class="cat-aviso${fila.aviso.pesa ? " pesa" : ""}">${esc(avisoTexto(fila.aviso))}</p>` +
    `</li>`;
}

/** LA LISTA ENTERA, o EL BORDE QUE CORRESPONDA.
 *
 * ⚠️ TRES BORDES, TRES CARAS DISTINTAS. Una lista vacía no significa nada por sí sola: hay
 * que decir POR QUÉ está vacía. «Todavía no buscaste» invita a escribir; «no pudimos
 * preguntar» ofrece reintentar y aclara que tus piezas siguen andando; «preguntamos y no
 * existe» ofrece construirlo. Pintar los tres igual convierte un outage en la mentira de
 * que el conector de alguien no existe. */
export function pintarLista(vista, { conectadas = null } = {}) {
  if (vista.borde === C.BORDE_VACIO)
    return `<div class="cat-borde" data-borde="vacio">` +
      `<p class="cat-borde-copy">${esc(L(
        "El registro público no se navega entero. Escribe qué necesitas.",
        "The public registry can't be browsed whole. Type what you need."))}</p>` +
      `<p class="cat-borde-pie">${esc(L("¿Sabes que no existe?", "Know it doesn't exist?"))} ` +
      `<button class="cx-btn cat-construir" data-construir="1">` +
      `${esc(L("Construir un MCP", "Build an MCP"))}</button></p></div>`;

  if (vista.borde === C.BORDE_CAIDO)
    return `<div class="cat-borde cat-borde-rojo" data-borde="caido" role="alert">` +
      `<p class="cat-borde-tit"><span aria-hidden="true">🔴</span> ` +
      `${esc(L("No disponible por ahora", "Not available right now"))}</p>` +
      `<p class="cat-borde-copy">${esc(vista.notice || L(
        "El registro público no contestó. No es que no haya piezas: no pudimos preguntar.",
        "The public registry didn't answer. It's not that there are no pieces: we couldn't ask."))}</p>` +
      `<p class="cat-borde-pie">` +
      `<button class="cx-btn cx-accion cat-reintentar" data-reintentar-busqueda="1">` +
      `${esc(L("Reintentar", "Retry"))}</button>` +
      // EL DATO QUE BAJA EL SUSTO: lo tuyo sigue andando. Sale del conteo real del local,
      // el mismo que pinta el resumen — si no lo hay, no se inventa la frase.
      (conectadas == null ? "" : `<small>${esc(L(
        `Tus ${conectadas} piezas conectadas siguen funcionando.`,
        `Your ${conectadas} connected pieces keep working.`))}</small>`) +
      `</p></div>`;

  // EL CUARTO BORDE · hay piezas, las tapa el filtro. Dice CUÁNTAS hay detrás y ofrece la
  // salida correcta —quitar el filtro—, no «construir un MCP»: lo que se busca ya llegó.
  if (vista.borde === C.BORDE_FILTRO_VACIO)
    return pintarFiltro(vista) +
      `<div class="cat-borde" data-borde="filtro_vacio">` +
      `<p class="cat-borde-tit">${esc(L("0 con ese filtro", "0 with that filter"))}</p>` +
      `<p class="cat-borde-copy">${esc(L(
        `Llegaron ${vista.total} piezas, pero ninguna pide ${nombresDe(vista.filtro)}.`,
        `${vista.total} pieces arrived, but none needs ${nombresDe(vista.filtro)}.`))}</p>` +
      `<p class="cat-borde-pie">` +
      `<button class="cx-btn cx-accion" data-filtro-limpiar="1">` +
      `${esc(L("Quitar el filtro", "Clear the filter"))}</button></p></div>`;

  if (vista.borde === C.BORDE_SIN_RESULTADOS)
    return `<div class="cat-borde" data-borde="sin_resultados">` +
      `<p class="cat-borde-tit">${esc(L("0 encontradas", "0 found"))}</p>` +
      `<p class="cat-borde-copy">${esc(L(
        "El registro respondió bien: no hay ninguna pieza que coincida con",
        "The registry answered fine: no piece matches"))} ` +
      `<b>${esc(vista.consulta)}</b>.</p>` +
      `<p class="cat-borde-pie">` +
      `<button class="cx-btn cx-accion cat-construir" data-construir="1">` +
      `${esc(L("Construir un MCP", "Build an MCP"))}</button>` +
      `<small>${esc(L("o prueba con otra palabra", "or try another word"))}</small></p></div>`;

  // ⚠️ CON FILTRO PUESTO, EL CONTADOR DICE «2 de 4». Decir «2 encontradas» sería cierto y
  // engañoso a la vez: nadie debe creer que el registro devolvió 2 cuando devolvió 4 y hay
  // un chip tapando las otras.
  const cuenta = vista.filtrado
    ? L(`${vista.filas.length} de ${vista.total}`, `${vista.filas.length} of ${vista.total}`)
    : L(`${vista.filas.length} encontradas`, `${vista.filas.length} found`);
  return `<div class="cat-lista-head">` +
    `<b>${esc(L("Del registro público", "From the public registry"))}</b>` +
    `<span class="cx-number"${vista.filtrado ? ' data-filtrado="true"' : ""}>` +
    `${esc(cuenta)}</span>` +
    `<small>${esc(L("ordenadas por confianza", "sorted by confidence"))}</small></div>` +
    pintarFiltro(vista) +
    `<ul class="cat-filas">${vista.filas.map((f) => pintarFila(f,
      { seleccionada: f.id === vista.elegida })).join("")}</ul>` +
    `<p class="cat-pie">${esc(L("¿Ninguna es la que buscas?", "None of these?"))} ` +
    `<button class="cx-btn cat-construir" data-construir="1">` +
    `${esc(L("Construir un MCP", "Build an MCP"))}</button></p>`;
}

/* ══════════════════════════════════════════════════════════════════════════════════════
 * LA FICHA · las CUATRO caras
 * ════════════════════════════════════════════════════════════════════════════════════ */

/** LA FICHA DE UNA PIEZA, con la cara que su veredicto le dio.
 *
 * `crudo` es el manifest ya traído (o `null` si todavía no se pidió). La ficha NO lo pide:
 * pedirlo es un verbo y los verbos son del montaje. */
export function pintarFicha(ficha, { crudo = null, crudoAbierto = false } = {}) {
  const out = [`<div class="cat-ficha" data-pieza="${esc(ficha.id)}"` +
               ` data-cara="${esc(ficha.cara)}">`];

  // ── la cabecera: quién es, y qué dice ser ────────────────────────────────────
  out.push(`<div class="cat-ficha-head">`,
    `<span class="cat-face">${cara(ficha)}</span>`,
    `<div><h3>${esc(ficha.nombre)}`,
    ficha.sello.etiqueta
      ? `<span class="cat-sello${ficha.sello.verificado ? " ok" : ""}">` +
        `${esc(ficha.sello.etiqueta)}</span>` : "",
    `</h3>`,
    ficha.voz ? `<p class="cat-voz">${esc(ficha.voz)}</p>` : "",
    `</div></div>`);

  // ── la cara ROJA: no se puede, y por qué ─────────────────────────────────────
  if (ficha.cara === C.CARA_NO_SE_PUEDE) {
    out.push(`<div class="cat-bloque cat-rojo" role="alert">`,
      `<p class="cat-bloque-tit"><span aria-hidden="true">🔴</span> `,
      `${esc(L("No disponible por ahora", "Not available right now"))}</p>`,
      `<p>${esc(ficha.mensaje || L("No pudimos traerla.", "We couldn't bring it."))}</p>`,
      ficha.comprobadoTs
        ? `<small>${esc(L("Comprobado", "Checked"))} ${esc(cuando(ficha.comprobadoTs))}.</small>`
        : "",
      `</div>`);
    // EL CAMINO. Un impostor tiene una pieza buena detrás; un servicio inexistente tiene
    // la construcción. Ofrecer «construir» ante un impostor mandaría a fabricar algo que
    // ya existe verificado — el peor consejo posible en esa pantalla.
    out.push(`<div class="cat-bloque">`, `<b class="cat-label">${esc(L("El camino", "The way"))}</b>`);
    if (ficha.motivo === C.MOTIVO_IMPOSTOR && ficha.confiable)
      out.push(`<p>${esc(L("Hay una pieza verificada del mismo servicio:",
                           "There's a verified piece for the same service:"))}</p>`,
        `<div class="cat-alternativa">`,
        `<b>${esc(ficha.confiable)}</b>`,
        `<button class="cx-btn cx-accion" data-traer-la-buena="${esc(ficha.confiable)}">`,
        `${esc(L("Traer esta", "Bring this one"))}</button></div>`);
    if (ficha.sePuedeConstruir || ficha.motivo === C.MOTIVO_INEXISTENTE)
      out.push(`<p class="cat-pie">${esc(L("¿No es lo que necesitas?", "Not what you need?"))} `,
        `<button class="cx-btn cat-construir" data-construir="1">`,
        `${esc(L("Construir un MCP", "Build an MCP"))}</button></p>`);
    out.push(`</div>`);
    out.push(pintarDetalleCrudo(ficha, crudo, crudoAbierto));
    return out.join("") + `</div>`;
  }

  // ── la cara del OUTAGE: no pudimos preguntar ─────────────────────────────────
  if (ficha.cara === C.CARA_SIN_REGISTRO) {
    out.push(`<div class="cat-bloque cat-rojo" role="alert">`,
      `<p class="cat-bloque-tit"><span aria-hidden="true">🔴</span> `,
      `${esc(L("No pudimos comprobarla ahora", "We couldn't check it right now"))}</p>`,
      `<p>${esc(ficha.mensaje || L(
        "El registro público no contestó. No es que la pieza esté mal: no pudimos preguntar.",
        "The public registry didn't answer. It's not that the piece is bad: we couldn't ask."))}</p>`,
      `<button class="cx-btn cx-accion" data-revalidar="${esc(ficha.id)}">`,
      `${esc(L("Reintentar", "Retry"))}</button></div>`);
    out.push(pintarDetalleCrudo(ficha, crudo, crudoAbierto));
    return out.join("") + `</div>`;
  }

  // ── la línea medida de la cara CON RESERVAS ──────────────────────────────────
  if (ficha.cara === C.CARA_CON_RESERVAS)
    out.push(`<div class="cat-bloque cat-reserva">`,
      `<b class="cat-label">${esc(L("Qué no pudimos confirmar",
                                    "What we couldn't confirm"))}</b>`,
      `<p>${esc(ficha.mensaje || "")}</p>`,
      // LO MEDIDO, no un adjetivo. `reason` es lo que el resolver midió; si no lo mandó,
      // no se rellena con una frase de relleno: se omite la línea.
      ficha.razon ? `<small>${esc(ficha.razon)}</small>` : "",
      `</div>`);

  // ── qué pide · confianza ─────────────────────────────────────────────────────
  const r = reqDe(ficha);
  out.push(`<div class="cat-dos">`,
    `<div class="cat-caja"><b class="cat-label">${esc(L("Qué pide", "What it needs"))}</b>`,
    `<p class="cat-dato">${esc(r.icono)} ${esc(r.corto)}</p>`,
    `<small>${esc(r.copy)}</small></div>`,
    `<div class="cat-caja"><b class="cat-label">`,
    `${esc(L("Confianza del match", "Match confidence"))}</b>`,
    `<p class="cat-dato">${ficha.confianza == null
      ? esc(L("sin medir", "not measured"))
      : esc(ficha.confianza.toFixed(2)) + barra(ficha.confianza)}</p>`,
    // LA FECHA DE INGESTA, SÓLO SI EXISTE. Su ausencia ES un dato: nunca estuvo en tu local.
    `<small>${esc(ficha.fechaIngesta
      ? L(`Ingerida ${cuando(ficha.fechaIngesta)}.`, `Ingested ${cuando(ficha.fechaIngesta)}.`)
      : L("Aún no ingerida — nunca estuvo en tu local.",
          "Not ingested yet — it was never in your local."))}</small></div></div>`);

  // ── qué avisa · la franja imposible de perder ────────────────────────────────
  out.push(`<div class="cat-bloque cat-aviso-bloque${ficha.aviso.pesa ? " pesa" : ""}">`,
    `<b class="cat-label">${esc(L("Qué avisa", "What it warns"))}</b>`,
    `<p>${esc(avisoTexto(ficha.aviso))}</p></div>`);

  out.push(pintarDetalleCrudo(ficha, crudo, crudoAbierto));

  // ── el botón, y qué va a pasar si lo apretás ─────────────────────────────────
  const conReservas = ficha.cara === C.CARA_CON_RESERVAS;
  out.push(`<div class="cat-cta">`,
    `<button class="cx-btn cx-accion cat-traer" data-traer="${esc(ficha.id)}"`,
    ` data-asi="${conReservas ? "true" : "false"}">`,
    `${esc(conReservas ? L("Traer así", "Bring it anyway") : L("Traer", "Bring it"))}</button>`,
    `<div class="cat-cta-copy">`,
    conReservas
      ? `<p>${esc(L("Entra con este aviso guardado en su ficha, no como un cartel que se cierra.",
                    "It enters with this notice saved in its listing, not as a banner that closes."))}</p>` +
        `<p>${esc(L("Se puede desconectar cuando quieras.",
                    "You can disconnect it whenever you want."))}</p>`
      : (ficha.comprobadoTs
          ? `<p>${esc(L("Comprobado", "Checked"))} ${esc(cuando(ficha.comprobadoTs))}.</p>` : "") +
        // QUÉ VA A PASAR, derivado del requisito. No es una promesa escrita a mano: sale
        // del mismo campo que pinta la celda «Qué pide».
        `<p>${esc(ficha.requisito === "ninguno"
          ? L("No te va a pedir nada: queda lista al llegar.",
              "It won't ask you for anything: it's ready on arrival.")
          : L("Va a pedirte lo suyo; hasta entonces queda en En preparación.",
              "It'll ask for its part; until then it stays in In preparation."))}</p>`,
    `</div></div>`);

  return out.join("") + `</div>`;
}

/** MIENTRAS SE COMPRUEBA · lo único honesto que se puede decir todavía.
 *
 * ⚠️ NO ES UNA FICHA A MEDIAS. La cara de una ficha SALE del veredicto; sin él, cualquier
 * cara que pintáramos sería inventada, y la única disponible («no pudimos comprobarla»)
 * describiría un outage que no ocurrió. Se dice qué está pasando y se espera. */
export function pintarComprobando(fila) {
  return `<div class="cat-ficha" data-pieza="${esc(fila.id)}" data-cara="comprobando">` +
    `<div class="cat-ficha-head"><span class="cat-face">${cara(fila)}</span>` +
    `<div><h3>${esc(fila.nombre)}</h3>` +
    (fila.voz ? `<p class="cat-voz">${esc(fila.voz)}</p>` : "") + `</div></div>` +
    `<div class="cat-bloque"><p>${esc(L(
      "Comprobando esta pieza contra el registro…",
      "Checking this piece against the registry…"))}</p></div></div>`;
}

/** EL [?] DE LA FICHA · el crudo, y el botón de «esto no coincide».
 *
 * ⚠️ SE ABRE SOLO CUANDO NO PODEMOS RESPONDER POR LA PIEZA. Si nadie probó de quién es, no
 * queremos que nadie confíe en nuestro resumen: se abre el manifest entero sin pedirlo. Con
 * sello, va plegado — el resumen alcanza porque hay un pin detrás. */
export function pintarDetalleCrudo(ficha, crudo, abierto) {
  const auto = ficha.crudoAuto;
  const visible = abierto || auto;
  const cabecera = auto
    ? L("Abrimos el crudo solos: sin sello de origen no queremos que confíes en nuestro resumen.",
        "We open the raw manifest ourselves: with no origin seal we don't want you trusting our summary.")
    : L("Manifest crudo · qué comprobamos · confianza · Esto no coincide",
        "Raw manifest · what we checked · confidence · This doesn't match");
  return `<div class="cat-detalle" data-detalle="${esc(ficha.id)}"` +
    ` data-abierto="${visible ? "true" : "false"}">` +
    `<button class="cat-detalle-head" data-crudo="${esc(ficha.id)}"` +
    ` aria-expanded="${visible ? "true" : "false"}">` +
    `<span class="qmark" aria-hidden="true">?</span><span>${esc(cabecera)}</span>` +
    `<span class="cat-chev" aria-hidden="true">${visible ? "⌃" : "›"}</span></button>` +
    (!visible ? "" :
      `<div class="cat-detalle-cuerpo">` +
      (crudo
        ? `<pre class="cat-crudo">${esc(JSON.stringify(crudo, null, 2))}</pre>`
        // FALLO VISIBLE TAMBIÉN ACÁ: si el crudo no llegó, se dice; no se deja un hueco
        // que se lee como «no hay nada que ver».
        : `<p class="cat-crudo-vacio">${esc(L(
            "El manifest todavía no llegó.", "The manifest hasn't arrived yet."))}</p>`) +
      `<div class="cat-nocoincide">` +
      `<button class="cx-btn" data-no-coincide="${esc(ficha.id)}">` +
      `${esc(L("Esto no coincide", "This doesn't match"))}</button>` +
      `<small>${esc(L("Avisanos y lo revisamos: la próxima búsqueda ya lo sabe.",
                      "Tell us and we'll review it: the next search will know."))}</small>` +
      `</div></div>`) +
    `</div>`;
}

/* ══════════════════════════════════════════════════════════════════════════════════════
 * EL VIAJE
 * ════════════════════════════════════════════════════════════════════════════════════ */

const TITULO_PASO = () => ({
  [C.PASO_RESOLVER]:  L("Buscar en el registro", "Look it up in the registry"),
  [C.PASO_COMPROBAR]: L("Comprobar la pieza", "Check the piece"),
  [C.PASO_TRAER]:     L("Traer a tu local", "Bring it into your local"),
});

/** El detalle a la derecha de un paso. Sale del EVENTO que lo cerró, o no sale. */
function detallePaso(paso) {
  const d = paso.detalle;
  if (d == null) {
    if (paso.estado === "probando") return L("en curso", "in progress");
    if (paso.estado === "pendiente") return L("pendiente", "pending");
    return "";
  }
  if (typeof d === "object" && d.herramientas != null)
    return L(`${d.herramientas} herramientas`, `${d.herramientas} tools`);
  return String(d);
}

/** EL VIAJE, pintado · los tres pasos y, si algo falló, DÓNDE.
 *
 * ⚠️ SE DETIENE EN EL PASO CULPABLE Y AHÍ MISMO PONE EL BOTÓN. La causa vive junto al paso
 * que la produjo: separarla —un mensaje abajo de todo— obliga a adivinar a cuál de los tres
 * pertenece. Y los pasos posteriores quedan en «no llegamos acá», que es la verdad. */
export function pintarViaje(estado, { nombre = "", conReservas = false } = {})  {
  const titulos = TITULO_PASO();
  const roto = estado.pasos.find((p) => p.estado === "roto");
  const causa = roto ? causaDe(estado.causa, estado.causaLiteral) : null;
  const hechos = estado.pasos.filter((p) => p.estado === "hecho").length;
  const llego = estado.cerrado && estado.ok;
  const at = (llego && estado.aterrizaje) || null;
  const enEscala = !!(at && at.escala);

  const cabecera = llego
    ? (enEscala
        ? L(`${at ? at.nombre : nombre} quedó En preparación.`,
            `${at ? at.nombre : nombre} is now In preparation.`)
        : L(`${at ? at.nombre : nombre} entró a tu local.`,
            `${at ? at.nombre : nombre} is in your local.`))
    : roto
      ? L(`Se detuvo en ${titulos[roto.id]}`, `It stopped at ${titulos[roto.id]}`)
      : L(`Trayendo ${nombre}`, `Bringing ${nombre}`);

  const filas = estado.pasos.map((p) => {
    const marca = p.estado === "hecho" ? "✓" : p.estado === "roto" ? "✗"
                : p.estado === "probando" ? "◔" : "○";
    // Un paso pendiente DESPUÉS de uno roto no está esperando: no corrió nunca.
    const iRoto = estado.pasos.findIndex((x) => x.estado === "roto");
    const iEste = estado.pasos.findIndex((x) => x.id === p.id);
    const detalle = (iRoto >= 0 && iEste > iRoto)
      ? L("no llegamos aquí", "we didn't get here") : detallePaso(p);
    return `<li class="cat-paso" data-paso="${esc(p.id)}" data-estado="${esc(p.estado)}">` +
      `<span class="cat-paso-marca" aria-hidden="true">${marca}</span>` +
      `<span class="cat-paso-tit">${esc(titulos[p.id] || p.id)}</span>` +
      `<span class="cat-paso-det">${esc(detalle)}</span>` +
      (p.estado === "roto" && causa
        ? `<div class="cat-paso-causa">` +
          `<p>${esc(causa.texto)}` +
          (causa.provisional
            ? ` <em>${esc(L("(estamos afinando este aviso)",
                            "(we're still refining this notice)"))}</em>` : "") +
          `</p>${pintarSalida(causa.accion, estado)}</div>`
        : "") +
      `</li>`;
  });

  return `<div class="cat-viaje" data-cerrado="${estado.cerrado ? "true" : "false"}"` +
    ` data-ok="${estado.ok ? "true" : "false"}" aria-live="polite">` +
    `<div class="cat-viaje-head"><b>${esc(cabecera)}</b>` +
    `<span class="cat-viaje-cuenta">${esc(L(
      `${hechos} de ${estado.pasos.length}`, `${hechos} of ${estado.pasos.length}`))}</span>` +
    // LA X · CERRAR ES DEL USUARIO. Sólo cuando el viaje terminó: mientras corre, la salida
    // es Cancelar, que además dice qué implica. Un aspa a mitad de camino no aclara si
    // cierra la ventana o aborta la traída.
    (estado.cerrado
      ? `<button class="cat-viaje-x" data-cerrar-viaje="1"` +
        ` aria-label="${esc(L("Cerrar", "Close"))}" title="${esc(L("Cerrar", "Close"))}">✕</button>`
      : "") +
    `</div>` +
    (estado.cerrado ? "" : `<p class="cat-viaje-copy">${esc(L(
      "Puedes irte a otra pantalla: seguimos igual y te lo contamos aquí.",
      "You can go to another screen: we keep going and tell you here."))}</p>`) +
    `<ul class="cat-pasos">${filas.join("")}</ul>` +
    (llego ? pintarAterrizaje(at, enEscala) : "") +
    (estado.cerrado ? "" :
      `<div class="cat-viaje-pie">` +
      `<button class="cx-btn cat-cancelar" data-cancelar-viaje="1">` +
      `${esc(L("Cancelar", "Cancel"))}</button>` +
      `<small>${esc(L("Si cancelas no queda nada a medias: la pieza no entra a tu local.",
                      "If you cancel nothing is left half-done: the piece doesn't enter your local."))}` +
      `</small></div>`) +
    `</div>`;
}

/** EL FINAL DEL VIAJE CUANDO SALE BIEN · la simetría que le faltaba al éxito.
 *
 * ⚠️ EL ÉXITO SE CERRABA SOLO Y NO LLEVABA A NINGUNA PARTE. Medido con persona usuaria: la pieza
 * entraba, el panel del viaje desaparecía, quedaba un aviso chico en el catálogo público y
 * **la pieza quedaba invisible hasta buscarla a mano**. Probó y no supo si había entrado.
 *
 * El fallo, en cambio, ya tenía las dos cosas: se queda en pantalla y ofrece su salida. Esa
 * asimetría era el defecto — no un adorno faltante. Acá el éxito recibe lo mismo:
 *
 *   · DÓNDE QUEDÓ, con el nombre de la pieza. «Entró a tu local» y «Quedó En preparación»
 *     son dos desenlaces distintos y se dicen distinto; el segundo además dice QUÉ FALTA,
 *     porque «en preparación» sin el pendiente es un estado sin acción.
 *   · UN CAMINO. El botón NAVEGA a la lista donde la pieza está — y al llegar la pieza
 *     queda SEÑALADA. Llevar a una lista de 40 filas sin decir cuál es la nueva es no
 *     llevar a ningún lado.
 *   · CERRAR ES DEL USUARIO (la ✕ de la cabecera). Nunca solo.
 */
export function pintarAterrizaje(at, enEscala) {
  if (!at) return "";
  const faltan = (at.faltan || []).filter(Boolean);
  const donde = enEscala ? "aduana" : "local";
  const rotulo = enEscala
    ? L("Ver en En preparación", "See it in In preparation")
    : L("Ver en tu local", "See it in your local");
  // QUÉ FALTA, en la lengua de la casa. Sale de `pertenencia().faltan`, que es lo mismo que
  // lee la fila: si acá dijera otra cosa, la pieza tendría dos pendientes distintos.
  const pendiente = !enEscala ? ""
    : faltan.length
      ? L(`Le falta ${faltan.join(", ")}.`, `It needs ${faltan.join(", ")}.`)
      : L("Le falta algo tuyo para quedar lista.", "It needs something from you to be ready.");
  const copy = enEscala
    ? L(`${at.nombre} llegó, pero todavía no puede trabajar. ${pendiente}`,
        `${at.nombre} arrived, but can't work yet. ${pendiente}`)
    : L(`${at.nombre} ya está lista para usar. No pidió nada.`,
        `${at.nombre} is ready to use. It asked for nothing.`);
  return `<div class="cat-aterrizaje" data-escala="${enEscala ? "true" : "false"}"` +
    ` data-pieza="${esc(at.entityId || "")}">` +
    `<p>${esc(copy)}</p>` +
    `<div class="cat-viaje-pie">` +
    `<button class="cx-btn cx-accion" data-ver-pieza="${esc(at.entityId || "")}"` +
    ` data-donde="${donde}">${esc(rotulo)}</button>` +
    `</div></div>`;
}

/** LA SALIDA DE UNA CAUSA · un botón, el que la tabla declaró. Nunca un menú: elegir entre
 *  cuatro opciones le pide decidir a quien no sabe qué pasó. */
/** EL CAMPO DE LLAVE · la única copia de este formulario.
 *
 * Estaba adentro de `pintarSalida` y por eso una superficie nueva no lo podía usar: la de
 * Recomendados (F3) escribió el suyo. Se saca acá para que se LLAME.
 *
 * Con `campos` (de `widget.camposDeCredencial`) pinta uno por campo, respeta `secreto` —un
 * campo que no lo es no va como `password`, que era otra cosa que la copia perdía— y muestra
 * la `forma` esperada. Sin `campos` cae al campo único de siempre, que es lo que el catálogo
 * público usa cuando todavía no leyó la ficha.
 *
 * `link` es el `deep_link`: mandar a alguien a buscar una llave sin decirle dónde es un
 * dead-end, y el dato está declarado en el catálogo. */
export function pintarCampoLlave(campos = null, { link = null, boton = null } = {}) {
  const filas = (campos && campos.length)
    ? campos.map((c) => `<label><span>${esc(c.label || c.key || "")}` +
        (c.forma ? ` <em class="cat-forma">(${esc(c.forma)})</em>` : "") + `</span>` +
        `<input type="${c.secreto === false ? "text" : "password"}"` +
        ` name="${esc(c.key || "cat-llave")}" autocomplete="off"` +
        ` placeholder="${esc(L("tu token…", "your token…"))}"></label>`).join("")
    : `<label><span>${esc(L("Pega tu llave y la probamos en vivo:",
                            "Paste your key and we'll test it live:"))}</span>` +
      `<input type="password" name="cat-llave" autocomplete="off"` +
      ` placeholder="${esc(L("tu token…", "your token…"))}"></label>`;
  return `<div class="cat-llave">` + filas +
    (link ? `<a class="cat-donde" href="${esc(link)}" target="_blank" rel="noopener">` +
            `${esc(L("¿Dónde la consigo?", "Where do I get it?"))}</a>` : "") +
    `<button class="cx-btn cx-accion" data-traer-con-llave="1">` +
    `${esc(boton || L("Traer con mi llave", "Bring it with my key"))}</button></div>`;
}

function pintarSalida(accion, estado) {
  if (accion === "reintentar")
    return `<button class="cx-btn cx-accion" data-reintentar-viaje="1">` +
           `${esc(L("Reintentar", "Retry"))}</button>`;
  if (accion === "traer_asi" && estado.siguiente === "traer_asi")
    // SÓLO SI EL BACKEND LO HABILITÓ. `next:"traer_asi"` es el permiso, y sin él el botón
    // no se ofrece: prometer un camino que el servidor va a rechazar es peor que no darlo.
    return `<button class="cx-btn cx-accion" data-traer-asi="1">` +
           `${esc(L("Traer así", "Bring it anyway"))}</button>`;
  if (accion === "traer_la_buena" && estado.servidor)
    return `<button class="cx-btn cx-accion" data-traer-la-buena="${esc(estado.servidor)}">` +
           `${esc(L("Traer la verificada", "Bring the verified one"))}</button>`;
  if (accion === "llave") return pintarCampoLlave();
  if (accion === "login")
    return `<a class="cx-btn cx-accion" href="Auth.dc.html">` +
           `${esc(L("Entrar a tu cuenta", "Sign in"))}</a>`;
  // `nada` ES UNA SALIDA, y es explícita a propósito. Un dominio que no existe y una pieza
  // que no trae herramientas no se arreglan reintentando: el botón sólo daría a entender
  // que falta paciencia. Que esté escrito la distingue de una acción con un typo, que cae
  // igual en el `return ""` de abajo pero por error.
  if (accion === "nada") return "";
  return "";
}

/** EL AVISO DE LLEGADA · la franja que corona la lista cuando una pieza aterrizó.
 *
 * ⚠️ NO ES UN ESTADO DE LA PIEZA, ES UN ACUSE. Se va al recargar, y la fila queda como
 * cualquier otra: mismo semáforo, misma fecha, mismo [?]. Si esta franja fuera parte de la
 * card, una pieza traída se vería distinta de las demás para siempre — y el adaptador
 * existe justamente para que haya UNA forma de mostrar una pieza. */
export function pintarLlegada({ nombre, escala, pasos }) {
  return `<div class="cat-llegada${escala ? " escala" : ""}" role="status"` +
    ` data-escala="${escala ? "true" : "false"}">` +
    `<span aria-hidden="true">${escala ? "✓" : "✓"}</span>` +
    `<p>${esc(escala
      ? L(`${nombre} llegó a tu local. Le falta algo tuyo para quedar lista — está en En preparación.`,
          `${nombre} arrived in your local. It needs something from you — it's in In preparation.`)
      : L(`${nombre} ya está lista para usar. No pidió nada.`,
          `${nombre} is ready to use. It asked for nothing.`))}</p>` +
    `<small>${esc(L(`${pasos} pasos, todos ✓`, `${pasos} steps, all ✓`))}</small></div>`;
}

/** EL CSS DE LA SECCIÓN · viaja CON la superficie, igual que el del panel.
 *
 * Tokens del sistema con respaldo, para que también se vea bien en una pantalla que no haya
 * cargado `aleph-tokens.css`. Cero bordes y cero relieves: la jerarquía es sombra + radio,
 * como el resto de la casa. */
export const CSS_CATALOGO = `
.cat-buscador{width:100%;border:0;background:var(--paper2,#1b1b1f);color:var(--ink,#f2f2f4);
  border-radius:var(--r-md,12px);padding:14px 18px;outline:none;
  font:300 14px var(--font-ui,system-ui)}
.cat-buscador:focus{background:var(--accent-soft,#2b2540)}
.cat-vista{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;align-items:start}
.cat-vista[data-con-ficha="true"]{grid-template-columns:minmax(0,380px) minmax(0,1fr)}
/* EL FILTRO · los chips son el mismo par icono+nombre que la fila ya usa a la derecha. El
   puesto se distingue por RELLENO, no sólo por color: el estado no puede depender de ver
   bien un tono, y aria-pressed lo dice para quien no ve nada. */
.cat-filtro{display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin:0 0 12px}
.cat-filtro-tit{color:var(--faint,#6f6f78);font:300 11.5px var(--font-ui,system-ui);margin-right:2px}
.cat-chip{display:inline-flex;align-items:center;gap:5px;padding:3px 9px;border-radius:999px;
  border:1px solid var(--line,#e3e3e8);background:transparent;cursor:pointer;
  font:400 12px var(--font-ui,system-ui);color:var(--ink,#1a1a1f)}
.cat-chip:hover{border-color:var(--faint,#6f6f78)}
.cat-chip.on{background:var(--ink,#1a1a1f);border-color:var(--ink,#1a1a1f);color:#fff}
.cat-chip.vacio{opacity:.45}
.cat-chip.vacio.on{opacity:1}
.cat-chip-n{opacity:.6;font-variant-numeric:tabular-nums}
.cat-chip-limpiar{margin-left:4px;padding:3px 4px;border:0;background:transparent;cursor:pointer;
  color:var(--faint,#6f6f78);font:300 11.5px var(--font-ui,system-ui);text-decoration:underline}
.cat-chip-limpiar:hover{color:var(--ink,#1a1a1f)}
/* el contador con filtro puesto se marca: «2 de 4» no puede leerse como «2 encontradas» */
.cx-number[data-filtrado]{background:var(--ink,#1a1a1f);color:#fff}
.cat-lista-head{display:flex;align-items:baseline;gap:9px;margin:0 0 12px}
.cat-lista-head b{font:400 var(--fs-md,14px) var(--font-ui,system-ui)}
.cat-lista-head small{color:var(--faint,#6f6f78);font:300 11.5px var(--font-ui,system-ui)}
.cat-filas{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px}
.cat-fila{background:var(--paper,#242429);border-radius:var(--r-md,12px);
  box-shadow:var(--sh-1,0 1px 2px rgba(0,0,0,.2));overflow:hidden}
.cat-fila.on{background:var(--accent-soft,#2b2540)}
.cat-fila-btn{display:grid;grid-template-columns:34px minmax(0,1fr) 132px 96px 14px;
  align-items:center;gap:0 13px;width:100%;padding:13px 16px;border:0;background:transparent;
  color:inherit;text-align:left;cursor:pointer;font:inherit}
.cat-face{display:flex;align-items:center;justify-content:center}
.cat-copy{min-width:0;display:flex;flex-direction:column;gap:3px}
.cat-nombre{display:flex;align-items:center;gap:8px;min-width:0;
  font:400 var(--fs-md,14px) var(--font-ui,system-ui)}
.cat-sello{flex:none;border-radius:var(--r-full,999px);padding:2px 9px;
  background:var(--paper2,#1b1b1f);color:var(--muted,#9a9aa2);
  font:300 10.5px var(--font-ui,system-ui);white-space:nowrap}
.cat-sello.ok{background:var(--green-bg,#1e3326);color:var(--green,#6ee7a8)}
.cat-voz{color:var(--muted,#9a9aa2);font:300 12.5px var(--font-ui,system-ui);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cat-req{color:var(--muted,#9a9aa2);font:300 12px var(--font-ui,system-ui);white-space:nowrap}
.cat-conf{display:flex;flex-direction:column;align-items:flex-end;gap:3px}
.cat-conf b{font:400 15px var(--font-ui,system-ui)}
.cat-conf small{color:var(--faint,#6f6f78);font:300 10px var(--font-ui,system-ui)}
.cat-barra{display:flex;gap:3px}
.cat-barra i{width:14px;height:3px;border-radius:2px;background:var(--paper2,#1b1b1f)}
.cat-barra i.on{background:var(--accent-deep,#a78bfa)}
.cat-chev{color:var(--faint,#6f6f78)}
/* LA FRANJA DEL AVISO · ancho completo y sin click de por medio: es lo único que puede
   cambiar una decisión ANTES de traer. */
.cat-aviso{margin:0;padding:9px 16px;background:var(--paper2,#1b1b1f);
  color:var(--muted,#9a9aa2);font:300 12px/1.45 var(--font-ui,system-ui)}
.cat-aviso.pesa{background:var(--amber-bg,#3a2f1c);color:var(--amber,#e6b566)}
.cat-ficha{display:flex;flex-direction:column;gap:12px;padding:18px 20px;
  background:var(--paper,#242429);border-radius:var(--r-md,12px);box-shadow:var(--sh-1,none)}
.cat-ficha-head{display:flex;align-items:flex-start;gap:13px}
.cat-ficha-head h3{display:flex;align-items:center;gap:9px;margin:0;
  font:400 var(--fs-lg,17px) var(--font-ui,system-ui);letter-spacing:-.01em}
.cat-ficha-head p{margin:5px 0 0}
.cat-dos{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.cat-caja,.cat-bloque{padding:12px 14px;background:var(--paper2,#1b1b1f);
  border-radius:var(--r-md,12px)}
.cat-label{display:block;color:var(--faint,#6f6f78);
  font:300 11px var(--font-ui,system-ui);margin-bottom:5px}
.cat-dato{display:flex;align-items:center;gap:9px;margin:0;
  font:400 15px var(--font-ui,system-ui)}
.cat-caja small,.cat-bloque small{display:block;margin-top:5px;color:var(--faint,#6f6f78);
  font:300 11.5px/1.5 var(--font-ui,system-ui)}
.cat-bloque p{margin:0;font:300 13px/1.5 var(--font-ui,system-ui)}
.cat-aviso-bloque.pesa{background:var(--amber-bg,#3a2f1c)}
.cat-aviso-bloque.pesa p,.cat-aviso-bloque.pesa .cat-label{color:var(--amber,#e6b566)}
.cat-reserva{background:var(--accent-soft,#2b2540)}
.cat-rojo{background:var(--red-bg,#3a1f22)}
.cat-rojo p,.cat-rojo .cat-bloque-tit{color:var(--red,#f2a0a4)}
.cat-bloque-tit{display:flex;align-items:center;gap:8px;margin:0 0 6px;
  font:400 14px var(--font-ui,system-ui)}
.cat-alternativa{display:flex;align-items:center;justify-content:space-between;gap:12px;
  margin-top:9px;padding:11px 13px;background:var(--paper,#242429);border-radius:var(--r-md,12px)}
.cat-detalle{background:var(--paper2,#1b1b1f);border-radius:var(--r-md,12px);overflow:hidden}
.cat-detalle-head{display:grid;grid-template-columns:22px minmax(0,1fr) 14px;align-items:center;
  gap:10px;width:100%;padding:12px 14px;border:0;background:transparent;color:var(--muted,#9a9aa2);
  text-align:left;cursor:pointer;font:300 12.5px var(--font-ui,system-ui)}
.cat-detalle-head .qmark{width:22px;height:22px;border-radius:var(--r-full,999px);
  background:var(--paper,#242429);display:flex;align-items:center;justify-content:center}
.cat-detalle-cuerpo{padding:0 14px 14px}
.cat-crudo{margin:0;padding:12px 14px;background:var(--paper,#242429);
  border-radius:var(--r-md,12px);overflow-x:auto;color:var(--ink,#f2f2f4);
  font:300 11.5px/1.6 var(--font-mono,ui-monospace,monospace)}
.cat-crudo-vacio{margin:0;color:var(--faint,#6f6f78);font:300 12px var(--font-ui,system-ui)}
.cat-nocoincide{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:10px}
.cat-nocoincide small{color:var(--faint,#6f6f78);font:300 11.5px var(--font-ui,system-ui)}
.cat-cta{display:flex;align-items:flex-start;gap:14px;flex-wrap:wrap}
.cat-cta-copy p{margin:0;color:var(--muted,#9a9aa2);font:300 12.5px/1.5 var(--font-ui,system-ui)}
.cat-traer{padding:13px 26px;font:400 13px var(--font-ui,system-ui)}
/* EL VIAJE */
.cat-viaje{display:flex;flex-direction:column;gap:12px;padding:18px 20px;
  background:var(--paper,#242429);border-radius:var(--r-md,12px)}
.cat-viaje-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px}
.cat-viaje-head b{font:400 var(--fs-lg,17px) var(--font-ui,system-ui)}
.cat-viaje-cuenta{color:var(--faint,#6f6f78);font:300 11.5px var(--font-ui,system-ui)}
.cat-viaje-copy{margin:0;color:var(--muted,#9a9aa2);font:300 12.5px var(--font-ui,system-ui)}
.cat-pasos{list-style:none;margin:0;padding:14px;background:var(--paper2,#1b1b1f);
  border-radius:var(--r-md,12px);display:flex;flex-direction:column;gap:2px}
.cat-paso{display:grid;grid-template-columns:20px minmax(0,1fr) auto;align-items:center;
  gap:10px;padding:9px 10px;border-radius:var(--r-sm,8px);
  font:300 13px var(--font-ui,system-ui);color:var(--muted,#9a9aa2)}
.cat-paso[data-estado="hecho"] .cat-paso-marca{color:var(--green,#6ee7a8)}
.cat-paso[data-estado="hecho"] .cat-paso-tit{color:var(--ink,#f2f2f4)}
.cat-paso[data-estado="probando"]{background:var(--accent-soft,#2b2540)}
.cat-paso[data-estado="probando"] .cat-paso-tit,
.cat-paso[data-estado="probando"] .cat-paso-det{color:var(--accent-deep,#a78bfa)}
.cat-paso[data-estado="roto"]{background:var(--red-bg,#3a1f22)}
.cat-paso[data-estado="roto"] .cat-paso-marca,
.cat-paso[data-estado="roto"] .cat-paso-tit{color:var(--red,#f2a0a4)}
.cat-paso-det{color:var(--faint,#6f6f78);font:300 11.5px var(--font-ui,system-ui);
  white-space:nowrap}
.cat-paso-causa{grid-column:1/-1;display:flex;flex-direction:column;gap:9px;
  margin-top:7px;padding-left:30px}
.cat-paso-causa p{margin:0;color:var(--red,#f2a0a4);font:300 12.5px/1.5 var(--font-ui,system-ui)}
.cat-paso-causa em{color:var(--faint,#6f6f78);font-style:italic}
.cat-llave{display:flex;flex-wrap:wrap;align-items:flex-end;gap:9px}
.cat-llave label{display:flex;flex-direction:column;gap:4px;flex:1 1 200px;
  color:var(--muted,#9a9aa2);font:300 11px var(--font-ui,system-ui)}
.cat-llave input{border:0;background:var(--paper,#242429);color:var(--ink,#f2f2f4);
  border-radius:var(--r-sm,8px);padding:10px 12px;outline:none;
  font:300 13px var(--font-ui,system-ui)}
.cat-viaje-pie{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.cat-viaje-pie small{color:var(--faint,#6f6f78);font:300 11.5px var(--font-ui,system-ui)}
/* LA ✕ · cerrar es del usuario. Área táctil real (no un glifo de 11px), y sólo aparece con
   el viaje cerrado: mientras corre, la salida es Cancelar. */
.cat-viaje-x{margin-left:4px;border:0;background:transparent;cursor:pointer;line-height:1;
  padding:4px 7px;border-radius:var(--r-sm,8px);color:var(--faint,#6f6f78);
  font:300 15px var(--font-ui,system-ui)}
.cat-viaje-x:hover{background:var(--accent-soft,#2b2540);color:var(--ink,#f2f2f4)}
/* EL ATERRIZAJE · el desenlace, separado de los pasos por una línea: los pasos son lo que
   pasó, esto es dónde quedó la pieza. Sin borde de color propio — el estado ya lo dice el
   texto, y un verde/ámbar aquí competiría con el semáforo de la fila. */
.cat-aterrizaje{display:flex;flex-direction:column;gap:10px;padding-top:12px;
  border-top:1px solid var(--line,#2a2a30)}
.cat-aterrizaje p{margin:0;font:400 13.5px var(--font-ui,system-ui);color:var(--ink,#f2f2f4)}
.cat-aterrizaje[data-escala="true"] p{color:var(--muted,#9a9aa2)}
/* LA PIEZA SEÑALADA · un acuse, no un estado. Se va sola a los 2,6 s y la fila vuelve a ser
   una fila: una marca permanente la haría distinta de las 41 para siempre. */
.cx-fila[data-senalada="true"],li[data-senalada="true"]{
  outline:2px solid var(--accent,#7c5cff);outline-offset:2px;
  transition:outline-color .4s ease}
@media (prefers-reduced-motion:reduce){
  .cx-fila[data-senalada="true"],li[data-senalada="true"]{transition:none}}
/* LOS BORDES · tres, y se ven distintos a propósito */
.cat-borde{padding:26px 24px;background:var(--paper2,#1b1b1f);border-radius:var(--r-md,12px)}
.cat-borde-rojo{background:var(--red-bg,#3a1f22)}
.cat-borde-rojo .cat-borde-copy,.cat-borde-rojo .cat-borde-tit{color:var(--red,#f2a0a4)}
.cat-borde-tit{display:flex;align-items:center;gap:8px;margin:0 0 8px;
  font:400 15px var(--font-ui,system-ui)}
.cat-borde-copy{margin:0;color:var(--muted,#9a9aa2);font:300 13px/1.55 var(--font-ui,system-ui)}
.cat-borde-pie{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:16px 0 0}
.cat-borde-pie small{color:var(--faint,#6f6f78);font:300 12px var(--font-ui,system-ui)}
.cat-pie{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:14px 0 0;
  color:var(--faint,#6f6f78);font:300 12.5px var(--font-ui,system-ui)}
/* LA LLEGADA · un acuse, no un estado. Se va al recargar. */
.cat-llegada{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:14px 18px;
  margin-bottom:16px;background:var(--green-bg,#1e3326);border-radius:var(--r-md,12px)}
.cat-llegada.escala{background:var(--accent-soft,#2b2540)}
.cat-llegada p{margin:0;flex:1 1 300px;font:300 13px var(--font-ui,system-ui)}
.cat-llegada small{color:var(--faint,#6f6f78);font:300 11.5px var(--font-ui,system-ui)}
@media(max-width:900px){
  .cat-vista[data-con-ficha="true"]{grid-template-columns:minmax(0,1fr)}
  .cat-fila-btn{grid-template-columns:34px minmax(0,1fr) 14px;gap:6px 13px}
  .cat-req,.cat-conf{grid-column:2;align-items:flex-start}
  .cat-conf{flex-direction:row;align-items:baseline;gap:7px}
  .cat-dos{grid-template-columns:1fr}
}
`;
