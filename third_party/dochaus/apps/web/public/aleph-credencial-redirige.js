// aleph-credencial-redirige.js — LA PUERTA DE CREDENCIAL, CONVERTIDA EN REDIRECCIÓN.
//
// [Convergencia · superficie 3 · fase 5 · decisión del dueño 2026-08-18]
//
// LA DECISIÓN: el usuario NO pone una llave propia adentro de un workspace. El vault de la
// casa es el destino único. Una llave pegada acá adentro quedaría fuera del vault y fuera
// del ledger de gasto — invisible para el dueño y para Aleph.
//
// LO QUE **NO** SE HACE: borrar la entrada. El usuario ya aprendió que la llave de búsqueda
// se pone en Settings → Research, y sacarla de ahí lo deja buscando. La entrada se queda
// donde está y se vuelve una puerta a Conectores, al espacio que corresponde. Es la misma
// forma que se eligió para Ajustes: no se saca, se rotula.
//
// POR QUÉ NO SE EDITA EL COMPONENTE. `Settings.tsx:60` es de upstream. Este archivo es de
// Aleph y vive al lado del suyo —igual que `aleph-theme-preload.js`—, así que un merge de
// upstream no lo pisa ni hay que reaplicar un parche.
//
// POR QUÉ LA REGLA ES POR TIPO Y NO POR TEXTO. Medido: `input[type="password"]` aparece
// UNA sola vez en todo `apps/web/src` (la Exa key), y no hay ningún otro campo de llave.
// Enganchar por el texto «Exa discovery key» se rompería con un cambio de copy de upstream;
// enganchar por el tipo sigue funcionando, y además **atrapa la próxima puerta que agreguen
// sin que nadie se acuerde de esta decisión**. Fail-closed en la dirección correcta.
//
// EL ORDEN IMPORTA: el listener en CAPTURA es lo que protege. El botón es la cortesía. Si
// React re-renderiza y se lleva el botón, la puerta sigue cerrada; el observer lo repone.
(function () {
  "use strict";

  // Sin padre no hay a dónde redirigir. Cerrar una puerta sin ofrecer la otra es un callejón
  // sin salida, y no protege nada real: quien corre este árbol suelto es un dev con la
  // fuente en la mano. Adentro de Aleph —el único caso del producto— siempre hay padre.
  if (window.parent === window) return;

  var COPY = "Tu llave se guarda en Aleph";
  var SUB  = "Vale para todos los espacios que la usan, y queda en tu registro de gasto.";

  function pedirConectores() {
    // El `ws` NO se manda: la casa sabe en qué espacio está este iframe. Si lo mandáramos,
    // este archivo podría pedir abrir los conectores de otro espacio.
    try { window.parent.postMessage({ aleph: "conectores" }, "*"); } catch (e) {}
  }

  // ── LA PROTECCIÓN: capturar antes de que el campo reciba nada ────────────────────────
  ["pointerdown", "mousedown", "focusin", "keydown"].forEach(function (tipo) {
    document.addEventListener(tipo, function (ev) {
      var t = ev.target;
      if (!t || t.tagName !== "INPUT" || t.type !== "password") return;
      ev.preventDefault();
      ev.stopPropagation();
      try { t.blur(); } catch (e) {}
      pedirConectores();
    }, true);   // ← CAPTURA: corre antes que cualquier handler de React
  });

  // ── LA CORTESÍA: que se vea que es una puerta, no un campo roto ──────────────────────
  function vestir(input) {
    if (input.dataset.alephRedirige === "1") return;
    input.dataset.alephRedirige = "1";
    input.readOnly = true;
    input.value = "";
    input.placeholder = COPY;
    input.style.cursor = "pointer";

    var nota = document.createElement("button");
    nota.type = "button";
    nota.className = "aleph-credencial-cta";
    nota.textContent = "Ponerla en Aleph →";
    nota.setAttribute("style",
      "display:block;margin-top:6px;border:0;border-radius:8px;padding:7px 12px;" +
      "font:400 12.5px/1.4 inherit;cursor:pointer;background:rgba(139,108,240,.16);color:inherit");
    nota.addEventListener("click", function (ev) { ev.preventDefault(); pedirConectores(); });

    var pie = document.createElement("small");
    pie.className = "aleph-credencial-sub";
    pie.textContent = SUB;
    pie.setAttribute("style", "display:block;margin-top:5px;opacity:.7;font-size:11.5px");

    var donde = input.parentElement || input;
    donde.appendChild(nota);
    donde.appendChild(pie);
  }

  function barrer() {
    var campos = document.querySelectorAll('input[type="password"]');
    for (var i = 0; i < campos.length; i++) vestir(campos[i]);
  }

  // React monta Settings cuando el usuario navega, y lo re-renderiza al guardar: un barrido
  // único no alcanza y por eso hay observer. Es barato — sólo mira nodos agregados.
  var obs = new MutationObserver(barrer);
  function arrancar() {
    barrer();
    obs.observe(document.documentElement, { childList: true, subtree: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", arrancar);
  else arrancar();
})();
