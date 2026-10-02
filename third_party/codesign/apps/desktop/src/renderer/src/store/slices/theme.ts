export type Theme = 'light' | 'dark';

export const THEME_STORAGE_KEY = 'open-codesign:theme';

/**
 * [Aleph · 2026-08-11] EL ESQUEMA LO MANDA LA CASA.
 *
 * Diseño corre dentro de Aleph, en una webview. La casa no le manda colores: le manda UNA
 * PALABRA por query string —`?aleph_scheme=dark|light`, que arma
 * `product/app/design/workspaces/diseno.html` con el tema YA RESUELTO, jamás «auto»— y el
 * lienzo la resuelve con su propia hoja. Es el mismo puente que usa Legal
 * (`apps/web/dist/aleph-theme-preload.js`), y ahora que la paleta de este workspace ES la de
 * la casa, además caen en el mismo hex.
 *
 * SE PERSISTE, y eso es load-bearing: la casa pone el `src` del iframe UNA SOLA VEZ, y en
 * cuanto el router del stack navega a un diseño se pierde el `search`. Sin persistir, el
 * tema volvería a claro en la primera navegación.
 *
 * Gana sobre lo guardado a propósito: si el usuario cambió el tema DE ALEPH, esa es la
 * decisión más reciente. Dentro del workspace el interruptor propio sigue funcionando y
 * pisa esto hasta la próxima entrada, que es lo que hace Legal.
 */
export function readInitialTheme(): Theme {
  if (typeof window === 'undefined') return 'light';
  try {
    const deLaCasa = new URLSearchParams(window.location.search).get('aleph_scheme');
    if (deLaCasa === 'dark' || deLaCasa === 'light') {
      window.localStorage.setItem(THEME_STORAGE_KEY, deLaCasa);
      return deLaCasa;
    }
  } catch {
    // Sin storage (modo privado, iframe con cookies bloqueadas) se sigue de largo: el
    // esquema de la casa se pierde, pero la pantalla no se rompe.
  }
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
  } catch {
    // localStorage unavailable
  }
  return 'light';
}

export function applyThemeClass(theme: Theme): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  if (theme === 'dark') root.classList.add('dark');
  else root.classList.remove('dark');
}

export function persistTheme(theme: Theme): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // localStorage unavailable
  }
}
