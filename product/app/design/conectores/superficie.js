/* superficie.js — LA ÚNICA SUPERFICIE DE CONECTORES. El adaptador, pintado.
 *
 * Reemplaza a la card vieja de la lista, al modal «Arreglar X» y al wizard «Conectar X».
 * No hay tres formas de mostrar una pieza: hay UNA, y sale entera de `widget.derivar()`.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * POR QUÉ ESTAS FUNCIONES DEVUELVEN STRINGS Y NO TOCAN EL DOM.
 *
 * Porque así la vara prueba LO QUE EL USUARIO VE, no una función suelta. `pintarCard()` y
 * `pintarPanel()` son puras: mismo modelo, mismo HTML, en node y en el browser. La vara
 * las llama con las 42 piezas reales y busca frases prohibidas en la salida — que es
 * exactamente la superficie montada, sin necesidad de un navegador.
 *
 * La alternativa —render imperativo contra el DOM— obliga a levantar un browser para
 * verificar una frase, y una vara que necesita browser se corre una vez y se abandona.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * LA LEY, EN UNA LÍNEA: acá NO se decide nada. El estado viene del registro+vault, el botón
 * de repair, los pasos de la ficha y el belt, la evidencia de verify. Si esta superficie
 * tuviera un `if` por conector o un texto propio de una pieza, sería la cuarta forma de
 * mostrar lo mismo — y volveríamos al parcheo card por card que esto vino a matar.
 */
import * as W from "./widget.js";

const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** El idioma. Se conserva de la superficie vieja a propósito: perderlo sería una regresión
 *  silenciosa para quien usa Aleph en inglés, y «la pantalla se reescribió» no es una razón
 *  para que un producto bilingüe deje de serlo. */
function lang() {
  try {
    return String(typeof window !== "undefined" && window.AlephI18n && AlephI18n.lang
      ? AlephI18n.lang() : "es").startsWith("en") ? "en" : "es";
  } catch (_) { return "es"; }
}
const L = (es, en) => (lang() === "en" ? en : es);

/** El rótulo del estado. Son TRES y ninguno confiesa nada.
 *
 * `esperando` no tiene rótulo propio a propósito: lo dice el PASO, que es más específico y
 * más accionable («Falta tu llave» le sirve a alguien; «Esperando» no le sirve a nadie). */
const ROTULO = () => ({
  conectado: L("Conectado", "Connected"),
  esperando: null,
  bloqueado: L("No disponible por ahora", "Not available right now"),
});

/** Lo que pide cada tipo de paso, en palabras del usuario. No hay una entrada por
 *  conector: hay una por TIPO, que es lo que hace que sirva para 17.000. */
const PIDE = () => ({
  [W.PASO_LLAVE]: L("Falta tu llave", "Your key is missing"),
  [W.PASO_OAUTH]: L("Falta autorizar tu cuenta", "You still need to authorize"),
  [W.PASO_INSTALAR]: L("Falta instalarlo en tu equipo", "Install it on your machine"),
  [W.PASO_ESPERAR]: L("Midiendo", "Measuring"),
  // ⚠️ MATICES QUE UN PASO PUEDE PEDIR POR NOMBRE, cuando el rótulo del tipo es cierto pero
  // pierde el dato que ahorra un viaje. Siguen siendo por TIPO DE SITUACIÓN, jamás por
  // conector: los declara una REGLA de la tabla de conocimiento, no una pieza.
  //
  // «La sesión venció» ≠ «tu llave fue rechazada». La primera se arregla reconectando; la
  // segunda manda a conseguir otra credencial. Decirle «rechazada» a un token que caducó lo
  // manda a buscar una llave que ya tiene.
  sesion_vencida: L("La sesión venció · reconecta", "Session expired · reconnect"),
});

/** Qué pide un paso, con su matiz si lo declara. */
const pideDe = (pide, paso) => (paso && pide[paso.pide]) || (paso && pide[paso.tipo]) || null;

/** La cara del servicio. La pinta Brandface —logo curado o iniciales deterministas— igual
 *  que antes: los logos de marca no se tocan. Sin Brandface, iniciales. */
function cara(modelo) {
  const nombre = modelo.nombre || modelo.entityId;
  try {
    if (typeof window !== "undefined" && window.AlephBrand)
      return AlephBrand.faceHTML({ connector: modelo.entityId, server: null,
                                   name: modelo.entityId, label: nombre },
                                 { size: 34, cls: "cx-logo" });
  } catch (_) { /* la cara nunca puede tumbar la fila */ }
  return `<span class="cx-logo-fallback" aria-hidden="true">` +
         `${esc(String(nombre).slice(0, 2).toUpperCase())}</span>`;
}

/** LA CARD · una fila, SIEMPRE con las mismas seis celdas.
 *
 * ⚠️ LA FILA ES UN GRID FIJO, NO UNA SUCESIÓN DE COSAS. Antes cada celda aparecía o no
 * según el estado, y el resultado era una lista desordenada: los estados empezaban en una x
 * distinta por fila, las fechas bailaban, y una fila con botón era más alta que una sin.
 * Ahora las seis celdas SIEMPRE se emiten —vacías si no hay nada que poner— y el ancho lo
 * fija el CSS. Es una regla de layout, no un ajuste card por card: por eso vale igual para
 * las 42 de hoy y para las 17.000 del catálogo.
 *
 *   [cara] [nombre] [estado] [fecha] [acción] [?]
 */
