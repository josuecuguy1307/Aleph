/* AlephBrand — la CARA de cada servicio conectable (ticket 8 · logos en toda superficie).
 *
 * Contrato: slug (server/connector) → logo REAL del servicio si está en el mapa curado del
 * backend (GET /v1/icons → manifest de slugs conocidos; GET /v1/icons/{slug} → favicon
 * cacheado server-side) · si no → FALLBACK genérico: iniciales + color determinista por
 * nombre. UN ícono por pieza (logo O genérico, jamás ambos). El logo se muestra INTACTO
 * (sin tinte ni recorte); el copy alrededor dice "conecta con X", nunca "oficial de X".
 *
 * Sin red / backend caído / takedown (404): TODO degrada al fallback — ninguna superficie
 * se rompe ni queda esperando. El manifest evita disparar un 404 por pieza desconocida:
 * la decisión logo-vs-genérico es sincrónica una vez cargado (evento "aleph:brands").
 *
 * Módulo clásico (no-ESM), mismo idiom que icons.js → window.AlephBrand.
 *   AlephBrand.faceHTML({server:"github"}, {size:16})  → '<span class="bface">…' (img o iniciales)
 *   AlephBrand.has("github") · AlephBrand.url("github") · AlephBrand.ready (Promise del manifest)
 *   AlephBrand.image("github") → Promise<HTMLImageElement|null> (para texturas Pixi del Cuarto)
 */
