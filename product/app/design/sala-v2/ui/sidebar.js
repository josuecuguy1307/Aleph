// LA NAVEGACIÓN NUEVA (1.5).
//
//     El Cuarto · La Sala · [workspaces elegibles por STACK] · Biblioteca · Ajustes
//
// Tres decisiones, y las tres tienen consecuencia:
//
// 1 · **«Chats» se disuelve.** Deja de ser un destino: los hilos recientes viven acá
//     adentro, debajo de La Sala. CERO PÉRDIDA DE HISTORIAL — no se migra nada ni se toca
//     el esquema: los hilos siguen siendo los mismos de `GET /v1/chats` (tabla `chats`,
//     migración 0007), scope-ados por `(user_id, puppet_id)` exactamente igual que hoy. Lo
//     que cambia es dónde se listan. Y `Historial.dc.html` sigue en pie y alcanzable, así
//     que ni siquiera queda un camino viejo roto.
//
// 2 · **Los workspaces no elegibles NO aparecen.** Ni grises, ni con candado (ley de
//     producto 6 y 4.4: jamás catálogo).
//
//     [Gate 4 · Fase 3 · 3.7] **LA ELEGIBILIDAD ES POR STACK, NO POR CINTURÓN** — enmienda
//     sellada 2026-08-08. Con la ley 0, un vertical vale ENTERO sin un solo conector de
//     Aleph: su UI, su motor, sus fuentes y sus tools son suyos. Condicionar su existencia
//     al cinturón escondería algo que funciona, y el usuario que instaló un workspace no
//     tiene por qué armar un conector para verlo. El cinturón SUGIERE (Fase 4 lo usa como
//     señal en la transición); el stack decide si el workspace existe.
//
//     [cosecha de la Fase 3] **CERO ELEGIBLES ⇒ LA SECCIÓN NO EXISTE.** Hoy no hay ningún
//     stack heredado adentro, así que `GET /v1/workspaces` devuelve `[]`. Un encabezado
//     «Workspaces» sobre un texto que explica que no hay ninguno le enseña al usuario una
//     categoría vacía y le pide que la entienda: eso es catálogo, que es exactamente lo
//     que la decisión 2 prohíbe. La sección aparece cuando hay algo que mostrar.
//
//     Quién lo mide: el backend (`GET /v1/workspaces`), no esta pantalla. Un `fetch` a un
//     puerto desde el navegador diría «no corre» en cuanto haya un CORS de por medio, y
//     «no corre» ≠ «no está instalado» — son dos hechos distintos y el menú depende del
//     primero, no del segundo.
//
//     Por qué importa que quede cableado y no «para después»: el censo midió (§D.2) que el
//     nav global tiene el filtro por capability EXISTIENDO (`Territorio.forBelt`) y NO
//     cableado a `nav.js`. Un mecanismo sin consumidor es un mecanismo que nadie prueba.
//
// 3 · **El Cuarto sigue siendo un documento aparte.** No se toca. El cruce es el mismo de
//     siempre: `?puppet=<id>` por query-string (`bridge.js:4-6`).

import { React } from "../vendor/assistant-ui.bundle.js";

const h = React.createElement;
const tr = (k, fb) => {
  const s = typeof window !== "undefined" && window.t ? window.t(k) : null;
  return s && s !== k ? s : fb;
};

/**
 * Los workspaces elegibles: los que el backend reporta con su STACK INSTALADO.
 *
 * Cada fila trae, además de lo que el menú pinta, los TIPOS que el workspace acepta
 * (`accepts`, del puente) — la compatibilidad por artefacto de la ley 7. El cinturón no
 * entra en la decisión: entra como sugerencia en la transición de Fase 4.
 *
 *     { id, label, icon, href, accepts: [...], stack: {name, installed, running} }
 *
 * Un fallo de red devuelve `[]` — que es lo mismo que «no hay ninguno instalado» para el
 * menú, y no una lista inventada.
 */
