/* ALEPH · identidad por Supabase — CONTRACT-AUTH-v2, lado cliente.

   LA MISMA COSTURA QUE EN EL BACKEND. Allá, `session_owner()` mantuvo su firma y por eso
   cambiar quién emite el token no tocó un solo endpoint. Acá el equivalente es el slot
   `sessionStorage.puppet_user.session_token`, que auth.js ya inyecta como Bearer en toda
   llamada /v1.

   Así que esto NO reescribe el sistema de sesión del front: cuando hay sesión de
   Supabase, escribe su `access_token` EN ESE MISMO SLOT. Las 14 pantallas siguen
   andando sin tocar una línea, igual que los 206 tests del backend.

   ⚠️ EL TOKEN NO DICE EL PLAN. Acá sólo vive la identidad. El tier lo resuelve el
   servidor (`GET /v1/payments/me/tier`) y lo cachea tier_cache. Si alguna vez alguien
   lee el tier de este JWT, la muralla se cae — es el patrón que el Step 5 cerró cuatro
   veces (reports/step5/LECCION-identidad-del-cliente.md).

   OFFLINE (criterio no negociable de v2): el JWT caduca ~1h y refrescarlo EXIGE RED.
   Sin cuidado, un corte de internet deja afuera a quien pagó. La política es la misma
   que el cache de tier y que session_cache.py del backend:
     · nunca supimos quién sos → anónimo
     · te conocimos y no hay red → SEGUÍS SIENDO VOS, marcado honesto
     · el servidor NIEGA con red → afuera, en el acto
   "No pude preguntar" ≠ "me dijeron que no". */
