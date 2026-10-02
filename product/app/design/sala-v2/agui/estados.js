// ESTADOS EN VIVO — derivados de los eventos AG-UI, de ninguna otra fuente.
//
// La regla madre de la Sala vieja (`sala.html:4330-4332`) sigue rigiendo acá y es la razón
// de que este archivo no tenga un solo `setTimeout` ni un solo estado optimista:
//
//     «todo punto/estado/tilde viene de un evento REAL. Sin evento → sin dibujo».
//
// Los siete estados del pedido, y el evento EXACTO que los enciende:
//
//   1 pensando               RUN_STARTED · REASONING_*
//   2 preparando tool        TOOL_CALL_START
//   3 esperando confirmación CUSTOM `aleph.gate_waiting`
//   4 ejecutando en [X]      TOOL_CALL_ARGS  (los args cerrados ⇒ la tool ya está corriendo)
//   5 recibiendo             TOOL_CALL_RESULT · CUSTOM `aleph.tool_meta`
//   6 interpretando          TEXT_MESSAGE_CONTENT **después** de que hubo una tool
//   7 final                  RUN_FINISHED · RUN_ERROR
//
// El 6 es el único que necesita memoria: «escribiendo» e «interpretando» son el MISMO
// evento (texto del modelo) y sólo se distinguen por si antes corrió una herramienta. Esa
// distinción es real —el usuario quiere saber si lo que lee sale de datos traídos o de la
// cabeza del modelo— así que se guarda ese bit y nada más.
//
// TEXTO Y TOOLS NO SE MEZCLAN: el hilo pinta el texto del modelo (assistant-ui, con sus
// message parts ordenados por el runtime) y esta máquina pinta el estado de la corrida.
// Son dos superficies, y por eso no compiten por el mismo renglón.

export const ESTADO = Object.freeze({
  QUIETO: "quieto",
  // [OBRA 2] El arranque del cinturón. Es el único estado que NO ocurre dentro de una
  // llamada al modelo: pasa ANTES de la primera, y hasta esta obra no se veía. Medido:
  // la Sala en frío tardaba 39,56 s en su primer evento y la pantalla decía «Pensando…»
  // todo ese tiempo. No hay timer detrás: enciende con `belt_starting` y apaga con
  // `belt_ready`, los dos eventos REALES de `recipe_assembler.py`.
  CINTURON: "cinturon",
  PENSANDO: "pensando",
  PREPARANDO: "preparando",
  ESPERANDO_OK: "esperando_ok",
  EJECUTANDO: "ejecutando",
  RECIBIENDO: "recibiendo",
  INTERPRETANDO: "interpretando",
  FINAL: "final",
  FALLO: "fallo",
});

/**
 * Copy por estado. Cae al literal en español si la clave no está en `i18n.js`, igual que
 * `trS` en la Sala vieja (`sala.html:928`).
 *
 * REGLA SELLADA del repo: ninguna causa llega a una superficie sin copy. Estos NO son
 * causas —son estados de progreso— pero valen la misma disciplina: el texto está acá, no
 * repartido por la pantalla, y un estado nuevo sin copy se ve como estado nuevo sin copy.
 */
const COPY = {
  [ESTADO.QUIETO]: ["salav2.estado.quieto", ""],
  // Sin el número el copy sería una frase que no dice nada nuevo; con él, cada arranque
  // informa de qué tamaño es el cinturón de ESTA receta. `{piezas}` sale del evento, no de
  // una cuenta local: si el evento no lo trae, la frase se queda sin el paréntesis.
  [ESTADO.CINTURON]: ["salav2.estado.cinturon", "Preparando las herramientas{piezas}…"],
  [ESTADO.PENSANDO]: ["salav2.estado.pensando", "Pensando…"],
  [ESTADO.PREPARANDO]: ["salav2.estado.preparando", "Preparando la herramienta…"],
  [ESTADO.ESPERANDO_OK]: ["salav2.estado.esperando_ok", "Esperando tu confirmación"],
  // [T2.2] «{servicio}» ahora es una ACCIÓN en castellano («leyendo un archivo»), no el
  // nombre crudo de una función, así que la preposición «en» ya no compone. Sin tool
  // conocida cae a «Ejecutando…», que sigue siendo verdad.
  [ESTADO.EJECUTANDO]: ["salav2.estado.ejecutando", "{servicio}…"],
  [ESTADO.RECIBIENDO]: ["salav2.estado.recibiendo", "Recibiendo el resultado…"],
  [ESTADO.INTERPRETANDO]: ["salav2.estado.interpretando", "Interpretando lo que llegó…"],
  [ESTADO.FINAL]: ["salav2.estado.final", "Listo"],
  [ESTADO.FALLO]: ["salav2.estado.fallo", "No pude completar el turno"],
};

