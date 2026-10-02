/**
 * aleph-frame.tsx — EL FRAME DE ALEPH, ESCRITO EN EL COMPONENTE (Ciencia · SolidJS).
 * [rediseño · CIENCIA · el frame · Ley 6, archivo NUESTRO dentro de un árbol ajeno]
 *
 * POR QUÉ ESTE ARCHIVO EXISTE, Y POR QUÉ ACÁ ES DISTINTO. En los otros cuatro verticales el
 * frame se MUDÓ: ya existía un `aleph-frame.tsx` de una fase anterior. Ciencia no tenía
 * ninguno — medido: `find third_party -name 'aleph-frame*'` devuelve cuatro archivos
 * (vibetrading, dochaus, deeptutor, openwork) y openscience no está. Lo único de Aleph que
 * este stack tenía era la HOJA (`public/aleph-piel.css` + `aleph-piel.js`), o sea color y
 * letra sin barra. Acá el shell se CONSTRUYE.
 *
 * ⚠️ Y LA INYECCIÓN NUNCA LE LLEGÓ. `aleph-piel.js` monta su cabecera y su pie anclando en
 * `[data-sidebar="sidebar"], [data-slot="sidebar-inner"]`, y openscience no expone ninguno
 * de los dos (grep = 0 en `src/`). O sea que con `?piel=v2` puesto a mano, Ciencia mostraba
 * el riel de la casa escondido por CSS y NINGUNA cabecera de Aleph: media cara. Es lo que
 * `piel.js` ya dejaba anotado en su tabla `POR_ESPACIO`.
 *
 * ⚠️ LO QUE ESTE ARCHIVO NO HACE: no toca un handler. Las filas que ya existían —`New`,
 * `Search`, `Files`, `Terminal`, `Compute`, `Atlas`, `Trace`, `Details`— conservan su
 * `onClick`, su estado y su comportamiento; lo único que cambia es su rótulo, su glifo y su
 * lugar. Acá sólo viven las piezas que son de Aleph y que antes no estaban en ningún lado:
 * la marca, `‹ Inicio`, `⚙ Settings` y la cuenta.
 *
 * ⚠️ LOS BOTONES DE ACÁ NO NAVEGAN: PIDEN. Corremos en un `<iframe>` de OTRO ORIGEN, así que
 * `parent.location` es inalcanzable. Se le pide el destino a la cáscara por `postMessage` y
 * ella —que sí conoce su ruta— resuelve. Los contratos ya existían todos: `aleph-go-home`,
 * `aleph-open-settings` y `aleph-go-home`.
 */
import { For, Show, createSignal, onCleanup, onMount, type JSX } from "solid-js"
import { useDialog } from "@synsci/ui/context/dialog"
import { DialogSettings } from "../components/dialog-settings"
import { useLanguage } from "@/context/language"

/** Los parámetros que la casa pasa en la URL del iframe. */
export type AlephFrameInfo = {
  activo: boolean
  espacio: string
  etiqueta: string
  usuario: string
  rol: string
  /** El panel de ajustes que la casa pide abrir (`aleph_panel`). Vacío = ninguno. */
  panel: string
}

/* ⚠️ SE LEEN UNA SOLA VEZ, AL CARGAR, Y ESTO ES LOAD-BEARING. `src/aleph.ts` de este mismo
 * repo ya lo dejó escrito: «la casa los pasa en la URL del `<iframe>`, y en cuanto el router
 * de esta app navega a un proyecto el `search` se pierde». Leerlos tarde daría «no estoy
 * adentro de Aleph» justo después del primer click — y acá el primer click es automático,
 * porque `home.tsx` entra solo al proyecto cuando `dentroDeAleph`. */
const LEIDO: AlephFrameInfo = (() => {
  const vacio = { activo: false, espacio: "", etiqueta: "", usuario: "", rol: "", panel: "" }
  if (typeof window === "undefined") return vacio
  try {
    const q = new URLSearchParams(window.location.search)
    const guardado = (k: string) => {
      const v = q.get(k)
      if (v) {
        try {
          window.sessionStorage.setItem("aleph." + k, v)
        } catch {
          /* modo privado */
        }
        return v
      }
      try {
        return window.sessionStorage.getItem("aleph." + k) || ""
      } catch {
        return ""
      }
    }
    const piel = guardado("aleph_piel")
    return {
      // El frame vive detrás del MISMO interruptor que la piel: con el flag apagado, esta
      // barra queda exactamente como estaba hoy.
      activo: piel === "v2" && window.parent !== window,
      espacio: guardado("aleph_ws"),
      etiqueta: guardado("aleph_label"),
      /* Quién sos lo sabe la casa, no este stack: llega por la misma URL que el resto. Es
       * sólo el rótulo — ni id ni token. Mismo camino que Finanzas dejó abierto. */
      usuario: guardado("aleph_user"),
      rol: guardado("aleph_rol"),
      /* Sólo se lee de la URL, NUNCA de `sessionStorage`: es un pedido de UNA visita, no
       * un estado del espacio. Guardarlo reabriría el panel en cada recarga. */
      panel: (() => { try { return q.get("aleph_panel") || "" } catch { return "" } })(),
    }
  } catch {
    return vacio
  }
})()

