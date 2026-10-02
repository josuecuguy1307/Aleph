/* ALEPH · paywall — el 402 se VE. Step 5 · Casa 1 · P10.

   El problema que cierra: los muros premium ya negaban bien server-side y devolvían
   un rechazo honesto con su copy… que NO TENÍA UN SOLO CONSUMIDOR en el front. El
   usuario free golpeaba el muro y recibía un error mudo (o nada). El §4 pase 2 del
   Step 5 exige "402 + upsell honesto + jamás error mudo", y sin esto no se certifica.

   CÓMO: un interceptor global sobre fetch (mismo patrón que auth.js, que ya envuelve
   fetch para inyectar el Bearer). Cualquier pantalla que reciba un 402 con
   `tier_gated` muestra la card — sin tocar el código de cada pantalla, presente o
   futura. Una pantalla nueva queda cubierta el día que se escribe.

   REGLA DURA — EL COPY VIENE DEL SERVIDOR. Esta card NO inventa texto de venta: lo
   que muestra es el `error` que emitió `platform/gates/tier_gate.py`, que ya está
   certificado (Reválida 4.6) y ya nombra lo que el plan gratuito SÍ puede hacer.
   Duplicar el mensaje acá crearía dos verdades que se desincronizan: el día que
   cambie la frontera, el front mentiría.

   NO TRAGA EL ERROR: la respuesta se devuelve intacta al llamador (se lee sobre un
   clone). Quien quiera manejar su propio 402 puede seguir haciéndolo. */
