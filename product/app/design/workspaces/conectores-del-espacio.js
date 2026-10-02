/* LOS CONECTORES DE ESTE ESPACIO · la vista que el usuario va a usar de verdad.
 *
 * POR QUÉ ES UN PANEL DE LA BARRA Y NO UNA SECCIÓN DEL LIENZO. El lienzo de un workspace es
 * ENTERO un `iframe` del stack: no hay lugar «debajo» que no sea robarle espacio a la pieza
 * ajena. Lo único que es de la casa en esta pantalla es la barra de arriba, así que la
 * entrada vive ahí y el panel se abre encima. El stack sigue siendo dueño de su lienzo.
 *
 * ⚠️ LEE EL MISMO ENDPOINT QUE LA VISTA GENERAL DE CONECTORES — `GET /v1/connectors?
 * workspace=<ws>` — y eso no es economía: es la garantía del cruce. Si esta vista resolviera
 * su propia lista, configurar `github` acá podría verse «sin configurar» en Conectores, o al
 * revés, y la cara estaría mintiendo sobre un destino que es UNO. Un destino, N vistas.
 *
 * La Lista A sale de `GET /v1/workspaces`, que ya sirve las fuentes por workspace.
 */
import { pintarFilaReco, esc, estado as estadoDe, selloDe, capacidad } from "../conectores/recomendados.js";
import { traerRecomendados, traerFuentesPorEspacio } from "../conectores/recomendaciones.js";

/* ⚠️ ESTE PANEL YA NO REIMPLEMENTA NADA. Antes tenía copias de `capacidad()`, `pide()`,
 * `esc()` y del markup de la fila — y por eso arrastró el mismo defecto de OAuth que la vista
 * general, porque lo copié de mí mismo. Ahora importa el render y las reglas de texto, y lo
 * único propio es la FORMA de esta vista: el panel de la barra y cómo cuenta el cruce. */
