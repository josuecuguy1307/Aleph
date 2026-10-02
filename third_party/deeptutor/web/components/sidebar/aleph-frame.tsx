"use client";

/**
 * aleph-frame.tsx — EL FRAME DE ALEPH, ESCRITO EN EL COMPONENTE.
 * [rediseño · fase 6 · Ley 6, tercera cirugía · archivo NUESTRO dentro de un árbol ajeno]
 *
 * POR QUÉ ESTE ARCHIVO EXISTE. Hasta la fase 5 la cabecera de Aleph se INYECTABA por DOM
 * desde `aleph-piel.js`, desde afuera de React. Medido con una sonda: eso encimaba el rótulo
 * «WORKSPACES» con la primera sesión, y apagando sólo la inyección el encimado desaparecía.
 * La causa es el `m.div layoutScroll` de framer-motion en la barra de Oficina: mide posiciones
 * al montar y queda con transforms viejos cuando le meten nodos después. La lección vale para
 * los seis: el frame tiene que estar ESCRITO en el componente. El dueño autorizó abrir el
 * cuerpo el 2026-09-07 y la Ley 6 se reescribió para admitirlo.
 *
 * ⚠️ LO QUE ESTE ARCHIVO NO HACE: no toca un handler. Los ítems que ya existían —PRIMARY_NAV, SECONDARY_NAV
 * y la lista de recientes— conservan su `<Link to>`, su estado y su comportamiento; lo único que cambia es su rótulo y su lugar. Acá sólo viven las piezas que
 * son de Aleph y que antes no estaban en ningún lado: la marca, `‹ Inicio` y `⚙ Settings`.
 *
 * ⚠️ LOS DOS BOTONES DE ACÁ NO NAVEGAN: PIDEN. Corremos en un `<iframe>` de OTRO ORIGEN, así
 * que `parent.location` es inalcanzable y un `<a target="_top">` queda bloqueado. Se le pide
 * el destino a la cáscara por `postMessage` y ella —que sí conoce su ruta— resuelve. Los dos
 * contratos ya existían: `aleph-go-home` desde la fase 3 y `aleph-open-settings` desde agosto.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

/** Los parámetros que la casa pasa en la URL del iframe. */
type AlephFrame = { activo: boolean; espacio: string; etiqueta: string };

/* ⚠️ SE LEEN UNA SOLA VEZ, AL CARGAR, Y ESTO ES LOAD-BEARING. El `aleph.ts` de este mismo
 * repo ya lo dejó escrito: «la casa los pasa en la URL del `<iframe>`, y en cuanto el router
 * de esta app navega, el `search` se pierde». Leerlos tarde daría «no estoy adentro de Aleph»
 * justo después del primer click. Se leen al importar el módulo y se guardan. */
const LEIDO: AlephFrame = (() => {
  if (typeof window === "undefined") return { activo: false, espacio: "", etiqueta: "" };
  try {
    const q = new URLSearchParams(window.location.search);
    const guardado = (k: string) => {
      const v = q.get(k);
      if (v) {
        try { window.sessionStorage.setItem("aleph." + k, v); } catch { /* modo privado */ }
        return v;
      }
      try { return window.sessionStorage.getItem("aleph." + k) || ""; } catch { return ""; }
    };
    const piel = guardado("aleph_piel");
    return {
      // El frame vive detrás del MISMO interruptor que la piel: con el flag apagado, esta
      // barra queda exactamente como estaba hoy. Es la condición que el dueño puso en la
      // fase 1 y que no cambió desde entonces.
      activo: piel === "v2" && window.parent !== window,
      espacio: guardado("aleph_ws"),
      etiqueta: guardado("aleph_label"),
    };
  } catch {
    return { activo: false, espacio: "", etiqueta: "" };
  }
})();

export function useAlephFrame(): AlephFrame {
  /* El valor no cambia en toda la vida de la página; el estado es para que React no lo
   * recalcule y para que el primer render del servidor —si lo hubiera— no difiera. */
  const [f] = useState(LEIDO);
  return f;
}

/** La mascota, la misma que la casa sirve en `/aleph-mascot-v2.png`, en SVG para no depender
 *  de una request que puede fallar y dejar la marca coja. */