export async function elegiblesPorStack(headers) {
  try {
    const r = await fetch("/v1/workspaces", { headers: headers ? headers() : {} });
    if (!r.ok) return [];
    const j = await r.json();
    return (j?.workspaces || []).map((w) => ({
      ...w,
      href: "../workspaces/" + encodeURIComponent(w.id) + ".html",
    }));
  } catch (_) {
    return [];
  }
}

function Link({ href, icon, label, actual, onClick }) {
  return h(
    href ? "a" : "button",
    {
      className: "sv-link",
      ...(href ? { href } : { type: "button" }),
      ...(actual ? { "aria-current": "page" } : {}),
      onClick,
    },
    h("span", { className: "ic" }, icon),
    h("span", null, label),
  );
}

/**
 * UNA PIEZA DEL CINTURÓN — un server con las tools que el agente tiene de él.
 *
 * No es un link ni un botón: desde acá no se equipa nada. Equipar es del Cuarto; La Sala
 * sólo muestra con qué está trabajando el agente. Un elemento que parece accionable y no
 * hace nada es peor que uno que no lo parece.
 */
function Pieza({ p }) {
  return h(
    "div",
    { className: "sv-pieza", title: (p.tools || []).join(" · ") },
    h("span", { className: "sv-pieza-lbl" }, p.label),
    (p.tools || []).length
      ? h("span", { className: "sv-pieza-n" }, String(p.tools.length))
      : null,
  );
}

/* ── LOS TRES GRUPOS DE UN RESULTADO ──────────────────────────────────────────────────
 * [convergencia · superficie 5 · F.5] El índice interno (`GET /v1/busqueda`) devuelve
 * `{hilos, mensajes, artefactos}` y hasta hoy no lo llamaba NADIE: la Sala buscaba con
 * `/v1/chats/search`, que sólo sabe de mensajes, y los aplanaba a una lista de hilos.
 * O sea que el usuario no podía encontrar un artefacto suyo desde ningún lado.
 *
 * Los tres grupos se pintan SIEMPRE en el mismo orden y el que viene vacío NO se dibuja —
 * un encabezado «Artefactos» sobre la nada es una promesa incumplida en cada búsqueda. */
const GRUPOS = [
  { clave: "hilos", k: "salav2.res.hilos", fb: "Conversaciones" },
  { clave: "mensajes", k: "salav2.res.mensajes", fb: "Mensajes" },
  { clave: "artefactos", k: "salav2.res.artefactos", fb: "Artefactos" },
];

function Resultados({ res, onAbrirResultado }) {
  const grupos = GRUPOS.filter((g) => (res[g.clave] || []).length);
  if (!grupos.length) {
    return h("div", { className: "sv-vacio" },
      tr("salav2.sin_coincidencias", "Nada tuyo coincide con esa búsqueda."));
  }
  return h(
    "div", { className: "sv-res" },
    ...grupos.map((g) =>
      h("div", { key: g.clave, className: "sv-res-grupo" },
        h("div", { className: "sv-res-tit" }, tr(g.k, g.fb)),
        ...(res[g.clave] || []).map((it, i) =>
          h("button", {
            key: g.clave + i, type: "button", className: "sv-hilo sv-res-fila",
            title: it.titulo || "",
            onClick: () => onAbrirResultado?.(it),
          },
            h("span", { className: "sv-res-nom", "data-no-tm": "" }, it.titulo || tr("salav2.hilo_sin_titulo", "Sin título")),
            // El fragmento SÓLO si el índice lo mandó: un hilo no trae `snippet` porque lo
            // que matcheó fue su título, y fabricar uno sería inventar dónde estaba el hit.
            it.snippet ? h("span", { className: "sv-res-frag" }, it.snippet) : null))),
    ),
    // EL TOPE, DICHO. `recortado` viaja desde el índice justamente para esto: un total que
    // calla su límite miente, y el usuario que no ve lo que busca merece saber que hay más.
    res.recortado
      ? h("div", { className: "sv-res-mas" }, tr("salav2.res.recortado", "Hay más — afina la búsqueda."))
      : null,
  );
}