(function () {
  if (window.__alephPaywall) return;
  window.__alephPaywall = true;

  var ULTIMO = 0;   // anti-spam: varias llamadas en paralelo no apilan cards

  function t(es, en) {
    try {
      var lang = (document.documentElement.lang || 'es').toLowerCase();
      return lang.indexOf('en') === 0 ? en : es;
    } catch (e) { return es; }
  }

  function estilos() {
    if (document.getElementById('aleph-paywall-css')) return;
    var s = document.createElement('style');
    s.id = 'aleph-paywall-css';
    s.textContent = [
      '.aleph-paywall-bg{position:fixed;inset:0;background:rgba(8,8,16,.62);',
      'backdrop-filter:blur(3px);z-index:99999;display:flex;align-items:center;',
      'justify-content:center;padding:24px;animation:alephPwIn .16s ease-out}',
      '@keyframes alephPwIn{from{opacity:0}to{opacity:1}}',
      '.aleph-paywall{background:var(--paper,#141416);color:var(--ink,#F5F5F6);',
      'border:1px solid var(--line2,transparent);border-radius:12px;max-width:460px;width:100%;',
      'padding:22px 22px 18px;box-shadow:0 18px 60px rgba(0,0,0,.5);',
      'font:14px/1.55 var(--font-ui, "Hanken Grotesk", system-ui, sans-serif)}',
      '.aleph-paywall h3{margin:0 0 10px;font-size:15px;font-weight:500;',
      'color:var(--accent-deep,#B7B5F5);display:flex;gap:8px;align-items:center}',
      '.aleph-paywall p{margin:0 0 14px;color:var(--ink,#F5F5F6);opacity:.92}',
      '.aleph-paywall .aleph-pw-nota{font-size:12.5px;color:var(--muted,#A0A0A6);margin-bottom:16px}',
      '.aleph-paywall .aleph-pw-row{display:flex;gap:9px;justify-content:flex-end;flex-wrap:wrap}',
      '.aleph-paywall button{font:inherit;font-weight:500;border-radius:9px;padding:9px 15px;',
      'cursor:pointer;border:1px solid transparent}',
      '.aleph-pw-no{background:transparent;color:var(--muted,#A0A0A6);border-color:var(--line2,transparent)}',
      '.aleph-pw-no:hover{color:var(--ink,#F5F5F6)}',
      '.aleph-pw-si{background:var(--accent,#8D8BEE);color:#14142A}',
      '.aleph-pw-si:hover{background:var(--accent-deep,#B7B5F5)}',
      '.aleph-pw-si[disabled]{opacity:.6;cursor:progress}',
      '.aleph-pw-err{color:var(--amber,#C89329);font-size:12.5px;margin:10px 0 0}'
    ].join('');
    document.head.appendChild(s);
  }

  function cerrar() {
    var n = document.querySelector('.aleph-paywall-bg');
    if (n) n.remove();
  }

  async function mejorar(btn, err) {
    btn.disabled = true;
    btn.textContent = t('Abriendo el pago…', 'Opening checkout…');
    try {
      var r = await window.fetch('/v1/payments/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan: 'monthly' })
      });
      var d = await r.json().catch(function () { return {}; });
      if (r.ok && d.checkout_url) { window.location.href = d.checkout_url; return; }
      // Honesto: si el pago no se puede abrir, se DICE. Nada de fallar en silencio.
      err.textContent = (r.status === 401)
        ? t('Inicia sesión para poder mejorar tu plan.',
            'Sign in to upgrade your plan.')
        : t('No pudimos abrir el pago ahora mismo. Prueba de nuevo en un momento.',
            'We could not open checkout right now. Please try again in a moment.');
      btn.disabled = false;
      btn.textContent = t('Mejorar mi plan', 'Upgrade my plan');
    } catch (e) {
      err.textContent = t('No pudimos abrir el pago (sin conexión).',
                          'We could not open checkout (no connection).');
      btn.disabled = false;
      btn.textContent = t('Mejorar mi plan', 'Upgrade my plan');
    }
  }

  function mostrar(rechazo) {
    var ahora = Date.now();
    if (ahora - ULTIMO < 1200 || document.querySelector('.aleph-paywall-bg')) return;
    ULTIMO = ahora;
    estilos();

    // EL COPY ES EL DEL SERVIDOR. El fallback existe sólo por si un muro futuro
    // devuelve 402 sin mensaje — nunca para reemplazar el que sí viene.
    var mensaje = (rechazo && rechazo.error) ||
      t('Esta función es parte del plan Premium.',
        'This feature is part of the Premium plan.');

    var bg = document.createElement('div');
    bg.className = 'aleph-paywall-bg';
    bg.setAttribute('role', 'dialog');
    bg.setAttribute('aria-modal', 'true');
    bg.innerHTML =
      '<div class="aleph-paywall">' +
        '<h3>🔒 <span></span></h3>' +
        '<p class="aleph-pw-msg"></p>' +
        '<div class="aleph-pw-nota"></div>' +
        '<div class="aleph-pw-row">' +
          '<button class="aleph-pw-no"></button>' +
          '<button class="aleph-pw-si"></button>' +
        '</div>' +
        '<p class="aleph-pw-err"></p>' +
      '</div>';

    // textContent, no innerHTML: el mensaje viene del servidor y no se interpola
    // como markup ni aunque el servidor cambie mañana.
    bg.querySelector('h3 span').textContent = t('Esto necesita Premium', 'This needs Premium');
    bg.querySelector('.aleph-pw-msg').textContent = mensaje;
    bg.querySelector('.aleph-pw-nota').textContent = t(
      'Tu trabajo no se perdió: nada se ejecutó todavía.',
      'Your work is safe: nothing was executed.');
    var no = bg.querySelector('.aleph-pw-no');
    var si = bg.querySelector('.aleph-pw-si');
    no.textContent = t('Ahora no', 'Not now');
    si.textContent = t('Mejorar mi plan', 'Upgrade my plan');

    no.addEventListener('click', cerrar);
    bg.addEventListener('click', function (e) { if (e.target === bg) cerrar(); });
    document.addEventListener('keydown', function esc(e) {
      if (e.key === 'Escape') { cerrar(); document.removeEventListener('keydown', esc); }
    });
    si.addEventListener('click', function () {
      mejorar(si, bg.querySelector('.aleph-pw-err'));
    });

    document.body.appendChild(bg);
    si.focus();
  }

  // ── El interceptor ──────────────────────────────────────────────────────────
  var _fetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    return _fetch(input, init).then(function (resp) {
      if (resp && resp.status === 402) {
        // clone(): el cuerpo se lee UNA sola vez. Si lo consumiéramos acá, el
        // llamador recibiría un stream vacío y romperíamos su manejo de errores.
        resp.clone().json().then(function (body) {
          var d = (body && body.detail) || body || {};
          if (d.tier_gated) mostrar(d);
        }).catch(function () { /* 402 sin JSON: no es nuestro muro, se ignora */ });
      }
      return resp;   // la respuesta viaja INTACTA al llamador
    });
  };

  // Para que el SSE (dispatch.denied, que niega EN BANDA y nunca es un 402 HTTP)
  // pueda mostrar la misma card sin duplicar UI.
  window.alephMostrarPaywall = mostrar;
})();
