"""
capture/events.py — captura selector + valor de clicks/inputs durante la demo.

Inyecta un init-script que escucha clicks/inputs/changes/submits en captura y los
reenvía a Python vía un binding expuesto. Esto da la SEÑAL HUMANA: qué campos se
tipearon y con qué valor — la pista para que correlate aísle la request real.

REDACCIÓN: los inputs type=password (o con nombre con pinta de secreto) se
reportan con value=null. El password crudo JAMÁS sale del navegador.
"""
from __future__ import annotations

import time

from inspection.models import ObservedEvent, looks_secret_name

_BINDING = "__aleph_record"

_INIT_SCRIPT = r"""(() => {
  if (window.__alephHooked) return;
  window.__alephHooked = true;
  function cssPath(el) {
    if (!(el instanceof Element)) return '';
    if (el.id) return '#' + CSS.escape(el.id);
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && parts.length < 5) {
      let sel = cur.nodeName.toLowerCase();
      const nm = cur.getAttribute && cur.getAttribute('name');
      if (nm) { parts.unshift(sel + '[name="' + nm + '"]'); break; }
      let nth = 1, sib = cur;
      while ((sib = sib.previousElementSibling) != null) {
        if (sib.nodeName === cur.nodeName) nth++;
      }
      parts.unshift(sel + ':nth-of-type(' + nth + ')');
      cur = cur.parentElement;
    }
    return parts.join(' > ');
  }
  function send(type, el, extra) {
    try {
      window.__aleph_record(Object.assign({
        type: type,
        selector: cssPath(el),
        tag: el.tagName ? el.tagName.toLowerCase() : null,
      }, extra || {}));
    } catch (e) {}
  }
  document.addEventListener('click', e =>
    send('click', e.target, { text: (e.target.innerText || e.target.value || '').slice(0, 80) }), true);
  function onInput(e) {
    const el = e.target;
    const t = (el.type || '').toLowerCase();
    const nm = (el.getAttribute && el.getAttribute('name')) || '';
    const secret = t === 'password' || /pass|secret|token|cvv|card|otp/i.test(nm);
    send(e.type, el, { input_type: t, value: secret ? null : (el.value || '').slice(0, 300) });
  }
  document.addEventListener('input', onInput, true);
  document.addEventListener('change', onInput, true);
  document.addEventListener('submit', e => send('submit', e.target, {}), true);
})();"""


class EventRecorder:
    def __init__(self):
        self.events: list[ObservedEvent] = []
        self._page = None

    async def attach(self, ctx_or_page) -> None:
        """Debe llamarse ANTES de navegar al target (el init-script corre por documento)."""
        page = getattr(ctx_or_page, "page", ctx_or_page)
        self._page = page
        try:
            await page.expose_binding(_BINDING, self._on_record)
        except Exception:
            pass  # ya expuesto (re-attach)
        await page.add_init_script(_INIT_SCRIPT)

    def _on_record(self, source, payload) -> None:
        try:
            value = payload.get("value")
            name = (payload.get("selector") or "")
            # defensa extra server-side: si el nombre/selector huele a secreto, redacta
            if value is not None and looks_secret_name(name):
                value = None
            self.events.append(ObservedEvent(
                type=payload.get("type", "?"),
                selector=payload.get("selector", ""),
                ts=time.time(),
                value=value,
                tag=payload.get("tag"),
                input_type=payload.get("input_type"),
                text=payload.get("text"),
            ))
        except Exception:
            pass
