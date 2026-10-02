/* aleph-ds.js — Vertical Sliding Focus, el patrón de listas del sistema ALEPH.
 *
 * En una pista (.ds-track) exactamente UN elemento (.ds-item) está en foco: tamaño real,
 * tinte de mascota y sus acciones visibles. El resto retrocede a escala/opacidad de token
 * conservando nombre y metadato legibles. El control ^ˇ en cristal desliza el foco.
 *
 * INVARIANTE FUNCIONAL: esto cambia cómo se ALCANZAN las acciones, no cuáles son. Las
 * acciones del elemento en foco son exactamente las del original — no se agrega ni se
 * quita ninguna. Las de los elementos retrocedidos siguen en el DOM (para lectores de
 * pantalla y para que un submit programático siga funcionando); solo se las oculta
 * visualmente y se les quita el puntero.
 *
 * Uso mínimo:
 *   <div class="ds-well ds-track" data-ds-track>
 *     <div class="ds-card ds-item">… <div class="ds-actions">…</div></div>
 *     …
 *   </div>
 * El control ^ˇ se inyecta solo. API: window.AlephDS.{init,focus,refresh}.
 */
(function () {
  'use strict';

  var ATTR = 'data-ds-track';

  function items(track) {
    // solo los hijos directos marcados: una pista anidada no roba los elementos de la de afuera
    return Array.prototype.filter.call(
      track.querySelectorAll('.ds-item'),
      function (el) { return el.closest('[' + ATTR + ']') === track; }
    );
  }

  function apply(track, idx) {
    var list = items(track);
    if (!list.length) return;
    idx = Math.max(0, Math.min(idx, list.length - 1));
    track._dsIndex = idx;

    list.forEach(function (el, i) {
      var on = i === idx;
      el.setAttribute('data-focus', on ? '1' : '0');
      // el elemento retrocedido no es un destino de tabulación, pero SIGUE en el árbol
      // de accesibilidad: se lee, no se navega con Tab.
      el.setAttribute('aria-current', on ? 'true' : 'false');
      var act = el.querySelector('.ds-actions');
      if (act) {
        Array.prototype.forEach.call(
          act.querySelectorAll('button,a,input,select,textarea'),
          function (c) { if (on) { c.removeAttribute('tabindex'); } else { c.setAttribute('tabindex', '-1'); } }
        );
      }
    });

    // deslizar la pista para que el elemento en foco quede visible
    var el = list[idx];
    if (el && track.scrollHeight > track.clientHeight) {
      var top = el.offsetTop - (track.clientHeight - el.offsetHeight) / 2;
      track.scrollTo({ top: Math.max(0, top), behavior: prefersReduced() ? 'auto' : 'smooth' });
    }

    var s = track._dsSlider;
    if (s) {
      s.up.disabled = idx <= 0;
      s.down.disabled = idx >= list.length - 1;
    }
    track.dispatchEvent(new CustomEvent('ds:focus', { detail: { index: idx, item: el }, bubbles: true }));
  }

  function prefersReduced() {
    try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; }
  }

  function mkSlider(track) {
    if (track._dsSlider) return;
    var wrap = document.createElement('div');
    wrap.className = 'ds-slider ds-glass';
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', 'Deslizar el foco de la lista');

    function btn(glyph, label, delta) {
      var b = document.createElement('button');
      b.type = 'button'; b.textContent = glyph;
      b.setAttribute('aria-label', label);
      b.addEventListener('click', function (e) {
        e.preventDefault();
        apply(track, (track._dsIndex || 0) + delta);
      });
      return b;
    }
    var up = btn('⌃', 'Anterior', -1);
    var down = btn('ˇ', 'Siguiente', 1);
    wrap.appendChild(up); wrap.appendChild(down);
    track.appendChild(wrap);
    track._dsSlider = { el: wrap, up: up, down: down };
  }

  function wire(track) {
    if (track._dsWired) return;
    track._dsWired = true;
    mkSlider(track);

    // tocar un elemento retrocedido lo trae al foco; tocar el que ya está en foco no
    // interfiere con sus acciones (el handler mira si el click nació dentro de .ds-actions).
    track.addEventListener('click', function (e) {
      var it = e.target.closest ? e.target.closest('.ds-item') : null;
      if (!it || items(track).indexOf(it) === -1) return;
      if (e.target.closest('.ds-actions')) return;   // dejar pasar la acción real
      var i = items(track).indexOf(it);
      if (i !== track._dsIndex) { e.preventDefault(); apply(track, i); }
    });

    track.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); apply(track, (track._dsIndex || 0) + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); apply(track, (track._dsIndex || 0) - 1); }
      else if (e.key === 'Home') { e.preventDefault(); apply(track, 0); }
      else if (e.key === 'End') { e.preventDefault(); apply(track, items(track).length - 1); }
    });

    if (!track.hasAttribute('tabindex')) track.setAttribute('tabindex', '0');
    track.setAttribute('role', 'listbox');

    // Las listas del producto se pintan por fetch DESPUÉS del primer apply (Home carga los
    // agentes reales async y reemplaza la muestra). Sin esto, los elementos que llegan tarde
    // se quedan sin data-focus: ni en foco ni retrocedidos, o sea a tamaño completo todos —
    // que es exactamente lo contrario del patrón. Se re-aplica cuando cambian los hijos.
    if (window.MutationObserver) {
      var pend = null;
      new MutationObserver(function () {
        clearTimeout(pend);
        pend = setTimeout(function () {
          var list = items(track);
          var n = list.length;
          if (!n) return;
          // Mirar SOLO la cantidad no alcanza: un repintado que devuelve la MISMA cantidad de
          // filas (renderList() de Métodos, pintarLista() de Modelos, cualquier re-render con
          // innerHTML) trae nodos NUEVOS y sin data-focus. La pista quedaba muerta: todas las
          // filas a tamaño completo, ninguna en foco, y el patrón desaparecía en silencio.
          // Medido en Métodos: 4 items / 0 en foco / 4 sin atributo. Por eso se re-aplica
          // también cuando ALGUNA fila perdió su estado.
          var huerfanas = false;
          for (var i = 0; i < n; i++) { if (!list[i].hasAttribute('data-focus')) { huerfanas = true; break; } }
          if (n !== track._dsCount || huerfanas) {
            track._dsCount = n;
            apply(track, Math.min(track._dsIndex || 0, n - 1));
          }
        }, 30);
      }).observe(track, { childList: true, subtree: true });
    }

    var start = parseInt(track.getAttribute('data-ds-focus') || '0', 10);
    track._dsCount = items(track).length;
    apply(track, isNaN(start) ? 0 : start);
  }

  function init(root) {
    var scope = root || document;
    Array.prototype.forEach.call(scope.querySelectorAll('[' + ATTR + ']'), wire);
  }

  // las listas se pintan por fetch: re-enganchar cuando aparezcan pistas nuevas
  function observe() {
    if (!window.MutationObserver || !document.body) return;
    new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        var m = muts[i];
        for (var j = 0; j < m.addedNodes.length; j++) {
          var n = m.addedNodes[j];
          if (n.nodeType !== 1) continue;
          if (n.hasAttribute && n.hasAttribute(ATTR)) wire(n);
          if (n.querySelectorAll) init(n);
        }
      }
    }).observe(document.body, { childList: true, subtree: true });
  }

  function boot() { init(document); observe(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

  window.AlephDS = {
    init: init,
    refresh: function (track) { apply(track, track._dsIndex || 0); },
    focus: function (track, i) { apply(track, i); }
  };
})();