function Mascota() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <ellipse cx="12" cy="12" rx="10.4" ry="4.4" stroke="#cdbcfa" strokeWidth="1.2" />
      <ellipse cx="12" cy="12" rx="10.4" ry="4.4" stroke="#cdbcfa" strokeWidth="1.2" transform="rotate(60 12 12)" />
      <ellipse cx="12" cy="12" rx="10.4" ry="4.4" stroke="#cdbcfa" strokeWidth="1.2" transform="rotate(120 12 12)" />
      <circle cx="12" cy="12" r="4.6" fill="#b39cf7" />
      <path d="M10.1 11.6c.35-.6.95-.6 1.3 0M12.6 11.6c.35-.6.95-.6 1.3 0" stroke="#2e2749" strokeWidth="1.05" strokeLinecap="round" />
    </svg>
  );
}

/**
 * La marca + el nombre del espacio + `‹ Inicio`, arriba de todo.
 * El diseño (pantallas 02-05, 10 y 11) lo fija igual para los seis espacios.
 */
export function AlephFrameHeader({
  onColapsar,
  colapsarLabel,
}: {
  /** El `setCollapsed(true)` del propio stack. Sin él la cabecera no dibuja el botón. */
  onColapsar?: () => void;
  colapsarLabel?: string;
} = {}) {
  const f = useAlephFrame();
  const { t } = useTranslation();

  /* ⚠️ LA MARCA QUE APAGA LA INYECCIÓN. Mientras exista este atributo en el documento,
   * `aleph-piel.js` NO monta su cabecera ni su pie. Es la forma de que no queden DOS caminos
   * haciendo lo mismo: uno de los dos terminaría mintiendo. Se declara acá —donde el frame
   * nativo de verdad se montó— y no en una lista de stacks que hay que acordarse de tocar. */
  useEffect(() => {
    if (!f.activo) return;
    document.documentElement.setAttribute("data-aleph-frame-nativo", "1");
  }, [f.activo]);

  if (!f.activo) return null;

  return (
    <div className="aleph-frame-cabecera">
      <div className="aleph-frame-marca">
        <Mascota />
        <span className="aleph-frame-wordmark">Aleph</span>
        {f.etiqueta ? <span className="aleph-frame-espacio">{f.etiqueta}</span> : null}
        {/* ⚠️ EL BOTÓN DE COLAPSAR NO ES NUESTRO: ES EL SUYO, MUDADO. Vivía en la cabecera
            vieja del stack, que con el frame ya no se renderiza. Llega como prop con su
            MISMO `setCollapsed`; acá sólo se dibuja. Si el que monta no lo pasa —el drawer
            móvil, donde colapsar no significa nada— la cabecera queda sin él y no se
            inventa un botón que no gobierna nada. */}
        {onColapsar ? (
          <button
            type="button"
            className="aleph-frame-colapsar"
            onClick={onColapsar}
            aria-label={colapsarLabel}
            title={colapsarLabel}
          >
            <svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke="currentColor"
                 strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
              <rect x="3" y="4" width="14" height="12" rx="2" />
              <path d="M8 4v12" />
            </svg>
          </button>
        ) : null}
      </div>
      <button
        type="button"
        className="aleph-frame-inicio"
        onClick={() => {
          try { window.parent.postMessage({ type: "aleph-go-home" }, "*"); } catch { /* nunca tumbar la barra */ }
        }}
      >
        ‹ {t("Home")}
      </button>
      <div className="aleph-frame-sep" />
    </div>
  );
}

/**
 * El pie: `⚙ Settings`. El diseño pone también la cuenta (`○ Renata O. · Admin`); esa fila
 * queda como HUECO DECLARADO y no se pinta, porque la identidad que este stack conoce es la
 * suya y no la de Aleph — pintarla sería mostrarle al usuario una cuenta que no es la que
 * tiene en la casa. Se resuelve cuando la casa le pase su identidad al iframe.
 */
/**
 * La etiqueta de grupo en mono con su contador, tal como el diseño la fija
 * (`FINANZAS 62`, `RECENT SESSIONS 24`). Es presentación pura: el número se lo pasa quien
 * lo tiene, no se calcula acá.
 */
export function AlephFrameGrupo({ texto, cuenta }: { texto: string; cuenta?: number }) {
  return (
    <div className="aleph-frame-grupo">
      <span className="aleph-frame-grupo-txt">{texto}</span>
      {typeof cuenta === "number" ? <span className="aleph-frame-grupo-num">{cuenta}</span> : null}
    </div>
  );
}

/**
 * El sub-grupo colapsable «Más en <Espacio>» del diseño. Colapsado por defecto NO: el diseño
 * lo dibuja ABIERTO, con la flechita hacia abajo.
 */
