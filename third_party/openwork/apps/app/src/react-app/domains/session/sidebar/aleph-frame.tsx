/**
 * aleph-frame.tsx — EL FRAME DE ALEPH, ESCRITO EN EL COMPONENTE.
 * [rediseño · fase 6 · Ley 6, tercera cirugía · archivo NUESTRO dentro de un árbol ajeno]
 *
 * POR QUÉ ESTE ARCHIVO EXISTE. Hasta la fase 5 la cabecera de Aleph se INYECTABA por DOM
 * desde `aleph-piel.js`, desde afuera de React. Medido con una sonda: eso encimaba el rótulo
 * «WORKSPACES» con la primera sesión, y apagando sólo la inyección el encimado desaparecía.
 * La causa es el `m.div layoutScroll` de framer-motion en `app-sidebar.tsx`: mide posiciones
 * al montar y queda con transforms viejos cuando le meten nodos después. Montar por encima no
 * podía arreglarlo — el frame tenía que estar ESCRITO en el componente. El dueño autorizó
 * abrir el cuerpo el 2026-09-07 y la Ley 6 se reescribió para admitirlo.
 *
 * ⚠️ LO QUE ESTE ARCHIVO NO HACE: no toca un handler. Los ítems que ya existían —New task,
 * Search sessions, Library, las sesiones— conservan su `onClick`, su estado y su
 * comportamiento; lo único que cambia es su rótulo y su lugar. Acá sólo viven las piezas que
 * son de Aleph y que antes no estaban en ningún lado: la marca, `‹ Inicio` y `⚙ Settings`.
 *
 * ⚠️ LOS DOS BOTONES DE ACÁ NO NAVEGAN: PIDEN. Corremos en un `<iframe>` de OTRO ORIGEN, así
 * que `parent.location` es inalcanzable y un `<a target="_top">` queda bloqueado. Se le pide
 * el destino a la cáscara por `postMessage` y ella —que sí conoce su ruta— resuelve. Los dos
 * contratos ya existían: `aleph-go-home` desde la fase 3 y `aleph-open-settings` desde agosto.
 */
import { useEffect, useState, type ReactNode } from "react";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { t } from "@/i18n";

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
 *  de una request que puede fallar y dejar la marca coja.
 *
 *  ⚠️ UNA SOLA MASCOTA, EXPORTADA. La hoja del estándar es explícita: «Un solo Aleph … se
 *  cayeron las otras tres versiones que había». El saludo del inicio de sesión la pide en 92
 *  px y la cabecera en 20; es el mismo dibujo con otro tamaño, no un segundo archivo. */
export function Mascota({ size = 20 }: { size?: number }) {
  /* El mockup dibuja los anillos con trazo .85 en la versión grande y 1.2 en la chica: a 92 px
   * un trazo de 1.2 se ve pesado. Es el mismo criterio óptico que la hoja aplica al peso de la
   * letra, no dos dibujos distintos. */
  const anillo = size >= 48 ? 0.85 : 1.2;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <ellipse cx="12" cy="12" rx="10.4" ry="4.4" stroke="#cdbcfa" strokeWidth={anillo} />
      <ellipse cx="12" cy="12" rx="10.4" ry="4.4" stroke="#cdbcfa" strokeWidth={anillo} transform="rotate(60 12 12)" />
      <ellipse cx="12" cy="12" rx="10.4" ry="4.4" stroke="#cdbcfa" strokeWidth={anillo} transform="rotate(120 12 12)" />
      <circle cx="12" cy="12" r="4.6" fill="#b39cf7" />
      <path d="M10.1 11.6c.35-.6.95-.6 1.3 0M12.6 11.6c.35-.6.95-.6 1.3 0" stroke="#2e2749" strokeWidth={size >= 48 ? 1 : 1.05} strokeLinecap="round" />
    </svg>
  );
}

/**
 * La marca + el nombre del espacio + `‹ Inicio`, arriba de todo.
 * El diseño (pantallas 02-05, 10 y 11) lo fija igual para los seis espacios.
 */
