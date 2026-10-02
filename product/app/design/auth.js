/* ALEPH auth — adjunta el token de sesión a toda llamada /v1 (anti-IDOR).
   El backend autoriza por sesión (session.owner == el id pedido), no por el id
   que manda el cliente. El token lo emite el login y se guarda como
   puppet_user.session_token. Este wrapper lo inyecta como
   `Authorization: Bearer <token>` sin tocar la lógica de cada pantalla. */
(function () {
  if (window.__alephAuthWrapped) return;
  window.__alephAuthWrapped = true;

  var KEY = 'puppet_user';

  function attachLaunchCap(headers) {
    var cap = (typeof window.__ALEPH_LAUNCH_CAP__ === 'string')
      ? window.__ALEPH_LAUNCH_CAP__ : '';
    if (cap) headers['X-Aleph-Launch'] = cap;
    return headers;
  }

  function parse(raw) {
    try { return raw ? JSON.parse(raw) : null; } catch (e) { return null; }
  }

  function usable(u) {
    return !!(u && u.id && u.session_token);
  }

  function read(store) {
    try { return parse(store.getItem(KEY)); } catch (e) { return null; }
  }

  function write(store, user) {
    try {
      if (user) store.setItem(KEY, JSON.stringify(user));
      else store.removeItem(KEY);
    } catch (e) {}
  }

  function getUser() {
    var current = read(sessionStorage);
    if (usable(current)) return current;

    var persisted = read(localStorage);
    if (usable(persisted)) {
      write(sessionStorage, persisted);
      return persisted;
    }
    return current || persisted || null;
  }

  function setUser(user) {
    if (!usable(user)) return null;
    write(sessionStorage, user);
    write(localStorage, user);
    return user;
  }

  function clearUser() {
    var user = getUser();
    var revoked = Promise.resolve();
    if (user && user.session_token && typeof _fetch === 'function') {
      try {
        revoked = _fetch('/v1/auth/logout', {
          method: 'POST', keepalive: true,
          headers: { 'Authorization': 'Bearer ' + user.session_token }
        }).catch(function () {});
      } catch (e) {}
    }
    write(sessionStorage, null);
    write(localStorage, null);
    return revoked;
  }

  /* LOGIN SUAVE — la app funciona 100% local SIN cuenta. isAnon() reconoce la
     sesión de equipo (device user); ensureLocal() la garantiza: si ya hay sesión
     usable la devuelve, si no pide POST /v1/auth/local (identidad de ESTE equipo,
     sin red externa) y la persiste. Resuelve null si el backend no ofrece auth
     local (p.ej. control plane web) → el caller decide si manda a Auth. */
  function isAnon(u) {
    return !!(u && (u.anon === true ||
      (typeof u.email === 'string' && u.email.indexOf('device::') === 0)));
  }

  var _localP = null;
  function ensureLocal() {
    var u = getUser();
    if (usable(u) && !isAnon(u)) return Promise.resolve(u);   // cuenta real: nada que hacer
    if (_localP) return _localP;
    var headers = attachLaunchCap({});
    if (usable(u)) headers['Authorization'] = 'Bearer ' + u.session_token;  // reusar/reparar
    _localP = _fetch('/v1/auth/local', { method: 'POST', headers: headers })
      .then(function (r) {
        if (!r.ok) return null;
        return r.json().then(function (j) {
          if (j && j.id && j.session_token) { setUser(j); return j; }
          return null;
        });
      })
      .catch(function () { return null; })
      .then(function (res) {
        if (!res) _localP = null;   // no cachear el fallo: el próximo intento reintenta
        return res;
      });
    return _localP;
  }

  /* REPARACIÓN — a diferencia de ensureLocal, NO respeta el guard "cuenta real": se
     invoca SÓLO cuando el backend ya rechazó el token actual (401), y un token rechazado
     no es una cuenta, es un estorbo (el caso real: supabase-auth pisaba el slot con un
     JWT que el sidecar cliente no puede mapear — users.auth_uid vive en el control
     plane). POST /v1/auth/local re-minta siempre (probado: ignora un Bearer podrido).
     En el control plane ese endpoint da 404 → resuelve null → el 401 legítimo sigue su
     camino. Single-flight: N llamadas 401eando a la vez comparten UN mint. */
  var _repairP = null;
  function repairLocal() {
    if (_repairP) return _repairP;
    var u = getUser();
    var headers = attachLaunchCap({});
    if (u && u.session_token) headers['Authorization'] = 'Bearer ' + u.session_token;
    _repairP = _fetch('/v1/auth/local', { method: 'POST', headers: headers })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (j && j.id && j.session_token) { setUser(j); return j; }
        return null;
      })
      .catch(function () { return null; })
      .then(function (res) { _repairP = null; return res; });
    return _repairP;
  }

  window.AlephSession = { get: getUser, set: setUser, clear: clearUser,
                          ensureLocal: ensureLocal, isAnon: isAnon,
                          repairLocal: repairLocal };
  getUser();

  /* ¿Esta request apunta a /v1 de NUESTRO backend? Cubre la forma relativa ('/v1/...')
     y la absoluta del mismo origen ('http://localhost:PUERTO/v1/...') — la versión
     anterior sólo veía la relativa, así que un fetch construido con base absoluta
     viajaba sin token. Cross-origin jamás: el token no sale de la máquina. */
  function v1Path(input) {
    var url = (typeof input === 'string') ? input : (input && input.url) || '';
    if (!url) return null;
    if (url.indexOf('/v1') === 0) return url;
    try {
      var p = new URL(url, window.location.origin);
      if (p.origin === window.location.origin && p.pathname.indexOf('/v1') === 0)
        return p.pathname + p.search;
    } catch (e) {}
    return null;
  }

  function replayable(input, init) {
    if (typeof input !== 'string') return false;              // Request con body: no re-leíble
    var b = init && init.body;
    return !(b && typeof b === 'object' && typeof b.getReader === 'function'); // stream: gastado
  }

  var _fetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    init = init || {};
    var path = null;
    try {
      path = v1Path(input);
      if (path) {
        var u = getUser();
        if (u && u.session_token) {
          var h = new Headers(init.headers || (typeof input !== 'string' && input.headers) || {});
          if (!h.has('Authorization')) h.set('Authorization', 'Bearer ' + u.session_token);
          init.headers = h;
        }
        if (path.indexOf('/v1/auth/local') === 0 || path.indexOf('/v1/auth/merge-local') === 0) {
          var cap = (typeof window.__ALEPH_LAUNCH_CAP__ === 'string')
            ? window.__ALEPH_LAUNCH_CAP__ : '';
          if (cap) {
            var hc = new Headers(init.headers || (typeof input !== 'string' && input.headers) || {});
            if (!hc.has('X-Aleph-Launch')) hc.set('X-Aleph-Launch', cap);
            init.headers = hc;
          }
        }
      }
    } catch (e) { /* sin sesión → la llamada sale sin token y el backend responde 401 */ }
    var p = _fetch(input, init);
    /* INTERCEPTOR GLOBAL (el martillo): un 401 de /v1 = "este token no vale acá" →
       reparar la sesión local UNA vez y reintentar la request original con el token
       fresco. Universal: cubre los flujos existentes y los futuros sin cableo por-flujo.
       Excepciones: los endpoints de auth mismos (evita bucles; merge-local es
       capability-based y su 401 ES la respuesta) y el control plane (repairLocal
       resuelve null porque /v1/auth/local no existe allá → el 401 legítimo se muestra
       con su botón-camino). */
    if (!path || path.indexOf('/v1/auth/') === 0 || init.__alephRetried || !replayable(input, init)) return p;
    return p.then(function (r) {
      if (r.status !== 401) return r;
      return repairLocal().then(function (nu) {
        if (!nu) return r;
        var h2;
        try { h2 = new Headers(init.headers || {}); } catch (e) { return r; }
        h2.set('Authorization', 'Bearer ' + nu.session_token);   // pisa: el rechazado no vuelve
        var init2 = Object.assign({}, init, { headers: h2, __alephRetried: true });
        return _fetch(input, init2);
      });
    });
  };
})();