/**
 * EL CINTURÓN VIVO, PERO DICHO EN CASTELLANO. [T2.2]
 *
 * La decisión de producto: las tools del piso son INTERNAS. El usuario no elige un
 * cinturón ni ve una lista de servers — ve QUÉ se hizo en el turno, en la línea de
 * razonamiento. Por eso esto no es un panel: es copy.
 *
 * El defecto que tapa, medido: `estados.js` ponía `servicio = ev.toolCallName`, o sea el
 * nombre CRUDO de la función. La línea decía «Ejecutando en run_python…» y
 * «Ejecutando en convert_to_markdown…». Eso es el nombre interno de una tool MCP filtrando
 * a la cara del producto — la misma clase de fallo que la regla sellada «ninguna causa
 * llega a una superficie sin copy» prohíbe para las causas.
 *
 * Cubre las 25 tools del kit base (`kit_base.KIT_TOOL_FILTERS`), que son las únicas que el
 * piso puede disparar. Una tool que NO esté acá NO se inventa ni se disfraza: cae al nombre
 * crudo, que es honesto y además hace visible el hueco. Mismo criterio que `copyDe`.
 */
const COPY_TOOL = {
  // 1 · CÓDIGO
  run_python: ["salav2.tool.run_python", "ejecutando código"],
  // 2 · ARCHIVOS
  read_text_file: ["salav2.tool.read_text_file", "leyendo un archivo"],
  read_multiple_files: ["salav2.tool.read_multiple_files", "leyendo varios archivos"],
  list_directory: ["salav2.tool.list_directory", "mirando la carpeta"],
  directory_tree: ["salav2.tool.directory_tree", "recorriendo las carpetas"],
  search_files: ["salav2.tool.search_files", "buscando entre los archivos"],
  get_file_info: ["salav2.tool.get_file_info", "mirando los datos del archivo"],
  list_allowed_directories: ["salav2.tool.list_allowed_directories", "viendo a qué carpetas llega"],
  write_file: ["salav2.tool.write_file", "escribiendo un archivo"],
  edit_file: ["salav2.tool.edit_file", "editando un archivo"],
  create_directory: ["salav2.tool.create_directory", "creando una carpeta"],
  move_file: ["salav2.tool.move_file", "moviendo un archivo"],
  // 3 · DATOS
  read_query: ["salav2.tool.read_query", "consultando los datos"],
  write_query: ["salav2.tool.write_query", "escribiendo en los datos"],
  create_table: ["salav2.tool.create_table", "creando una tabla"],
  list_tables: ["salav2.tool.list_tables", "viendo qué tablas hay"],
  // 4 · DOCUMENTOS
  convert_to_markdown: ["salav2.tool.convert_to_markdown", "leyendo el documento"],
  // 5 · WEB
  search: ["salav2.tool.search", "buscando en la web"],
  fetch_content: ["salav2.tool.fetch_content", "leyendo la página"],
  fetch: ["salav2.tool.fetch", "trayendo la página"],
};

/**
 * El nombre de una tool como se le dice a una persona. Sin entrada ⇒ el nombre crudo:
 * jamás se inventa uno, y el hueco queda a la vista.
 */
export function copyDeTool(nombreCrudo) {
  const par = COPY_TOOL[nombreCrudo];
  if (!par) return nombreCrudo || "";
  const [clave, fallback] = par;
  const traducido = typeof window !== "undefined" && window.t ? window.t(clave) : null;
  return traducido && traducido !== clave ? traducido : fallback;
}