(function () {
  "use strict";

  function tr(key, fallback, vars) {
    var value = window.AlephI18n && window.AlephI18n.t ? window.AlephI18n.t(key, vars) : key;
    return value && value !== key ? value : fallback;
  }



  window.AlephConectoresDelEspacio = {
    /** @param ws  el id del workspace · @param usuario  función que devuelve {id} o null */
    montar: function (ws, usuario) {
      var barra = document.querySelector(".ws-bar");
      /* [Finanzas · el nudo de las dos barras] LA BARRA DEJÓ DE SER OBLIGATORIA. Antes, sin
       * `.ws-bar`, este módulo no montaba NADA — y con él se caía también el puente de acá
       * abajo, por el que el stack pide sus conectores. Con el shell único la barra de la
       * casa desaparece, así que el PANEL se arma siempre y el BOTÓN sólo si hay dónde
       * ponerlo. Nada de lo que hace cambia. */

      var boton = document.createElement("button");
      boton.type = "button";
      boton.className = "ws-conect-entrada";
      boton.textContent = tr("ws.connectors.button", "Conectores");
      boton.setAttribute("aria-expanded", "false");

      var panel = document.createElement("section");
      panel.className = "ws-conect-panel";
      panel.hidden = true;
      panel.setAttribute("aria-label", tr("ws.connectors.aria", "Conectores de este espacio"));

      // La entrada va ANTES del estado, que es el que crece: así el botón no se mueve cuando
      // el pack pasa de «arrancando» a «listo».
      if (barra) {
        var estado = barra.querySelector("#ws-estado");
        if (estado) barra.insertBefore(boton, estado); else barra.appendChild(boton);
      }
      document.body.appendChild(panel);

      var traido = false;
      //: por qué se abrió el panel. `null` = lo abrió el usuario desde la barra.
      //: "credencial" = lo mandó el stack porque el usuario fue a poner una llave adentro.
      //: Regla sellada: ninguna causa llega a una superficie sin copy — el copy de ésta se
      //: pinta en `traer()`, no acá, porque acá todavía no hay panel dibujado.
      var motivo = null;

      function cerrar() {
        panel.hidden = true;
        boton.setAttribute("aria-expanded", "false");
      }

      async function traer() {
        // ⚠️ `get()` NO ALCANZA: en un equipo sin sesión previa devuelve null y el panel se
        // queda en «no sé» para siempre. Aleph es local-first — `ensureLocal()` pide
        // `POST /v1/auth/local` (identidad de ESTE equipo, sin cuenta y sin red externa) y la
        // persiste. Sin esta línea, el estado nunca se sabe y el usuario no entiende por qué.
        var u = null;
        try {
          var A = window.AlephSession;
          u = (A && A.ensureLocal) ? await A.ensureLocal() : (usuario ? usuario() : null);
        } catch (e) { u = usuario ? usuario() : null; }
        var uid = u && u.id ? u.id : null;
        // El token ya no se guarda acá: `recomendaciones.js` lo resuelve con
        // `fuentes.cabeceras()`, que es el único lugar donde la casa arma la autorización.
        panel.innerHTML = "<p class='ws-conect-copy'>" + esc(tr("ws.connectors.loading", "Buscando…")) + "</p>";
        // ⚠️ LAS DOS LECTURAS SALEN DE `recomendaciones.js`, LA MISMA QUE USA LA VISTA
        // GENERAL. Acá estaban copiadas —con su propio armado de `Authorization`, su propio
        // manejo del no-ok y su propio parseo—, y eso no era economía perdida: era la
        // garantía del cruce. Dos lectores del mismo endpoint es cómo `github` puede verse
        // «sin configurar» en una pantalla y configurado en la otra, en el mismo instante.
        var d = await traerRecomendados(ws, uid);
        if (!d || d.error) {
          var causa = (d && d.error && d.error.causa) || "";
          var http = (d && d.error && d.error.http) || 0;
          panel.innerHTML = "<p class='ws-conect-copy'>" + esc(tr("ws.connectors.load_error", "No pude traer los conectores de este espacio"))
            + (causa ? ": " + esc(window.AlephI18n && window.AlephI18n.text ? window.AlephI18n.text(causa) : causa) : (http ? " (HTTP " + http + ")" : ": " + esc(tr("ws.connectors.no_response", "no hubo respuesta")))) + ".</p>";
          return;
        }
        var mapa = await traerFuentesPorEspacio();
        var fuentes = mapa ? (mapa[ws] || []) : null;   // `null` = no se pudo leer, no «cero»

        var todos = d.connectors || [];
        var conAccion = todos.filter(function (c) { return String(c.auth_method || "").toLowerCase() !== "keyless"; });
        var sinAccion = todos.filter(function (c) { return String(c.auth_method || "").toLowerCase() === "keyless"; });

        var filas = conAccion.map(function (c) {
          var puesta = c.tiene_llave === true;
          var probada = c.verificado === true;
          var esOauth = String(c.auth_method || "").toLowerCase() === "oauth";
          // ⚠️ ACÁ HABÍA UNA COPIA DE LA DECISIÓN, y era la misma falla de duplicación que ya
          // me costó romper OAuth: dos derivadores del mismo estado son dos formas de que la
          // misma llave se lea distinto según la pantalla. Se llama al de la vista general.
          var e = estadoDe(c);
          var etiqueta = puesta ? e.txt
            : (c.tiene_llave === false ? (esOauth ? tr("ws.connectors.oauth", "Pide autorizar tu cuenta") : tr("ws.connectors.key", "Pide tu llave")) : "");
          var sello = puesta ? selloDe(e) : "";
          var otros = (c.workspaces || []).filter(function (w) { return w !== ws; });
          // LOS DOS VAN A CONECTORES. El `oauth/start` es un POST con sesión que devuelve URL o
          // motivo (medido), así que no es un enlace: es un trámite. Acá se VE; el trámite
          // vive en un solo lugar, que es lo mismo que se le sacó a Ajustes.
          var accion = (c.tiene_llave === false)
            ? (esOauth
                ? "<a class='ws-btn' href='../Conectores.dc.html'>" + esc(tr("ws.connectors.authorize", "Autorizar")) + "</a>"
                : "<a class='ws-btn' href='../Conectores.dc.html'>" + esc(tr("ws.connectors.add_key", "Poner mi llave")) + "</a>")
            : "";
          return pintarFilaReco(c, {
            etiqueta: etiqueta, listo: puesta ? "si" : "no",
            // La MISMA regla que la vista general, llamada y no copiada: el «Listo —» entra
            // con el veredicto verde, nunca con el guardado.
            capacidad: capacidad(c.capability_line_i18n || c.capability_line, probada),
            cruzaTxt: [sello, otros.length ? tr(otros.length === 1 ? "ws.connectors.shared_one" : "ws.connectors.shared_many",
                       "Se configura una vez y vale en " + otros.length + (otros.length === 1 ? " espacio más." : " espacios más."), {n: otros.length}) : ""]
                      .filter(Boolean).join(" "),
            accion: accion, clase: "ws-conect-fila",
          });
        }).join("");

        var nombres = null;
        if (fuentes) {
          nombres = fuentes.filter(function (f) {
            var k = String(f.key == null ? "none" : f.key).toLowerCase();
            return k === "none" || k === "keyless";
          }).map(function (f) { return f.label || f.id; })
            .concat(sinAccion.map(function (c) { return c.connector || c.slug; }));
        }

        panel.innerHTML =
          "<div class='ws-conect-head'><strong>" + esc(tr("ws.connectors.aria", "Conectores de este espacio")) + "</strong>"
          + "<span class='ws-conect-ambito'>" + esc((ws || "").toUpperCase()) + "</span>"
          + "<button type='button' class='ws-btn' data-cerrar='1'>" + esc(tr("ws.connectors.close", "Cerrar")) + "</button></div>"
          // EL PORQUÉ, cuando el usuario no vino por su cuenta. Sin esta línea el panel
          // aparece solo y parece un error; con ella es una respuesta a lo que acaba de
          // hacer. No dice «no podés»: dice dónde sí, y por qué le conviene.
          + (motivo === "credencial"
              ? "<p class='ws-conect-copy ws-conect-motivo'>" + tr("ws.connectors.credential_reason", "Tus llaves se guardan <strong>aquí</strong>, no adentro del espacio. Así valen para todos los espacios que las usan y quedan en tu registro de gasto. Ponla una vez y listo.") + "</p>"
              : "")
          + (uid ? "" : "<p class='ws-conect-copy'>" + esc(tr("ws.connectors.no_session", "No pude abrir la sesión local de este equipo, así que no sé cuáles ya tienes configuradas.")) + "</p>")
          + "<p class='ws-conect-copy'><strong>" + esc(tr("ws.connectors.needs_action", "Estos te piden algo una vez:")) + "</strong> " + esc(tr("ws.connectors.needs_action_detail", "tu llave o autorizar tu cuenta.")) + "</p>"
          + "<ul class='ws-conect-lista'>" + (filas || "<li class='ws-conect-fila'>" + esc(tr("ws.connectors.none", "Este espacio no tiene conectores recomendados.")) + "</li>") + "</ul>"
          + "<p class='ws-conect-copy'><strong>" + esc(tr("ws.connectors.keyless", "Estas no te piden nada")) + "</strong>"
          + (nombres ? " (" + nombres.length + ")" : "") + ": " + esc(tr("ws.connectors.ready", "ya están andando.")) + "</p>"
          + "<p class='ws-conect-lista-a'>"
          + (nombres === null
              ? esc(tr("ws.connectors.ready_error", "No pude leer qué hay listo en este espacio."))
              : (nombres.length ? esc(nombres.join(" · ")) : esc(tr("ws.connectors.ready_none", "Todavía no hay nada listo sin configurar aquí."))))
          + "</p>"
          // NO SE DUPLICA LA GESTIÓN. Poner la llave se hace en UN lugar; acá se ve y se va
          // para allá. Dos formularios sobre el mismo destino es lo que Ajustes acaba de
          // dejar de hacer.
          + "<p class='ws-conect-copy'><a class='ws-btn' href='../Conectores.dc.html'>" + esc(tr("ws.connectors.configure", "Configurar en Conectores")) + "</a></p>";
      }

      /* ABRIR EL PANEL. Estaba adentro del handler del botón; sale porque ahora tiene un
       * segundo llamador —el stack, por el puente— y dos formas de abrir la misma cosa es
       * cómo se llega a que una se actualice y la otra no. Una sola. */
      async function abrir(porque) {
        var cambio = (porque || null) !== motivo;
        motivo = porque || null;
        panel.hidden = false;
        boton.setAttribute("aria-expanded", "true");
        // Si ya estaba traído pero el MOTIVO cambió, hay que repintar: el aviso de la
        // redirección es parte del contenido, no un adorno encima.
        if (!traido || cambio) { traido = true; await traer(); }
      }

      async function alternar() {
        if (!panel.hidden) { cerrar(); return; }
        await abrir(null);
      }
      boton.addEventListener("click", alternar);
      /* Mismo cuerpo para el botón de la barra y para el disparador que ahora vive adentro
       * del stack. `abrir` ya era el punto único; esto sólo le pone nombre al gesto. */
      window.AlephConectoresDelEspacio.alternar = alternar;

      /* ── LA VUELTA DEL PUENTE: el stack pide abrir esto ──────────────────────────────
       * [Convergencia · superficie 3 · fase 5] La casa YA le hablaba al iframe
       * (`postMessage({type:"aleph-theme"})`). Faltaba la vuelta. El stack la usa cuando el
       * usuario toca SU puerta de credencial: en vez de dejarlo pegar una llave que quedaría
       * fuera del vault y fuera del ledger, lo trae acá, a los conectores DE ESTE ESPACIO.
       *
       * ⚠️ EL LISTENER VIVE ACÁ Y NO EN LAS SEIS ANFITRIONAS. Las seis ya cargan este
       * archivo, así que ponerlo acá les llega a todas con una sola copia. Escribirlo seis
       * veces sería seis lugares donde arreglar la validación de origen.
       *
       * ⚠️ LO QUE LLEGA DEL IFRAME ES UN DATO, NO UNA ORDEN.
       *   · se exige que el emisor sea EXACTAMENTE el contentWindow de NUESTRO `#ws-frame`;
       *     un `ev.origin` suelto no alcanza, y cualquier ventana puede postear a ésta.
       *   · el `ws` que mande el stack SE IGNORA: el espacio lo sabe la casa (`montar(ws)`).
       *     Si se lo creyéramos, un stack podría abrir los conectores de otro espacio.
       *   · lo único que puede pedir es ABRIR UN PANEL NUESTRO. No hay ninguna acción con
       *     consecuencia detrás de este mensaje.
       */
      window.addEventListener("message", function (ev) {
        var frame = document.getElementById("ws-frame");
        if (!frame || !frame.contentWindow || ev.source !== frame.contentWindow) return;
        var d = ev.data;
        if (!d || d.aleph !== "conectores") return;
        abrir("credencial");
      });

      // Para que la anfitriona (o una vara) pueda abrirlo sin simular un click.
      window.AlephConectoresDelEspacio.abrir = abrir;
      window.AlephConectoresDelEspacio.cerrar = cerrar;
      panel.addEventListener("click", function (ev) {
        if (ev.target.closest("[data-cerrar]")) cerrar();
      });
      document.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape" && !panel.hidden) cerrar();
      });
    },
  };
})();
