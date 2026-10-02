/**
 * In-iframe bridge for live EDITMODE token updates.
 *
 * Without this, every token edit forced a full srcdoc reload or a full JSX
 * recompilation — re-mounting React, re-initialising Babel, and re-running the
 * agent script (~300-500ms blank flash).
 *
 * With this, the host posts `{type: 'codesign:tweaks:update', tokens}` to the
 * iframe. The bridge updates the runtime-owned token object, maps primitives to
 * canonical CSS custom properties, and asks the already-compiled artifact runner
 * to render again on the next animation frame. Slider/color changes no longer
 * pay the Babel compilation cost on every tick.
 *
 * Bundled as a string at build time; injected by `wrapJsxAsSrcdoc`.
 */

export const TWEAKS_BRIDGE_SETUP = `(function() {
  'use strict';
  if (!window.ReactDOM || typeof window.ReactDOM.createRoot !== 'function') return;
  var EDITMODE_RE = /\\/\\*\\s*EDITMODE-BEGIN\\s*\\*\\/[\\s\\S]*?\\/\\*\\s*EDITMODE-END\\s*\\*\\//;
  var state = {
    root: null,
    tokens: {},
    runner: null,
    renderPending: false
  };
  var origCreateRoot = window.ReactDOM.createRoot;
  window.ReactDOM.createRoot = function(el) {
    if (state.root) return state.root;
    var root = origCreateRoot.call(this, el);
    state.root = root;
    return root;
  };
  function toKebab(key) {
    return String(key)
      .replace(/([a-z0-9])([A-Z])/g, '$1-$2')
      .replace(/[_\\s]+/g, '-')
      .replace(/[^A-Za-z0-9-]/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '')
      .toLowerCase();
  }
  function cssValue(value) {
    if (typeof value === 'string' || typeof value === 'number') return String(value);
    if (typeof value === 'boolean') return value ? '1' : '0';
    return null;
  }
  function applyCssVars(tokens) {
    if (!tokens || typeof tokens !== 'object') return false;
    var root = document.documentElement;
    for (var key in tokens) {
      if (!Object.prototype.hasOwnProperty.call(tokens, key)) continue;
      var name = toKebab(key);
      var value = cssValue(tokens[key]);
      if (!name || value === null) continue;
      root.style.setProperty('--ocd-tweak-' + name, value);
    }
    return true;
  }
  function replaceTokens(tokens) {
    for (var existing in state.tokens) {
      if (Object.prototype.hasOwnProperty.call(state.tokens, existing)) delete state.tokens[existing];
    }
    if (tokens && typeof tokens === 'object') {
      for (var key in tokens) {
        if (Object.prototype.hasOwnProperty.call(tokens, key)) state.tokens[key] = tokens[key];
      }
    }
    applyCssVars(state.tokens);
  }
  function parseInitialTokens(source) {
    var match = String(source || '').match(EDITMODE_RE);
    if (!match) return null;
    var body = match[0]
      .replace(/^\\/\\*\\s*EDITMODE-BEGIN\\s*\\*\\//, '')
      .replace(/\\/\\*\\s*EDITMODE-END\\s*\\*\\/$/, '')
      .trim();
    if (!body) return {};
    return JSON.parse(body);
  }
  function scheduleRender() {
    if (state.renderPending || typeof state.runner !== 'function') return;
    state.renderPending = true;
    var raf = window.requestAnimationFrame || function(cb) { return setTimeout(cb, 0); };
    raf(function() {
      state.renderPending = false;
      state.runner();
    });
  }
  window.__codesign_tweaks__ = {
    tokens: state.tokens,
    applyCssVars: applyCssVars,
    applyTokens: function(tokens) {
      replaceTokens(tokens);
      scheduleRender();
    },
    applyInitial: function(source) {
      replaceTokens(parseInitialTokens(source));
    },
    registerRunner: function(runner) {
      state.runner = runner;
    }
  };
})();`;

export const TWEAKS_BRIDGE_LISTENER = `(function() {
  'use strict';
  if (!window.__codesign_tweaks__ || typeof window.__codesign_tweaks__.applyTokens !== 'function') return;
  window.addEventListener('message', function(event) {
    var data = event && event.data;
    if (!data || data.type !== 'codesign:tweaks:update') return;
    if (!data.tokens || typeof data.tokens !== 'object') return;
    window.__codesign_tweaks__.applyTokens(data.tokens);
  });
})();`;
