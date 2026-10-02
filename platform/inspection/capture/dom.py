"""
capture/dom.py — page.accessibility.snapshot() + DOM relevante (forms/inputs/botones).

Da el contexto estructural de la pantalla: qué formularios e inputs existen y qué
botones disparan acciones. Sirve para enriquecer el schema de campos (nombres,
required, tipos) y para que el Cuarto, en FASE 2, sepa qué "software" apareció.
Sin visión: todo es estructura del DOM + árbol de accesibilidad.
"""
from __future__ import annotations

import time

from inspection.models import DomSnapshot

# JS que extrae forms/inputs/botones relevantes (serializable, sin ciclos).
_EXTRACT_JS = r"""() => {
  const forms = [...document.forms].map(f => ({
    action: f.getAttribute('action') || '',
    method: (f.getAttribute('method') || 'get').toLowerCase(),
    id: f.id || null,
    inputs: [...f.querySelectorAll('input,select,textarea')].map(el => ({
      name: el.getAttribute('name') || null,
      id: el.id || null,
      type: (el.getAttribute('type') || el.tagName.toLowerCase()),
      required: el.required || false,
      placeholder: el.getAttribute('placeholder') || null,
    })),
  }));
  const buttons = [...document.querySelectorAll('button,input[type=submit],[role=button]')]
    .slice(0, 40)
    .map(b => ({
      text: (b.innerText || b.value || '').trim().slice(0, 60),
      type: (b.getAttribute('type') || '').toLowerCase() || null,
      id: b.id || null,
      name: b.getAttribute('name') || null,
    }));
  return { forms, buttons };
}"""


async def snapshot_dom(page, *, with_a11y: bool = True) -> DomSnapshot:
    url = page.url
    try:
        title = await page.title()
    except Exception:
        title = ""
    forms, buttons = [], []
    try:
        data = await page.evaluate(_EXTRACT_JS)
        forms = data.get("forms", [])
        buttons = data.get("buttons", [])
    except Exception:
        pass
    a11y = None
    if with_a11y:
        try:
            a11y = await page.accessibility.snapshot()
        except Exception:
            a11y = None
    return DomSnapshot(
        url=url, title=title, forms=forms, buttons=buttons,
        accessibility=a11y, captured_at=time.time(),
    )
