/* causas-catalogo.js — EL VOCABULARIO DE CAUSAS DEL VIAJE. Una sola copy por causa.
 *
 * Vivía dentro de `superficie-catalogo.js`, y ahí estaba bien mientras la sección era la
 * única que pintaba un viaje. Dejó de estarlo: el HUD del Cuarto (`cuarto/catalog_equip.js`)
 * también muestra el fracaso, y estaba echando mano del `detail` que mandaba el backend —
 * o sea una SEGUNDA copy, escrita en Python, que además decía otra cosa. Dos textos para el
 * mismo hecho son dos textos que se desincronizan.
 *
 * Así que el vocabulario se mudó acá, sin dueño: lo importan las dos superficies.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * LA REGLA SELLADA: **ninguna causa llega a una superficie sin copy.** Si el backend emite
 * una causa que esta tabla no conoce, NO se pinta su nombre técnico crudo ni se calla: se
 * deriva una frase honesta y se marca `provisional`, para que la falta se vea y se arregle.
 *
 * LA SEGUNDA REGLA, que costó una auditoría: **ninguna frase culpa a la ficha si la ficha
 * está bien.** `curacion_rechazo` decía «no respondió como su ficha dice que responde» para
 * los cuatro mundos distintos que el backend colapsaba en ella — y para un dominio que no
 * existe eso es, directamente, falso. Medido: de 20 piezas del registro, 16 quedaban bien
 * clasificadas y las 4 que fallaban estaban muertas de verdad. La comprobación estaba bien;
 * el que mentía era el texto.
 */

export function lang() {
  try {
    return String(typeof window !== "undefined" && window.AlephI18n && AlephI18n.lang
      ? AlephI18n.lang() : "es").startsWith("en") ? "en" : "es";
  } catch (_) { return "es"; }
}
export const L = (es, en) => (lang() === "en" ? en : es);

/* ══════════════════════════════════════════════════════════════════════════════════════
 * LAS CAUSAS DEL VIAJE · cada una con su copy y su camino.
 *
 * `accion` NO es un texto: es qué botón corresponde. El rótulo lo pone `pintarSalida`, así
 * un mismo camino se llama igual en todas partes. `"nada"` es una acción de pleno derecho —
 * hay fracasos que no tienen salida, y ofrecer un botón que no va a servir es peor que no
 * ofrecer ninguno.
 * ════════════════════════════════════════════════════════════════════════════════════ */