export function pintarCard(modelo) {
  const v = modelo.veredicto;
  const pide = PIDE(), rotulo = ROTULO();
  const paso = (modelo.pasos || []).find((p) => p.territorio === W.USUARIO)
            || (modelo.pasos || [])[0] || null;

  // LA LÁPIDA MANDA SOBRE LA MEDICIÓN. Una pieza que el usuario desconectó NO va a correr:
  // el restaurador la saltea. Pintarla verde sería mentir sobre lo único que importa —si va
  // a estar cuando el agente la use— así que va ⚪ y ofrece volver a conectarla.
  const apagada = !!modelo.apagada;
  const _p0 = modelo.pertenencia || {};
  const luz = apagada ? "⚪"
            // Una regresión y una llave vencida son del local y hoy no sirven: ámbar, que
            // es exactamente lo que significan — «tuyo, y con algo que hacer».
            : (_p0.regresion || _p0.rotar) ? "🟡"
            : v.estado === "conectado" ? "✅" : v.estado === "esperando" ? "🟡" : "🔴";
  const p = modelo.pertenencia || {};
  const titulo = apagada ? L("Desconectado", "Disconnected")
               // LA CAUSA OPERATIVA CON NOMBRE. Una regresión no es «no disponible por
               // ahora»: es que el programa que estaba ya no está, y decirlo es la mitad
               // que convierte el botón en algo que se entiende.
               : p.regresion ? L("Ya no está instalado", "No longer installed")
               : p.rotar ? L("La llave dejó de servir", "Your key stopped working")
               : v.estado === "esperando" && paso ? pideDe(pide, paso)
               : rotulo[v.estado];

  const partes = [
    `<li class="cx-card ds-card ds-item" data-entity="${esc(modelo.entityId)}"`,
    ` data-estado="${esc(v.estado)}" data-bloqueo="${esc(v.bloqueo)}"`,
    ` data-apagada="${apagada ? "true" : "false"}">`,
    `<span class="cx-face">${cara(modelo)}</span>`,
    `<span class="cx-nombre">${esc(modelo.nombre || modelo.entityId)}</span>`,
    `<span class="cx-estado"><span class="cx-luz" aria-hidden="true">${luz}</span>`,
    `<b>${esc(titulo)}</b></span>`,
    // LA FECHA, SIEMPRE Y EN SU PROPIA COLUMNA. Ver `fecha()`: nunca queda vacía.
    `<span class="cx-cuando">${esc(fecha(modelo))}</span>`,
    `<span class="cx-actions ds-actions">`,
  ];

  const local = !modelo.pertenencia || modelo.pertenencia.local;

  if (apagada) {
    partes.push(`<button class="cx-btn cx-reconectar" data-reconectar="${esc(modelo.entityId)}">`,
                `${esc(L("Conectar", "Connect"))}</button>`);
  } else if (local && (modelo.pertenencia || {}).regresion) {
    // UNA REGRESIÓN: la pieza ANDUVO y hoy le falta su programa. Se queda en el local —el
    // yo-yo está prohibido— y su camino es el MISMO ladrillo de la aduana, pintado inline
    // bajo este botón. Jamás [Reintentar] a secas: reintentar no vuelve a instalar nada, y
    // ofrecerlo sería prometer algo que el click no puede cumplir.
    partes.push(`<button class="cx-btn cx-accion" data-accion="abrir"`,
                ` data-entity="${esc(modelo.entityId)}">`,
                `${esc(L("Reinstalar", "Reinstall"))}</button>`);
  } else if (local && (modelo.pertenencia || {}).rotar) {
    // LA LLAVE ESTÁ PERO NO SIRVE. Es la única falla operativa que NO se arregla
    // reintentando —lo que hay que cambiar es la credencial— y por eso tiene su propio
    // botón. La pieza NO sale del local: nunca dejó de estar completa.
    partes.push(`<button class="cx-btn cx-rotar" data-rotar="${esc(modelo.entityId)}">`,
                `${esc(L("Rotar llave", "Rotate key"))}</button>`);
  } else if (v.estado === "bloqueado" && local) {
    // ══ EL ESTADO 🔴 (persona usuaria, sellado 2026-08-04) ══════════════════════════════════════
    //
    //   «No disponible por ahora» + UN solo botón: [Reintentar conexión]. Nada más.
    //   El botón relanza el ciclo completo —repair con todas sus armas— y la card se
    //   repinta con el resultado real. Cero causas técnicas visibles, cero menús.
    //
    // ⚠️ Y EXIGE SER DEL LOCAL (`&& local`). [Reintentar] sobre una pieza que todavía no
    // tiene su llave o su programa es TEATRO: reintentar no puede cambiar el resultado, y
    // ofrecerlo le hace perder el tiempo a alguien con la promesa de que algo va a pasar.
    // Acta §3: «[Reintentar] solo aparece donde reintentar puede cambiar el resultado».
    // Las no-completas no muestran botón acá — su camino está en la aduana.
    //
    // ⚠️ Y POR ESO ESTA RAMA VA **ANTES** QUE EL BOTÓN DE REPAIR. En rojo, repair puede
    // ofrecer [Ver error], [Instalarlo], [Ver planes]… — un menú distinto por causa, que es
    // exactamente lo que se prohíbe: le hace elegir a alguien que no sabe qué pasó, y cada
    // opción le cuenta un pedazo de nuestro problema. Lo que sí puede elegir es volver a
    // intentar; el resto —qué falló y qué se intentó— vive en el [?].
    partes.push(`<button class="cx-btn cx-reintentar" data-reintentar="${esc(modelo.entityId)}">`,
                `${esc(L("Reintentar conexión", "Retry connection"))}</button>`);
  } else if (local && modelo.boton && modelo.boton.accion &&
             modelo.boton.accion !== "no_disponible") {
    // EL BOTÓN SALE DE REPAIR. Si no hay, no se inventa uno: hay estados sin acción y
    // decirlo es más honesto que ofrecer un click que no lleva a nada.
    partes.push(
      `<button class="cx-btn cx-accion" data-accion="${esc(modelo.boton.accion)}"`,
      ` data-entity="${esc(modelo.entityId)}">`,
      `${esc(lang() === "en" ? modelo.boton.en : modelo.boton.es)}</button>`);
  } else if (local && (modelo.pasos || []).some((p) => p.territorio === W.USUARIO)) {
    // Hay algo del usuario y repair no dio botón: la puerta la abre el panel, que es donde
    // vive el trámite. Sin esto una pieza con un paso pendiente quedaría sin entrada.
    partes.push(`<button class="cx-btn cx-accion" data-accion="abrir"`,
                ` data-entity="${esc(modelo.entityId)}">`,
                `${esc(L("Resolver", "Resolve"))}</button>`);
  }
  partes.push(`</span>`);
  // EL [?] · la evidencia técnica vive acá y sólo acá. Celda propia: es la última columna
  // fija, así el `?` de todas las filas cae en la misma x aunque una no tenga botón.
  partes.push(`<button class="cx-detalle qmark" data-detalle="${esc(modelo.entityId)}"`,
              ` aria-label="${esc(L("Ver evidencia técnica", "See technical evidence"))}">?</button>`);
  // EL PANEL VIVE ADENTRO DE LA FILA, plegado. El trámite ocurre DONDE EL USUARIO ESTÁ: no
  // hay modal que tape la lista ni pantalla a la que navegar y de la que volver.
  partes.push(`<div class="cx-panel-host" data-panel="${esc(modelo.entityId)}" hidden></div>`);
  partes.push(`</li>`);
  return partes.join("");
}

