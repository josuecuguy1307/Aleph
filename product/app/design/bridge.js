/* ══════════════════════════════════════════════════════════════════════════
 * Aleph · PUENTE DE CONTINUIDAD Cuarto→Sala   (Step 4 · 4A#5)
 *
 * La transición entre El Cuarto (cuarto.html) y La Sala (sala.html) es un page-nav DURO
 * (dos documentos aislados; sólo ?puppet=<id> cruza). Este puente la hace SENTIR continua
 * SIN unificar superficies: dibuja el MISMO frame en los dos archivos —el Cuarto lo LEVANTA
 * antes del location.href, la Sala lo RECIBE y sólo REVELA cuando está DE VERDAD lista—.
 *
 * Reusa el LENGUAJE DEL REEL, no inventa: la mascota es el átomo canon de Aleph (el mismo
 * glifo --mark de la Sala = gemelo vector del makeNucleo de PIXI: órbitas cruzadas + beads +
 * hexágono + cara ⌒⌒). Las "partículas" son beads que CONVERGEN al átomo (Cuarto) y DISPERSAN
 * al revelar (Sala). El frame de corte (pico) es DETERMINÍSTICO → idéntico por construcción.
 *
 * HONESTO: el puente aguanta hasta ready(); si el montaje falla → nota honesta + volver al
 * Taller, NUNCA revela una Sala vacía/a medias. La continuidad es SÓLO visual: el estado ya
 * viaja por ?puppet=<id> + re-fetch — este módulo no lo toca.
 * ════════════════════════════════════════════════════════════════════════ */
