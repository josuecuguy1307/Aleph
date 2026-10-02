// EL CANVAS — la mitad derecha de La Sala. [Gate 4 · Fase 3 · obra 3.0 · deuda D3]
//
// FASE1 §6 dejó esto dicho sin rodeos: «la Sala vieja son dos columnas: chat + obra
// renderizada; sala-v2 hoy es sólo el chat. Quien la camine esperando "la vieja con cara
// nueva" va a encontrar la mitad derecha vacía». Esto es la mitad derecha.
//
// QUÉ NO SE REESCRIBE: el dibujo. `SalaRender` (`render/sala-render.js`) es el registro de formas
// que 2.3 cableó al vocabulario único y 2.4 dotó de `unmount`/`onTeardown`/`isDead`. Es el
// MISMO registro que usa la Sala vieja, cargado como script clásico (su IIFE se protege de
// la doble carga). Un segundo registro para la pantalla nueva habría sido la quinta lista
// de tipos justo después de que 2.3 matara las cuatro.
//
// EL CICLO, QUE ES LA MITAD DEL TRABAJO: `SalaRender.renderArtifact` ya desmonta lo anterior
// (2.4), pero eso no alcanza acá — cuando el componente se va (cambiar de hilo, cerrar el
// canvas, desmontar la app) React saca el nodo del árbol y NADIE apagaría lo que ese nodo
// prendió. Medido en 2.4: el autoplay de `convergence` redibuja un heatmap entero cada 1,4 s
// dentro de un nodo que ya nadie mira, y cada iframe sostiene un documento y un contexto
// WebGL. Por eso el efecto de abajo devuelve su cleanup: montar y desmontar son simétricos.
//
// LO QUE EL HEADER MUESTRA ES LO QUE EL DISCO TIENE: título, tipo canónico, cuántas
// versiones hay y de qué calidad es su procedencia. Nada de eso se deriva de la pantalla —
// sale del artefacto que devolvió el borde de escritura.

import { React } from "../vendor/assistant-ui.bundle.js";

const h = React.createElement;

const tr = (clave, fallback) => {
  const s = typeof window !== "undefined" && window.t ? window.t(clave) : null;
  return s && s !== clave ? s : fallback;
};

/** Cuánto vale la procedencia de esta obra, en una palabra que se entienda. */
function textoCalidad(prov) {
  if (!prov) return tr("salav2.canvas.prov.legacy", "sin registro de origen");
  switch (prov.capture_quality) {
    case "exact":
      return tr("salav2.canvas.prov.exact", "origen verificado");
    case "declared":
      return prov.workspace
        ? tr("salav2.canvas.prov.workspace", "producido por {w}").replace("{w}", prov.workspace)
        : tr("salav2.canvas.prov.declared", "origen declarado");
    case "partial":
      return tr("salav2.canvas.prov.partial", "origen parcial");
    default:
      return tr("salav2.canvas.prov.unknown", "sin registro de origen");
  }
}

/**
 * El dibujo. Un host propio + `SalaRender`, con el ciclo cerrado de los dos lados.
 *
 * `obra` es el objeto que el renderer espera: `{type, content, …}`. El artefacto del
 * almacén guarda el contenido rico como JSON en `content` (así lo hace la Sala vieja para
 * planilla/convergence/cad/…): si parsea a un objeto con `type`, ESE es el que se dibuja.
 */