/** El frame de esta página. El valor no cambia en toda la vida del documento. */
export function alephFrame(): AlephFrameInfo {
  return LEIDO
}

const pedir = (mensaje: unknown) => {
  try {
    window.parent.postMessage(mensaje, "*")
  } catch {
    /* nunca tumbar la barra por un postMessage */
  }
}

/* ── LOS GLIFOS ───────────────────────────────────────────────────────────────────────
 * Salen del artboard (`Aleph Ciencia.dc.html`, pantalla 3a), trazo por trazo: viewBox 20,
 * `stroke-width` 1.5 salvo donde el dibujo pide otro, y el color por `currentColor` para que
 * el activo tiña el glifo junto con el rótulo. La hoja del estándar lo pide así: «cada
 * espacio tiene su glifo de línea propio, mismo trazo y mismo tamaño que el resto».
 *
 * Atlas, Trace y Details NO están dibujados en el artboard —en la captura estaban apagados,
 * que es distinto de no existir— así que se dibujan en la misma familia y no se les cambia
 * el significado. Es la lección del DATO VACÍO: un control que hoy no se ve no es un control
 * que sobra. */
function Glifo(props: { children: JSX.Element; size?: number; ancho?: number }) {
  return (
    <svg
      width={props.size ?? 16}
      height={props.size ?? 16}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      stroke-width={props.ancho ?? 1.5}
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      {props.children}
    </svg>
  )
}

export const GlifoNuevo = () => (
  <Glifo ancho={1.7}>
    <path d="M10 4v12M4 10h12" />
  </Glifo>
)
export const GlifoBuscar = () => (
  <Glifo>
    <circle cx="9" cy="9" r="5.5" />
    <path d="M13.2 13.2 17 17" />
  </Glifo>
)
export const GlifoBiblioteca = () => (
  <Glifo>
    <rect x="3" y="3" width="6" height="6" rx="1.4" />
    <rect x="11" y="3" width="6" height="6" rx="1.4" />
    <rect x="3" y="11" width="6" height="6" rx="1.4" />
    <rect x="11" y="11" width="6" height="6" rx="1.4" />
  </Glifo>
)
export const GlifoTerminal = () => (
  <Glifo>
    <path d="M4 6l3 3-3 3M10 14h6" />
  </Glifo>
)
export const GlifoCompute = () => (
  <Glifo>
    <rect x="5.5" y="5.5" width="9" height="9" rx="1.6" />
    <path d="M8 2.5v2M12 2.5v2M8 15.5v2M12 15.5v2M2.5 8h2M2.5 12h2M15.5 8h2M15.5 12h2" />
  </Glifo>
)
export const GlifoAtlas = () => (
  <Glifo>
    <path d="M3 5.5 7.5 4l5 1.5L17 4v10.5L12.5 16l-5-1.5L3 16z" />
    <path d="M7.5 4v10.5M12.5 5.5V16" />
  </Glifo>
)
export const GlifoTrace = () => (
  <Glifo>
    <path d="M2.5 10h3l2-5 3 10 2-5h5" />
  </Glifo>
)
export const GlifoDetalle = () => (
  <Glifo>
    <path d="M11.5 2.5H6a1.5 1.5 0 0 0-1.5 1.5v12A1.5 1.5 0 0 0 6 17.5h8a1.5 1.5 0 0 0 1.5-1.5V6.5z" />
    <path d="M11.5 2.5v4h4" />
  </Glifo>
)
export const GlifoAjustes = () => (
  <Glifo>
    <circle cx="10" cy="10" r="2.9" />
    <circle cx="10" cy="10" r="6.1" />
    <path d="M10 2.6v1.9M10 15.5v1.9M2.6 10h1.9M15.5 10h1.9M4.8 4.8l1.35 1.35M13.85 13.85l1.35 1.35M15.2 4.8l-1.35 1.35M6.15 13.85L4.8 15.2" />
  </Glifo>
)
/** El chevron de `‹ Inicio`. En el artboard de Ciencia esa fila es una FILA como las otras
 *  —glifo en la columna de 20, rótulo en 14/400— y no el texto «‹ Inicio» que dibuja el
 *  artboard de Finanzas. Manda el de este espacio. */
