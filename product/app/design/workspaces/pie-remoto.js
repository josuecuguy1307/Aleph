/* pie-remoto.js — LA IDENTIDAD DE ALEPH, PARA LA FILA DE CUENTA DEL PIE. UNA PARA LAS SEIS.
 * [rediseño · integración y cierre]
 *
 * QUÉ RESUELVE. El diseño cierra la barra de los seis con dos filas —`⚙ Settings` y
 * `○ <Nombre> · <Rol>`— y la segunda no la puede pintar el stack: la identidad que él conoce
 * es la SUYA, no la que el usuario tiene en Aleph. Se la pide a esta cáscara, que sí la sabe.
 *
 * ⚠️ ACÁ VIVÍA TAMBIÉN UN CENSO DEL PIE Y SE FUE. La sesión de integración lo escribió para
 * darle disparador a `Ir a…` y `Conectores`, que se quedaron sin riel; se vio en pantalla y el
 * dueño lo cortó. `Aleph Settings.dc.html` (artboard 13a) y el 38a de Legal cierran la barra
 * con esas dos filas y nada más. Los once destinos de la casa —Conectores entre ellos— se
 * alcanzan por `‹ Inicio`. Se saca el contestador junto con el emisor: un listener sin quien
 * lo dispare es exactamente el defecto que esta sesión encontró en Finanzas y en Diseño, y
 * dejarlo acá sería repetirlo del otro lado.
 *
 * ⚠️ LO QUE LLEGA DEL IFRAME ES UN DATO, NO UNA ORDEN. El candado del emisor es el de la
 * fase 5 y no se afloja: `event.source` tiene que ser EXACTAMENTE el `contentWindow` de
 * nuestro `#ws-frame`. Un `origin` suelto no alcanza — cualquier ventana puede postear a
 * ésta. Y lo único que se contesta es un rótulo: ni el id ni el token cruzan.
 */
(function () {
  "use strict";

  function tr(k, fb) { try { var s = window.t ? window.t(k) : null; return (s && s !== k) ? s : fb; } catch (e) { return fb; } }

  /* La sesión de Aleph, leída igual que la leen las seis páginas. */
  function usuario() {
    try {
      var u = window.AlephSession && window.AlephSession.get ? window.AlephSession.get() : null;
      if (!u) { var raw = localStorage.getItem("puppet_user") || sessionStorage.getItem("puppet_user"); u = raw ? JSON.parse(raw) : null; }
      return u || null;
    } catch (e) { return null; }
  }

  window.AlephPieRemoto = {
    montar: function () {
      var frame = document.getElementById("ws-frame");
      if (!frame) return false;

      window.addEventListener("message", function (event) {
        if (!frame.contentWindow || event.source !== frame.contentWindow) return;
        var d = event.data || {};

        /* LA CUENTA DE LA FILA DEL PIE. Cada stack tiene su propio menú de cuenta y está
         * apagado al embeber a propósito: la identidad que él conoce es la SUYA, y pintarla
         * sería mostrarle al usuario una cuenta que no es la que tiene en la casa. La de
         * Aleph la sabe esta cáscara. Se contesta con lo que hay; sin sesión no se contesta y
         * del otro lado la fila simplemente no se dibuja — un nombre inventado sería peor que
         * el hueco. */
        if (d.type === "aleph-identidad?") {
          var u = usuario();
          if (!u) return;
          var mail = "";
          try { mail = (u.email && String(u.email).indexOf("device::") !== 0) ? String(u.email) : ""; } catch (e) {}
          var nombre = u.name || (mail ? mail.split("@")[0] : "");
          var linea = mail;
          /* La cuenta local anónima dice lo mismo que dice Settings para ella, no un mail
           * `device::…` que no es la dirección de nadie. */
          try {
            if (window.AlephSession && window.AlephSession.isAnon && window.AlephSession.isAnon(u)) {
              nombre = tr("set.local.name", "Esta computadora");
              linea = tr("set.local.line", "Cuenta local");
            }
          } catch (e) {}
          if (!nombre) return;
          try { frame.contentWindow.postMessage({ type: "aleph-identidad", nombre: nombre, linea: linea }, "*"); } catch (e) {}
          return;
        }

      });
      return true;
    },
  };
})();