(function (root) {
  "use strict";

  var known = null; // Set de slugs con logo curado; null = manifest aún no llegó (→ fallback)
  var _resolveReady;
  var ready = new Promise(function (res) { _resolveReady = res; });

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function uniq(arr) {
    var out = [], seen = {};
    for (var i = 0; i < arr.length; i++) {
      var s = String(arr[i] == null ? "" : arr[i]).toLowerCase().trim();
      if (!s || seen[s]) continue;
      seen[s] = 1; out.push(s);
    }
    return out;
  }

  /** server/connector/string → slug normalizado (lo que el backend espera en /v1/icons/{slug}). */
  function slugFor(x) {
    var c = slugCandidates(x);
    return c.length ? c[0] : "";
  }

  function slugCandidates(x) {
    if (!x) return [];
    if (typeof x !== "object") return uniq([x]);
    // La entidad normalizada del Cuarto usa `logo`/`service` y no tiene por qué exponer
    // un server único. Los widgets conservan la marca desde esos campos; connector,
    // server y name quedan como compatibilidad para cards antiguas.
    return uniq([x.slug, x.logo, x.service, x.connector, x.server, x.name]);
  }

  function knownSlugFor(x) {
    var c = slugCandidates(x);
    if (!known) return "";
    for (var i = 0; i < c.length; i++) if (known.has(c[i])) return c[i];
    return "";
  }

  function has(x) {
    return !!knownSlugFor(x);
  }

  function url(x) { return "/v1/icons/" + encodeURIComponent(knownSlugFor(x) || slugFor(x)); }

  /** Color determinista por nombre (mismo nombre → mismo color, en cualquier superficie). */
  function hueOf(name) {
    var h = 0; name = String(name || "");
    for (var i = 0; i < name.length; i++) h = ((h * 31 + name.charCodeAt(i)) & 0x7fffffff);
    return h % 360;
  }
  function colorFor(name) { return "hsl(" + hueOf(name) + " 42% 40%)"; }

  /** Iniciales legibles del nombre humano ("google_drive" → "GD", "exa" → "EX"). */
  function initialsOf(name) {
    var words = String(name || "?").replace(/[_\-./]+/g, " ").trim().split(/\s+/).filter(Boolean);
    if (!words.length) return "?";
    var s = words.length > 1 ? words[0].charAt(0) + words[1].charAt(0)
                             : words[0].slice(0, 2);
    return s.toUpperCase();
  }

  /** Nombre humano del slug (idéntico criterio que svcName del Cuarto: titleize). */
  function displayName(x) {
    if (x && typeof x === "object" && x.label) return String(x.label);
    return slugFor(x).replace(/[_-]+/g, " ").replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }

  function initialsHTML(name, size, cls) {
    return '<span class="bface binit' + (cls ? " " + cls : "") + '"' +
      ' style="width:' + size + "px;height:" + size + "px;background:" + colorFor(name) +
      ';font-size:' + Math.max(7, Math.round(size * 0.42)) + 'px"' +
      ' aria-hidden="true">' + esc(initialsOf(name)) + "</span>";
  }

  /**
   * faceHTML(nameOrData, {size=16, cls}) → string HTML.
   * Conocido → <img> del logo (onerror → cae solo a iniciales; p.ej. takedown a mitad de sesión).
   * Desconocido / manifest ausente → iniciales + color (cero red).
   */
  function faceHTML(x, opts) {
    opts = opts || {};
    var size = opts.size || 16;
    var name = displayName(x);
    if (!has(x)) return initialsHTML(name, size, opts.cls);
    return '<span class="bface' + (opts.cls ? " " + opts.cls : "") + '"' +
      ' style="width:' + size + "px;height:" + size + 'px" data-bname="' + esc(name) + '"' +
      ' aria-hidden="true"><img src="' + esc(url(x)) + '" alt="" loading="lazy" decoding="async"' +
      ' onerror="window.AlephBrand&&AlephBrand._fail(this)"></span>';
  }

  /** onerror del <img>: degrada EN EL LUGAR a iniciales+color (sin re-render del caller). */
  function _fail(img) {
    var host = img && img.parentNode; if (!host) return;
    var name = host.getAttribute("data-bname") || "?";
    host.classList.add("binit");
    host.style.background = colorFor(name);
    host.style.fontSize = Math.max(7, Math.round((host.clientWidth || 16) * 0.42)) + "px";
    host.textContent = initialsOf(name);
  }

  // ── cara para canvas (Pixi del Cuarto): HTMLImageElement cacheado por slug ──
  var _imgCache = {};
  function image(x) {
    var s = knownSlugFor(x) || slugFor(x);
    if (!s) return Promise.resolve(null);
    if (_imgCache[s]) return _imgCache[s];
    _imgCache[s] = ready.then(function () {
      if (!has(s)) return null;
      return new Promise(function (res) {
        var im = new Image();
        im.onload = function () { res(im); };
        im.onerror = function () { res(null); };   // 404/red → null → el caller conserva su glifo
        im.src = url(s);
      });
    });
    return _imgCache[s];
  }

  // ── manifest: UNA vez por página; al llegar avisa (las superficies re-renderizan si quieren) ──
  function loadManifest() {
    var p;
    try { p = fetch("/v1/icons").then(function (r) { return r.ok ? r.json() : null; }); }
    catch (e) { p = Promise.resolve(null); }
    return p.then(function (d) { known = new Set((d && d.known) || []); })
      .catch(function () { known = new Set(); })
      .then(function () {
        _resolveReady(known);
        try { root.dispatchEvent(new CustomEvent("aleph:brands")); } catch (e) {}
      });
  }

  // ── CSS propio (inyectado una vez): la cara es cuadradita, el logo entero, sin tinte ──
  function injectCSS() {
    if (typeof document === "undefined" || document.getElementById("aleph-brandface-css")) return;
    var st = document.createElement("style");
    st.id = "aleph-brandface-css";
    st.textContent =
      ".bface{display:inline-flex;align-items:center;justify-content:center;vertical-align:middle;" +
      "border-radius:3px;overflow:hidden;flex:none;box-sizing:border-box}" +
      ".bface img{width:100%;height:100%;object-fit:contain;display:block}" +
      /* [barrido] Las iniciales son la MARCA cuando no hay logo: van en la serif de marca a
         peso 400, igual que los avatares de agente en Home. El 700 y el fallback a
         'Hanken Grotesk' —la familia anterior— venían del diseño viejo. El blanco se
         conserva: el cuadrado va tinteado con el color del servicio. */
      ".bface.binit{font-weight:400;line-height:1;color:#fff;letter-spacing:0;" +
      "font-family:var(--font-brand, 'Newsreader', Georgia, serif);user-select:none}";
    (document.head || document.documentElement).appendChild(st);
  }

  injectCSS();
  loadManifest();

  root.AlephBrand = {
    ready: ready, has: has, url: url, slugFor: slugFor, faceHTML: faceHTML,
    initialsHTML: function (name, opts) { opts = opts || {}; return initialsHTML(name, opts.size || 16, opts.cls); },
    colorFor: colorFor, initialsOf: initialsOf, displayName: displayName,
    image: image, _fail: _fail,
    _candidates: slugCandidates,
    _known: function () { return known ? Array.from(known) : null; }   // hook de verificación
  };
})(typeof window !== "undefined" ? window : this);