export function Sidebar({ hilos, hiloActual, onAbrirHilo, onNuevoHilo, workspaces, puppetId, cinturon, onBuscar, buscando, resultados, onAbrirResultado }) {
  const q = puppetId ? "?puppet=" + encodeURIComponent(puppetId) : "";

  return h(
    "nav",
    { className: "sv-spine", "aria-label": tr("salav2.nav.aria", "Secciones") },
    // [rediseño · fase 1 · una sola mascota] EL ROMBO DEJA DE SER LA MARCA. `◈` acompañaba
    // a "Aleph" acá como si fuera el logotipo; el estándar dice que la mascota —el átomo con
    // la carita— es el único Aleph, y que el rombo queda SÓLO como glifo del riel. Es el
    // mismo PNG que la barra usa desde julio, no un dibujo nuevo.
    h("div", { className: "sv-brand" },
      h("img", { src: "../assets/aleph-mascot-v2.png", alt: "", width: 18, height: 18,
                 style: { display: "block", flex: "none" } }),
      h("span", null, "Aleph")),

    h(Link, { href: "../Cuarto.dc.html" + q, icon: "＋", label: tr("nav.armar", "El Cuarto") }),
    h(Link, { href: "./sala-v2.html" + q, icon: "▶", label: tr("nav.sala", "La Sala"), actual: true }),

    // ── los hilos, adentro de La Sala ──────────────────────────────────────────────────
    h(
      "div",
      { className: "sv-hilos" },
      h(
        "button",
        { type: "button", className: "sv-hilo", onClick: onNuevoHilo },
        "＋ " + tr("salav2.nuevo_hilo", "Conversación nueva"),
      ),
      // ── BUSCAR EN LOS CHATS — rescatado de la Sala vieja antes de borrarla ──────────
      // `sala.html:2795` con su debounce de 250 ms y `/v1/chats/search`. El endpoint ya
      // existía y la v2 no lo llamaba: con 12 hilos visibles y sin buscador, una
      // conversación vieja era inalcanzable. Aparece sólo con más de 5 hilos — con menos,
      // un campo de búsqueda es una pregunta que el usuario contesta mirando.
      //
      // ⚠️ `|| buscando` NO ES DECORATIVO. El umbral mira la MISMA lista que la búsqueda
      // reemplaza, así que sin esa mitad el campo se desmontaba solo en cuanto el
      // resultado traía 5 filas o menos —el caso normal— y con 0 resultados dejaba al
      // usuario encerrado: sin campo que borrar, sin forma de volver a la lista completa.
      (hilos || []).length > 5 || buscando
        ? h("input", {
            className: "sv-buscar",
            type: "search",
            placeholder: tr("sala.chats.search_ph", "Buscar en los chats…"),
            "aria-label": tr("sala.chats.search_aria", "buscar en los chats"),
            onInput: (e) => onBuscar?.(e.target.value.trim()),
          })
        : null,
      // Con una búsqueda en curso manda el resultado en tres grupos; sin ella, la lista
      // normal de hilos. No conviven: son dos respuestas a dos preguntas distintas.
      buscando && resultados
        ? h(Resultados, { res: resultados, onAbrirResultado })
        : (hilos || []).length
        ? hilos.slice(0, 12).map((c) =>
            h(
              "button",
              {
                key: c.id,
                type: "button",
                className: "sv-hilo",
                "data-no-tm": "",
                "aria-current": c.id === hiloActual ? "true" : undefined,
                title: c.title || "",
                onClick: () => onAbrirHilo?.(c.id),
              },
              c.title || tr("salav2.hilo_sin_titulo", "Sin título"),
            ),
          )
        // Dos causas distintas, dos copys. Con una búsqueda escrita, «Todavía no hay
        // conversaciones» es literalmente falso —el usuario tiene doce— y lo manda a
        // crear una en vez de a corregir lo que escribió. Se vio MIRANDO la pantalla:
        // en el código las dos ramas eran la misma línea.
        : h("div", { className: "sv-vacio" },
            buscando
              ? tr("salav2.sin_coincidencias", "Ningún chat coincide con esa búsqueda.")
              : tr("salav2.sin_hilos", "Todavía no hay conversaciones.")),
    ),

    // ── workspaces elegibles por STACK instalado (3.7 · ley 6 enmendada) ──────────────
    // La sección ENTERA —encabezado incluido— sólo existe si hay al menos uno. Cero
    // elegibles no es un estado vacío que haya que explicar: es una sección que no va.
    // AGRUPADOS EN UN DESPLEGABLE, no sueltos. Seis entradas planas ocupaban media barra y
    // competían en peso con El Cuarto y La Sala, que son a donde se entra todo el tiempo.
    //
    // `<details>` y no un estado propio: da el teclado, el `aria-expanded` y el foco gratis,
    // y no hay un booleano que pueda desincronizarse. Se abre HACIA ABAJO, en el flujo —
    // sólo empuja lo que tiene debajo (Más), no reacomoda la barra ni tapa nada.
    //
    // ⚠️ `data-no-tm` NO ES DECORACIÓN. `i18n.js` recorre TODOS los nodos de texto y los
    // traduce por coincidencia de string (`trWith`, el TreeWalker de :2910). Los nombres de
    // los workspaces son DATO DEL BACKEND, no copy de la interfaz, y el barrido los pisaba:
    // MEDIDO en la .app instalada, React recibía `label:"Educación"` y el DOM mostraba
    // «Education» — y «Finanzas»/«Oficina» igual, mientras «Ciencia»/«Diseño» sobrevivían
    // sólo porque no están en el diccionario. Media lista en un idioma y media en otro.
    // `data-no-tm` es la exclusión que el propio i18n publica (`noTM`, :2932).
    ...((workspaces || []).length
      ? [
          h(
            "details",
            { className: "sv-ws", key: "ws" },
            h(
              "summary",
              { className: "sv-link sv-ws-sum" },
              h("span", { className: "ic" }, "▚"),
              h("span", null, tr("salav2.nav.workspaces", "Workspaces")),
              h("span", { className: "sv-ws-n" }, String(workspaces.length)),
            ),
            h(
              "div",
              { className: "sv-ws-lista", "data-no-tm": "" },
              ...workspaces.map((w) =>
                h(Link, {
                  key: w.id,
                  href: w.href + q,
                  icon: w.icon || "▚",
                  label: w.label,
                  // El stack instalado y APAGADO igual aparece: que no corra es algo que la
                  // pantalla del workspace tiene que decir, no algo que el menú deba esconder.
                  title: w.stack?.running ? undefined : tr("salav2.ws.apagado", "instalado · no está corriendo"),
                }),
              ),
            ),
          ),
        ]
      : []),

    // ── el cinturón del agente ────────────────────────────────────────────────────────
    // Mismo patrón que los workspaces de arriba: la sección ENTERA sólo existe si hay algo
    // que mostrar. En RAW no hay agente, así que no hay cinturón — y una sección vacía que
    // dijera «sin herramientas» estaría afirmando algo sobre un agente que no existe.
    //
    // Sólo lo que el usuario EQUIPÓ. El kit base viaja adentro y hace su trabajo, pero no
    // se pinta: es infraestructura, nadie la eligió. (Se excluye solo: declara 0 cards.)
    ...((cinturon || []).length
      ? [
          h("div", { className: "sv-sect" }, tr("salav2.nav.cinturon", "Cinturón")),
          ...cinturon.map((p) => h(Pieza, { key: p.id, p })),
        ]
      : []),

    h("div", { className: "sv-sect" }, tr("salav2.nav.mas", "Más")),
    h(Link, { href: "../Biblioteca.dc.html", icon: "▤", label: tr("nav.biblioteca", "Biblioteca") }),
    h(Link, { href: "../Settings.dc.html", icon: "⚙", label: tr("nav.ajustes", "Ajustes") }),
  );
}
