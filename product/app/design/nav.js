/* nav.js — barra de navegación SUPERIOR de Aleph (estilo web).
 *
 * Script auto-inyectable (un <script src="./nav.js"></script> en el <head> de cada
 * pantalla). Antes era un botón flotante + drawer; ahora renderiza una BARRA fija arriba
 * con la marca + los destinos seleccionables + tema/idioma/＋crear/salir, como cualquier
 * sitio. Cuando no hay ancho suficiente, los links colapsan en un botón ▦ que abre el
 * panel lateral (se reusa el drawer).
 *
 * Los workspaces 100vh (Sala / Cuarto) tienen su propio chrome superior. Este launcher no
 * inyecta controles flotantes ahí, para evitar botones de salida aislados en las esquinas.
 *
 * Decoupled del runtime DC: React monta en #dc-root (reemplaza <x-dc>); la barra/drawer
 * viven como hermanos en document.body y sobreviven los re-render.
 *
 * Apagar en una pantalla: window.ALEPH_NAV_OFF = true antes de cargar este script
 * (Landing/Auth no lo incluyen — son pre-login).
 */
/* [sistema 2026-07-31] El comportamiento del sistema (Vertical Sliding Focus) se carga desde
 * acá: nav.js ya lo cargan todas las pantallas, así que es el único punto de enganche que no
 * obliga a editar 17 HTML. Se inyecta como <script> con la ruta relativa al propio nav.js
 * (las pantallas de subcarpeta —sala/, metodo/— resolverían mal una ruta fija). */
(function () {
  try {
    if (document.getElementById('aleph-ds-js')) return;
    var me = document.currentScript || (function () {
      var all = document.getElementsByTagName('script');
      for (var i = all.length - 1; i >= 0; i--) if ((all[i].src || '').indexOf('nav.js') >= 0) return all[i];
      return null;
    })();
    var base = me && me.src ? me.src.replace(/nav\.js.*$/, '') : './';
    var s = document.createElement('script');
    s.id = 'aleph-ds-js'; s.src = base + 'aleph-ds.js'; s.defer = true;
    (document.head || document.documentElement).appendChild(s);
  } catch (e) {}
})();

