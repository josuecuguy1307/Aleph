// model-chip.js — LA CÁSCARA DE REACT DEL CHIP. El componente vive en `ui/model-chip.core.js`.
//
// [convergencia · un solo picker en las siete · decisión del dueño 2026-08-22]
//
// QUÉ PASÓ ACÁ. Este archivo ERA el chip: 209 líneas de `React.createElement` con el
// trigger, el menú, el buscador, las filas y el «＋ Añadir otro modelo». El dueño pidió ESE
// MISMO widget en las siete superficies, y un workspace es un iframe de otro origen sin
// React — así que el componente se mudó a `product/app/design/ui/model-chip.core.js`, sin
// framework, y la Sala lo consume desde acá.
//
// ⚠️ NO ES UNA SEGUNDA VERSIÓN NI UN WRAPPER DE CORTESÍA: es LA MISMA implementación. El
// markup, las clases, las marcas, el orden de las filas y el destino del ＋ salen del
// núcleo. Si mañana alguien cambia el chip, lo cambia en un solo archivo y cambia en las
// siete. Volver a pintar el markup acá sería reabrir la partición que esta obra cerró.
//
// LO ÚNICO QUE QUEDA DE ESTE LADO, y por qué no puede estar en el núcleo: `useAuiState`.
// El chip se bloquea mientras corre un turno, y ese hecho sólo lo sabe el runtime de
// assistant-ui, que existe en la Sala y en ningún otro de los siete. Así que acá se traduce
// `s.thread.isRunning` a un booleano y se le pasa al núcleo como `bloqueado`. Eso es todo.
//
// `normalizarEtiqueta` se re-exporta porque `sala-v2.js` lo importa DE ACÁ desde antes de
// esta obra; cambiarle el origen al llamador sería tocar la Sala por una razón cosmética.
import { React, useAuiState } from "../vendor/assistant-ui.bundle.js";
// El núcleo llega por `<script>` clásico desde `sala-v2.html` (ver el ⚠️ de su cabecera:
// un `import` no serviría del otro lado del borde de origen, y el archivo es UNO).
const { montarChip, normalizarEtiqueta } = window.AlephModelChip;

export function ModelChip({ choices, selectedRef, searchThreshold = 12, onSelect, lockedLabel, motores }) {
  const host = React.useRef(null);
  const mando = React.useRef(null);
  const corriendo = useAuiState((s) => s.thread.isRunning);

  // Los datos vivos en un ref: el núcleo guarda las callbacks que le pasamos, y si el
  // `onSelect` de este render quedara capturado adentro, elegir un modelo después de que la
  // Sala re-renderice llamaría al handler VIEJO. Un ref lo mantiene apuntando al de ahora.
  const vivo = React.useRef({ onSelect });
  vivo.current.onSelect = onSelect;

  React.useEffect(() => {
    if (!host.current) return undefined;
    mando.current = montarChip(host.current, {
      choices, selectedRef, searchThreshold, lockedLabel, motores,
      bloqueado: corriendo,
      onSelect: (ref) => vivo.current.onSelect?.(ref),
    });
    return () => { mando.current?.destruir(); mando.current = null; };
    // Se monta UNA vez: los cambios entran por `actualizar` abajo. Re-montarlo en cada
    // cambio de props cerraría el menú en la cara del usuario mientras elige.
  }, []);

  React.useEffect(() => {
    mando.current?.actualizar({
      choices, selectedRef, searchThreshold, lockedLabel, motores, bloqueado: corriendo,
    });
  }, [choices, selectedRef, searchThreshold, lockedLabel, motores, corriendo]);

  // Y si empieza a correr un turno con el menú abierto, se cierra — igual que antes.
  React.useEffect(() => { if (corriendo) mando.current?.cerrar(); }, [corriendo]);

  return React.createElement("span", { ref: host, className: "sv-model-chip-host" });
}

export { normalizarEtiqueta };