export const GlifoAtras = () => (
  <Glifo size={15} ancho={1.8}>
    <path d="M12 5l-5 5 5 5" />
  </Glifo>
)

/** El clip del composer. El artboard lo dibuja en 18 y con este trazo exacto; el set de
 *  íconos de este stack no tiene ninguno equivalente (78 nombres, contados). */
export const GlifoClip = () => (
  <Glifo size={18}>
    <path d="M12.6 7.7 8 12.3a2.4 2.4 0 0 0 3.4 3.4l5.1-5.1a4 4 0 0 0-5.7-5.7l-5.5 5.5a5.6 5.6 0 0 0 7.9 7.9" />
  </Glifo>
)

/** El glifo de plegar la barra: caja de 26 con radio 7 y el panel de 15, como el artboard. */
const GlifoPanel = () => (
  <Glifo size={15}>
    <rect x="3" y="4" width="14" height="12" rx="2" />
    <path d="M8 4v12" />
  </Glifo>
)

/** La mascota, la misma que la casa sirve en `/aleph-mascot-v2.png`, en SVG para no depender
 *  de una request que puede fallar y dejar la marca coja. */
export function Mascota(props: { size?: number; trazo?: number }) {
  const s = () => props.size ?? 24
  /* El artboard dibuja la mascota chica con trazo 1.2 y la GRANDE con .85: el mismo trazo a
     92px se lee pesado. Es un dato del dibujo, no una preferencia. */
  const t = () => props.trazo ?? 1.2
  return (
    <svg width={s()} height={s()} viewBox="0 0 24 24" fill="none" aria-hidden="true" style={{ flex: "none" }}>
      <ellipse cx="12" cy="12" rx="10.4" ry="4.4" stroke="#cdbcfa" stroke-width={t()} />
      <ellipse cx="12" cy="12" rx="10.4" ry="4.4" stroke="#cdbcfa" stroke-width={t()} transform="rotate(60 12 12)" />
      <ellipse cx="12" cy="12" rx="10.4" ry="4.4" stroke="#cdbcfa" stroke-width={t()} transform="rotate(120 12 12)" />
      <circle cx="12" cy="12" r="4.6" fill="#b39cf7" />
      <path
        d="M10.1 11.6c.35-.6.95-.6 1.3 0M12.6 11.6c.35-.6.95-.6 1.3 0"
        stroke="#2e2749"
        stroke-width="1.05"
        stroke-linecap="round"
      />
    </svg>
  )
}

/**
 * UNA FILA DE LA BARRA. Las clases son las del frame COMPARTIDO (`aleph-frame-fila*`), que
 * viven en `public/aleph-piel.css` y son las mismas en los seis stacks: una fila de Ciencia
 * y una de Finanzas tienen que medir igual, y eso no se sostiene con dos hojas.
 *
 * ⚠️ ESTA FILA NO SABE LO QUE HACE. Recibe el `onClick` de quien ya lo tenía. Es la regla
 * que gobierna toda la obra: se mueve el frente, no la lógica.
 */
export function FilaFrame(props: {
  glifo: JSX.Element
  rotulo: string
  /** El atajo, en mono, tal como el artboard lo pone en `Search`. */
  atajo?: string
  /** Un valor al final de la fila (`Local` en Compute). */
  valor?: string
  /** Un número al final, en mono (`128` en Library). */
  cuenta?: number
  /** El punto de estado: verde = vivo, apagado = sin nada corriendo. */
  punto?: "vivo" | "quieto"
  activa?: boolean
  primaria?: boolean
  disabled?: boolean
  ariaLabel?: string
  onWarm?: () => void
  onClick: () => void
}): JSX.Element {
  return (
    <button
      type="button"
      class="aleph-frame-fila"
      classList={{ "aleph-frame-fila-primaria": props.primaria }}
      data-activa={props.activa ? "true" : undefined}
      aria-pressed={props.activa === undefined ? undefined : props.activa}
      aria-label={props.ariaLabel ?? props.rotulo}
      disabled={props.disabled}
      onPointerEnter={() => props.onWarm?.()}
      onFocus={() => props.onWarm?.()}
      onClick={() => props.onClick()}
    >
      <span class="aleph-frame-fila-glifo">{props.glifo}</span>
      <span class="aleph-frame-fila-txt">{props.rotulo}</span>
      <Show when={props.punto}>
        <span class="aleph-frame-fila-punto" data-estado={props.punto} aria-hidden="true" />
      </Show>
      <Show when={props.valor}>
        <span class="aleph-frame-fila-valor">{props.valor}</span>
      </Show>
      <Show when={typeof props.cuenta === "number"}>
        <span class="aleph-frame-fila-num">{props.cuenta}</span>
      </Show>
      <Show when={props.atajo}>
        <kbd class="aleph-frame-fila-atajo">{props.atajo}</kbd>
      </Show>
    </button>
  )
}