(function () {
  "use strict";
  var KEY = "aleph_bridge";     // token en sessionStorage (modelo: sala_pending_attach)
  var TTL = 8000;               // token fresco 8s: un nav real tarda <1s → evita puentes zombie de una pestaña vieja

  // LA MASCOTA, Y AHORA ES LA MISMA QUE EN TODAS PARTES.
  // [rediseño · fase 2 · decisión del dueño: la CLARA, no la oscura]
  //
  // Acá vivía el átomo dibujado a mano en SVG, con sus violetas HARDCODEADOS (#6E6BD0
  // órbitas, #8E8BF5 hexágono, #211E3A cara): la versión OSCURA. El estándar pide un solo
  // Aleph y el dueño eligió la clara — `assets/aleph-mascot-v2.png`, la misma que la barra
  // usa desde julio.
  //
  // ⚠️ POR QUÉ ESTO NO ROMPE EL FRAME DE CORTE. El puente dibuja SU PROPIO overlay en los dos
  // documentos (el Cuarto lo levanta, la Sala lo recibe) y los dos cargan ESTE archivo. O
  // sea que el frame determinístico lo es porque las dos mitades leen el mismo código, no
  // porque el glifo coincida con el `makeNucleo` de PIXI —que es otra pieza, del diorama—.
  // Cambiar el glifo acá lo cambia en las dos mitades a la vez, que es justo la condición.
  //
  // LA RUTA SE RESUELVE DESDE ESTE SCRIPT, no desde el documento: el Cuarto vive en
  // `design/cuarto/` y la Sala en `design/sala-v2/`, así que un `assets/…` relativo al
  // documento apuntaría a dos lugares distintos y uno de los dos daría 404 — o sea el puente
  // sin mascota justo en la transición que existe para que no se vea el salto.
  var BASE = (function () {
    try {
      var me = document.currentScript;
      if (!me) {
        var todos = document.getElementsByTagName("script");
        for (var k = todos.length - 1; k >= 0; k--) {
          if ((todos[k].src || "").indexOf("bridge.js") >= 0) { me = todos[k]; break; }
        }
      }
      return me && me.src ? me.src.replace(/bridge\.js.*$/, "") : "./";
    } catch (e) { return "./"; }
  })();

  var ATOM =
    "<img class='ab-glyph' alt='' aria-hidden='true' src='" + BASE + "assets/aleph-mascot-v2.png'>";

  // 8 beads convergentes (el lenguaje de partículas del reel). Posiciones fijas por índice →
  // determinísticas: convergen en .ab-in, quedan MERGED (invisibles) en el pico (frame de corte),
  // y DISPERSAN en .ab-out. Cada una parte/vuelve a un ángulo fijo (var --a) y radio (var --r).
  function beads() {
    var h = "", n = 8, i, a;
    for (i = 0; i < n; i++) {
      a = (360 / n) * i;
      h += "<i class='ab-p' style='--a:" + a + "deg'></i>";
    }
    return h;
  }

  var CSS =
    "html.ab-lock,body.ab-lock{overflow:hidden!important}" +
    "#ab-overlay{position:fixed;inset:0;z-index:2147483000;display:flex;align-items:center;justify-content:center;" +
      "background:radial-gradient(circle at 50% 42%,#241b3a 0%,#140f1e 58%,#0c0912 100%);" +
      "font-family:var(--font-ui);-webkit-font-smoothing:antialiased;" +
      "opacity:1;transition:opacity .56s ease}" +
    "#ab-overlay.ab-out{opacity:0}" +
    "#ab-overlay .ab-stage{position:relative;display:flex;flex-direction:column;align-items:center;gap:18px;" +
      "transform:translateY(-2%)}" +
    "#ab-overlay .ab-halo{position:absolute;top:-38px;left:50%;width:220px;height:220px;margin-left:-110px;border-radius:50%;" +
      "background:radial-gradient(circle,rgba(142,139,245,.30) 0%,rgba(142,139,245,.10) 42%,transparent 68%);" +
      "filter:blur(2px);opacity:.9}" +
    "#ab-overlay.ab-out .ab-halo{animation:ab-burst .56s ease forwards}" +
    "#ab-overlay .ab-atom{position:relative;width:132px;height:132px;display:flex;align-items:center;justify-content:center}" +
    "#ab-overlay .ab-glyph{width:118px;height:118px;display:block;filter:drop-shadow(0 4px 22px rgba(110,107,208,.45));" +
      "transform:scale(1);transition:transform .5s cubic-bezier(.2,.8,.2,1)}" +
    "#ab-overlay.ab-in .ab-glyph{animation:ab-emerge .6s cubic-bezier(.2,.8,.2,1) both}" +
    "#ab-overlay.ab-out .ab-glyph{animation:ab-pulse .56s ease forwards}" +
    // beads: en el pico están en el centro (merged, opacity 0). .ab-in las trae DESDE fuera; .ab-out las MANDA fuera.
    "#ab-overlay .ab-p{position:absolute;top:50%;left:50%;width:6px;height:6px;margin:-3px 0 0 -3px;border-radius:50%;" +
      "background:#b389ff;box-shadow:0 0 8px rgba(179,137,255,.8);opacity:0;" +
      "transform:rotate(var(--a)) translateX(0)}" +
    "#ab-overlay.ab-in .ab-p{animation:ab-converge .6s ease-out both}" +
    "#ab-overlay.ab-out .ab-p{animation:ab-disperse .56s ease-in forwards}" +
    "#ab-overlay .ab-name{font-family:var(--font-display);font-weight:500;font-size:19px;color:#F3ECE0;letter-spacing:-.01em;" +
      "text-align:center;max-width:80vw;text-shadow:0 1px 12px rgba(0,0,0,.5)}" +
    "#ab-overlay .ab-note{font-size:12.5px;color:#A89C8B;display:flex;align-items:center;gap:8px}" +
    "#ab-overlay .ab-dot{width:6px;height:6px;border-radius:50%;background:#b389ff;box-shadow:0 0 8px rgba(179,137,255,.7);" +
      "animation:ab-blink 1.15s ease-in-out infinite}" +
    "#ab-overlay .ab-back{margin-top:4px;font-size:12.5px;color:#B4B1FF;background:none;border:1px solid #463A66;border-radius:9px;" +
      "padding:7px 14px;cursor:pointer;text-decoration:none;display:none}" +
    "#ab-overlay.ab-fail .ab-back{display:inline-block}" +
    "#ab-overlay.ab-fail .ab-dot{display:none}" +
    "#ab-overlay.ab-fail .ab-glyph{filter:grayscale(.7) drop-shadow(0 4px 14px rgba(0,0,0,.4));opacity:.7}" +
    "#ab-overlay.ab-fail .ab-name{color:#E58A8A}" +
    "@keyframes ab-emerge{from{transform:scale(.86);opacity:.5}to{transform:scale(1);opacity:1}}" +
    "@keyframes ab-converge{from{opacity:.9;transform:rotate(var(--a)) translateX(150px)}" +
      "60%{opacity:1}to{opacity:0;transform:rotate(var(--a)) translateX(0)}}" +
    "@keyframes ab-disperse{from{opacity:0;transform:rotate(var(--a)) translateX(0)}" +
      "20%{opacity:1}to{opacity:0;transform:rotate(var(--a)) translateX(170px)}}" +
    "@keyframes ab-pulse{0%{transform:scale(1)}40%{transform:scale(1.08)}100%{transform:scale(1.14);opacity:0}}" +
    "@keyframes ab-burst{0%{transform:scale(1);opacity:.9}100%{transform:scale(1.9);opacity:0}}" +
    "@keyframes ab-blink{0%,100%{opacity:.35}50%{opacity:1}}" +
    "@media (prefers-reduced-motion:reduce){#ab-overlay .ab-p{display:none}" +
      "#ab-overlay.ab-in .ab-glyph,#ab-overlay.ab-out .ab-glyph,#ab-overlay.ab-out .ab-halo{animation:none}}";

  function ensureStyle() {
    if (document.getElementById("ab-style")) return;
    var s = document.createElement("style");
    s.id = "ab-style";
    s.textContent = CSS;
    (document.head || document.documentElement).appendChild(s);
  }

  function mount(name) {
    ensureStyle();
    var o = document.getElementById("ab-overlay");
    if (o) return o;
    o = document.createElement("div");
    o.id = "ab-overlay";
    o.setAttribute("role", "status");
    o.setAttribute("aria-live", "polite");
    o.innerHTML =
      "<div class='ab-stage'>" +
        "<div class='ab-halo'></div>" +
        "<div class='ab-atom'>" + ATOM + beads() + "</div>" +
        "<div class='ab-name'></div>" +
        "<div class='ab-note'><span class='ab-dot'></span><span class='ab-note-t'>cobrando vida…</span></div>" +
        "<a class='ab-back' href='../cuarto/cuarto.pixi.html'></a>" +
      "</div>";
    var back = o.querySelector(".ab-back");
    back.textContent = window.AlephI18n && window.AlephI18n.t
      ? window.AlephI18n.t("workshop.action.return")
      : "Volver al Cuarto";
    o.querySelector(".ab-name").textContent = name || "Tu agente";
    var root = document.documentElement; if (root) root.classList.add("ab-lock");
    (document.body || document.documentElement).appendChild(o);
    if (document.body) document.body.classList.add("ab-lock");
    return o;
  }

  function unmount(o) {
    if (o && o.parentNode) o.parentNode.removeChild(o);
    var root = document.documentElement; if (root) root.classList.remove("ab-lock");
    if (document.body) document.body.classList.remove("ab-lock");
  }

  // ── CUARTO: LEVANTAR el puente y navegar en el frame pico ────────────────
  // Dibuja el overlay + la convergencia (.ab-in) AHORA, deja el token, y navega tras `delay`
  // (default 700ms, el mismo beat de "cobra vida" de darleVida). Al momento del location.href el
  // overlay está en su estado PICO (átomo pleno, beads merged) = el frame que la Sala redibuja.
  function raise(opts) {
    opts = opts || {};
    var name = opts.name || "Tu agente";
    try { sessionStorage.setItem(KEY, JSON.stringify({ name: name, t: Date.now() })); } catch (e) {}
    var o = mount(name);
    // reflow para que .ab-in anime desde el estado base (no salte)
    void o.offsetWidth;
    o.classList.add("ab-in");
    var delay = (typeof opts.delay === "number") ? opts.delay : 700;
    setTimeout(function () { if (opts.href) location.href = opts.href; }, delay);
    return o;
  }

  // ── SALA: RECIBIR el puente ───────────────────────────────────────────────
  // Si hay token fresco, monta el MISMO frame (held, sin fade-in → continuo con el Cuarto) y
  // devuelve un control {ready,fail}. NO revela solo: aguanta hasta ready() (Sala de verdad lista).
  // Sin token / token viejo → devuelve null (carga directa, sin overlay). Timeout → fail honesto.
  function receive(opts) {
    opts = opts || {};
    var raw; try { raw = sessionStorage.getItem(KEY); } catch (e) { return null; }
    if (!raw) return null;
    try { sessionStorage.removeItem(KEY); } catch (e) {}       // read-once (como sala_pending_attach)
    var tok; try { tok = JSON.parse(raw); } catch (e) { return null; }
    if (!tok || !tok.t || (Date.now() - tok.t) > TTL) return null;

    var o = mount(tok.name);
    o.classList.add("ab-held");                                // frame PICO idéntico al del Cuarto (sin re-animar la entrada)
    var done = false;
    var to = setTimeout(function () {
      if (!done) fail("Tardó demasiado en abrir. Recarga o vuelve al Taller.");
    }, (typeof opts.timeout === "number") ? opts.timeout : 12000);

    function reveal() {
      if (done) return; done = true; clearTimeout(to);
      o.classList.remove("ab-held"); o.classList.add("ab-out");
      // esperar el fin del fade (.ab-out = .56s) para sacar el overlay → la Sala YA lista queda debajo
      setTimeout(function () { unmount(o); }, 620);
    }
    function fail(msg) {
      if (done) return; done = true; clearTimeout(to);
      o.classList.remove("ab-held"); o.classList.add("ab-fail");
      var t = o.querySelector(".ab-note-t"); if (t) t.textContent = msg || "No pudimos abrir la Sala de tu agente.";
      // NO se revela una Sala vacía: el overlay QUEDA con la nota honesta + volver al Taller.
    }
    return { ready: reveal, fail: fail };
  }

  window.AlephBridge = { raise: raise, receive: receive };
})();