export function AlephFrameMas({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  const [abierto, setAbierto] = useState(true);
  return (
    <div className="aleph-frame-mas">
      <button type="button" className="aleph-frame-mas-cab" onClick={() => setAbierto((v) => !v)} aria-expanded={abierto}>
        <span className="aleph-frame-mas-flecha">{abierto ? "\u02c5" : "\u02c3"}</span>
        <span>{titulo}</span>
      </button>
      {abierto ? <div className="aleph-frame-mas-cuerpo">{children}</div> : null}
    </div>
  );
}

/** Quién sos, según LA CASA. El stack conoce otra identidad y no es la que va acá. */
type Identidad = { nombre: string; linea: string };

/**
 * El pie: `⚙ Settings` y la cuenta. Dos filas, y nada más.
 *
 * ⚠️ ACÁ HUBO UN CENSO Y SE FUE. Este pie llegó a dibujar además `Ir a…` y `Conectores`, los
 * dos botones que la cáscara montaba en su riel y que se quedaron sin casa cuando el riel se
 * borró. La sesión de integración se los devolvió por un censo, se vio en pantalla y el dueño
 * lo cortó. El diseño le da la razón: `Aleph Settings.dc.html` (artboard 13a) y el 38a de
 * Legal cierran la barra exactamente así:
 *
 *     ──────────────────────────────
 *     ⚙ Settings
 *     ○ <Nombre> · <Rol>
 *
 * Los once destinos de la casa —Conectores entre ellos— se alcanzan por `‹ Inicio`, que es el
 * primer ítem del raíz y está en los seis.
 *
 * ⚠️ LA CUENTA ES LA DE ALEPH, Y POR ESO SE PIDE. El menú de cuenta de este stack sigue
 * apagado al embeber y tiene que seguir apagado: la identidad que conoce es la SUYA. Mientras
 * la casa no conteste, la fila no se dibuja — un avatar con un nombre inventado sería peor
 * que el hueco.
 */
export function AlephFrameFooter({ embebido = false }: { embebido?: boolean } = {}) {
  const f = useAlephFrame();
  const { t } = useTranslation();
  const [yo, setYo] = useState<Identidad | null>(null);

  useEffect(() => {
    if (!f.activo) return;
    const oir = (ev: MessageEvent) => {
      const d = (ev.data ?? {}) as { type?: string; nombre?: string; linea?: string };
      if (d.type === "aleph-identidad" && d.nombre) {
        setYo({ nombre: d.nombre, linea: d.linea ?? "" });
      }
    };
    window.addEventListener("message", oir);
    /* Se pregunta DESPUÉS de suscribirse, nunca antes: al revés la respuesta puede llegar
     * en el hueco entre el `postMessage` y el `addEventListener`. */
    try {
      window.parent.postMessage({ type: "aleph-identidad?" }, "*");
    } catch { /* nunca tumbar la barra */ }
    return () => window.removeEventListener("message", oir);
  }, [f.activo]);

  if (!f.activo) return null;

  const pedirAlPadre = (mensaje: Record<string, unknown>) => {
    try { window.parent.postMessage(mensaje, "*"); } catch { /* idem */ }
  };

  /* `embebido` es para los stacks que YA tienen su propio bloque de pie con su línea y su
   * padding — Educación lo tiene. Sin esto, el pie del frame agrega una SEGUNDA línea
   * encima de la del stack y el diseño pide una sola. */
  return (
    <div className={embebido ? "aleph-frame-pie aleph-frame-pie--embebido" : "aleph-frame-pie"}>
      <button
        type="button"
        className="aleph-frame-pie-item"
        onClick={() => {
          /* `aleph-open-settings` ya existía y la cáscara ya resuelve sección y espacio.
           * No se inventa un contrato nuevo para algo que la casa sabe hacer. */
          pedirAlPadre({ type: "aleph-open-settings", section: "perfil" });
        }}
      >
        <span className="aleph-frame-pie-glifo">⚙</span>
        <span>{t("Settings")}</span>
      </button>


      {/* LA CUENTA DEJA DE SER UN HUECO. El diseño la dibuja («○ Renata O. · Docente») y la
          identidad que este stack conoce es la SUYA, no la de Aleph — por eso se pide por
          `aleph-identidad?`. Si la casa no contesta, la fila NO se dibuja: un nombre
          inventado es peor que el hueco. */}
      {yo ? (
        <div className="aleph-frame-cuenta">
          <span className="aleph-frame-cuenta-ava" aria-hidden="true" />
          <span className="aleph-frame-cuenta-txt">
            <span className="aleph-frame-cuenta-nom">{yo.nombre}</span>
            {yo.linea ? <span className="aleph-frame-cuenta-rol">{yo.linea}</span> : null}
          </span>
        </div>
      ) : null}
    </div>
  );
}