/**
 * La marca + el nombre del espacio + plegar, y debajo `‹ Inicio` con su línea.
 * El diseño lo fija igual para los seis espacios (hoja del estándar, «El frame»).
 */
export function AlephFrameCabecera(props: { onPlegar?: () => void }): JSX.Element {
  const f = alephFrame()
  const language = useLanguage()

  /* ⚠️ LA MARCA QUE APAGA LA INYECCIÓN. Mientras exista este atributo en el documento,
   * `aleph-piel.js` NO monta su cabecera ni su pie. Acá no llegaba a montar nada por falta
   * de ancla, pero se declara igual: el día que alguien le agregue un `data-sidebar` a este
   * stack, dos caminos dibujando la misma barra es un defecto esperando. */
  /* ⚠️ [integración] «ABRIME PARADO EN ESTE PANEL». `Aleph Settings.dc.html` (13a) dibuja la
   * sección de Ciencia con sus filas —Skills, Specialists, Compute, Sandbox, Permissions— y
   * el dueño decidió que cada fila te lleve al espacio en esa superficie.
   *
   * Ciencia es el ÚNICO de los tres que no se resuelve solo. Finanzas y Educación rutean, así
   * que a ellos les alcanza con que la casa le cuelgue el path al origen del iframe y no hay
   * que tocar el stack. Acá los ajustes viven en un DIÁLOGO (`dialog-settings.tsx` sobre
   * `settings/registry.ts`), no en una ruta: no hay path que colgar, así que la casa manda
   * `aleph_panel` y este cuerpo lo abre. Es el MISMO `dialog.show(<DialogSettings initial=…>)`
   * que ya usan `prompt-input.tsx:264` y `dialog-select-model.tsx:211`; no es un camino nuevo.
   *
   * ⚠️ EL `try` NO ES DECORACIÓN. `useDialog()` sólo existe bajo su provider, y esta cabecera
   * también se monta en el drawer móvil. Sin el try, un espacio que hoy abre bien se caería
   * entero por una fila de Ajustes. Y el `queueMicrotask` es el de `prompt-input.tsx`: pedirle
   * al diálogo que se muestre en pleno montaje deja el overlay a medio construir. */
  const dialogo = (() => { try { return useDialog() } catch { return null } })()

  onMount(() => {
    if (!f.activo) return
    document.documentElement.setAttribute("data-aleph-frame-nativo", "1")
    if (!f.panel || !dialogo) return
    queueMicrotask(() => {
      try { dialogo.show(() => <DialogSettings initial={f.panel as never} />) } catch { /* nunca tumbar la barra */ }
    })
  })

  return (
    <div class="aleph-frame-cabecera">
      <div class="aleph-frame-marca">
        <Mascota />
        <span class="aleph-frame-wordmark">Aleph</span>
        <Show when={f.etiqueta}>
          <span class="aleph-frame-espacio">{f.etiqueta}</span>
        </Show>
        {/* ⚠️ RELOCALIZADO, NO REESCRITO: es el MISMO botón de plegar del `session-sidebar__top`,
            con el `onCollapse` que ya tenía. El artboard lo pone acá arriba y deja UN solo
            control de colapsar donde antes había dos («un solo control de colapsar, antes
            había dos», nota del artboard). */}
        <Show when={props.onPlegar}>
          <button
            type="button"
            class="aleph-frame-plegar"
            onClick={() => props.onPlegar?.()}
            title={language.t("aleph.frame.collapse")}
            aria-label={language.t("aleph.frame.collapse")}
          >
            <GlifoPanel />
          </button>
        </Show>
      </div>
      {/* ⚠️ `‹ Inicio` ES UNA FILA, no un texto. El artboard de Ciencia (3a) la dibuja con el
          mismo molde que `New chat`: chevron en la columna de 20, rótulo en 14/400 y radio 11.
          La clase `aleph-frame-inicio` de la hoja compartida viene del artboard de FINANZAS,
          que la dibuja como un `‹` pegado al texto en 13.5 — por eso acá no se usa. */}
      <FilaFrame
        glifo={<GlifoAtras />}
        rotulo={language.t("aleph.frame.home")}
        ariaLabel={language.t("aleph.frame.goHome")}
        onClick={() => pedir({ type: "aleph-go-home" })}
      />
      <div class="aleph-frame-sep" />
    </div>
  )
}

