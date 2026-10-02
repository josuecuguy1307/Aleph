;(function () {
  // ── [Aleph · Gate 4 · F4 · O3 · inmersión nivel-2] EL TEMA CRUZA EL BORDE DE ORIGEN ──
  //
  // Esta UI se sirve desde `127.0.0.1:<puerto>`, que es OTRO ORIGEN que el de la casa. Su
  // `localStorage` es otro, así que este archivo NO PODÍA ENTERARSE del tema de Aleph: leía
  // `openscience-color-scheme`, no lo encontraba, caía en `"system"` y seguía al sistema
  // operativo. Y Aleph es OSCURO por defecto, no `auto` (`product/app/design/theme.js:13`).
  //
  // Resultado, medido con una captura: marco oscuro de la casa, lienzo claro del stack. Dos
  // pantallas pegadas en vez de una superficie. Ésa era la «pantalla-sobre-pantalla» de la
  // caminata, y la causa no era el layout: era el tema.
  //
  // La casa manda el suyo en la URL del `<iframe>` y acá se PERSISTE, para que lo vean tanto
  // este preload (que evita el parpadeo) como el contexto de tema en runtime, que lee las
  // mismas claves. Si el parámetro no viene —el stack corriendo suelto— no se toca nada.
  try {
    var q = new URLSearchParams(location.search)
    var deLaCasa = q.get("aleph_scheme")
    if (deLaCasa === "dark" || deLaCasa === "light") {
      localStorage.setItem("openscience-color-scheme", deLaCasa)
      if (!localStorage.getItem("openscience-theme-id")) {
        // Sin un tema elegido, este preload salía por la puerta de atrás (el `return` de
        // abajo) y el `data-color-scheme` no se aplicaba nunca. Se fija el tema base.
        //
        // [Aleph · 2026-08-11] Y ESE TEMA BASE ES EL DE ALEPH. Acá se sembraba
        // `"openscience-1"` —la piel del producto de origen—: en un arranque limpio el
        // primer frame se pintaba con la marca ajena y recién después `ui/src/theme/
        // context.tsx` lo corregía a `"aleph"` en runtime. Medido con el `localStorage`
        // borrado: el estado final quedaba bien, el primer pintado no. Si la vista viene
        // de la casa, el tema de arranque es el de la casa. De paso deja de aplicar el
        // `return` de más abajo, y el CSS cacheado del tema sí se usa para evitar el
        // parpadeo, que es justamente para lo que existe este archivo.
        localStorage.setItem("openscience-theme-id", "aleph")
      }
    }
  } catch (e) {
    /* sin localStorage el tema no se puede fijar; la UI igual pinta */
  }

  var themeId = localStorage.getItem("openscience-theme-id")
  if (!themeId) return

  var scheme = localStorage.getItem("openscience-color-scheme") || "system"
  var isDark = scheme === "dark" || (scheme === "system" && matchMedia("(prefers-color-scheme: dark)").matches)
  var mode = isDark ? "dark" : "light"

  document.documentElement.dataset.theme = themeId
  document.documentElement.dataset.colorScheme = mode

  if (themeId === "openscience-1") return

  // Keep in lockstep with STORAGE_KEYS.THEME_CSS_* in ui/src/theme/context.tsx —
  // the cache is keyed by mode only, not by theme id.
  var css = localStorage.getItem("openscience-theme-css-" + mode)
  if (css) {
    var style = document.createElement("style")
    style.id = "openscience-theme-preload"
    style.textContent =
      ":root{color-scheme:" +
      mode +
      ";--text-mix-blend-mode:" +
      (isDark ? "plus-lighter" : "multiply") +
      ";" +
      css +
      "}"
    document.head.appendChild(style)
  }
})()
