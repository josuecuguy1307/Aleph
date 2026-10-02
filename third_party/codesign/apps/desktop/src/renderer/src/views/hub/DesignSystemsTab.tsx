import { useT } from '@open-codesign/i18n';

export function DesignSystemsTab() {
  const t = useT();
  return (
    <section className="max-w-[var(--size-prose-narrow)] space-y-[var(--space-2)]">
      {/* [rediseño · fase DISEÑO · pieza 12, regla 3] «Un solo título, 44px peso 300» — y para
          que la regla pueda aplicarse, el título de la pantalla tiene que SER el título de la
          pantalla. Era un `<h2>` sin `<h1>` arriba: la piel apunta a `main h1`, que es donde
          vive la regla de los ocho espacios, y esta pantalla quedaba afuera por semántica.
          Las clases no se tocan, así que sin frame se ve exactamente igual que hoy —Tailwind
          resetea los tamaños de encabezado— y lo único que cambia es el nivel. */}
      <h1 className="display text-[var(--text-lg)] tracking-[var(--tracking-heading)] text-[var(--color-text-primary)] m-0">
        {t('hub.designSystems.title')}
      </h1>
      <p className="text-[var(--text-sm)] text-[var(--color-text-muted)] leading-[var(--leading-body)]">
        {t('hub.designSystems.comingSoon')}
      </p>
    </section>
  );
}