/**
 * El sub-grupo colapsable de la sección del espacio — el «Más en …» del diseño.
 *
 * ⚠️ POR QUÉ ACÁ ADENTRO Y NO SUELTO. La hoja del estándar lo dice como regla, no como
 * adorno: «lo propio de cada espacio se ANIDA en su propia sección; sólo lo verdaderamente
 * importante queda afuera». Su tabla fija para Ciencia exactamente dos filas —Terminal y
 * Compute—; las otras tres que este stack tiene (Atlas, Trace, Details) no están en el
 * artboard porque en esa captura estaban APAGADAS, que no es lo mismo que no existir.
 * Sacarlas sería perder controles; dejarlas planas sería contradecir la tabla. Se anidan.
 *
 * Es el MISMO cuerpo y las MISMAS clases que `AlephFrameMas` de Educación y que el «Más en
 * Finanzas»: la hoja compartida ya declara `.aleph-frame-mas-cab`, `-flecha` y `-cuerpo`.
 * Abierto por default, como los otros dos.
 */
export function AlephFrameMas(props: { titulo: string; children: JSX.Element }): JSX.Element {
  const [abierto, setAbierto] = createSignal(true)
  return (
    <div class="aleph-frame-mas">
      <button
        type="button"
        class="aleph-frame-mas-cab"
        onClick={() => setAbierto((v) => !v)}
        aria-expanded={abierto()}
      >
        <span class="aleph-frame-mas-flecha">{abierto() ? "\u02c5" : "\u02c3"}</span>
        <span>{props.titulo}</span>
      </button>
      <Show when={abierto()}>
        <div class="aleph-frame-mas-cuerpo">{props.children}</div>
      </Show>
    </div>
  )
}

/**
 * La etiqueta de grupo en mono con su contador, tal como el diseño la fija
 * (`CIENCIA`, `RECENT SESSIONS 55`). Es presentación pura: el número se lo pasa quien lo
 * tiene, no se calcula acá.
 */
export function AlephFrameGrupo(props: { texto: string; cuenta?: number }): JSX.Element {
  return (
    <div class="aleph-frame-grupo">
      <span class="aleph-frame-grupo-txt">{props.texto}</span>
      <Show when={typeof props.cuenta === "number"}>
        <span class="aleph-frame-grupo-num">{props.cuenta}</span>
      </Show>
    </div>
  )
}

/**
 * El pie: `⚙ Settings` y la cuenta. Dos filas, y nada más.
 *
 * ⚠️ ACÁ HUBO UN CENSO Y SE FUE. Este pie llegó a dibujar además `Ir a…` y `Conectores`, los
 * dos botones que la cáscara montaba en su riel. Se vio en pantalla y el dueño lo cortó, y el
 * diseño le da la razón: `Aleph Settings.dc.html` (artboard 13a) cierra la barra con
 * `⚙ Settings` y `○ <Nombre> · <Rol>`, y nada más. Los once destinos de la casa —Conectores
 * entre ellos— se alcanzan por `‹ Inicio`, que es el primer ítem del raíz.
 */
export function AlephFramePie(): JSX.Element {
  const f = alephFrame()
  const language = useLanguage()
  return (
    <div class="aleph-frame-pie">
      <button
        type="button"
        class="aleph-frame-pie-item"
        onClick={() => {
          /* `aleph-open-settings` ya existía y `ciencia.html` ya lo resuelve desde agosto
           * (su listener está en la línea 126). No se inventa un contrato nuevo para algo
           * que la casa sabe hacer. */
          pedir({ type: "aleph-open-settings", section: "perfil" })
        }}
      >
        <span class="aleph-frame-pie-glifo" aria-hidden="true">
          <GlifoAjustes />
        </span>
        <span>{language.t("aleph.frame.settings")}</span>
      </button>

      {/* La cuenta del pie. El nombre y el rol los manda la casa; si no vinieron —sin sesión
          todavía— no se dibuja una fila con un avatar mudo: se dibuja nada. */}
      <Show when={f.usuario}>
        <div class="aleph-frame-cuenta">
          <span class="aleph-frame-cuenta-ava" aria-hidden="true" />
          <span class="aleph-frame-cuenta-txt">
            <span class="aleph-frame-cuenta-nom">{f.usuario}</span>
            <Show when={f.rol}>
              <span class="aleph-frame-cuenta-rol">{f.rol}</span>
            </Show>
          </span>
        </div>
      </Show>
    </div>
  )
}
