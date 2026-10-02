/**
 * ThemeScript - Initializes theme from localStorage before React hydration
 * This prevents the flash of wrong theme on page load.
 *
 * Must be a Server Component: in Next.js / React 19, <script> tags rendered
 * by Client Components are inert on the client. Rendering it from the server
 * inlines the snippet into the SSR HTML so the browser executes it before
 * hydration.
 */
export default function ThemeScript() {
  const themeScript = `
    (function() {
      try {
        // [Gate 4 · F6 · Educación · inmersión 3.8] EL ESQUEMA DE LA CASA CRUZA EL BORDE.
        // La casa no le manda colores al lienzo: le manda UNA PALABRA por query string
        // (?aleph_scheme=dark|light, que arma product/app/design/workspaces/educacion.html
        // con el tema YA RESUELTO — jamás «auto»), y el lienzo la resuelve con SU propia
        // paleta. El criterio no es «mismo hex» sino caer del MISMO LADO de la línea
        // claro/oscuro. Sin esto el tutor elegía por su cuenta según el sistema operativo, y
        // podía abrir claro dentro de una casa oscura.
        //
        // Se PERSISTE en la clave que el stack ya usaba, y eso es load-bearing: la casa pone
        // el src del iframe UNA sola vez, y en cuanto el router del tutor navega se pierde
        // el search. Sin persistir, el tema se perdería en la primera navegación.
        const deLaCasa = new URLSearchParams(location.search).get('aleph_scheme');
        if (deLaCasa === 'dark' || deLaCasa === 'light') {
          localStorage.setItem('deeptutor-theme', deLaCasa === 'dark' ? 'dark' : 'snow');
        }
        const stored = localStorage.getItem('deeptutor-theme');

        document.documentElement.classList.remove('dark', 'theme-glass', 'theme-snow');

        if (stored === 'dark') {
          document.documentElement.classList.add('dark');
        } else if (stored === 'glass') {
          document.documentElement.classList.add('dark', 'theme-glass');
        } else if (stored === 'snow') {
          document.documentElement.classList.add('theme-snow');
        } else if (stored === 'light') {
          // already clean
        } else {
          // No stored preference: Default (snow) for light systems,
          // Dark for prefers-color-scheme: dark.
          if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
            document.documentElement.classList.add('dark');
            localStorage.setItem('deeptutor-theme', 'dark');
          } else {
            document.documentElement.classList.add('theme-snow');
            localStorage.setItem('deeptutor-theme', 'snow');
          }
        }
      } catch (e) {
        /* localStorage may be disabled */
      }
    })();
  `;

  return (
    <script
      dangerouslySetInnerHTML={{ __html: themeScript }}
      suppressHydrationWarning
    />
  );
}
