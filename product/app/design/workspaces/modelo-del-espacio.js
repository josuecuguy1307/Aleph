/* modelo-del-espacio.js — LA CASA LE DA DE COMER AL CHIP QUE VIVE EN EL COMPOSER DEL STACK.
 * [convergencia · un solo picker en las siete · decisión del dueño 2026-08-22]
 *
 * ═══ QUÉ ES ESTO, Y QUÉ NO ES ═════════════════════════════════════════════════════════
 * NO pinta ningún picker. La primera versión de este archivo montaba un panel en la barra
 * del workspace y el dueño lo rechazó con razón: **el usuario mira el composer, no la
 * franja de arriba**, y un panel a página completa con filas gigantes no es el widget de la
 * Sala — es otro widget que se le parece. El picker es UNO y es el chip compacto del
 * composer (`product/app/design/ui/model-chip.core.js`), el mismo que pinta la Sala.
 *
 * Ese chip no puede vivir acá: el composer está adentro del `iframe` del stack, que es otro
 * origen. Así que el chip se monta ADENTRO del stack, desde su propio script de Aleph, y
 * este archivo es lo único que puede estar de este lado — **el que tiene la sesión del
 * dueño**. El reparto es:
 *
 *     la casa (acá)          el stack (`aleph-picker-unico.js`)
 *     ─────────────────      ─────────────────────────────────────
 *     trae el catálogo   →   pinta el chip con el núcleo compartido
 *     valida y persiste  ←   avisa qué eligió el usuario
 *     avisa el cambio    →   repinta
 *
 * Ni el catálogo ni la sesión cruzan al stack: lo que baja son FILAS DE VITRINA
 * (`selection_ref`, label, marca, ventana, costo) — el mismo recorte público que la Sala le
 * pasa a su chip, sin `provider`/`model` ejecutable, sin URL y sin secretos.
 *
 * ═══ EL CANDADO QUE SE ABRIÓ, Y CON QUÉ SE COMPENSA ═══════════════════════════════════
 * La fase 5 selló que «lo único que el stack puede pedir es ABRIR UN PANEL NUESTRO — no hay
 * ninguna acción con consecuencia detrás de este mensaje». Acá SÍ hay una: elegir el
 * cerebro. Es deliberado, y se compensa con la única defensa que sirve:
 *
 *   · el `selection_ref` que manda el stack tiene que ser UNO DE LOS QUE LA CASA LE MANDÓ.
 *     No se busca en el catálogo entero: se busca en la lista que este módulo acaba de
 *     bajarle. Un stack no puede elegir algo que no le ofrecimos, ni inventar un id.
 *   · sigue sin poder tocar una llave, ni leer una, ni pedir nada más.
 *   · y sigue vigente el candado del emisor: sólo el `contentWindow` de NUESTRO `#ws-frame`.
 *
 * ═══ LO QUE NO HUBO QUE CONSTRUIR ═════════════════════════════════════════════════════
 *   · `AlephModelSelector.load/options/persist` — el catálogo y la escritura a la fuente
 *     única (`preferencias-v2.default`), que es lo que los siete leen.
 *   · `aleph:model-selection` + BroadcastChannel `aleph-modelos-v2` — el despertador entre
 *     superficies, que `brain-status.js:613` ya publica.
 *   · el chip mismo, que es el de la Sala.
 */