function Dibujo({ obra }) {
  const host = React.useRef(null);

  React.useEffect(() => {
    const el = host.current;
    if (!el) return undefined;
    const R = typeof window !== "undefined" ? window.SalaRender : null;
    if (!R) {
      // FALLO VISIBLE: sin el registro de formas no se dibuja nada, y se dice. Pintar el
      // markdown crudo como si tal cosa escondería que la pantalla está a medias.
      el.textContent = tr("salav2.canvas.sin_render", "No pude cargar el dibujador de obras.");
      return undefined;
    }
    R.renderArtifact(el, obra);
    return () => {
      // El desmontaje que 2.4 construyó: apaga timers, le pone about:blank a cada iframe
      // ANTES de sacarlo, marca el nodo muerto y vacía el host.
      try {
        R.unmount(el);
      } catch (_) {
        /* desmontar jamás rompe el desmontaje */
      }
    };
  }, [obra]);

  // DOS nodos, y hace falta: los renderers de `SalaRender` PISAN el `className` del nodo
  // que reciben (`el.className = "sala-canvas sala-informe"`, y así cada forma). Si le
  // pasáramos el contenedor, el scroll y el padding de esta columna se perderían en el
  // primer dibujo — medido: tras renderar, `.sv-canvas-host` dejaba de existir.
  // El de afuera es la caja de la columna; el de adentro es del registro de formas.
  return h("div", { className: "sv-canvas-host" }, h("div", { ref: host }));
}

/** Una fila de la Biblioteca. */
function ItemBiblioteca({ art, activo, onAbrir }) {
  return h(
    "button",
    {
      type: "button",
      className: "sv-lib-item",
      "aria-current": activo ? "true" : undefined,
      onClick: () => onAbrir(art.id),
      title: art.title || "",
    },
    h("span", { className: "sv-lib-tit" }, art.title || tr("salav2.canvas.sin_titulo", "Sin título")),
    h("span", { className: "sv-lib-tipo" }, art.type || ""),
  );
}

/**
 * El canvas entero: header + obra + Biblioteca.
 *
 * @param {object[]} artefactos  lo que el almacén tiene para esta sesión
 * @param {string}   activoId    la obra en pantalla
 * @param {function} onAbrir     cambiar de obra (desmonta la anterior por el efecto de arriba)
 * @param {function} onRevertir  restaurar la última versión previa (contenido + procedencia)
 * @param {string}   urlDescarga la del artefacto activo, o null si no hay
 * @param {string}   aviso       fallo visible del almacén (crear/revertir/listar)
 */
