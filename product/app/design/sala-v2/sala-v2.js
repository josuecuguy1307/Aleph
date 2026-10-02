// EL ARRANQUE de La Sala v2.
//
// Junta las tres piezas: el runtime de assistant-ui (`useAgUiRuntime`), el adaptador
// (`AlephAgent`) y la máquina de estados. Nada de acá habla con un modelo: todo pasa por el
// adaptador, que a su vez habla con el backend de Gate 1-3 SIN MODIFICARLO.

import {
  React,
  ReactDOMClient,
  AssistantRuntimeProvider,
  useAgUiRuntime,
} from "./vendor/assistant-ui.bundle.js";
import { AlephAgent } from "./agui/aleph-agent.js?v=sala-te";
import { MaquinaDeEstados } from "./agui/estados.js?v=sala-te";
import { Hilo } from "./ui/hilo.js?v=sala-te";
import { ModelChip } from "./ui/model-chip.js?v=sala-te";
import { Sidebar, elegiblesPorStack } from "./ui/sidebar.js?v=sala-te";
// [Gate 4 · Fase 3 · obra 3.0 · deuda D3] La mitad derecha.
import { Canvas } from "./ui/canvas.js?v=sala-te";
import * as Obras from "./artefactos.js?v=sala-te";
import { buscarEnLaWeb, conFuentesCitadas, pasaporteDeFuentes,
         conDocumentosCitados } from "./buscar-web.js?v=sala-te";
import { investigarAFondo, pararInvestigacion, textoDeEtapa } from "./investigar.js?v=sala-te";
import { ensureSearchProvider } from "./search-provider.js?v=sala-te";

const h = React.createElement;

// ── sesión y llamadas ─────────────────────────────────────────────────────────────────
function usuario() {
  try {
    if (window.AlephSession?.get) return window.AlephSession.get();
    const raw = sessionStorage.getItem("puppet_user") || localStorage.getItem("puppet_user");
    return raw ? JSON.parse(raw) : null;
  } catch (_) {
    return null;
  }
}
function authHeaders(base) {
  const hh = base || {};
  const u = usuario();
  if (u && u.session_token) hh["Authorization"] = "Bearer " + u.session_token;
  return hh;
}

/**
 * Scrub de secretos para la tarjeta del gate. Se toma el de la Sala vieja si está expuesto;
 * si no, un mínimo propio. NO es una segunda política de seguridad: la real vive
 * server-side (`_safe_fn_args` ya llega scrubbeado desde el assembler). Esto es la última
 * red de la pantalla.
 */
function scrubSecrets(s) {
  return String(s ?? "").replace(
    /\b(sk-[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._-]{8,}|eyJ[A-Za-z0-9._-]{20,})/g,
    "···",
  );
}

const params = new URLSearchParams(location.search);
const PUPPET_ID = params.get("puppet") || null;

// La Sala moderna no tiene una receta propia. En RAW el chip guarda una selección por
// sesión y manda sólo su `selection_ref`; con agente, la Recipe v1 queda bloqueada y manda.


async function cargarChoices() {
  const headers = authHeaders({ Accept: "application/json" });
  const response = await fetch("/v1/model-use/choices", { headers });
  if (response.ok) return response.json();
  // Compatibilidad de despliegue: los estáticos del dev server cambian en vivo, pero sus
  // routers sólo al reiniciar. Mientras un proceso anterior siga abierto, se proyectan los
  // MISMOS picker_id y metadatos del selector v2; no se traducen aliases ni provider/model.
  if (response.status !== 404) throw new Error(`HTTP ${response.status}`);
  const legacy = await fetch("/v1/modelos/selector", { headers });
  if (!legacy.ok) throw new Error(`HTTP ${legacy.status}`);
  const data = await legacy.json();
  return {
    schema_version: "model-use/v1-compat",
    default_ref: data.default_id || null,
    search_threshold: 12,
    choices: (data.modelos || []).filter((row) => row.conectado === true && row.picker_id).map((row) => ({
      selection_ref: String(row.picker_id),
      label: String(row.label || row.picker_id),
      provider: String(row.marca || row.familia || "Aleph"),
      tier: row.tier || null,
      capabilities: row.model_use_capabilities || row.capacidades || [],
      context_window: row.context_window || null,
      cost: row.cost || null,
      default: String(row.picker_id) === String(data.default_id || ""),
    })),
  };
}

// SEAM PÚBLICO. Mismo patrón —y misma razón— que `window.__salaChat` / `window.__salaGate`
// / `window.__narrateStart` de la Sala vieja: expone las funciones y los datos REALES, no
// una copia, para que una vara mida producción y no un arnés paralelo.
//
// `onAlephEspia` / `onEstadoEspia` están vacíos en producción y no cuestan nada; la vara
// los reemplaza para registrar los eventos que YA circulan. Sin ellos, medir «¿el estado
// llegó a tiempo?» obligaría a leer píxeles, que es medir la consecuencia y no el hecho.
window.__salaV2 = {
  authHeaders,
  scrubSecrets,
  toolMeta: (nombre) => window.__salaV2._meta.get(nombre) || null,
  _meta: new Map(),
  /** La vara inyecta acá la receta del turno (evita crear un agente guardado sólo para medir). */
  recetaDePrueba: null,
  /** Espías: los pisa la vara; en producción no hacen nada. */
  onAlephEspia: null,
  onEstadoEspia: null,
  onEventoEspia: null,
  /** El hilo abierto, para poder afirmar que sobrevivió a una recarga. */
  chatIdActual: null,
};