export function copyDe(estado, datos) {
  const [clave, fallback] = COPY[estado] || COPY[ESTADO.QUIETO];
  const traducido = typeof window !== "undefined" && window.t ? window.t(clave) : null;
  let texto = traducido && traducido !== clave ? traducido : fallback;
  if (texto.includes("{servicio}")) {
    const s = (datos && datos.servicio) || "";
    texto = texto.replace("{servicio}", s ? copyDeTool(s) : "Ejecutando");
  }
  if (texto.includes("{piezas}")) {
    // Mismo criterio que `{servicio}`: sin dato NO se inventa un número, se cae a la frase
    // sin él. Un «(0)» sería mentira y un «(?)» sería ruido.
    const n = datos && Number.isFinite(datos.piezas) ? datos.piezas : null;
    texto = texto.replace("{piezas}", n ? ` (${n})` : "");
  }
  return texto;
}

/**
 * La máquina. No conoce React ni el DOM: recibe eventos AG-UI y avisa cuándo cambió.
 * Se le pasan los MISMOS eventos que van al hilo (`onEvent` del agente), así que no hay
 * dos verdades que puedan divergir.
 */
export class MaquinaDeEstados {
  /**
   * Dos canales, a propósito y no por gusto:
   *
   *   `onCambio` — lo pisa el componente que pinta la línea de estado (React lo reasigna en
   *                cada montaje, que es lo normal).
   *   `onTraza`  — lo pone el arranque UNA vez y nadie más lo toca. Existe porque si la vara
   *                usara `onCambio`, el `useEffect` del componente lo sobrescribiría al
   *                montar y la vara terminaría midiendo un canal muerto.
   *
   * Un solo callback no alcanza cuando hay dos consumidores con ciclos de vida distintos.
   */
  constructor(onCambio, onTraza) {
    this.onCambio = onCambio || (() => {});
    this.onTraza = onTraza || (() => {});
    this.reset();
  }

  reset() {
    this.estado = ESTADO.QUIETO;
    this.servicio = null; // el server MCP en el que corre la tool
    this.huboTool = false; // el bit que separa «escribiendo» de «interpretando»
    this.gate = null; // la retención viva, si hay
    this._ultimo = null;
  }

  _ir(estado, datos) {
    if (this.estado === estado && this._ultimo === JSON.stringify(datos || null)) return;
    this.estado = estado;
    this._ultimo = JSON.stringify(datos || null);
    const v = {
      estado,
      // Los `datos` del propio salto entran al copy. Antes sólo entraba `servicio`, así que
      // un estado con un dato propio —el `{piezas}` del cinturón— no tenía cómo decirlo.
      // `servicio` va después para que un salto no pueda pisarlo sin querer.
      texto: copyDe(estado, { ...(datos || {}), servicio: this.servicio }),
      servicio: this.servicio,
      gate: this.gate,
      huboTool: this.huboTool,
    };
    try {
      this.onTraza(v);
    } catch (_) {
      /* un observador roto no puede tumbar la máquina */
    }
    this.onCambio(v);
  }

  /**
   * [§6.a.bis] UN SOBRE QUE YA VIENE MASTICADO, de un motor que no habla AG-UI.
   *
   * La búsqueda web no pasa por `/v1/puppets/run/stream`: su pack emite sus propios
   * sobres `{etapa, estado, texto}` —los produce `platform/sala/busqueda/etapas.py`— y
   * traen algo que `copyDe()` no puede dar: **el número**. «81 resultados» y «19 fuentes
   * citadas» no son copy de un estado, son el estado.
   *
   * Por eso este método es ADITIVO y no toca `consumir()`: los eventos AG-UI siguen
   * entrando por donde entraban, y el texto propio del sobre gana sobre el genérico
   * SÓLO cuando viene. Un sobre sin texto cae al copy de siempre.
   */
  externo(sobre) {
    if (!sobre || !sobre.estado) return;
    this.estado = sobre.estado;
    this._ultimo = JSON.stringify(sobre);
    const v = {
      estado: sobre.estado,
      texto: sobre.texto || copyDe(sobre.estado, { servicio: this.servicio }),
      etapa: sobre.etapa || null,
      servicio: this.servicio,
      gate: this.gate,
      huboTool: true,          // la búsqueda ES una corrida con herramientas
    };
    try { this.onTraza(v); } catch (_) { /* un observador roto no tumba la máquina */ }
    this.onCambio(v);
  }

