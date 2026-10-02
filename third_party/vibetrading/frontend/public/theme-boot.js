(() => {
  const root = document.documentElement;
  let savedTheme = null;

  // [Gate 4 · F6 · Finanzas · inmersión 3.8] EL ESQUEMA DE LA CASA CRUZA EL BORDE DE ORIGEN.
  //
  // La casa no le manda colores a la mesa: le manda UNA PALABRA por query string
  // (?aleph_scheme=dark|light, que arma product/app/design/workspaces/finanzas.html con el
  // tema YA RESUELTO — jamás «auto»), y la mesa la resuelve con SU propia paleta. El criterio
  // no es «mismo hex» sino caer del MISMO LADO de la línea claro/oscuro.
  //
  // Sin esto la mesa decidía por el sistema operativo y podía abrir clara dentro de una casa
  // que por default es oscura. Se PERSISTE en la clave que el stack ya usaba, y eso es
  // load-bearing: la casa pone el src del iframe UNA sola vez, y en cuanto el router navega
  // se pierde el search.
  try {
    const deLaCasa = new URLSearchParams(window.location.search).get("aleph_scheme");
    if (deLaCasa === "dark" || deLaCasa === "light") {
      window.localStorage.setItem("qa-theme", deLaCasa);
    }
  } catch {
    // Sin storage la mesa se queda con lo que ya hacía: seguir al sistema.
  }

  try {
    savedTheme = window.localStorage.getItem("qa-theme");
  } catch {
    // Storage can be unavailable in restricted iframes and WebViews.
  }

  let prefersDark = false;
  if (savedTheme !== "dark" && savedTheme !== "light" && typeof window.matchMedia === "function") {
    try {
      prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    } catch {
      // Fall back to light when the media-query API is present but unusable.
    }
  }

  const dark = savedTheme === "dark" || (savedTheme !== "light" && prefersDark);
  root.classList.toggle("dark", dark);
  root.style.colorScheme = dark ? "dark" : "light";
})();
