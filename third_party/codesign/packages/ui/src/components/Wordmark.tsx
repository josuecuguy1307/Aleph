/**
 * Aleph Diseño wordmark.
 * Logo icon + word, optional pre-alpha pill.
 * Use anywhere the app needs to identify itself.
 */


interface WordmarkProps {
  badge?: string;
  size?: 'sm' | 'md' | 'titlebar';
}

export function Wordmark({ badge, size = 'md' }: WordmarkProps) {
  const metrics = {
    sm: { markPx: 36, fontSize: '16px', badgeSize: '8px', gap: '8px', badgeMarginTop: '4px' },
    titlebar: {
      markPx: 56,
      fontSize: '24px',
      badgeSize: '9px',
      gap: '10px',
      badgeMarginTop: '6px',
    },
    md: { markPx: 88, fontSize: '30px', badgeSize: '10px', gap: '16px', badgeMarginTop: '10px' },
  }[size];
  return (
    <span className="inline-flex items-center leading-none" style={{ gap: metrics.gap }}>
      {/* [Aleph] El glifo va en el ACENTO de la casa, no en el gris de apoyo. En este sistema
          el color es 90/8/2 y la marca es uno de los lugares donde el 8% aparece a propósito
          — como el punto de la nav o el halo de la mascota. Estaba en `--color-text-secondary`,
          que ahora es el mismo gris con el que se rotula lo secundario: la marca se perdía
          entre los metadatos. */}
      <span aria-hidden style={{ fontSize: metrics.markPx, lineHeight: 1, color: 'var(--color-accent)' }}>✦</span>
      <span className="flex flex-col">
        <span
          className="leading-none"
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: metrics.fontSize,
            fontWeight: 600,
            letterSpacing: '0',
          }}
        >
          {/* «Aleph» en la tinta y «Diseño» en el acento: la casa primero, el oficio en color.
              Es el mismo reparto que hace la nav de Aleph, donde el destino activo es lo
              único teñido. */}
          <span style={{ color: 'var(--color-text-primary)' }}>Aleph </span>
          <span style={{ color: 'var(--color-accent)' }}>Diseño</span>
        </span>
        {badge ? (
          <span
            className="font-medium uppercase leading-none"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: metrics.badgeSize,
              letterSpacing: '0.12em',
              color: 'var(--color-text-muted)',
              marginTop: metrics.badgeMarginTop,
            }}
          >
            {badge}
          </span>
        ) : null}
      </span>
    </span>
  );
}