(function () {
  if (window.ALEPH_NAV_OFF) return;
  if (window.__alephNav) return;
  window.__alephNav = true;

  // ── i18n con fallback (si i18n.js no cargó, o la clave no existe, usa el texto ES) ──
  function L(key, fb) {
    try { var v = window.t ? window.t(key) : null; return (v && v !== key) ? v : fb; }
    catch (e) { return fb; }
  }

  // ── ubicación: la app vive en design/ ; la Sala en design/sala/ → ajustar rutas ──
  var inSala = /\/sala\//.test(location.pathname) || /\/sala-v2\//.test(location.pathname);

  // ── LA SALA ES UNA SOLA ──────────────────────────────────────────────────────────────
  // [Convergencia · superficie 7 · paso 5] El flag `aleph-sala=v1` MURIÓ. Era la puerta de
  // vuelta a la Sala vieja mientras la nueva se certificaba, y esa certificación ya pasó:
  // el agente anidado, el cinturón, el puente del Cuarto y el buscador de chats se
  // rescataron; el aviso de cerebro caído lo trajo `818cff19`.
  //
  // Y el flag era una ILUSIÓN de reversibilidad: gobernaba UNA puerta —esta— mientras
  // otras catorce del producto iban derecho a la vieja, hardcodeadas (medido en el censo).
  // Dejarlo habría sido conservar el gesto de la salida sin la salida.
  //
  // La reversión de verdad es `git revert`, que es honesta porque devuelve TODO el estado
  // —las catorce puertas incluidas— en vez de una preferencia que sólo movía el menú.
  var salaId = 'sala-v2/sala-v2.html';
  var inCuarto = /\/cuarto\//.test(location.pathname);
  var inMetodo = /\/metodo\//.test(location.pathname);   // pantalla Método: barra normal, pero vive en subdir
  // [convergencia · superficie 8] EL TERCER CASO DE «CROMO PROPIO», que este comentario ya
  // nombraba sin poder probarlo: los 6 workspaces nunca cargaban `nav.js`, así que la barra
  // compartida no aparecía ahí por AUSENCIA, no por decisión. Ahora la cargan —para leer los
  // destinos, ver `window.AlephDestinos` abajo— y hace falta decir explícitamente lo que
  // antes decía el silencio: acá manda `.ws-bar`, no esta barra.
  var inWorkspace = /\/workspaces\//.test(location.pathname);
  var inApp = inSala || inCuarto || inWorkspace;         // workspaces full-height → chrome propio, sin barra compartida
  try {
    document.documentElement.classList.add(inCuarto ? 'aleph-nav-cuarto' : (inSala ? 'aleph-nav-sala' : 'aleph-nav-topbar'));
  } catch (e) {}
  var up = (inApp || inMetodo) ? '../' : '';

  // [sistema 2026-07-31] `up` es una LISTA BLANCA de subcarpetas (sala/cuarto/metodo) y sirve
  // para los DESTINOS, que solo existen en esas. Pero los ASSETS los pide cualquier pantalla,
  // incluidas las que no están en la lista: inspeccion/ pedía `inspeccion/assets/aleph-mascot-v2.png`
  // y devolvía 404 (medido). La base de assets se deriva del src de este mismo script, así
  // funciona desde cualquier profundidad sin tener que enumerar carpetas.
  var assetBase = (function () {
    try {
      var s = document.currentScript;
      if (!s) {
        var all = document.getElementsByTagName('script');
        for (var i = all.length - 1; i >= 0; i--) {
          if ((all[i].src || '').indexOf('nav.js') >= 0) { s = all[i]; break; }
        }
      }
      if (s && s.src) return s.src.replace(/nav\.js.*$/, '');
    } catch (e) {}
    return up;   // último recurso: el comportamiento viejo
  })();
  // [UX·C] cruzar Cuarto↔Sala por el drawer YA NO pierde la composición: si la pantalla
  // actual tiene ?puppet=, los destinos que entienden composición lo llevan consigo.
  var _pup = (function () { try { return new URLSearchParams(location.search).get('puppet'); } catch (e) { return null; } })();
  // Las dos Salas entienden `?puppet=`: la nueva lo lee igual que la vieja (bridge.js:4-6).
  var _CARRY = { 'Cuarto.dc.html': 1, 'sala/sala.html': 1, 'sala-v2/sala-v2.html': 1 };
  function href(id) {                                   // id = ruta relativa a design/
    if (_pup && _CARRY[id]) return assetBase + id + '?puppet=' + encodeURIComponent(_pup);
    return assetBase + id;
  }
  var seg = (location.pathname.split('/').pop() || '').toLowerCase();
  var curId = inSala ? salaId
            : inCuarto ? 'Cuarto.dc.html'
            : inMetodo ? 'metodo/metodo.html'
            : (!seg || seg === 'index.html') ? 'Home.dc.html'
            : (location.pathname.split('/').pop());

  // ── iconos inline del set propio (SELF-CONTAINED). nav.js corre en MUCHAS pantallas, la mayoría
  //    fuera de la ola de iconografía → NO puede depender de que window.AlephIcons esté presente.
  //    Mismo lenguaje que el resto del set: Lucide vendored, mono, stroke, currentColor. ────────────
  /* ── LOS ÍCONOS DEL RIEL, TAL CUAL EL DISEÑO ──────────────────────────────────────
   * Acá el riel dibujaba glifos de texto (⌂ ◈ ◷ ▤ ◇ ⌕). El artboard tiene íconos de línea
   * propios, bitono: un trazo y una pieza rellena que le da peso. Se copian sus paths tal
   * cual, con dos cambios y sólo dos: el trazo pasa a `currentColor` —así el ítem activo se
   * pone índigo solo, por el color del `<a>`— y el relleno pasa a `currentColor` al 42%,
   * que reproduce el bitono sin clavar el `#c7b6f9` del tema claro. Mismo dibujo, dos temas. */
  var _ICP = {
    'd-inicio': '<path d="M4.2 10.6 12 4.2l7.8 6.4V19.4H4.2z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"></path><path d="M9.4 19.4v-5.2h5.2v5.2z" fill="currentColor" fill-opacity=".42"></path>',
    'd-agentes': '<path d="M12 3.2 20.8 12 12 20.8 3.2 12z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"></path><circle cx="12" cy="12" r="2.6" fill="currentColor" fill-opacity=".42"></circle>',
    'd-modelos': '<path d="M12 3 19.2 7.2v9.6L12 21l-7.2-4.2V7.2z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"></path><path d="M12 12 19.2 7.8v9L12 21z" fill="currentColor" fill-opacity=".42"></path>',
    'd-conect': '<path d="M11.4 12.6 7 17a2.5 2.5 0 0 0 3.6 3.5l4.8-4.8" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"></path><path d="M12.6 11.4 17 7a2.5 2.5 0 0 1 3.5 3.6l-4.8 4.8" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"></path><circle cx="14" cy="14" r="2.2" fill="currentColor" fill-opacity=".42"></circle>',
    'd-histor': '<circle cx="12" cy="12" r="8.4" stroke="currentColor" stroke-width="1.4"></circle><path d="M12 6.8V12l3.6 2.2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"></path><circle cx="12" cy="12" r="1.7" fill="currentColor" fill-opacity=".42"></circle>',
    'd-biblio': '<path d="M4.4 5.2h6.2A1.6 1.6 0 0 1 12 6.8v12a1.7 1.7 0 0 0-1.6-1.3H4.4z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"></path><path d="M19.6 5.2h-6.2A1.6 1.6 0 0 0 12 6.8v12a1.7 1.7 0 0 1 1.6-1.3h6z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"></path><path d="M15 5.2h3.2v4.6L16.6 8.6 15 9.8z" fill="currentColor" fill-opacity=".42"></path>',
    'd-metodos': '<path d="M12 2.8 17 12l-5 9.2L7 12z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"></path><path d="M12 8.4 14.6 12 12 15.6 9.4 12z" fill="currentColor" fill-opacity=".42"></path>',
    'd-inspect': '<circle cx="10.6" cy="10.6" r="6.4" stroke="currentColor" stroke-width="1.4"></circle><path d="M15.4 15.4 20 20" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"></path><circle cx="10.6" cy="10.6" r="2.4" fill="currentColor" fill-opacity=".42"></circle>',
    'd-ajustes': '<path d="M12 3.2 13.9 5l2.5-.5 1 2.4 2.2 1.3-.5 2.5.5 2.5-2.2 1.3-1 2.4-2.5-.5L12 20.8 10.1 19l-2.5.5-1-2.4L4.4 15.8l.5-2.5-.5-2.5 2.2-1.3 1-2.4L10.1 5z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"></path><circle cx="12" cy="12" r="2.6" fill="currentColor" fill-opacity=".42"></circle>',
    'd-ayuda': '<circle cx="12" cy="12" r="8.4" stroke="currentColor" stroke-width="1.4"></circle><path d="M9.6 9.4a2.5 2.5 0 0 1 4.9.7c0 1.7-2.5 1.9-2.5 3.6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"></path><circle cx="12" cy="17" r="1.5" fill="currentColor" fill-opacity=".42"></circle>',
    'settings':  '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
    'globe':     '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
    'key-round': '<path d="M2.586 17.414A2 2 0 0 0 2 18.828V21a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h1a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h.172a2 2 0 0 0 1.414-.586l.814-.814a6.5 6.5 0 1 0-4-4z"/><circle cx="16.5" cy="7.5" r=".5" fill="currentColor"/>',
    'sun':       '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
    'moon':      '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    // [FIX-P8] Modelos = lo que PIENSA. Un chip, no un órgano: la metáfora anatómica del
    // nombre viejo es la que hacía sonar a esto como una cosa sola, fija y mágica —
    // cuando son varios, elegibles, y cada uno sirve para cosas distintas.
    'cpu':       '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v2"/><path d="M15 2v2"/><path d="M9 20v2"/><path d="M15 20v2"/><path d="M2 9h2"/><path d="M2 15h2"/><path d="M20 9h2"/><path d="M20 15h2"/>'
  };
  function svgi(name, size) {
    size = size || 15;
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ' +
      'style="display:inline-block;vertical-align:-.14em">' + (_ICP[name] || '') + '</svg>';
  }

  // ── destinos (id = ruta relativa a design/) ──
  //
  // [convergencia · superficie 8] CADA ENTRADA LLEVA `key`/`fb` EN VEZ DE UN `label` YA
  // RESUELTO, y el cambio es porque esta tabla dejó de tener un solo lector. `L()` se
  // evalúa cuando `nav.js` se parsea, o sea ANTES de que `i18n.js` esté listo en varias
  // pantallas: un consumidor que llegue después se quedaba con el castellano de respaldo
  // para siempre. Con la clave adentro, cada uno traduce a SU tiempo. `etiqueta()` de abajo
  // hace exactamente lo que hacía el `label`, para quien no necesite más.
  var ITEMS = [
    { id: 'Home.dc.html',      icon: svgi('d-inicio', 19),  key: 'nav.inicio',     fb: 'Inicio' },
    // [rediseño · fase 2 · 2.1] AGENTES, que antes era un widget adentro de Home. Va segundo
    // porque es el segundo del riel del diseño, y el orden de esta tabla ES el del riel.
    { id: 'Agentes.dc.html',   icon: svgi('d-agentes', 19), key: 'nav.agentes',    fb: 'Agentes' },
    // El Cuarto SIGUE en la tabla aunque no esté en el riel: `window.AlephDestinos` la
    // publica y el hub de Home lista desde ahí (`Home.dc.html:311`). Sacarlo de acá lo
    // sacaría también del hub. Del riel lo saca `RIELLINKS`, abajo, como ya hacía la barra.
    { id: 'Cuarto.dc.html',    icon: '＋', key: 'nav.armar',      fb: 'Arma un agente' },
    // La Sala dejó de ser un destino global: es un espacio de trabajo par y se entra
    // desde el desplegable «Espacios de trabajo» de Inicio, junto a Oficina y los demás.
    // [FIX-P8] MODELOS = lo que PIENSA · CONEXIONES/CATÁLOGO = lo que HACE. La entrada
    // propia es la mitad estructural de esa separación: mientras los modelos vivían dentro
    // de otra pantalla, cualquier cosa podía colarse al lado de ellos (y se coló).
    { id: 'Modelos.dc.html',   icon: svgi('d-modelos', 19), key: 'nav.modelos', fb: 'Modelos' },
    // [cierre de la separación de P8] «Conexiones» MURIÓ del nav. Era la mitad que sobraba:
    // sus tres familias de cognición (incluido · cli · api) son EXACTAMENTE las que Modelos
    // ya lista, y sus capacidades (＋ Agregar llave · Probar todas · Probar las seleccionadas)
    // se mudaron ahí. Lo que no es cognición —cuentas y servidores MCP— es un CONECTOR, y vive
    // en Conectores. Conexiones.dc.html redirige; nadie queda con un link muerto.
    { id: 'Conectores.dc.html', icon: svgi('d-conect', 19), key: 'nav.conectores', fb: 'Conectores' },
    { id: 'Historial.dc.html', icon: svgi('d-histor', 19),  key: 'nav.historial',  fb: 'Historial' },
    { id: 'Biblioteca.dc.html',icon: svgi('d-biblio', 19),  key: 'nav.biblioteca', fb: 'Biblioteca' },
    { id: 'metodo/metodo.html',icon: svgi('d-metodos', 19), key: 'nav.metodo',     fb: 'Métodos' },
    // [C · Cuarto limpio · item 7] entrada ADITIVA: inspeccionar/armar un MCP dejó de ser un modal
    // encima del diorama y tiene su pantalla, igual que Métodos. Desde el Cuarto sólo se equipa.
    { id: 'inspeccion/inspeccion.html', icon: svgi('d-inspect', 19), key: 'nav.inspeccion', fb: 'Inspección' },
    // [Casa 2 · Fase 0] 'Estados.dc.html' SALIÓ de acá. No es una pantalla de producto:
    // es el catálogo de ESPECIFICACIÓN de diseño ("Los momentos en que el producto se
    // juzga"), con ejemplos y datos ficticios. Estaba enlazada desde el nav principal, o
    // sea que cualquier usuario llegaba a documentación interna con un clic. El archivo
    // sigue en el árbol de dev — lo que cambia es que deja de ser un destino del producto.
    { id: 'Settings.dc.html',  icon: svgi('d-ajustes', 19), key: 'nav.ajustes', fb: 'Ajustes' },
    { id: 'Ayuda.dc.html',     icon: svgi('d-ayuda', 19),   key: 'nav.ayuda',      fb: 'Ayuda' },
  ];
  /** El nombre del destino, traducido AHORA (no cuando se parseó este archivo). */
  function etiqueta(it) { return L(it.key, it.fb); }

  /* EL RÓTULO DEL RIEL ES LA PALABRA ENTERA, y la abreviatura MURIÓ.
   *
   * Acá vivía una tabla `CORTO` que escribía CONECT · HISTOR · BIBLIO · INSPECT, con este
   * argumento: «en 60 px de ancho Conectores y Biblioteca se cortan con puntos suspensivos».
   * Era cierto CUANDO SE ESCRIBIÓ y dejó de serlo, porque el riel creció y nadie volvió a
   * medir. Medido hoy contra la geometría que fija el diseño —riel de 78 px, rótulo en
   * JetBrains Mono 8 px con letter-spacing .04em— la palabra más larga de los dos idiomas
   * («CONEXIONES» en castellano, «CONNECTORS» en inglés) mide 51,2 px. Entra con 26 px de
   * sobra. Lo que las cortaba no era el ancho del riel: era este archivo pidiendo 8,5 px con
   * letter-spacing .1em contra un `max-width:58px` —59,5 px de texto en 58 px de caja— y
   * además la tabla, que las cortaba ANTES de que el CSS tuviera ocasión.
   *
   * El diseño escribe las cortas en su mock porque su baldosa mide 46 px; acá la baldosa es
   * de 64 y el riel el mismo de 78, así que la palabra entra ENTERA y no hay nada que
   * abreviar. La regla de la casa —«nunca un rótulo cortado»— y la geometría del diseño
   * coinciden; sólo había que medirlas juntas. */
  ITEMS.forEach(function (it) {
    // `label` se conserva como propiedad LEÍDA, no almacenada: el resto de este archivo lo
    // usa en cinco lugares y no hay razón para tocarlos, pero tiene que traducirse tarde.
    Object.defineProperty(it, 'label', { get: function () { return etiqueta(it); } });
  });

  // ── LA TABLA DE DESTINOS, PUBLICADA ──────────────────────────────────────────────────
  // [convergencia · superficie 8] Había DOS copias de «los destinos del producto» y la
  // segunda había DERIVADO, con una consecuencia que el usuario ve: el hub de `Home.dc.html`
  // seguía enlazando `Estados.dc.html`, que es el catálogo de ESPECIFICACIÓN de diseño y que
  // esta tabla sacó a propósito («cualquier usuario llegaba a documentación interna con un
  // clic», ver el comentario más abajo). El arreglo se hizo acá y la copia no se enteró.
  // Además al hub le faltaban cuatro destinos que la barra sí tiene: Modelos, Conectores,
  // Métodos e Inspección.
  //
  // Se publica en `window` y no se exporta como módulo a propósito: `nav.js` es un script
  // clásico que corre al parsearse, así que la tabla está lista antes del `DOMContentLoaded`
  // de cualquier consumidor — sin cambiarle el momento de construcción a la barra, que vive
  // en 17 pantallas. Mismo trato que `espacios-tabla.js`: una copia, varios lectores.
  try { window.AlephDestinos = { items: ITEMS, etiqueta: etiqueta, href: href }; } catch (e) {}

  /* ── EL RIEL SE PARTE EN DOS, Y ESO ES EL DISEÑO ──────────────────────────────────────
   * Arriba los ocho destinos del trabajo; abajo Ajustes, Ayuda y la cuenta. La barra vieja
   * ponía todo en una fila y le sumaba un CTA «＋ Crear Aleph»: ese CTA MUERE porque el
   * destino de crear ahora vive adentro de Agentes («＋ Crear agente»), que es donde el
   * diseño lo puso. El Cuarto no queda inalcanzable — se llega desde Agentes y desde el hub. */
  var PIE = { 'Settings.dc.html': 1, 'Ayuda.dc.html': 1 };
  var RIELLINKS = ITEMS.filter(function (it) { return it.id !== 'Cuarto.dc.html' && !PIE[it.id]; });
  var PIELINKS  = ITEMS.filter(function (it) { return PIE[it.id]; });

  /* [rediseño · fase 1 · una sola mascota] ACÁ VIVÍA UN ÁTOMO SVG INLINE, Y ESTABA MUERTO.
   * `var ATOM = '<svg …>'` — declarado, 8 líneas, y usado CERO veces: la mascota de la barra
   * es `assets/aleph-mascot-v2.png` desde julio (línea 423) y nadie borró el vector que
   * reemplazó. Medido con grep antes de tocarlo: 1 aparición en todo el archivo, la
   * declaración. Se borra: un glifo de marca que nadie dibuja igual puede volver a
   * dibujarse por accidente, y el estándar pide UN solo Aleph. */

  /* ── ESTILOS · EL RIEL ────────────────────────────────────────────────────────────────
   * [rediseño · fase 2 · 2.1] Acá vivía la barra superior flotante: tres cápsulas de cristal
   * con marca, destinos y utilidades. El estándar del rediseño la prohíbe con todas las
   * letras —«Nada de una segunda barra superior dentro de la app»— y pone la navegación en
   * un RIEL vertical angosto, con el glifo arriba y su rótulo monoespaciado abajo.
   * Se reescriben los estilos, no el archivo: `nav.js` lo cargan 24 pantallas, publica
   * `window.AlephDestinos` (que leen el hub de Home y los seis workspaces) e INYECTA
   * `aleph-ds.js` en todas. Borrarlo para escribir un `riel.js` habría sido mudar tres
   * cables por una razón de nombre. */
  var CSS = [
    '#aleph-riel{position:fixed;top:0;left:0;bottom:0;z-index:40;width:78px;display:flex;flex-direction:column;',
      'align-items:center;background:var(--paper2,#141412);box-sizing:border-box;padding:14px 0 12px}',
    '#aleph-riel::after{content:"";position:absolute;top:0;right:0;bottom:0;width:1px;background:var(--hairline,transparent)}',
    '.aleph-riel-mark{display:flex;align-items:center;justify-content:center;width:34px;height:34px;margin-bottom:14px;flex:none}',
    '.aleph-riel-mark img{width:22px;height:22px;display:block}',
    '.aleph-riel-body{display:flex;flex-direction:column;align-items:center;gap:2px;width:100%;overflow-y:auto;overflow-x:hidden;flex:1 1 auto;min-height:0;scrollbar-width:none}',
    '.aleph-riel-body::-webkit-scrollbar{display:none}',
    '.aleph-riel-foot{display:flex;flex-direction:column;align-items:center;gap:2px;width:100%;flex:none;padding-top:10px}',
    '.aleph-riel-link{display:flex;flex-direction:column;align-items:center;gap:3px;width:64px;padding:8px 0 7px;',
      'border-radius:var(--r-sm,13px);text-decoration:none;color:var(--faint,#838379);flex:none;',
      'transition:color .14s,background .14s}',
    '.aleph-riel-link .gl{display:flex;align-items:center;justify-content:center;height:19px;font-size:15px;line-height:1}',
    /* El rótulo es monoespaciado y en versalitas: es el vocabulario que el estándar le da a
     * las etiquetas de grupo, el mismo de RECENT SESSIONS. */
    /* 8 px y .04em son los del diseño, y son los que hacen entrar la palabra entera: con
     * 8,5 px y .1em —lo de antes— «CONEXIONES» pedía 59,5 px contra un tope de 58 y salía
     * cortada. El `max-width` queda de red, no de tijera: el rótulo más largo mide 51,2 px. */
    '.aleph-riel-link .lb{font:500 8px/1 var(--font-mono,ui-monospace,monospace);letter-spacing:.04em;text-transform:uppercase;',
      'max-width:62px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:center}',
    '.aleph-riel-link:hover{color:var(--ink,#e6e6e3);background:var(--paper,#1a1917)}',
    '.aleph-riel-link.cur{color:var(--accent,#9494e4);background:var(--accent-soft,#1b1839)}',
    '.aleph-riel-cuenta{width:26px;height:26px;border-radius:50%;background:var(--paper,#1a1917);border:0;cursor:pointer;margin-top:8px;flex:none;padding:0}',
    '#aleph-riel-brain{width:100%;display:flex;justify-content:center;padding:6px 0 2px}',
    /* Angosto: el riel se esconde y vuelve el disparador del panel lateral, que ya existía. */
    '@media (max-width:720px){#aleph-riel{display:none}}',
    '#aleph-nav-btn{position:fixed;left:14px;bottom:14px;z-index:41;width:40px;height:40px;border-radius:var(--r-sm,13px);',
      'border:0;background:var(--paper2,#141412);color:var(--ink,#e6e6e3);font-size:15px;cursor:pointer;display:none}',
    '@media (max-width:720px){#aleph-nav-btn{display:block}}',
    '#aleph-nav-scrim{position:fixed;inset:0;z-index:44;background:rgba(0,0,0,.5);opacity:0;pointer-events:none;transition:opacity .18s}',
    '#aleph-nav-scrim.on{opacity:1;pointer-events:auto}',
    '#aleph-nav-panel{position:fixed;top:0;left:0;bottom:0;z-index:45;width:264px;background:var(--paper,#1a1917);',
      'display:flex;flex-direction:column;transform:translateX(-100%);transition:transform .2s ease}',
    '#aleph-nav-panel.on{transform:none}',
    '.aleph-nav-link{display:flex;align-items:center;gap:11px;padding:11px 18px;text-decoration:none;color:var(--muted,#97978f);font:400 14px var(--font-ui,system-ui,sans-serif)}',
    '.aleph-nav-link:hover{color:var(--ink,#e6e6e3);background:var(--paper2,#141412)}',
    '.aleph-nav-link.cur{color:var(--accent,#9494e4);background:var(--accent-soft,#1b1839)}',
    '#aleph-nav-foot{display:flex;gap:8px;padding:14px 12px;border:0}',
    '.aleph-nav-fbtn{flex:1;display:flex;align-items:center;justify-content:center;gap:6px;padding:10px 0;',
      'border-radius:var(--r-sm,13px);cursor:pointer;border:0;background:var(--paper2,#141412);',
      'color:var(--muted,#97978f);font:400 12px/1 var(--font-ui,system-ui,sans-serif);transition:color .14s}',
    '.aleph-nav-fbtn:hover{color:var(--ink,#e6e6e3)}',
    '@media (prefers-reduced-motion: reduce){#aleph-riel,#aleph-nav-btn,#aleph-nav-scrim,#aleph-nav-panel,.aleph-nav-link,.aleph-nav-fbtn,.aleph-riel-link{transition:none}}',
  ].join('');

  function el(tag, attrs, html) {
    var n = document.createElement(tag);
    if (attrs) for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (html != null) n.innerHTML = html;
    return n;
  }

  function ensureBrain(cb) {
    if (window.AlephBrain) return cb && cb();
    if (window.__alephBrainLoading) {
      document.addEventListener('aleph:brain-script-ready', function once() {
        document.removeEventListener('aleph:brain-script-ready', once);
        cb && cb();
      });
      return;
    }
    window.__alephBrainLoading = true;
    var s = document.createElement('script');
    s.src = assetBase + 'brain-status.js';   // [2026-07-31] mismo 404 que la mascota: `up` no cubre inspeccion/
    s.onload = function () {
      try { document.dispatchEvent(new CustomEvent('aleph:brain-script-ready')); } catch (e) {}
      cb && cb();
    };
    s.onerror = function () {};
    document.head.appendChild(s);
  }
  function mountBrain(host, opts) {
    if (!host) return;
    ensureBrain(function () {
      if (window.AlephBrain) window.AlephBrain.mount(host, opts || {});
    });
  }

  /* [rediseño · fase 2 · 2.1] ACÁ VIVÍAN `toggleTheme` y `toggleLang`, y se fueron con sus
   * botones. Dejarlas habría sido dejar dos funciones sin llamante — exactamente el defecto
   * que esta casa persigue en todo lo demás. El tema y el idioma se cambian en
   * Settings → Preferencias, que ya los tenía cableados antes de que estos botones murieran.
   *
   * ⚠️ Y ME CORREGÍ ACÁ MISMO: escribí que `curTheme` y `curLang` se quedaban «porque las
   * usa mountBrain», y era FALSO — un grep de sus llamantes dio CERO en cuanto los botones
   * se fueron. Se borraron también. Escribir el motivo sin medirlo es cómo nace el código
   * muerto que después nadie se anima a tocar. */
  function logout() {
    var done = null;
    try {
      if (window.AlephSession && window.AlephSession.clear) done = window.AlephSession.clear();
      else {
        sessionStorage.removeItem('puppet_user');
        try { localStorage.removeItem('puppet_user'); } catch (_) {}
      }
    } catch (e) {}
    if (done && typeof done.finally === 'function') done.finally(function () {
      location.href = href('Auth.dc.html');
    });
    else location.href = href('Auth.dc.html');
  }

  var panel, scrim, open = false;
  function setOpen(v) {
    open = v;
    if (panel) panel.classList.toggle('on', v);
    if (scrim) scrim.classList.toggle('on', v);
    if (panel) panel.setAttribute('aria-hidden', v ? 'false' : 'true');
  }

  // ── panel lateral (drawer): todos los destinos + tema/idioma/salir ──
  function buildDrawer() {
    scrim = el('div', { id: 'aleph-nav-scrim' });
    scrim.onclick = function () { setOpen(false); };
    document.body.appendChild(scrim);

    panel = el('div', { id: 'aleph-nav-panel', role: 'navigation', 'aria-hidden': 'true' });
    panel.appendChild(el('div', { id: 'aleph-nav-head' },
      '<div class="ttl">Aleph</div><div class="sub">' + L('nav.adonde', '¿A dónde vas?') + '</div>'));
    var drawerBrain = null;
    if (!window.ALEPH_NAV_BRAIN_OFF) {
      drawerBrain = el('div', { id: 'aleph-nav-brain-drawer', style: 'padding:10px 12px 0' });
      panel.appendChild(drawerBrain);
    }

    var list = el('div', { id: 'aleph-nav-list' });
    ITEMS.forEach(function (it) {
      var cur = it.id === curId;
      var a = el('a', { 'class': 'aleph-nav-link' + (cur ? ' cur' : ''), href: href(it.id) },
        '<span class="gl">' + it.icon + '</span><span>' + it.label + '</span>');
      if (cur) a.setAttribute('aria-current', 'page');
      list.appendChild(a);
    });
    panel.appendChild(list);

    /* [rediseño · fase 2 · 2.1] El pie del panel tenía TEMA e IDIOMA. Se van a Appearance,
     * igual que los del riel: dejarlos acá sería conservar dos de las tres copias del mismo
     * control. Queda Ajustes —que es donde viven ahora— y cerrar sesión. */
    var foot = el('div', { id: 'aleph-nav-foot' });
    var bSet = el('button', { 'class': 'aleph-nav-fbtn', title: L('nav.ajustes', 'Ajustes') },
      svgi('settings', 14) + ' ' + L('nav.ajustes', 'Ajustes'));
    bSet.onclick = function () { location.href = href('Settings.dc.html'); };
    var bOut = el('button', { 'class': 'aleph-nav-fbtn danger', title: L('common.cerrar_sesion', 'Cerrar sesión') }, '⎋');
    bOut.onclick = logout;
    foot.appendChild(bSet); foot.appendChild(bOut);
    panel.appendChild(foot);
    document.body.appendChild(panel);
    if (drawerBrain) mountBrain(drawerBrain, { compact: true });
  }

  // ── EL RIEL (todas las pantallas menos la Sala, el Cuarto y los workspaces) ──────────
  function buildRiel() {
    var riel = el('nav', { id: 'aleph-riel', role: 'navigation', 'aria-label': L('nav.adonde', '¿A dónde vas?') });

    // La mascota, y sólo la mascota: el estándar dice UN Aleph, y acá arriba no va el
    // wordmark porque el riel no tiene ancho para una palabra.
    riel.appendChild(el('a', { 'class': 'aleph-riel-mark', href: href('Home.dc.html'), 'aria-label': L('nav.inicio_label', 'Aleph · Inicio') },
      '<img src="' + assetBase + 'assets/aleph-mascot-v2.png" alt="" width="22" height="22">'));

    function link(it) {
      var cur = it.id === curId;
      var a = el('a', { 'class': 'aleph-riel-link' + (cur ? ' cur' : ''), href: href(it.id), title: it.label },
        '<span class="gl">' + it.icon + '</span><span class="lb">' + etiqueta(it) + '</span>');
      if (cur) a.setAttribute('aria-current', 'page');
      return a;
    }

    var body = el('div', { 'class': 'aleph-riel-body' });
    RIELLINKS.forEach(function (it) { body.appendChild(link(it)); });
    riel.appendChild(body);

    var pie = el('div', { 'class': 'aleph-riel-foot' });
    var brainHost = el('div', { id: 'aleph-riel-brain' });
    pie.appendChild(brainHost);
    PIELINKS.forEach(function (it) { pie.appendChild(link(it)); });

    /* LA CUENTA, Y ACÁ MUEREN LAS DOS PASTILLAS. La barra tenía un botón de TEMA y uno de
     * IDIOMA, y eran los únicos de 24 pantallas. El estándar los manda a Appearance, y eso
     * NO es una promesa: `Settings.dc.html` ya tiene los tres controles —Idioma, Tema y
     * Tamaño del texto— con sus `pick` cableados, y el ⚙ que lleva ahí lo pone `ajustes.js`
     * en 26 pantallas (se engancha desde `theme.js`, que llega a más que `nav.js`).
     * Medido antes de borrar nada; si no hubieran estado, esto habría dejado al producto sin
     * forma de cambiar el tema. También muere el CTA «＋ Crear Aleph»: crear vive adentro de
     * Agentes. */
    var cuenta = el('button', { 'class': 'aleph-riel-cuenta', title: L('common.cerrar_sesion', 'Cerrar sesión'),
                                'aria-label': L('common.cerrar_sesion', 'Cerrar sesión') });
    cuenta.onclick = logout;
    pie.appendChild(cuenta);
    riel.appendChild(pie);

    // El disparador del panel lateral, para cuando el riel no entra.
    var burger = el('button', { id: 'aleph-nav-btn', title: L('nav.ir_a', 'Ir a…'), 'aria-label': L('nav.ir_a', 'Ir a…') }, '▦');
    burger.onclick = function () { setOpen(!open); };
    document.body.appendChild(burger);

    // append (NO insertBefore): el runtime DC de algunas pantallas reemplaza el primer hijo
    // del body asumiendo que es <x-dc>; appendear sobrevive el re-render.
    document.body.appendChild(riel);
    /* EL CONTENIDO SE CORRE A LA DERECHA, no hacia abajo. La barra empujaba con
     * `paddingTop:66px`; el riel empuja con `paddingLeft`. Si esto no acompaña, el título de
     * cada pantalla queda debajo del riel. En angosto el riel se esconde y el padding se va
     * con él — por eso la media query también está acá y no sólo en el CSS. */
    try {
      var pad = el('style', null,
        'body{padding-left:78px}@media (max-width:720px){body{padding-left:0}}');
      document.head.appendChild(pad);
    } catch (e) {}
    // el tema ya no se cambia desde acá → el flotante de theme.js tampoco tiene por qué
    // estar: su lugar es Appearance. (`ALEPH_THEME_NOFLOAT` ya lo apaga en la mayoría.)
    document.head.appendChild(el('style', null, '#aleph-tg{display:none!important}'));
    mountBrain(brainHost, { compact: true });
  }

  function build() {
    if (document.getElementById('aleph-riel') || document.getElementById('aleph-nav-btn')) return;

    var style = el('style'); style.textContent = CSS; document.head.appendChild(style);
    if (inApp) {
      // Sala/Cuarto own the top chrome; preserve the compact brain without a detached nav launcher.
      if (!window.ALEPH_NAV_BRAIN_OFF) {
        var fh = el('div', { id: 'aleph-floating-brain' });
        document.body.appendChild(fh);
        mountBrain(fh, { compact: true });
      }
      return;
    }
    buildDrawer();
    buildRiel();
  }

  // cerrar con Escape
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && open) setOpen(false); });

  if (document.body) build();
  else document.addEventListener('DOMContentLoaded', build);
})();