/** LA FECHA DE UN VEREDICTO. **Nunca vacía.**
 *
 * ⚠️ UN VEREDICTO SIN FECHA ES AFIRMAR DE MEMORIA, y está prohibido (persona usuaria, sellado). El
 * caso que lo mostró: una entidad residual salía con su estado y sin una sola pista de
 * cuándo se había mirado — indistinguible de una medida hace un minuto.
 *
 * La celda vacía era el bug, no la fecha faltante: dejaba pasar una afirmación sin su
 * cuándo. Cuando no hay medición la respuesta honesta no es el silencio, es **«sin medir»**
 * — que ES el cuándo: nunca.
 */
function fecha(modelo) {
  const ts = modelo && modelo.header && modelo.header.ts;
  const t = ts == null ? NaN : Date.parse(String(ts));
  if (!Number.isFinite(t)) return L("sin medir", "not measured");
  try {
    return new Intl.DateTimeFormat(lang() === "en" ? "en" : "es",
      { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(t));
  } catch (_) { return String(ts); }
}

/** EL AVISO AL TRAER · una sola vez, dos lugares.
 *
 * ⚠️ [OBRA 6b · #5] ESTABA ESCRITO Y NO SE PODÍA VER, y eso es un bug con nombre propio en
 * esta casa. La reserva se persiste, viaja en el modelo y tenía su HTML — pero sólo dentro
 * de `pintarPanel`, y a ese panel se llega SÓLO por los botones condicionales de la card
 * (`data-accion`, `data-rotar`…), que una pieza sana y conectada NO emite. Medido en la
 * app instalada: la pieza traída con reserva no tenía un solo click que la mostrara. Es
 * exactamente el bug que ya pagamos con `[Desconectar]` y `[Rotar llave]`.
 *
 * Ahora vive también en el detalle del `[?]`, que SÍ está en todas las cards, siempre. La
 * función es una sola para que las dos superficies no puedan decir cosas distintas del
 * mismo aviso. Devuelve "" cuando no hay reserva: no es un caso especial, es la mayoría. */
export function bloqueReserva(modelo) {
  const r = (modelo || {}).reserva;
  if (!r) return "";
  function copy(text) {
    // Translate only our known import notices; unknown external/user text stays intact.
    return L(text, String(text || "")
      .replaceAll("No se pudo confirmar la identidad del namespace que publicó esta pieza.", "Could not verify the identity of the namespace that published this component.")
      .replaceAll("El manifest no declara herramientas; sus consecuencias se sabrán al conectar.", "The manifest declares no tools; their effects will be known after connection.")
      .replaceAll("Señal del matcher:", "Matcher score:"));
  }
  return `<div class="cx-reserva" data-reserva="${esc(modelo.entityId)}">` +
         `<b>${esc(L("Aviso al traer", "Import notice"))}</b>` +
         `<p data-no-tm>${esc(copy(r.texto_1linea || ""))}</p>` +
         (r.detalle ? `<small data-no-tm>${esc(copy(r.detalle))}</small>` : "") +
         `</div>`;
}

/** EL PANEL · lo que antes eran el wizard y el modal. Los pasos DERIVADOS, en orden. */
export function pintarPanel(modelo) {
  const v = modelo.veredicto;
  const pide = PIDE(), rotulo = ROTULO();
  const out = [`<div class="cx-panel" data-entity="${esc(modelo.entityId)}">`];

  out.push(bloqueReserva(modelo));

  for (const paso of modelo.pasos || []) {
    // Un paso que es NUESTRO no se le muestra al usuario: no tiene nada que hacer con él.
    // Va al [?] con su nombre de bug, que es donde sirve para arreglarlo.
    if (paso.territorio === W.NUESTRO) continue;

    if (paso.tipo === W.PASO_LLAVE) {
      out.push(`<div class="cx-paso" data-paso="llave">`);
      out.push(`<p>${esc(pideDe(pide, paso))}</p>`);
      // EL CAMPO, INLINE. No manda a otra pantalla: el trámite ocurre donde el usuario está.
      for (const campo of paso.campos || []) {
        out.push(`<label>${esc(campo.label || campo.key)}`,
                 `<input type="${campo.secreto ? "password" : "text"}"`,
                 ` name="${esc(campo.key)}" autocomplete="off"`,
                 // LA FORMA ESPERADA, si el catálogo la declara. Pegar la llave de otro
                 // servicio y que te digan «no sirve» cuesta una tarde; mostrar el formato
                 // antes es gratis. Y sale de la ficha: acá no se inventa ningún patrón.
                 campo.forma ? ` placeholder="${esc(campo.forma)}"` : "",
                 `></label>`);
      }
      // DÓNDE CONSEGUIRLA, si el catálogo lo declara. Si no lo declara, no se inventa un
      // link: se omite la línea, y la ficha queda marcada en el censo.
      if (paso.link)
        out.push(`<a class="cx-link" href="${esc(paso.link)}" target="_blank" rel="noopener">`,
                 `${esc(L("Conseguir la llave", "Get your key"))}</a>`);
      out.push(`<button class="cx-btn cx-guardar" data-entity="${esc(modelo.entityId)}">`,
               `${esc(L("Guardar y probar", "Save and test"))}</button>`);
      out.push(`</div>`);
    } else if (paso.tipo === W.PASO_OAUTH) {
      out.push(`<div class="cx-paso" data-paso="oauth">`,
               `<p>${esc(pideDe(pide, paso))}</p>`);
      // LOS SCOPES QUE FALTAN, cuando la regla los pudo nombrar. Decirle QUÉ va a autorizar
      // antes de mandarlo al proveedor es la diferencia entre un consentimiento y un salto
      // de fe — y sale de la ficha, no de un texto escrito acá.
      if ((paso.scopes_faltantes || []).length)
        out.push(`<ul class="cx-scopes">`,
                 paso.scopes_faltantes.map((s) => `<li>${esc(s)}</li>`).join(""),
                 `</ul>`);
      out.push(`<button class="cx-btn cx-autorizar" data-entity="${esc(modelo.entityId)}">`,
               `${esc(paso.reconectar ? L("Volver a conectar", "Reconnect")
                                      : L("Conectar", "Connect"))}</button></div>`);
    } else if (paso.tipo === W.PASO_INSTALAR) {
      out.push(`<div class="cx-paso" data-paso="instalar">`,
               `<p>${esc(paso.que || pideDe(pide, paso))}</p>`);
      if (paso.link)
        out.push(`<a class="cx-link" href="${esc(paso.link)}" target="_blank" rel="noopener">`,
                 `${esc(L("Descargarlo", "Download it"))}</a>`);
      out.push(`<button class="cx-btn cx-verificar" data-entity="${esc(modelo.entityId)}">`,
               `${esc(paso.rotulo || L("Ya lo instalé · verificar", "I installed it · verify"))}`,
               `</button></div>`);
    } else if (paso.tipo === W.PASO_ESPERAR) {
      // NO ES UN PASO DEL USUARIO: es un aviso de que el sistema trabaja. Sin botón.
      out.push(`<div class="cx-paso" data-paso="midiendo">`,
               `<p>${esc(pide[W.PASO_ESPERAR])}</p></div>`);
    }
  }

  // Sin ningún paso del usuario y sin conexión: la tercera salida de la ley.
  const hayPasoDeUsuario = (modelo.pasos || []).some((p) => p.territorio === W.USUARIO);
  if (!hayPasoDeUsuario && v.estado === "bloqueado")
    out.push(`<div class="cx-paso" data-paso="no_disponible">`,
             `<p>${esc(rotulo.bloqueado)}</p></div>`);

  // EL HUECO DEL CHECKLIST VIVO. Se rellena desde el montaje cuando corre una reconexión;
  // vacío no ocupa nada.
  out.push(`<div class="cx-checklist-host" data-checklist="${esc(modelo.entityId)}"></div>`);

  out.push(`</div>`);
  return out.join("");
}

/** EL [?] · TODA la verdad técnica, y sólo acá. Es donde vive el escrutinio.
 *
 * La ley de fondo: estar en el catálogo local es haber pasado por los 12 verbos. El verde
 * sin evidencia no existe — así que este panel siempre dice QUÉ verbo midió, CUÁNDO y QUÉ
 * devolvió. Y si la pieza está trabada por razón nuestra, el nombre del bug va acá, no en
 * la card.
 */
export function pintarDetalle(modelo) {
  const e = modelo.evidencia || {};
  const v = modelo.veredicto;
  const k = modelo.conocimiento || {};

  // ⚠️ LAS ACCIONES OPERATIVAS VIVEN ACÁ, Y ACÁ ES EL LUGAR CORRECTO — el acta lo dice con
  // esas palabras: «[Desconectar] SIEMPRE disponible en el detalle».
  //
  // Y resuelve el problema que las tenía inalcanzables. Estaban en `pintarPanel`, que sólo
  // se abre desde el botón de repair o desde un paso pendiente: una pieza SANA no tiene
  // ninguno de los dos, así que existían en el código, viajaban en el bundle, y ningún
  // click de la app instalada llegaba a ellas.
  //
  // El [?] SÍ está en todas las cards, siempre, en su columna fija — incluida la 🔴, que
  // tiene un solo botón y nada más. Poner las acciones acá las hace alcanzables desde
  // CUALQUIER fila sin agregar un control nuevo que compitiera con esa regla sellada.
  const esLocal = !modelo.pertenencia || modelo.pertenencia.local;
  const acciones = esLocal ? pintarAccionesOperativas(modelo) : "";
  const filas = [
    [L("estado", "state"), e.estado],
    [L("medido", "measured"), e.ts],
    [L("tool usada", "tool used"), e.tool_usada],
    [L("causa", "cause"), e.causa],
    // [OBRA 6b · #5] LA EVIDENCIA, que es donde el motor deja lo que MIDIÓ — incluida la
    // cita de la reserva que la Obra 3 pega al final de la causa («Te avisamos al traerla:
    // …»). Estaba en la fila y en el modelo, y no se pintaba en ningún lado: el usuario
    // leía «causa: arranque» y nunca el porqué. Se muestra tal cual viene; acá no se
    // escribe ni una frase nueva.
    [L("evidencia", "evidence"),
     typeof e.evidencia === "string" ? e.evidencia
       : (e.evidencia ? JSON.stringify(e.evidencia) : null)],
    [L("credencial", "credential"), modelo.credencial && modelo.credencial.estado],
    [L("fuente", "source"), v.fuente],
    [L("tipo de pieza", "piece type"), (k.tipos || []).join(" + ")],
  ];
  // QUÉ CREDENCIALES PIDE Y BAJO QUÉ PROVIDER LAS BUSCA. Es lo que vuelve auditable el
  // «falta tu llave»: si dice que falta, acá se ve exactamente dónde la buscó.
  for (const c of k.credenciales || [])
    filas.push([L("credencial pedida", "credential required"),
                `${c.variable} (${c.donde}) → ${c.provider || "(sin resolver)"} · ${c.rol || "?"}`]);
  if (v.bloqueo === W.NUESTRO) filas.push([L("pendiente nuestro", "our pending"), v.motivo]);
  for (const c of v.contradicciones || [])
    filas.push([L("contradicción", "contradiction"), c.tipo + " · " + c.fuente]);
  // LAS REGLAS QUE SE APLICARON. Sin esto, una pieza pintada distinta de su estado crudo
  // sería inexplicable — y un ajuste que no se puede auditar es magia, no ingeniería.
  for (const r of k.reglas || [])
    filas.push([L("regla aplicada", "rule applied"), r]);
  for (const t of modelo.trazas || [])
    filas.push([L("deriva de", "derived from"), `${t.que} ← ${t.fuente}`]);
  // LAS ACCIONES PRIMERO, la evidencia después: se abre esto para HACER algo más seguido
  // que para leer un traceback, y lo que se usa va arriba.
  // LA RESERVA VA ARRIBA DE TODO, antes de las acciones: es un aviso sobre la PROCEDENCIA
  // de la pieza, no un dato de su última medición, y se lee antes de decidir qué hacer.
  return bloqueReserva(modelo) + acciones + `<dl class="cx-detalle-panel">` +
    filas.filter(([, val]) => val != null && val !== "")
         .map(([kk, val]) => `<dt>${esc(kk)}</dt><dd>${esc(val)}</dd>`).join("") +
    `</dl>`;
}

/** EL RESUMEN · el mismo conteo que las cards, POR CONSTRUCCIÓN: cuenta los modelos.
 *
 * ⚠️ ESTA FUNCIÓN ES LA QUE MATA UN BUG ENTERO. Antes el resumen contaba con el vocabulario
 * del motor y las cards pintaban con el del registro: medido, el resumen decía «1 conexión
 * activa» encima de una lista llena de ✅ Conectado. Ninguno mentía por su cuenta; juntos
 * sí. Ahora no hay dos cuentas que puedan divergir: hay una lista de modelos y esto la
 * cuenta. Que coincidan no es una regla que alguien tenga que respetar — es aritmética.
 */
export function pintarResumen(modelos) {
  const conectadas = modelos.filter((m) => m.veredicto.estado === "conectado" && !m.apagada).length;
  const atencion = modelos.filter((m) => m.veredicto.estado === "esperando");
  return `<div class="cx-summary" data-connected="${conectadas}" data-total="${modelos.length}">` +
    `<div class="cx-summary-main"><strong data-summary-connected>${conectadas}</strong> ` +
    `<span>${esc(L(`de ${modelos.length} conectadas`, `of ${modelos.length} connected`))}</span></div>` +
    (atencion.length
      ? `<div class="cx-summary-attention"><span>${esc(L("Necesitan algo tuyo:", "Need something from you:"))} ` +
        `<b>${esc(atencion.map((m) => m.nombre || m.entityId).slice(0, 3).join(", "))}` +
        `${atencion.length > 3 ? "…" : ""}</b></span></div>`
      : "") +
    `</div>`;
}

/** EL CHECKLIST VIVO · los verbos completándose, no un spinner mudo.
 *
 * ⚠️ QUÉ ARREGLA. [Reintentar] se apretaba y no pasaba nada visible durante segundos: el
 * usuario no sabía si el click había entrado, si el sistema estaba trabajando, ni —cuando
 * volvía en rojo— en qué momento se había caído. Un spinner responde a la primera pregunta
 * y a ninguna de las otras dos.
 *
 * LOS VERBOS SON LOS QUE EL SISTEMA CORRE DE VERDAD (`spec → handshake → tools →
 * credencial`), con los títulos que el backend ya escribió. No se dibujan pasos que no
 * existen: una animación que no corresponde a nada miente con más detalle que un spinner.
 *
 * Y SI FALLA, SE DETIENE EN EL VERBO CULPABLE. Los anteriores quedan ✓, el culpable ✗ con
 * su causa, y los siguientes NO se pintan — porque no corrieron. Un checklist que se pinta
 * entero en gris al fallar borra justo el dato que lo hacía útil: hasta dónde se llegó.
 */
export function pintarChecklist(estado) {
  const verbos = (estado && estado.verbos) || [];
  if (!verbos.length) return "";
  const filas = verbos.map((v) => {
    const marca = v.estado === "hecho" ? "✓"
                : v.estado === "roto" ? "✗"
                : v.estado === "probando" ? "⏳" : "·";
    return `<li class="cx-verbo" data-verbo="${esc(v.id)}" data-estado="${esc(v.estado)}">` +
      `<span class="cx-verbo-marca" aria-hidden="true">${marca}</span>` +
      `<span>${esc(v.titulo)}</span>` +
      // LA CAUSA VIVE JUNTO AL VERBO QUE LA PRODUJO. Separarla —un mensaje abajo de todo—
      // obliga a adivinar a cuál de los cuatro pertenece.
      (v.estado === "roto" && v.causa
        ? `<small class="cx-verbo-causa">${esc(causaHumana(v.causa))}</small>` : "") +
      `</li>`;
  });
  return `<ul class="cx-checklist" aria-live="polite">${filas.join("")}</ul>`;
}

/** La causa, en palabras del usuario. Sale del diccionario ÚNICO del semáforo —el mismo que
 *  ya usan el Cuarto, el chat y el preflight— así que una causa dice lo mismo en todas
 *  partes. Una causa que este diccionario no conoce no se inventa: se omite, y su nombre
 *  técnico sigue entero en el [?]. */
function causaHumana(causa) {
  try {
    const meta = W.CAUSAS_HUMANAS && W.CAUSAS_HUMANAS[causa];
    if (meta) return lang() === "en" ? meta.en : meta.es;
  } catch (_) { /* nunca puede tumbar el checklist */ }
  return "";
}

/** LAS ACCIONES OPERATIVAS DE UNA PIEZA COMPLETA (acta §3).
 *
 * ⚠️ EL HUECO QUE CIERRA: una pieza verde sólo tenía el [?]. Estaba lista para usar y no
 * había forma de desconectarla, de rotar su llave voluntariamente ni de volver a probarla —
 * el catálogo local era de sólo lectura para todo lo que no estuviera roto.
 *
 * Cada acción aparece por una RAZÓN derivada, no «por si acaso»:
 *   · [Desconectar]  SIEMPRE. Es el permiso del usuario sobre su propia pieza, y no
 *     depende de ningún estado. **Deja la llave** (contrato de la lápida): volver es un
 *     click. Borrar la credencial es la otra acción y vive en el Llavero, con su impacto.
 *   · [Reconectar]   sólo si está apagada — es la vuelta de lo anterior.
 *   · [Rotar llave]  sólo si la pieza TIENE credencial. Rotación voluntaria: nadie tiene
 *     que esperar a que una llave falle para cambiarla.
 *   · [Reintentar]   **SÓLO ante un fallo transitorio.** Sobre una pieza sana no resuelve
 *     nada y sugiere que algo anda mal; sobre una permanente devuelve el mismo rojo.
 *     Quién decide si es transitorio ya está escrito: `repair_clasificar`, vía la
 *     clasificación que viaja en el modelo. Acá no se re-decide.
 */
export function pintarAccionesOperativas(modelo) {
  const cred = modelo.credencial || {};
  const clase = String((modelo.clasificacion || {}).clase || "").toUpperCase();
  const rota = (modelo.evidencia || {}).estado === "rota";
  const transitorio = rota && clase === "TEMPORAL";
  const b = [];

  if (modelo.apagada) {
    b.push(`<button class="cx-btn cx-reconectar" data-reconectar="${esc(modelo.entityId)}">` +
           `${esc(L("Reconectar", "Reconnect"))}</button>`);
  } else {
    if (transitorio)
      b.push(`<button class="cx-btn cx-reintentar" data-reintentar="${esc(modelo.entityId)}">` +
             `${esc(L("Reintentar", "Retry"))}</button>`);
    if (cred.hay)
      b.push(`<button class="cx-btn cx-rotar" data-rotar="${esc(modelo.entityId)}">` +
             `${esc(L("Rotar llave", "Rotate key"))}</button>`);
    b.push(`<button class="cx-btn cx-desconectar" data-entity="${esc(modelo.entityId)}">` +
           `${esc(L("Desconectar", "Disconnect"))}</button>`);
  }
  return `<div class="cx-operativas" data-operativas="${esc(modelo.entityId)}">` +
    b.join("") +
    `<small>${esc(modelo.apagada
      ? L("Tu llave sigue guardada.", "Your key is still saved.")
      : L("Desconectar deja tu llave guardada. Volver es un click.",
          "Disconnecting keeps your key. Coming back is one click."))}</small></div>`;
}

/* ══════════════════════════════════════════════════════════════════════════════════════
 * EL PASO 2.5 · LA ADUANA
 *
 * Entre el [Traer] del catálogo público y el catálogo local. Acá se resuelve TODO lo
 * previo —instalar, pegar la llave, autorizar— y la verificación real. **Nada entra al
 * local a medias.**
 *
 * ⚠️ LADRILLOS VIEJOS, LUGAR NUEVO. No se construyó ni un flujo: el campo de llave inline
 * con [Guardar y probar], el link de instalación con [Ya lo instalé · verificar] y el
 * [Conectar] de OAuth son EXACTAMENTE los que ya vivían en las cards. Lo único que cambió
 * es DÓNDE se muestran — porque una pieza a la que le falta la llave no es un servicio que
 * tenés, es un servicio que estás trayendo.
 *
 * Y no hay botón «mover al local»: cuando el trámite se completa y la verificación pasa, el
 * clasificador la promueve solo. Un botón para mover sería una segunda opinión sobre lo que
 * `pertenencia()` ya sabe.
 * ════════════════════════════════════════════════════════════════════════════════════ */

/** LOS GRUPOS DE LA ADUANA · por TIPO de trámite, que es el vocabulario que ya existe.
 *
 * No se inventa ninguno: son los tres pasos que el adaptador ya deriva (`oauth` · `llave` ·
 * `instalar`) más el cajón de lo que es NUESTRO. Que sean por tipo y no por conector es lo
 * mismo que hace escalar al resto: sirve igual para las de hoy y para las 17.000. */
const GRUPO = () => ({
  [W.PASO_OAUTH]: { titulo: L("Click", "Click"),
                    copy: L("Autorizas en el sitio del servicio y vuelves.",
                            "You authorize on the service's site and come back.") },
  [W.PASO_LLAVE]: { titulo: L("Llave", "Key"),
                    copy: L("Pegas una llave que te dan y la probamos al instante.",
                            "Paste the key they give you and we test it right away.") },
  [W.PASO_INSTALAR]: { titulo: L("Descarga", "Download"),
                       copy: L("Corre en tu equipo: hay que instalarlo una vez.",
                               "It runs on your machine: install it once.") },
});

// ⚠️ ACÁ HABÍA UN CUARTO GRUPO: «Nos toca a nosotros», para las piezas trabadas por un hueco
// NUESTRO. **Murió por orden de persona usuaria (2026-08-04), y la razón es buena**: decirle al usuario
// «esto es deuda nuestra» le entrega un problema que no contrajo, sobre el que no puede hacer
// nada, y que va a seguir ahí mañana. Una fila que sólo se puede mirar no es información: es
// una lápida.
//
// Esas piezas ya no llegan a esta capa. Se retienen en el registro con
// `estado_interno='pendiente_ingesta'` y el endpoint de las fuentes no las manda — invisibles
// por construcción, no por un `if` de render que la próxima vista pueda olvidar. Su deuda
// vive en el censo (`qa/censo_widget.mjs`), que es nuestra herramienta y no la del usuario.

/** Qué grupo le toca a una pieza · **el PRIMERO de `pertenencia().faltan`, y nada más.**
 *
 * ⚠️ ACÁ HABÍA UN SEGUNDO ORDEN, y por eso una pieza caía en el grupo equivocado. Esta
 * función recorría su propia lista de prioridades en vez de respetar la del clasificador, y
 * una pieza con una contradicción ficha-vs-belt terminaba en «Llave» —con su campo y su
 * botón— porque `oauth` venía antes que `escrutinio` en ESTA lista y después en la otra.
 *
 * El clasificador ya decidió qué es lo primero que le falta: si algo no se puede escrutar,
 * eso manda sobre cualquier trámite que quizá ni exista. Dos órdenes para la misma pregunta
 * son dos verdades, que es el bug que todo este adaptador existe para no volver a tener.
 */
export function grupoDe(modelo) {
  return (((modelo.pertenencia || {}).faltan) || [])[0] || null;
}

/** QUÉ PIEZAS SON DE LA ADUANA · las que tienen un trámite DEL USUARIO pendiente.
 *
 * ⚠️ UNA SOLA FUENTE PARA EL CONTADOR, EL `hidden` Y EL RENDER. Sin esto la sección podía
 * quedar visible con el contador en 1 y ninguna fila adentro: el montaje contaba «todo lo
 * que no es del local» y el render descartaba después la deuda nuestra. Dos cuentas de la
 * misma cosa, y el usuario viendo una caja vacía que dice que tiene algo.
 */
export function piezasDeAduana(modelos) {
  const RENDERIZABLES = [W.PASO_INSTALAR, W.PASO_OAUTH, W.PASO_LLAVE];
  return (modelos || []).filter((m) => RENDERIZABLES.includes(grupoDe(m)));
}

/** LA ADUANA, pintada · una sección por grupo, y adentro la fila con SU camino. */
export function pintarAduana(modelos) {
  const grupos = GRUPO();
  const porGrupo = new Map();
  for (const m of piezasDeAduana(modelos)) {
    const g = grupoDe(m);
    if (!porGrupo.has(g)) porGrupo.set(g, []);
    porGrupo.get(g).push(m);
  }
  if (!porGrupo.size)
    return `<p class="cx-aduana-vacia">${esc(L(
      "Nada en preparación: todo lo que trajiste está listo para usar.",
      "Nothing in preparation: everything you brought is ready to use."))}</p>`;

  // ⚠️ EL GRUPO `escrutinio` NO SE PINTA, y su ausencia es deliberada: es deuda NUESTRA, y
  // el usuario jamás la ve. En condiciones normales tampoco llega hasta acá —el endpoint de
  // las fuentes no manda las retenidas— así que esto cubre el caso de una pieza con un hueco
  // estructural que todavía nadie marcó.
  //
  // Y NO DESAPARECE EN SILENCIO: el censo la cuenta aparte y la nombra («SIN RETENER»), que
  // es precisamente la señal de que hay una deuda esperando su `pendiente_ingesta`. Invisible
  // para el usuario, imposible de perder para nosotros.
  const out = [];
  for (const k of [W.PASO_INSTALAR, W.PASO_OAUTH, W.PASO_LLAVE]) {
    const piezas = porGrupo.get(k);
    if (!piezas || !piezas.length) continue;
    const g = grupos[k];
    out.push(`<section class="cx-grupo" data-grupo="${esc(k)}">`,
             `<div class="cx-section-head"><h3>${esc(g.titulo)}</h3>`,
             `<span class="cx-number">${piezas.length}</span></div>`,
             `<p class="cx-section-copy">${esc(g.copy)}</p>`,
             `<ul class="cx-rows">`,
             piezas.map((m) => pintarFilaAduana(m)).join(""),
             `</ul></section>`);
  }
  return out.join("");
}

/** UNA FILA DE LA ADUANA · el nombre, qué falta, y SU camino desplegado.
 *
 * A diferencia de la card del local, acá el trámite está ABIERTO: el usuario entró a esta
 * sección justamente a hacerlo, y esconderlo detrás de un click más sería pedirle que
 * adivine dónde está lo que vino a hacer.
 */
export function pintarFilaAduana(modelo) {
  const p = modelo.pertenencia || {};
  return `<li class="cx-card cx-aduana ds-card ds-item" data-entity="${esc(modelo.entityId)}"` +
    ` data-grupo="${esc(grupoDe(modelo) || "")}" data-lista="aduana">` +
    `<span class="cx-face">${cara(modelo)}</span>` +
    `<span class="cx-nombre">${esc(modelo.nombre || modelo.entityId)}</span>` +
    `<span class="cx-estado"><span class="cx-luz" aria-hidden="true">🟡</span>` +
    `<b>${esc(p.motivo || "")}</b></span>` +
    // LA FECHA, TAMBIÉN ACÁ. La ley no cambia por cambiar de lista: un veredicto sin su
    // cuándo es afirmar de memoria, esté donde esté.
    `<span class="cx-cuando">${esc(fecha(modelo))}</span>` +
    `<span class="cx-actions ds-actions"></span>` +
    `<button class="cx-detalle qmark" data-detalle="${esc(modelo.entityId)}"` +
    ` aria-label="${esc(L("Ver evidencia técnica", "See technical evidence"))}">?</button>` +
    // EL CAMINO, ABIERTO. Toda fila que llega acá tiene un trámite del usuario: las que no
    // lo tienen —la deuda nuestra— ni siquiera se agrupan.
    `<div class="cx-panel-host" data-panel="${esc(modelo.entityId)}">` +
    pintarPanel(modelo) +
    `</div></li>`;
}

/** EL LLAVERO · una fila por credencial guardada, con qué piezas dependen de ella.
 *
 * ⚠️ AHORA SALE DEL VAULT, QUE ES LA VERDAD. La versión vieja lo armaba con el campo
 * `credential` del catálogo de capacidades —o sea, con lo que la receta DECÍA que había—
 * y por eso podía listar una credencial borrada o esconder una guardada. El vault es lo que
 * el usuario efectivamente entregó; el catálogo es lo que alguien declaró que haría falta.
 * Son dos hechos distintos y el llavero pregunta por el primero.
 *
 * El IMPACTO se deriva igual: qué piezas piden ESE provider sale de resolver las variables
 * de cada belt, que es exactamente lo mismo que hace el assembler para inyectar. Si el
 * llavero contara otra cosa, sacar una llave dejaría rota una pieza que no estaba en la
 * lista de advertencia.
 */
export function pintarLlavero(vault, modelos) {
  const usos = new Map();
  for (const m of modelos || [])
    for (const c of (m.conocimiento || {}).credenciales || []) {
      if (!c.provider) continue;
      if (!usos.has(c.provider)) usos.set(c.provider, []);
      usos.get(c.provider).push(m.nombre || m.entityId);
    }

  const filas = Object.keys(vault || {}).sort();
  if (!filas.length)
    return `<li class="cx-empty">${esc(L(
      "Todavía no guardaste ninguna credencial. Nacen al conectar un servicio.",
      "No credentials saved yet. They start when you connect a service."))}</li>`;

  return filas.map((provider) => {
    const impacto = Array.from(new Set(usos.get(provider) || []));
    return `<li class="cx-card ds-card ds-item cx-key-row" data-key="${esc(provider)}">` +
      `<span class="cx-face">${cara({ entityId: provider, nombre: provider })}</span>` +
      `<span class="cx-nombre">${esc(provider)}` +
      // ⚠️ NUNCA los últimos dígitos de la llave. El endpoint no los manda y esta línea no
      // los pediría: un `last4` es un dato de la credencial, y de la credencial acá sólo
      // viaja que existe y desde cuándo.
      `<small class="cx-desde">${esc(fecha({ header: { ts: (vault[provider] || {}).desde } }))}` +
      `</small></span>` +
      `<span class="cx-estado"><span class="cx-luz" aria-hidden="true">🔑</span>` +
      `<b>${esc(L("Guardada", "Saved"))}</b>` +
      `<small>${esc(impacto.length
        ? L(`la usan: ${impacto.join(", ")}`, `used by: ${impacto.join(", ")}`)
        // UNA LLAVE QUE NADIE PIDE NO ES UN ERROR PERO ES UN DATO: el adaptador ya la
        // delata como contradicción en la pieza; acá se ve del lado de la credencial.
        : L("ninguna pieza equipada la pide", "no equipped piece requires it"))}</small></span>` +
      `<span class="cx-actions ds-actions">` +
      `<button class="cx-btn cx-btn-danger cx-sacar" data-sacar="${esc(provider)}">` +
      `${esc(L("Sacar", "Remove"))}</button></span>` +
      // EL IMPACTO ANTES DE CONFIRMAR, y la confirmación pintada acá y no en un `confirm()`:
      // la advertencia tiene que decir QUÉ se rompe, y para eso necesita el impacto derivado.
      `<div class="cx-panel-host" data-confirmar="${esc(provider)}" hidden></div>` +
      `</li>`;
  }).join("");
}

/** LA ADVERTENCIA DE SACAR UNA LLAVE. Impacto primero, botón después. */
export function pintarConfirmarSacar(provider, impacto) {
  return `<div class="cx-key-preview" role="alert">` +
    `<b>${esc(L("Antes de sacar esta credencial:", "Before removing this credential:"))}</b> ` +
    `${esc(impacto.length
      ? L(`quedarán sin credencial: ${impacto.join(", ")}`,
          `these will lose their credential: ${impacto.join(", ")}`)
      : L("ninguna pieza equipada la está usando.",
          "no equipped piece is using it."))} ` +
    `<button class="cx-btn cx-btn-danger cx-sacar-ok" data-sacar-ok="${esc(provider)}">` +
    `${esc(L("Confirmar", "Confirm"))}</button> ` +
    `<button class="cx-btn cx-sacar-no" data-sacar-no="${esc(provider)}">` +
    `${esc(L("Cancelar", "Cancel"))}</button></div>`;
}

/** LO QUE SE VE CUANDO LA LECTURA NO OCURRIÓ.
 *
 * FALLO VISIBLE, JAMÁS MUDO. Una lista vacía y una lista que no se pudo leer se ven igual y
 * significan cosas opuestas: la primera dice «no tenés nada equipado», la segunda «no sé
 * qué tenés». Decir la primera cuando pasa la segunda es inventar un estado.
 */
export function pintarSinLectura() {
  return `<li class="cx-empty cx-error" data-sin-lectura="true">` +
         `${esc(L("Tus conectores no se ven por ahora. Estamos reintentando.",
                  "Your connectors aren't visible right now. We're retrying."))}</li>`;
}

export function pintarVacio() {
  return `<li class="cx-empty">${esc(L("Todavía no equipaste ningún conector.",
                                       "You haven't equipped any connector yet."))}</li>`;
}

/** EL CSS DEL PANEL · viaja CON la superficie, no con la pantalla.
 *
 * ⚠️ POR QUÉ ACÁ Y NO EN CADA `.dc.html`. El panel se abre en DOS lugares —la lista de
 * Conectores y, anclado, el Cuarto— y va a abrirse en más. Si el estilo viviera en cada
 * pantalla, cada una tendría su copia y el mismo panel se vería distinto según desde dónde
 * se lo abriera; peor, una pantalla nueva lo mostraría sin estilo y nadie lo notaría hasta
 * verlo. Es el mismo motivo por el que el wizard viejo traía su `inyectarCSS`, y es la
 * parte de aquel diseño que sí había que conservar.
 *
 * Usa los tokens del sistema (`--paper`, `--r-md`, …) con respaldo, así funciona también en
 * una pantalla que no haya cargado `aleph-tokens.css`.
 */
export const CSS_PANEL = `
.cx-panel{display:flex;flex-direction:column;gap:12px}
.cx-paso{display:flex;flex-wrap:wrap;align-items:center;gap:9px;padding:12px 14px;
         background:var(--paper2,#1b1b1f);border-radius:var(--r-md,12px)}
.cx-paso p{margin:0;flex:1 1 100%;font:400 13px var(--font-ui,system-ui)}
.cx-paso label{display:flex;flex-direction:column;gap:4px;flex:1 1 220px;
               font:300 11px var(--font-ui,system-ui);color:var(--muted,#9a9aa2)}
.cx-paso input{border:0;background:var(--paper,#242429);color:var(--ink,#f2f2f4);
               border-radius:var(--r-sm,8px);padding:10px 12px;outline:none;
               font:300 13px var(--font-ui,system-ui)}
.cx-paso input:focus{background:var(--accent-soft,#2b2540)}
.cx-link{color:var(--accent-deep,#a78bfa);font:400 12px var(--font-ui,system-ui);text-decoration:none}
.cx-link:hover{text-decoration:underline}
.cx-scopes{margin:0;padding-left:18px;flex:1 1 100%;
           font:300 12px var(--font-ui,system-ui);color:var(--muted,#9a9aa2)}
.cx-lapida{background:transparent;padding:2px 0}
.cx-lapida small{font:300 11px var(--font-ui,system-ui);color:var(--faint,#6f6f78)}
.cx-detalle-panel{display:grid;grid-template-columns:minmax(120px,auto) 1fr;gap:4px 14px;
                  margin:0;padding:12px 14px;background:var(--paper2,#1b1b1f);
                  border-radius:var(--r-md,12px);font:300 11.5px/1.5 var(--font-ui,system-ui)}
.cx-detalle-panel dt{color:var(--faint,#6f6f78)}
.cx-detalle-panel dd{margin:0;color:var(--ink,#f2f2f4);word-break:break-word}
.cx-key-preview{padding:12px 14px;border:0;background:var(--red-bg,#3a1f22);
                color:var(--ink,#f2f2f4);border-radius:var(--r-md,12px);line-height:1.8;
                font:300 12.5px var(--font-ui,system-ui)}
/* EL PANEL ANCLADO · el mismo panel, flotando junto al botón que lo abrió. Es lo que hace
   que el Cuarto no tenga que sacar a nadie de donde está para arreglar una pieza. */
.cx-anclado{position:absolute;z-index:9999;min-width:300px;max-width:min(420px,92vw);
            padding:14px;background:var(--paper,#242429);border-radius:var(--r-md,12px);
            box-shadow:0 18px 48px rgba(0,0,0,.45)}
.cx-anclado .cx-anclado-head{display:flex;align-items:center;justify-content:space-between;
                             gap:10px;margin-bottom:10px}
.cx-anclado .cx-anclado-head b{font:400 13px var(--font-ui,system-ui)}
.cx-anclado .cx-cerrar{border:0;background:transparent;color:var(--muted,#9a9aa2);
                       cursor:pointer;font-size:16px;line-height:1;padding:2px 6px}
`;

/** La cabecera del panel anclado: qué pieza es, y cómo salir. */
export function pintarAnclado(modelo) {
  return `<div class="cx-anclado-head"><b>${esc(modelo.nombre || modelo.entityId)}</b>` +
    `<button class="cx-cerrar" data-cerrar-anclado="1"` +
    ` aria-label="${esc(L("Cerrar", "Close"))}">×</button></div>` +
    pintarPanel(modelo);
}