  /** @param {{type:string,[k:string]:any}} ev evento AG-UI ya tipado */
  consumir(ev) {
    if (!ev || !ev.type) return;
    switch (ev.type) {
      case "RUN_STARTED":
        this.reset();
        this._ir(ESTADO.PENSANDO);
        break;

      case "REASONING_START":
      case "REASONING_MESSAGE_CONTENT":
        this._ir(ESTADO.PENSANDO);
        break;

      case "TOOL_CALL_START":
        this.huboTool = true;
        this.servicio = ev.toolCallName || null;
        this._ir(ESTADO.PREPARANDO);
        break;

      case "TOOL_CALL_ARGS":
        // Los args completos significan que la llamada salió: de acá en adelante la tool
        // está corriendo del otro lado. No se adivina: es el último evento antes de que el
        // assembler ejecute.
        this._ir(ESTADO.EJECUTANDO);
        break;

      case "TOOL_CALL_RESULT":
        this._ir(ESTADO.RECIBIENDO);
        break;

      case "TEXT_MESSAGE_CONTENT":
        // Texto del modelo. Si antes corrió una tool, lo que escribe es lectura de lo que
        // trajo; si no, es respuesta directa. Los dos son «avanzando», con nombre distinto.
        this._ir(this.huboTool ? ESTADO.INTERPRETANDO : ESTADO.PENSANDO);
        break;

      case "RUN_FINISHED":
        this.gate = null;
        this._ir(ESTADO.FINAL);
        break;

      case "RUN_ERROR":
        this.gate = null;
        this._ir(ESTADO.FALLO, { detalle: ev.message || null });
        break;

      case "CUSTOM":
        this._custom(ev);
        break;

      default:
        break; // un evento que no mueve el estado no lo mueve. No hay estado por defecto.
    }
  }

  _custom(ev) {
    switch (ev.name) {
      case "aleph.gate_waiting":
        this.gate = ev.value || null;
        this.servicio = ev.value?.server || this.servicio;
        this._ir(ESTADO.ESPERANDO_OK, { sig: ev.value?.sig });
        break;

      case "aleph.gate_resolved":
        this.gate = null;
        // Resuelto el gate, el run sigue: vuelve a lo que estaba haciendo.
        this._ir(ev.value?.approved ? ESTADO.EJECUTANDO : ESTADO.PENSANDO);
        break;

      case "aleph.cinturon":
        // Los dos bordes del arranque. `listo:true` NO va a un estado propio de «listo»:
        // lo que sigue de verdad es la primera llamada al modelo, así que vuelve a
        // «Pensando…», que es lo que está pasando. Inventar un «Listo» que dura 0 ms sería
        // teatro. Y no pisa nada más avanzado: si el turno ya arrancó tools, se ignora.
        if (ev.value?.listo) {
          if (this.estado === ESTADO.CINTURON) this._ir(ESTADO.PENSANDO);
        } else if (this.estado === ESTADO.QUIETO || this.estado === ESTADO.PENSANDO) {
          this._ir(ESTADO.CINTURON, { piezas: ev.value?.piezas ?? null });
        }
        break;

      case "aleph.tool_meta":
        this._ir(ESTADO.RECIBIENDO, { call_id: ev.value?.call_id });
        break;

      case "aleph.tool_inicio":
        this.servicio = ev.value?.server || ev.value?.nombre || this.servicio;
        break;

      case "aleph.costo":
        // Medido: `cost` es el PRIMER evento que emite un turno equipado, ~3,4 s antes de
        // que el POST vuelva. Es el que convierte una espera muda en «está pasando algo».
        // No cambia el estado si ya avanzamos más: sólo saca al turno de «quieto».
        if (this.estado === ESTADO.QUIETO) this._ir(ESTADO.PENSANDO);
        break;

      default:
        break;
    }
  }
}
