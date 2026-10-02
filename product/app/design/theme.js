/* theme.js — tema unificado de Aleph (system · light · dark). Default 'dark'.
 * 'system' sigue prefers-color-scheme EN VIVO. Aplica data-theme (resuelto a light/dark)
 * sobre <html>, y data-theme-mode (la elección cruda) para que un control pueda mostrar
 * "Sistema" como activo. API: window.AlephTheme.{get,set,resolved}.
 * Toggle flotante salvo window.ALEPH_THEME_NOFLOAT (Home/Settings traen el suyo propio).
 *
 * Una sola fuente de verdad del tema en todo el producto. Las pantallas declaran su CSS
 * de tema con `html[data-theme="light"]{…}` (override sobre el :root oscuro).
 */
(function () {
  var KEY = 'aleph-theme';
  function modeOf(v) {
    // `auto` queda como alias de migración para instalaciones anteriores; la preferencia
    // canónica que se persiste desde ahora es `system`.
    if (v === 'auto') return 'system';
    return (v === 'light' || v === 'dark' || v === 'system') ? v : 'dark';
  }
  function raw() {
    try { return modeOf(localStorage.getItem(KEY)); }
    catch (e) { return 'dark'; }
  }
  var mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  function resolved() { var m = raw(); return m === 'system' ? ((mq && mq.matches) ? 'dark' : 'light') : m; }
  function applyDom() {
    try { var h = document.documentElement; h.setAttribute('data-theme', resolved()); h.setAttribute('data-theme-mode', raw()); }
    catch (e) {}
  }
  applyDom(); // síncrono, antes del primer paint → sin flash

  var channel = null;
  try { channel = window.BroadcastChannel ? new BroadcastChannel('aleph-theme-v1') : null; } catch (e) { channel = null; }
  function announce() {
    var detail = { mode: raw(), theme: resolved() };
    try { window.dispatchEvent(new CustomEvent('aleph:theme-changed', { detail: detail })); } catch (e) {}
  }

  // en modo 'auto', sigue los cambios del sistema en vivo
  if (mq) {
    var onMq = function () { if (raw() === 'system') { applyDom(); refreshIcon(); announce(); } };
    try { mq.addEventListener('change', onMq); } catch (e) { try { mq.addListener(onMq); } catch (_) {} }
  }

  function icon() { return resolved() === 'light' ? '☾' : '☀'; } // ☾ en light (click→dark) · ☀ en dark
  var btn = null;
  function refreshIcon() { if (btn) btn.textContent = icon(); }

  function set(m) {
    m = modeOf(m);
    try { localStorage.setItem(KEY, m); } catch (e) {}     // caché de arranque, no la fuente
    applyDom(); refreshIcon(); announce();
    try { if (channel) channel.postMessage({ mode: m }); } catch (e) {}
    guardar('tema', m);
  }

  window.addEventListener('storage', function (e) {
    if (e.key !== KEY || e.newValue == null) return;
    applyDom(); refreshIcon(); announce();
  });
  if (channel) channel.onmessage = function (e) {
    if (!e || !e.data || !e.data.mode) return;
    applyDom(); refreshIcon(); announce();
  };

  function mkToggle() {
    // [convergencia · s3 · fase 3] EL FLOTANTE DE TEMA CEDE LA ESQUINA AL ⚙.
    // El plan pide UN solo disparador en el mismo píxel; dos botones flotantes en la misma
    // esquina son dos. El tema no se pierde: es el primer control del overlay, a un click.
    // La función se deja entera —no se borra— porque `ALEPH_AJUSTES_OFF` la devuelve tal
    // cual estaba, y porque el día que el ⚙ no cargue esta pantalla no queda sin tema.
    if (!window.ALEPH_AJUSTES_OFF) return;
    if (window.ALEPH_THEME_NOFLOAT) return;
    if (document.getElementById('aleph-tg')) return;
    btn = document.createElement('button');
    btn.id = 'aleph-tg'; btn.textContent = icon();
    btn.setAttribute('aria-label', 'Tema'); btn.setAttribute('title', 'Tema');
    // [barrido 2026-07-31] Era el ÚLTIMO borde compartido del producto: aparecía en todas las
    // pantallas que no traen su propio toggle. Pasa al cristal del sistema — sin borde, con
    // sombra en vez de línea, y los dos hex sueltos (rgba(150,150,190,…)) fuera.
    btn.setAttribute('style', 'position:fixed;bottom:18px;right:18px;z-index:99999;width:40px;height:40px;border-radius:var(--r-sm,13px);border:0;background:var(--glass,rgba(20,20,22,.78));-webkit-backdrop-filter:blur(16px);backdrop-filter:blur(16px);box-shadow:var(--sh-1,0 4px 14px rgba(0,0,0,.4));color:var(--ink,#F5F5F6);font-size:16px;cursor:pointer');
    btn.onclick = function () { set(resolved() === 'light' ? 'dark' : 'light'); }; // el flotante alterna light/dark; "Auto" se elige en Settings
    document.body.appendChild(btn);
  }
  if (document.body) mkToggle();
  else document.addEventListener('DOMContentLoaded', mkToggle);

  // ── EL AJUSTE SIGUE A LA CUENTA, NO AL NAVEGADOR ─────────────────────────────────
  // [Convergencia · superficie 3 · fase 1b]
  //
  // QUÉ CAMBIA Y QUÉ NO. `localStorage` deja de ser la FUENTE y pasa a ser la CACHÉ DE
  // ARRANQUE. Lo que NO cambia es el `applyDom()` de arriba: sigue siendo síncrono y
  // sigue leyendo de `localStorage` antes del primer paint, así que el «sin flash» se
  // conserva entero. El servidor llega después y corrige si hace falta.
  //
  // POR QUÉ ACÁ Y NO EN UN ARCHIVO NUEVO: un `preferencias.js` habría que declararlo en
  // 26 pantallas. `i18n.js` no sirve de casa porque CARGA ANTES que este archivo (medido:
  // `Home.dc.html:12` vs `:14`), así que no puede depender de nada de acá. Este archivo
  // ya se declara «una sola fuente de verdad del tema en todo el producto»; hacerlo el
  // que habla con el servidor mantiene esa frase cierta en vez de abrir un segundo dueño.
  //
  // ATIENDE LOS DOS EJES —tema e idioma— porque son la misma llamada y partirla en dos
  // sería pedir dos veces lo mismo en cada arranque.
  //
  // HUECOS CONOCIDOS, medidos y escritos para que nadie los descubra tarde:
  //   · 9 pantallas cargan este archivo y NO `i18n.js`: ahí el idioma no se sincroniza
  //     (tampoco hay quién lo muestre).
  //   · `render/render.demo.html` carga `i18n.js` y NO éste: es la única pantalla con
  //     idioma y sin sincronización. Es un demo.
  //   · Sin sesión, el GET da 401 y no pasa nada: la caché local sigue gobernando. Un
  //     ajuste que no se pudo traer NO se pisa con el default —eso borraría la elección
  //     de alguien por estar deslogueado.
  var adoptando = false;

  function guardar(clave, valor) {
    if (adoptando) return Promise.resolve({ ok: true, skipped: true }); // adoptar no es elegir
    try {
      return new Promise(function (resolve) {
        var terminado = false;
        var cerrar = function (resultado) {
          if (terminado) return;
          terminado = true;
          clearTimeout(limite);
          resolve(resultado);
        };
        // No dejar el cambio de idioma esperando indefinidamente a una cuenta fuera de línea.
        var limite = setTimeout(function () { cerrar({ ok: false, causa: 'timeout' }); }, 8000);
        fetch('/v1/preferencias', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        // `keepalive` NO es adorno: `AlephI18n.setLang` hace `location.reload()` en el
        // mismo tick, y un fetch normal muere con la navegación — el idioma se habría
        // guardado en la caché local y NUNCA en la cuenta. Se ve sólo al cambiar de
        // máquina, que es exactamente el caso que esta fase existe para arreglar.
        keepalive: true,
        body: JSON.stringify({ cambios: (function (o) { o[clave] = valor; return o; })({}) })
        }).then(function (r) { cerrar({ ok: r.ok, status: r.status }); })
          .catch(function () { cerrar({ ok: false, causa: 'red' }); });
      });
    } catch (e) { return Promise.resolve({ ok: false, causa: 'red' }); }
  }

  function adoptar(pref) {
    if (!pref) return;
    adoptando = true;
    try {
      if (pref.tema && pref.tema !== raw()) set(pref.tema);
      var I = window.AlephI18n;
      var idiomaPendiente = null;
      try { idiomaPendiente = sessionStorage.getItem('aleph-lang-pending'); } catch (e) {}
      if (idiomaPendiente && I && I.lang && I.lang() === idiomaPendiente) {
        // La cuenta puede contestar con el valor previo al PUT keepalive. No rebotes una
        // elección explícita durante navegación; el marcador se limpia al converger.
        if (pref.idioma === idiomaPendiente) {
          try { sessionStorage.removeItem('aleph-lang-pending'); } catch (e) {}
        }
      } else if (pref.idioma && I && I.lang && I.setLang && pref.idioma !== I.lang()) {
        I.setLang(pref.idioma);
      }
    } catch (e) {} finally { adoptando = false; }
  }

  function sincronizar() {
    try {
      fetch('/v1/preferencias', { headers: { Accept: 'application/json' } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { adoptar(d && d.ajustes); })
        .catch(function () {});
    } catch (e) {}
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', sincronizar);
  } else { sincronizar(); }

  window.AlephTheme = { get: raw, set: set, resolved: resolved, mode: raw, KEY: KEY,
                        sincronizar: sincronizar, guardar: guardar };

  // ── EL ⚙ ÚNICO SE CARGA DESDE ACÁ ────────────────────────────────────────────────
  // [convergencia · s3 · fase 3] Medido archivo por archivo: `nav.js` llega a 15 de 35
  // pantallas y a NINGUNO de los 6 workspaces; este archivo llega a 26, workspaces
  // incluidos. Las 9 que faltan son shims, fixtures y sondas, no producto. O sea que éste
  // es el único enganche que cumple «el mismo píxel TAMBIÉN adentro del workspace».
  // La forma de inyectar es la que `nav.js` ya usa para `aleph-ds.js`: se resuelve la ruta
  // relativa al propio script, porque las pantallas de subcarpeta (`workspaces/`, `sala/`)
  // resolverían mal una ruta fija.
  (function () {
    try {
      if (window.ALEPH_AJUSTES_OFF) return;
      if (document.getElementById('aleph-ajustes-js')) return;
      var me = document.currentScript || (function () {
        var all = document.getElementsByTagName('script');
        for (var i = all.length - 1; i >= 0; i--) if ((all[i].src || '').indexOf('theme.js') >= 0) return all[i];
        return null;
      })();
      var base = me && me.src ? me.src.replace(/theme\.js.*$/, '') : './';
      var s = document.createElement('script');
      s.id = 'aleph-ajustes-js'; s.src = base + 'ajustes.js'; s.defer = true;
      (document.head || document.documentElement).appendChild(s);
    } catch (e) {}
  })();
})();