export const CAUSAS_CATALOGO = {
  registry_unreachable: {
    es: "El registro público no contestó. No es que la pieza no exista: no pudimos preguntar.",
    en: "The public registry didn't answer. It's not that the piece doesn't exist: we couldn't ask.",
    accion: "reintentar",
  },
  no_confiable: {
    es: "No pudimos comprobar de quién es esta pieza.",
    en: "We couldn't confirm who this piece belongs to.",
    accion: "traer_asi",
  },
  sin_prueba_de_origen: {
    es: "El registro la sirve, pero nadie probó que sea de quien dice ser.",
    en: "The registry serves it, but nobody proved it belongs to who it claims.",
    accion: "traer_asi",
  },
  candidato_distinto_del_oficial: {
    es: "La que elegiste no es la oficial verificada de ese servicio.",
    en: "The one you picked isn't the verified official one for that service.",
    accion: "traer_la_buena",
  },

  /* ── LAS CUATRO FINAS · selladas por persona usuaria el 2026-08-07 ──────────────────────────────
   * Salieron de partir `curacion_rechazo`, que las decía a todas con la misma frase y con
   * la culpa puesta en la ficha. Van en orden de qué tan lejos llegó el intento: no llegué
   * a llamar · llamé y no contestó · contestó pidiendo algo que no declara · contestó bien
   * y no trae nada. */
  servicio_inexistente: {
    // NO dice «revisá la URL» a secas: el usuario puede haber pegado bien lo que le dieron
    // mal. Dice qué pasó —esa dirección no existe— y deja la decisión donde corresponde.
    es: "Esa dirección no existe: el nombre no resuelve. No llegamos a hablar con nadie.",
    en: "That address doesn't exist: the name doesn't resolve. We never got to talk to anyone.",
    accion: "nada",
  },
  // ── [Gate 4 · Fase 6 · §6.a.bis] LAS CAUSAS DE LA BÚSQUEDA WEB DE LA SALA ───────────
  // Se agregan acá y no en el router porque la regla sellada las quiere en UN lugar: el
  // backend ya manda su `copy`, pero la Sala resuelve por esta tabla, y sin entrada
  // propia pintaba «motor_no_responde · sin copy propia todavía». MEDIDO EN PANTALLA,
  // que es la única forma en que esto se ve: la vara del servidor pasa igual.
  motor_no_responde: {
    es: "El buscador no contestó. No es tu consulta: el motor no está respondiendo.",
    en: "The search engine didn't answer. It's not your query: the engine isn't responding.",
    accion: "reintentar",
  },
  pack_no_arranco: {
    es: "El buscador no llegó a levantarse.",
    en: "The search engine couldn't start.",
    accion: "reintentar",
  },
  pack_no_instalado: {
    es: "La búsqueda web no viajó con esta instalación.",
    en: "Web search didn't ship with this installation.",
    accion: null,
  },
  sin_red: {
    es: "No se pudo hablar con el buscador. Revisa tu conexión.",
    en: "Couldn't reach the search engine. Check your connection.",
    accion: "reintentar",
  },
  consulta_vacia: {
    es: "Escribe algo para buscar.",
    en: "Type something to search for.",
    accion: null,
  },
  sin_fuentes: {
    // NO es un fallo: la búsqueda corrió y no encontró nada citable. Se dice, no se
    // disimula — una respuesta de búsqueda web sin bibliografía es una señal.
    es: "La búsqueda no encontró fuentes para citar.",
    en: "The search found no sources to cite.",
    accion: null,
  },
  // ── [Gate 4 · Fase 6 · §6.a] LAS CAUSAS DE BROWSER USE ────────────────────────────
  // Van acá por la MISMA razón que costó una auditoría en §6.a.bis: el router de búsqueda
  // mandaba `copy` y la Sala igual decía «sin copy propia todavía», porque este catálogo no
  // las conocía. Ninguna vara lo atrapó — se vio mirando la pantalla. Así que las causas del
  // navegador entran ACÁ el mismo día que nacen, no después.
  //
  // Las dos primeras NO son fallos: son ESTADOS del cerebro elegido, y se dicen ANTES de
  // arrancar. Un usuario que va a mandar al agente a una página con un mapa tiene que poder
  // leer que este cerebro no ve, en vez de descubrirlo cuando el turno se pierde.
  browser_sin_vision: {
    es: "Este cerebro no ve imágenes, así que voy a navegar leyendo la estructura de la página. En páginas con mapas, gráficos o botones sin texto puedo no encontrar lo que buscas. Con un modelo que vea, uso capturas.",
    en: "This brain can't see images, so I'll navigate by reading the page structure. On pages with maps, charts, or buttons without text I may not find what you need. With a model that sees, I use screenshots.",
    accion: "elegir_modelo",
  },
  // ── EL CEREBRO NO ALCANZA PARA ESTE PEDIDO ────────────────────────────────────────
  // Las tira el resolver de model-use (`model_use_resolver.py`) y llegan a la pantalla por
  // `hilo.js:654`. Hasta hoy NO tenían copy: la causa viajaba entera —tipada, con
  // `aleph.missing`— y el hilo caía en el respaldo `provisional`, o sea que el usuario leía
  // «No se pudo completar el viaje de esta pieza» sobre algo que sí sabemos explicar.
  //
  // ⚠️ EL COPY NO NOMBRA «imágenes», Y ESO ES A PROPÓSITO. `capability_unavailable` es
  // GENÉRICA: hoy la única capacidad que se exige es `vision`, pero mañana puede ser otra,
  // y una frase que diga «tu cerebro no ve» sería un diagnóstico inventado en cuanto eso
  // cambie. Es el mismo error del gate que imprimía «falta código nuestro» para cualquier
  // fallo: detectaba bien y diagnosticaba mal. Acá se dice lo que SÍ se sabe —falta una
  // capacidad, elegí otro modelo— y la capacidad concreta viaja en `aleph.missing`.
  //
  // DEUDA DECLARADA, no inventada: para nombrarla en la frase hace falta que ese detalle
  // llegue a la superficie, y `causaDe(causa, literal)` sólo elige entre claves fijas. No
  // se resuelve escribiendo copy: se resuelve cableando el detalle.
  //
  // Y el aviso PREVIO ya existe y no se duplica: la Sala avisa ANTES de enviar cuando el
  // cerebro no ve (`salav2.adjuntar.sin_vision`, `hilo.js:435`). Esto es lo otro — lo que
  // se dice cuando el turno ya falló, que hasta hoy no se decía.
  capability_unavailable: {
    es: "El cerebro que elegiste no tiene una de las capacidades que este pedido necesita, así que el turno no salió.",
    en: "The brain you picked lacks one of the capabilities this request needs, so the turn didn't run.",
    accion: "elegir_modelo",
  },
  // La hermana, y va junta porque la deja el MISMO resolver dos ramas más arriba: acá el
  // modelo puede tener la capacidad, pero no declara su matriz, así que no se puede
  // afirmar. Dejarla sin copy sería volver a abrir el agujero que esta entrada tapa.
  capability_unknown: {
    es: "Todavía no sabemos qué sabe hacer el cerebro que elegiste, y este pedido exige una capacidad concreta. Elige un modelo del catálogo del proveedor.",
    en: "We don't yet know what the brain you picked can do, and this request requires a specific capability. Pick a model from the provider's catalog.",
    accion: "elegir_modelo",
  },
  // ── Y LAS OTRAS DOS DEL MISMO RESOLVER ────────────────────────────────────────────
  // Mismo agujero, dos causas más: viajaban tipadas y el hilo las mostraba como «No se
  // pudo completar el viaje de esta pieza».
  //
  // ⚠️ `no_session` ES EL MISMO HECHO QUE `sin_sesion`, QUE YA TIENE COPY ACÁ ABAJO — y
  // aun así NO se reusa la frase, sólo la ACCIÓN. La de `sin_sesion` dice «para traer una
  // pieza a tu local»: está atada al flujo de conectores. Mostrarla cuando lo que se cayó
  // fue un TURNO le contaría al usuario que estaba haciendo algo que no estaba haciendo —
  // la misma clase de mentira que evitar «no ve imágenes» en la causa genérica, sólo que
  // por copiar de más en vez de por inventar. Se comparte `accion: "login"`, que es lo que
  // de verdad es común.
  no_session: {
    es: "Hay que entrar a tu cuenta para esto.",
    en: "You need to sign in for this.",
    accion: "login",
  },
  // Dice las DOS mitades porque el resolver falla por las dos: no hay elección explícita
  // **ni** un Default resoluble. Decir sólo «elegí un modelo» dejaría afuera al que sí
  // tenía uno por defecto y se le rompió.
  selection_missing: {
    es: "No hay un cerebro elegido ni uno por defecto que sirva. Elige uno en Modelos.",
    en: "There's no brain picked and no usable default. Pick one in Models.",
    accion: "elegir_modelo",
  },
  // ── LAS CUATRO QUE FALTABAN DE LA MISMA FAMILIA ───────────────────────────────────
  // Todas fallan ANTES de que el turno llegue al cerebro, todas viajaban tipadas, y todas
  // caían en el respaldo `provisional` — el usuario veía el turno muerto sin saber por qué.
  //
  // NINGUNA REUSA UNA FRASE, Y NO ES POR NO BUSCAR. Se buscaron las candidatas y las tres
  // que había están atadas a OTRO flujo:
  //   · `servicio_inexistente` («esa dirección no existe: el nombre no resuelve») es un DNS
  //     de conector, no un modelo que no está en el catálogo;
  //   · `credencial_no_declarada` («pide una llave que su ficha no declara») culpa a la
  //     ficha de la pieza, y acá no hay pieza ni ficha;
  //   · `falta_key` («falta tu llave») vive en el OTRO diccionario —el semáforo del
  //     Cuarto— y además diagnostica de más: ver `model_not_connected`.
  // Copiarlas sería la mentira por copiar de más, que ya se pagó una vez con `sin_sesion`.
  // Lo que SÍ se reusa es la ACCIÓN: `elegir_modelo`, que ya existía.

  // La elección resolvió a una fila del catálogo… y la fila no trae con qué correr. El
  // usuario no hizo nada mal: es un dato nuestro incompleto, y el copy no lo culpa.
  model_unresolved: {
    es: "El modelo que elegiste está en tu catálogo pero no tiene con qué correr. Elige otro en Modelos.",
    en: "The model you picked is in your catalog but has nothing to run with. Pick another one in Models.",
    accion: "elegir_modelo",
  },
  // ⚠️ SE DICE «NO ESTÁ», NO «YA NO ESTÁ». La causa la tiran DOS sitios con matices
  // distintos: el resolver dice «no existe en el catálogo de este dueño» (pudo no haber
  // estado nunca) y la ejecución dice «ya no existe» (estaba y desapareció). Una frase que
  // afirme que estaba sería inventar la mitad que no sabemos.
  selection_not_found: {
    es: "El modelo que quedó elegido no está en tu catálogo. Elige uno en Modelos.",
    en: "The selected model is not in your catalog. Choose one in Models.",
    accion: "elegir_modelo",
  },
  // Ésta NO es una elección del usuario: es una RECETA (un Aleph) cuyo cerebro no se puede
  // resolver a nada del catálogo. Decirle «elegiste mal» sería culparlo de algo que no
  // eligió él.
  selection_unmapped: {
    es: "Este Aleph todavía no tiene un cerebro que se pueda resolver. Elige uno en Modelos.",
    en: "This Aleph does not yet have a resolvable brain. Choose one for it in Models.",
    accion: "elegir_modelo",
  },
  // ⚠️ NO DICE «FALTA TU LLAVE», Y ES EL MISMO CRITERIO QUE `capability_unavailable`.
  // `model_not_connected` es un ENVOLTORIO: el motivo fino viaja aparte, en
  // `aleph.cause`, y puede ser `falta_key`, `key_invalida`, `cli_no_instalado`,
  // `sin_sesion` o `plan_insuficiente` (`cuarto.semaforo.js:271`). Decir «pegá tu llave»
  // acertaría a veces y mentiría el resto — y por eso la acción tampoco es `llave`:
  // `elegir_modelo` lleva a Modelos, que es donde se termina de conectar O se elige otro,
  // que son las dos salidas verdaderas.
  model_not_connected: {
    es: "El modelo que elegiste todavía no está conectado. Termina de conectarlo en Modelos, o elige otro.",
    en: "The model you picked isn't connected yet. Finish connecting it in Models, or pick another.",
    accion: "elegir_modelo",
  },
  browser_cerebro_lento: {
    es: "Este cerebro tarda más de lo que un navegador aguanta por paso. Para manejar el navegador conviene un cerebro de CLI o de API.",
    en: "This brain is slower than a browser step can wait for. To drive the browser, a CLI or API brain works better.",
    accion: "elegir_modelo",
  },
  tarea_vacia: {
    es: "Dime qué quieres que haga en el navegador.",
    en: "Tell me what you want done in the browser.",
    accion: null,
  },
  navegador_ausente: {
    es: "El navegador no viajó con esta instalación.",
    en: "The browser didn't ship with this install.",
    accion: null,
  },
  url_bloqueada: {
    // La regla de loopback (platform/browser/REGLA-LOOPBACK.md): sólo puertos que este
    // mismo trabajo levantó. No es un error del usuario y el texto no lo trata como tal.
    es: "No puedo abrir esa dirección desde aquí: sólo puedo entrar a lo que este mismo trabajo levantó.",
    en: "I can't open that address from here: I can only reach what this same job started.",
    accion: null,
  },
  motor_roto: {
    es: "El navegador se cortó a mitad del trabajo.",
    en: "The browser stopped midway through the job.",
    accion: "reintentar",
  },
  parado: {
    es: "Paraste el trabajo.",
    en: "You stopped the job.",
    accion: null,
  },
  // ── [Gate 4 · Fase 6 · §6.f] LAS CAUSAS DEL MODO LARGO DE LA SALA ──────────────────
  // Van acá por lo mismo que las de su hermano, y sabiendo lo que costó allá: el router
  // manda su `copy`, pero la Sala resuelve por ESTA tabla, así que una causa que no esté
  // acá se pinta «… · sin copy propia todavía». **No lo ve ninguna vara** —la del servidor
  // pasa igual, porque el copy sí sale del backend—: sólo se ve mirando la pantalla.
  //
  // `motor_no_responde`, `pack_no_arranco`, `pack_no_instalado`, `sin_red` y
  // `consulta_vacia` ya están arriba, puestas por §6.a.bis, y se comparten a propósito: son
  // el mismo hecho contado igual. Lo que sigue es lo que sólo puede pasarle a este modo.
  // ── [T2.5] LAS CINCO CAUSAS DEL MOTOR, que llegaban a la Sala SIN COPY ────────────
  // MEDIDO EN PANTALLA contra la .app instalada (2aa64a13): un turno del piso falló y la
  // Sala pintó literalmente «auth-rejected · sin copy propia todavía». El nombre interno de
  // un error del assembler, en la cara del producto — la misma clase de fallo que la regla
  // sellada prohíbe, y que ninguna vara ve porque el sobre viaja igual.
  //
  // Las cinco salen de `recipe_assembler._safe_err`, que es el ÚNICO lugar que las nombra.
  // Se transcriben desde ahí y no de memoria: una causa que el motor no emite sería copy
  // muerto, y una que emite y falta acá vuelve a pintar su nombre interno.
  //
  // El guion es parte del identificador (`auth-rejected`, no `auth_rejected`): así lo manda
  // el motor y así se busca.
  "auth-rejected": {
    // NO se dice «tu llave está mal»: puede ser la llave, la suscripción vencida, o —lo que
    // pasó acá— otro proceso local que tomó el puerto del cerebro con otra credencial. Se
    // dice el HECHO (no te dejó entrar) y se manda a donde se arregla.
    es: "Tu cerebro rechazó la credencial. Revisa que siga conectado en Modelos.",
    en: "Your brain rejected the credential. Check it's still connected under Models.",
    // ⚠️ `accion: null`, y NO un «abrir_modelos» inventado. Lo escribí así en el primer
    // intento y no lo despacha NADIE: habría sido un botón que no lleva a ningún lado —
    // exactamente el botón falso que la regla de `caminoDe` prohíbe. La causa sola ya es
    // el valor; el camino se cablea cuando exista quien lo atienda.
    accion: null,
  },
  timeout: {
    es: "Tu cerebro tardó demasiado y corté el turno. Nada quedó a medias.",
    en: "Your brain took too long and I cut the turn. Nothing was left half-done.",
    accion: "reintentar",
  },
  "connection-refused": {
    es: "No pude alcanzar a tu cerebro. Si es un CLI local, fíjate que esté corriendo.",
    en: "I couldn't reach your brain. If it's a local CLI, check that it's running.",
    accion: "reintentar",
  },
  "payload-too-large": {
    // La causa REAL del 413, que durante toda una fase se anunció como rate-limit. El copy
    // dice qué achicar, porque «too large» sin objeto no le sirve a nadie.
    es: "El turno llegó demasiado grande para tu cerebro. Prueba con menos herramientas equipadas o un pedido más corto.",
    en: "The turn arrived too large for your brain. Try fewer equipped tools or a shorter request.",
    accion: "reintentar",
  },
  "rate-limited": {
    es: "Tu cerebro te frenó por límite de uso. Espera un rato o elige otro modelo.",
    en: "Your brain rate-limited you. Wait a bit or pick another model.",
    accion: "reintentar",
  },
  informe_sin_fuentes: {
    // LA CAUSA DEL VERDE MUDO. El motor contestó, escribió, y no trajo una sola fuente
    // verificable. La frase dice las dos mitades: que no sirve COMO investigación, y que
    // el borrador está guardado igual — porque lo está, y no decirlo sería tirar minutos
    // de trabajo del usuario en silencio.
    es: "La investigación terminó sin una sola fuente verificable. Guardé el borrador, pero no es un informe: no hay de dónde comprobarlo.",
    en: "The research finished without a single verifiable source. I saved the draft, but it isn't a report: there's nothing to check it against.",
    accion: "reintentar",
  },
  investigacion_sin_busqueda: {
    // Y ésta es su CAUSA, no su síntoma: si nunca buscó, mandar a mirar el buscador sería
    // el consejo equivocado. Lo que falló es la estrategia, y reintentar sí puede servir.
    es: "La investigación nunca llegó a buscar: lo que hay está escrito de memoria, no consultado.",
    en: "The research never got to search: what's there was written from memory, not looked up.",
    accion: "reintentar",
  },
  obra_cancelada: {
    // NO es un fallo, y la frase no puede sonar a uno: lo pidió el usuario. Sin acción,
    // porque no hay nada que reparar.
    es: "Paraste esta investigación.",
    en: "You stopped this research.",
    accion: null,
  },
  sin_buscador: {
    es: "El modo de investigación no tiene buscador configurado, y sin buscar no puede investigar.",
    en: "Research mode has no search engine configured, and without searching it can't research.",
    accion: null,
  },
  motor_no_instalado: {
    es: "El motor de investigación no viajó con esta instalación.",
    en: "The research engine didn't ship with this installation.",
    accion: null,
  },
  motor_fallo: {
    es: "La investigación falló.",
    en: "The research failed.",
    accion: "reintentar",
  },
  cerebro_sin_config: {
    es: "El modo de investigación no recibió su configuración.",
    en: "Research mode didn't receive its configuration.",
    accion: "reintentar",
  },
  cerebro_config_ilegible: {
    es: "La configuración del modo de investigación está rota.",
    en: "Research mode's configuration is broken.",
    accion: null,
  },
  cerebro_config_incompleta: {
    es: "La configuración del modo de investigación está incompleta.",
    en: "Research mode's configuration is incomplete.",
    accion: null,
  },
  cerebro_sin_sdk: {
    es: "Este build no trae el motor de investigación.",
    en: "This build doesn't include the research engine.",
    accion: null,
  },
  cuerpo_invalido: {
    // Las dos que siguen son DE PROTOCOLO: sólo pueden pasar si quien llama está mal
    // escrito, no si el usuario hizo algo. Llevan copy igual, porque la regla no admite
    // excepciones por improbabilidad — si alguna vez llegan a una pantalla, un slug crudo
    // sería peor. Es la misma decisión que `servidor.py` tomó del otro lado del cable.
    es: "La Sala mandó un pedido que no se entiende.",
    en: "The Room sent a request that couldn't be understood.",
    accion: "reintentar",
  },
  ruta_desconocida: {
    es: "Ese camino no existe en el modo de investigación.",
    en: "That path doesn't exist in research mode.",
    accion: null,
  },
  obra_desconocida: {
    es: "No sé qué investigación parar.",
    en: "I don't know which research to stop.",
    accion: null,
  },
  servicio_no_responde: {
    // Lo importante de esta frase es la segunda mitad: que no es culpa de la pieza ni suya.
    // Es la única de las cuatro donde reintentar tiene sentido real.
    es: "El servicio está caído ahora mismo. No es tu pieza ni tu llave: no contesta.",
    en: "The service is down right now. It's not your piece or your key: it isn't answering.",
    accion: "reintentar",
  },
  credencial_no_declarada: {
    // DISTINTA de `needs_credential`: allá la ficha declara su llave y sólo falta pegarla.
    // Acá la pieza pide una que nunca mencionó, y eso es un defecto de la pieza, no del
    // usuario. Se ofrece igual la salida —pegarla— porque suele funcionar.
    es: "Pide una llave que su ficha no declara. Si tienes una, pégala y la probamos.",
    en: "It asks for a key its listing never declares. If you have one, paste it and we'll test it.",
    accion: "llave",
  },
  sin_herramientas: {
    // Arrancó, saludó, y su catálogo vino vacío. No hay nada que reintentar ni que pegar:
    // la pieza, hoy, no hace nada.
    es: "Arrancó bien, pero no ofrece ninguna herramienta. No hay nada que equipar todavía.",
    en: "It started fine, but offers no tools. There's nothing to equip yet.",
    accion: "nada",
  },

  curacion_rechazo: {
    // EL RESTO HONESTO, ya no el default. Las cuatro de arriba se llevaron los casos que
    // sabemos nombrar; lo que cae acá es un fracaso que todavía no supimos clasificar, y
    // el texto no puede fingir que sí. Antes decía «no respondió como su ficha dice que
    // responde» — una acusación a la ficha, sobre fichas que estaban bien.
    es: "La pieza no pasó la comprobación y no pudimos precisar por qué.",
    en: "The piece failed the check and we couldn't pin down why.",
    accion: "reintentar",
  },
  needs_credential: {
    es: "Pide tu llave para poder comprobarla.",
    en: "It needs your key before we can check it.",
    accion: "llave",
  },
  sin_red: {
    es: "No pudimos llegar hasta el final. Puede ser tu conexión.",
    en: "We couldn't get to the end. It might be your connection.",
    accion: "reintentar",
  },
  sin_sesion: {
    es: "Hay que entrar a tu cuenta para traer una pieza a tu local.",
    en: "You need to sign in to bring a piece into your local.",
    accion: "login",
  },
  estado_local_no_escribible: {
    es: "Tu equipo no dejó guardar esta conexión.",
    en: "Your machine wouldn't let this connection be saved.",
    accion: "reintentar",
  },
};

/** LA CAUSA, EN PALABRAS. Nunca muda, nunca en jerga.
 *
 * ⚠️ EL FALLBACK NO ES PEREZA: ES LA REGLA. Una causa nueva del backend no puede llegar a la
 * pantalla como `curacion_rechazo_v2`, y tampoco puede desaparecer. Se deriva una frase
 * honesta y se marca `provisional`, que es la señal de que a esta tabla le falta una
 * entrada — visible para el usuario como algo que pasó, visible para nosotros como deuda. */
export function causaDe(causa, literal) {
  const clave = literal && CAUSAS_CATALOGO[literal] ? literal : causa;
  const meta = clave && CAUSAS_CATALOGO[clave];
  if (meta) return { texto: L(meta.es, meta.en), accion: meta.accion, provisional: false };
  if (!causa) return null;
  return {
    texto: L("No se pudo completar el viaje de esta pieza.",
             "This piece's trip couldn't be completed."),
    accion: "reintentar", provisional: true,
  };
}
