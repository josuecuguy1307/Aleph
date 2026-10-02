// LA TARJETA DE LA OBRA — el trabajo aparece DONDE el usuario está mirando.
// [Gate 4 · Fase 4 · obra O6b · 4.3 · ley 6 · B10 · LEY 15]
//
// QUÉ RESUELVE
// ------------
// Hasta hoy, cuando un turno producía algo, la obra aparecía SOLA en la columna de la
// derecha. El usuario estaba leyendo el hilo y el resultado de su trabajo nacía fuera de su
// campo de visión. Y esa columna existía SIEMPRE —vacía— justamente para que aparecer no
// moviera el chat de lugar (el defecto que el pulido de Fase 1 pagó).
//
// La ley 6 dice cómo tiene que ser: *Sala mínima → tarjeta inline con preview → selector
// filtrado por stack → auto por preferencia*. O sea: **el trabajo se anuncia en el hilo**, y
// crecer es una decisión del usuario.
//
// LA REGLA QUE HACE POSIBLE B10 SIN REABRIR EL DEFECTO DE FASE 1
// --------------------------------------------------------------
// El defecto era *«una columna que va y viene mueve el chat a mitad de una conversación»*.
// La palabra que importa es **SOLA**: lo intolerable es el movimiento que el usuario no
// pidió. Así que:
//
//   · una obra nueva **NUNCA** abre el canvas — nace esta tarjeta, en el flujo del hilo,
//     que es donde el usuario ya está mirando y donde nada se corre de lugar;
//   · el canvas **sólo** se abre (y se cierra) por una acción del usuario. Si él lo pidió,
//     el movimiento es la consecuencia de su gesto, no una sorpresa.
//
// «TAP → EL PREVIEW CRECE AL WORKSPACE»
// -------------------------------------
// Crecer tiene DOS destinos y los decide el aplicador único de O5
// (`GET /v1/workspaces/destino`), no esta tarjeta: si algún workspace instalado reclama el
// tipo, la tarjeta ofrece ese lugar con su nombre; si no lo reclama nadie, crece al canvas
// de La Sala, que es el suelo (ley 4). **La tarjeta no opina**: muestra lo que el aplicador
// resolvió, con el motivo que él redactó.
//
// LEY 15: acá no hay ni una mención de agente, y no es casualidad. Una obra tiene un TIPO y
// un lugar donde vivir; que la haya producido un agente o un modelo en seco no cambia nada
// de esta superficie. El agente es aditivo, no un requisito de la transición.

import { React } from "../vendor/assistant-ui.bundle.js";

const h = React.createElement;
const tr = (clave, fallback) => {
  const s = typeof window !== "undefined" && window.t ? window.t(clave) : null;
  return s && s !== clave ? s : fallback;
};

/** El tipo, en la palabra que el usuario usa. Sale del vocabulario único de 2.3. */
const NOMBRE_TIPO = {
  informe: "informe",
  imagen: "imagen",
  planilla: "planilla",
  ficha: "ficha",
  cad: "plano",
  convergence: "convergencia",
};

/**
 * El preview en lenguaje llano. **No se genera contenido**: se recorta lo que la obra ya
 * tiene. Un preview inventado sería exactamente lo que el anti-grift existe para atrapar.
 */
function preview(obra) {
  const cuerpo = String(obra?.content || "");
  if (!cuerpo) return "";
  let texto = cuerpo;
  if (cuerpo.trim().startsWith("{")) {
    try {
      const j = JSON.parse(cuerpo);
      texto = String(j.content || j.summary || j.title || "");
      if (!texto && Array.isArray(j.rows)) {
        texto = tr("salav2.tarjeta.filas", "{n} filas").replace("{n}", j.rows.length);
      }
    } catch (_) {
      texto = cuerpo;
    }
  }
  return texto.replace(/[#*`>|]/g, " ").replace(/\s+/g, " ").trim().slice(0, 180);
}

export function TarjetaObra({ obra, destino, onAbrir, onIrAlWorkspace }) {
  if (!obra) return null;
  const tipo = NOMBRE_TIPO[obra.type] || obra.type || "obra";
  const texto = preview(obra);
  // El destino lo resolvió el aplicador. Sin destino, la obra crece acá — que no es un
  // estado degradado: es el suelo (ley 4).
  const alWorkspace = destino && destino.destino ? destino : null;

  return h(
    "div",
    { className: "sv-tarjeta-obra", "data-tipo": obra.type || "", role: "group",
      "aria-label": obra.title || tipo },
    h(
      "div",
      { className: "sv-tarjeta-cab" },
      h("span", { className: "sv-tarjeta-tipo" }, tipo),
      h("span", { className: "sv-tarjeta-tit", "data-no-tm": "" }, obra.title || tr("salav2.canvas.sin_titulo", "Sin título")),
    ),
    texto ? h("p", { className: "sv-tarjeta-preview", "data-no-tm": "" }, texto) : null,
    h(
      "div",
      { className: "sv-tarjeta-acciones" },
      h(
        "button",
        { type: "button", className: "sv-tarjeta-btn", onClick: () => onAbrir?.(obra.id) },
        tr("salav2.tarjeta.abrir", "Abrir aquí"),
      ),
      alWorkspace
        ? h(
            "button",
            {
              type: "button",
              className: "sv-tarjeta-btn sv-tarjeta-btn--ws",
              // El motivo lo redactó el aplicador; la tarjeta no inventa su propia
              // explicación de por qué ese lugar.
              title: alWorkspace.copy || "",
              onClick: () => onIrAlWorkspace?.(alWorkspace.destino, obra.id),
            },
            tr("salav2.tarjeta.crecer", "Abrir en {ws}")
              .replace("{ws}", (alWorkspace.candidatos?.[0]?.label) || alWorkspace.destino),
          )
        : null,
    ),
    // AMBIGÜEDAD: la ley 6 dice UNA LÍNEA, jamás una galería. La línea viene del aplicador.
    destino && destino.motivo === "ambiguo" && destino.pregunta
      ? h("p", { className: "sv-tarjeta-pregunta" }, destino.pregunta)
      : null,
  );
}