export function Canvas({ artefactos, activo, activoId, onAbrir, onRevertir, onCerrar,
                         urlDescarga, aviso, metodo }) {
  // `artefactos` son los RESÚMENES de la Biblioteca (sin contenido ni versiones — así los
  // devuelve el almacén) y `activo` es la obra ENTERA, pedida por id cuando hay una que
  // dibujar. Mezclarlos haría que listar arrastre el cuerpo de cada obra de la sesión.
  const resumen = (artefactos || []).find((a) => a.id === activoId) || null;

  // El contenido rico viaja como JSON dentro de `content` (paridad con la Sala vieja). Si
  // parsea y trae `type`, es la obra; si no, el artefacto ES la obra.
  const obra = React.useMemo(() => {
    if (!activo) return null;
    const bruto = activo.content;
    if (typeof bruto === "string" && bruto.trim().startsWith("{")) {
      try {
        const o = JSON.parse(bruto);
        if (o && typeof o === "object" && o.type) return o;
      } catch (_) {
        /* no era rica: se dibuja como viene */
      }
    }
    return { type: activo.type, content: bruto, title: activo.title };
  }, [activo]);

  if (!artefactos || !artefactos.length) {
    return h(
      "aside",
      { className: "sv-canvas sv-canvas-vacio", "data-testid": "sv-canvas" },
      h(
        "div",
        { className: "sv-canvas-vacio-txt" },
        tr("salav2.canvas.vacio", "Aquí aparece lo que produzcas: informes, planillas, gráficos."),
      ),
      aviso ? h("div", { className: "sv-canvas-aviso", role: "status" }, aviso) : null,
    );
  }

  // Del resumen (`n_versions`) o de la obra entera, lo que haya: los dos salen del
  // disco, ninguno se deriva de la pantalla.
  const versiones = activo?.versions ? activo.versions.length : resumen?.n_versions || 0;

  return h(
    "aside",
    { className: "sv-canvas", "data-testid": "sv-canvas" },
    h(
      "header",
      { className: "sv-canvas-head" },
      h(
        "div",
        { className: "sv-canvas-id" },
        h("h2", { className: "sv-canvas-tit", "data-no-tm": "" }, (activo || resumen)?.title || tr("salav2.canvas.sin_titulo", "Sin título")),
        h(
          "div",
          { className: "sv-canvas-meta" },
          h("span", { className: "sv-canvas-tipo" }, (activo || resumen)?.type || ""),
          versiones
            ? h(
                "span",
                { className: "sv-canvas-vers", "data-testid": "sv-versiones" },
                tr("salav2.canvas.versiones", "v{n}").replace("{n}", String(versiones + 1)),
              )
            : null,
          h("span", { className: "sv-canvas-prov" }, textoCalidad(activo?.provenance)),
        ),
      ),
      h(
        "div",
        { className: "sv-canvas-acciones" },
        // [Gate 4 · F4 · O6b · B10] LO QUE SE ABRE, SE CIERRA. El canvas dejó de estar
        // siempre puesto: ahora emerge cuando el usuario lo pide, y por lo tanto tiene
        // que poder irse cuando ya no lo quiere. Sin este botón, «emergente» sería
        // «apareció y no se va», que es peor que la columna fija de antes.
        onCerrar
          ? h("button", { type: "button", className: "sv-canvas-cerrar",
                          "data-testid": "sv-cerrar-canvas",
                          title: tr("salav2.canvas.cerrar", "Cerrar"),
                          "aria-label": tr("salav2.canvas.cerrar", "Cerrar"),
                          onClick: onCerrar }, "✕")
          : null,
        versiones
          ? h(
              "button",
              {
                type: "button",
                className: "sv-btn-sec",
                "data-testid": "sv-revertir",
                onClick: () => onRevertir(activoId),
              },
              tr("salav2.canvas.revertir", "Revertir"),
            )
          : null,
        urlDescarga
          ? h(
              "a",
              { className: "sv-btn-sec", href: urlDescarga, download: "", "data-testid": "sv-descargar" },
              tr("salav2.canvas.descargar", "Descargar"),
            )
          : null,
      ),
    ),
    // [T2.6] DE DÓNDE VIENE ESTA OBRA. La guía prometía «obras que vienen de un método» y
    // la procedencia SÍ se grababa (`method_id` en el pasaporte del artefacto) — no se
    // mostraba en ningún lado. Ahora se dice, con camino a la pantalla del método.
    //
    // ⚠️ El LINK sólo si hay `method_id`. Con nombre y sin id no hay a dónde ir, y un botón
    // cuyo destino no existe es lo que la regla de `caminoDe` prohíbe: en ese caso se dice
    // el nombre en texto, honesto, sin fingir que se puede abrir.
    metodo && (metodo.name || metodo.method_id)
      ? h("div", { className: "sv-canvas-metodo", "data-testid": "sv-obra-metodo" },
          tr("salav2.canvas.viene_de", "Viene del método"), " ",
          metodo.method_id
            ? h("a", { className: "sv-metodo-link",
                       href: `../metodo/metodo.html?id=${encodeURIComponent(metodo.method_id)}` },
                metodo.name || metodo.method_id)
            : h("span", null, metodo.name))
      : null,
    aviso ? h("div", { className: "sv-canvas-aviso", role: "status" }, aviso) : null,
    obra
      ? h(Dibujo, { obra, key: activoId + ":" + (activo?.updated_at || versiones) })
      : h("div", { className: "sv-canvas-cargando" }, tr("salav2.canvas.cargando", "Abriendo la obra…")),
    h(
      "footer",
      { className: "sv-lib", "data-testid": "sv-biblioteca" },
      h("div", { className: "sv-lib-tit-sec" }, tr("salav2.canvas.biblioteca", "Biblioteca")),
      h(
        "div",
        { className: "sv-lib-lista" },
        artefactos.map((a) =>
          h(ItemBiblioteca, { key: a.id, art: a, activo: a.id === activoId, onAbrir }),
        ),
      ),
    ),
  );
}
