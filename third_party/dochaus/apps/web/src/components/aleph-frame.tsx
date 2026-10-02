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
 * ⚠️ LO QUE ESTE ARCHIVO NO HACE: no toca un handler. Los ítems que ya existían —Matters, Templates, Workflows,
 * el Settings del pie y la lista de matters— conservan su `<Link to>`, su estado y su comportamiento; lo único que cambia es su rótulo y su lugar. Acá sólo viven las piezas que
 * son de Aleph y que antes no estaban en ningún lado: la marca, `‹ Inicio` y `⚙ Settings`.
 *
 * ⚠️ LOS DOS BOTONES DE ACÁ NO NAVEGAN: PIDEN. Corremos en un `<iframe>` de OTRO ORIGEN, así
 * que `parent.location` es inalcanzable y un `<a target="_top">` queda bloqueado. Se le pide
 * el destino a la cáscara por `postMessage` y ella —que sí conoce su ruta— resuelve. Los dos
 * contratos ya existían: `aleph-go-home` desde la fase 3 y `aleph-open-settings` desde agosto.
 */
import { useEffect, useState } from "react";
import { useLanguage } from "../i18n";

/** Los parámetros que la casa pasa en la URL del iframe. */
type AlephFrame = { activo: boolean; espacio: string; etiqueta: string; usuario: string; rol: string };

/* ⚠️ SE LEEN UNA SOLA VEZ, AL CARGAR, Y ESTO ES LOAD-BEARING. El `aleph.ts` de este mismo
 * repo ya lo dejó escrito: «la casa los pasa en la URL del `<iframe>`, y en cuanto el router
 * de esta app navega, el `search` se pierde». Leerlos tarde daría «no estoy adentro de Aleph»
 * justo después del primer click. Se leen al importar el módulo y se guardan. */
const LEIDO: AlephFrame = (() => {
  if (typeof window === "undefined") return { activo: false, espacio: "", etiqueta: "", usuario: "", rol: "" };
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
      /* [integración · la fila de la cuenta] La identidad ES LA DE ALEPH, no la de este
       * stack. Su `AccountStatusMenu` sigue apagado al embeber a propósito; el nombre y la
       * línea los manda la casa por la URL, igual que el espacio y el tema. Se guardan en
       * `sessionStorage` con los demás porque el `search` se pierde en cuanto el router
       * navega — el mismo motivo que ya valía para `aleph_ws`. */
      usuario: guardado("aleph_user"),
      rol: guardado("aleph_rol"),
    };
  } catch {
    return { activo: false, espacio: "", etiqueta: "", usuario: "", rol: "" };
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
export function AlephFrameHeader({ accion }: { accion?: React.ReactNode } = {}) {
  const f = useAlephFrame();
  const { t } = useLanguage();

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
        {/* El artboard cierra esta fila con el glifo de plegar el panel, a la derecha. No se
         *  fabrica acá: lo pone el stack, con SU handler y SU estado, y este archivo sólo le
         *  presta el lugar. Sin `accion` la fila queda como estaba. */}
        {accion ?? null}
      </div>
      <button
        type="button"
        className="aleph-frame-inicio"
        onClick={() => {
          try { window.parent.postMessage({ type: "aleph-go-home" }, "*"); } catch { /* nunca tumbar la barra */ }
        }}
      >
        {t("‹ Home")}
      </button>
      <div className="aleph-frame-sep" />
    </div>
  );
}

/**
 * ⚠️ EN LEGAL ESTE PIE NO SE USA. Su barra YA TIENE su propio `Settings` con su `onOpenSettings`
 * en `sidebar-foot`, y el diseño pide exactamente eso: `⚙ Settings` abajo. Reemplazarlo por el
 * nuestro sería reimplementar un botón que ya funciona — justo lo que la regla prohíbe. Queda
 * exportado porque el archivo es el mismo en los seis stacks, pero Legal no lo monta.
 *
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

/* ⚠️ [integración · corrección del dueño] ACÁ VIVIÓ UN CENSO DEL PIE Y NO VA.
 * Esta sesión lo agregó para darle disparador a `Ir a…` y a `Conectores`, los dos botones de
 * la casa que se quedaron sin riel. Se vio en pantalla y el dueño lo cortó: **el pie del
 * diseño son DOS filas y nada más**. La hoja del estándar lo fija así, y el artboard 38a de
 * Legal termina exactamente ahí:
 *
 *     ──────────────────────────────
 *     ⚙ Settings
 *     ○ <Nombre> · <Rol>
 *
 * Los once destinos de la casa —Conectores entre ellos— se alcanzan por `‹ Inicio`, que es
 * el primer ítem del raíz y está en los seis. El camino existe; lo que sobraba eran dos filas
 * que el diseño no dibuja. La plomería de la cáscara se queda (el riel BORRADO con su pie
 * mudado al ancla, y `Conectores` montándose de verdad): esos eran defectos reales y siguen
 * arreglados, sólo que su puerta es Inicio y no esta barra. */
export function AlephFrameFooter() {
  const f = useAlephFrame();
  const { t } = useLanguage();
  if (!f.activo) return null;
  return (
    <div className="aleph-frame-pie">
      <button
        type="button"
        className="aleph-frame-pie-item"
        onClick={() => {
          /* `aleph-open-settings` ya existía y la cáscara ya resuelve sección y espacio.
           * No se inventa un contrato nuevo para algo que la casa sabe hacer. */
          try { window.parent.postMessage({ type: "aleph-open-settings", section: "perfil" }, "*"); } catch { /* idem */ }
        }}
      >
        <span className="aleph-frame-pie-glifo">⚙</span>
        <span>{t("Settings")}</span>
      </button>
      {/* [integración · la fila de la cuenta] El artboard cierra la barra con Settings Y la
          cuenta, y Legal era el único de los seis que la dejaba afuera. Si no vinieron —sin
          sesión todavía— no se dibuja una fila con un avatar mudo: se dibuja nada. Un nombre
          inventado sería peor que el hueco. */}
      {f.usuario ? (
        <div className="aleph-frame-cuenta">
          <span className="aleph-frame-cuenta-ava" aria-hidden="true" />
          <span className="aleph-frame-cuenta-txt">
            <span className="aleph-frame-cuenta-nom">{f.usuario}</span>
            {f.rol ? <span className="aleph-frame-cuenta-rol">{f.rol}</span> : null}
          </span>
        </div>
      ) : null}
    </div>
  );
}
