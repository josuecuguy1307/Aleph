# La Sala (v2)

El chat base de Aleph sobre el que van a vivir todos los workspaces de Gate 4. Reemplaza a
`../sala/sala.html` como destino por defecto de «La Sala» en el nav — **sin borrarla**.

---

## Cómo volver a la Sala vieja

Tres caminos, del más chico al más grande. Los tres funcionan hoy.

**1 · Por preferencia (lo normal).** En la consola del navegador, o desde cualquier código
del producto:

```js
localStorage.setItem('aleph-sala', 'v1');   // el nav vuelve a apuntar a la vieja
localStorage.removeItem('aleph-sala');      // vuelve a la nueva (default)
```

Con el flag puesto, además, entrar a `sala-v2/sala-v2.html` redirige solo a la vieja: un
enlace guardado no te deja atrapado en la pantalla que pediste no usar.
`?v2=1` fuerza quedarse en la nueva aunque el flag esté (es lo que usa la vara).

**2 · Escribiendo la ruta.** `sala/sala.html` **siempre** está servida y entera. No depende
de que ninguna función corra bien: si el flag se rompe, la URL sigue existiendo.

**3 · Revertir el swap del todo.** Una línea en `../nav.js`:

```js
var salaId = SALA_V1;   // en vez del ternario que lee el flag
```

Y si hay que revertir la fase completa: `git revert` del commit del swap. La Sala vieja no
se movió ni un archivo, así que no hay nada que restaurar.

## Qué NO se borró

Nada. `../sala/` sigue con sus 6.485 líneas, sus 24 varas y sus screenshots. La Sala vieja
es el fallback y va a seguir siéndolo hasta que la v2 esté certificada un tiempo — esa
decisión es de persona usuaria, no de esta fase.

---

## Cómo está armado

```
sala-v2.html          la pantalla (documento aparte, como las otras 9)
sala-v2.css           la piel: SÓLO tokens de ../aleph-tokens.css, cero color literal
sala-v2.js            el arranque: junta runtime + adaptador + máquina de estados
agui/
  envelope.js         lee el sobre de Gate 3 (los dos streams SSE) y lo normaliza
  aleph-agent.js      EL ADAPTADOR: la tabla de mapeo Aleph → AG-UI, caso por caso
  estados.js          los 7 estados en vivo, derivados de eventos AG-UI y de nada más
ui/
  hilo.js             el hilo y el composer (primitivas de assistant-ui + piel Aleph)
  gate-card.js        la tarjeta de consentimiento — CONECTADA a Ó11, no reconstruida
  sidebar.js          la navegación nueva; «Chats» disuelto adentro de La Sala
vendor/
  assistant-ui.bundle.js            GENERADO — no editar
  assistant-ui.bundle.js.sri        su sha384
  assistant-ui.bundle.manifest.json qué versiones y licencias viajan adentro
verify/
  humo.mjs            ¿arranca? (bundle íntegro · monta · composer usable)
```

**El código de Aleph no pasa por ningún build.** Es ESM plano servido tal cual: se edita y
se recarga. El único artefacto construido es `vendor/assistant-ui.bundle.js`, y sólo se
regenera al subir de versión a un tercero:

```sh
cd tools/sala-v2-build && npm install && npm run build
```

## La regla que gobierna esta carpeta

El backend de Gate 1-3 **no cambió**. Esta pantalla consume exactamente los mismos endpoints
que la Sala vieja (`/v1/puppets/run`, `/v1/puppets/run/stream`, `/v1/spaces/{id}/stream`,
`/v1/runs/{id}/approve`, `/v1/chats`). Todo lo nuevo es traducción en el borde.