(function () {
  if (window.__alephSupabaseAuth) return;
  window.__alephSupabaseAuth = true;

  var CFG = window.ALEPH_SUPABASE || {};
  var SLOT = 'puppet_user';          // el slot que auth.js ya lee — la costura
  var ESPEJO = 'aleph_identidad';    // copia en localStorage: sobrevive al cierre de pestaña
  var _desktopLoginActive = false;   // el SDK guarda un solo verifier PKCE por cliente
  var _DESKTOP_PENDING = 'aleph_desktop_oauth_pending';

  function _cliente() {
    if (!CFG.url || !CFG.anonKey || !window.supabase) return null;
    if (!window.__alephSbClient) {
      window.__alephSbClient = window.supabase.createClient(CFG.url, CFG.anonKey, {
        auth: {
          persistSession: true,
          autoRefreshToken: true,     // renueva solo MIENTRAS haya red
          detectSessionInUrl: true,
          flowType: 'pkce'            // el buzón desktop transporta código, jamás tokens
        }
      });
    }
    return window.__alephSbClient;
  }

  /* Escribe la identidad en el slot que el resto del front ya consume. */
  function _guardar(session) {
    if (!session || !session.access_token) return;
    var u = session.user || {};
    var identidad = {
      id: u.id || null,                    // auth.users.id; el backend lo traduce por auth_uid
      email: u.email || null,
      session_token: session.access_token, // ← LA COSTURA
      proveedor: (u.app_metadata || {}).provider || null,
      confirmado_at: Date.now()
    };
    try {
      // ⚠️ DESKTOP (.app): el SLOT no se toca. El /v1 local se autoriza con la sesión
      // LOCAL (Fernet); el JWT de la cuenta NO mapea en el sidecar cliente (users.auth_uid
      // vive en el control plane) → pisarlo dejaba TODA la app en 401 "necesita tu sesión"
      // en cada arranque con login previo. La identidad de cuenta vive en el ESPEJO.
      if (!_esDesktop()) sessionStorage.setItem(SLOT, JSON.stringify(identidad));
      localStorage.setItem(ESPEJO, JSON.stringify(identidad));
    } catch (e) { /* almacenamiento bloqueado: se sigue en memoria */ }
    window.dispatchEvent(new CustomEvent('aleph:identidad', { detail: identidad }));
  }

  function _olvidar() {
    try {
      // En desktop el SLOT es la sesión LOCAL (device), no la de la cuenta: cerrar la
      // cuenta Supabase no debe matar la sesión local que autoriza el /v1 del sidecar.
      if (!_esDesktop()) sessionStorage.removeItem(SLOT);
      localStorage.removeItem(ESPEJO);
    } catch (e) { /* */ }
    window.dispatchEvent(new CustomEvent('aleph:identidad', { detail: null }));
  }

  function _guardada() {
    try {
      var raw = sessionStorage.getItem(SLOT) || localStorage.getItem(ESPEJO);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }

  /* ── LA POLÍTICA OFFLINE ──────────────────────────────────────────────────
     Devuelve {identidad, degraded, mensaje}. Nunca deslogea por falta de red. */
  async function identidad() {
    var c = _cliente();
    var guardada = _guardada();

    if (!c) {
      // SDK o config ausentes: no se puede preguntar. Si hay algo guardado, vale.
      return guardada
        ? { identidad: guardada, degraded: true,
            mensaje: 'No pudimos verificar tu sesión. Sigues con la última conocida.' }
        : { identidad: null, degraded: true, mensaje: 'No hay sesión en este equipo.' };
    }

    try {
      var r = await c.auth.getSession();
      var s = r && r.data ? r.data.session : null;
      if (s && s.access_token) {
        _guardar(s);
        return { identidad: _guardada(), degraded: false };
      }
      // El SDK respondió y dice que NO hay sesión. Es una RESPUESTA, no silencio:
      // se obedece sólo si además hay red — sin red, getSession() puede devolver
      // vacío por no poder refrescar, y eso NO es un logout.
      if (navigator.onLine === false && guardada) {
        return { identidad: guardada, degraded: true,
                 mensaje: 'Estás sin conexión. Sigues con tu sesión guardada; la ' +
                          'revalidamos cuando vuelva internet.' };
      }
      _olvidar();
      return { identidad: null, degraded: false };
    } catch (e) {
      // NO PUDE PREGUNTAR → se preserva lo conocido. La distinción que sostiene todo.
      return guardada
        ? { identidad: guardada, degraded: true,
            mensaje: 'No pudimos verificar tu sesión ahora. Sigues con la guardada.' }
        : { identidad: null, degraded: true, mensaje: 'No hay sesión en este equipo.' };
    }
  }

  /* ── DESKTOP vs WEB ────────────────────────────────────────────────────────
     Google BLOQUEA OAuth en webviews embebidas (disallowed_useragent). En el `.app`
     (Tauri) el botón abre el NAVEGADOR DEL SISTEMA con la URL de OAuth de siempre; el
     callback vuelve por LOOPBACK al MISMO puerto que ya sirve la webview (nuestro origen),
     el sidecar lo deposita en un buzón por-nonce, y acá lo poleamos y establecemos la
     sesión. La WEB no se toca: allá `_esDesktop()` es false y sigue el flujo de siempre. */
  function _esDesktop() {
    return !!(window.__TAURI__ || window.__TAURI_INTERNALS__);
  }

  function _abrirEnNavegador(url) {
    var T = window.__TAURI__;
    try {
      if (T && T.opener && typeof T.opener.openUrl === 'function') return T.opener.openUrl(url);
      if (T && T.core && typeof T.core.invoke === 'function')
        return T.core.invoke('plugin:opener|open_url', { url: url });
    } catch (e) { /* cae al reject de abajo */ }
    return Promise.reject(new Error('No se pudo abrir el navegador del sistema.'));
  }

  async function _pollSesionDesktop(nonce, timeoutMs) {
    var t0 = Date.now();
    while (Date.now() - t0 < timeoutMs) {
      try {
        var cap = (typeof window.__ALEPH_LAUNCH_CAP__ === 'string')
          ? window.__ALEPH_LAUNCH_CAP__ : '';
        var r = await window.fetch('/auth/desktop/session?aleph_nonce=' + encodeURIComponent(nonce),
          { cache: 'no-store', headers: cap ? { 'X-Aleph-Launch': cap } : {} });
        if (r.status === 200) {
          var j = await r.json();
          if (j && j.error) {
            var providerError = new Error(j.error_description || j.error);
            providerError.oauthProvider = true;
            throw providerError;
          }
          if (j && j.code) return j;
        }
        // 204 = el callback todavía no volvió; seguir esperando
      } catch (e) {
        if (e && e.oauthProvider) throw e;
        // red transitoria del poll → reintentar
      }
      await new Promise(function (res) { setTimeout(res, 1200); });
    }
    throw new Error('El login por el navegador no volvió a tiempo.');
  }

  // Canal de diagnóstico del OAuth desktop: a la consola Y al stderr del sidecar (la webview
  // del .app no tiene consola visible headless). Fire-and-forget, nunca rompe el flujo.
  function _diag(paso) {
    var o = { paso: paso };
    try { console.log('[oauth-diag]', paso); } catch (e) {}
    try {
      window.fetch('/auth/desktop/log', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(o), keepalive: true });
    } catch (e) {}
  }

  function _pendingDesktop() {
    // sessionStorage sobrevive a un reload de la misma webview, igual que el verifier
    // PKCE del SDK. Un nuevo login no debe sobrescribirlo mientras el anterior vive.
    var raw;
    try { raw = sessionStorage.getItem(_DESKTOP_PENDING); }
    catch (e) { throw new Error('No hay almacenamiento seguro para el ingreso.'); }
    if (!raw) return null;
    var p;
    try { p = JSON.parse(raw); } catch (e) { p = null; }
    if (p && typeof p.nonce === 'string' && /^[A-Za-z0-9._:-]{16,128}$/.test(p.nonce)
        && Number.isFinite(p.until) && p.until > Date.now()) return p;
    try { sessionStorage.removeItem(_DESKTOP_PENDING); }
    catch (e) { throw new Error('No se pudo limpiar un ingreso vencido.'); }
    return null;
  }

  function _guardarPendingDesktop(nonce) {
    try { sessionStorage.setItem(_DESKTOP_PENDING,
      JSON.stringify({ nonce: nonce, until: Date.now() + 300000 })); }
    catch (e) { throw new Error('No hay almacenamiento seguro para el ingreso.'); }
  }

  function _limpiarPendingDesktop(nonce) {
    try {
      var p = _pendingDesktop();
      if (p && p.nonce === nonce) sessionStorage.removeItem(_DESKTOP_PENDING);
    } catch (e) { /* la entrada caduca en 5 min; nunca iniciar otro flow inseguro */ }
  }

  async function _terminarDesktop(c, nonce, timeoutMs) {
    _diag('poll:inicio');
    var tok;
    try {
      tok = await _pollSesionDesktop(nonce, timeoutMs);
      _diag('poll:ok');
    } catch (ep) {
      _diag('poll:error'); throw ep;
    }
    // Sólo la webview iniciadora conserva el verifier PKCE, incluso tras reload.
    var s = await c.auth.exchangeCodeForSession(tok.code);
    if (s && s.error) { _diag('setSession:error'); throw s.error; }
    _diag('setSession:ok');
    var destino = (CFG.redirectTo || window.location.origin + '/Home.dc.html');
    _diag('navegando');
    window.location.assign(destino);
    return s;
  }

  async function _entrarDesktop(c, proveedor) {
    var nonce = null;
    try {
      var pending = _pendingDesktop();
      if (pending) {
        nonce = pending.nonce;
        return await _terminarDesktop(c, nonce, pending.until - Date.now());
      }
      if (!window.crypto || typeof window.crypto.randomUUID !== 'function')
        throw new Error('No hay generador criptográfico para iniciar sesión.');
      nonce = window.crypto.randomUUID();
      var state = window.crypto.randomUUID();
      // el callback vuelve a NUESTRO origen (= el puerto del sidecar que ya nos sirve)
      var callback = window.location.origin + '/auth/desktop/callback?aleph_nonce=' +
        encodeURIComponent(nonce) + '&aleph_state=' + encodeURIComponent(state);
      _diag('inicio');
      var launchCap = (typeof window.__ALEPH_LAUNCH_CAP__ === 'string')
        ? window.__ALEPH_LAUNCH_CAP__ : '';
      var inicio = await window.fetch('/auth/desktop/start', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Aleph-Launch': launchCap },
        body: JSON.stringify({ aleph_nonce: nonce, aleph_state: state })
      });
      if (!inicio.ok) throw new Error('No se pudo preparar el ingreso seguro.');
      // 1. la URL de OAuth SIN navegar la webview (skipBrowserRedirect)
      var r = await c.auth.signInWithOAuth({
        provider: proveedor,
        options: { redirectTo: callback, skipBrowserRedirect: true }
      });
      if (r && r.error) { _diag('signInWithOAuth:error'); throw r.error; }
      if (!r || !r.data || !r.data.url) { _diag('signInWithOAuth:sin-url'); throw new Error('No se pudo generar la URL de OAuth.'); }
      // El SDK ya persistió el verifier; recién ahora es seguro reanudar tras reload.
      _guardarPendingDesktop(nonce);
      _diag('signInWithOAuth:ok');
      // 2. abrir el navegador del sistema (fuera de la webview)
      try {
        await _abrirEnNavegador(r.data.url);
        _diag('abrirNavegador:ok');
      } catch (eo) {
        _diag('abrirNavegador:error'); throw eo;
      }
      // 3. poll y canje en la webview que conserva el verifier PKCE.
      return await _terminarDesktop(c, nonce, 300000);
    } catch (e) {
      _diag('FALLO');
      throw e;
    } finally {
      if (nonce) _limpiarPendingDesktop(nonce);
    }
  }

  async function entrarCon(proveedor) {
    var c = _cliente();
    if (!c) throw new Error('Supabase no está configurado en este cliente.');
    if (_esDesktop()) {
      if (_desktopLoginActive) throw new Error('Ya hay un ingreso en curso.');
      _desktopLoginActive = true;
      try { return await _entrarDesktop(c, proveedor); }
      finally { _desktopLoginActive = false; }
    }
    // WEB: el flujo de siempre (NO se toca) — el SDK navega la pestaña afuera y vuelve con el token.
    var destino = (CFG.redirectTo || window.location.origin + '/Home.dc.html');
    var r = await c.auth.signInWithOAuth({
      provider: proveedor,                  // 'google' | 'github'
      options: { redirectTo: destino }
    });
    if (r && r.error) throw r.error;
    return r;
  }

  async function salir() {
    var c = _cliente();
    // Se borra lo local SIEMPRE, aunque el signOut remoto falle: si no, un logout sin
    // red dejaría la sesión viva en la máquina — y en un equipo compartido eso es
    // dejarle la cuenta abierta al siguiente.
    try { if (c) await c.auth.signOut(); } catch (e) { /* */ }
    _olvidar();
  }

  /* ── MATERIALIZAR LA CUENTA ────────────────────────────────────────────────
     Sin esto, un login perfecto de Google dejaba al usuario existiendo en Supabase
     pero NO en nuestro Postgres: el alta local es perezosa y sólo ocurre cuando el
     backend ve el token, y ninguna pantalla hacía una llamada autenticada al cargar.
     Resultado observado: 3 usuarios en auth.users, 0 en public.users, y el backend sin
     recibir una sola request.

     `GET /v1/payments/me/tier` es la llamada correcta para esto: dispara session_owner
     (que crea y liga la cuenta por auth_uid) y de paso trae el tier que el cliente
     necesita. Una llamada, dos cosas.

     ⚠️ Del tier que devuelve, el cliente sólo decide QUÉ MOSTRAR. Los muros siguen
     resolviéndolo server-side en cada request. */
  async function _materializar() {
    try {
      var r = await window.fetch('/v1/payments/me/tier');   // auth.js le pone el Bearer
      if (!r.ok) return null;
      var t = await r.json();
      window.dispatchEvent(new CustomEvent('aleph:tier', { detail: t }));
      return t;
    } catch (e) {
      // Sin red no se materializa todavía; se reintenta en el próximo arranque. No es
      // un error del login: la sesión ya es válida y el cliente sigue andando.
      return null;
    }
  }

  /* ── EL OAUTH QUE VUELVE MAL TIENE QUE DECIRLO ────────────────────────────
     Un login que falla y te deposita de vuelta en la pantalla de entrada SIN UNA
     PALABRA es el peor fallo posible: el usuario no sabe si se equivocó, si el
     servicio está caído, o si tiene que reintentar. Pasó en la primera prueba real de
     v2 (la URL de retorno no estaba en la allowlist de Supabase; el proveedor devolvió
     al Site URL sin token y la pantalla se quedó callada).

     Supabase informa el motivo en el fragmento (#error=…&error_description=…) o en la
     query. Se lee, se muestra y se limpia de la URL para que no quede pegado. */
  function _errorDeRetorno() {
    var fuentes = [window.location.hash.replace(/^#/, ''), window.location.search.replace(/^\?/, '')];
    for (var i = 0; i < fuentes.length; i++) {
      if (!fuentes[i]) continue;
      var p = new URLSearchParams(fuentes[i]);
      var err = p.get('error') || p.get('error_code');
      if (err) {
        var det = p.get('error_description') || '';
        return { error: err, detalle: decodeURIComponent(det.replace(/\+/g, ' ')) };
      }
    }
    return null;
  }

  (function avisarSiVolvioMal() {
    var e = _errorDeRetorno();
    if (!e) return;
    // Se limpia la URL: un F5 no debe repetir el mensaje de un intento viejo.
    try { history.replaceState(null, '', window.location.pathname); } catch (x) { /* */ }
    window.dispatchEvent(new CustomEvent('aleph:auth-error', { detail: e }));
    console.warn('[aleph] el proveedor devolvió un error:', e.error, '·', e.detalle);
    // Aviso visible aunque la pantalla no escuche el evento: sin esto el usuario ve
    // la pantalla de login otra vez y no sabe por qué.
    try {
      var d = document.createElement('div');
      d.setAttribute('data-aleph-auth-error', e.error);
      d.style.cssText = 'position:fixed;top:14px;left:50%;transform:translateX(-50%);' +
        'z-index:99999;background:#3A2F1E;color:#F3ECE0;border:1px solid #E0A23C;' +
        'border-radius:12px;padding:11px 15px;font:13px/1.45 var(--font-ui, "Hanken Grotesk", system-ui, sans-serif);' +
        'max-width:min(560px,92vw);box-shadow:0 10px 34px rgba(0,0,0,.45)';
      d.textContent = 'No pudimos completar el ingreso: ' + (e.detalle || e.error);
      var cerrar = function () { if (d.parentNode) d.remove(); };
      d.addEventListener('click', cerrar);
      setTimeout(cerrar, 12000);
      (document.body || document.documentElement).appendChild(d);
    } catch (x) { /* */ }
  })();

  // El SDK renueva el token solo; cada renovación tiene que refrescar la costura, o
  // auth.js seguiría mandando el token viejo hasta que la pestaña se recargue.
  (function suscribir() {
    var c = _cliente();
    if (!c) return;
    c.auth.onAuthStateChange(function (evento, session) {
      if (session && session.access_token) {
        _guardar(session);
        if (evento === 'SIGNED_IN' || evento === 'INITIAL_SESSION') _materializar();
      } else if (evento === 'SIGNED_OUT') {
        _olvidar();
      }
    });
  })();

  window.alephAuth = {
    identidad: identidad,
    materializar: _materializar,
    entrarCon: entrarCon,
    salir: salir,
    guardada: _guardada,
    disponible: function () { return !!_cliente(); }
  };
})();
