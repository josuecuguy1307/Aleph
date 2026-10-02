// aleph-theme-preload.js — EL ESQUEMA DE LA CASA, ANTES DEL PRIMER PINTADO.
//
// [Gate 4 · Fase 6 · Legal · inmersión 3.8]
//
// La casa no le manda colores al lienzo: le manda UNA PALABRA por query string
// (`?aleph_scheme=dark|light`, que arma `product/app/design/workspaces/legal.html` con el
// tema YA RESUELTO — jamás «auto»). El lienzo la resuelve con SU propia paleta. El criterio
// de éxito no es «mismo hex» sino «mismo lado de la línea claro/oscuro»; es el precedente
// medido de Ciencia, donde casa `rgb(11,11,12)` convive con lienzo `rgb(19,16,16)`.
//
// Corre ANTES del bundle para que no haya un parpadeo claro sobre una casa oscura.
//
// SE PERSISTE, y eso es load-bearing: la casa pone el `src` del iframe UNA SOLA VEZ, y en
// cuanto el router del stack navega a un matter se pierde el `search`. Sin persistir, el
// tema volvería a claro en la primera navegación.
(function () {
  try {
    var deLaCasa = new URLSearchParams(location.search).get("aleph_scheme");
    if (deLaCasa === "dark" || deLaCasa === "light") {
      localStorage.setItem("aleph-color-scheme", deLaCasa);
    }
    var elegido = localStorage.getItem("aleph-color-scheme");
    if (elegido === "dark" || elegido === "light") {
      document.documentElement.dataset.alephScheme = elegido;
    }
  } catch (_) {
    // Sin storage (modo privado, iframe con cookies bloqueadas) el lienzo se queda con su
    // esquema claro de siempre. Degradar a lo que ya funcionaba, jamás romper la pantalla.
  }
})();