export function AlephFrameHeader({ acciones }: { acciones?: ReactNode }) {
  const f = useAlephFrame();

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
        <span className="aleph-frame-acciones">
          {acciones}
          {/* EL COLAPSAR DEL MOCKUP. La cabecera del diseño lo dibuja a la derecha de la fila
              de la marca, y este stack ya lo tiene: `SidebarTrigger` es su primitiva, con su
              `toggleSidebar` y su atajo. Se usa EL SUYO, no un botón nuevo que llame a lo
              mismo. El de la barra de arriba —`chat/session-page.tsx`— se apaga con el frame
              prendido para que no queden dos disparadores del mismo interruptor. */}
          <SidebarTrigger className="aleph-frame-colapsar" />
        </span>
      </div>
      <button
        type="button"
        className="aleph-frame-inicio"
        onClick={() => {
          try { window.parent.postMessage({ type: "aleph-go-home" }, "*"); } catch { /* nunca tumbar la barra */ }
        }}
      >
        ‹ {t("aleph.frame.home")}
      </button>
      <div className="aleph-frame-sep" />
    </div>
  );
}


/** Quién sos EN ALEPH. Nunca la identidad que este stack conoce. */
type Identidad = { nombre: string; linea: string };

/**
 * El pie: `⚙ Settings` y la cuenta. Dos filas, y nada más.
 *
 * ⚠️ ACÁ HUBO UN CENSO Y SE FUE. Este pie llegó a dibujar además `Ir a…` y `Conectores`, los
 * dos botones que la cáscara montaba en su riel y que se quedaron sin casa cuando el riel se
 * borró. La sesión de integración se los devolvió por un censo del pie, se vio en
 * pantalla y el dueño lo cortó. El diseño le da la razón: `Aleph Settings.dc.html`
 * (artboard 13a) y el 38a de Legal cierran la barra exactamente así:
 *
 *     ──────────────────────────────
 *     ⚙ Settings
 *     ○ <Nombre> · <Rol>
 *
 * Los once destinos de la casa —Conectores entre ellos— se alcanzan por `‹ Inicio`, que es el
 * primer ítem del raíz y está en los seis. El camino existe; lo que sobraba eran dos filas que
 * el diseño no dibuja.
 *
 * ⚠️ LA CUENTA ES LA DE ALEPH, Y POR ESO SE PIDE. El menú de cuenta de este stack sigue
 * apagado al embeber y tiene que seguir apagado: la identidad que conoce es la SUYA, y
 * pintarla sería mostrarle al usuario una cuenta que no es la que tiene en la casa. El diseño
 * pide igual la fila, así que se la pedimos a quien sí la sabe. Mientras la casa no conteste,
 * la fila no se dibuja — un avatar con un nombre inventado sería peor que el hueco.
 */
export function AlephFrameFooter() {
  const f = useAlephFrame();
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
    /* Se pregunta después de suscribirse, nunca antes: al revés la respuesta puede llegar
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

  return (
    <div className="aleph-frame-pie">
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
        <span>{t("aleph.frame.settings")}</span>
      </button>


      {yo ? (
        <div className="aleph-frame-cuenta">
          <span className="aleph-frame-cuenta-ava" aria-hidden="true" />
          <span className="aleph-frame-cuenta-txt">
            <span className="aleph-frame-cuenta-nom">{yo.nombre}</span>
            {/* La clase se llama `-rol` porque así la bautizó Finanzas, que llegó primero a
                esta hoja compartida, y un elemento del estándar con dos nombres es peor que un
                nombre imperfecto. Pero acá adentro NO va un rol: Oficina no conoce ninguno, así
                que pinta el mail de la cuenta de Aleph, que es el dato real que la casa
                contesta. Si algún día la casa manda un rol, entra por acá sin tocar la hoja. */}
            {yo.linea ? <span className="aleph-frame-cuenta-rol">{yo.linea}</span> : null}
          </span>
        </div>
      ) : null}
    </div>
  );
}