(function () {
  "use strict";

  window.AlephModeloDelEspacio = {
    /** @param ws  el id del workspace (el mismo que usan los otros dos paneles de la barra) */
    montar: function (ws) {
      var frame = document.getElementById("ws-frame");
      if (!frame) return;
      //: las filas que se le bajaron al stack en el último envío. Es contra ESTA lista que
      //: se valida lo que sube — no contra el catálogo entero.
      var ofrecidas = [];

      /* `brain-status.js` no llega solo acá: las anfitrionas prenden `ALEPH_NAV_BRAIN_OFF`,
       * así que `nav.js::ensureBrain` nunca lo pide. Se carga una vez, con el MISMO evento
       * de listo que usa `nav.js`, para que no termine cargado dos veces. */
      function conBrain(cb) {
        if (window.AlephModelSelector) { cb(); return; }
        if (window.__alephBrainLoading) {
          document.addEventListener("aleph:brain-script-ready", function once() {
            document.removeEventListener("aleph:brain-script-ready", once);
            cb();
          });
          return;
        }
        window.__alephBrainLoading = true;
        var s = document.createElement("script");
        s.src = "../brain-status.js";
        s.onload = function () {
          try { document.dispatchEvent(new CustomEvent("aleph:brain-script-ready")); } catch (e) {}
          cb();
        };
        s.onerror = function () {};   // sin catálogo el stack se queda con su chip mudo, y lo dice él
        document.head.appendChild(s);
      }

      /** El recorte PÚBLICO de una fila del selector, con la forma que el chip espera.
       *
       * ⚠️ ES EL MISMO RECORTE QUE LA SALA LE PASA AL SUYO (`sala-v2.js::cargarChoices`), y
       * eso no es prolijidad: el chip es UNO, así que si acá se le mandara otra forma el
       * mismo componente pintaría distinto en un workspace que en la Sala. `provider` acá es
       * la MARCA (`marca`/`familia`), no el proveedor ejecutable. */
      function vitrina(m) {
        return {
          selection_ref: String(m.picker_id || m.id || m.slug),
          label: String(m.label || m.picker_id || m.slug),
          provider: String(m.marca || m.familia || "Aleph"),
          tier: m.tier || null,
          capabilities: m.model_use_capabilities || m.capacidades || [],
          context_window: m.context_window || null,
          cost: m.cost || null,
        };
      }

      /** Baja el catálogo y la elección. Sin `todos`: al stack le van las que se PUEDEN USAR.
       *
       * ⚠️ ACÁ SÍ VA EL POOL Y NO `todos=1`, y es la diferencia con el panel que se descartó.
       * El chip del composer es para ELEGIR, no para configurar: ofrecer ahí una API sin
       * llave sería el verde falso otra vez (el usuario la elige, el turno se estrella). El
       * trámite de poner una llave tiene su lugar, y es Conectores — a donde lleva la fila
       * «＋ Añadir otro modelo» que el propio chip trae. Es la misma ley que sacó el campo de
       * llave de las filas del selector compartido. */
      function bajar() {
        var AMS = window.AlephModelSelector;
        if (!AMS || !frame.contentWindow) return;
        AMS.load(ws, false, false).then(function () {
          var d = AMS.data(ws, false) || {};
          var lista = AMS.options({ contexto: ws, data: d })
            .filter(function (m) { return m.conectado === true || m.connected === true; })
            .map(vitrina);
          ofrecidas = lista;
          var pref = String(d["default"] || "");
          var fila = (d.modelos || []).find(function (m) { return m && m.slug === pref; });
          try {
            frame.contentWindow.postMessage({
              aleph: "modelo-catalogo",
              choices: lista,
              selectedRef: fila ? String(fila.picker_id || fila.id || fila.slug) : null,
            }, "*");
          } catch (e) {}
        }).catch(function () {});
      }

      /* ── LO QUE SUBE DEL STACK ────────────────────────────────────────────────────────
       * Dos mensajes y nada más. El candado del emisor es el de la fase 5 y no se afloja:
       * `ev.source` tiene que ser EXACTAMENTE el `contentWindow` de nuestro frame — un
       * `ev.origin` no alcanza, porque cualquier ventana puede postear a ésta. */
      window.addEventListener("message", function (ev) {
        if (!frame.contentWindow || ev.source !== frame.contentWindow) return;
        var d = ev.data;
        if (!d) return;

        // 1) «ya enganché, mandame el catálogo». Sin consecuencia.
        if (d.aleph === "modelo?") { conBrain(bajar); return; }

        // 2) «el usuario eligió esto». LA ÚNICA acción con consecuencia, y va validada
        //    contra lo que ESTE módulo le ofreció — no contra el catálogo entero.
        if (d.aleph === "modelo-elegir") {
          var ref = String(d.ref || "");
          if (!ofrecidas.some(function (m) { return m.selection_ref === ref; })) return;
          var AMS = window.AlephModelSelector;
          if (!AMS) return;
          var m = AMS.options({ contexto: ws, data: AMS.data(ws, false) })
                     .find(function (x) { return String(x.picker_id || x.id || x.slug) === ref; });
          if (!m) return;
          // `persist` escribe `preferencias-v2.default` —la fuente que los siete leen— y
          // dispara el evento/BroadcastChannel que despierta a las otras superficies.
          AMS.persist(ws, m);
          return;
        }
      });

      /* El frame carga DESPUÉS que este script, así que el primer envío le llegaría a una
       * ventana que todavía no enganchó. Dos caminos para el mismo hecho, porque el orden de
       * carga no está bajo control de ninguno de los dos: su `load` de este lado, y el
       * `modelo?` que el stack manda por su cuenta al arrancar. */
      frame.addEventListener("load", function () { conBrain(bajar); });

      /* El cerebro cambió en OTRA superficie (la Sala, otra pestaña, otro workspace). El
       * chip del stack está afirmando el viejo: se le vuelve a bajar el estado. */
      window.addEventListener("aleph:model-selection", function () { conBrain(bajar); });
    },
  };
})();