// ── la app ────────────────────────────────────────────────────────────────────────────
function App() {
  const [hilos, setHilos] = React.useState([]);
  const [hiloActual, setHiloActual] = React.useState(null);
  const [gates, setGates] = React.useState([]);
  const [avisos, setAvisos] = React.useState([]);
  // LAS DELEGACIONES DEL TURNO. Una por sub-agente, en orden de aparición: quién es, qué se
  // le pidió, y —cuando cierra— cómo le fue y qué devolvió. Es lo único que la Sala vieja
  // mostraba del trabajo del agente y que acá no existía: la JERARQUÍA. El dato ya llegaba
  // (el espinazo lo emite, el adaptador lo traduce); lo que faltaba era escucharlo.
  const [delegaciones, setDelegaciones] = React.useState([]);
  // EL CINTURÓN DEL AGENTE — lo que el usuario equipó en el Cuarto, y NADA MÁS.
  //
  // El kit base NO va acá, y no hace falta filtrarlo por nombre: `catalog/templates/kit/
  // belt-kit.mcp.json` declara CERO cards a propósito (medido contra `/v1/belts/cards`), o
  // sea que se excluye solo, por dato. Es infraestructura — el usuario no la armó ni la
  // eligió, y pintarla sería ruido sobre lo único que acá es suyo.
  //
  // En RAW queda vacío y no se pide nada: sin agente no hay cinturón que mostrar.
  const [cinturon, setCinturon] = React.useState([]);
  const _tBuscar = React.useRef(null);
  // Hay una búsqueda escrita. Gobierna que el campo NO se desmonte cuando el resultado
  // trae pocas filas — ver el comentario del umbral en `ui/sidebar.js`.
  const [buscando, setBuscando] = React.useState(false);
  // [convergencia · superficie 5 · F.5] Los tres grupos del índice interno. `null` mientras
  // el pedido está en vuelo: así el sidebar sigue mostrando lo último válido en vez de
  // parpadear a vacío en cada tecla.
  const [resultados, setResultados] = React.useState(null);
  // EL ESTADO DE LOS MOTORES — para avisar ANTES, no después de perder el turno.
  // Una sola petición al montar: `/v1/brains/status` ya devuelve el estado por proveedor.
  // No se re-consulta por turno a propósito: sondear en cada envío agregaría latencia al
  // camino caliente para un dato que cambia cuando el usuario toca su CLI, no cuando
  // escribe. Si cambia entre el chequeo y el click, el aviso reactivo de `818cff19` lo
  // levanta — los dos se complementan y por eso ninguno duplica al otro.
  const [motores, setMotores] = React.useState(null);
  const [receta, setReceta] = React.useState(null);
  const [modeloFinal, setModeloFinal] = React.useState(null);
  const [modelIdentity, setModelIdentity] = React.useState(null);
  const [modelos, setModelos] = React.useState({ choices: [], defaultRef: null, searchThreshold: 12 });
  const [modeloSeleccionado, setModeloSeleccionado] = React.useState(null);
  const [fallo, setFallo] = React.useState(null);
  // [§6.f] LA OBRA LARGA EN VUELO. Es el `obra_id` que llegó en la primera línea del
  // stream; mientras exista, el botón de parar está en pantalla y sabe a quién parar.
  const [obraViva, setObraViva] = React.useState(null);
  const [parandoObra, setParandoObra] = React.useState(false);
  // [§6.a.bis · §6.f] HAY UNA CAPACIDAD DE LA SALA CORRIENDO. Es lo que le dice a la línea
  // de razonamiento que se pinte: el reloj de assistant-ui no las ve, porque no corren por
  // su runtime (`ui/hilo.js`, `EstadoVivo`). Una sola bandera para las dos.
  const [capacidadViva, setCapacidadViva] = React.useState(false);
  // [§6.a.bis · §6.f] EL MODO ARMADO. **Una sola variable, y por eso los dos modos no
  // pueden estar prendidos a la vez**: no es una validación que se pueda olvidar, es la
  // forma del dato. Deep Research ya busca por dentro, así que prender los dos sería
  // buscar dos veces. `null` = turno normal.
  const [modoSala, setModoSala] = React.useState(null);
  // [T2.5] Lo adjunto de ESTE turno. Vive acá y no en el agente porque es estado de
  // pantalla hasta que el turno sale: el usuario puede poner, mirar y sacar antes de
  // enviar. Se vacía al enviar — un adjunto pegajoso mandaría la imagen de nuevo en el
  // turno siguiente sin que nadie lo pidiera.
  const [adjuntos, setAdjuntos] = React.useState([]);
  // [T2.6] El método que dirigió el último turno, tal como lo devolvió el arnés.
  const [metodoDelTurno, setMetodoDelTurno] = React.useState(null);
  const _adjuntoSeq = React.useRef(0);
  // `contexto()` lo lee el agente FUERA del render (es un callback que vive en el
  // adaptador), así que leer el state directo le daría el del primer montaje. Mismo
  // motivo por el que el propio adaptador documenta que el contexto se pide por función.
  // ══ [T2.3] LOS WIDGETS DEL TURNO ═══════════════════════════════════════════════════
  // El motor (`../chat/opciones.js` + `conexion-inline.js`) se MONTA, no se reescribe. El
  // Guía es el precedente y de ahí sale la forma de `destinos`; lo que cambia son los
  // caminos, porque la Sala llega a otros lugares que el Cuarto.
  //
  // ⚠️ SÓLO SE CABLEA LO QUE ESTA PANTALLA PUEDE CUMPLIR DE VERDAD. La regla sellada del
  // motor —«una opción sin handler cableado NO SE PINTA, se dice honesto»— la aplica él
  // mirando este objeto: un destino ausente se vuelve texto, jamás un botón muerto. Por eso
  // acá no hay entradas de relleno.
  const refOpciones = React.useRef(null);
  const opcionesRef = React.useRef(null);
  const conexionInlineRef = React.useRef(null);
  const adaptadorRef = React.useRef(null);
  const enviarTextoRef = React.useRef(null);
  const clientToolsRef = React.useRef(null);
  const callsVistasRef = React.useRef(new Set());
  // LAS OBRAS YA NACIDAS, por turno. Un turno puede emitir MÁS DE UN `aleph.veredicto`
  // —el del stream y el terminal del POST— y sin esta llave el mismo trabajo entraría dos
  // veces a la Biblioteca. La asimetría es la de siempre: no crearla de más no pierde
  // nada (el texto sigue en el hilo), crearla dos veces ensucia para siempre.
  const obrasNacidasRef = React.useRef(new Set());

  const asegurarHiloRef = React.useRef(null);
  const hiloActualRef = React.useRef(null);
  const _adjuntosVivos = React.useRef([]);
  React.useEffect(() => { _adjuntosVivos.current = adjuntos; }, [adjuntos]);
  // [T2.5] La matriz REAL del cerebro elegido, del mismo catálogo que ya está cargado.
  // `null` = todavía no llegó: «no sé» no es «no puede», así que no se avisa nada.
  // Con agente equipado la selección no la manda la Sala ⇒ tampoco se opina.
  const puedeVer = React.useMemo(() => {
    if (PUPPET_ID || receta) return null;
    const fila = modelos.choices.find((m) => m.selection_ref === modeloSeleccionado);
    if (!fila || !Array.isArray(fila.capabilities) || !fila.capabilities.length) return null;
    return fila.capabilities.includes("vision");
  }, [modelos.choices, modeloSeleccionado, receta]);
  const agregarAdjunto = React.useCallback((a) => {
    const id = `adj-${_adjuntoSeq.current++}`;
    // Se pinta PRIMERO y se sube después: el usuario ve lo que eligió al instante y el
    // estado de la subida viaja en la misma ficha. Al revés, un archivo de 20 MB dejaría
    // el composer mudo varios segundos y parecería que el click no hizo nada.
    setAdjuntos((prev) => [...prev, { ...a, id, subiendo: !a.error }]);
    if (a.error || !a.archivo) return;
    (async () => {
      try {
        // El inbox es POR CONVERSACIÓN, así que la conversación tiene que existir. Es la
        // MISMA función que el agente usa antes de mandar el turno: un solo lugar que crea
        // hilos, no dos que podrían crear dos.
        const sid = (await Promise.resolve(asegurarHiloRef.current?.() ?? null)) || hiloActualRef.current;
        if (!sid) throw new Error("sin conversación");
        const r = await fetch(
          `/v1/sessions/${encodeURIComponent(sid)}/inbox?nombre=${encodeURIComponent(a.nombre)}`,
          { method: "POST", headers: authHeaders({ "Content-Type": "application/octet-stream" }),
            body: a.archivo });
        const j = await r.json().catch(() => null);
        if (!r.ok) throw new Error(j?.detail?.detail || `HTTP ${r.status}`);
        // El nombre GUARDADO puede no ser el elegido (saneo, o un duplicado que quedó
        // «-2»). Se adopta el del server: es el que el agente va a ver.
        setAdjuntos((prev) => prev.map((x) => x.id === id
          ? { ...x, subiendo: false, nombre: j?.nombre || x.nombre, ruta: j?.ruta } : x));
      } catch (e) {
        setAdjuntos((prev) => prev.map((x) => x.id === id
          ? { ...x, subiendo: false, error: String(e?.message || e).slice(0, 120) } : x));
      }
    })();
  }, [authHeaders]);
  const quitarAdjunto = React.useCallback((id) => {
    setAdjuntos((prev) => prev.filter((a, i) => (a.id ?? i) !== id));
  }, []);
  // ── el canvas (3.0) ──────────────────────────────────────────────────────────────────
  // `obras` son los RESÚMENES de la Biblioteca; `obraActiva` es la obra ENTERA en pantalla.
  // El almacén separa las dos cosas y la pantalla respeta esa separación (listar no
  // arrastra el cuerpo de cada obra).
  const [obras, setObras] = React.useState([]);
  const [obraId, setObraId] = React.useState(null);
  const [obraActiva, setObraActiva] = React.useState(null);
  const [avisoObra, setAvisoObra] = React.useState(null);
  const SID = React.useMemo(() => Obras.artSid(PUPPET_ID), []);

  // ── [Gate 4 · Fase 4 · O6b · 4.3 · B10] LA TARJETA, Y EL CANVAS QUE EMERGE ──────────
  // `tarjetas` son las obras ANUNCIADAS en el hilo. Una obra nueva nace acá y NO abre el
  // canvas: el defecto que Fase 1 pagó era que una columna fuera y viniera SOLA, moviendo
  // el chat a mitad de una conversación. Abrir es del usuario; anunciar es de la casa.
  const [tarjetas, setTarjetas] = React.useState([]);
  const CLAVE_CANVAS = "aleph:salav2:canvas";
  const [canvasAbierto, setCanvasAbierto] = React.useState(() => {
    // El estado del panel es UI, no dominio: `localStorage` es su lugar correcto (la ley
    // técnica 4 pide clave de dominio para el SNAPSHOT del trabajo, no para un panel).
    try { return localStorage.getItem(CLAVE_CANVAS) === "1"; } catch (_) { return false; }
  });
  const moverCanvas = React.useCallback((abierto) => {
    setCanvasAbierto(abierto);
    try { localStorage.setItem(CLAVE_CANVAS, abierto ? "1" : "0"); } catch (_) {}
  }, []);
  // `destinos[tipo]` — lo que el APLICADOR ÚNICO de O5 resolvió para ese tipo de obra. La
  // tarjeta no decide dónde crece: lo pregunta una vez por tipo y muestra la respuesta.
  const [destinos, setDestinos] = React.useState({});
  const pedirDestino = React.useCallback((tipo) => {
    if (!tipo || destinos[tipo] !== undefined) return;
    const u = usuario();
    const q = "?tipo=" + encodeURIComponent(tipo) + (u?.id ? "&user_id=" + encodeURIComponent(u.id) : "");
    fetch("/v1/workspaces/destino" + q, { headers: authHeaders() })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setDestinos((prev) => ({ ...prev, [tipo]: d })))
      .catch(() => setDestinos((prev) => ({ ...prev, [tipo]: null })));
  }, [destinos]);
  // [3.7 · ley 6 enmendada] Los workspaces salen del backend, que es quien puede medir
  // si el stack está instalado. El cinturón no decide su existencia.
  const [workspaces, setWorkspaces] = React.useState([]);
  React.useEffect(() => {
    elegiblesPorStack(authHeaders).then(setWorkspaces);
  }, []);

  // ── EL CEREBRO DE LA CASA, NO EL DEL HILO ──────────────────────────────────────────
  // [TANDA 1 · obra 1 · decisión del dueño] Esto persistía la elección en
  // `localStorage["aleph:model-use:sala:<owner>:<chat>"]` — una elección POR CONVERSACIÓN
  // que además NUNCA SALÍA DEL NAVEGADOR: medido interceptando `fetch` en la página
  // instalada, el body de `POST /v1/puppets/run` lleva `user_id, prompt, space_id, lang,
  // chat_id, agent, client_tools` y ningún `model`. Consecuencia medida: con «Grok» en el
  // chip el turno contestó `claude-opus-5` con `degraded: null` — un pedido que nunca se
  // hizo, que es peor que un fallo porque no tiene causa que mostrar.
  //
  // Ahora el chip escribe la MISMA fuente que los seis workspaces y la Sala ya leen
  // (`preferencias-v2.default`), por el ÚNICO escritor que existe
  // (`AlephBrain.elegirCerebro`, que es `brain-status.js::selectorPersist`). Cero almacén
  // nuevo, cero cuarto camino: elegir acá cambia el cerebro de las siete superficies.
  const recargarChoices = React.useCallback(() => {
    return cargarChoices()
      .then((data) => {
        const choices = Array.isArray(data?.choices) ? data.choices : [];
        const defaultRef = data?.default_ref || choices.find((row) => row.default)?.selection_ref || choices[0]?.selection_ref || null;
        setModelos({ choices, defaultRef, searchThreshold: data?.search_threshold || 12 });
        // El chip refleja la FUENTE, siempre. Sin esto un cambio hecho en Diseño o en el
        // Cuarto dejaba a la Sala pintando el cerebro viejo hasta un F5.
        setModeloSeleccionado(defaultRef);
        //: cuántas quedaron. Lo usa el reintento de abajo — devolver el `defaultRef` no
        //: alcanza para distinguir «no hay ninguna» de «hay pero ninguna es la default».
        return choices.length;
      })
      .catch(() => {
        setModelos({ choices: [], defaultRef: null, searchThreshold: 12 });
        return 0;
      });
  }, []);

  /* ⚠️ EL CATÁLOGO SE VUELVE A PEDIR HASTA QUE LLEGA — el arranque en frío lo dejaba vacío.
   *
   * MEDIDO el 2026-08-22, primera apertura de la `.app` recién instalada: el chip decía
   * «Elegir modelo», sin una sola opción, y con un F5 aparecía «Grok». La Sala pide su
   * catálogo UNA vez al montar; si en ese instante el sidecar todavía no terminó de detectar
   * los CLIs (`/v1/brains/status` tarda un par de segundos en frío), recibe una lista vacía
   * y no vuelve a preguntar nunca. Se ve en el peor momento posible: la primera pantalla
   * después de abrir Aleph.
   *
   * Es la MISMA falla que ya se arregló del otro lado del borde —`aleph-picker-unico.js`
   * reintenta su saludo hasta que la casa contesta— y le faltaba a la Sala.
   *
   * ⚠️ Y TIENE TOPE, a propósito. Cero modelos es un estado LEGÍTIMO: una máquina sin ningún
   * CLI ni llave no tiene nada que ofrecer, y ahí el chip debe decir «Elegir modelo» y su
   * fila «＋ Añadir otro modelo» llevar a Conectores. Reintentar para siempre convertiría
   * ese estado honesto en un latido eterno. Ocho intentos con espera creciente cubren un
   * arranque en frío (~35 s) y después se acepta la respuesta. */
  React.useEffect(() => {
    let vivo = true;
    let id = null;
    const ESPERAS = [700, 1000, 1500, 2500, 4000, 6000, 8000, 10000];
    let intento = 0;
    const pedir = () => {
      recargarChoices().then((n) => {
        if (!vivo || n > 0 || intento >= ESPERAS.length) return;
        id = setTimeout(pedir, ESPERAS[intento++]);
      });
    };
    pedir();
    return () => { vivo = false; if (id) clearTimeout(id); };
  }, [recargarChoices]);

  // La elección hecha en CUALQUIER superficie despierta a ésta. El evento y el
  // BroadcastChannel ya existían en `brain-status.js`; lo que faltaba era escucharlos.
  React.useEffect(() => {
    const alCambiar = () => { recargarChoices(); };
    window.addEventListener("aleph:model-selection", alCambiar);
    let canal = null;
    try {
      canal = new BroadcastChannel("aleph-modelos-v2");   // el MISMO canal que abre brain-status.js:613
      canal.onmessage = (ev) => { if (ev?.data?.type === "selection") alCambiar(); };
    } catch (_) { /* navegador sin BroadcastChannel: queda el evento local */ }
    return () => {
      window.removeEventListener("aleph:model-selection", alCambiar);
      try { canal?.close(); } catch (_) {}
    };
  }, [recargarChoices]);

  // [O6b · B10] La grilla la decide el CSS, y el CSS lee este atributo. Va en el root del
  // documento y no en un wrapper nuevo: `#sv-root` ES la grilla, y meterle un div adentro
  // sería cambiarle el esqueleto a la pantalla para mover una columna.
  React.useEffect(() => {
    const raiz = document.getElementById("sv-root");
    if (raiz) raiz.setAttribute("data-canvas", canvasAbierto ? "abierto" : "cerrado");
  }, [canvasAbierto]);

  /** Anunciar una obra en el hilo — el MISMO camino que usa un turno al cerrar.
   *  Se expone como seam (`window.__salaV2`) igual que el resto: la vara mide producción,
   *  no un arnés paralelo, y así el sabotaje se arma DESDE AFUERA (llamar a `abrirObra`
   *  después de anunciar reproduce el comportamiento viejo) sin dejar una perilla de
   *  sabotaje adentro del código del usuario. */
  const anunciarObra = React.useCallback((a) => {
    if (!a || !a.id) return;
    setObras((prev) => (prev.some((o) => o.id === a.id) ? prev : [...prev, {
      id: a.id, title: a.title, type: a.type,
      created_at: a.created_at, updated_at: a.updated_at,
      n_versions: (a.versions || []).length,
    }]));
    setTarjetas((prev) => (prev.some((o) => o.id === a.id) ? prev : [...prev, a]));
    pedirDestino(a.type);
  }, [pedirDestino]);

  // Seam de verificación: la vara mide ESTE camino, no uno paralelo. Y el sabotaje de la
  // vara se arma DESDE AFUERA (anunciar y después abrir reproduce el comportamiento viejo),
  // así no queda una perilla de sabotaje adentro del código del usuario.
  React.useEffect(() => {
    window.__salaV2.SID = SID;
    window.__salaV2.anunciarObra = anunciarObra;
    window.__salaV2.abrirObra = abrirObra;
    window.__salaV2.canvasAbierto = () => canvasAbierto;
  });

  const maquina = React.useMemo(
    () =>
      new MaquinaDeEstados(null, (e) => {
        try {
          window.__salaV2.onEstadoEspia?.(e);
        } catch (_) {
          /* ídem */
        }
      }),
    [],
  );

  // ── EL CANVAS · las cuatro operaciones ────────────────────────────────────────────────
  // Todas van contra los endpoints del contrato (Fase 2). Ningún fallo se traga: el borde
  // rechaza TIPADO y ese motivo se muestra — una obra que el usuario ve y el disco no tiene
  // es peor que un error.
  const abrirObra = React.useCallback(
    async (id) => {
      // [O6b] Abrir una obra ES abrir el canvas. Es el único camino por el que la columna
      // aparece, y siempre nace de un gesto: un tap en la tarjeta, o un click en la
      // Biblioteca. Nunca de un turno.
      moverCanvas(true);
      setObraId(id);
      // La obra entera se pide SIEMPRE al almacén, jamás se arma de lo que la pantalla
      // recuerda: el contenido, las versiones y la procedencia son del disco.
      setObraActiva(null);
      try {
        const a = await Obras.obtener(SID, authHeaders, id);
        setObraActiva(a);
        setAvisoObra(null);
      } catch (_) {
        setAvisoObra(tr("salav2.canvas.err.abrir", "No pude abrir esa obra."));
      }
    },
    [SID],
  );

  const refrescarBiblioteca = React.useCallback(
    async (abrir) => {
      try {
        const lista = await Obras.listar(SID, authHeaders);
        setObras(lista);
        const id = abrir || (lista.length ? lista[lista.length - 1].id : null);
        if (id) await abrirObra(id);
        else {
          setObraId(null);
          setObraActiva(null);
        }
      } catch (e) {
        setAvisoObra(tr("salav2.canvas.err.listar", "No pude leer tu Biblioteca."));
      }
    },
    [SID, abrirObra],
  );

  const revertirObra = React.useCallback(
    async (id) => {
      try {
        const a = await Obras.revertir(SID, authHeaders, id);
        setObraActiva(a);
        setAvisoObra(null);
        const lista = await Obras.listar(SID, authHeaders).catch(() => null);
        if (lista) setObras(lista);
      } catch (e) {
        setAvisoObra(
          e?.sinVersion
            ? tr("salav2.canvas.err.sin_version", "Esta obra no tiene una versión anterior.")
            : tr("salav2.canvas.err.revertir", "No pude revertir esta obra."),
        );
      }
    },
    [SID],
  );

  /** El turno cerró y produjo algo: nace la obra, con su identidad adentro. */

  const nacerObra = React.useCallback(
    async (veredicto, intento) => {
      setMetodoDelTurno(veredicto?.method || null);
      // [T2.3] LAS OPCIONES DEL TURNO, PINTADAS. `client_calls` es la verdad terminal del
      // POST. El dedup es por `call_id` porque la MISMA call puede llegar dos veces —viva
      // por el espinazo y otra vez en el record al cerrar— y sin él cada opción se pintaría
      // duplicada, la segunda con los botones ya cerrados de la primera.
      for (const c of veredicto?.client_calls || []) {
        const k = String(c?.call_id || (c?.tool + JSON.stringify(c?.args || {})));
        if (!c?.tool || callsVistasRef.current.has(k)) continue;
        callsVistasRef.current.add(k);
        try {
          if (c.tool === "conectar_inline") conexionInlineRef.current?.emitir(c.args || {});
          else opcionesRef.current?.emitir(c.tool, c.args || {}, { prosa: "" });
        } catch (e) {
          console.error("[opciones] no pude pintar la opción del turno:", e);
        }
      }
      const rica = veredicto?.obra && typeof veredicto.obra === "object" ? veredicto.obra : null;
      // [T2.4] Si el turno se apoyó en el Conocimiento del usuario, la obra lo DICE. Sólo
      // sobre la respuesta de texto: una obra rica es un objeto tipado y meterle una
      // sección de markdown adentro la rompería. Sin apuntes el texto pasa intacto.
      const cuerpo = rica
        ? JSON.stringify(rica)
        : conDocumentosCitados(String(veredicto?.answer || ""), veredicto?.rag?.provenance);
      // Un turno sin entregable no inventa una obra — y «entregable» es una regla escrita,
      // no «hay texto». Ver `mereceSerObra`: la asimetría manda (no crearla no pierde nada,
      // el texto sigue en el hilo; crearla de más ensucia la Biblioteca para siempre).
      if (!Obras.mereceSerObra(cuerpo, rica)) return;
      // LA LLAVE DEL TURNO, en orden de confianza: el run (camino equipado) → el espacio →
      // el id de turno del cliente (el único que existe en el replay idempotente de la
      // charla). Si no hubiera ninguno, se cae al pedido + el largo del cuerpo: peor llave,
      // pero llave — quedarse sin ninguna es volver a poder duplicar.
      const llaveTurno = String(
        veredicto?.run_id || veredicto?.space_id || veredicto?.client_turn_id ||
        `${intento}::${cuerpo.length}`,
      );
      if (obrasNacidasRef.current.has(llaveTurno)) return;
      obrasNacidasRef.current.add(llaveTurno);
      const tipo = rica?.type || "informe";
      // EL TÍTULO DE LA OBRA ES SU TÍTULO, NO EL PEDIDO. Medido contra la .app instalada:
      // la descarga salía «Tom__las_ventas_mensuales_2025_de_una_PyME__ene_48200__feb_…»
      // porque el título caía al PROMPT entero. Y el nombre del archivo se DERIVA del
      // título, así que el defecto viajaba al disco del usuario.
      //
      // El modelo ya escribe un `# Título` como primera línea del informe: se usa ÉSE. No
      // se inventa nada — si no hay encabezado se cae al pedido, como antes, y recién si
      // tampoco hay, a «Sin título». Orden: lo que la obra rica declara → su encabezado →
      // el pedido.
      const _h1 = (cuerpo.match(/^\s*#{1,3}\s+(.+)$/m) || [])[1];
      const titulo = (rica?.title || _h1 || intento || "").trim().slice(0, 120) ||
        tr("salav2.canvas.sin_titulo", "Sin título");
      try {
        const a = await Obras.crear(SID, authHeaders, {
          title: titulo,
          type: tipo,
          content: cuerpo,
          userId: usuario()?.id,
          refs: Obras.refsDelTurno({
            out: veredicto,
            intent: intento,
            chatId: window.__salaV2.chatIdActual,
            puppetId: PUPPET_ID,
            spaceId: veredicto?.space_id,
          }),
        });
        if (!a) return;
        // [O6b · 4.3] LA OBRA SE ANUNCIA EN EL HILO, NO SE ABRE SOLA. Antes esto hacía
        // `setObraId` + `setObraActiva`, o sea: el resultado del trabajo aparecía en una
        // columna a la derecha, fuera de donde el usuario estaba mirando. Ahora nace una
        // tarjeta con su preview, en el flujo del hilo, y crecer es un gesto del usuario.
        setTarjetas((prev) => [...prev, a]);
        pedirDestino(a.type);
        setAvisoObra(null);
      } catch (e) {
        // La llave se suelta: se tomó ANTES de crear para ganarle a la carrera entre dos
        // veredictos del mismo turno, pero si la creación falló no hay obra que proteger —
        // dejarla tomada le negaría el intento al veredicto que venga después.
        obrasNacidasRef.current.delete(llaveTurno);
        // El borde tipa el rechazo (`artifact_type_invalid` 422 …). Se muestra.
        setAvisoObra(
          tr("salav2.canvas.err.crear", "No pude guardar la obra de este turno.") +
            (e?.detalle?.error ? " (" + e.detalle.error + ")" : ""),
        );
      }
    },
    [SID],
  );

  // ── [§6.a.bis] LA BÚSQUEDA WEB, DESDE LA SALA ───────────────────────────────────────
  // El progreso se rinde EN la línea de razonamiento —la misma que pinta los turnos del
  // agente—, las fuentes se citan en el hilo, y el resultado nace como artefacto con las
  // fuentes en el pasaporte. La cara de Vane no se monta en ningún lado.
  const onBuscarWeb = React.useCallback(
    async (consulta) => {
      let ultima = null;
      setCapacidadViva(true);
      try {
      await buscarEnLaWeb({
        consulta,
        headers: authHeaders,
        puppetId: PUPPET_ID,
        chatId: window.__salaV2?.chatIdActual,
        // El sobre ya viene con su `etapa`, su `estado` y su texto con el NÚMERO
        // («81 resultados»). La máquina lo pinta tal cual: acá no se re-traduce nada.
        onEstado: (sobre) => maquina.externo(sobre),
        onRespuesta: (r) => { ultima = r; },
        onFallo: (f) => {
          maquina.externo({ estado: "fallo", etapa: "fallando",
                            texto: f?.copy || "La búsqueda falló." });
          setFallo?.({ causa: f?.causa, copy: f?.copy, detalle: f?.detalle });
        },
      });
      if (!ultima) return;
      maquina.externo({ estado: "final", etapa: "terminando", texto: "Listo." });
      // EL ARTEFACTO, con las fuentes adentro y en el pasaporte. `nacerObra` ya sabe
      // anunciarlo en el hilo sin robarle la pantalla al usuario (O6b · 4.3), así que se
      // reusa en vez de abrir un camino paralelo que después divergiría.
      await nacerObra(
        {
          answer: conFuentesCitadas(ultima.texto, ultima.fuentes,
                                    tr("salav2.fuentes", "Fuentes")),
          obra: {
            type: "informe",
            // UN BORRADOR SE LLAMA BORRADOR. Si cruzara con el mismo título que un informe
            // terminado, la biblioteca del usuario tendría dos cosas distintas con el mismo
            // nombre y ninguna forma de saber cuál se puede citar.
            title: (ultima.parcial
                     ? tr("salav2.investigar.borrador", "Borrador sin fuentes") + " — "
                     : "") + consulta.slice(0, 120),
            content: conFuentesCitadas(ultima.texto, ultima.fuentes,
                                       tr("salav2.fuentes", "Fuentes")),
            // Las fuentes van TAMBIÉN estructuradas: el markdown es para leer, esto es
            // para el pasaporte. Ninguna se inventa (`pasaporteDeFuentes` filtra).
            fuentes: pasaporteDeFuentes(ultima.fuentes),
            sha256: ultima.sha256 || null,
          },
        },
        consulta,
      );
      } finally { setCapacidadViva(false); }
    },
    [maquina, nacerObra],
  );

  // ── [§6.f] LA INVESTIGACIÓN A FONDO, DESDE LA SALA ──────────────────────────────────
  // Mismo patrón que la búsqueda web —el progreso en la línea de razonamiento, las fuentes
  // citadas en el hilo, el resultado como artefacto por `nacerObra`—, con dos diferencias
  // que salen de que esto corre MINUTOS y aquello segundos:
  //
  //   1. el `obra_id` se guarda apenas llega, para que el botón de parar exista;
  //   2. el progreso se pinta por ETAPA y no por resultado: `textoDeEtapa` le suma el
  //      «N de M» cuando el motor lo dio, y no lo inventa cuando no.
  const onInvestigar = React.useCallback(
    async (consulta) => {
      let ultima = null;
      setObraViva(null);
      setParandoObra(false);
      setCapacidadViva(true);
      try {
      await investigarAFondo({
        consulta,
        headers: authHeaders,
        puppetId: PUPPET_ID,
        chatId: window.__salaV2?.chatIdActual,
        onAbre: (a) => setObraViva(a?.obra_id || null),
        // El sobre ya viene con su `etapa`, su `estado` y su texto en castellano
        // (`platform/sala/research/etapas.py`). Acá sólo se le agrega el contador.
        onEstado: (sobre) => maquina.externo({ ...sobre, texto: textoDeEtapa(sobre) }),
        onInforme: (r) => { ultima = r; },
        onFallo: (f) => {
          maquina.externo({ estado: "fallo", etapa: "fallando",
                            texto: f?.copy || "La investigación falló." });
          setFallo?.({ causa: f?.causa, copy: f?.copy, detalle: f?.detalle });
          // EL BORRADOR SE GUARDA **SÓLO SI EXISTE**, y eso no se adivina del texto: se
          // lee de las etapas que el servidor contó de los latidos del motor.
          //
          // ⚠️ ESTO LO DESTAPÓ LA PANTALLA, no la vara. La primera versión guardaba el
          // borrador cada vez que el fallo traía `texto`, y en la corrida real de una
          // instalación sin cerebro conectado eso produjo un artefacto tipo INFORME,
          // titulado con la consulta del usuario, cuyo contenido era
          // «Error: Error code: 424 - {'detail': …}». LDR se traga el error del modelo y lo
          // devuelve COMO SI FUERA el resumen, así que «tiene texto» no significa «hay un
          // borrador». Guardar eso era exactamente el pecado que este modo vino a cerrar:
          // vestir de informe algo que no lo es — sólo que un nivel más arriba.
          //
          // `sintetizando` es el hecho que separa los dos mundos: si el motor nunca llegó
          // a escribir, no hay borrador que perder, y el fallo se cuenta y nada más.
          if (f?.texto && (f.etapas || []).includes("sintetizando")) {
            ultima = { ...f, parcial: true };
          }
        },
      });
      setObraViva(null);
      setParandoObra(false);
      if (!ultima) return;
      if (!ultima.parcial) {
        maquina.externo({ estado: "final", etapa: "terminando", texto: "Informe listo." });
      }
      // EL ARTEFACTO, con las fuentes adentro y en el pasaporte. Se reusa `nacerObra`, que
      // ya sabe anunciarlo en el hilo sin robarle la pantalla al usuario (O6b · 4.3), en
      // vez de abrir un camino paralelo que después divergiría.
      const cuerpo = conFuentesCitadas(ultima.texto, ultima.fuentes,
                                       tr("salav2.fuentes", "Fuentes"));
      await nacerObra(
        {
          answer: cuerpo,
          // EL ESPACIO DE LA OBRA, AL PASAPORTE. `nacerObra` lo lee de acá
          // (`Obras.refsDelTurno({… spaceId: veredicto?.space_id})`), y sin él la
          // procedencia salía con `space_id: null` — medido sobre un artefacto real.
          //
          // No es cosmético: el pack abre un espacio por obra y le manda `X-Aleph-Space`
          // al borde en CADA llamada al modelo, o sea que todos los turnos de esta
          // investigación están anotados ahí. Sin el id en el pasaporte, el informe y sus
          // turnos quedan en dos mitades que nadie puede volver a unir, y el anti-grift
          // —que lee exactamente eso— se queda ciego a este modo.
          space_id: ultima.espacio || null,
          obra: {
            type: "informe",
            // UN BORRADOR SE LLAMA BORRADOR. Si cruzara con el mismo título que un informe
            // terminado, la biblioteca del usuario tendría dos cosas distintas con el mismo
            // nombre y ninguna forma de saber cuál se puede citar.
            title: (ultima.parcial
                     ? tr("salav2.investigar.borrador", "Borrador sin fuentes") + " — "
                     : "") + consulta.slice(0, 120),
            content: cuerpo,
            // Las fuentes van TAMBIÉN estructuradas: el markdown es para leer, esto es
            // para el pasaporte. Ninguna se inventa (`pasaporteDeFuentes` filtra).
            fuentes: pasaporteDeFuentes(ultima.fuentes),
            // LAS ETAPAS QUE CORRIERON DE VERDAD viajan al pasaporte. Es el dato que
            // separa un informe investigado de uno escrito de memoria, y el servidor lo
            // cuenta de los latidos del motor, no del `iterations` que él se auto-reporta.
            etapas: Array.isArray(ultima.etapas) ? ultima.etapas : null,
            fuentes_crudas: Number.isFinite(ultima.fuentes_crudas) ? ultima.fuentes_crudas : null,
            sha256: ultima.sha256 || null,
          },
        },
        consulta,
      );
      } finally { setCapacidadViva(false); }
    },
    [maquina, nacerObra],
  );

  /** El composer mandó el turno con un modo armado. El modo NO se apaga solo.
   *
   * Que quede prendido es la decisión: el usuario que prendió «Buscar en la web» va a
   * hacer varias búsquedas seguidas, y apagárselo después de cada una lo obligaría a
   * volver a prenderlo cada vez. Se apaga cuando él lo apaga.
   */
  const onEnviarModo = React.useCallback(
    async (modo, consulta, onAceptado) => {
      if (modo !== "investigar" && modo !== "buscar") return;
      try {
        if (!await ensureSearchProvider(authHeaders)) return;
      } catch (error) {
        setFallo?.({ causa: "search_provider_status_failed",
                    copy: error?.message || "Could not check the search provider." });
        return;
      }
      onAceptado?.();
      if (modo === "investigar") return onInvestigar(consulta);
      return onBuscarWeb(consulta);
    },
    [onInvestigar, onBuscarWeb],
  );

  /** El usuario apretó parar. Se le pide al MOTOR, no se aborta el fetch. */
  const onPararObra = React.useCallback(async () => {
    if (!obraViva) return;
    setParandoObra(true);
    const r = await pararInvestigacion({ obraId: obraViva, headers: authHeaders });
    // HONESTO SOBRE LOS DOS CASOS. Si la obra ya había terminado, no se dice «parada»:
    // no es un error —el usuario apretó justo cuando llegaba el informe— pero tampoco es
    // lo mismo. El stream se encarga del resto: el motor lo cierra con `obra_cancelada`.
    if (!r?.encontrada) {
      maquina.externo({ estado: "final", etapa: "terminando",
                        texto: tr("salav2.pararobra.tarde", "La investigación ya había terminado.") });
      setParandoObra(false);
      setObraViva(null);
    }
  }, [obraViva, maquina]);

  // Todo lo que el adaptador manda por el canal lateral entra por acá. Es el MISMO
  // contenido que viaja como CUSTOM en el hilo: una sola verdad, dos consumidores.
  const onAleph = React.useCallback(({ nombre, valor }) => {
    try {
      window.__salaV2.onAlephEspia?.({ nombre, valor });
    } catch (_) {
      /* un espía roto no puede tumbar el turno */
    }
    switch (nombre) {
      case "aleph.tool_meta":
        if (valor?.nombre) window.__salaV2._meta.set(valor.nombre, valor);
        break;

      case "aleph.veredicto":
        // `model_final` es el modelo que REALMENTE corrió, según el backend. Se prefiere al
        // de la receta porque la receta declara una intención y esto declara un hecho —y
        // Gate 3 selló que la sustitución se anuncia, no se esconde.
        if (valor?.model_final) setModeloFinal(valor.model_final);
        if (valor?.model_identity) setModelIdentity(valor.model_identity);
        // [3.0] El turno cerró: si dejó un entregable, nace la obra en el almacén y el
        // canvas la muestra. Un turno que no dejó nada NO inventa una obra vacía.
        if (valor?.ok !== false) nacerObra(valor, valor?.intent || "");
        break;

      case "aleph.model_final":
        if (valor?.model_final) setModeloFinal(valor.model_final);
        break;

      case "aleph.gate_waiting":
        setGates((prev) => {
          const i = prev.findIndex((g) => g.sig === valor.sig);
          // La tarjeta NO se duplica: el `gate_waiting` vivo la crea en freeze y el
          // `held_action` del cierre la sube a operable sobre la MISMA firma.
          if (i === -1) return [...prev, { ...valor, resuelto: false }];
          const copia = prev.slice();
          copia[i] = { ...copia[i], ...valor, ux: valor.ux || copia[i].ux };
          return copia;
        });
        break;

      case "aleph.gate_resolved":
        // Lo resolvió el backend (timeout, o el otro lado): la tarjeta se cierra sola.
        setGates((prev) =>
          prev.map((g) =>
            g.server === valor?.tool || g.tool === valor?.tool
              ? { ...g, resuelto: true, aprobado: !!valor?.approved }
              : g,
          ),
        );
        break;

      // ── LA DELEGACIÓN ────────────────────────────────────────────────────────────────
      // `aleph.paso` llega para CADA paso del run (cinturón, turno:N, subagente:X). Sólo
      // los de sub-agente abren una fila: el resto ya tiene su lugar en la línea de estado
      // y duplicarlo sería dos verdades para el mismo hecho.
      case "aleph.paso":
        if (String(valor?.paso || "").startsWith("subagente:")) {
          setDelegaciones((prev) =>
            // Idempotente por clave: el espinazo puede repetir un evento en una reconexión
            // del SSE, y un sub-agente que aparece dos veces sería una delegación inventada.
            prev.some((d) => d.clave === valor.paso)
              ? prev
              : [...prev, {
                  clave: valor.paso,
                  nombre: valor.sub || "sub-agente",
                  tarea: valor.task || null,
                  profundidad: valor.depth || 1,
                  cerrada: false,
                }],
          );
        }
        break;

      // El cierre. Si nunca llega, la fila queda abierta Y SE VE ABIERTA: un sub-agente que
      // no volvió es un hecho del turno, no algo que la pantalla deba disimular.
      case "aleph.paso_fin":
        if (String(valor?.paso || "").startsWith("subagente:")) {
          setDelegaciones((prev) =>
            prev.map((d) =>
              d.clave === valor.paso
                ? {
                    ...d,
                    cerrada: true,
                    estado: valor.status || (valor.child_ok ? "ok" : "error"),
                    retenido: (valor.held || 0) > 0,
                    devolvio: valor.result || null,
                  }
                : d,
            ),
          );
        }
        break;

      case "aleph.modelo_sustituido":
        setAvisos((a) => [...a, textoSustitucion(valor)]);
        break;

      case "aleph.sesion_perdida":
        setAvisos((a) => [...a, textoSesionPerdida(valor)]);
        break;

      case "aleph.espinazo_caido":
        setAvisos((a) => [
          ...a,
          tr("salav2.aviso.espinazo", "Perdí el detalle en vivo de este turno. El resultado igual llega."),
        ]);
        break;

      case "aleph.frame_ilegible":
      case "aleph.frame_desconocido":
      case "aleph.evento_desconocido":
        // Fallo visible, jamás mudo: un frame que no entendemos SE VE. Es la única forma de
        // enterarse de que el backend cambió el contrato sin avisarle a la pantalla.
        setAvisos((a) => [...a, tr("salav2.aviso.frame", "Llegó un evento que esta pantalla no conoce.")]);
        break;

      default:
        break;
    }
  }, [nacerObra]);

  // Al montar: la Biblioteca sale del disco. Ésta es la mitad de «cerrar y reabrir»
  // (§6 del contrato): la clave de sesión vive en localStorage desde 2.2, así que reabrir
  // la app encuentra las obras donde quedaron en vez de una Biblioteca vacía con los JSON
  // huérfanos al lado.
  React.useEffect(() => {
    refrescarBiblioteca();
  }, [refrescarBiblioteca]);

  React.useEffect(() => {
    fetch("/v1/brains/status", { headers: authHeaders({}) })
      .then((r) => (r.ok ? r.json() : null))
      // Sin respuesta se queda en `null` y el chip no dice NADA: no medimos, no opinamos.
      .then((d) => setMotores(d?.providers || null))
      .catch(() => {});
  }, []);

  const agente = React.useMemo(
    () =>
      new AlephAgent({
        authHeaders,
        onAleph,
        contexto: () => {
          const c = agente._ctxVivo || {};
          // `recetaDePrueba` es el seam de la vara: le deja correr un turno equipado sin
          // obligarla a crear un agente guardado sólo para medir. En producción es null.
          // Precedencia: la vara (si inyectó una) → el agente equipado → raw sin receta.
          // Raw manda sólo el picker_id; el servidor reconstruye el model_cfg canónico.
          const recipe = window.__salaV2.recetaDePrueba || c.receta || null;
          const raw = !PUPPET_ID && !recipe;
          return {
            puppetId: PUPPET_ID,
            agent: PUPPET_ID || null,
            // Una receta con cinturón corre por el camino equipado aunque no haya agente
            // guardado. Un puppet_id también conserva el circuito completo mientras su
            // receta termina de llegar.
            equipado: Boolean(PUPPET_ID || recipe?.belt?.belt_ref),
            userId: usuario()?.id,
            // [T2.5] Sólo los que SE PUDIERON leer: un adjunto con error se le muestra al
            // humano como error y NO viaja — mandar la mitad sería peor que no mandar.
            // Sólo IMÁGENES viajan como data-URL: es el único campo que el modelo
            // multimodal consume. Los documentos NO van por acá — ya están en el inbox y
            // el agente los lee por ruta con markitdown/filesystem.
            images: _adjuntosVivos.current.filter((a) => !a.error && a.dataUrl)
                                          .map((a) => a.dataUrl),
            // [T2.3] Los schemas de las 6 familias, en el idioma de la sesión. Salen del
            // MISMO módulo que después las valida y las pinta: un solo contrato, no una
            // copia acá que pueda quedar vieja. Sin motor montado no se declara nada.
            clientTools: clientToolsRef.current || undefined,
            chatId: c.hiloActual ?? null,
            recipe,
            model: raw ? c.modeloSeleccionado : undefined,
            spaceId: raw ? null : undefined,
            lang: window.AlephI18n?.lang?.() === "en" ? "en" : "es",
          };
        },
      }),
    // `contexto` es una función que lee estado fresco en cada turno, así que el agente NO
    // se recrea cuando cambia el hilo: recrearlo tiraría el runtime y con él el historial
    // en pantalla.
    [onAleph], // eslint-disable-line
  );
  // Las refs vivas que la función `contexto` necesita leer.
  React.useEffect(() => {
    agente._ctxVivo = { hiloActual, receta, modeloSeleccionado };
    window.__salaV2.chatIdActual = hiloActual;
    hiloActualRef.current = hiloActual;
  }, [agente, hiloActual, receta, modeloSeleccionado]);

  const runtime = useAgUiRuntime({
    agent: agente,
    // La máquina de estados ve exactamente los mismos eventos que el hilo.
    onEvent: undefined,
  });

  // Rehidrata el hilo seleccionado desde el registro real. Cambiar de conversación no
  // mezcla historiales: assistant-ui recibe sólo los mensajes del chat elegido.
  //
  // ⚠️ `agente.setMessages()` NO ALCANZA, Y ÉSE ERA EL BUG. Medido en la .app instalada
  // (sidecar 30cde224) y también en la anterior (2aa64a13), o sea que no es de esta tanda:
  // se abría un chat de ayer, `GET /v1/chats/{id}` contestaba con sus 2 o 4 mensajes… y la
  // pantalla seguía diciendo «Contame qué necesitás y lo hacemos». El hilo quedaba en
  // blanco con el registro lleno, que para el usuario es haber perdido la conversación.
  //
  // DÓNDE SE CORTABA, exacto. `setMessages` del `AbstractAgent` guarda el array y avisa a
  // sus `subscribers` por `onMessagesChanged`. **Nadie implementa ese handler**: el runtime
  // de assistant-ui no se suscribe por ahí — su repositorio de mensajes sólo se llena por
  // el stream de eventos AG-UI (`MESSAGES_SNAPSHOT` → `importMessagesSnapshot`), y nuestro
  // `AlephAgent` emite 19 tipos de evento y ése no. Así que el agente quedaba con la
  // historia y la pantalla sin enterarse. El dato llegaba y se tiraba en la última pulgada.
  //
  // LA PUERTA YA ESTABA ABIERTA, faltaba tocarla: `runtime.thread.reset(mensajes)` —
  // `reset(e){ this.import(Ha.fromArray(e ?? [])) }` en el bundle vendorizado. Es la API
  // pública de assistant-ui para restaurar un hilo y estaba entera; no se agrega ninguna
  // maquinaria. Mismo patrón que ya pasó con `render.js` y con el motor de widgets: el
  // código sobrevive y lo que falta es quién lo llame.
  //
  // El `content` va como PARTES (`[{type:"text",text}]`), no como string pelado: es la
  // forma que `Ha.fromArray` sabe leer, y se comprobó en vivo contra el hilo real.
  //
  // `setMessages` SE MANTIENE: es el estado del agente, que es otra cosa que lo pintado.
  // (El contexto del MODELO no depende de ninguno de los dos — se rehidrata server-side
  // por `chat_id` en cada turno, igual que en la Sala vieja.)
  React.useEffect(() => {
    let vivo = true;
    const pintar = (msgs) => {
      agente.setMessages(msgs);
      try {
        runtime?.thread?.reset(msgs.map((m) => ({
          id: m.id,
          role: m.role,
          content: [{ type: "text", text: m.texto }],
        })));
      } catch (_) {
        /* si el runtime todavía no está, el hilo queda como estaba: degradar, no romper */
      }
    };
    if (!hiloActual) {
      pintar([]);
      setModeloFinal(null);
      setModelIdentity(null);
      return () => { vivo = false; };
    }
    fetch("/v1/chats/" + encodeURIComponent(hiloActual), { headers: authHeaders({}) })
      .then((r) => (r.ok ? r.json() : null))
      .then((chat) => {
        if (!vivo || !chat) return;
        const msgs = (chat.messages || []).map((m) => ({
          id: String(m.id),
          role: m.role === "agent" ? "assistant" : m.role,
          content: String(m.content || ""),
          texto: String(m.content || ""),
        })).filter((m) => m.role === "user" || m.role === "assistant" || m.role === "system");
        pintar(msgs);
      })
      .catch(() => { if (vivo) pintar([]); });
    return () => { vivo = false; };
  }, [agente, runtime, hiloActual]);

  // [T2.3] MANDAR UN TEXTO COMO SI LO HUBIERA ESCRITO EL HUMANO. Es el gesto que sostiene
  // las opciones: tocar una convierte su label en el MENSAJE del humano y arranca el turno
  // siguiente — para el modelo, simplemente contestó. Se usa el `append` del runtime, que
  // es el mismo camino del composer: no hay una segunda vía de enviar que pueda divergir.
  React.useEffect(() => {
    enviarTextoRef.current = (texto) => {
      const t = String(texto == null ? "" : texto).trim();
      if (!t) return false;
      try {
        runtime.thread.append({ role: "user", content: [{ type: "text", text: t }] });
        return true;
      } catch (e) {
        console.error("[opciones] no pude mandar la respuesta al hilo:", e);
        return false;
      }
    };
  }, [runtime]);

  // [T2.3] EL MOTOR DE WIDGETS, MONTADO. Import dinámico porque vive fuera de esta carpeta
  // (es transversal: el Guía usa EXACTAMENTE el mismo) y porque su CSS y su peso no tienen
  // por qué entrar en el arranque de la Sala.
  React.useEffect(() => {
    let vivo = true;
    (async () => {
      const host = refOpciones.current;
      if (!host || opcionesRef.current) return;
      try {
        const [Op, Cx, { crearChatAdaptador }] = await Promise.all([
          import("../chat/opciones.js?v=sala-te"),
          import("../chat/conexion-inline.js?v=sala-te"),
          import("./ui/opciones-host.js?v=sala-te"),
        ]);
        const montarOpciones = Op.montar, montarConexionInline = Cx.montar;
        if (!vivo) return;
        // EL CSS DEL MOTOR, inyectado una vez. Es el mismo gesto que hace `aleph-chat.js`
        // (concatena OPCIONES_CSS + CONEXION_INLINE_CSS): las tarjetas traen sus clases
        // `ac-*` y sin la hoja se pintarían como texto suelto. Va en un <style> propio y
        // marcado, para que se vea de dónde salió y no se duplique al remontar.
        if (!document.getElementById("sv-opciones-css")) {
          const est = document.createElement("style");
          est.id = "sv-opciones-css";
          est.textContent = (Op.CSS || "") + (Cx.CSS || "");
          document.head.appendChild(est);
        }
        const chat = crearChatAdaptador(host, () => {
          try { host.scrollIntoView({ block: "end", behavior: "smooth" }); } catch (e) {}
        });
        adaptadorRef.current = chat;
        conexionInlineRef.current = montarConexionInline(chat, {
          surface: "sala",
          // Retomar el turno tras conectar: el resultado vuelve como mensaje del humano,
          // igual que en el Guía. La credencial JAMÁS entra acá — el componente la manda
          // directo al validador y sólo devuelve metadata inocua.
          onResultado: (r) => {
            const seguro = { tool: "conectar_inline", connector: String(r?.connector || ""),
                             ok: !!r?.ok, estado: String(r?.estado || ""), credencial_en_chat: false };
            enviarTextoRef.current?.(
              "[Resultado de la tool conectar_inline — no es un pedido nuevo]\n"
              + JSON.stringify(seguro)
              + "\nRetoma ahora la tarea original desde este resultado. No vuelvas a pedir la credencial.");
          },
        });
        // Las 6 familias (5 de opciones + la de credencial), en el idioma de la sesión.
        const lang = window.AlephI18n?.lang?.() === "en" ? "en" : "es";
        clientToolsRef.current = Op.CLIENT_TOOLS(lang);
        opcionesRef.current = montarOpciones(chat, {
          lang: () => (window.AlephI18n?.lang?.() === "en" ? "en" : "es"),
          surface: "sala",
          onRespuesta: (texto) => { enviarTextoRef.current?.(texto); },
          // ⚠️ SÓLO LO QUE ESTA PANTALLA CUMPLE DE VERDAD. Lo que no está acá el motor lo
          // dice en texto y no lo pinta como botón (su regla sellada). No se agrega una
          // entrada «por completitud»: eso es justamente el botón falso que prohíbe.
          destinos: {
            aprobar: (d) => {
              const orden = d?.instruccion || d?.resumen || "";
              if (!enviarTextoRef.current?.("Aprobado: " + orden)) {
                return { ok: false, texto: "No pude mandar la aprobación." };
              }
              return { ok: true, texto: "Aprobado — lo hago ahora.", evidencia: d?.resumen };
            },
            rechazar: () => ({ ok: false, texto: "No lo hice. Nada corrió." }),
            ir: (destino) => {
              // La Sala YA es la Sala: llevar a alguien donde ya está sería mentirle.
              if (destino === "sala") return { ok: true, texto: "Ya estás en la Sala." };
              if (destino === "conexiones") {
                location.href = "../Conectar.dc.html?volver=" + encodeURIComponent(location.pathname);
                return { ok: true, texto: "Abrí el Centro de conexiones." };
              }
              if (destino === "cuarto") {
                location.href = "../cuarto/cuarto.pixi.html";
                return { ok: true, texto: "Abrí el Cuarto." };
              }
              if (destino === "cerebro") {
                // El selector de la Sala vive en el composer, no en otra pantalla: llevar
                // al humano ahí es SEÑALARLO y darle el foco. Es un destino real, y por eso
                // se cablea en vez de dejar un botón que no hace nada.
                const chip = document.querySelector(".sv-model-chip, [data-testid='sv-modelo']");
                if (!chip) return { ok: false, texto: "No tengo a dónde llevarte para eso todavía." };
                try { chip.scrollIntoView({ block: "center", behavior: "smooth" }); chip.focus?.(); } catch (e) {}
                chip.click?.();
                return { ok: true, texto: "Ahí está el selector de modelo." };
              }
              if (destino === "pieza") {
                // Una pieza vive en el Cuarto y el Cuarto NO acepta enfocarla por URL
                // (medido: no hay `?pieza=`). Se lleva al Cuarto, que es cierto, y el copy
                // no promete el enfoque que no se puede cumplir.
                location.href = "../cuarto/cuarto.pixi.html";
                return { ok: true, texto: "Abrí el Cuarto, donde viven tus piezas." };
              }
              // Un destino que el motor sume en el futuro y esta pantalla no conozca: se
              // dice con las MISMAS palabras que el motor usa para «no hay camino», en vez
              // de un `null` que su desenlace leería como un éxito mudo.
              return { ok: false, texto: "No tengo a dónde llevarte para eso todavía." };
            },
          },
        });
        // Hooks de verificación, mismo idiom que el Guía (`window.__guiaOpciones`): la
        // vara necesita poder emitir una opción sin un turno real del modelo.
        window.__salaOpciones = opcionesRef.current;
        window.__salaConexionInline = conexionInlineRef.current;
      } catch (e) {
        // Que el motor no cargue NO puede llevarse la Sala: sin él se chatea igual, sólo
        // que sin opciones tocables. Se reporta y se sigue.
        console.error("[opciones] no pude montar el motor de widgets:", e);
      }
    })();
    return () => {
      vivo = false;
      try { adaptadorRef.current?.destruir(); } catch (e) {}
      adaptadorRef.current = null;
      opcionesRef.current = null;
      conexionInlineRef.current = null;
    };
  }, []);

  // El catálogo y la elección VIVOS, para leerlos desde el callback de eventos sin meterlos
  // en sus deps: agregarlos ahí re-suscribiría el stream cada vez que cambia el modelo, que
  // es peor que el problema. Medido: sin esto, el aviso de fallo salía sin cerebro ni
  // alternativa porque el callback leía el catálogo de cuando montó — todavía vacío.
  const vivoRef = React.useRef({ choices: [], sel: null });
  vivoRef.current = { choices: modelos.choices || [], sel: modeloSeleccionado };

  // ── ELEGIR CEREBRO: UN SOLO CAMINO, PARA LOS DOS GESTOS ───────────────────────────
  // Se elige el cerebro de DOS maneras —el chip del composer y el botón «Usar otro
  // conectado» del error— y hasta acá cada una hacía algo distinto: el chip persistía por
  // el escritor único y el botón sólo movía estado de React. Consecuencia MEDIDA en la
  // .app instalada (ledger `cli_eventos.jsonl`, tres turnos): el chip decía «Codex» y
  // spawneaba `grok_cli`, que es el `default` que nunca se había reescrito. Es la misma
  // mentira que el bloque de arriba (:290) dice haber sacado —«elegí Grok» y «Grok corre»
  // como dos cosas distintas—, entrando por la otra puerta.
  //
  // Va en UNA función y no copiada en los dos llamadores a propósito: dos caminos para el
  // mismo gesto es exactamente lo que este archivo mata en su propio comentario de :1182.
  const elegirCerebro = React.useCallback(async (selectionRef) => {
    if (!selectionRef) return false;
    const previo = vivoRef.current.sel;
    setModeloSeleccionado(selectionRef);      // optimista: el chip responde al toque
    setModeloFinal(null);
    setModelIdentity(null);
    try {
      await window.AlephBrain.elegirCerebro(selectionRef);
      return true;
    } catch (err) {
      // Vuelve a lo que REALMENTE está elegido y lo dice. Un chip que se queda en el
      // modelo nuevo mientras el servidor sigue con el viejo es la mentira exacta que
      // esta obra vino a sacar.
      setModeloSeleccionado(previo || null);
      setAvisos((a) => [...a, tr(
        "salav2.aviso.cerebro_no_cambio",
        "No pude cambiar el cerebro. Sigue el de antes.",
      ) + ` (${err?.message || err})`]);
      recargarChoices();
      return false;
    }
  }, [recargarChoices]);
  // El `useEffect` de los eventos captura su closure una sola vez (deps `[agente,
  // maquina]`), así que el botón del error llega a la versión viva por ref — el mismo
  // recurso que ya usa `vivoRef` dos líneas arriba, y por la misma razón.
  const elegirCerebroRef = React.useRef(null);
  elegirCerebroRef.current = elegirCerebro;

  // Suscripción a los eventos del agente para la máquina de estados. Se hace acá y no
  // dentro del adaptador porque el adaptador no debe conocer la pantalla.
  React.useEffect(() => {
    const off = agente.subscribe?.({
      onEvent: ({ event }) => {
        // Seam de vara: los eventos AG-UI CRUDOS, antes de que nadie los interprete.
        // Es el único punto donde se puede afirmar «el turno terminó» sin depender de un
        // efecto secundario — y la vara lo necesitó: esperar al primer `veredicto` medía
        // demasiado pronto, porque el texto final del modelo llega DESPUÉS de él.
        try { window.__salaV2.onEventoEspia?.(event); } catch (_) { /* espía roto, turno vivo */ }
        maquina.consumir(event);
        // EL TÍTULO DEL HILO LO PONE EL BACKEND CON EL PRIMER MENSAJE, y la lista se pidió
        // ANTES de que ese mensaje existiera: el hilo abierto se quedaba en «Sin título»
        // para siempre (visto en captura). Al cerrar el turno se re-pide. El título es un
        // dato que ya existe server-side — acá no se fabrica ninguno.
        if (event?.type === "RUN_FINISHED" || event?.type === "RUN_ERROR") cargarHilos();
        // FALLO VISIBLE, JAMÁS MUDO — y acá casi se rompe la ley propia.
        // `MessagePrimitive.Error` sólo pinta si YA existe un mensaje al que colgarse. Un
        // turno que muere ANTES de que el modelo diga una letra no tiene ese mensaje, así
        // que el error no tenía dónde aparecer: la vara sobre la .app instalada midió
        // `RUN_STARTED → RUN_ERROR` con la pantalla en silencio absoluto. El fallo del run
        // es del HILO, no de un mensaje, y por eso se pinta al nivel del hilo.
        // Un turno nuevo arranca sin delegaciones: las del anterior ya se contaron y
        // dejarlas colgadas mostraría sub-agentes de un trabajo que terminó.
        if (event?.type === "RUN_STARTED") {
          setFallo(null);
          setDelegaciones([]);
          // [T2.5] El turno YA se llevó los adjuntos (el body salió con `images`), así que
          // el composer se vacía. Se hace acá y no en el click de enviar porque hay DOS
          // caminos de envío —el `Send` de assistant-ui y el nuestro con modo prendido— y
          // vaciar en uno solo dejaba el adjunto pegado justo en el otro.
          setAdjuntos([]);
        }
        if (event?.type === "RUN_ERROR") {
          // El cerebro que falló y el que queda: los dos salen del catálogo que la Sala ya
          // tiene cargado, así que el aviso no cuesta una petición de más.
          const { choices: _ch, sel: _sel } = vivoRef.current;
          const usado = _ch.find((m) => m.selection_ref === _sel);
          const otro = _ch.find((m) => m.selection_ref !== _sel);
          setFallo({
            mensaje: event.message || tr("salav2.err.turno", "No pude completar el turno."),
            causa: event.code || null,
            diagnostic: event.diagnostic || null,
            runtime_state: event.runtime_state || null,
            quota_availability: event.quota_availability || "unknown",
            provider_rate_limit_event: event.provider_rate_limit_event || null,
            // `message` trae el detalle del backend cuando la causa lo trajo: entonces ESE
            // es el texto, y no el del catálogo.
            detalle_propio: !!event.code && !!event.message,
            cerebro: usado?.label || modeloSeleccionado || null,
            alternativa: event.code === "no_provider" ? null : otro || null,
            setupHref: event.code === "no_provider"
              ? window.AlephBrain?.setupHref?.({ returnTo: location.pathname + location.search })
              : null,
            // PERSISTE, como el chip. Antes esto sólo movía estado de React: el
            // usuario veía el cerebro nuevo y el turno siguiente salía con el viejo.
            // El error se limpia sólo si el cambio ENTRÓ — si no, el aviso de
            // `elegirCerebro` queda a la vista y el fallo también, que es la verdad.
            onUsarAlternativa: (ref) => {
              Promise.resolve(elegirCerebroRef.current?.(ref)).then((ok) => {
                if (ok) setFallo(null);
              });
            },
          });
        }
      },
    });
    return () => {
      try {
        off?.unsubscribe?.();
      } catch (_) {
        /* ya desuscripto */
      }
    };
  }, [agente, maquina]);

  // ── hilos: la lista que antes vivía en «Chats» ──────────────────────────────────────
  //
  // `workspace=none` — LOS HILOS DE LA SALA, Y NADA MÁS. Los seis workspaces crean su hilo
  // con `POST /v1/chats` (`workspaces/<ws>.html`), así que viven en la MISMA tabla que los
  // de acá y esta lista los mostraba: medido en la `aleph.db` real, 6 de 82 —«Ciencia» con
  // 105 mensajes, «Diseño» 63, «Educación» 48…— y arriba de todo, porque el orden es
  // `updated_at DESC` y un workspace recién usado es lo más reciente que hay. Peor que
  // verlos: `rows[0]?.id` de abajo elegía uno de ELLOS como hilo por defecto de La Sala.
  //
  // No es un filtro nuevo en la pantalla: es el scope que el sidebar ya declaraba tener
  // («scope-ados por (user_id, puppet_id)», `ui/sidebar.js` §1) y que se le había quedado
  // corto cuando nació el segundo eje. La vista global sigue existiendo y es otra:
  // `Historial.dc.html`, con sus chips de espacio, que pide sin `workspace` y ve los 82.
  const cargarHilos = React.useCallback(() => {
    const u = usuario();
    if (!u?.id) return;
    const qs = "?workspace=none" + (PUPPET_ID ? "&puppet_id=" + encodeURIComponent(PUPPET_ID) : "");
    fetch("/v1/chats" + qs, { headers: authHeaders({}) })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        const rows = j?.chats || j || [];
        setHilos(rows);
        setHiloActual((actual) => {
          if (actual && rows.some((row) => row.id === actual)) return actual;
          let saved = null;
          try { saved = localStorage.getItem("aleph:sala:v2:chat:" + u.id); } catch (_) {}
          return (saved && rows.some((row) => row.id === saved)) ? saved : (rows[0]?.id || null);
        });
      })
      .catch(() => {
        /* sin lista de hilos la Sala igual funciona; no se rompe el turno por esto */
      });
  }, []);
  React.useEffect(cargarHilos, [cargarHilos]);

  React.useEffect(() => {
    const u = usuario();
    if (!u?.id) return;
    try {
      if (hiloActual) localStorage.setItem("aleph:sala:v2:chat:" + u.id, hiloActual);
      else localStorage.removeItem("aleph:sala:v2:chat:" + u.id);
    } catch (_) {}
  }, [hiloActual]);

  /**
   * EL CINTURÓN DEL AGENTE, una sola llamada.
   *
   * `belt_refs[]` ∪ `belt_ref` con de-dup: es la misma unión que la Sala vieja resolvió en
   * `sala.html:6424` — el schema declara el plural y el legacy dejó el singular, y una
   * receta real puede traer cualquiera de los dos.
   *
   * SÓLO SE PINTA LO QUE VIENE DE `catalog/`, y ése es el filtro correcto — no «excluir el
   * kit». Medido sobre los 1623 agentes reales, los refs se parten en dos familias:
   *
   *     catalog/belts/stem.md · catalog/templates/…      ← lo que el usuario ELIGIÓ
   *     platform/assembler/fixtures/… · deleg_fixtures/  ← data de prueba
   *     catalog/templates/kit/belt-kit.mcp.json          ← el kit base, infraestructura
   *
   * La primera versión de esto se apoyaba en que el kit declara 0 cards y «se excluye
   * solo». Es cierto y NO ALCANZA: `fixtures/belt-calc.mcp.json` (267 agentes) sí declara
   * cards, y pintarlas sería mostrar un belt de prueba como si el usuario lo hubiera
   * armado. El kit queda afuera por la misma regla, sin necesitar una lista de nombres.
   *
   * Los refs de fuera de `catalog/` SE SIGUEN PIDIENDO si el backend los necesita — acá
   * sólo se decide qué se PINTA.
   *
   * Un fetch que falla deja el cinturón VACÍO y la sección no se dibuja. Es deliberado:
   * decir «este agente no tiene herramientas» porque se cayó la red sería afirmar un hecho
   * que no medimos — y este agente puede tener cinco brazos.
   */
  const cargarCinturon = React.useCallback((config) => {
    const b = (config && config.belt) || {};
    const refs = [...(Array.isArray(b.belt_refs) ? b.belt_refs : []), ...(b.belt_ref ? [b.belt_ref] : [])]
      .filter(Boolean);
    // El kit vive DENTRO de catalog/ (`catalog/templates/kit/`), así que la ruta sola no
    // alcanza: se nombra, y es la única excepción declarada.
    const esDelUsuario = (r) => {
      const s = String(r || "").trim().toLowerCase().replace(/^\/+/, "");
      return s.startsWith("catalog/") && !s.includes("/kit/") && !s.includes("belt-kit");
    };
    const unicos = [...new Set(refs)].filter(esDelUsuario);
    if (!unicos.length) return;
    Promise.all(
      unicos.map((ref) =>
        fetch("/v1/belts/cards?ref=" + encodeURIComponent(ref), { headers: authHeaders({}) })
          .then((r) => (r.ok ? r.json() : null))
          .then((d) => d?.cards || [])
          .catch(() => []),
      ),
    ).then((tandas) => {
      const vistos = new Set();
      const piezas = [];
      for (const c of tandas.flat()) {
        const id = String(c?.id || c?.server || "");
        if (!id || vistos.has(id)) continue;
        vistos.add(id);
        piezas.push({ id, label: c.label || id, tools: Array.isArray(c.tools) ? c.tools : [] });
      }
      setCinturon(piezas);
    });
  }, []);

  // ── la receta del agente equipado ───────────────────────────────────────────────────
  //
  // [Convergencia · superficie 7 · paso 4] AQUÍ SE SUELTA EL PUENTE, y no en el montaje.
  //
  // La Sala vieja revela cuando el CINTURÓN del agente está pintado —o sea, cuando la
  // pantalla tiene de verdad lo que vino a mostrar— y falla honesto si el agente no
  // aparece. Ésta no pinta cinturón, así que su equivalente es la RECETA resuelta: con
  // `?puppet=` venimos del Cuarto a ver UN agente, y revelar antes mostraría una Sala que
  // todavía no sabe de quién es.
  //
  // Sin `?puppet=` no hay agente que esperar y se revela al montar: hacer esperar a una
  // charla suelta por un fetch que nunca va a pasar sería sostener el overlay por nada.
  React.useEffect(() => {
    const puente = window.__alephBridge;
    if (!PUPPET_ID) {
      puente?.ready();
      return;
    }
    // POR LA LISTA DEL DUEÑO, NO POR `/v1/puppets/{id}` — ESA RUTA NO EXISTE.
    //
    // Esto pedía `GET /v1/puppets/{id}` desde que se escribió, y el backend no la sirve:
    // el OpenAPI del server sólo tiene POST /v1/puppets · .../config · .../methods ·
    // .../memories · .../shelf · .../export.aleph y **GET /v1/users/{uid}/puppets**. La
    // respuesta era un 404 con `{"detail":"Not Found"}` pelado —el de FastAPI, no una
    // causa de Aleph— y el `catch` la tragaba: `setReceta(null)` y la Sala seguía sin
    // saber de quién era. Mudo, así que nadie lo vio.
    //
    // Lo destapó el puente del paso 4: al colgar el `ready()` de esta promesa, un agente
    // REAL empezó a mostrar «No encontré ese agente». El defecto era viejo; hacerlo ruido
    // fue lo que lo encontró. Es la misma resolución que usa la Sala vieja (`sala.html:6417`).
    const duenio = usuario();
    if (!duenio?.id) {
      puente?.ready();                 // sin dueño no hay lista que pedir: no se bloquea
      return;
    }
    fetch("/v1/users/" + encodeURIComponent(duenio.id) + "/puppets", { headers: authHeaders({}) })
      .then((r) => (r.ok ? r.json() : null))
      .then((r) => {
        const p = (r?.puppets || []).find((x) => x.id === PUPPET_ID) || null;
        setReceta(p?.config && typeof p.config === "object" ? p.config : null);
        if (p) cargarCinturon(p.config);
        // El agente NO está en la lista del dueño. `fail()` deja el overlay con su nota y
        // el camino de vuelta al Taller, en vez de revelar una Sala que no es la que se
        // pidió — la regla de la vieja: jamás revelar un inline disfrazado del agente.
        if (p) puente?.ready();
        else puente?.fail(tr("salav2.puente.sinAgente", "No encontré ese agente."));
      })
      .catch(() => {
        setReceta(null);
        puente?.fail(tr("salav2.puente.corte", "Se cortó la conexión al abrir la Sala."));
      });
  }, []);

  // ── el hilo se crea ANTES del turno, no después ─────────────────────────────────────
  // Sin `chat_id` el backend corre el turno igual pero NO lo registra: la conversación
  // desaparece al recargar. La vara lo destapó (`chat_id=null`, cero hilos tras recargar).
  // Mismo criterio que `ensureChat` de la Sala vieja, incluido el fail-soft: si la creación
  // falla (401/404), el turno corre lo mismo — el registro nunca bloquea la conversación.
  const pendiente = React.useRef(null);
  const asegurarHilo = React.useCallback(() => {
    const u = usuario();
    if (!u?.id) return Promise.resolve(null);
    if (hiloActual) return Promise.resolve(hiloActual);
    if (pendiente.current) return pendiente.current;
    pendiente.current = fetch("/v1/chats", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(PUPPET_ID ? { puppet_id: PUPPET_ID } : {}),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((c) => {
        pendiente.current = null;
        if (c?.id) {
          // [TANDA 1 · obra 1] Acá se arrastraba la elección «draft» al hilo recién creado,
          // porque el cerebro se guardaba POR CONVERSACIÓN. Ya no: es uno para la casa y
          // vive en `preferencias-v2.default`, así que un hilo nuevo nace con el mismo
          // cerebro sin que nadie tenga que copiar nada de un almacén a otro.
          setHiloActual(c.id);
          cargarHilos();
          return c.id;
        }
        return null;
      })
      .catch(() => {
        pendiente.current = null;
        return null;
      });
    return pendiente.current;
  }, [hiloActual, cargarHilos]);

  // El agente pide el hilo antes de cada turno; el `await` va adentro del adaptador porque
  // el `chat_id` tiene que viajar EN el body del run, no llegar después.
  React.useEffect(() => {
    agente._asegurarHilo = asegurarHilo;
    asegurarHiloRef.current = asegurarHilo;   // [T2.5c] el adjunto necesita el mismo hilo
  }, [agente, asegurarHilo]);

  const onGateDecidido = React.useCallback((sig, ok) => {
    setGates((prev) => prev.map((g) => (g.sig === sig ? { ...g, resuelto: true, aprobado: !!ok } : g)));
  }, []);

  return h(
    AssistantRuntimeProvider,
    { runtime },
    h(Sidebar, {
      hilos,
      hiloActual,
      puppetId: PUPPET_ID,
      workspaces,
      // Lo que el usuario equipó en el Cuarto. Vacío en RAW: sin agente no hay cinturón.
      cinturon,
      // BUSCAR EN LOS CHATS, rescatado de la vieja (`sala.html:2795`): mismo endpoint,
      // mismo debounce de 250 ms. Sin texto vuelve la lista normal — no se deja al usuario
      // en un resultado vacío por haber borrado lo que escribió.
      buscando,
      resultados,
      /* [convergencia · superficie 5 · F.5] BUSCAR EN LO PROPIO, no sólo en los chats.
         Acá se llamaba a `/v1/chats/search`, que sólo sabe de mensajes, y sus hits se
         aplanaban a una lista de hilos. El índice interno —`GET /v1/busqueda`, mergeado y
         montado— devuelve los TRES grupos (hilos · mensajes · artefactos) en una consulta,
         y no lo llamaba nadie: cero consumidores en todo `product/app/design/`. O sea que
         un artefacto propio era inencontrable desde cualquier pantalla.

         ⚠️ ESTA NO ES LA BÚSQUEDA WEB. Acá se busca en lo del usuario; el agente saliendo a
         internet es otra superficie y otro motor.

         El scope del dueño NO viaja desde acá: lo pone el backend con la sesión, y el
         índice lo exige como TOKEN del match — si esta capa se lo olvidara, la búsqueda
         levanta en vez de devolver de más (`platform/busqueda/indice.py`). Por eso no hay
         `user_id` en esta URL y no es un olvido. */
      onBuscar: (q) => {
        // Fuera del debounce a propósito: el input tiene que sobrevivir a la tecla, no
        // esperar 250 ms para enterarse de que hay una búsqueda en curso.
        setBuscando(!!q);
        clearTimeout(_tBuscar.current);
        _tBuscar.current = setTimeout(() => {
          if (!q) { setResultados(null); return cargarHilos(); }
          // El mínimo es del índice (`_MIN_Q = 2`), no de acá: con una sola letra el
          // endpoint contesta 422 y pintar «nada coincide» sería mentir sobre por qué.
          if (q.length < 2) return;
          fetch("/v1/busqueda?q=" + encodeURIComponent(q), { headers: authHeaders({}) })
            .then((r) => (r.ok ? r.json() : null))
            .then((d) => {
              if (!d) return;   // sin respuesta se conserva lo último: no se finge un vacío
              setResultados({ hilos: d.hilos || [], mensajes: d.mensajes || [],
                              artefactos: d.artefactos || [], recortado: !!d.recortado });
            })
            .catch(() => {});
        }, 250);
      },
      /* A DÓNDE LLEVA CADA GRUPO, y los tres destinos ya existían:
           hilo      → `ref` ES el chat_id
           mensaje   → `ref2` es su chat_id (`ref` es el id del mensaje, que no se abre solo)
           artefacto → `ref` es el artefacto y `ref2` su sesión de obra. Se abre en el
                       lienzo SÓLO si es de ESTA sesión; si es de otra, se va a la
                       Biblioteca en vez de abrir un lienzo que mostraría otra cosa. */
      onAbrirResultado: (it) => {
        if (!it) return;
        if (it.tipo === "hilo" && it.ref) return setHiloActual(it.ref);
        if (it.tipo === "mensaje" && it.ref2) return setHiloActual(it.ref2);
        if (it.tipo === "artefacto" && it.ref) {
          if (it.ref2 && it.ref2 !== SID) { location.href = "../Biblioteca.dc.html"; return; }
          abrirObra(it.ref);
        }
      },
      onAbrirHilo: (id) => setHiloActual(id),
      onNuevoHilo: () => {
        setHiloActual(null);
        setGates([]);
        setAvisos([]);
        setFallo(null);
        setModeloFinal(null);
        setModelIdentity(null);
        setDelegaciones([]);
      },
    }),
    h(Hilo, {
      modelIdentity,
      // LA PRIMERA TECLA CREA EL HILO: con su carpeta ya existiendo, el backend
      // arranca sus MCP mientras la persona termina de escribir (ver `precalentar_hilo`).
      onPrimeraTecla: asegurarHilo,
      maquina,
      gates,
      avisos,
      onGateDecidido,
      fallo,
      modoSala,
      onModo: setModoSala,
      adjuntos,
      onAdjuntar: agregarAdjunto,
      onQuitarAdjunto: quitarAdjunto,
      // [T2.5] ¿EL CEREBRO ELEGIDO PUEDE VER? Sale de la matriz REAL que el selector ya
      // trae (`model_use_capabilities`), no de una lista de nombres nuestra: es la MISMA
      // que el resolver usa para admitir la llamada, así que la pantalla y el backend no
      // pueden discrepar. `null` cuando todavía no cargó el catálogo — y ahí no se avisa
      // nada, porque «no sé» no es «no puede».
      puedeVer,
      onEnviarModo,
      refOpciones,
      obraViva,
      parandoObra,
      onPararObra,
      capacidadViva,
      modeloSelector: h(ModelChip, {
        motores,
            choices: modelos.choices,
            selectedRef: modeloSeleccionado,
            searchThreshold: modelos.searchThreshold,
            lockedLabel: receta?.model?.primary || null,
            // ELEGIR ESCRIBE LA FUENTE, y el fallo se DICE. Antes esto sólo movía
            // estado de React (y un localStorage que no viajaba), así que «elegí Grok»
            // y «Grok corre» eran dos cosas distintas sin nada que las uniera.
            onSelect: (selectionRef) => { elegirCerebro(selectionRef); },
          }),
      // El modelo REAL del turno, en este orden: el que el backend dijo que corrió
      // (`model_final`, que es el dato del anti-grift) y, mientras no haya corrido ninguno,
      // el que el selector canónico tiene elegido. Nunca un literal: si no hay ninguno de
      // los dos, va vacío.
      cerebro: modeloFinal
        || modelos.choices.find((m) => m.selection_ref === modeloSeleccionado)?.label
        || receta?.model?.primary
        || null,
      // Los sub-agentes de ESTE turno, en el hilo, mientras trabajan.
      delegaciones,
      // [O6b · 4.3] Las obras del turno, anunciadas EN EL HILO con su preview.
      tarjetas,
      destinos,
      onAbrirObra: abrirObra,
      onIrAlWorkspace: (ws) => {
        const q = PUPPET_ID ? "?puppet=" + encodeURIComponent(PUPPET_ID) : "";
        location.href = "../workspaces/" + encodeURIComponent(ws) + ".html" + q;
      },
    }),
    // [3.0 · deuda D3 · B10] LA MITAD DERECHA, QUE AHORA EMERGE. La regla de Fase 1 sigue
    // en pie y por eso esto funciona: lo que aquel defecto prohibía era que la columna
    // fuera y viniera SOLA, moviendo el chat a mitad de una conversación. Un turno ya no la
    // abre —anuncia su tarjeta en el hilo—, así que cuando aparece es porque el usuario la
    // pidió, y el movimiento es la consecuencia de su gesto en vez de una sorpresa.
    canvasAbierto
      ? h(Canvas, {
          artefactos: obras,
          activo: obraActiva,
          activoId: obraId,
          onAbrir: abrirObra,
          onRevertir: revertirObra,
          onCerrar: () => moverCanvas(false),
          urlDescarga: obraId ? Obras.urlDescarga(SID, obraId, null, usuario()?.session_token) : null,
          aviso: avisoObra,
          // [T2.6] El método del ÚLTIMO turno. Sale del veredicto, que ya lo trae con su
          // nombre: la pantalla no pide `/v1/methods/{id}` para poder nombrarlo.
          metodo: metodoDelTurno,
        })
      : null,
  );
}

function tr(k, fb) {
  const s = window.t ? window.t(k) : null;
  return s && s !== k ? s : fb;
}

/** Obra B de Gate 3: la sustitución SE ANUNCIA, con el payload que ya viene redactado. */
function textoSustitucion(v) {
  const pedido = v?.pedido || v?.requested || "?";
  const usado = v?.usado || v?.used || "?";
  return tr("salav2.aviso.sustituido", `Pediste ${pedido} y corrió ${usado}.`)
    .replace("{pedido}", pedido)
    .replace("{usado}", usado);
}

/** Obra 6 de Gate 3: perder la memoria en silencio es peor que perderla con aviso. */
function textoSesionPerdida() {
  return tr("salav2.aviso.sesion", "Perdí la memoria de la conversación anterior. Este turno arranca de cero.");
}

// ── montaje ───────────────────────────────────────────────────────────────────────────
const host = document.getElementById("sv-root");
ReactDOMClient.createRoot(host).render(h(App));
